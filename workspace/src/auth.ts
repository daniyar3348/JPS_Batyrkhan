import type { Capability, MeOut, Role } from "@jps/api-client";
import { type QueryClient, useQuery } from "@tanstack/react-query";
import { ApiError, api, setCsrfToken, unwrap } from "./api";

export const meQueryKey = ["me"] as const;

async function fetchMe(): Promise<MeOut | null> {
  try {
    const me = await unwrap(api.GET("/api/v1/me"));
    setCsrfToken(me.csrf_token);
    return me;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

/** The signed-in user, or null when signed out. */
export function useMe() {
  return useQuery({ queryKey: meQueryKey, queryFn: fetchMe, staleTime: 60_000, retry: false });
}

/** For pages behind RequireAuth, where a session is guaranteed. */
export function useSignedInUser(): MeOut {
  const { data } = useMe();
  if (!data) throw new Error("useSignedInUser must be used inside RequireAuth");
  return data;
}

/** Store a new session (after sign-in) or forget it (after sign-out or expiry). */
export function applySession(queryClient: QueryClient, me: MeOut | null): void {
  setCsrfToken(me?.csrf_token ?? null);
  if (me === null) {
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== meQueryKey[0] });
  }
  queryClient.setQueryData(meQueryKey, me);
}

export function can(me: MeOut | null | undefined, capability: Capability): boolean {
  return !!me?.capabilities.includes(capability);
}

export function hasRole(me: MeOut | null | undefined, ...roles: Role[]): boolean {
  return !!me?.roles.some((role) => roles.includes(role));
}
