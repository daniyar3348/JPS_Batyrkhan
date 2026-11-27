import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { FeePanel } from "./FeePanel";

const INVOICE = {
  id: 4,
  submission_id: 9,
  number: "INV-2026-0004",
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
  payer_organization: "",
  payer_address: "",
  payer_tax_id: "",
  description: "Article publication fee",
  due_date: "2026-12-27",
  overdue: false,
  issued_at: "2026-11-27T10:00:00Z",
  paid_at: null,
  waived_at: null,
  voided_at: null,
  void_reason: "",
  pdf_url: "/api/v1/payments/invoices/4/pdf",
  payments: [],
};

const BILLING = {
  enabled: true,
  fee_required: true,
  accepted: true,
  currency: "KZT",
  expected_fee: "100000.00",
  invoices: [INVOICE],
  waivers: [],
  can_request_waiver: true,
  waiver_policy: "",
  methods: [
    { method: "card", label: "Card", available: true, reason: "" },
    { method: "paypal", label: "PayPal", available: false, reason: "PayPal does not accept KZT" },
    { method: "bank_transfer", label: "Bank transfer", available: true, reason: "" },
  ],
  bank_details: {
    name: "Demo Journal LLP",
    tax_id: "123456789012",
    address: "",
    bank_name: "Halyk Bank",
    iban: "KZ123456789012345678",
    bic: "HSBKKZKX",
    kbe: "17",
    knp: "859",
  },
};

afterEach(() => vi.restoreAllMocks());

describe("FeePanel", () => {
  it("shows what is due and sends the payer to the provider's page", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const calls = mockApi({
      "GET /api/v1/submissions/9/billing": () => json(200, BILLING),
      "POST /api/v1/payments/invoices/4/checkout": () =>
        json(200, { payment_id: 12, redirect_url: "https://pay.example/checkout/12" }),
    });
    renderPage(<FeePanel submissionId={9} />);

    expect(await screen.findByText("Invoice INV-2026-0004")).toBeInTheDocument();
    expect(screen.getByText("Fee waiver (50%)")).toBeInTheDocument();
    // The page shows a narrow no-break space between thousands; the testing library reads it as a space.
    expect(screen.getByText("56 000.00 KZT")).toBeInTheDocument();
    expect(screen.getByText("KZ123456789012345678")).toBeInTheDocument();
    // PayPal cannot take tenge: the button is off, with the reason.
    expect(screen.getByRole("button", { name: "Pay with PayPal" })).toBeDisabled();
    expect(screen.getByText("PayPal: PayPal does not accept KZT.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Pay by card/i }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://pay.example/checkout/12"));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ method: "card" });
  });

  it("before acceptance, only explains the fee", async () => {
    mockApi({
      "GET /api/v1/submissions/9/billing": () =>
        json(200, { ...BILLING, accepted: false, invoices: [], can_request_waiver: true }),
    });
    renderPage(<FeePanel submissionId={9} />);
    expect(await screen.findByText(/charged only if the manuscript is accepted/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask for a waiver" })).toBeInTheDocument();
  });
});
