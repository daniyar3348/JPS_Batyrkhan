import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { IssueContents } from "@/components/ArticleItem";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";

export const revalidate = 3600;
export const dynamicParams = true;

/** Issues are built when first visited, then kept until the platform says they changed. */
export function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ id: string }> };

async function load(id: string) {
  return /^\d+$/.test(id) ? api.issue(Number(id)) : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const issue = await load((await params).id);
  if (!issue) return {};
  return {
    title: issue.label,
    description: issue.description || undefined,
    alternates: { canonical: `/issues/${issue.id}` },
  };
}

export default async function IssuePage({ params }: Props) {
  const issue = await load((await params).id);
  if (!issue) notFound();
  return (
    <>
      <nav className="breadcrumbs" aria-label="Breadcrumbs">
        <Link href="/">Home</Link> / <Link href="/issues">Archive</Link> / {issue.label}
      </nav>
      <h1>{issue.label}</h1>
      <p className="muted">
        Published {formatDate(issue.published_at)} {"·"} {issue.article_count}{" "}
        {issue.article_count === 1 ? "article" : "articles"}
      </p>
      {issue.description ? <p className="lead reading">{issue.description}</p> : null}
      <div className="reading" style={{ maxWidth: "52rem" }}>
        <IssueContents sections={issue.sections} />
      </div>
    </>
  );
}
