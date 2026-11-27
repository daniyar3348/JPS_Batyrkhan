/** Words, colours and number formatting for the publication fee, shared by authors' and finance pages. */

interface Look {
  label: string;
  color: string;
}

export const INVOICE_STATUS: Record<string, Look> = {
  issued: { label: "Awaiting payment", color: "orange" },
  paid: { label: "Paid", color: "teal" },
  waived: { label: "Waived", color: "grape" },
  void: { label: "Void", color: "gray" },
  refunded: { label: "Refunded", color: "gray" },
};

export const PAYMENT_STATUS: Record<string, Look> = {
  created: { label: "Started", color: "gray" },
  pending: { label: "Waiting", color: "blue" },
  succeeded: { label: "Received", color: "teal" },
  failed: { label: "Failed", color: "red" },
  cancelled: { label: "Cancelled", color: "gray" },
};

export const WAIVER_STATUS: Record<string, Look> = {
  pending: { label: "Being considered", color: "blue" },
  approved: { label: "Approved", color: "teal" },
  rejected: { label: "Not approved", color: "red" },
};

export const METHOD_LABELS: Record<string, string> = {
  card: "Card",
  paypal: "PayPal",
  bank_transfer: "Bank transfer",
};

export function look(table: Record<string, Look>, status: string): Look {
  return table[status] ?? { label: status, color: "gray" };
}

/** "112000.00" → "112 000.00 KZT" (narrow no-break spaces between thousands, as on the invoice). */
export function money(value: string | number, currency: string): string {
  const number = typeof value === "number" ? value : Number(value);
  const [whole, cents = "00"] = number.toFixed(2).split(".");
  const grouped = (whole ?? "0").replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${grouped}.${cents} ${currency}`;
}
