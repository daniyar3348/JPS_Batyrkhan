import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./styles.css";

import { MantineProvider } from "@mantine/core";
import { ModalsProvider } from "@mantine/modals";
import { Notifications } from "@mantine/notifications";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { ApiError } from "./api";
import { applySession } from "./auth";
import { router } from "./router";
import { theme } from "./theme";

const queryClient: QueryClient = new QueryClient({
  // A 401 anywhere means the session ended: forget it, and the router sends the user to the sign-in page.
  queryCache: new QueryCache({ onError: forgetExpiredSession }),
  mutationCache: new MutationCache({ onError: forgetExpiredSession }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
    },
  },
});

function forgetExpiredSession(error: unknown): void {
  if (error instanceof ApiError && error.status === 401) {
    applySession(queryClient, null);
  }
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <ModalsProvider>
          <RouterProvider router={router} />
        </ModalsProvider>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
