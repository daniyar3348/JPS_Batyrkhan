import type { PublicArticleSummary, PublicIssueSection } from "@jps/api-client";
import Link from "next/link";
import { formatDate } from "@/lib/format";

/** One article in a table of contents or a list of results. */
export function ArticleItem({
  article,
  showIssue = false,
  showAbstract = false,
}: {
  article: PublicArticleSummary;
  showIssue?: boolean;
  showAbstract?: boolean;
}) {
  const pdf = article.galleys.find((g) => g.content_type === "application/pdf") ?? article.galleys[0];
  return (
    <article className="article-item">
      <h3>
        <Link href={`/articles/${article.slug}`}>
          {article.title}
          {article.subtitle ? `: ${article.subtitle}` : ""}
        </Link>
      </h3>
      {article.authors.length ? <p style={{ margin: "0 0 0.35rem" }}>{article.authors.join(", ")}</p> : null}
      {showAbstract && article.abstract ? (
        <p className="muted small" style={{ margin: "0 0 0.5rem" }}>
          {article.abstract.length > 280 ? `${article.abstract.slice(0, 280).trimEnd()}…` : article.abstract}
        </p>
      ) : null}
      <div className="article-meta">
        {showIssue && article.issue ? (
          <Link href={`/issues/${article.issue.id}`}>{article.issue.label}</Link>
        ) : null}
        {article.pages ? <span>pp. {article.pages}</span> : null}
        <span>{formatDate(article.published_at)}</span>
        {article.doi_url ? (
          <a href={article.doi_url} rel="noopener noreferrer">
            {article.doi_url}
          </a>
        ) : null}
        {pdf ? (
          <a className="chip" href={`/articles/${article.slug}/download/${pdf.id}`}>
            {pdf.label}
          </a>
        ) : null}
      </div>
    </article>
  );
}

/** An issue's articles under their sections. */
export function IssueContents({ sections }: { sections: PublicIssueSection[] }) {
  if (!sections.length) return <p className="muted">No articles yet.</p>;
  return (
    <>
      {sections.map((group) => (
        <section
          className="toc-section"
          key={group.section.id}
          aria-labelledby={`section-${group.section.id}`}
        >
          <h2 id={`section-${group.section.id}`}>{group.section.title}</h2>
          {group.articles.map((article) => (
            <ArticleItem key={article.slug} article={article} />
          ))}
        </section>
      ))}
    </>
  );
}
