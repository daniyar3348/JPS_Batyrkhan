import type { MetadataRoute } from "next";
import { allArticles, api } from "@/lib/api";
import { config } from "@/lib/config";

export const revalidate = 3600;

/** Every public page, for search engines. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const site = config.siteUrl;
  const [issues, pages, announcements, articles] = await Promise.all([
    api.issues(),
    api.pages(),
    api.announcements(100),
    allArticles(),
  ]);
  return [
    { url: `${site}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${site}/issues`, changeFrequency: "weekly" },
    { url: `${site}/about`, changeFrequency: "monthly" },
    { url: `${site}/editorial-board`, changeFrequency: "monthly" },
    { url: `${site}/announcements`, changeFrequency: "weekly" },
    ...(pages ?? []).map((page) => ({ url: `${site}/${page.slug}`, changeFrequency: "monthly" as const })),
    ...(issues ?? []).map((issue) => ({
      url: `${site}/issues/${issue.id}`,
      lastModified: issue.published_at ?? undefined,
    })),
    ...articles.map((article) => ({
      url: `${site}/articles/${article.slug}`,
      lastModified: article.published_at,
      priority: 0.8,
    })),
    ...(announcements ?? []).map((item) => ({
      url: `${site}/announcements/${item.id}`,
      lastModified: item.published_at,
    })),
  ];
}
