from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, id_column, utcnow

MONEY = Numeric(12, 2)


class InvoiceStatus:
    ISSUED = "issued"  # waiting for payment
    PAID = "paid"
    WAIVED = "waived"  # the whole fee was waived
    VOID = "void"  # cancelled (e.g. a wrong amount); a new invoice can be issued
    REFUNDED = "refunded"  # paid, then refunded in full


ACTIVE_INVOICE = (InvoiceStatus.ISSUED, InvoiceStatus.PAID, InvoiceStatus.WAIVED, InvoiceStatus.REFUNDED)
SETTLED = (InvoiceStatus.PAID, InvoiceStatus.WAIVED)


class Invoice(TimestampMixin, Base):
    """The publication fee for an accepted manuscript."""

    __tablename__ = "invoices"
    __table_args__ = (
        # One invoice in force per manuscript; void ones stay for the record.
        Index(
            "uq_invoices_submission_active",
            "submission_id",
            unique=True,
            postgresql_where=text("status <> 'void'"),
        ),
        Index("ix_invoices_status_due", "journal_id", "status", "due_date"),
    )

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="RESTRICT"))
    number: Mapped[str] = mapped_column(String(30), unique=True)  # INV-2026-0017
    status: Mapped[str] = mapped_column(String(20), default=InvoiceStatus.ISSUED)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(MONEY)  # the fee before discount and tax
    discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    discount_percent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    vat_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(MONEY)
    refunded: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), server_default="0")
    # Who pays: the submitting author by default; an institution can be named instead.
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    payer_name: Mapped[str] = mapped_column(String(300))
    payer_email: Mapped[str] = mapped_column(String(320))
    payer_organization: Mapped[str] = mapped_column(String(300), default="", server_default="")
    payer_address: Mapped[str] = mapped_column(Text, default="", server_default="")
    payer_tax_id: Mapped[str] = mapped_column(String(40), default="", server_default="")
    description: Mapped[str] = mapped_column(String(500))
    due_date: Mapped[date]
    issued_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    paid_at: Mapped[datetime | None]
    waived_at: Mapped[datetime | None]
    voided_at: Mapped[datetime | None]
    void_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    payments: Mapped[list[Payment]] = relationship(lazy="selectin", order_by="Payment.id")

    __mapper_args__: dict[str, Any] = {"version_id_col": row_version}  # noqa: RUF012


class PaymentStatus:
    CREATED = "created"  # a checkout is being prepared with the provider
    PENDING = "pending"  # the payer is on the provider's page, or a transfer is expected
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Payment(Base):
    """One attempt to pay an invoice, through a provider or by bank transfer."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_ref"),
        Index("ix_payments_open", "created_at", postgresql_where=text("status IN ('created', 'pending')")),
    )

    id: Mapped[int] = id_column()
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    # The provider's id for the checkout (PayPal order); then for the money movement (PayPal capture).
    provider_ref: Mapped[str | None] = mapped_column(String(100))
    capture_ref: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default=PaymentStatus.CREATED)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    refunded: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), server_default="0")
    checkout_url: Mapped[str | None] = mapped_column(String(2000))
    # For bank transfers: the bank's reference, as entered by the finance manager.
    reference: Mapped[str] = mapped_column(String(200), default="", server_default="")
    failure_reason: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    completed_at: Mapped[datetime | None]

    refunds: Mapped[list[Refund]] = relationship(lazy="selectin", order_by="Refund.id")


class RefundStatus:
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = id_column()
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=RefundStatus.PENDING)
    provider_ref: Mapped[str | None] = mapped_column(String(100))
    failure_reason: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    completed_at: Mapped[datetime | None]


class ProviderEvent(Base):
    """A notification received from a payment provider. The unique key makes redelivery harmless."""

    __tablename__ = "provider_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)

    id: Mapped[int] = id_column()
    provider: Mapped[str] = mapped_column(String(30))
    event_id: Mapped[str] = mapped_column(String(150))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(String(300), default="", server_default="")
    received_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class WaiverStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class WaiverRequest(Base):
    """An author's request to reduce or waive the fee. Decided by the finance manager, never the editors."""

    __tablename__ = "waiver_requests"
    __table_args__ = (Index("ix_waiver_requests_status", "status", "created_at"),)

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    percent: Mapped[int] = mapped_column(Integer)  # requested: 100 means the whole fee
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=WaiverStatus.PENDING)
    approved_percent: Mapped[int | None] = mapped_column(Integer)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    decided_at: Mapped[datetime | None]


class InvoiceCounter(Base):
    __tablename__ = "invoice_counters"

    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer)


class InvoiceReminder(Base):
    __tablename__ = "invoice_reminders"
    __table_args__ = (UniqueConstraint("invoice_id", "offset_days", "due"),)

    id: Mapped[int] = id_column()
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    offset_days: Mapped[int] = mapped_column(Integer)
    due: Mapped[date]
    sent_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
