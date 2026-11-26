import { ApiError, createApiClient, unwrap } from "@jps/api-client";

let csrfToken: string | null = null;

/** Remember the CSRF token of the current session; it is sent with every state-changing request. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

// The API is served from the same origin as this app (via the dev proxy or nginx), so the session cookie applies.
export const api = createApiClient({ baseUrl: window.location.origin, getCsrfToken: () => csrfToken });

export { ApiError, unwrap };

/** A message suitable for a notification, for any error thrown by a request. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
