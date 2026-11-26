/**
 * Typed client for the journal platform API.
 *
 * `schema.ts` is generated from the backend's OpenAPI schema with `npm run generate:api`;
 * never edit it by hand. Request and response types therefore always match the server.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, Problem, paths } from "./schema";

export * from "./schema";
export type Schemas = components["schemas"];

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** An error response from the API (RFC 9457 problem details). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  /** Messages for individual fields, keyed by field name (e.g. "email" or "interests.0"). */
  readonly fieldErrors: Record<string, string>;

  constructor(status: number, problem?: Partial<Problem> | null) {
    const detail = problem?.detail ?? "Something went wrong. Please try again.";
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = problem?.code ?? (status === 0 ? "network_error" : "http_error");
    this.detail = detail;
    this.fieldErrors = Object.fromEntries((problem?.errors ?? []).map((e) => [e.field, e.message]));
  }
}

export type ApiClient = ReturnType<typeof createApiClient>;

export interface ApiClientOptions {
  baseUrl?: string;
  /** Returns the CSRF token of the current session; sent with every state-changing request. */
  getCsrfToken?: () => string | null;
  fetch?: typeof fetch;
}

export function createApiClient(options: ApiClientOptions = {}) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? "",
    credentials: "same-origin",
    // Look up fetch on every call, so tests and polyfills can replace it after the client is created.
    fetch: options.fetch ?? ((...args: Parameters<typeof fetch>) => globalThis.fetch(...args)),
  });
  const csrf: Middleware = {
    onRequest({ request }) {
      const token = options.getCsrfToken?.();
      if (token && !SAFE_METHODS.has(request.method)) {
        request.headers.set("X-CSRF-Token", token);
      }
      return request;
    },
  };
  client.use(csrf);
  return client;
}

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Return the response body, or throw an ApiError for any non-2xx response. */
export async function unwrap<T>(request: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await request;
  } catch {
    throw new ApiError(0, { detail: "Cannot reach the server. Check your connection and try again." });
  }
  if (!result.response.ok) {
    throw new ApiError(result.response.status, result.error as Partial<Problem> | undefined);
  }
  return result.data as T;
}
