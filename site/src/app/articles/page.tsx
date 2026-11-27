import type { Metadata } from "next";
import Link from "next/link";
import { ArticleItem } from "@/components/ArticleItem";
import { api } from "@/lib/api";

export const revalidate = 60;
export const metadata: Metadata = { title: "Latest articles", alternates: { canonical: "/articles" } };

export default async function ArticlesPage() {
  const page = await api.articles(undefined, 30);
  const articles = page?.items ?? [];
  return (
    <div className="reading" style={{ maxWidth: "52rem" }}>
      <h1>Latest articles</h1>
      <p className="muted">
        The most recently published articles. Older ones are in the <Link href="/issues">archive</Link>.
      </p>
      {articles.length === 0 ? <p className="muted">No articles have been published yet.</p> : null}
      {articles.map((article) => (
        <ArticleItem key={article.slug} article={article} showIssue />
      ))}
    </div>
  );
}
