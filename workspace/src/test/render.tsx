import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { theme } from "../theme";

/** Render a page at a URL, with the app's providers and a fresh query cache. */
export function renderPage(element: ReactElement, options: { path?: string; url?: string } = {}) {
  const path = options.path ?? "/";
  const url = options.url ?? path;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path, element },
      { path: "*", element: <div>Navigated away</div> },
    ],
    { initialEntries: [url] },
  );
  return {
    router,
    queryClient,
    ...render(
      <MantineProvider theme={theme}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </MantineProvider>,
    ),
  };
}

type Route = Record<string, (request: Request) => Response | Promise<Response>>;

/** Replace fetch with handlers keyed by "METHOD /path". Unknown requests fail the test. */
export function mockApi(routes: Route) {
  const calls: { method: string; path: string; body: unknown; headers: Headers }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(input);
    const path = new URL(request.url).pathname;
    const key = `${request.method} ${path}`;
    const text = await request.clone().text();
    calls.push({
      method: request.method,
      path,
      body: text ? JSON.parse(text) : undefined,
      headers: request.headers,
    });
    const handler = routes[key];
    if (!handler) throw new Error(`Unexpected request: ${key}`);
    return handler(request);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export function json(status: number, body: unknown): Response {
  const type = status >= 400 ? "application/problem+json" : "application/json";
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": type } });
}
