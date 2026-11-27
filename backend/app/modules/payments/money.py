"""Amounts on invoices. Decimal throughout, rounded half up to the cent at each printed line."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
# Thousands are separated by a narrow no-break space (12 500.00 KZT), as in Kazakh and Russian usage.
THOUSANDS = "\u202f"


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Totals:
    amount: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal


def totals(amount: Decimal, *, discount_percent: int, vat_percent: Decimal) -> Totals:
    """Fee, minus the waiver discount, plus VAT on what remains."""
    amount = cents(amount)
    discount = cents(amount * Decimal(discount_percent) / 100)
    net = amount - discount
    tax = cents(net * vat_percent / 100)
    return Totals(amount=amount, discount=discount, tax=tax, total=net + tax)


def format_money(value: Decimal, currency: str) -> str:
    return f"{value:,.2f} {currency}".replace(",", THOUSANDS)
