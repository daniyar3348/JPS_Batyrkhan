import type { Metadata } from "next";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";

export const revalidate = 60;
export const metadata: Metadata = { title: "Announcements", alternates: { canonical: "/announcements" } };

export default async function AnnouncementsPage() {
  const items = (await api.announcements(100)) ?? [];
  return (
    <div className="reading">
      <h1>Announcements</h1>
      {items.length === 0 ? <p className="muted">No announcements yet.</p> : null}
      {items.map((item) => (
        <article key={item.id} className="article-item">
          <h3>
            <Link href={`/announcements/${item.id}`}>{item.title}</Link>
          </h3>
          <p className="muted small" style={{ margin: "0 0 0.35rem" }}>
            {formatDate(item.published_at)}
          </p>
          {item.summary ? <p style={{ margin: 0 }}>{item.summary}</p> : null}
        </article>
      ))}
    </div>
  );
}
