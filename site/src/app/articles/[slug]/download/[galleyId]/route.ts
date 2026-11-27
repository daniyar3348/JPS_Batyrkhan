import { notFound } from "next/navigation";
import { NextResponse } from "next/server";
import { api } from "@/lib/api";
import { config } from "@/lib/config";

/**
 * A file of a published article. The platform answers with a short-lived link to the file, so the link
 * is never cached; this address stays the same and is what Crossref and indexers keep.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string; galleyId: string }> },
) {
  const { slug, galleyId } = await params;
  const article = /^\d+$/.test(galleyId) ? await api.article(slug) : null;
  const id = Number(galleyId);
  const belongs = article?.versions.some((version) => version.galleys.some((galley) => galley.id === id));
  if (!article || !belongs) notFound();
  const response = await fetch(`${config.apiUrl}/public/v1/galleys/${id}/download`, {
    redirect: "manual",
    cache: "no-store",
  });
  const location = response.headers.get("location");
  if (response.status !== 302 || !location) notFound();
  // Local storage gives a path on the API's host; S3 gives a full address.
  const target = new URL(location, `${config.publicApiUrl}/`);
  return NextResponse.redirect(target, { status: 302, headers: { "Cache-Control": "no-store" } });
}
