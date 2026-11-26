import type { Role } from "@jps/api-client";
import { Alert, Badge, Button, Center, Group, Loader, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { errorMessage } from "../api";
import { ROLE_COLORS, ROLE_LABELS } from "../lib/roles";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <Group justify="space-between" align="flex-end" gap="md">
      <Stack gap={4}>
        <Title order={2}>{title}</Title>
        {typeof description === "string" ? <Text c="dimmed">{description}</Text> : description}
      </Stack>
      {actions}
    </Group>
  );
}

export function RoleBadges({ roles, size = "sm" }: { roles: Role[]; size?: "xs" | "sm" | "md" }) {
  if (roles.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No roles
      </Text>
    );
  }
  return (
    <Group gap={6}>
      {roles.map((role) => (
        <Badge key={role} color={ROLE_COLORS[role]} variant="light" size={size}>
          {ROLE_LABELS[role]}
        </Badge>
      ))}
    </Group>
  );
}

/** Loading and error states for a query, so pages only render their happy path. */
export function QueryState({
  isPending,
  error,
  onRetry,
}: {
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  if (isPending) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  return (
    <Alert color="red" title="Could not load this page">
      <Stack gap="sm" align="flex-start">
        <Text size="sm">{errorMessage(error)}</Text>
        <Button size="xs" variant="light" color="red" onClick={onRetry}>
          Try again
        </Button>
      </Stack>
    </Alert>
  );
}
