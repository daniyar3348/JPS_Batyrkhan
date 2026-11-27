/**
 * What indexers read from an article page: Highwire Press `citation_*` tags (Google Scholar),
 * Dublin Core, and schema.org JSON-LD.
 */
import type { PublicArticle, PublicJournalOut } from "@jps/api-client";

export type MetaTag = [name: string, content: string];

function issns(journal: PublicJournalOut): string[] {
  return [journal.issn_online, journal.issn_print].filter((issn): issn is string => Boolean(issn));
}

function slashDate(iso: string): string {
  return iso.slice(0, 10).replace(/-/g, "/");
}

function pageBounds(pages: string): [string, string] {
  const [first = "", last = ""] = pages.split(/\s*[-–]\s*/);
  return [first.trim(), last.trim()];
}

function authorName(author: { given_name: string; family_name: string }): string {
  return author.family_name ? `${author.family_name}, ${author.given_name}` : author.given_name;
}

/** Google Scholar wants each author followed by their institution, so the order of the tags matters. */
export function highwireTags(
  article: PublicArticle,
  journal: PublicJournalOut,
  urls: { page: string; pdf?: string },
): MetaTag[] {
  const tags: MetaTag[] = [["citation_title", article.title]];
  for (const author of article.authors) {
    tags.push(["citation_author", authorName(author)]);
    if (author.affiliation) tags.push(["citation_author_institution", author.affiliation]);
    if (author.orcid) tags.push(["citation_author_orcid", `https://orcid.org/${author.orcid}`]);
  }
  tags.push(["citation_publication_date", slashDate(article.dates.published)]);
  tags.push(["citation_online_date", slashDate(article.dates.published)]);
  tags.push(["citation_journal_title", journal.name]);
  if (journal.abbreviation) tags.push(["citation_journal_abbrev", journal.abbreviation]);
  for (const issn of issns(journal)) tags.push(["citation_issn", issn]);
  if (journal.publisher) tags.push(["citation_publisher", journal.publisher]);
  if (article.issue?.volume != null) tags.push(["citation_volume", String(article.issue.volume)]);
  if (article.issue?.number) tags.push(["citation_issue", article.issue.number]);
  if (article.pages) {
    const [first, last] = pageBounds(article.pages);
    if (first) tags.push(["citation_firstpage", first]);
    if (last) tags.push(["citation_lastpage", last]);
  }
  if (article.doi) tags.push(["citation_doi", article.doi]);
  tags.push(["citation_abstract_html_url", urls.page]);
  if (urls.pdf) tags.push(["citation_pdf_url", urls.pdf]);
  tags.push(["citation_language", "en"]);
  for (const keyword of article.keywords) tags.push(["citation_keywords", keyword]);
  for (const reference of article.references) tags.push(["citation_reference", reference]);
  return tags;
}

export function dublinCoreTags(
  article: PublicArticle,
  journal: PublicJournalOut,
  pageUrl: string,
): MetaTag[] {
  const tags: MetaTag[] = [["DC.title", article.title]];
  for (const author of article.authors) tags.push(["DC.creator", authorName(author)]);
  for (const keyword of article.keywords) tags.push(["DC.subject", keyword]);
  if (article.abstract) tags.push(["DC.description", article.abstract]);
  if (journal.publisher) tags.push(["DC.publisher", journal.publisher]);
  tags.push(["DC.date", article.dates.published.slice(0, 10)]);
  tags.push(["DC.type", "Text"]);
  tags.push(["DC.type", "Article"]);
  if (article.doi_url) tags.push(["DC.identifier", article.doi_url]);
  tags.push(["DC.identifier", pageUrl]);
  const source = [journal.name, article.issue?.label, article.pages].filter(Boolean).join("; ");
  tags.push(["DC.source", source]);
  for (const issn of issns(journal)) tags.push(["DC.source.issn", issn]);
  tags.push(["DC.language", "en"]);
  if (article.license_url) tags.push(["DC.rights", article.license_url]);
  return tags;
}

export function scholarlyArticleLd(
  article: PublicArticle,
  journal: PublicJournalOut,
  pageUrl: string,
): Record<string, unknown> {
  const periodical: Record<string, unknown> = {
    "@type": "Periodical",
    name: journal.name,
    ...(issns(journal).length ? { issn: issns(journal) } : {}),
    ...(journal.publisher ? { publisher: { "@type": "Organization", name: journal.publisher } } : {}),
  };
  let isPartOf: Record<string, unknown> = periodical;
  if (article.issue) {
    const volume =
      article.issue.volume != null
        ? { "@type": "PublicationVolume", volumeNumber: String(article.issue.volume), isPartOf: periodical }
        : periodical;
    isPartOf = {
      "@type": "PublicationIssue",
      ...(article.issue.number ? { issueNumber: article.issue.number } : {}),
      ...(article.issue.published_at ? { datePublished: article.issue.published_at.slice(0, 10) } : {}),
      isPartOf: volume,
    };
  }
  const [pageStart, pageEnd] = article.pages ? pageBounds(article.pages) : ["", ""];
  return {
    "@context": "https://schema.org",
    "@type": "ScholarlyArticle",
    headline: article.title.slice(0, 110),
    name: article.title,
    ...(article.subtitle ? { alternativeHeadline: article.subtitle } : {}),
    author: article.authors.map((author) => ({
      "@type": "Person",
      name: author.name,
      givenName: author.given_name,
      ...(author.family_name ? { familyName: author.family_name } : {}),
      ...(author.affiliation ? { affiliation: { "@type": "Organization", name: author.affiliation } } : {}),
      ...(author.orcid ? { sameAs: `https://orcid.org/${author.orcid}` } : {}),
    })),
    datePublished: article.dates.published.slice(0, 10),
    ...(article.dates.updated ? { dateModified: article.dates.updated.slice(0, 10) } : {}),
    ...(article.abstract ? { abstract: article.abstract, description: article.abstract.slice(0, 300) } : {}),
    ...(article.keywords.length ? { keywords: article.keywords.join(", ") } : {}),
    ...(article.doi
      ? {
          identifier: { "@type": "PropertyValue", propertyID: "DOI", value: article.doi },
          sameAs: article.doi_url,
        }
      : {}),
    url: pageUrl,
    mainEntityOfPage: pageUrl,
    inLanguage: "en",
    isAccessibleForFree: true,
    ...(article.license_url ? { license: article.license_url } : {}),
    ...(pageStart ? { pageStart } : {}),
    ...(pageEnd ? { pageEnd } : {}),
    ...(article.section ? { articleSection: article.section.title } : {}),
    isPartOf,
  };
}

/** JSON for a <script> element: "<" is escaped so the text cannot close the element. */
export function jsonForScript(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}
