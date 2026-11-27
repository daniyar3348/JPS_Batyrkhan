"""The interface every payment provider implements (§8.2 of the architecture).

A provider shows the payer its own payment page (card details never reach our server), tells us the
outcome by a signed notification, and can refund. Adding a provider means one more implementation of
``PaymentProvider``; nothing else in the system changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol


class ProviderError(Exception):
    """The provider refused the request or could not be reached."""


class InvalidNotification(Exception):
    """A notification whose signature or content cannot be trusted."""


@dataclass(frozen=True)
class Checkout:
    provider_ref: str  # the provider's id for this checkout
    redirect_url: str  # where to send the payer


@dataclass(frozen=True)
class CheckoutRequest:
    payment_id: int
    invoice_number: str
    amount: Decimal
    currency: str
    description: str
    payer_email: str
    merchant_name: str
    return_url: str
    cancel_url: str


EventKind = Literal["succeeded", "failed", "approved", "refunded", "ignored"]


@dataclass(frozen=True)
class ProviderNotice:
    """What a notification says, in our terms."""

    event_id: str
    event_type: str
    kind: EventKind
    # Which payment: the checkout id we stored, or our payment id passed through the provider.
    provider_ref: str | None = None
    payment_id: int | None = None
    capture_ref: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderStatus:
    kind: Literal["succeeded", "failed", "pending", "approved"]
    capture_ref: str | None = None
    amount: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True)
class RefundResult:
    provider_ref: str
    succeeded: bool  # False: accepted but still processing


class PaymentProvider(Protocol):
    name: str
    label: str

    @property
    def currencies(self) -> frozenset[str] | None:
        """Currencies the provider can charge; None: any."""
        ...

    async def create_checkout(self, request: CheckoutRequest) -> Checkout: ...

    async def parse_notification(self, headers: Mapping[str, str], body: bytes) -> list[ProviderNotice]:
        """Check the notification's signature and read it. Raises ``InvalidNotification``."""
        ...

    async def complete(self, provider_ref: str) -> ProviderStatus:
        """Called when the payer comes back: finish the payment if the provider needs it (PayPal capture)."""
        ...

    async def status(self, provider_ref: str) -> ProviderStatus:
        """The provider's view of a checkout, for reconciliation."""
        ...

    async def refund(
        self,
        *,
        refund_id: int,
        provider_ref: str,
        capture_ref: str | None,
        amount: Decimal,
        currency: str,
        reason: str,
    ) -> RefundResult: ...
