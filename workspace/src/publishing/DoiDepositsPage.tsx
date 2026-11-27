import { Anchor, Badge, Card, SegmentedControl, Stack, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDateTime } from "../lib/format";
import { doiDepositsKey } from "./queries";

const FILTERS = [
  { value: "", label: "All" },
  { value: "failed", label: "Failed" },
  { value: "submitted", label: "Submitted" },
  { value: "registered", label: "Registered" },
];

export const DEPOSIT_STATUS: Record<string, { label: string; color: string }> = {
  queued: { label: "Waiting", color: "gray" },
  submitted: { label: "Submitted", color: "blue" },
  registered: { label: "Registered", color: "green" },
  failed: { label: "Failed", color: "red" },
};

export function DoiDepositsPage() {
  const [status, setStatus] = useState("");
  const deposits = useQuery({
    queryKey: doiDepositsKey(status),
    queryFn: () =>
      unwrap(api.GET("/api/v1/publishing/doi-deposits", { params: { query: { status: status || null } } })),
  });
  return (
    <Stack>
      <PageHeader
        title="DOI deposits"
        description="Each time an article's metadata is sent to Crossref, and what Crossref answered. Failed deposits can be sent again from the article's Publication tab."
      />
      <SegmentedControl value={status} onChange={setStatus} data={FILTERS} w={{ base: "100%", sm: 440 }} />
      {deposits.data ? (
        deposits.data.length === 0 ? (
          <Text c="dimmed">No deposits here.</Text>
        ) : (
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={820}>
              <Table verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Article</Table.Th>
                    <Table.Th>DOI</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Crossref's answer</Table.Th>
                    <Table.Th>Sent</Table.Th>
                    <Table.Th>Completed</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {deposits.data.map((deposit) => {
                    const state = DEPOSIT_STATUS[deposit.status] ?? { label: deposit.status, color: "gray" };
                    return (
                      <Table.Tr key={deposit.id}>
                        <Table.Td>
                          <Anchor
                            component={Link}
                            to={`/submissions/${deposit.submission_id}`}
                            size="sm"
                            ff="monospace"
                          >
                            {deposit.submission_number ?? deposit.submission_id}
                          </Anchor>
                          <Text size="sm" lineClamp={2}>
                            {deposit.title}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Anchor
                            href={`https://doi.org/${deposit.doi}`}
                            target="_blank"
                            rel="noreferrer"
                            size="sm"
                            ff="monospace"
                          >
                            {deposit.doi}
                          </Anchor>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={4} align="flex-start">
                            <Badge color={state.color} variant="light">
                              {state.label}
                            </Badge>
                            {deposit.mode !== "production" ? (
                              <Badge color="gray" variant="outline" size="xs">
                                {deposit.mode}
                              </Badge>
                            ) : null}
                          </Stack>
                        </Table.Td>
                        <Table.Td>
                          <Text
                            size="sm"
                            c={deposit.status === "failed" ? "red" : undefined}
                            className="pre-wrap"
                          >
                            {deposit.message || "—"}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{formatDateTime(deposit.submitted_at ?? deposit.created_at)}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{formatDateTime(deposit.completed_at)}</Text>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        )
      ) : (
        <QueryState
          isPending={deposits.isPending}
          error={deposits.error}
          onRetry={() => deposits.refetch()}
        />
      )}
    </Stack>
  );
}
