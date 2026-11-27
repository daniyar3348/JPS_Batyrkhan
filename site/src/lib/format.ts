const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

/** "27 November 2026". */
export function formatDate(iso: string | null | undefined): string {
  return iso ? DATE.format(new Date(iso)) : "";
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Money as the journal charges it: "100 000 KZT". */
export function formatMoney(amount: string, currency: string): string {
  const value = Number(amount);
  const text = new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  })
    .format(value)
    .replace(/,/g, " ");
  return `${text} ${currency}`;
}

/** Short names of common licences, for a readable label next to the link. */
export function licenceName(url: string): string {
  const match = url.match(/creativecommons\.org\/licenses\/([a-z-]+)\/([\d.]+)/);
  if (match) return `CC ${match[1]?.toUpperCase()} ${match[2]}`;
  if (url.includes("creativecommons.org/publicdomain/zero")) return "CC0 1.0";
  return "Licence";
}

/** The first sentences of a text, for descriptions in search results and link previews. */
export function excerpt(text: string, length = 240): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= length) return flat;
  const cut = flat.slice(0, length);
  return `${cut.slice(0, cut.lastIndexOf(" "))}…`;
}
