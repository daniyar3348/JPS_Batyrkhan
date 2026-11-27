import type { PublishingSettingsOut } from "@jps/api-client";
import { useQuery } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../api";

export const issuesKey = ["issues"] as const;
export const issueKey = (id: number) => ["issues", id] as const;
export const publishingSettingsKey = ["publishing-settings"] as const;
export const doiDepositsKey = (status: string) => ["doi-deposits", status] as const;

export function useIssues(status?: "future" | "published") {
  return useQuery({
    queryKey: status ? [...issuesKey, { status }] : issuesKey,
    queryFn: () => unwrap(api.GET("/api/v1/issues", { params: { query: { status: status ?? null } } })),
  });
}

export function useIssue(id: number) {
  return useQuery({
    queryKey: issueKey(id),
    queryFn: () => unwrap(api.GET("/api/v1/issues/{issue_id}", { params: { path: { issue_id: id } } })),
  });
}

/** The settings, and the journal's version from the ETag header (sent back in If-Match). */
export interface PublishingSettingsState {
  data: PublishingSettingsOut;
  etag: string;
}

interface Result {
  data?: PublishingSettingsOut;
  error?: unknown;
  response: Response;
}

export async function withEtag(request: Promise<Result>): Promise<PublishingSettingsState> {
  const data = await unwrap(request);
  const result = await request;
  const etag = result.response.headers.get("etag");
  if (!etag) throw new ApiError(500, { detail: "The server did not say which version this is." });
  return { data, etag };
}

export function usePublishingSettings() {
  return useQuery({
    queryKey: publishingSettingsKey,
    queryFn: () => withEtag(api.GET("/api/v1/journal/publishing-settings")),
  });
}
