/**
 * Reading the public API. Responses are cached by Next.js and rebuilt when the platform says something
 * changed (see app/api/revalidate), or after `revalidate` seconds at the latest.
 */
import type {
  PublicAnnouncement,
  PublicArticle,
  PublicArticleSummary,
  PublicIssue,
  PublicIssueDetail,
  PublicJournalOut,
  PublicPage,
  PublicPageLink,
  PublicSection,
  SearchResults,
} from "@jps/api-client";
import { config } from "./config";

export type {
  PublicAnnouncement,
  PublicArticle,
  PublicArticleSummary,
  PublicIssue,
  PublicIssueDetail,
  PublicJournalOut,
  PublicPage,
  PublicPageLink,
  PublicSection,
  SearchResults,
};

/** Every cached response carries this tag, so the platform can ask for everything to be rebuilt. */
export const ALL = "jps";
const HOUR = 3600;

/** `next build` runs without the API (in Docker, in CI): pages are then built empty and rebuilt on first use. */
const building = process.env.NEXT_PHASE === "phase-production-build";

interface Options {
  revalidate?: number;
  /** Rendered on every request (search): no caching. */
  fresh?: boolean;
}

async function get<T>(path: string, options: Options = {}): Promise<T | null> {
  let response: Response;
  try {
    response = await fetch(`${config.apiUrl}${path}`, {
      headers: { Accept: "application/json" },
      ...(options.fresh
        ? { cache: "no-store" as const }
        : { next: { revalidate: options.revalidate ?? HOUR, tags: [ALL] } }),
    });
  } catch (error) {
    if (building) return null;
    throw error;
  }
  if (response.status === 404) return null;
  if (!response.ok) {
    if (building) return null;
    // Thrown, so Next.js keeps serving the last good version of the page.
    throw new Error(`The journal's API answered ${response.status} for ${path}`);
  }
  return (await response.json()) as T;
}

export const api = {
  journal: () => get<PublicJournalOut>("/public/v1/journal"),
  pages: () => get<PublicPageLink[]>("/public/v1/pages"),
  page: (slug: string) => get<PublicPage>(`/public/v1/pages/${encodeURIComponent(slug)}`),
  currentIssue: () => get<PublicIssueDetail>("/public/v1/issues/current"),
  issues: () => get<PublicIssue[]>("/public/v1/issues"),
  issue: (id: number) => get<PublicIssueDetail>(`/public/v1/issues/${id}`),
  article: (slug: string) => get<PublicArticle>(`/public/v1/articles/${encodeURIComponent(slug)}`),
  articles: (cursor?: string, limit = 20) =>
    get<{ items: PublicArticleSummary[]; next_cursor: string | null }>(
      `/public/v1/articles?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
  sections: () => get<PublicSection[]>("/public/v1/sections"),
  announcements: (limit = 20) => get<PublicAnnouncement[]>(`/public/v1/announcements?limit=${limit}`),
  announcement: (id: number) => get<PublicAnnouncement>(`/public/v1/announcements/${id}`),
  search: (q: string, cursor?: string) =>
    get<SearchResults>(
      `/public/v1/search?q=${encodeURIComponent(q)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      { fresh: true },
    ),
};

/** All published articles, newest first (for the sitemap and feeds). */
export async function allArticles(max = 5000): Promise<PublicArticleSummary[]> {
  const result: PublicArticleSummary[] = [];
  let cursor: string | undefined;
  do {
    const page = await api.articles(cursor, 100);
    if (!page) break;
    result.push(...page.items);
    cursor = page.next_cursor ?? undefined;
  } while (cursor && result.length < max);
  return result;
}
