"""The publication fee: invoices, payments, refunds and waivers (§8 of the architecture).

Rules this module keeps:
- An invoice is issued only when a manuscript is accepted, in the same transaction as the decision.
- A payment counts only when the provider says so: its signed notification, or its API when the payer
  returns. Never the payer's browser alone.
- Every provider notification is stored under a unique (provider, event id): a repeated delivery
  changes nothing.
- The editors never see invoices or waiver requests; after acceptance they see only whether the fee
  is settled (see ``fee_settled``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import escape_like, utcnow
from app.core.errors import Conflict, FieldError, NotFound, ServiceUnavailable, ValidationFailed
from app.core.jobs import enqueue
from app.modules.audit.service import AuditService
from app.modules.identity.models import User
from app.modules.journals.email_templates import EmailTemplateService
from app.modules.journals.models import Journal
from app.modules.journals.payment_settings import PaymentSettings, payment_settings
from app.modules.journals.permissions import Role
from app.modules.journals.service import JournalService
from app.modules.notifications.service import queue_email
from app.modules.payments import emails
from app.modules.payments.models import (
    SETTLED,
    Invoice,
    InvoiceCounter,
    InvoiceReminder,
    InvoiceStatus,
    Payment,
    PaymentStatus,
    ProviderEvent,
    Refund,
    RefundStatus,
    WaiverRequest,
    WaiverStatus,
)
from app.modules.payments.money import format_money, totals
from app.modules.payments.providers.base import (
    CheckoutRequest,
    ProviderError,
    ProviderNotice,
    ProviderStatus,
)
from app.modules.payments.providers.registry import (
    BANK_TRANSFER,
    METHOD_LABELS,
    provider_for_method,
    providers,
)
from app.modules.submissions.mailer import Mailer
from app.modules.submissions.models import Stage, Submission, SubmissionStatus

logger = logging.getLogger(__name__)

CAPTURE = "payments.capture"
PROCESS_REFUND = "payments.process_refund"
ACCEPTED_STAGES = frozenset({Stage.COPYEDITING, Stage.PRODUCTION})
STUCK_AFTER = timedelta(days=2)


def today() -> date:
    return utcnow().date()


class PaymentService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.journals = JournalService(db, settings)
        self.mailer = Mailer(db, settings)
        self.templates = EmailTemplateService(db)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ where things stand

    @staticmethod
    def accepted(submission: Submission) -> bool:
        return submission.stage in ACCEPTED_STAGES or submission.status in (
            SubmissionStatus.SCHEDULED,
            SubmissionStatus.PUBLISHED,
        )

    @staticmethod
    def fee_required(journal: Journal, submission: Submission) -> bool:
        config = payment_settings(journal)
        return config.enabled and config.fee_for(submission.section_id) > 0

    async def invoices(self, submission_id: int) -> Sequence[Invoice]:
        return (
            await self.db.scalars(
                select(Invoice).where(Invoice.submission_id == submission_id).order_by(Invoice.id)
            )
        ).all()

    async def active_invoice(self, submission_id: int) -> Invoice | None:
        return await self.db.scalar(
            select(Invoice).where(
                Invoice.submission_id == submission_id, Invoice.status != InvoiceStatus.VOID
            )
        )

    async def fee_settled(self, journal: Journal, submission: Submission) -> bool | None:
        """For the editors, after acceptance: may the article be published? None before acceptance."""
        if not self.accepted(submission):
            return None
        invoice = await self.active_invoice(submission.id)
        if invoice is not None:
            return invoice.status in SETTLED
        return not self.fee_required(journal, submission)

    async def get_invoice(self, journal: Journal, invoice_id: int) -> Invoice:
        invoice = await self.db.scalar(
            select(Invoice).where(Invoice.id == invoice_id, Invoice.journal_id == journal.id)
        )
        if invoice is None:
            raise NotFound("Invoice not found.")
        return invoice

    async def get_payment(self, journal: Journal, payment_id: int) -> tuple[Payment, Invoice]:
        payment = await self.db.get(Payment, payment_id)
        if payment is None:
            raise NotFound("Payment not found.")
        return payment, await self.get_invoice(journal, payment.invoice_id)

    # ------------------------------------------------------------------ issuing

    async def issue_for_accepted(
        self, journal: Journal, submission: Submission, actor: User
    ) -> Invoice | None:
        """Called with the "accept" decision, in its transaction."""
        if not self.fee_required(journal, submission):
            return None
        existing = await self.active_invoice(submission.id)
        if existing is not None:
            return existing
        return await self._issue(journal, submission, actor)

    async def reissue(self, journal: Journal, submission: Submission, actor: User) -> Invoice:
        """A new invoice after a void one (finance), e.g. once a wrong amount was corrected."""
        if not self.accepted(submission):
            raise Conflict("Invoices are issued only for accepted manuscripts.", code="not_accepted")
        if await self.active_invoice(submission.id) is not None:
            raise Conflict("This manuscript already has an invoice. Void it first.", code="invoice_exists")
        if not self.fee_required(journal, submission):
            raise Conflict("No publication fee is set for this section.", code="no_fee")
        return await self._issue(journal, submission, actor)

    async def _approved_waiver(self, submission_id: int) -> int:
        percent = await self.db.scalar(
            select(WaiverRequest.approved_percent)
            .where(
                WaiverRequest.submission_id == submission_id, WaiverRequest.status == WaiverStatus.APPROVED
            )
            .order_by(WaiverRequest.decided_at.desc())
            .limit(1)
        )
        return int(percent or 0)

    async def _issue(self, journal: Journal, submission: Submission, actor: User) -> Invoice:
        config = payment_settings(journal)
        percent = await self._approved_waiver(submission.id)
        amounts = totals(
            config.fee_for(submission.section_id), discount_percent=percent, vat_percent=config.vat_percent
        )
        now = utcnow()
        submitter = submission.submitter
        waived = amounts.total <= 0
        invoice = Invoice(
            journal_id=journal.id,
            submission_id=submission.id,
            number=await self._next_number(journal.id, now.year),
            status=InvoiceStatus.WAIVED if waived else InvoiceStatus.ISSUED,
            currency=config.currency,
            amount=amounts.amount,
            discount=amounts.discount,
            discount_percent=percent,
            vat_percent=config.vat_percent,
            tax=amounts.tax,
            total=amounts.total,
            refunded=Decimal("0"),
            recipient_id=submitter.id,
            payer_name=submitter.full_name,
            payer_email=submitter.email,
            payer_organization=submitter.affiliation,
            description=f"Article publication fee: {submission.number} “{submission.publication.title}”"[
                :500
            ],
            due_date=now.date() + timedelta(days=config.due_days),
            issued_at=now,
            waived_at=now if waived else None,
        )
        invoice.payments = []
        self.db.add(invoice)
        await self.db.flush()
        if not waived:
            await self._mail_payer(journal, submission, invoice, emails.ISSUED.key)
        await self.audit.record(
            "invoice.issued",
            "invoice",
            invoice.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"number": invoice.number, "total": str(invoice.total), "currency": invoice.currency},
        )
        return invoice

    async def _next_number(self, journal_id: int, year: int) -> str:
        statement = (
            insert(InvoiceCounter)
            .values(journal_id=journal_id, year=year, last_value=1)
            .on_conflict_do_update(
                index_elements=[InvoiceCounter.journal_id, InvoiceCounter.year],
                set_={"last_value": InvoiceCounter.last_value + 1},
            )
            .returning(InvoiceCounter.last_value)
        )
        value = (await self.db.execute(statement)).scalar_one()
        return f"INV-{year}-{value:04d}"

    # ------------------------------------------------------------------ e-mails

    def invoice_url(self, submission_id: int) -> str:
        return f"{self.settings.workspace_url}/submissions/{submission_id}?tab=fee"

    def _invoice_values(self, invoice: Invoice) -> dict[str, str]:
        return {
            "invoiceNumber": invoice.number,
            "invoiceTotal": format_money(invoice.total, invoice.currency),
            "dueDate": invoice.due_date.strftime("%d %B %Y"),
            "invoiceUrl": self.invoice_url(invoice.submission_id),
        }

    async def _mail_payer(
        self, journal: Journal, submission: Submission, invoice: Invoice, key: str, **extra: str
    ) -> None:
        # Not in the manuscript's e-mail log: the editors read it (§8.5).
        await self.mailer.send(
            journal,
            key,
            submission,
            to_name=invoice.payer_name,
            to_email=invoice.payer_email,
            values={**self._invoice_values(invoice), **extra},
            log=False,
        )

    async def finance_people(self, journal: Journal) -> list[User]:
        people = list(await self.journals.users_with_role(journal.id, Role.FINANCE_MANAGER))
        return people or list(await self.journals.users_with_role(journal.id, Role.ADMIN))

    async def _mail_finance(self, journal: Journal, key: str, values: Mapping[str, str]) -> None:
        for person in await self.finance_people(journal):
            rendered = await self.templates.render(
                journal,
                key,
                recipient_name=person.full_name,
                values={"financeUrl": f"{self.settings.workspace_url}/finance", **values},
            )
            await queue_email(self.db, to=person.email, subject=rendered.subject, text=rendered.body)

    async def _submission(self, submission_id: int) -> Submission:
        submission = await self.db.get(Submission, submission_id)
        if submission is None:
            raise NotFound("Submission not found.")
        return submission

    # ------------------------------------------------------------------ the invoice

    async def update_payer(self, invoice: Invoice, values: Mapping[str, str], actor: User) -> Invoice:
        if invoice.status != InvoiceStatus.ISSUED:
            raise Conflict("The payer can be changed only before the invoice is paid.", code="invoice_closed")
        for field, value in values.items():
            setattr(invoice, field, value)
        await self.db.flush()
        await self.audit.record(
            "invoice.payer_changed", "invoice", invoice.id, actor_id=actor.id, journal_id=invoice.journal_id
        )
        return invoice

    async def void(self, invoice: Invoice, reason: str, actor: User) -> Invoice:
        if invoice.status != InvoiceStatus.ISSUED:
            raise Conflict("Only unpaid invoices can be voided.", code="invoice_closed")
        if any(p.status == PaymentStatus.SUCCEEDED for p in invoice.payments):
            raise Conflict(
                "Money has been received for this invoice: refund it instead.", code="invoice_has_payments"
            )
        invoice.status = InvoiceStatus.VOID
        invoice.voided_at = utcnow()
        invoice.void_reason = reason
        for payment in invoice.payments:
            if payment.status in (PaymentStatus.CREATED, PaymentStatus.PENDING):
                payment.status = PaymentStatus.CANCELLED
        await self.db.flush()
        await self.audit.record(
            "invoice.voided",
            "invoice",
            invoice.id,
            actor_id=actor.id,
            journal_id=invoice.journal_id,
            data={"reason": reason},
        )
        return invoice

    def methods(self, journal: Journal) -> list[tuple[str, str, bool, str]]:
        """(method, label, available, why not) for each method the journal switched on."""
        return self.methods_for(payment_settings(journal))

    def methods_for(self, config: PaymentSettings) -> list[tuple[str, str, bool, str]]:
        result = []
        for method, enabled in config.methods.model_dump().items():
            if not enabled:
                continue
            label = METHOD_LABELS[method]
            if method == BANK_TRANSFER:
                ready = bool(config.payee.iban)
                result.append(
                    (method, label, ready, "" if ready else "The journal's bank details are not set")
                )
                continue
            provider = provider_for_method(self.settings, method)
            if provider is None:
                why = (
                    "No card acquirer is connected yet"
                    if method == "card"
                    else f"{label} is not connected on the server"
                )
                result.append((method, label, False, why))
            elif provider.currencies is not None and config.currency not in provider.currencies:
                result.append((method, label, False, f"{label} does not accept {config.currency}"))
            else:
                result.append((method, label, True, ""))
        return result

    # ------------------------------------------------------------------ paying online

    async def start_checkout(self, journal: Journal, invoice: Invoice, method: str, actor: User) -> Payment:
        if invoice.status != InvoiceStatus.ISSUED:
            raise Conflict("This invoice is not waiting for payment.", code="invoice_closed")
        available = {m: (ok, why) for m, _, ok, why in self.methods(journal)}
        if method == BANK_TRANSFER or method not in available or not available[method][0]:
            reason = available.get(method, (False, "This payment method is not offered"))[1]
            raise Conflict(reason or "This payment method is not offered.", code="method_unavailable")
        provider = provider_for_method(self.settings, method)
        if provider is None:
            raise Conflict("This payment method is not offered.", code="method_unavailable")
        payment = Payment(
            invoice_id=invoice.id,
            provider=provider.name,
            status=PaymentStatus.CREATED,
            amount=invoice.total,
            currency=invoice.currency,
            created_by_id=actor.id,
        )
        payment.refunds = []
        self.db.add(payment)
        await self.db.flush()
        return_url = f"{self.settings.workspace_url}/payments/return?payment={payment.id}"
        try:
            checkout = await provider.create_checkout(
                CheckoutRequest(
                    payment_id=payment.id,
                    invoice_number=invoice.number,
                    amount=invoice.total,
                    currency=invoice.currency,
                    description=invoice.description,
                    payer_email=invoice.payer_email,
                    merchant_name=journal.name,
                    return_url=return_url,
                    cancel_url=f"{return_url}&cancelled=1",
                )
            )
        except ProviderError as exc:
            logger.warning("Checkout failed", extra={"provider": provider.name, "error": str(exc)})
            raise ServiceUnavailable(
                "The payment service is not responding. Try again in a few minutes or choose another method."
            ) from exc
        payment.provider_ref = checkout.provider_ref
        payment.checkout_url = checkout.redirect_url
        payment.status = PaymentStatus.PENDING
        await self.db.flush()
        await self.audit.record(
            "payment.started",
            "invoice",
            invoice.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"payment_id": payment.id, "provider": provider.name},
        )
        return payment

    async def confirm(self, journal: Journal, payment: Payment) -> Payment:
        """The payer came back from the provider's page: finish and check the payment with the provider."""
        if payment.status != PaymentStatus.PENDING or not payment.provider_ref:
            return payment
        provider = providers(self.settings).get(payment.provider)
        if provider is None:
            return payment
        try:
            status = await provider.complete(payment.provider_ref)
        except ProviderError:
            return payment  # the notification or reconciliation will settle it
        await self.apply_status(journal, payment, status)
        return payment

    async def apply_status(self, journal: Journal, payment: Payment, status: ProviderStatus) -> str:
        if status.kind == "succeeded":
            return await self._succeeded(journal, payment, status.amount, status.currency, status.capture_ref)
        if status.kind == "failed" and payment.status in (PaymentStatus.CREATED, PaymentStatus.PENDING):
            payment.status = PaymentStatus.FAILED
            payment.completed_at = utcnow()
            await self.db.flush()
            return "failed"
        return status.kind

    async def _succeeded(
        self,
        journal: Journal,
        payment: Payment,
        amount: Decimal | None,
        currency: str | None,
        capture_ref: str | None,
    ) -> str:
        if payment.status == PaymentStatus.SUCCEEDED:
            return "already recorded"
        if (amount is not None and amount != payment.amount) or (
            currency is not None and currency != payment.currency
        ):
            # Never mark an invoice paid for a different sum; a person must look at it.
            payment.failure_reason = (
                f"Provider reported {amount} {currency}, expected {payment.amount} {payment.currency}"
            )
            await self.db.flush()
            await self._mail_finance(
                journal,
                emails.ATTENTION.key,
                {"problems": f"Payment #{payment.id}: {payment.failure_reason}."},
            )
            return "amount mismatch"
        payment.status = PaymentStatus.SUCCEEDED
        payment.completed_at = utcnow()
        payment.capture_ref = capture_ref or payment.capture_ref
        payment.failure_reason = ""
        await self.db.flush()
        invoice = await self.db.get(Invoice, payment.invoice_id)
        if invoice is not None:
            await self._settle(journal, invoice)
        return "paid"

    async def _settle(self, journal: Journal, invoice: Invoice) -> None:
        await self.db.refresh(invoice, attribute_names=["payments"])
        received = sum(
            (p.amount for p in invoice.payments if p.status == PaymentStatus.SUCCEEDED), Decimal("0")
        )
        if invoice.status == InvoiceStatus.ISSUED and received >= invoice.total:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = utcnow()
            await self.db.flush()
            submission = await self._submission(invoice.submission_id)
            await self._mail_payer(
                journal,
                submission,
                invoice,
                emails.RECEIVED.key,
                paidAmount=format_money(received, invoice.currency),
            )
            await self.audit.record(
                "invoice.paid",
                "invoice",
                invoice.id,
                actor_id=None,
                journal_id=journal.id,
                data={"received": str(received)},
            )
        elif invoice.status in (InvoiceStatus.VOID, InvoiceStatus.WAIVED, InvoiceStatus.PAID):
            await self._mail_finance(
                journal,
                emails.ATTENTION.key,
                {
                    "problems": f"Money arrived for {invoice.number}, which is {invoice.status}. Refund it if needed."
                },
            )

    # ------------------------------------------------------------------ provider notifications

    async def handle_notification(
        self, journal: Journal, provider_name: str, headers: Mapping[str, str], body: bytes
    ) -> list[str]:
        provider = providers(self.settings).get(provider_name)
        if provider is None:
            raise NotFound("Unknown payment provider.")
        notices = await provider.parse_notification(headers, body)  # raises InvalidNotification
        results = []
        for notice in notices:
            event_id = await self.db.scalar(
                insert(ProviderEvent)
                .values(
                    provider=provider_name,
                    event_id=notice.event_id,
                    event_type=notice.event_type,
                    payload=dict(notice.payload),
                )
                .on_conflict_do_nothing()
                .returning(ProviderEvent.id)
            )
            if event_id is None:
                results.append("duplicate")
                continue
            result = await self._apply_notice(journal, provider_name, notice)
            await self.db.execute(
                update(ProviderEvent).where(ProviderEvent.id == event_id).values(result=result)
            )
            results.append(result)
        return results

    async def _find_payment(self, provider_name: str, notice: ProviderNotice) -> Payment | None:
        if notice.provider_ref:
            payment = await self.db.scalar(
                select(Payment).where(
                    Payment.provider == provider_name, Payment.provider_ref == notice.provider_ref
                )
            )
            if payment is not None:
                return payment
        if notice.payment_id is not None:
            payment = await self.db.get(Payment, notice.payment_id)
            if payment is not None and payment.provider == provider_name:
                return payment
        return None

    async def _apply_notice(self, journal: Journal, provider_name: str, notice: ProviderNotice) -> str:
        if notice.kind == "ignored":
            return "ignored"
        payment = await self._find_payment(provider_name, notice)
        if payment is None:
            logger.warning(
                "Notification for an unknown payment",
                extra={"provider": provider_name, "event": notice.event_id},
            )
            return "unknown payment"
        if notice.kind == "approved":
            await enqueue(self.db, CAPTURE, {"payment_id": payment.id})
            return "capture queued"
        if notice.kind == "succeeded":
            return await self._succeeded(journal, payment, notice.amount, notice.currency, notice.capture_ref)
        if notice.kind == "failed":
            return await self.apply_status(journal, payment, ProviderStatus(kind="failed"))
        return "noted"

    async def capture(self, payment_id: int) -> None:
        """Worker step: finish a payment the payer approved but did not come back from."""
        payment = await self.db.get(Payment, payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return
        invoice = await self.db.get(Invoice, payment.invoice_id)
        journal = await self.db.get(Journal, invoice.journal_id) if invoice else None
        if journal is not None:
            await self.confirm(journal, payment)

    # ------------------------------------------------------------------ bank transfers

    async def record_transfer(
        self,
        journal: Journal,
        invoice: Invoice,
        *,
        amount: Decimal,
        reference: str,
        paid_on: date,
        actor: User,
    ) -> Payment:
        if invoice.status != InvoiceStatus.ISSUED:
            raise Conflict("This invoice is not waiting for payment.", code="invoice_closed")
        if amount <= 0:
            raise ValidationFailed("Enter the amount received.", code="invalid_amount")
        payment = Payment(
            invoice_id=invoice.id,
            provider=BANK_TRANSFER,
            status=PaymentStatus.SUCCEEDED,
            amount=amount,
            currency=invoice.currency,
            reference=reference,
            created_by_id=actor.id,
            completed_at=datetime.combine(paid_on, time(12), tzinfo=utcnow().tzinfo),
        )
        payment.refunds = []
        self.db.add(payment)
        await self.db.flush()
        await self.audit.record(
            "payment.transfer_recorded",
            "invoice",
            invoice.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"amount": str(amount), "reference": reference},
        )
        await self._settle(journal, invoice)
        return payment

    # ------------------------------------------------------------------ refunds

    async def request_refund(
        self, journal: Journal, payment: Payment, *, amount: Decimal, reason: str, actor: User
    ) -> Refund:
        if payment.status != PaymentStatus.SUCCEEDED:
            raise Conflict("Only received payments can be refunded.", code="not_refundable")
        reserved = sum((r.amount for r in payment.refunds if r.status != RefundStatus.FAILED), Decimal("0"))
        if amount <= 0 or amount > payment.amount - reserved:
            raise ValidationFailed(
                "The refund cannot exceed what was paid and not yet refunded.",
                code="invalid_amount",
                errors=[FieldError(field="amount", message=f"At most {payment.amount - reserved}")],
            )
        refund = Refund(
            payment_id=payment.id,
            amount=amount,
            reason=reason,
            status=RefundStatus.PENDING,
            created_by_id=actor.id,
        )
        self.db.add(refund)
        await self.db.flush()
        await self.audit.record(
            "payment.refund_requested",
            "invoice",
            payment.invoice_id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"payment_id": payment.id, "amount": str(amount)},
        )
        if payment.provider == BANK_TRANSFER:
            # The money goes back by bank transfer outside the system; this records that it did.
            await self._refund_done(journal, refund, payment, provider_ref=None)
        else:
            await enqueue(self.db, PROCESS_REFUND, {"refund_id": refund.id})
        return refund

    async def process_refund(self, refund_id: int) -> None:
        """Worker step: ask the provider to refund. Provider errors are retried by the job queue."""
        refund = await self.db.get(Refund, refund_id)
        if refund is None or refund.status != RefundStatus.PENDING or refund.provider_ref:
            return
        payment = await self.db.get(Payment, refund.payment_id)
        provider = providers(self.settings).get(payment.provider) if payment else None
        if payment is None or provider is None:
            refund.status = RefundStatus.FAILED
            refund.failure_reason = "The payment provider is not connected on the server."
            return
        result = await provider.refund(
            refund_id=refund.id,
            provider_ref=payment.provider_ref or "",
            capture_ref=payment.capture_ref,
            amount=refund.amount,
            currency=payment.currency,
            reason=refund.reason,
        )
        invoice = await self.db.get(Invoice, payment.invoice_id)
        journal = await self.db.get(Journal, invoice.journal_id) if invoice else None
        if result.succeeded and journal is not None:
            await self._refund_done(journal, refund, payment, provider_ref=result.provider_ref)
        else:
            refund.provider_ref = result.provider_ref  # still processing; reconciliation follows it up

    async def give_up_refund(self, refund_id: int, error: str) -> None:
        refund = await self.db.get(Refund, refund_id)
        if refund is not None and refund.status == RefundStatus.PENDING:
            refund.status = RefundStatus.FAILED
            refund.failure_reason = error[:500]

    async def _refund_done(
        self, journal: Journal, refund: Refund, payment: Payment, *, provider_ref: str | None
    ) -> None:
        refund.status = RefundStatus.SUCCEEDED
        refund.provider_ref = provider_ref
        refund.completed_at = utcnow()
        payment.refunded += refund.amount
        invoice = await self.db.get(Invoice, payment.invoice_id)
        if invoice is None:
            return
        invoice.refunded += refund.amount
        received = sum(
            (p.amount for p in invoice.payments if p.status == PaymentStatus.SUCCEEDED), Decimal("0")
        )
        if invoice.refunded >= received and invoice.status == InvoiceStatus.PAID:
            invoice.status = InvoiceStatus.REFUNDED
        await self.db.flush()
        submission = await self._submission(invoice.submission_id)
        await self.mailer.send(
            journal,
            emails.REFUNDED.key,
            submission,
            to_name=invoice.payer_name,
            to_email=invoice.payer_email,
            values={
                "invoiceNumber": invoice.number,
                "refundAmount": format_money(refund.amount, payment.currency),
                "reason": refund.reason,
            },
            log=False,
        )
        await self.audit.record(
            "payment.refunded",
            "invoice",
            invoice.id,
            actor_id=None,
            journal_id=journal.id,
            data={"amount": str(refund.amount)},
        )

    # ------------------------------------------------------------------ waivers

    async def waivers_for(self, submission_id: int) -> Sequence[WaiverRequest]:
        return (
            await self.db.scalars(
                select(WaiverRequest)
                .where(WaiverRequest.submission_id == submission_id)
                .order_by(WaiverRequest.id)
            )
        ).all()

    async def can_request_waiver(self, journal: Journal, submission: Submission) -> bool:
        if not payment_settings(journal).enabled or submission.status in (
            SubmissionStatus.DECLINED,
            SubmissionStatus.WITHDRAWN,
            SubmissionStatus.DRAFT,
        ):
            return False
        if any(w.status == WaiverStatus.PENDING for w in await self.waivers_for(submission.id)):
            return False
        invoice = await self.active_invoice(submission.id)
        return invoice is None or invoice.status == InvoiceStatus.ISSUED

    async def request_waiver(
        self, journal: Journal, submission: Submission, *, percent: int, reason: str, actor: User
    ) -> WaiverRequest:
        if not await self.can_request_waiver(journal, submission):
            raise Conflict(
                "A waiver cannot be requested for this manuscript now.", code="waiver_not_possible"
            )
        waiver = WaiverRequest(
            submission_id=submission.id,
            requested_by_id=actor.id,
            percent=percent,
            reason=reason,
            status=WaiverStatus.PENDING,
        )
        self.db.add(waiver)
        await self.db.flush()
        await self._mail_finance(
            journal,
            emails.WAIVER_REQUESTED.key,
            {
                "submissionNumber": submission.number or "",
                "authorName": actor.full_name,
                "percent": str(percent),
                "reason": reason,
            },
        )
        await self.audit.record(
            "waiver.requested",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"percent": percent},
        )
        return waiver

    async def list_waivers(
        self, journal: Journal, *, status: str | None
    ) -> Sequence[tuple[WaiverRequest, Submission]]:
        query = (
            select(WaiverRequest, Submission)
            .join(Submission, Submission.id == WaiverRequest.submission_id)
            .where(Submission.journal_id == journal.id)
            .order_by(WaiverRequest.created_at.desc())
        )
        if status:
            query = query.where(WaiverRequest.status == status)
        return [(w, s) for w, s in (await self.db.execute(query)).all()]

    async def get_waiver(self, journal: Journal, waiver_id: int) -> tuple[WaiverRequest, Submission]:
        row = (
            await self.db.execute(
                select(WaiverRequest, Submission)
                .join(Submission, Submission.id == WaiverRequest.submission_id)
                .where(WaiverRequest.id == waiver_id, Submission.journal_id == journal.id)
            )
        ).first()
        if row is None:
            raise NotFound("Waiver request not found.")
        return row[0], row[1]

    async def decide_waiver(
        self,
        journal: Journal,
        waiver: WaiverRequest,
        submission: Submission,
        *,
        approve: bool,
        percent: int | None,
        note: str,
        actor: User,
    ) -> WaiverRequest:
        if waiver.status != WaiverStatus.PENDING:
            raise Conflict("This request has already been decided.", code="already_decided")
        waiver.status = WaiverStatus.APPROVED if approve else WaiverStatus.REJECTED
        waiver.approved_percent = (percent or waiver.percent) if approve else None
        waiver.decided_by_id = actor.id
        waiver.decided_at = utcnow()
        waiver.decision_note = note
        await self.db.flush()
        if approve:
            invoice = await self.active_invoice(submission.id)
            if invoice is not None and invoice.status == InvoiceStatus.ISSUED:
                await self._apply_discount(invoice, waiver.approved_percent or 0)
        decision = (
            f"Your request has been approved: {waiver.approved_percent}% of the publication fee for "
            f"“{submission.publication.title}” is waived."
            if approve
            else f"We are sorry, but your request for a fee waiver for “{submission.publication.title}” "
            "could not be approved."
        )
        requester = await self.db.get(User, waiver.requested_by_id) if waiver.requested_by_id else None
        target = requester or submission.submitter
        await self.mailer.send(
            journal,
            emails.WAIVER_DECISION.key,
            submission,
            to_name=target.full_name,
            to_email=target.email,
            values={"decisionText": decision, "note": note},
            log=False,
        )
        await self.audit.record(
            "waiver.decided",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"approved": approve, "percent": waiver.approved_percent},
        )
        return waiver

    async def _apply_discount(self, invoice: Invoice, percent: int) -> None:
        amounts = totals(invoice.amount, discount_percent=percent, vat_percent=invoice.vat_percent)
        invoice.discount_percent = percent
        invoice.discount = amounts.discount
        invoice.tax = amounts.tax
        invoice.total = amounts.total
        if amounts.total <= 0:
            invoice.status = InvoiceStatus.WAIVED
            invoice.waived_at = utcnow()
            for payment in invoice.payments:
                if payment.status in (PaymentStatus.CREATED, PaymentStatus.PENDING):
                    payment.status = PaymentStatus.CANCELLED
        await self.db.flush()

    # ------------------------------------------------------------------ periodic work

    async def send_reminders(self) -> int:
        """Unpaid invoices, at the configured days around the due date. Each reminder is sent once."""
        rows = (
            await self.db.execute(
                select(Invoice, Journal)
                .join(Journal, Journal.id == Invoice.journal_id)
                .where(Invoice.status == InvoiceStatus.ISSUED)
            )
        ).all()
        sent = 0
        now = today()
        for invoice, journal in rows:
            reached = [
                d
                for d in payment_settings(journal).reminder_days
                if now >= invoice.due_date + timedelta(days=d)
            ]
            if not reached:
                continue
            inserted = set(
                (
                    await self.db.scalars(
                        insert(InvoiceReminder)
                        .values(
                            [
                                {"invoice_id": invoice.id, "offset_days": d, "due": invoice.due_date}
                                for d in reached
                            ]
                        )
                        .on_conflict_do_nothing()
                        .returning(InvoiceReminder.offset_days)
                    )
                ).all()
            )
            if max(reached) not in inserted:
                continue
            submission = await self._submission(invoice.submission_id)
            await self._mail_payer(journal, submission, invoice, emails.REMINDER.key)
            sent += 1
        return sent

    async def reconcile(self) -> list[str]:
        """Ask providers about open payments; report what a person should look at."""
        problems: list[str] = []
        cutoff = utcnow() - timedelta(minutes=15)
        open_payments = (
            await self.db.scalars(
                select(Payment).where(
                    Payment.status.in_([PaymentStatus.CREATED, PaymentStatus.PENDING]),
                    Payment.created_at < cutoff,
                )
            )
        ).all()
        available = providers(self.settings)
        for payment in open_payments:
            invoice = await self.db.get(Invoice, payment.invoice_id)
            journal = await self.db.get(Journal, invoice.journal_id) if invoice else None
            provider = available.get(payment.provider)
            if journal is None or provider is None or not payment.provider_ref:
                continue
            try:
                status = await provider.complete(payment.provider_ref)
            except ProviderError as exc:
                problems.append(
                    f"Payment #{payment.id} ({payment.provider}): the provider could not be asked ({exc})."
                )
                continue
            await self.apply_status(journal, payment, status)
            if payment.status == PaymentStatus.PENDING and payment.created_at < utcnow() - STUCK_AFTER:
                # The payer most likely abandoned the page; close it so it does not linger.
                payment.status = PaymentStatus.CANCELLED
                payment.failure_reason = "Abandoned: not completed within two days"
        mismatched = (
            await self.db.scalars(
                select(Payment).where(Payment.status == PaymentStatus.PENDING, Payment.failure_reason != "")
            )
        ).all()
        problems += [f"Payment #{p.id}: {p.failure_reason}." for p in mismatched]
        stale_refunds = (
            await self.db.scalars(
                select(Refund).where(
                    Refund.status == RefundStatus.PENDING, Refund.created_at < utcnow() - timedelta(days=1)
                )
            )
        ).all()
        problems += [f"Refund #{r.id} of {r.amount} is still being processed." for r in stale_refunds]
        failed_refunds = (
            await self.db.scalars(
                select(Refund).where(
                    Refund.status == RefundStatus.FAILED, Refund.created_at > utcnow() - timedelta(days=1)
                )
            )
        ).all()
        problems += [f"Refund #{r.id} failed: {r.failure_reason}" for r in failed_refunds]
        await self.db.flush()
        if problems:
            journals = (await self.db.scalars(select(Journal))).all()
            for journal in journals:
                await self._mail_finance(
                    journal, emails.ATTENTION.key, {"problems": "\n".join(f"- {p}" for p in problems)}
                )
        return problems

    # ------------------------------------------------------------------ finance lists

    async def list_invoices(
        self, journal: Journal, *, status: str | None, overdue: bool, q: str | None, limit: int, offset: int
    ) -> tuple[Sequence[tuple[Invoice, Submission]], int]:
        query = (
            select(Invoice, Submission)
            .join(Submission, Submission.id == Invoice.submission_id)
            .where(Invoice.journal_id == journal.id)
        )
        if status:
            query = query.where(Invoice.status == status)
        if overdue:
            query = query.where(Invoice.status == InvoiceStatus.ISSUED, Invoice.due_date < today())
        if q and q.strip():
            pattern = f"%{escape_like(q.strip().lower())}%"
            query = query.where(
                func.lower(Invoice.number).like(pattern, escape="\\")
                | func.lower(Invoice.payer_name).like(pattern, escape="\\")
                | func.lower(Invoice.payer_email).like(pattern, escape="\\")
                | func.lower(Submission.number).like(pattern, escape="\\")
            )
        total = int(await self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = (
            await self.db.execute(
                query.order_by(Invoice.issued_at.desc(), Invoice.id.desc()).limit(limit).offset(offset)
            )
        ).all()
        return [(i, s) for i, s in rows], total

    async def summary(self, journal: Journal) -> list[tuple[str, str, int, Decimal]]:
        rows = await self.db.execute(
            select(Invoice.currency, Invoice.status, func.count(), func.coalesce(func.sum(Invoice.total), 0))
            .where(Invoice.journal_id == journal.id)
            .group_by(Invoice.currency, Invoice.status)
        )
        return [(currency, status, count, Decimal(total)) for currency, status, count, total in rows]

    def settings_for(self, journal: Journal) -> PaymentSettings:
        return payment_settings(journal)
