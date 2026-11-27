/**
 * "How to cite": an article in the common reference styles, and as BibTeX and RIS for reference managers.
 *
 * A formatted reference is a list of parts; italic parts are objects, so the page can show them in
 * italics and the copy button can give plain text.
 */

export interface CitedAuthor {
  given_name: string;
  family_name: string;
}

export interface CitedArticle {
  title: string;
  subtitle?: string;
  authors: CitedAuthor[];
  /** ISO date of the first publication. */
  published: string;
  volume?: number | null;
  issue?: string | null;
  pages?: string;
  doi?: string | null;
  url: string;
  abstract?: string;
  keywords?: string[];
}

export interface CitedJournal {
  name: string;
  abbreviation?: string;
  issn?: string | null;
  publisher?: string;
}

export type Part = string | { i: string };
export type Style = "apa" | "mla" | "chicago" | "harvard" | "vancouver";

export const STYLES: { id: Style; label: string }[] = [
  { id: "apa", label: "APA" },
  { id: "mla", label: "MLA" },
  { id: "chicago", label: "Chicago" },
  { id: "harvard", label: "Harvard" },
  { id: "vancouver", label: "Vancouver" },
];

export function plain(parts: Part[]): string {
  return parts.map((part) => (typeof part === "string" ? part : part.i)).join("");
}

// ---------------------------------------------------------------------------- pieces

function fullTitle(article: CitedArticle): string {
  return article.subtitle ? `${article.title}: ${article.subtitle}` : article.title;
}

function year(article: CitedArticle): string {
  return article.published.slice(0, 4);
}

/** "Jean-Paul Marie" → "J.-P. M." (with dots) or "JPM" (Vancouver). */
export function initials(given: string, dots = true): string {
  return given
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) =>
      word
        .split("-")
        .filter(Boolean)
        .map((piece) => (dots ? `${piece.charAt(0).toUpperCase()}.` : piece.charAt(0).toUpperCase()))
        .join(dots ? "-" : ""),
    )
    .join(dots ? " " : "");
}

/** People recorded with one name have it as the given name and no family name. */
function single(author: CitedAuthor): boolean {
  return !author.family_name;
}

function familyFirst(author: CitedAuthor, style: "initials" | "full"): string {
  if (single(author)) return author.given_name;
  if (style === "full") return `${author.family_name}, ${author.given_name}`;
  return `${author.family_name}, ${initials(author.given_name)}`;
}

function givenFirst(author: CitedAuthor): string {
  return single(author) ? author.given_name : `${author.given_name} ${author.family_name}`;
}

/** Page ranges take an en dash in most styles. */
function pageRange(pages: string | undefined, dash = "–"): string {
  return (pages ?? "").trim().replace(/\s*[-–]\s*/, dash);
}

function doiUrl(doi: string): string {
  return `https://doi.org/${doi}`;
}

function link(article: CitedArticle): string {
  return article.doi ? doiUrl(article.doi) : article.url;
}

function endWithPeriod(text: string): string {
  return /[.?!]$/.test(text) ? text : `${text}.`;
}

/** "Vol(No)" as in APA and Harvard: "1(2)", "1", or "" without a volume. */
function volumeIssue(article: CitedArticle): Part[] {
  if (article.volume == null) return article.issue ? [`(${article.issue})`] : [];
  return [{ i: String(article.volume) }, article.issue ? `(${article.issue})` : ""];
}

// ---------------------------------------------------------------------------- styles

/** APA 7th edition. */
function apa(article: CitedArticle, journal: CitedJournal): Part[] {
  const names = article.authors.map((a) => familyFirst(a, "initials"));
  let authors: string;
  if (names.length === 0) authors = "";
  else if (names.length === 1) authors = names[0] ?? "";
  else if (names.length <= 20) authors = `${names.slice(0, -1).join(", ")}, & ${names[names.length - 1]}`;
  else authors = `${names.slice(0, 19).join(", ")}, . . . ${names[names.length - 1]}`;
  const parts: Part[] = [];
  if (authors) parts.push(`${authors} `);
  parts.push(`(${year(article)}). ${endWithPeriod(fullTitle(article))} `, { i: journal.name });
  const vi = volumeIssue(article);
  if (vi.length) parts.push(", ", ...vi);
  if (article.pages) parts.push(`, ${pageRange(article.pages)}`);
  parts.push(`. ${link(article)}`);
  return parts;
}

/** MLA 9th edition. */
function mla(article: CitedArticle, journal: CitedJournal): Part[] {
  const [first, second] = article.authors;
  let authors = "";
  if (first && article.authors.length === 1) authors = familyFirst(first, "full");
  else if (first && second && article.authors.length === 2)
    authors = `${familyFirst(first, "full")}, and ${givenFirst(second)}`;
  else if (first) authors = `${familyFirst(first, "full")}, et al`;
  const parts: Part[] = [];
  if (authors) parts.push(`${endWithPeriod(authors)} `);
  parts.push(`“${endWithPeriod(fullTitle(article))}” `, { i: journal.name });
  if (article.volume != null) parts.push(`, vol. ${article.volume}`);
  if (article.issue) parts.push(`, no. ${article.issue}`);
  parts.push(`, ${year(article)}`);
  if (article.pages) parts.push(`, pp. ${pageRange(article.pages)}`);
  parts.push(`, ${article.doi ? doiUrl(article.doi) : article.url}.`);
  return parts;
}

/** Chicago 17th edition, author-date. */
function chicago(article: CitedArticle, journal: CitedJournal): Part[] {
  const names = article.authors.map((a, index) => (index === 0 ? familyFirst(a, "full") : givenFirst(a)));
  let authors: string;
  if (names.length <= 1) authors = names[0] ?? "";
  else if (names.length === 2) authors = `${names[0]}, and ${names[1]}`;
  else if (names.length <= 10) authors = `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
  else authors = `${names.slice(0, 7).join(", ")}, et al`;
  const parts: Part[] = [];
  if (authors) parts.push(`${endWithPeriod(authors)} `);
  parts.push(`${year(article)}. “${endWithPeriod(fullTitle(article))}” `, { i: journal.name });
  if (article.volume != null) parts.push(` ${article.volume}`);
  if (article.issue) parts.push(` (${article.issue})`);
  if (article.pages) parts.push(`: ${pageRange(article.pages)}`);
  parts.push(`. ${link(article)}.`);
  return parts;
}

/** Harvard (Cite Them Right). */
function harvard(article: CitedArticle, journal: CitedJournal): Part[] {
  const names = article.authors.map((a) => familyFirst(a, "initials"));
  let authors: string;
  if (names.length <= 1) authors = names[0] ?? "";
  else if (names.length <= 3) authors = `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  else authors = `${names[0]} et al.`;
  const parts: Part[] = [];
  if (authors) parts.push(`${authors} `);
  parts.push(`(${year(article)}) ‘${fullTitle(article)}’, `, { i: journal.name });
  const vi = volumeIssue(article);
  if (vi.length) parts.push(", ", ...vi);
  if (article.pages) parts.push(`, pp. ${pageRange(article.pages)}`);
  parts.push(article.doi ? `. doi: ${article.doi}.` : `. Available at: ${article.url}.`);
  return parts;
}

/** Vancouver (ICMJE / NLM). */
function vancouver(article: CitedArticle, journal: CitedJournal): Part[] {
  const names = article.authors.map((a) =>
    single(a) ? a.given_name : `${a.family_name} ${initials(a.given_name, false)}`,
  );
  const authors = names.length > 6 ? `${names.slice(0, 6).join(", ")}, et al` : names.join(", ");
  const parts: Part[] = [];
  if (authors) parts.push(`${endWithPeriod(authors)} `);
  parts.push(
    `${endWithPeriod(fullTitle(article))} ${journal.abbreviation || journal.name}. ${year(article)}`,
  );
  if (article.volume != null) parts.push(`;${article.volume}`);
  if (article.issue) parts.push(`(${article.issue})`);
  if (article.pages) parts.push(`:${pageRange(article.pages, "-")}`);
  parts.push(article.doi ? `. doi:${article.doi}` : `. Available from: ${article.url}`);
  return parts;
}

const FORMATTERS: Record<Style, (article: CitedArticle, journal: CitedJournal) => Part[]> = {
  apa,
  mla,
  chicago,
  harvard,
  vancouver,
};

export function cite(style: Style, article: CitedArticle, journal: CitedJournal): Part[] {
  return FORMATTERS[style](article, journal);
}

// ---------------------------------------------------------------------------- reference managers

function bibEscape(text: string): string {
  return text.replace(/([\\{}%&$#_])/g, "\\$1");
}

/** A stable key such as "author2026editorial". */
export function citationKey(article: CitedArticle): string {
  const first = article.authors[0];
  const name = (first ? first.family_name || first.given_name : "anon")
    .normalize("NFKD")
    .replace(/[^A-Za-z]/g, "")
    .toLowerCase();
  const word =
    article.title
      .normalize("NFKD")
      .toLowerCase()
      .split(/[^a-z]+/)
      .find((w) => w.length > 3 && !["the", "with", "from", "into", "that", "this"].includes(w)) ?? "";
  return `${name || "anon"}${year(article)}${word}`;
}

export function bibtex(article: CitedArticle, journal: CitedJournal): string {
  const fields: [string, string | undefined][] = [
    [
      "author",
      article.authors
        .map((a) => (single(a) ? `{${bibEscape(a.given_name)}}` : bibEscape(familyFirst(a, "full"))))
        .join(" and "),
    ],
    ["title", `{${bibEscape(fullTitle(article))}}`],
    ["journal", bibEscape(journal.name)],
    ["year", year(article)],
    ["volume", article.volume != null ? String(article.volume) : undefined],
    ["number", article.issue ?? undefined],
    ["pages", article.pages ? pageRange(article.pages, "--") : undefined],
    ["doi", article.doi ?? undefined],
    ["url", link(article)],
    ["issn", journal.issn ?? undefined],
    ["publisher", journal.publisher ? bibEscape(journal.publisher) : undefined],
  ];
  const body = fields
    .filter((field): field is [string, string] => Boolean(field[1]))
    .map(([name, value]) => `  ${name} = {${value}}`)
    .join(",\n");
  return `@article{${citationKey(article)},\n${body}\n}\n`;
}

export function ris(article: CitedArticle, journal: CitedJournal): string {
  const [first, last] = (article.pages ?? "").split(/\s*[-–]\s*/);
  const date = article.published.slice(0, 10).replace(/-/g, "/");
  const lines: [string, string | undefined | null][] = [
    ["TY", "JOUR"],
    ...article.authors.map((a): [string, string] => ["AU", familyFirst(a, "full")]),
    ["TI", fullTitle(article)],
    ["T2", journal.name],
    ["JO", journal.abbreviation || undefined],
    ["PY", year(article)],
    ["DA", date],
    ["VL", article.volume != null ? String(article.volume) : undefined],
    ["IS", article.issue],
    ["SP", first || undefined],
    ["EP", last || undefined],
    ["DO", article.doi],
    ["UR", link(article)],
    ["SN", journal.issn],
    ["PB", journal.publisher || undefined],
    ["AB", article.abstract?.replace(/\s+/g, " ").trim() || undefined],
    ...(article.keywords ?? []).map((k): [string, string] => ["KW", k]),
    ["ER", ""],
  ];
  return `${lines
    .filter(([tag, value]) => tag === "ER" || Boolean(value))
    .map(([tag, value]) => `${tag}  - ${value ?? ""}`)
    .join("\r\n")}\r\n`;
}
