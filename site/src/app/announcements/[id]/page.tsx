import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Markdown } from "@/components/Markdown";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";

export const revalidate = 3600;
export const dynamicParams = true;

export function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ id: string }> };

async function load(id: string) {
  return /^\d+$/.test(id) ? api.announcement(Number(id)) : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const item = await load((await params).id);
  return item
    ? {
        title: item.title,
        description: item.summary || undefined,
        alternates: { canonical: `/announcements/${item.id}` },
      }
    : {};
}

export default async function AnnouncementPage({ params }: Props) {
  const item = await load((await params).id);
  if (!item) notFound();
  return (
    <article className="reading">
      <nav className="breadcrumbs" aria-label="Breadcrumbs">
        <Link href="/">Home</Link> / <Link href="/announcements">Announcements</Link>
      </nav>
      <h1>{item.title}</h1>
      <p className="muted">{formatDate(item.published_at)}</p>
      {item.summary ? <p className="lead">{item.summary}</p> : null}
      <Markdown>{item.body}</Markdown>
    </article>
  );
}
