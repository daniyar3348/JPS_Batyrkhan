import { Anchor, Badge, Button, Card, Group, SegmentedControl, Stack, Table, Text } from "@mantine/core";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate } from "../lib/format";
import { statusLook } from "../submissions/labels";

/** Accepted articles the user copyedits, typesets or proofreads. */
export function ProductionWorkPage() {
  const [show, setShow] = useState<"open" | "all">("open");
  const work = useInfiniteQuery({
    queryKey: ["submissions", "production-work", show],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/submissions/production-work", {
          params: { query: { cursor: pageParam ?? undefined, include_done: show === "all" } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
  });
  const rows = work.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <Stack>
      <PageHeader
        title="Production work"
        description="Accepted articles you are assigned to copyedit, typeset or proofread."
        actions={
          <SegmentedControl
            value={show}
            onChange={(value) => setShow(value as "open" | "all")}
            data={[
              { value: "open", label: "In progress" },
              { value: "all", label: "All" },
            ]}
          />
        }
      />
      {work.data ? (
        <Card withBorder padding={0}>
          {rows.length === 0 ? (
            <Text p="lg" c="dimmed">
              Nothing assigned to you {show === "open" ? "at the moment" : "yet"}.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={640}>
              <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Number</Table.Th>
                    <Table.Th>Title</Table.Th>
                    <Table.Th>Section</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Submitted</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((row) => {
                    const look = statusLook(row);
                    return (
                      <Table.Tr key={row.id}>
                        <Table.Td>
                          <Anchor component={Link} to={`/submissions/${row.id}`} fw={500}>
                            {row.number}
                          </Anchor>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{row.title || "Untitled"}</Text>
                          <Text size="xs" c="dimmed">
                            {row.authors}
                          </Text>
                        </Table.Td>
                        <Table.Td>{row.section.title}</Table.Td>
                        <Table.Td>
                          <Badge variant="light" color={look.color}>
                            {look.label}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{row.submitted_at ? formatDate(row.submitted_at) : "—"}</Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          {work.hasNextPage ? (
            <Group justify="center" p="sm">
              <Button variant="subtle" loading={work.isFetchingNextPage} onClick={() => work.fetchNextPage()}>
                Show more
              </Button>
            </Group>
          ) : null}
        </Card>
      ) : (
        <QueryState isPending={work.isPending} error={work.error} onRetry={() => work.refetch()} />
      )}
    </Stack>
  );
}
