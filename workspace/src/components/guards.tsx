import type { Capability } from "@jps/api-client";
import { Alert, Button, Center, Loader, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation, useMatches } from "react-router";
import { errorMessage } from "../api";
import { can, useMe } from "../auth";

export function FullPageLoader() {
  return (
    <Center h="100vh">
      <Loader />
    </Center>
  );
}

/** Render children only for a signed-in user; otherwise go to the sign-in page and come back afterwards. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: me, isPending, isError, error, refetch } = useMe();
  const location = useLocation();

  if (isPending) return <FullPageLoader />;
  if (isError) {
    return (
      <Center h="100vh" p="md">
        <Stack align="center" maw={420}>
          <Text fw={600}>The editorial system is not reachable</Text>
          <Text c="dimmed" ta="center">
            {errorMessage(error)}
          </Text>
          <Button onClick={() => refetch()}>Try again</Button>
        </Stack>
      </Center>
    );
  }
  if (!me) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return children;
}

/** Child routes declare the capability they need in `handle`; this checks it before rendering them. */
export function CapabilityOutlet() {
  const matches = useMatches();
  const capability = matches
    .map((match) => (match.handle as { capability?: Capability } | undefined)?.capability)
    .findLast(Boolean);
  if (!capability) return <Outlet />;
  return (
    <RequireCapability capability={capability}>
      <Outlet />
    </RequireCapability>
  );
}

export function RequireCapability({ capability, children }: { capability: Capability; children: ReactNode }) {
  const { data: me } = useMe();
  if (!can(me, capability)) {
    return (
      <Alert color="red" title="No access">
        You do not have permission to open this page. Ask a journal administrator if you need access.
      </Alert>
    );
  }
  return children;
}
