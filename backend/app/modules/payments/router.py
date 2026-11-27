"""Payments over HTTP: the authors' and finance managers' screens, provider notifications, test page."""

from __future__ import annotations

import html
from decimal import Decimal
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import etag_for, parse_if_match
from app.core.config import Settings
from app.core.deps import get_db, get_settings, get_storage
from app.core.errors import BadRequest, NotFound
from app.core.storage import Storage
from app.modules.journals.deps import (
    Principal,
    get_current_journal,
    get_journal_service,
    get_principal,
    require,
)
from app.modules.journals.models import Journal
from app.modules.journals.payment_settings import (
    CURRENCIES,
    MethodAvailability,
    PaymentSettings,
    PaymentSettingsOut,
    payment_settings,
)
from app.modules.journals.permissions import Capability
from app.modules.journals.service import JournalService
from app.modules.payments.models import Invoice, Payment
from app.modules.payments.pdf import render_invoice
from app.modules.payments.providers.base import InvalidNotification
from app.modules.payments.providers.registry import BANK_TRANSFER, test_provider
from app.modules.payments.schemas import (
    BillingOut,
    CheckoutIn,
    CheckoutOut,
    InvoiceOut,
    InvoicePage,
    InvoiceRow,
    MethodOption,
    PayerIn,
    PaymentStatusOut,
    RefundIn,
    SummaryLine,
    TransferIn,
    VoidIn,
    WaiverDecisionIn,
    WaiverIn,
    WaiverOut,
    WaiverRow,
)
from app.modules.payments.service import PaymentService, today
from app.modules.submissions.models import Submission
from app.modules.submissions.policies import access_for
from app.modules.submissions.service import SubmissionService

router = APIRouter(tags=["payments"])
webhook_router = APIRouter(tags=["payments"])

FINANCE = require(Capability.PAYMENTS_MANAGE)


def get_payment_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> PaymentService:
    return PaymentService(db, settings)


def get_submission_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> SubmissionService:
    return SubmissionService(db, settings, storage)


def is_finance(principal: Principal) -> bool:
    return principal.can(Capability.PAYMENTS_MANAGE)


async def _billing_submission(
    submissions: SubmissionService, principal: Principal, submission_id: int
) -> Submission:
    """The manuscript, for its authors and the finance managers only. Editors get "not found"."""
    submission = await submissions.get(principal.journal, submission_id)
    if not (is_finance(principal) or access_for(principal, submission).is_author):
        raise NotFound("Submission not found.")
    return submission


async def _invoice_for_viewer(service: PaymentService, principal: Principal, invoice_id: int) -> Invoice:
    invoice = await service.get_invoice(principal.journal, invoice_id)
    if is_finance(principal):
        return invoice
    submission = await service.db.get(Submission, invoice.submission_id)
    if submission is None or not access_for(principal, submission).is_author:
        raise NotFound("Invoice not found.")
    return invoice


async def _billing(service: PaymentService, journal: Journal, submission: Submission) -> BillingOut:
    config = payment_settings(journal)
    methods = service.methods(journal)
    return BillingOut(
        enabled=config.enabled,
        fee_required=service.fee_required(journal, submission),
        accepted=service.accepted(submission),
        currency=config.currency,
        expected_fee=config.fee_for(submission.section_id),
        invoices=[InvoiceOut.of(i, today()) for i in await service.invoices(submission.id)],
        waivers=[WaiverOut.of(w) for w in await service.waivers_for(submission.id)],
        can_request_waiver=await service.can_request_waiver(journal, submission),
        waiver_policy=config.waiver_policy,
        methods=[
            MethodOption(method=m, label=label, available=ok, reason=why) for m, label, ok, why in methods
        ],
        bank_details=config.payee if any(m == BANK_TRANSFER and ok for m, _, ok, _ in methods) else None,
    )


# ---------------------------------------------------------------------- authors (and finance)


@router.get("/submissions/{submission_id}/billing")
async def get_billing(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PaymentService = Depends(get_payment_service),
) -> BillingOut:
    """The publication fee of a manuscript: invoices, payments, waiver requests, how to pay."""
    submission = await _billing_submission(submissions, principal, submission_id)
    return await _billing(service, principal.journal, submission)


@router.post("/submissions/{submission_id}/waiver-requests", status_code=201)
async def request_waiver(
    submission_id: int,
    data: WaiverIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PaymentService = Depends(get_payment_service),
) -> BillingOut:
    """Ask to reduce or waive the fee. The finance managers decide; the editors never see it."""
    submission = await submissions.get(principal.journal, submission_id)
    if not access_for(principal, submission).is_author:
        raise NotFound("Submission not found.")
    await service.request_waiver(
        principal.journal, submission, percent=data.percent, reason=data.reason, actor=principal.user
    )
    await service.db.commit()
    return await _billing(service, principal.journal, submission)


@router.patch("/payments/invoices/{invoice_id}/payer")
async def change_payer(
    invoice_id: int,
    data: PayerIn,
    principal: Principal = Depends(get_principal),
    service: PaymentService = Depends(get_payment_service),
) -> InvoiceOut:
    """Who the invoice is made out to, e.g. the author's university."""
    invoice = await _invoice_for_viewer(service, principal, invoice_id)
    await service.update_payer(invoice, data.model_dump(mode="json"), principal.user)
    await service.db.commit()
    return InvoiceOut.of(invoice, today())


@router.post("/payments/invoices/{invoice_id}/checkout")
async def start_checkout(
    invoice_id: int,
    data: CheckoutIn,
    principal: Principal = Depends(get_principal),
    service: PaymentService = Depends(get_payment_service),
) -> CheckoutOut:
    """Start paying online. The response says where to send the payer (the provider's page)."""
    invoice = await _invoice_for_viewer(service, principal, invoice_id)
    payment = await service.start_checkout(principal.journal, invoice, data.method, principal.user)
    await service.db.commit()
    return CheckoutOut(payment_id=payment.id, redirect_url=payment.checkout_url or "")


async def _payment_status(service: PaymentService, payment: Payment, invoice: Invoice) -> PaymentStatusOut:
    return PaymentStatusOut(
        payment_id=payment.id,
        status=payment.status,
        submission_id=invoice.submission_id,
        invoice_number=invoice.number,
        invoice_status=invoice.status,
        amount=payment.amount,
        currency=payment.currency,
    )


@router.get("/payments/{payment_id:int}")
async def get_payment_status(
    payment_id: int,
    principal: Principal = Depends(get_principal),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentStatusOut:
    payment, _ = await service.get_payment(principal.journal, payment_id)
    invoice = await _invoice_for_viewer(service, principal, payment.invoice_id)
    return await _payment_status(service, payment, invoice)


@router.post("/payments/{payment_id:int}/confirm")
async def confirm_payment(
    payment_id: int,
    principal: Principal = Depends(get_principal),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentStatusOut:
    """The payer is back from the provider's page: check the payment with the provider (never trust the
    browser alone). The provider's notification may also arrive before or after this."""
    payment, _ = await service.get_payment(principal.journal, payment_id)
    invoice = await _invoice_for_viewer(service, principal, payment.invoice_id)
    await service.confirm(principal.journal, payment)
    await service.db.commit()
    await service.db.refresh(invoice)
    return await _payment_status(service, payment, invoice)


@router.get("/payments/invoices/{invoice_id}/pdf", response_class=Response)
async def invoice_pdf(
    invoice_id: int,
    principal: Principal = Depends(get_principal),
    service: PaymentService = Depends(get_payment_service),
) -> Response:
    """The invoice, or the receipt once paid."""
    invoice = await _invoice_for_viewer(service, principal, invoice_id)
    data = render_invoice(invoice, principal.journal, payment_settings(principal.journal))
    kind = "receipt" if invoice.status in ("paid", "refunded") else "invoice"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.number}-{kind}.pdf"'},
    )


# ---------------------------------------------------------------------- finance managers


@router.get("/payments/invoices")
async def list_invoices(
    status: str | None = Query(default=None, max_length=20),
    overdue: bool = False,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> InvoicePage:
    rows, total = await service.list_invoices(
        principal.journal, status=status or None, overdue=overdue, q=q, limit=limit, offset=offset
    )
    now = today()
    return InvoicePage(
        items=[
            InvoiceRow(
                id=i.id,
                number=i.number,
                status=i.status,
                overdue=i.status == "issued" and i.due_date < now,
                total=i.total,
                currency=i.currency,
                payer_name=i.payer_name,
                due_date=i.due_date,
                issued_at=i.issued_at,
                paid_at=i.paid_at,
                submission_id=s.id,
                submission_number=s.number,
                submission_title=s.publication.title,
            )
            for i, s in rows
        ],
        total=total,
    )


@router.get("/payments/summary")
async def payments_summary(
    principal: Principal = Depends(FINANCE), service: PaymentService = Depends(get_payment_service)
) -> list[SummaryLine]:
    return [
        SummaryLine(currency=c, status=s, count=n, amount=a)
        for c, s, n, a in await service.summary(principal.journal)
    ]


@router.get("/payments/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: int,
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> InvoiceOut:
    return InvoiceOut.of(await service.get_invoice(principal.journal, invoice_id), today())


@router.post("/payments/invoices/{invoice_id}/transfers")
async def record_transfer(
    invoice_id: int,
    data: TransferIn,
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> InvoiceOut:
    """Record money received by bank transfer."""
    invoice = await service.get_invoice(principal.journal, invoice_id)
    await service.record_transfer(
        principal.journal,
        invoice,
        amount=data.amount,
        reference=data.reference,
        paid_on=data.paid_on,
        actor=principal.user,
    )
    await service.db.commit()
    await service.db.refresh(invoice)
    return InvoiceOut.of(invoice, today())


@router.post("/payments/invoices/{invoice_id}/void")
async def void_invoice(
    invoice_id: int,
    data: VoidIn,
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> InvoiceOut:
    invoice = await service.get_invoice(principal.journal, invoice_id)
    await service.void(invoice, data.reason, principal.user)
    await service.db.commit()
    return InvoiceOut.of(invoice, today())


@router.post("/submissions/{submission_id}/invoices", status_code=201)
async def issue_invoice(
    submission_id: int,
    principal: Principal = Depends(FINANCE),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PaymentService = Depends(get_payment_service),
) -> InvoiceOut:
    """Issue a new invoice for an accepted manuscript whose previous one was voided."""
    submission = await submissions.get(principal.journal, submission_id)
    invoice = await service.reissue(principal.journal, submission, principal.user)
    await service.db.commit()
    return InvoiceOut.of(invoice, today())


@router.post("/payments/{payment_id:int}/refunds")
async def refund_payment(
    payment_id: int,
    data: RefundIn,
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> InvoiceOut:
    """Refund all or part of a payment. Online payments are refunded through their provider."""
    payment, invoice = await service.get_payment(principal.journal, payment_id)
    await service.request_refund(
        principal.journal, payment, amount=data.amount, reason=data.reason, actor=principal.user
    )
    await service.db.commit()
    await service.db.refresh(invoice)
    for item in invoice.payments:
        await service.db.refresh(item)
    return InvoiceOut.of(invoice, today())


@router.get("/payments/waiver-requests")
async def list_waiver_requests(
    status: str | None = Query(default="pending", max_length=20),
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> list[WaiverRow]:
    rows = await service.list_waivers(principal.journal, status=status or None)
    result = []
    for waiver, submission in rows:
        requester = (
            await service.journals.identity.get_user(waiver.requested_by_id)
            if waiver.requested_by_id
            else None
        )
        result.append(
            WaiverRow(
                **WaiverOut.of(waiver).model_dump(),
                submission_number=submission.number,
                submission_title=submission.publication.title,
                requested_by=requester.full_name if requester else "",
            )
        )
    return result


@router.post("/payments/waiver-requests/{waiver_id}/decision")
async def decide_waiver(
    waiver_id: int,
    data: WaiverDecisionIn,
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> WaiverOut:
    waiver, submission = await service.get_waiver(principal.journal, waiver_id)
    await service.decide_waiver(
        principal.journal,
        waiver,
        submission,
        approve=data.approve,
        percent=data.percent,
        note=data.note,
        actor=principal.user,
    )
    await service.db.commit()
    return WaiverOut.of(waiver)


def _settings_out(journal: Journal, data: PaymentSettings, service: PaymentService) -> PaymentSettingsOut:
    # Availability as if every method were switched on, so the page can explain what is missing.
    every_method = data.methods.model_copy(update={"card": True, "paypal": True, "bank_transfer": True})
    availability = [
        MethodAvailability(method=m, label=label, available=ok, reason=why)
        for m, label, ok, why in service.methods_for(data.model_copy(update={"methods": every_method}))
    ]
    return PaymentSettingsOut(
        **data.model_dump(),
        version=journal.version,
        currencies=list(CURRENCIES),
        method_availability=availability,
    )


@router.get("/journal/payment-settings", tags=["journal"])
async def get_payment_settings(
    response: Response,
    principal: Principal = Depends(FINANCE),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentSettingsOut:
    response.headers["ETag"] = etag_for(principal.journal.version)
    return _settings_out(principal.journal, payment_settings(principal.journal), service)


@router.put("/journal/payment-settings", tags=["journal"])
async def update_payment_settings(
    data: PaymentSettings,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(FINANCE),
    journals: JournalService = Depends(get_journal_service),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentSettingsOut:
    saved = await journals.update_payment_settings(
        principal.journal, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await service.db.commit()
    response.headers["ETag"] = etag_for(principal.journal.version)
    return _settings_out(principal.journal, saved, service)


# ---------------------------------------------------------------------- providers (no sign-in)


@webhook_router.post("/payments/webhooks/{provider}", include_in_schema=False)
async def provider_notification(
    provider: str,
    request: Request,
    journal: Journal = Depends(get_current_journal),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    """Signed notifications from payment providers. The signature is the only authentication."""
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        results = await service.handle_notification(journal, provider, headers, body)
    except InvalidNotification as exc:
        raise BadRequest("The notification could not be verified.", code="invalid_notification") from exc
    await service.db.commit()
    return {"received": len(results), "results": results}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Test payment</title>
<style>body{{font:16px system-ui,sans-serif;background:#f4f5f9;margin:0;padding:24px}}
main{{max-width:420px;margin:40px auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 10px #0001}}
h1{{font-size:20px;margin:0 0 4px}}p{{color:#555}}.sum{{font-size:28px;font-weight:700;color:#111;margin:16px 0}}
.note{{background:#fff4e5;color:#8a4b00;padding:10px 12px;border-radius:8px;font-size:14px}}
button{{width:100%;padding:12px;border:0;border-radius:8px;font-size:16px;margin-top:12px;cursor:pointer}}
.pay{{background:#4c6ef5;color:#fff}}.decline{{background:#eee}}</style></head>
<body><main><h1>{merchant}</h1><p>Invoice {invoice}</p><div class="sum">{amount} {currency}</div>
<p class="note">Test payment page. No money is charged; this stands in for the card acquirer's page.</p>
<form method="post"><button class="pay" name="action" value="pay">Pay</button>
<button class="decline" name="action" value="decline">Decline the payment</button></form></main></body></html>"""


@webhook_router.get("/payments/test-checkout/{token}", response_class=HTMLResponse, include_in_schema=False)
async def test_checkout_page(token: str, settings: Settings = Depends(get_settings)) -> HTMLResponse:
    if not settings.payments_test_provider:
        raise NotFound()
    try:
        page = test_provider(settings).read_token(token)
    except InvalidNotification as exc:
        raise BadRequest(str(exc), code="invalid_link") from exc
    return HTMLResponse(
        PAGE.format(
            merchant=html.escape(page["merchant"]),
            invoice=html.escape(page["invoice"]),
            amount=html.escape(f"{Decimal(page['amount']):,.2f}"),
            currency=html.escape(page["currency"]),
        )
    )


@webhook_router.post("/payments/test-checkout/{token}", include_in_schema=False)
async def test_checkout_submit(
    token: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    journal: Journal = Depends(get_current_journal),
    service: PaymentService = Depends(get_payment_service),
) -> RedirectResponse:
    """The pretend provider's decision: its signed notification goes through the real notification path."""
    if not settings.payments_test_provider:
        raise NotFound()
    # A plain HTML form (application/x-www-form-urlencoded).
    action = parse_qs((await request.body()).decode()).get("action", [""])[0]
    provider = test_provider(settings)
    try:
        page = provider.read_token(token)
    except InvalidNotification as exc:
        raise BadRequest(str(exc), code="invalid_link") from exc
    headers, body = provider.notification(page, succeeded=action == "pay")
    await service.handle_notification(journal, "test", headers, body)
    await service.db.commit()
    return RedirectResponse(page["return"] if action == "pay" else page["cancel"], status_code=303)
