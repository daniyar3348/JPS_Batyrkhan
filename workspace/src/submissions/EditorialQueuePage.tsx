import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconSearch } from "@tabler/icons-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate } from "../lib/format";
import { statusLook } from "./labels";

const STATUSES = [
  { value: "queued", label: "In progress" },
  { value: "", label: "All" },
  { value: "published", label: "Published" },
  { value: "declined", label: "Declined" },
  { value: "withdrawn", label: "Withdrawn" },
];

export function EditorialQueuePage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [q] = useDebouncedValue(search.trim(), 300);
  const [status, setStatus] = useState("queued");
  const [sectionId, setSectionId] = useState<string | null>(null);
  const sections = useQuery({ queryKey: ["sections"], queryFn: () => unwrap(api.GET("/api/v1/sections")) });

  const queue = useInfiniteQuery({
    queryKey: ["submissions", "editorial", q, status, sectionId],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/submissions/editorial", {
          params: {
            query: {
              q: q || undefined,
              status,
              section_id: sectionId ? Number(sectionId) : undefined,
              cursor: pageParam ?? undefined,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
  });
  const rows = queue.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Stack>
      <PageHeader title="Editorial queue" description="Submitted manuscripts you handle, newest first." />
      <Group>
        <TextInput
          placeholder="Search by number or title"
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          w={{ base: "100%", sm: 320 }}
        />
        <Select
          data={STATUSES}
          value={status}
          onChange={(value) => setStatus(value ?? "")}
          w={{ base: "100%", sm: 160 }}
          allowDeselect={false}
        />
        <Select
          placeholder="All sections"
          data={(sections.data ?? []).map((s) => ({ value: String(s.id), label: s.title }))}
          value={sectionId}
          onChange={setSectionId}
          clearable
          w={{ base: "100%", sm: 220 }}
        />
      </Group>
      {queue.data ? (
        <Card withBorder padding={0}>
          {rows.length === 0 ? (
            <Text c="dimmed" p="lg">
              Nothing here.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={880}>
              <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={150}>Number</Table.Th>
                    <Table.Th>Manuscript</Table.Th>
                    <Table.Th w={140}>Section</Table.Th>
                    <Table.Th w={120}>Submitted</Table.Th>
                    <Table.Th w={110}>Similarity</Table.Th>
                    <Table.Th w={170}>Status</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((row) => {
                    const look = statusLook(row);
                    return (
                      <Table.Tr
                        key={row.id}
                        className="clickable-row"
                        onClick={() => navigate(`/submissions/${row.id}`)}
                      >
                        <Table.Td>
                          <Text size="sm" ff="monospace">
                            {row.number}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Anchor
                            component={Link}
                            to={`/submissions/${row.id}`}
                            size="sm"
                            fw={500}
                            c="inherit"
                            lineClamp={2}
                            onClick={(event) => event.stopPropagation()}
                          >
                            {row.title}
                          </Anchor>
                          <Text size="xs" c="dimmed" lineClamp={1}>
                            {row.authors}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{row.section.title}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{formatDate(row.submitted_at)}</Text>
                        </Table.Td>
                        <Table.Td>
                          {row.similarity_score !== null && row.similarity_score !== undefined ? (
                            <Tooltip
                              label={
                                row.similarity_flagged
                                  ? "Above the journal's threshold"
                                  : "Below the threshold"
                              }
                            >
                              <Badge color={row.similarity_flagged ? "red" : "teal"} variant="light">
                                {row.similarity_score}%
                              </Badge>
                            </Tooltip>
                          ) : (
                            <Text size="sm" c="dimmed">
                              —
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td>
                          <Badge color={look.color} variant="light">
                            {look.label}
                          </Badge>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          {queue.hasNextPage ? (
            <Group justify="center" p="md">
              <Button
                variant="light"
                loading={queue.isFetchingNextPage}
                onClick={() => queue.fetchNextPage()}
              >
                Show more
              </Button>
            </Group>
          ) : null}
        </Card>
      ) : (
        <QueryState isPending={queue.isPending} error={queue.error} onRetry={() => queue.refetch()} />
      )}
    </Stack>
  );
}
