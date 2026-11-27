import type { Metadata } from "next";
import Link from "next/link";
import { ArticleItem } from "@/components/ArticleItem";
import { api } from "@/lib/api";

export const metadata: Metadata = { title: "Search", robots: { index: false, follow: true } };

type Props = { searchParams: Promise<{ q?: string; cursor?: string }> };

export default async function SearchPage({ searchParams }: Props) {
  const { q = "", cursor } = await searchParams;
  const query = q.trim().slice(0, 200);
  const results = query ? await api.search(query, cursor) : null;
  return (
    <div className="reading" style={{ maxWidth: "52rem" }}>
      <h1>Search</h1>
      <search>
        <form className="search-form" action="/search">
          <label htmlFor="q" className="skip-link">
            Search articles
          </label>
          <input id="q" name="q" type="search" defaultValue={query} placeholder="Title, author, keyword…" />
          <button className="button" type="submit">
            Search
          </button>
        </form>
      </search>
      {results ? (
        <>
          <p className="muted" aria-live="polite">
            {results.total === 0
              ? `Nothing found for “${query}”.`
              : `${results.total} ${results.total === 1 ? "article" : "articles"} found for “${query}”.`}
          </p>
          {results.items.map((article) => (
            <ArticleItem key={article.slug} article={article} showIssue showAbstract />
          ))}
          {results.next_cursor ? (
            <div className="pagination">
              <Link
                className="button button-quiet"
                href={`/search?q=${encodeURIComponent(query)}&cursor=${encodeURIComponent(results.next_cursor)}`}
              >
                More results
              </Link>
            </div>
          ) : null}
        </>
      ) : (
        <p className="muted">Search the titles, authors, keywords and abstracts of all published articles.</p>
      )}
    </div>
  );
}
