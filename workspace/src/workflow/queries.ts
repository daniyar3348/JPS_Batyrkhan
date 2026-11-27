import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "../api";

export const workflowKey = (id: number) => ["workflow", id] as const;
export const reviewSettingsKey = ["review-settings"] as const;
export const reviewFormsKey = ["review-forms"] as const;

const BUSY = new Set(["pending_upload", "processing"]);

export function useWorkflow(id: number, enabled = true) {
  return useQuery({
    queryKey: workflowKey(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/submissions/{submission_id}/workflow", { params: { path: { submission_id: id } } }),
      ),
    enabled,
    // Reviewers' copies and uploads are checked by the worker: look again until they are ready.
    refetchInterval: (query) =>
      query.state.data?.rounds.some((round) =>
        [...round.review_files, ...round.revision_files].some((file) => BUSY.has(file.status)),
      )
        ? 1500
        : false,
  });
}

export function useReviewSettings() {
  return useQuery({
    queryKey: reviewSettingsKey,
    queryFn: () => unwrap(api.GET("/api/v1/journal/review-settings")),
    staleTime: 5 * 60_000,
  });
}

export function useReviewForms(enabled = true) {
  return useQuery({
    queryKey: reviewFormsKey,
    queryFn: () => unwrap(api.GET("/api/v1/journal/review-forms")),
    enabled,
  });
}
