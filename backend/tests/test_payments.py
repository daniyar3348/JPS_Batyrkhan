"""Stage 4: the publication fee. Invoices on acceptance, paying, refunds, waivers, and who sees what."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pypdf import PdfReader
from sqlalchemy import update

from app.core.config import Settings
from app.core.db import utcnow
from app.core.email import EmailMessage
from app.modules.journals.models import Section
from app.modules.journals.permissions import Role
from app.modules.payments.models import Invoice, Payment
from app.modules.payments.providers.base import CheckoutRequest, InvalidNotification, ProviderStatus
from app.modules.payments.providers.paypal import PayPalProvider
from app.modules.payments.providers.registry import test_provider as card_test_provider
from app.modules.payments.service import PaymentService
from tests.conftest import ClientFactory, UserFactory, problem
from tests.manuscripts import complete_draft

SETTINGS = {
    "enabled": True,
    "currency": "KZT",
    "fee": "100000.00",
    "vat_percent": "12",
    "due_days": 30,
    "methods": {"card": True, "paypal": True, "bank_transfer": True},
    "payee": {
        "name": "Demo Journal LLP",
        "tax_id": "123456789012",
        "address": "Almaty",
        "bank_name": "Halyk Bank",
        "iban": "KZ123456789012345678",
        "bic": "HSBKKZKX",
        "kbe": "17",
        "knp": "859",
    },
    "waiver_policy": "Authors from low-income countries may ask for a waiver.",
}


@dataclass
class Desk:
    author: AsyncClient
    chief: AsyncClient
    finance: AsyncClient
    submission_id: int
    run_jobs: Any
    outbox: list[EmailMessage]

    def url(self, path: str = "") -> str:
        return f"/api/v1/submissions/{self.submission_id}{path}"

    async def mail(self, address: str) -> list[EmailMessage]:
        await self.run_jobs()
        return [m for m in self.outbox if m.to == address]

    async def billing(self, http: AsyncClient | None = None) -> dict[str, Any]:
        response = await (http or self.author).get(self.url("/billing"))
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def accept(self) -> dict[str, Any]:
        response = await self.chief.post(self.url("/decisions"), json={"decision": "accept"})
        assert response.status_code == 201, response.text
        return await self.billing()


async def save_settings(finance: AsyncClient, **changes: Any) -> dict[str, Any]:
    current = await finance.get("/api/v1/journal/payment-settings")
    body = {
        k: v for k, v in current.json().items() if k not in ("version", "currencies", "method_availability")
    }
    saved = await finance.put(
        "/api/v1/journal/payment-settings",
        json={**body, **SETTINGS, **changes},
        headers={"If-Match": current.headers["etag"]},
    )
    assert saved.status_code == 200, saved.text
    result: dict[str, Any] = saved.json()
    return result


@pytest.fixture
async def desk(
    make_user: UserFactory,
    signed_in: ClientFactory,
    author: AsyncClient,
    sections: dict[str, Section],
    run_jobs,
    outbox: list[EmailMessage],
) -> Desk:
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF], given_name="Daniyar", family_name="Chief")
    await make_user("money@example.org", [Role.FINANCE_MANAGER], given_name="Farida", family_name="Finance")
    finance = await signed_in("money@example.org")
    await save_settings(finance, section_fees={str(sections["REV"].id): "50000.00"})
    draft = await complete_draft(author, sections["ART"].id, run_jobs)
    assert (await author.post(f"/api/v1/submissions/{draft['id']}/submit")).status_code == 200
    await run_jobs()
    return Desk(
        author=author,
        chief=await signed_in("chief@example.org"),
        finance=finance,
        submission_id=draft["id"],
        run_jobs=run_jobs,
        outbox=outbox,
    )


# ---------------------------------------------------------------------- invoices


async def test_no_invoice_before_acceptance_then_one_with_waiver_and_vat(desk: Desk):
    before = await desk.billing()
    assert before["invoices"] == [] and before["fee_required"] and not before["accepted"]
    assert before["expected_fee"] == "100000.00" and before["can_request_waiver"]

    # The author asks for a waiver before the decision; the finance manager, not the editor, decides.
    asked = await desk.author.post(
        desk.url("/waiver-requests"), json={"percent": 60, "reason": "No grant funding"}
    )
    assert asked.status_code == 201, asked.text
    assert "No grant funding" in (await desk.mail("money@example.org"))[-1].text
    assert not (
        await desk.author.post(desk.url("/waiver-requests"), json={"percent": 10, "reason": "x"})
    ).is_success
    [waiver] = (await desk.finance.get("/api/v1/payments/waiver-requests")).json()
    decided = await desk.finance.post(
        f"/api/v1/payments/waiver-requests/{waiver['id']}/decision",
        json={"approve": True, "percent": 50, "note": "Half, per our policy."},
    )
    assert decided.json()["approved_percent"] == 50
    assert "50% of the publication fee" in (await desk.mail("asel@example.org"))[-1].text

    billing = await desk.accept()
    [invoice] = billing["invoices"]
    year = utcnow().year
    assert invoice["number"] == f"INV-{year}-0001" and invoice["status"] == "issued"
    assert (invoice["amount"], invoice["discount"], invoice["tax"], invoice["total"]) == (
        "100000.00",
        "50000.00",
        "6000.00",
        "56000.00",
    )
    assert invoice["payer_name"] == "Asel Author" and not invoice["overdue"]
    issued = (await desk.mail("asel@example.org"))[-1]
    assert issued.subject.startswith(f"INV-{year}-0001") and "?tab=fee" in issued.text
    assert "56\u202f000.00 KZT" in issued.text  # a narrow no-break space between thousands

    # The editors see only that the fee is not settled yet; nothing about money or waivers.
    workflow = (await desk.chief.get(desk.url("/workflow"))).json()
    assert workflow["fee_settled"] is False
    assert (await desk.chief.get(desk.url("/billing"))).status_code == 404
    assert (await desk.chief.get(f"/api/v1/payments/invoices/{invoice['id']}")).status_code == 403
    assert (await desk.chief.get(f"/api/v1/payments/invoices/{invoice['id']}/pdf")).status_code == 404
    assert (await desk.chief.get("/api/v1/payments/waiver-requests")).status_code == 403
    log = (await desk.chief.get(desk.url("/emails"))).json()
    assert not any(e["template_key"] in ("invoice_issued", "waiver_decision") for e in log)


async def test_section_fees_and_no_fee(desk: Desk, sections: dict[str, Section], run_jobs):
    # A manuscript in the Reviews section pays that section's fee.
    review = await complete_draft(desk.author, sections["REV"].id, run_jobs, title="A review")
    await desk.author.post(f"/api/v1/submissions/{review['id']}/submit")
    await desk.chief.post(f"/api/v1/submissions/{review['id']}/decisions", json={"decision": "accept"})
    [invoice] = (await desk.author.get(f"/api/v1/submissions/{review['id']}/billing")).json()["invoices"]
    assert (invoice["amount"], invoice["total"]) == ("50000.00", "56000.00")

    # Without a fee there is no invoice, and the fee counts as settled.
    await save_settings(desk.finance, fee="0.00")
    billing = await desk.accept()
    assert billing["invoices"] == [] and billing["fee_required"] is False
    assert (await desk.chief.get(desk.url("/workflow"))).json()["fee_settled"] is True


async def test_pay_with_the_test_card_provider(desk: Desk, app: FastAPI, settings: Settings):
    invoice = (await desk.accept())["invoices"][0]
    methods = {m["method"]: m for m in (await desk.billing())["methods"]}
    assert methods["card"]["available"] and methods["bank_transfer"]["available"]
    assert not methods["paypal"]["available"]

    checkout = await desk.author.post(
        f"/api/v1/payments/invoices/{invoice['id']}/checkout", json={"method": "card"}
    )
    assert checkout.status_code == 200, checkout.text
    page_url = checkout.json()["redirect_url"]
    assert page_url.startswith("http://workspace.test/api/v1/payments/test-checkout/")
    path = page_url.removeprefix("http://workspace.test")
    page = await desk.author.get(path)
    assert page.status_code == 200 and "112,000.00 KZT" in page.text

    # Before the provider says so, coming back to the site proves nothing.
    status = await desk.author.post(f"/api/v1/payments/{checkout.json()['payment_id']}/confirm")
    assert status.json()["status"] == "pending" and status.json()["invoice_status"] == "issued"

    paid = await desk.author.post(
        path, content=b"action=pay", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert paid.status_code == 303
    assert (
        paid.headers["location"]
        == f"http://workspace.test/payments/return?payment={checkout.json()['payment_id']}"
    )
    billing = await desk.billing()
    [done] = billing["invoices"]
    assert done["status"] == "paid" and done["payments"][0]["status"] == "succeeded"
    assert done["payments"][0]["method"] == "card"
    assert "Payment received" in (await desk.mail("asel@example.org"))[-1].subject
    assert (await desk.chief.get(desk.url("/workflow"))).json()["fee_settled"] is True
    assert billing["can_request_waiver"] is False

    # A repeated or forged notification changes nothing.
    provider = card_test_provider(settings)
    data = provider.read_token(path.rsplit("/", 1)[1])
    headers, body = provider.notification(data, succeeded=True)
    first = await desk.author.post("/api/v1/payments/webhooks/test", content=body, headers=headers)
    again = await desk.author.post("/api/v1/payments/webhooks/test", content=body, headers=headers)
    assert first.json()["results"] == ["already recorded"] and again.json()["results"] == ["duplicate"]
    forged = await desk.author.post(
        "/api/v1/payments/webhooks/test", content=body.replace(b"112000", b"1"), headers=headers
    )
    assert forged.status_code == 400 and problem(forged)["code"] == "invalid_notification"


async def test_a_different_amount_is_never_accepted(desk: Desk, settings: Settings):
    invoice = (await desk.accept())["invoices"][0]
    checkout = await desk.author.post(
        f"/api/v1/payments/invoices/{invoice['id']}/checkout", json={"method": "card"}
    )
    provider = card_test_provider(settings)
    data = provider.read_token(checkout.json()["redirect_url"].rsplit("/", 1)[1])
    headers, body = provider.notification({**data, "amount": "1.00"}, succeeded=True)
    response = await desk.author.post("/api/v1/payments/webhooks/test", content=body, headers=headers)
    assert response.json()["results"] == ["amount mismatch"]
    assert (await desk.billing())["invoices"][0]["status"] == "issued"
    assert "expected 112000.00 KZT" in (await desk.mail("money@example.org"))[-1].text


async def test_bank_transfer_refunds_void_and_reissue(desk: Desk):
    invoice = (await desk.accept())["invoices"][0]
    url = f"/api/v1/payments/invoices/{invoice['id']}"
    part = await desk.finance.post(
        f"{url}/transfers", json={"amount": "100000.00", "reference": "PP-1", "paid_on": "2026-11-20"}
    )
    assert part.json()["status"] == "issued"  # not all of it yet
    rest = await desk.finance.post(
        f"{url}/transfers", json={"amount": "12000.00", "reference": "PP-2", "paid_on": "2026-11-21"}
    )
    assert rest.json()["status"] == "paid"
    assert (
        await desk.author.post(f"{url}/transfers", json={"amount": "1", "paid_on": "2026-11-21"})
    ).status_code == 403

    first, second = rest.json()["payments"]
    too_much = await desk.finance.post(
        f"/api/v1/payments/{second['id']}/refunds", json={"amount": "12000.01", "reason": "x"}
    )
    assert problem(too_much)["code"] == "invalid_amount"
    refunded = await desk.finance.post(
        f"/api/v1/payments/{second['id']}/refunds",
        json={"amount": "12000.00", "reason": "Paid twice by mistake"},
    )
    assert refunded.json()["refunded"] == "12000.00" and refunded.json()["status"] == "paid"
    assert "Paid twice by mistake" in (await desk.mail("asel@example.org"))[-1].text
    full = await desk.finance.post(
        f"/api/v1/payments/{first['id']}/refunds", json={"amount": "100000.00", "reason": "Withdrawn"}
    )
    assert full.json()["status"] == "refunded"

    # The finance lists.
    listed = (await desk.finance.get("/api/v1/payments/invoices", params={"status": "refunded"})).json()
    assert listed["total"] == 1 and listed["items"][0]["submission_number"].startswith("JRN-")
    summary = (await desk.finance.get("/api/v1/payments/summary")).json()
    assert summary == [{"currency": "KZT", "status": "refunded", "count": 1, "amount": "112000.00"}]
    assert (await desk.chief.get("/api/v1/payments/invoices")).status_code == 403

    # Paid invoices cannot be voided; unpaid ones can, and a new one is issued.
    assert problem(await desk.finance.post(f"{url}/void", json={"reason": "x"}))["code"] == "invoice_closed"


async def test_void_and_reissue(desk: Desk):
    invoice = (await desk.accept())["invoices"][0]
    url = f"/api/v1/payments/invoices/{invoice['id']}"
    voided = await desk.finance.post(f"{url}/void", json={"reason": "Wrong section fee"})
    assert voided.json()["status"] == "void"
    assert (await desk.chief.get(desk.url("/workflow"))).json()["fee_settled"] is False
    again = await desk.finance.post(desk.url("/invoices"))
    assert again.status_code == 201 and again.json()["number"].endswith("-0002")
    assert problem(await desk.finance.post(desk.url("/invoices")))["code"] == "invoice_exists"


async def test_full_waiver_after_the_invoice(desk: Desk):
    invoice = (await desk.accept())["invoices"][0]
    await desk.author.post(desk.url("/waiver-requests"), json={"percent": 100, "reason": "Student author"})
    [waiver] = (await desk.finance.get("/api/v1/payments/waiver-requests")).json()
    await desk.finance.post(
        f"/api/v1/payments/waiver-requests/{waiver['id']}/decision", json={"approve": True}
    )
    billing = await desk.billing()
    assert billing["invoices"][0]["status"] == "waived" and billing["invoices"][0]["total"] == "0.00"
    assert (await desk.chief.get(desk.url("/workflow"))).json()["fee_settled"] is True
    checkout = await desk.author.post(
        f"/api/v1/payments/invoices/{invoice['id']}/checkout", json={"method": "card"}
    )
    assert problem(checkout)["code"] == "invoice_closed"


async def test_payer_details_and_pdf(desk: Desk):
    invoice = (await desk.accept())["invoices"][0]
    changed = await desk.author.patch(
        f"/api/v1/payments/invoices/{invoice['id']}/payer",
        json={
            "payer_name": "Асель Автор",
            "payer_email": "accounts@university.kz",
            "payer_organization": "Казахский национальный университет",
            "payer_address": "Almaty, al-Farabi 71",
            "payer_tax_id": "990140000000",
        },
    )
    assert changed.status_code == 200, changed.text
    pdf = await desk.author.get(f"/api/v1/payments/invoices/{invoice['id']}/pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    for expected in (
        "INVOICE",
        invoice["number"],
        "Асель Автор",
        "Казахский национальный университет",
        "KZ123456789012345678",
    ):
        assert expected in text, expected
    await desk.finance.post(
        f"/api/v1/payments/invoices/{invoice['id']}/transfers",
        json={"amount": "112000.00", "paid_on": "2026-11-20"},
    )
    receipt = await desk.author.get(f"/api/v1/payments/invoices/{invoice['id']}/pdf")
    assert "RECEIPT" in PdfReader(io.BytesIO(receipt.content)).pages[0].extract_text()
    assert "receipt.pdf" in receipt.headers["content-disposition"]


async def test_other_authors_and_settings_access(
    desk: Desk, make_user: UserFactory, signed_in: ClientFactory
):
    await make_user("other@example.org", [Role.AUTHOR])
    other = await signed_in("other@example.org")
    invoice = (await desk.accept())["invoices"][0]
    assert (await other.get(desk.url("/billing"))).status_code == 404
    assert (await other.get(f"/api/v1/payments/invoices/{invoice['id']}/pdf")).status_code == 404
    assert (
        await other.post(f"/api/v1/payments/invoices/{invoice['id']}/checkout", json={"method": "card"})
    ).status_code == 404
    assert (await desk.author.get("/api/v1/journal/payment-settings")).status_code == 403
    settings = (await desk.finance.get("/api/v1/journal/payment-settings")).json()
    availability = {m["method"]: m for m in settings["method_availability"]}
    assert (
        availability["card"]["available"]
        and availability["paypal"]["reason"] == "PayPal is not connected on the server"
    )
    bad = await desk.finance.put(
        "/api/v1/journal/payment-settings",
        json={**SETTINGS, "currency": "XYZ"},
        headers={"If-Match": f'"{settings["version"]}"'},
    )
    assert bad.status_code == 422


async def test_reminders_once(desk: Desk, app: FastAPI, settings: Settings):
    invoice = (await desk.accept())["invoices"][0]
    async with app.state.session_factory() as db:
        await db.execute(
            update(Invoice)
            .where(Invoice.id == invoice["id"])
            .values(due_date=utcnow().date() - timedelta(days=8))
        )
        await db.commit()

    async def run() -> int:
        async with app.state.session_factory() as db:
            sent = await PaymentService(db, settings).send_reminders()
            await db.commit()
            return sent

    assert await run() == 1 and await run() == 0
    assert (await desk.mail("asel@example.org"))[-1].subject.startswith(f"Reminder: {invoice['number']}")
    assert (await desk.billing())["invoices"][0]["overdue"] is True


class FakeCards:
    """Stands in for a provider whose API reports a payment the notification never brought."""

    name = "test"
    label = "Card"
    currencies = None

    def __init__(self, result: ProviderStatus) -> None:
        self.result = result

    async def complete(self, provider_ref: str) -> ProviderStatus:
        return self.result


async def test_reconciliation_settles_missed_notifications(
    desk: Desk, app: FastAPI, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    invoice = (await desk.accept())["invoices"][0]
    checkout = await desk.author.post(
        f"/api/v1/payments/invoices/{invoice['id']}/checkout", json={"method": "card"}
    )
    payment_id = checkout.json()["payment_id"]
    async with app.state.session_factory() as db:
        await db.execute(
            update(Payment).where(Payment.id == payment_id).values(created_at=utcnow() - timedelta(hours=1))
        )
        await db.commit()
    fake = FakeCards(
        ProviderStatus(kind="succeeded", capture_ref="txn_1", amount=Decimal("112000.00"), currency="KZT")
    )
    monkeypatch.setattr("app.modules.payments.service.providers", lambda _: {"test": fake})
    async with app.state.session_factory() as db:
        problems = await PaymentService(db, settings).reconcile()
        await db.commit()
    assert problems == []
    assert (await desk.billing())["invoices"][0]["status"] == "paid"


# ---------------------------------------------------------------------- PayPal adapter (mocked HTTP)


def paypal(handler: Any) -> PayPalProvider:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        response: httpx.Response = handler(request)
        return response

    return PayPalProvider(
        client_id="id", client_secret="secret", webhook_id="WH-1", transport=httpx.MockTransport(route)
    )


REQUEST = CheckoutRequest(
    payment_id=7,
    invoice_number="INV-2026-0001",
    amount=Decimal("120.00"),
    currency="USD",
    description="Article publication fee",
    payer_email="a@example.org",
    merchant_name="Demo Journal",
    return_url="https://journal.kz/payments/return?payment=7",
    cancel_url="https://journal.kz/payments/return?payment=7&cancelled=1",
)


async def test_paypal_checkout_capture_and_refund():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/v2/checkout/orders" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "ORDER-1",
                    "status": "PAYER_ACTION_REQUIRED",
                    "links": [
                        {
                            "rel": "payer-action",
                            "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1",
                        }
                    ],
                },
            )
        if path == "/v2/checkout/orders/ORDER-1" and request.method == "GET":
            return httpx.Response(200, json={"id": "ORDER-1", "status": "APPROVED"})
        if path == "/v2/checkout/orders/ORDER-1/capture":
            return httpx.Response(
                201,
                json={
                    "id": "ORDER-1",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": "CAP-1",
                                        "status": "COMPLETED",
                                        "amount": {"currency_code": "USD", "value": "120.00"},
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if path == "/v2/payments/captures/CAP-1/refund":
            return httpx.Response(201, json={"id": "REF-1", "status": "COMPLETED"})
        return httpx.Response(404, json={})

    provider = paypal(handler)
    checkout = await provider.create_checkout(REQUEST)
    assert checkout.provider_ref == "ORDER-1" and "checkoutnow" in checkout.redirect_url
    body = json.loads(seen[0].content)
    unit = body["purchase_units"][0]
    assert unit["amount"] == {"currency_code": "USD", "value": "120.00"} and unit["custom_id"] == "7"
    assert body["payment_source"]["paypal"]["experience_context"]["return_url"] == REQUEST.return_url
    assert seen[0].headers["PayPal-Request-Id"] == "jps-payment-7"

    status = await provider.complete("ORDER-1")
    assert (status.kind, status.capture_ref, status.amount, status.currency) == (
        "succeeded",
        "CAP-1",
        Decimal("120.00"),
        "USD",
    )

    refund = await provider.refund(
        refund_id=3,
        provider_ref="ORDER-1",
        capture_ref="CAP-1",
        amount=Decimal("20.00"),
        currency="USD",
        reason="Partial",
    )
    assert refund.succeeded and refund.provider_ref == "REF-1"
    assert seen[-1].headers["PayPal-Request-Id"] == "jps-refund-3"
    currencies = provider.currencies or frozenset()
    assert "KZT" not in currencies and "USD" in currencies


PAYPAL_HEADERS = {
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
    "paypal-transmission-id": "T-1",
    "paypal-transmission-sig": "c2lnbmF0dXJl",
    "paypal-transmission-time": "2026-11-27T10:00:00Z",
}


async def test_paypal_notifications_are_verified_by_paypal():
    verified: list[dict[str, Any]] = []
    answer = {"verification_status": "SUCCESS"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/notifications/verify-webhook-signature":
            verified.append(json.loads(request.content))
            return httpx.Response(200, json=answer)
        return httpx.Response(404, json={})

    provider = paypal(handler)
    event = {
        "id": "WH-EVT-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-1",
            "custom_id": "7",
            "status": "COMPLETED",
            "amount": {"currency_code": "USD", "value": "120.00"},
            "supplementary_data": {"related_ids": {"order_id": "ORDER-1"}},
        },
    }
    [notice] = await provider.parse_notification(PAYPAL_HEADERS, json.dumps(event).encode())
    assert (notice.kind, notice.provider_ref, notice.payment_id, notice.capture_ref) == (
        "succeeded",
        "ORDER-1",
        7,
        "CAP-1",
    )
    assert verified[0]["webhook_id"] == "WH-1" and verified[0]["transmission_sig"] == "c2lnbmF0dXJl"
    assert verified[0]["webhook_event"]["id"] == "WH-EVT-1"

    answer["verification_status"] = "FAILURE"
    with pytest.raises(InvalidNotification):
        await provider.parse_notification(PAYPAL_HEADERS, json.dumps(event).encode())
    with pytest.raises(InvalidNotification):
        await provider.parse_notification({}, json.dumps(event).encode())
