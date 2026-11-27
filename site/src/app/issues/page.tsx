import type { Metadata } from "next";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";

export const revalidate = 60;
export const metadata: Metadata = { title: "Archive", alternates: { canonical: "/issues" } };

export default async function ArchivePage() {
  const issues = (await api.issues()) ?? [];
  return (
    <>
      <h1>Archive</h1>
      {issues.length === 0 ? <p className="muted">No issues have been published yet.</p> : null}
      <ul className="issue-grid">
        {issues.map((issue) => (
          <li key={issue.id}>
            <Link className="issue-card" href={`/issues/${issue.id}`}>
              <strong>{issue.label}</strong>
              <span className="muted small">
                {formatDate(issue.published_at)} {"·"} {issue.article_count}{" "}
                {issue.article_count === 1 ? "article" : "articles"}
                {issue.is_current ? " · current" : ""}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
