"""E-mails about the publication fee. They go to the authors and the finance managers only."""

from __future__ import annotations

from app.modules.journals.email_templates import TemplateSpec, register

GROUP = "Payments"

INVOICE = {
    "submissionNumber": "Manuscript number",
    "submissionTitle": "Title of the manuscript",
    "invoiceNumber": "Invoice number, e.g. INV-2026-0017",
    "invoiceTotal": "Amount due, with the currency",
    "dueDate": "Date by which the invoice should be paid",
    "invoiceUrl": "Link to the invoice in the editorial workspace",
}

ISSUED = register(
    TemplateSpec(
        key="invoice_issued",
        group=GROUP,
        name="Invoice for the publication fee",
        description="Sent to the submitting author when the manuscript is accepted and the fee is invoiced.",
        recipient="Submitting author",
        subject="{invoiceNumber}: publication fee for {submissionNumber}",
        body=(
            "Dear {recipientName},\n\n"
            "Congratulations again on the acceptance of “{submissionTitle}” ({submissionNumber}).\n\n"
            "The publication fee is {invoiceTotal}, due by {dueDate} (invoice {invoiceNumber}). "
            "You can pay by card or the other available methods, download the invoice, or change the payer's "
            "details (for example, to have your institution pay) here:\n\n{invoiceUrl}\n\n"
            "The article is published once the fee is paid. If you cannot pay it, you can ask for a waiver "
            "on the same page.\n\n"
            "{journalName}"
        ),
        variables=INVOICE,
    )
)

REMINDER = register(
    TemplateSpec(
        key="invoice_reminder",
        group=GROUP,
        name="Reminder: invoice due",
        description="Sent automatically before and after the due date of an unpaid invoice.",
        recipient="Payer",
        subject="Reminder: {invoiceNumber} is due on {dueDate}",
        body=(
            "Dear {recipientName},\n\n"
            "This is a reminder that invoice {invoiceNumber} for the publication of “{submissionTitle}” "
            "({invoiceTotal}) is due on {dueDate}. You can pay it here:\n\n{invoiceUrl}\n\n"
            "If you have already paid, please ignore this message.\n\n"
            "{journalName}"
        ),
        variables=INVOICE,
    )
)

RECEIVED = register(
    TemplateSpec(
        key="payment_received",
        group=GROUP,
        name="Payment received",
        description="Sent when an invoice is paid; the receipt can be downloaded from the link.",
        recipient="Payer",
        subject="Payment received: {invoiceNumber}",
        body=(
            "Dear {recipientName},\n\n"
            "Thank you: we have received {paidAmount} for invoice {invoiceNumber} "
            "(publication of “{submissionTitle}”). You can download the receipt here:\n\n{invoiceUrl}\n\n"
            "{journalName}"
        ),
        variables={**INVOICE, "paidAmount": "Amount received, with the currency"},
    )
)

WAIVER_DECISION = register(
    TemplateSpec(
        key="waiver_decision",
        group=GROUP,
        name="Fee waiver decision",
        description="Sent to the author when the finance manager decides on a waiver request.",
        recipient="Author",
        subject="{submissionNumber}: your request for a fee waiver",
        body=("Dear {recipientName},\n\n{decisionText}\n\n{note}\n\n{journalName}"),
        variables={
            "submissionNumber": INVOICE["submissionNumber"],
            "submissionTitle": INVOICE["submissionTitle"],
            "decisionText": "What was decided, e.g. that 50% of the fee is waived",
            "note": "The finance manager's note",
        },
    )
)

REFUNDED = register(
    TemplateSpec(
        key="refund_issued",
        group=GROUP,
        name="Refund",
        description="Sent to the payer when a payment is refunded.",
        recipient="Payer",
        subject="Refund for {invoiceNumber}",
        body=(
            "Dear {recipientName},\n\n"
            "We have refunded {refundAmount} for invoice {invoiceNumber}.\n\n"
            "Reason: {reason}\n\n"
            "Depending on your bank or payment provider, it may take a few days to appear.\n\n"
            "{journalName}"
        ),
        variables={
            "invoiceNumber": INVOICE["invoiceNumber"],
            "refundAmount": "Amount refunded, with the currency",
            "reason": "Why the payment was refunded",
        },
    )
)

WAIVER_REQUESTED = register(
    TemplateSpec(
        key="waiver_requested_finance",
        group=GROUP,
        name="Waiver requested (to finance)",
        description="Sent to the finance managers when an author asks for a fee waiver.",
        recipient="Finance managers",
        subject="Waiver request for {submissionNumber}",
        body=(
            "Dear {recipientName},\n\n"
            "{authorName} asks for a {percent}% waiver of the publication fee for {submissionNumber}.\n\n"
            "Reason:\n{reason}\n\n"
            "Decide here:\n\n{financeUrl}"
        ),
        variables={
            "submissionNumber": INVOICE["submissionNumber"],
            "authorName": "Name of the author who asked",
            "percent": "Share of the fee the author asks to waive",
            "reason": "The author's reason",
            "financeUrl": "Link to the waiver requests",
        },
    )
)

ATTENTION = register(
    TemplateSpec(
        key="payments_attention_finance",
        group=GROUP,
        name="Payments needing attention (to finance)",
        description="Sent to the finance managers when a payment does not match its invoice or is stuck.",
        recipient="Finance managers",
        subject="Payments need your attention",
        body="Dear {recipientName},\n\n{problems}\n\nReview them here:\n\n{financeUrl}",
        variables={"problems": "The list of problems found", "financeUrl": "Link to the invoices"},
    )
)
