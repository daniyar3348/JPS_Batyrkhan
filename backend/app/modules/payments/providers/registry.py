"""Which payment methods the server can offer, from its configuration."""

from __future__ import annotations

from app.core.config import Settings
from app.modules.payments.providers.base import PaymentProvider
from app.modules.payments.providers.paypal import PayPalProvider
from app.modules.payments.providers.test import TestProvider

# The journal's payment methods (shown to authors) and the provider behind each.
METHOD_LABELS = {"card": "Card", "paypal": "PayPal", "bank_transfer": "Bank transfer"}
BANK_TRANSFER = "bank_transfer"

_paypal_cache: dict[tuple[str, str, str | None, str], PayPalProvider] = {}


def test_provider(settings: Settings) -> TestProvider:
    return TestProvider(
        secret=settings.secret_key.get_secret_value().encode(), public_url=settings.workspace_url
    )


def providers(settings: Settings) -> dict[str, PaymentProvider]:
    """Providers with keys configured on this server, by provider name."""
    result: dict[str, PaymentProvider] = {}
    if settings.payments_test_provider:
        result["test"] = test_provider(settings)
    if settings.paypal_client_id and settings.paypal_client_secret:
        key = (
            settings.paypal_client_id,
            settings.paypal_client_secret.get_secret_value(),
            settings.paypal_webhook_id,
            settings.paypal_mode,
        )
        # One instance per configuration, so its access token is reused between requests.
        if key not in _paypal_cache:
            _paypal_cache[key] = PayPalProvider(
                client_id=key[0], client_secret=key[1], webhook_id=key[2], mode=key[3]
            )
        result["paypal"] = _paypal_cache[key]
    return result


def provider_for_method(settings: Settings, method: str) -> PaymentProvider | None:
    """The provider that takes payments for a method. Cards: a Kazakhstan acquirer once its adapter is
    added (it needs the journal's contract and keys); until then only the test provider in development."""
    available = providers(settings)
    if method == "card":
        return available.get("test")
    if method == "paypal":
        return available.get("paypal")
    return None


def method_of_provider(provider: str) -> str:
    return {"test": "card", "paypal": "paypal"}.get(provider, provider)
