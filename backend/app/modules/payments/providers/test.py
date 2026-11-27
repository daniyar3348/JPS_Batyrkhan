"""A pretend card provider for development and demonstrations (``JPS_PAYMENTS_TEST_PROVIDER``).

Its "payment page" is served by our own API. Paying there produces a notification signed with the
server's secret, which goes through exactly the same checks as a real provider's: signature,
duplicate detection, amount. The production settings refuse to start with it switched on.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.modules.payments.providers.base import (
    Checkout,
    CheckoutRequest,
    InvalidNotification,
    ProviderNotice,
    ProviderStatus,
    RefundResult,
)

SIGNATURE_HEADER = "x-test-signature"


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


PAGE_TTL = 3600


class TestProvider:
    name = "test"
    label = "Card (test)"
    currencies: frozenset[str] | None = None

    def __init__(self, *, secret: bytes, public_url: str) -> None:
        self.secret = secret
        self.public_url = public_url.rstrip("/")

    # ------------------------------------------------------------------ the pretend payment page

    def _sign(self, data: bytes) -> str:
        return hmac.new(self.secret, data, hashlib.sha256).hexdigest()

    def page_token(self, request: CheckoutRequest, provider_ref: str) -> str:
        payload = json.dumps(
            {
                "ref": provider_ref,
                "payment": request.payment_id,
                "invoice": request.invoice_number,
                "amount": str(request.amount),
                "currency": request.currency,
                "merchant": request.merchant_name,
                "return": request.return_url,
                "cancel": request.cancel_url,
                "exp": int(time.time()) + PAGE_TTL,
            },
            separators=(",", ":"),
        ).encode()
        return f"{b64encode(payload)}.{self._sign(payload)}"

    def read_token(self, token: str) -> dict[str, Any]:
        try:
            encoded, signature = token.split(".", 1)
            payload = b64decode(encoded)
        except ValueError as exc:
            raise InvalidNotification("Malformed payment link") from exc
        if not hmac.compare_digest(signature, self._sign(payload)):
            raise InvalidNotification("Invalid payment link")
        data: dict[str, Any] = json.loads(payload)
        if data["exp"] < time.time():
            raise InvalidNotification("The payment link has expired")
        return data

    def notification(self, page: Mapping[str, Any], *, succeeded: bool) -> tuple[dict[str, str], bytes]:
        """The signed notification the pretend provider sends after the payer's choice."""
        body = json.dumps(
            {
                "id": f"evt_{uuid.uuid4().hex}",
                "type": "payment.succeeded" if succeeded else "payment.failed",
                "ref": page["ref"],
                "transaction": f"txn_{uuid.uuid4().hex[:16]}",
                "amount": page["amount"],
                "currency": page["currency"],
            },
            separators=(",", ":"),
        ).encode()
        return {SIGNATURE_HEADER: self._sign(body), "content-type": "application/json"}, body

    # ------------------------------------------------------------------ PaymentProvider

    async def create_checkout(self, request: CheckoutRequest) -> Checkout:
        provider_ref = f"test_{uuid.uuid4().hex}"
        token = self.page_token(request, provider_ref)
        return Checkout(
            provider_ref=provider_ref, redirect_url=f"{self.public_url}/api/v1/payments/test-checkout/{token}"
        )

    async def parse_notification(self, headers: Mapping[str, str], body: bytes) -> list[ProviderNotice]:
        signature = headers.get(SIGNATURE_HEADER, "")
        if not signature or not hmac.compare_digest(signature, self._sign(body)):
            raise InvalidNotification("Bad signature")
        try:
            data = json.loads(body)
            kind = {"payment.succeeded": "succeeded", "payment.failed": "failed"}[data["type"]]
            return [
                ProviderNotice(
                    event_id=str(data["id"]),
                    event_type=str(data["type"]),
                    kind=kind,  # type: ignore[arg-type]
                    provider_ref=str(data["ref"]),
                    capture_ref=str(data["transaction"]),
                    amount=Decimal(str(data["amount"])),
                    currency=str(data["currency"]),
                    payload=data,
                )
            ]
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidNotification("Unreadable notification") from exc

    async def complete(self, provider_ref: str) -> ProviderStatus:
        # The pretend provider reports only through its notification.
        return ProviderStatus(kind="pending")

    async def status(self, provider_ref: str) -> ProviderStatus:
        return ProviderStatus(kind="pending")

    async def refund(
        self,
        *,
        refund_id: int,
        provider_ref: str,
        capture_ref: str | None,
        amount: Decimal,
        currency: str,
        reason: str,
    ) -> RefundResult:
        return RefundResult(provider_ref=f"test_refund_{uuid.uuid4().hex[:12]}", succeeded=True)
