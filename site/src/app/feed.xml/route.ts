import { api } from "@/lib/api";
import { config } from "@/lib/config";

export const revalidate = 3600;

function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** An Atom feed of the latest articles. */
export async function GET() {
  const [journal, page] = await Promise.all([api.journal(), api.articles(undefined, 30)]);
  const site = config.siteUrl;
  const articles = page?.items ?? [];
  const updated = articles[0]?.published_at ?? new Date().toISOString();
  const entries = articles
    .map((article) => {
      const url = `${site}/articles/${article.slug}`;
      return `  <entry>
    <id>${esc(article.doi_url ?? url)}</id>
    <title>${esc(article.title)}</title>
    <link rel="alternate" href="${esc(url)}"/>
    <published>${article.published_at}</published>
    <updated>${article.published_at}</updated>
${article.authors.map((name) => `    <author><name>${esc(name)}</name></author>`).join("\n")}
    <summary>${esc(article.abstract.slice(0, 1000))}</summary>
  </entry>`;
    })
    .join("\n");
  const xml = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>${esc(site)}/</id>
  <title>${esc(journal?.name ?? "Journal")}</title>
  <subtitle>${esc(journal?.tagline ?? "")}</subtitle>
  <link rel="self" href="${esc(site)}/feed.xml"/>
  <link rel="alternate" href="${esc(site)}/"/>
  <updated>${updated}</updated>
${entries}
</feed>
`;
  return new Response(xml, { headers: { "Content-Type": "application/atom+xml; charset=utf-8" } });
}
