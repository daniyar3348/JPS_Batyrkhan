"""PayPal, through its REST API: Orders v2 for checkout, captures, refunds, and webhook verification.

The payer approves the order on PayPal's page; we then capture it, either when they come back or when
PayPal tells us the order was approved (``CHECKOUT.ORDER.APPROVED``). ``PAYMENT.CAPTURE.COMPLETED``
confirms the money. Notifications are verified by asking PayPal (``verify-webhook-signature``), so
nothing is trusted that PayPal itself has not signed.

Verified against the documented request and response formats with mocked HTTP; check it against the
PayPal sandbox with the journal's own keys before going live (stage 7).
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from app.modules.payments.providers.base import (
    Checkout,
    CheckoutRequest,
    InvalidNotification,
    ProviderError,
    ProviderNotice,
    ProviderStatus,
    RefundResult,
)

BASE_URLS = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}

# Currencies PayPal can charge (its "currency codes" reference). The tenge is not among them, so a
# journal invoicing in KZT cannot offer PayPal.
CURRENCIES = frozenset(
    [
        "AUD",
        "BRL",
        "CAD",
        "CNY",
        "CZK",
        "DKK",
        "EUR",
        "HKD",
        "HUF",
        "ILS",
        "JPY",
        "MYR",
        "MXN",
        "TWD",
        "NZD",
        "NOK",
        "PHP",
        "PLN",
        "GBP",
        "SGD",
        "SEK",
        "CHF",
        "THB",
        "USD",
    ]
)

VERIFY_HEADERS = {
    "auth_algo": "paypal-auth-algo",
    "cert_url": "paypal-cert-url",
    "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig",
    "transmission_time": "paypal-transmission-time",
}


class PayPalProvider:
    name = "paypal"
    label = "PayPal"
    currencies: frozenset[str] | None = CURRENCIES

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        webhook_id: str | None,
        mode: str = "sandbox",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.webhook_id = webhook_id
        self.base_url = BASE_URLS[mode]
        self.transport = transport
        self._token: tuple[str, float] | None = None

    # ------------------------------------------------------------------ HTTP

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=20.0, transport=self.transport)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        response = await client.post(
            "/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
        )
        if response.status_code != 200:
            raise ProviderError(f"PayPal sign-in failed ({response.status_code})")
        data = response.json()
        self._token = (data["access_token"], time.time() + int(data.get("expires_in", 300)))
        return self._token[0]

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        async with self._client() as client:
            token = await self._access_token(client)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            if idempotency_key:
                # PayPal-Request-Id makes retries of the same request safe.
                headers["PayPal-Request-Id"] = idempotency_key
            try:
                response = await client.request(method, path, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise ProviderError("PayPal could not be reached") from exc
        if response.status_code >= 400:
            raise ProviderError(f"PayPal refused the request ({response.status_code}): {response.text[:300]}")
        data: dict[str, Any] = response.json() if response.content else {}
        return data

    # ------------------------------------------------------------------ PaymentProvider

    async def create_checkout(self, request: CheckoutRequest) -> Checkout:
        order = await self._call(
            "POST",
            "/v2/checkout/orders",
            idempotency_key=f"jps-payment-{request.payment_id}",
            body={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": request.invoice_number,
                        "custom_id": str(request.payment_id),
                        "invoice_id": f"{request.invoice_number}-{request.payment_id}",
                        "description": request.description[:127],
                        "amount": {"currency_code": request.currency, "value": f"{request.amount:.2f}"},
                    }
                ],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            "brand_name": request.merchant_name[:127],
                            "shipping_preference": "NO_SHIPPING",
                            "user_action": "PAY_NOW",
                            "return_url": request.return_url,
                            "cancel_url": request.cancel_url,
                        }
                    }
                },
            },
        )
        link = next(
            (
                item["href"]
                for item in order.get("links", [])
                if item.get("rel") in ("payer-action", "approve")
            ),
            None,
        )
        if not order.get("id") or not link:
            raise ProviderError("PayPal did not return a payment page")
        return Checkout(provider_ref=str(order["id"]), redirect_url=link)

    @staticmethod
    def _capture_of(order: Mapping[str, Any]) -> ProviderStatus:
        captures = [
            capture
            for unit in order.get("purchase_units", [])
            for capture in unit.get("payments", {}).get("captures", [])
        ]
        if not captures:
            status = order.get("status")
            if status == "APPROVED":
                return ProviderStatus(kind="approved")
            if status in ("VOIDED",):
                return ProviderStatus(kind="failed")
            return ProviderStatus(kind="pending")
        capture = captures[-1]
        amount = capture.get("amount", {})
        kind = {"COMPLETED": "succeeded", "DECLINED": "failed", "FAILED": "failed"}.get(
            capture.get("status"), "pending"
        )
        return ProviderStatus(
            kind=kind,  # type: ignore[arg-type]
            capture_ref=capture.get("id"),
            amount=Decimal(amount["value"]) if "value" in amount else None,
            currency=amount.get("currency_code"),
        )

    async def complete(self, provider_ref: str) -> ProviderStatus:
        current = await self.status(provider_ref)
        if current.kind != "approved":
            return current
        order = await self._call(
            "POST",
            f"/v2/checkout/orders/{provider_ref}/capture",
            body={},
            idempotency_key=f"jps-capture-{provider_ref}",
        )
        return self._capture_of(order)

    async def status(self, provider_ref: str) -> ProviderStatus:
        return self._capture_of(await self._call("GET", f"/v2/checkout/orders/{provider_ref}"))

    async def parse_notification(self, headers: Mapping[str, str], body: bytes) -> list[ProviderNotice]:
        if not self.webhook_id:
            raise InvalidNotification("PayPal webhook id is not configured")
        try:
            event = json.loads(body)
        except ValueError as exc:
            raise InvalidNotification("Unreadable notification") from exc
        missing = [name for name, header in VERIFY_HEADERS.items() if not headers.get(header)]
        if missing:
            raise InvalidNotification(f"Missing PayPal headers: {', '.join(missing)}")
        verification = await self._call(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            body={
                **{name: headers[header] for name, header in VERIFY_HEADERS.items()},
                "webhook_id": self.webhook_id,
                "webhook_event": event,
            },
        )
        if verification.get("verification_status") != "SUCCESS":
            raise InvalidNotification("PayPal did not confirm the signature")

        event_type = str(event.get("event_type", ""))
        resource = event.get("resource", {})
        notice: dict[str, Any] = {
            "event_id": str(event.get("id")),
            "event_type": event_type,
            "payload": event,
        }
        if event_type == "CHECKOUT.ORDER.APPROVED":
            return [ProviderNotice(**notice, kind="approved", provider_ref=resource.get("id"))]
        if event_type in ("PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED"):
            amount = resource.get("amount", {})
            order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
            custom = resource.get("custom_id")
            return [
                ProviderNotice(
                    **notice,
                    kind="succeeded" if event_type.endswith("COMPLETED") else "failed",
                    provider_ref=order_id,
                    payment_id=int(custom) if custom and str(custom).isdigit() else None,
                    capture_ref=resource.get("id"),
                    amount=Decimal(amount["value"]) if "value" in amount else None,
                    currency=amount.get("currency_code"),
                )
            ]
        return [ProviderNotice(**notice, kind="ignored")]

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
        if not capture_ref:
            raise ProviderError("The PayPal payment has no capture to refund")
        result = await self._call(
            "POST",
            f"/v2/payments/captures/{capture_ref}/refund",
            idempotency_key=f"jps-refund-{refund_id}",
            body={
                "amount": {"value": f"{amount:.2f}", "currency_code": currency},
                "note_to_payer": reason[:255],
            },
        )
        return RefundResult(provider_ref=str(result.get("id")), succeeded=result.get("status") == "COMPLETED")
