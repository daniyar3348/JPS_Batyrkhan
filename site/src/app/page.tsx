import Link from "next/link";
import { IssueContents } from "@/components/ArticleItem";
import { api } from "@/lib/api";
import { excerpt, formatDate } from "@/lib/format";

// A list page: it was built without the API, so it is checked again after a minute at the latest.
export const revalidate = 60;

export default async function HomePage() {
  const [journal, issue, announcements, pages] = await Promise.all([
    api.journal(),
    api.currentIssue(),
    api.announcements(3),
    api.pages(),
  ]);
  return (
    <div className="layout-2">
      <div>
        {issue ? (
          <>
            <span className="section-label">Current issue</span>
            <h1>{issue.label}</h1>
            <p className="muted">
              Published {formatDate(issue.published_at)}
              {" · "}
              <Link href={`/issues/${issue.id}`}>Issue page</Link>
            </p>
            {issue.description ? <p className="lead">{issue.description}</p> : null}
            <IssueContents sections={issue.sections} />
          </>
        ) : (
          <>
            <h1>{journal?.name ?? "Welcome"}</h1>
            <p className="lead">
              The first issue is being prepared. Articles will appear here when they are published.
            </p>
          </>
        )}
      </div>
      <aside aria-label="About the journal">
        {journal?.description ? (
          <section className="panel">
            <h2>About the journal</h2>
            <p>{excerpt(journal.description, 320)}</p>
            <p style={{ margin: 0 }}>
              <Link href="/about">More about the journal</Link>
            </p>
          </section>
        ) : null}
        <section className="panel">
          <h2>For authors</h2>
          <ul style={{ margin: "0 0 1rem", paddingLeft: "1.1rem" }}>
            {(pages ?? []).map((page) => (
              <li key={page.slug}>
                <Link href={`/${page.slug}`}>{page.title}</Link>
              </li>
            ))}
            <li>
              <Link href="/about#fees">Fees</Link>
            </li>
          </ul>
          <a className="button" href="/submit">
            Submit a manuscript
          </a>
        </section>
        {announcements?.length ? (
          <section className="panel">
            <h2>Announcements</h2>
            {announcements.map((item) => (
              <div key={item.id} style={{ marginBottom: "0.9rem" }}>
                <Link href={`/announcements/${item.id}`}>{item.title}</Link>
                <div className="muted small">{formatDate(item.published_at)}</div>
              </div>
            ))}
            <Link href="/announcements" className="small">
              All announcements
            </Link>
          </section>
        ) : null}
      </aside>
    </div>
  );
}
