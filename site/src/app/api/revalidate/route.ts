import { revalidatePath, revalidateTag } from "next/cache";
import { NextResponse } from "next/server";
import { ALL } from "@/lib/api";
import { config } from "@/lib/config";
import { parseRequest, validSignature } from "@/lib/signature";

/**
 * The platform asks for pages to be rebuilt after something is published or changed.
 * Body: {"paths": ["/", "/articles/x"], "sent_at": "..."}; "*" means every page.
 * Header: X-JPS-Signature: sha256=<HMAC of the body with the shared secret>.
 */
export async function POST(request: Request) {
  const secret = config.revalidateSecret;
  if (!secret) {
    return NextResponse.json({ error: "Revalidation is not configured" }, { status: 503 });
  }
  const body = await request.text();
  if (!validSignature(secret, body, request.headers.get("x-jps-signature"))) {
    return NextResponse.json({ error: "Invalid signature" }, { status: 401 });
  }
  const data = parseRequest(body);
  if (!data) {
    return NextResponse.json({ error: "Malformed or expired request" }, { status: 400 });
  }
  const paths = new Set(data.paths);
  if (paths.has("*")) {
    revalidateTag(ALL);
    revalidatePath("/", "layout");
    return NextResponse.json({ revalidated: ["*"] });
  }
  // Lists of articles are also in the feed and the sitemap.
  if ([...paths].some((path) => path.startsWith("/articles") || path.startsWith("/issues"))) {
    paths.add("/feed.xml");
    paths.add("/sitemap.xml");
  }
  for (const path of paths) {
    revalidatePath(path);
  }
  return NextResponse.json({ revalidated: [...paths].sort() });
}
