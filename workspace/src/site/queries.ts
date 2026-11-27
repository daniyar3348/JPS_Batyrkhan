import type { SiteSettingsOut } from "@jps/api-client";
import { useQuery } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../api";

export const sitePagesKey = ["site-pages"] as const;
export const sitePageKey = (id: number) => ["site-pages", id] as const;
export const announcementsKey = ["site-announcements"] as const;
export const siteSettingsKey = ["site-settings"] as const;

export function useSitePages() {
  return useQuery({ queryKey: sitePagesKey, queryFn: () => unwrap(api.GET("/api/v1/site/pages")) });
}

export function useSitePage(id: number, enabled = true) {
  return useQuery({
    queryKey: sitePageKey(id),
    queryFn: () => unwrap(api.GET("/api/v1/site/pages/{page_id}", { params: { path: { page_id: id } } })),
    enabled,
  });
}

export function useAnnouncements() {
  return useQuery({
    queryKey: announcementsKey,
    queryFn: () => unwrap(api.GET("/api/v1/site/announcements")),
  });
}

/** The settings, and the journal's version from the ETag header (sent back in If-Match). */
export interface SiteSettingsState {
  data: SiteSettingsOut;
  etag: string;
}

interface Result {
  data?: SiteSettingsOut;
  error?: unknown;
  response: Response;
}

export async function withEtag(request: Promise<Result>): Promise<SiteSettingsState> {
  const data = await unwrap(request);
  const result = await request;
  const etag = result.response.headers.get("etag");
  if (!etag) throw new ApiError(500, { detail: "The server did not say which version this is." });
  return { data, etag };
}

export function useSiteSettings() {
  return useQuery({
    queryKey: siteSettingsKey,
    queryFn: () => withEtag(api.GET("/api/v1/journal/site-settings")),
  });
}
