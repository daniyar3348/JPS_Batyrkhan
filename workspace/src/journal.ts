import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./api";

/** The journal's public profile (name, sections). Shown on sign-in pages and in the header. */
export function usePublicJournal() {
  return useQuery({
    queryKey: ["public-journal"],
    queryFn: () => unwrap(api.GET("/public/v1/journal")),
    staleTime: 5 * 60_000,
  });
}
