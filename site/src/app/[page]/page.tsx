import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Markdown } from "@/components/Markdown";
import { api } from "@/lib/api";
import { excerpt, formatDate } from "@/lib/format";

export const revalidate = 3600;
export const dynamicParams = true;

/** Pages written in the workspace (aims and scope, policies, guidelines), at /{slug}. */
export function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ page: string }> };

async function load(slug: string) {
  return /^[a-z0-9][a-z0-9-]{0,79}$/.test(slug) ? api.page(slug) : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const page = await load((await params).page);
  return page
    ? {
        title: page.title,
        description: excerpt(page.body.replace(/[#*_>`[\]]/g, ""), 200),
        alternates: { canonical: `/${page.slug}` },
      }
    : {};
}

export default async function ContentPage({ params }: Props) {
  const page = await load((await params).page);
  if (!page) notFound();
  return (
    <article className="reading">
      <h1>{page.title}</h1>
      <Markdown>{page.body}</Markdown>
      <p className="muted small">Last updated {formatDate(page.updated_at)}</p>
    </article>
  );
}
