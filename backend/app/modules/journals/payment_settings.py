"""What the journal charges and how authors can pay. Stored in ``Journal.settings["payments"]``.

There is one fee: for publication, charged after acceptance (APC). Amounts are decimals with two places.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.journals.models import Journal

Money = Annotated[Decimal, Field(ge=0, le=Decimal("10000000"), max_digits=12, decimal_places=2)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]

CURRENCIES = ("KZT", "USD", "EUR", "GBP", "RUB")


class Payee(BaseModel):
    """The journal's legal entity, printed on invoices and used for bank transfers."""

    name: Short = ""
    tax_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] = ""  # BIN in Kazakhstan
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    bank_name: Short = ""
    iban: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""
    bic: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] = ""
    # Kazakhstan: beneficiary code and payment purpose code; elsewhere leave empty.
    kbe: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5)] = ""
    knp: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5)] = ""


class Methods(BaseModel):
    card: bool = True
    paypal: bool = True
    bank_transfer: bool = True


class PaymentSettings(BaseModel):
    enabled: bool = False
    currency: str = Field(default="KZT", pattern=r"^[A-Z]{3}$")
    fee: Money = Decimal("0")
    # Different fees for some sections (e.g. short communications); missing sections pay ``fee``.
    section_fees: dict[int, Money] = Field(default_factory=dict)
    vat_percent: Decimal = Field(default=Decimal("0"), ge=0, le=50, max_digits=5, decimal_places=2)
    due_days: int = Field(default=30, ge=1, le=180)
    # Days relative to the due date (negative: before it) on which unpaid invoices are followed up.
    reminder_days: list[Annotated[int, Field(ge=-60, le=90)]] = Field(
        default_factory=lambda: [-7, 0, 7], max_length=6
    )
    methods: Methods = Field(default_factory=Methods)
    payee: Payee = Field(default_factory=Payee)
    invoice_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    waiver_policy: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""

    @field_validator("currency")
    @classmethod
    def _known_currency(cls, value: str) -> str:
        if value not in CURRENCIES:
            raise ValueError(f"Choose one of: {', '.join(CURRENCIES)}")
        return value

    @field_validator("reminder_days")
    @classmethod
    def _sorted(cls, value: list[int]) -> list[int]:
        return sorted(set(value))

    def fee_for(self, section_id: int) -> Decimal:
        return self.section_fees.get(section_id, self.fee)


def payment_settings(journal: Journal) -> PaymentSettings:
    return PaymentSettings.model_validate(journal.settings.get("payments", {}))


class MethodAvailability(BaseModel):
    method: str
    label: str
    # Configured on the server (provider keys present) and able to charge the journal's currency.
    available: bool
    reason: str = ""


class PaymentSettingsOut(PaymentSettings):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: int
    currencies: list[str]
    method_availability: list[MethodAvailability]
