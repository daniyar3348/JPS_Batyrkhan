import type { AuditEventOut } from "@jps/api-client";
import { Badge, Button, Card, Code, Group, Select, Stack, Table, Text } from "@mantine/core";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../../api";
import { PageHeader, QueryState } from "../../components/common";
import { formatDateTime } from "../../lib/format";
import { ROLE_LABELS } from "../../lib/roles";

const ACTIONS: Record<string, string> = {
  "journal.created": "Journal created",
  "journal.updated": "Journal settings changed",
  "section.created": "Section created",
  "section.updated": "Section changed",
  "section.deleted": "Section deleted",
  "section.editors_changed": "Section editors changed",
  "user.registered": "Registered",
  "user.invited": "Invited",
  "user.invitation_accepted": "Accepted invitation",
  "user.roles_changed": "Roles changed",
  "user.activated": "Account activated",
  "user.deactivated": "Account deactivated",
  "user.password_reset": "Password reset by e-mail",
  "user.password_changed": "Password changed",
};

const ENTITY_TYPES = [
  { value: "user", label: "Users" },
  { value: "section", label: "Sections" },
  { value: "journal", label: "Journal" },
];

function roleList(value: unknown): string {
  return Array.isArray(value)
    ? value.map((role) => ROLE_LABELS[role as keyof typeof ROLE_LABELS] ?? String(role)).join(", ")
    : "";
}

/** A one-line, human-readable summary of the event's details. */
function describe(event: AuditEventOut): string {
  const data = event.data as Record<string, unknown>;
  const parts: string[] = [];
  if (Array.isArray(data.fields)) parts.push(`Fields: ${data.fields.join(", ")}`);
  if (data.title) parts.push(String(data.title));
  // Users: added/removed roles. Sections: added/removed editors (names).
  const names =
    event.entity_type === "user"
      ? roleList
      : (value: unknown) => (Array.isArray(value) ? value.join(", ") : "");
  if (names(data.added)) parts.push(`Added: ${names(data.added)}`);
  if (names(data.removed)) parts.push(`Removed: ${names(data.removed)}`);
  if (Array.isArray(data.roles)) parts.push(`Roles: ${roleList(data.roles)}`);
  return parts.join(" · ");
}

export function AuditLogPage() {
  const [entityType, setEntityType] = useState<string | null>(null);
  const events = useInfiniteQuery({
    queryKey: ["audit-events", entityType],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/audit-events", {
          params: {
            query: { entity_type: entityType ?? undefined, cursor: pageParam ?? undefined, limit: 50 },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
  });
  const rows = events.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Stack>
      <PageHeader
        title="Audit log"
        description="Important actions, newest first. Entries cannot be edited or deleted."
      />
      <Select
        placeholder="Everything"
        data={ENTITY_TYPES}
        value={entityType}
        onChange={setEntityType}
        clearable
        w={{ base: "100%", sm: 220 }}
      />
      {events.data ? (
        <Card withBorder padding={0}>
          {rows.length === 0 ? (
            <Text c="dimmed" p="lg">
              Nothing recorded yet.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={760}>
              <Table verticalSpacing="sm" horizontalSpacing="md">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={170}>When</Table.Th>
                    <Table.Th>Who</Table.Th>
                    <Table.Th>What</Table.Th>
                    <Table.Th>Details</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((event) => (
                    <Table.Tr key={event.id}>
                      <Table.Td>
                        <Text size="sm">{formatDateTime(event.created_at)}</Text>
                        {event.ip ? (
                          <Text size="xs" c="dimmed">
                            {event.ip}
                          </Text>
                        ) : null}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{event.actor?.full_name ?? "System"}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={6} wrap="nowrap">
                          <Text size="sm">{ACTIONS[event.action] ?? event.action}</Text>
                          <Badge variant="light" color="gray" size="xs">
                            {event.entity_type} #{event.entity_id}
                          </Badge>
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        {describe(event) ? (
                          <Text size="sm">{describe(event)}</Text>
                        ) : Object.keys(event.data).length > 0 ? (
                          <Code>{JSON.stringify(event.data)}</Code>
                        ) : (
                          <Text size="sm" c="dimmed">
                            —
                          </Text>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          {events.hasNextPage ? (
            <Group justify="center" p="md">
              <Button
                variant="light"
                loading={events.isFetchingNextPage}
                onClick={() => events.fetchNextPage()}
              >
                Show older entries
              </Button>
            </Group>
          ) : null}
        </Card>
      ) : (
        <QueryState isPending={events.isPending} error={events.error} onRetry={() => events.refetch()} />
      )}
    </Stack>
  );
}
