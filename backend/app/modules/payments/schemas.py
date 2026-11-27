from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.modules.journals.payment_settings import Payee
from app.modules.payments.models import Invoice, Payment, Refund, WaiverRequest
from app.modules.payments.providers.registry import method_of_provider

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class Defaults(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class RefundOut(Defaults):
    id: int
    amount: Decimal
    reason: str
    status: str
    failure_reason: str
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def of(cls, refund: Refund) -> RefundOut:
        return cls(
            id=refund.id,
            amount=refund.amount,
            reason=refund.reason,
            status=refund.status,
            failure_reason=refund.failure_reason,
            created_at=refund.created_at,
            completed_at=refund.completed_at,
        )


class PaymentOut(Defaults):
    id: int
    method: str
    provider: str
    status: str
    amount: Decimal
    currency: str
    refunded: Decimal
    reference: str
    failure_reason: str
    created_at: datetime
    completed_at: datetime | None
    refunds: list[RefundOut]

    @classmethod
    def of(cls, payment: Payment) -> PaymentOut:
        return cls(
            id=payment.id,
            method=method_of_provider(payment.provider),
            provider=payment.provider,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
            refunded=payment.refunded,
            reference=payment.reference,
            failure_reason=payment.failure_reason,
            created_at=payment.created_at,
            completed_at=payment.completed_at,
            refunds=[RefundOut.of(r) for r in payment.refunds],
        )


class InvoiceOut(Defaults):
    id: int
    submission_id: int
    number: str
    status: str
    currency: str
    amount: Decimal
    discount: Decimal
    discount_percent: int
    vat_percent: Decimal
    tax: Decimal
    total: Decimal
    refunded: Decimal
    payer_name: str
    payer_email: str
    payer_organization: str
    payer_address: str
    payer_tax_id: str
    description: str
    due_date: date
    overdue: bool
    issued_at: datetime
    paid_at: datetime | None
    waived_at: datetime | None
    voided_at: datetime | None
    void_reason: str
    pdf_url: str
    payments: list[PaymentOut]

    @classmethod
    def of(cls, invoice: Invoice, today: date) -> InvoiceOut:
        return cls(
            id=invoice.id,
            submission_id=invoice.submission_id,
            number=invoice.number,
            status=invoice.status,
            currency=invoice.currency,
            amount=invoice.amount,
            discount=invoice.discount,
            discount_percent=invoice.discount_percent,
            vat_percent=invoice.vat_percent,
            tax=invoice.tax,
            total=invoice.total,
            refunded=invoice.refunded,
            payer_name=invoice.payer_name,
            payer_email=invoice.payer_email,
            payer_organization=invoice.payer_organization,
            payer_address=invoice.payer_address,
            payer_tax_id=invoice.payer_tax_id,
            description=invoice.description,
            due_date=invoice.due_date,
            overdue=invoice.status == "issued" and invoice.due_date < today,
            issued_at=invoice.issued_at,
            paid_at=invoice.paid_at,
            waived_at=invoice.waived_at,
            voided_at=invoice.voided_at,
            void_reason=invoice.void_reason,
            pdf_url=f"/api/v1/payments/invoices/{invoice.id}/pdf",
            payments=[PaymentOut.of(p) for p in invoice.payments],
        )


class WaiverOut(Defaults):
    id: int
    submission_id: int
    percent: int
    reason: str
    status: str
    approved_percent: int | None
    decision_note: str
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def of(cls, waiver: WaiverRequest) -> WaiverOut:
        return cls(
            id=waiver.id,
            submission_id=waiver.submission_id,
            percent=waiver.percent,
            reason=waiver.reason,
            status=waiver.status,
            approved_percent=waiver.approved_percent,
            decision_note=waiver.decision_note,
            created_at=waiver.created_at,
            decided_at=waiver.decided_at,
        )


class MethodOption(Defaults):
    method: str
    label: str
    available: bool
    reason: str


class BillingOut(Defaults):
    """The publication fee of one manuscript, for its authors and the finance managers."""

    enabled: bool
    fee_required: bool
    accepted: bool
    currency: str
    expected_fee: Decimal
    invoices: list[InvoiceOut]
    waivers: list[WaiverOut]
    can_request_waiver: bool
    waiver_policy: str
    methods: list[MethodOption]
    # Shown when bank transfer is offered.
    bank_details: Payee | None


class WaiverIn(BaseModel):
    percent: int = Field(ge=1, le=100)
    reason: Reason


class WaiverDecisionIn(BaseModel):
    approve: bool
    percent: int | None = Field(default=None, ge=1, le=100)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""


class WaiverRow(WaiverOut):
    submission_number: str | None
    submission_title: str
    requested_by: str


class PayerIn(BaseModel):
    payer_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    payer_email: EmailStr
    payer_organization: Text = ""
    payer_address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    payer_tax_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""


class CheckoutIn(BaseModel):
    method: Literal["card", "paypal"]


class CheckoutOut(BaseModel):
    payment_id: int
    redirect_url: str


class PaymentStatusOut(Defaults):
    payment_id: int
    status: str
    submission_id: int
    invoice_number: str
    invoice_status: str
    amount: Decimal
    currency: str


class TransferIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    paid_on: date


class VoidIn(BaseModel):
    reason: Reason


class RefundIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: Reason


class InvoiceRow(Defaults):
    id: int
    number: str
    status: str
    overdue: bool
    total: Decimal
    currency: str
    payer_name: str
    due_date: date
    issued_at: datetime
    paid_at: datetime | None
    submission_id: int
    submission_number: str | None
    submission_title: str


class InvoicePage(Defaults):
    items: list[InvoiceRow]
    total: int


class SummaryLine(Defaults):
    currency: str
    status: str
    count: int
    amount: Decimal
