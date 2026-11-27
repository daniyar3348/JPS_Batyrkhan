import type { SummaryLine } from "@jps/api-client";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconSearch } from "@tabler/icons-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate } from "../lib/format";
import { INVOICE_STATUS, look, money } from "../payments/labels";

const PAGE_SIZE = 50;

const STATUSES = [
  { value: "", label: "All" },
  { value: "issued", label: "Awaiting payment" },
  { value: "paid", label: "Paid" },
  { value: "waived", label: "Waived" },
  { value: "void", label: "Void" },
  { value: "refunded", label: "Refunded" },
];

const TILES: { status: string; label: string }[] = [
  { status: "issued", label: "Awaiting payment" },
  { status: "paid", label: "Paid" },
  { status: "waived", label: "Waived" },
];

/** Totals per status, one line per currency (a journal can change its currency over time). */
function SummaryTiles({ lines }: { lines: SummaryLine[] }) {
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }}>
      {TILES.map((tile) => {
        const rows = lines.filter((line) => line.status === tile.status);
        const count = rows.reduce((sum, line) => sum + line.count, 0);
        return (
          <Card key={tile.status} withBorder padding="md">
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              {tile.label}
            </Text>
            <Text size="xl" fw={700}>
              {count} {count === 1 ? "invoice" : "invoices"}
            </Text>
            {rows.length === 0 ? (
              <Text size="sm" c="dimmed">
                —
              </Text>
            ) : (
              rows.map((line) => (
                <Text key={line.currency} size="sm" c="dimmed">
                  {money(line.amount, line.currency)}
                </Text>
              ))
            )}
          </Card>
        );
      })}
    </SimpleGrid>
  );
}

export function InvoicesPage() {
  const [search, setSearch] = useState("");
  const [q] = useDebouncedValue(search.trim(), 300);
  const [status, setStatus] = useState("");
  const [overdue, setOverdue] = useState(false);

  const summary = useQuery({
    queryKey: ["payments", "summary"],
    queryFn: () => unwrap(api.GET("/api/v1/payments/summary")),
  });

  const invoices = useInfiniteQuery({
    queryKey: ["payments", "invoices", q, status, overdue],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/payments/invoices", {
          params: {
            query: {
              q: q || undefined,
              status: status || undefined,
              overdue,
              limit: PAGE_SIZE,
              offset: pageParam,
            },
          },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (page, pages) => {
      const loaded = pages.reduce((sum, item) => sum + item.items.length, 0);
      return loaded < page.total ? loaded : undefined;
    },
  });
  const rows = invoices.data?.pages.flatMap((page) => page.items) ?? [];
  const total = invoices.data?.pages[0]?.total ?? 0;

  return (
    <Stack>
      <PageHeader
        title="Invoices"
        description="Publication fees: issued when a manuscript is accepted, paid by the authors or their institutions."
      />
      {summary.data ? <SummaryTiles lines={summary.data} /> : null}
      <Group>
        <TextInput
          placeholder="Search by invoice, payer or manuscript number"
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          w={{ base: "100%", sm: 360 }}
        />
        <Select
          data={STATUSES}
          value={status}
          onChange={(value) => setStatus(value ?? "")}
          allowDeselect={false}
          w={{ base: "100%", sm: 200 }}
          aria-label="Status"
        />
        <Switch
          label="Overdue only"
          checked={overdue}
          onChange={(event) => setOverdue(event.currentTarget.checked)}
        />
      </Group>
      {invoices.data ? (
        <Card withBorder padding={0}>
          {rows.length === 0 ? (
            <Text c="dimmed" p="lg">
              No invoices here.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={900}>
              <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={150}>Invoice</Table.Th>
                    <Table.Th>Manuscript</Table.Th>
                    <Table.Th>Payer</Table.Th>
                    <Table.Th ta="right">Total</Table.Th>
                    <Table.Th w={190}>Status</Table.Th>
                    <Table.Th w={120}>Due</Table.Th>
                    <Table.Th w={120}>Paid</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((row) => {
                    const state = look(INVOICE_STATUS, row.status);
                    return (
                      <Table.Tr key={row.id}>
                        <Table.Td>
                          <Anchor
                            component={Link}
                            to={`/finance/invoices/${row.id}`}
                            size="sm"
                            ff="monospace"
                          >
                            {row.number}
                          </Anchor>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm" ff="monospace">
                            {row.submission_number ?? "—"}
                          </Text>
                          <Text size="xs" c="dimmed" lineClamp={1}>
                            {row.submission_title}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{row.payer_name}</Text>
                        </Table.Td>
                        <Table.Td ta="right">
                          <Text size="sm" style={{ whiteSpace: "nowrap" }}>
                            {money(row.total, row.currency)}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Group gap={6}>
                            <Badge variant="light" color={state.color}>
                              {state.label}
                            </Badge>
                            {row.overdue ? (
                              <Badge variant="filled" color="red">
                                Overdue
                              </Badge>
                            ) : null}
                          </Group>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{formatDate(row.due_date)}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{formatDate(row.paid_at)}</Text>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Card>
      ) : (
        <QueryState
          isPending={invoices.isPending}
          error={invoices.error}
          onRetry={() => invoices.refetch()}
        />
      )}
      {invoices.data && rows.length > 0 ? (
        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            Showing {rows.length} of {total}
          </Text>
          {invoices.hasNextPage ? (
            <Button
              variant="default"
              loading={invoices.isFetchingNextPage}
              onClick={() => invoices.fetchNextPage()}
            >
              Load more
            </Button>
          ) : null}
        </Group>
      ) : null}
    </Stack>
  );
}
