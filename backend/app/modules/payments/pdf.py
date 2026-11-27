"""Invoices and receipts as PDF, drawn on request (they are small, and always match the current data)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF

from app.modules.journals.models import Journal
from app.modules.journals.payment_settings import PaymentSettings
from app.modules.payments.models import Invoice, InvoiceStatus
from app.modules.payments.money import format_money

FONTS = Path(__file__).parent / "fonts"
MINUS = "\u2212"  # a real minus sign for the discount line


def _date(value: date | datetime | None) -> str:
    return value.strftime("%d %B %Y") if value else ""


class _Document(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4")
        # DejaVu covers Latin, Cyrillic (Kazakh and Russian names) and common symbols.
        self.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=18)


def render_invoice(invoice: Invoice, journal: Journal, settings: PaymentSettings) -> bytes:
    """The invoice; once paid, the same document titled as a receipt."""
    receipt = invoice.status in (InvoiceStatus.PAID, InvoiceStatus.REFUNDED)
    payee = settings.payee
    pdf = _Document()
    pdf.set_title(f"{'Receipt' if receipt else 'Invoice'} {invoice.number}")
    pdf.set_author(payee.name or journal.name)
    pdf.add_page()
    width = pdf.epw

    pdf.set_font("DejaVu", "B", 18)
    pdf.cell(width / 2, 10, "RECEIPT" if receipt else "INVOICE")
    pdf.set_font("DejaVu", "", 10)
    pdf.multi_cell(width / 2, 5, f"{invoice.number}\nIssued {_date(invoice.issued_at)}", align="R")
    pdf.ln(4)

    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(width / 2, 6, "From")
    pdf.cell(width / 2, 6, "To", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9.5)
    seller = "\n".join(
        line
        for line in (
            payee.name or journal.publisher or journal.name,
            payee.address,
            f"Tax ID (BIN): {payee.tax_id}" if payee.tax_id else "",
            journal.contact_email,
        )
        if line
    )
    buyer = "\n".join(
        line
        for line in (
            invoice.payer_organization,
            invoice.payer_name,
            invoice.payer_address,
            f"Tax ID: {invoice.payer_tax_id}" if invoice.payer_tax_id else "",
            invoice.payer_email,
        )
        if line
    )
    top = pdf.get_y()
    pdf.multi_cell(width / 2 - 4, 5, seller)
    left_end = pdf.get_y()
    pdf.set_xy(pdf.l_margin + width / 2, top)
    pdf.multi_cell(width / 2, 5, buyer)
    pdf.set_y(max(left_end, pdf.get_y()) + 8)

    # The lines of the invoice.
    pdf.set_font("DejaVu", "B", 9.5)
    pdf.set_fill_color(238, 240, 247)
    pdf.cell(width * 0.7, 8, "Description", border="B", fill=True)
    pdf.cell(width * 0.3, 8, "Amount", border="B", fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9.5)
    rows = [(invoice.description, format_money(invoice.amount, invoice.currency))]
    if invoice.discount:
        rows.append(
            (
                f"Fee waiver ({invoice.discount_percent}%)",
                MINUS + format_money(invoice.discount, invoice.currency),
            )
        )
    if invoice.vat_percent:
        rows.append((f"VAT {invoice.vat_percent.normalize()}%", format_money(invoice.tax, invoice.currency)))
    for label, value in rows:
        y = pdf.get_y()
        pdf.multi_cell(width * 0.7, 6, label, border="B")
        end = pdf.get_y()
        pdf.set_xy(pdf.l_margin + width * 0.7, y)
        pdf.cell(width * 0.3, end - y, value, border="B", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(width * 0.7, 9, "Total")
    pdf.cell(
        width * 0.3,
        9,
        format_money(invoice.total, invoice.currency),
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    pdf.set_font("DejaVu", "", 9.5)
    if receipt:
        paid = [p for p in invoice.payments if p.status == "succeeded"]
        for payment in paid:
            method = {"bank_transfer": "bank transfer", "paypal": "PayPal", "test": "card (test)"}.get(
                payment.provider, payment.provider
            )
            pdf.multi_cell(
                width,
                5,
                f"Paid {format_money(payment.amount, payment.currency)} by {method} on {_date(payment.completed_at)}.",
            )
        if invoice.refunded:
            pdf.multi_cell(width, 5, f"Refunded: {format_money(invoice.refunded, invoice.currency)}.")
    elif invoice.status == InvoiceStatus.WAIVED:
        pdf.multi_cell(width, 5, "The fee has been waived. Nothing is due.")
    else:
        pdf.set_font("DejaVu", "B", 9.5)
        pdf.multi_cell(
            width, 5, f"Due by {_date(invoice.due_date)}. Please quote {invoice.number} with your payment."
        )
        pdf.set_font("DejaVu", "", 9.5)
        if settings.methods.bank_transfer and payee.iban:
            pdf.ln(2)
            bank = "\n".join(
                line
                for line in (
                    "Bank transfer:",
                    f"Beneficiary: {payee.name}" if payee.name else "",
                    f"BIN: {payee.tax_id}" if payee.tax_id else "",
                    f"Bank: {payee.bank_name}" if payee.bank_name else "",
                    f"IBAN: {payee.iban}",
                    f"BIC/SWIFT: {payee.bic}" if payee.bic else "",
                    f"KBe: {payee.kbe}" if payee.kbe else "",
                    f"KNP: {payee.knp}" if payee.knp else "",
                    f"Payment reference: {invoice.number}",
                )
                if line
            )
            pdf.multi_cell(width, 5, bank)
    if settings.invoice_note:
        pdf.ln(4)
        pdf.set_font("DejaVu", "", 8.5)
        pdf.multi_cell(width, 4.5, settings.invoice_note)
    return bytes(pdf.output())
