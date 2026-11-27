import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { InvoicePage } from "./InvoicePage";

const INVOICE = {
  id: 3,
  submission_id: 9,
  number: "INV-2026-0003",
  status: "issued",
  currency: "KZT",
  amount: "100000.00",
  discount: "50000.00",
  discount_percent: 50,
  vat_percent: "12.00",
  tax: "6000.00",
  total: "56000.00",
  refunded: "0.00",
  payer_name: "Asel Author",
  payer_email: "asel@example.org",
  payer_organization: "Nazarbayev University",
  payer_address: "Astana",
  payer_tax_id: "",
  description: "Article publication fee: JRN-2026-0009",
  due_date: "2026-12-27",
  overdue: false,
  issued_at: "2026-11-27T10:00:00Z",
  paid_at: null,
  waived_at: null,
  voided_at: null,
  void_reason: "",
  pdf_url: "/api/v1/payments/invoices/3/pdf",
  payments: [] as unknown[],
};

const TRANSFER = {
  id: 21,
  method: "bank_transfer",
  provider: "bank_transfer",
  status: "succeeded",
  amount: "56000.00",
  currency: "KZT",
  refunded: "0.00",
  reference: "PP-77",
  failure_reason: "",
  created_at: "2026-11-27T11:00:00Z",
  completed_at: "2026-11-26T12:00:00Z",
  refunds: [] as unknown[],
};

describe("InvoicePage", () => {
  it("records a bank transfer for the outstanding amount and shows the invoice paid", async () => {
    const calls = mockApi({
      "GET /api/v1/payments/invoices/3": () => json(200, INVOICE),
      "POST /api/v1/payments/invoices/3/transfers": () =>
        json(200, { ...INVOICE, status: "paid", paid_at: "2026-11-27T11:00:00Z", payments: [TRANSFER] }),
    });
    renderPage(<InvoicePage />, { path: "/finance/invoices/:id", url: "/finance/invoices/3" });

    expect(await screen.findByText("Awaiting payment")).toBeInTheDocument();
    expect(screen.getByText("Waiver (50%)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download invoice" })).toHaveAttribute("href", INVOICE.pdf_url);

    await userEvent.click(screen.getByRole("button", { name: "Record a bank transfer" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("textbox", { name: "Amount received, KZT" })).toHaveValue("56000.00");
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Bank reference/ }), "PP-77");
    await userEvent.click(within(dialog).getByRole("button", { name: "Record transfer" }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const sent = calls.find((call) => call.method === "POST");
    expect(sent?.body).toMatchObject({ amount: "56000.00", reference: "PP-77" });
    expect(await screen.findByText("Paid")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download receipt" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record a bank transfer" })).not.toBeInTheDocument();
  });

  it("refunds part of a payment with a reason", async () => {
    const paid = { ...INVOICE, status: "paid", payments: [TRANSFER] };
    const calls = mockApi({
      "GET /api/v1/payments/invoices/3": () => json(200, paid),
      "POST /api/v1/payments/21/refunds": () =>
        json(200, {
          ...paid,
          refunded: "6000.00",
          payments: [
            {
              ...TRANSFER,
              refunded: "6000.00",
              refunds: [
                {
                  id: 5,
                  amount: "6000.00",
                  reason: "VAT charged by mistake",
                  status: "succeeded",
                  failure_reason: "",
                  created_at: "2026-11-27T12:00:00Z",
                  completed_at: "2026-11-27T12:00:00Z",
                },
              ],
            },
          ],
        }),
    });
    renderPage(<InvoicePage />, { path: "/finance/invoices/:id", url: "/finance/invoices/3" });

    await userEvent.click(await screen.findByRole("button", { name: "Refund" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/refunded outside the system/)).toBeInTheDocument();
    const amount = within(dialog).getByRole("textbox", { name: "Amount, KZT" });
    expect(amount).toHaveValue("56000.00");
    await userEvent.clear(amount);
    await userEvent.type(amount, "6000");
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Reason/ }), "VAT charged by mistake");
    await userEvent.click(within(dialog).getByRole("button", { name: "Refund" }));

    await waitFor(() => expect(calls.some((call) => call.path === "/api/v1/payments/21/refunds")).toBe(true));
    expect(calls.find((call) => call.path === "/api/v1/payments/21/refunds")?.body).toEqual({
      amount: "6000",
      reason: "VAT charged by mistake",
    });
    expect(await screen.findByText(/Refund 6\s000\.00 KZT · done/)).toBeInTheDocument();
  });
});
