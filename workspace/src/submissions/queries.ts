import type { SubmissionOut } from "@jps/api-client";
import { type QueryClient, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "../api";

export const submissionKey = (id: number) => ["submission", id] as const;
export const submissionSettingsKey = ["submission-settings"] as const;

const BUSY = new Set(["pending_upload", "processing"]);

export function useSubmission(id: number) {
  return useQuery({
    queryKey: submissionKey(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/submissions/{submission_id}", { params: { path: { submission_id: id } } })),
    // While files are being checked, look again shortly.
    refetchInterval: (query) =>
      query.state.data?.files.some((file) => BUSY.has(file.status)) ? 1500 : false,
  });
}

export function useSubmissionSettings() {
  return useQuery({
    queryKey: submissionSettingsKey,
    queryFn: () => unwrap(api.GET("/api/v1/journal/submission-settings")),
    staleTime: 5 * 60_000,
  });
}

export function useActiveSections() {
  return useQuery({
    queryKey: ["sections"],
    queryFn: () => unwrap(api.GET("/api/v1/sections")),
    select: (sections) => sections.filter((section) => section.is_active),
  });
}

/** Store a fresh copy returned by the API, so the next save sends the right version. */
export function storeSubmission(queryClient: QueryClient, submission: SubmissionOut): void {
  queryClient.setQueryData(submissionKey(submission.id), submission);
  queryClient.invalidateQueries({ queryKey: ["submissions"] });
}
