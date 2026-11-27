import type { PublicArticle, PublicJournalOut } from "@jps/api-client";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CiteBox } from "@/components/CiteBox";
import { Paragraphs } from "@/components/Markdown";
import { OrcidLink } from "@/components/Orcid";
import { api } from "@/lib/api";
import type { CitedArticle, CitedJournal } from "@/lib/citation";
import { config } from "@/lib/config";
import { excerpt, formatDate, formatSize, licenceName } from "@/lib/format";
import { dublinCoreTags, highwireTags, jsonForScript, scholarlyArticleLd } from "@/lib/scholar";

export const revalidate = 3600;
export const dynamicParams = true;

/** Articles are built when first visited, then kept until the platform says they changed. */
export function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

function urls(article: PublicArticle) {
  const page = `${config.siteUrl}/articles/${article.slug}`;
  const pdf = article.galleys.find((g) => g.content_type === "application/pdf");
  return { page, pdf: pdf ? `${page}/download/${pdf.id}` : undefined };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const article = await api.article((await params).slug);
  if (!article) return {};
  const authors = article.authors.map((a) => a.name);
  return {
    title: article.title,
    description: excerpt(article.abstract || article.title, 200),
    alternates: { canonical: `/articles/${article.slug}` },
    authors: authors.map((name) => ({ name })),
    keywords: article.keywords,
    openGraph: {
      type: "article",
      title: article.title,
      description: excerpt(article.abstract, 200),
      url: `/articles/${article.slug}`,
      publishedTime: article.dates.published,
      modifiedTime: article.dates.updated ?? undefined,
      authors,
    },
  };
}

function cited(article: PublicArticle): CitedArticle {
  return {
    title: article.title,
    subtitle: article.subtitle,
    authors: article.authors,
    published: article.dates.published,
    volume: article.issue?.volume,
    issue: article.issue?.number,
    pages: article.pages,
    doi: article.doi,
    url: urls(article).page,
    abstract: article.abstract,
    keywords: article.keywords,
  };
}

function citedJournal(journal: PublicJournalOut | null): CitedJournal {
  return {
    name: journal?.name ?? "",
    abbreviation: journal?.abbreviation,
    issn: journal?.issn_online ?? journal?.issn_print,
    publisher: journal?.publisher,
  };
}

/** Numbered affiliations, each listed once, in the order the authors appear. */
function affiliations(article: PublicArticle): string[] {
  return [...new Set(article.authors.map((a) => a.affiliation).filter(Boolean))];
}

export default async function ArticlePage({ params }: Props) {
  const [article, journal] = await Promise.all([api.article((await params).slug), api.journal()]);
  if (!article) notFound();
  const places = affiliations(article);
  const links = urls(article);
  const tags = journal
    ? [...highwireTags(article, journal, links), ...dublinCoreTags(article, journal, links.page)]
    : [];
  const earlier = article.versions.filter((v) => v.version !== article.version);
  return (
    <>
      {/* React places these in the document head; Google Scholar needs them in this order. */}
      {tags.map(([name, content], index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: names repeat (one tag per author or reference).
        <meta key={index} name={name} content={content} />
      ))}
      {journal ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: JSON-LD, with "<" escaped by jsonForScript.
          dangerouslySetInnerHTML={{
            __html: jsonForScript(scholarlyArticleLd(article, journal, links.page)),
          }}
        />
      ) : null}
      <nav className="breadcrumbs" aria-label="Breadcrumbs">
        <Link href="/">Home</Link> / <Link href="/issues">Archive</Link>
        {article.issue ? (
          <>
            {" / "}
            <Link href={`/issues/${article.issue.id}`}>{article.issue.label}</Link>
          </>
        ) : null}
      </nav>
      <div className="layout-2">
        <article className="reading">
          <span className="section-label">{article.section.title}</span>
          <h1 className="article-title">{article.title}</h1>
          {article.subtitle ? <p className="article-subtitle">{article.subtitle}</p> : null}
          <ul className="authors" aria-label="Authors">
            {article.authors.map((author) => (
              <li key={author.name}>
                {author.name}
                {author.affiliation ? <sup>{places.indexOf(author.affiliation) + 1}</sup> : null}
                {author.is_corresponding ? <span title="Corresponding author">*</span> : null}
                {author.orcid ? <OrcidLink orcid={author.orcid} name={author.name} /> : null}
              </li>
            ))}
          </ul>
          {places.length ? (
            <ol className="affiliations" aria-label="Affiliations">
              {places.map((place, index) => (
                <li key={place}>
                  <sup>{index + 1}</sup> {place}
                </li>
              ))}
            </ol>
          ) : null}
          <div className="downloads">
            {article.galleys.map((galley) => (
              <a
                key={galley.id}
                className="button"
                href={`/articles/${article.slug}/download/${galley.id}`}
                aria-label={`Download ${galley.label} (${formatSize(galley.size_bytes)})`}
              >
                {galley.label}
                <span style={{ fontWeight: 400, opacity: 0.85 }}>{formatSize(galley.size_bytes)}</span>
              </a>
            ))}
            {article.doi_url ? (
              <a className="button button-quiet" href={article.doi_url} rel="noopener noreferrer">
                DOI: {article.doi}
              </a>
            ) : null}
          </div>

          <h2>Abstract</h2>
          <Paragraphs text={article.abstract} className="prose" />
          {article.keywords.length ? (
            <>
              <h2 className="small" style={{ fontSize: "1rem" }}>
                Keywords
              </h2>
              <ul className="keywords">
                {article.keywords.map((keyword) => (
                  <li key={keyword}>
                    <Link className="chip chip-plain" href={`/search?q=${encodeURIComponent(keyword)}`}>
                      {keyword}
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {article.references.length ? (
            <section aria-labelledby="references">
              <h2 id="references">References</h2>
              <ol className="references">
                {article.references.map((reference) => (
                  <li key={reference}>{reference}</li>
                ))}
              </ol>
            </section>
          ) : null}
          {article.funding_statement ? (
            <section>
              <h2>Funding</h2>
              <p>{article.funding_statement}</p>
            </section>
          ) : null}
          {article.competing_interests ? (
            <section>
              <h2>Competing interests</h2>
              <p>{article.competing_interests}</p>
            </section>
          ) : null}
        </article>

        <aside aria-label="About this article">
          <section className="panel">
            <h2>Article information</h2>
            <dl className="facts">
              {article.issue ? (
                <>
                  <dt>Issue</dt>
                  <dd>
                    <Link href={`/issues/${article.issue.id}`}>{article.issue.label}</Link>
                  </dd>
                </>
              ) : null}
              {article.pages ? (
                <>
                  <dt>Pages</dt>
                  <dd>{article.pages}</dd>
                </>
              ) : null}
              {article.dates.submitted ? (
                <>
                  <dt>Submitted</dt>
                  <dd>{formatDate(article.dates.submitted)}</dd>
                </>
              ) : null}
              {article.dates.accepted ? (
                <>
                  <dt>Accepted</dt>
                  <dd>{formatDate(article.dates.accepted)}</dd>
                </>
              ) : null}
              <dt>Published</dt>
              <dd>{formatDate(article.dates.published)}</dd>
              {article.dates.updated ? (
                <>
                  <dt>Updated</dt>
                  <dd>
                    {formatDate(article.dates.updated)} (version {article.version})
                  </dd>
                </>
              ) : null}
              {article.doi ? (
                <>
                  <dt>DOI</dt>
                  <dd>
                    <a href={article.doi_url ?? undefined} rel="noopener noreferrer">
                      {article.doi}
                    </a>
                  </dd>
                </>
              ) : null}
            </dl>
          </section>
          {article.license_url ? (
            <section className="panel">
              <h2>Licence</h2>
              <p style={{ margin: 0 }}>
                {article.copyright_holder ? (
                  <>
                    Copyright {"©"} {article.copyright_year} {article.copyright_holder}.{" "}
                  </>
                ) : null}
                This article is published under the{" "}
                <a href={article.license_url} rel="license noopener noreferrer">
                  {licenceName(article.license_url)}
                </a>{" "}
                licence.
              </p>
            </section>
          ) : null}
          <CiteBox article={cited(article)} journal={citedJournal(journal)} />
          {earlier.length ? (
            <section className="panel">
              <h2>Versions</h2>
              <p className="small muted">
                You are reading version {article.version}. Earlier versions stay available.
              </p>
              <ul style={{ paddingLeft: "1.1rem", margin: 0 }}>
                {article.versions
                  .slice()
                  .reverse()
                  .map((version) => (
                    <li key={version.version} className="small" style={{ marginBottom: "0.6rem" }}>
                      <strong>Version {version.version}</strong>, {formatDate(version.published_at)}
                      {version.note ? <div className="muted">{version.note}</div> : null}
                      {version.version !== article.version
                        ? version.galleys.map((galley) => (
                            <div key={galley.id}>
                              <a href={`/articles/${article.slug}/download/${galley.id}`}>{galley.label}</a>
                            </div>
                          ))
                        : null}
                    </li>
                  ))}
              </ul>
            </section>
          ) : null}
        </aside>
      </div>
    </>
  );
}
