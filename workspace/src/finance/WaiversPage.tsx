import type { WaiverRow } from "@jps/api-client";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  NumberInput,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate, formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { look, WAIVER_STATUS } from "../payments/labels";

const FILTERS = [
  { value: "pending", label: "To decide" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Not approved" },
  { value: "", label: "All" },
];

function DecideModal({ waiver, onClose }: { waiver: WaiverRow; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState("approve");
  const [percent, setPercent] = useState<number | string>(waiver.percent);
  const [note, setNote] = useState("");
  const approve = choice === "approve";
  const decide = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/payments/waiver-requests/{waiver_id}/decision", {
          params: { path: { waiver_id: waiver.id } },
          body: { approve, percent: approve ? Number(percent) : null, note },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["payments", "waivers"] });
      queryClient.invalidateQueries({ queryKey: ["payments", "invoices"] });
      queryClient.invalidateQueries({ queryKey: ["payments", "summary"] });
      notifySaved(approve ? "Waiver approved" : "Waiver not approved");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  const valid = !approve || (Number(percent) >= 1 && Number(percent) <= 100);
  return (
    <Modal opened onClose={onClose} title={`Waiver for ${waiver.submission_number ?? "the manuscript"}`}>
      <Stack>
        <Text size="sm">
          {waiver.requested_by} asks for a {waiver.percent}% waiver.
        </Text>
        <Text size="sm" c="dimmed" className="pre-wrap">
          {waiver.reason}
        </Text>
        <SegmentedControl
          value={choice}
          onChange={setChoice}
          data={[
            { value: "approve", label: "Approve" },
            { value: "reject", label: "Do not approve" },
          ]}
        />
        {approve ? (
          <NumberInput
            label="Share of the fee waived, %"
            description="100% settles the invoice; less reduces it. Without an invoice yet, it applies when one is issued."
            min={1}
            max={100}
            value={percent}
            onChange={setPercent}
          />
        ) : null}
        <Textarea
          label="Note to the author"
          description="Sent to the author with the decision."
          autosize
          minRows={2}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            color={approve ? undefined : "red"}
            loading={decide.isPending}
            disabled={!valid}
            onClick={() => decide.mutate()}
          >
            {approve ? "Approve" : "Do not approve"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function WaiverCard({ waiver, onDecide }: { waiver: WaiverRow; onDecide: (waiver: WaiverRow) => void }) {
  const state = look(WAIVER_STATUS, waiver.status);
  return (
    <Card withBorder padding="lg">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={2}>
            <Anchor component={Link} to={`/submissions/${waiver.submission_id}`} size="sm" ff="monospace">
              {waiver.submission_number ?? "Manuscript"}
            </Anchor>
            <Text fw={600} lineClamp={2}>
              {waiver.submission_title}
            </Text>
            <Text size="sm" c="dimmed">
              {waiver.requested_by} · {formatDate(waiver.created_at)} · asks for {waiver.percent}%
            </Text>
          </Stack>
          <Badge variant="light" color={state.color}>
            {state.label}
          </Badge>
        </Group>
        <Text size="sm" className="pre-wrap">
          {waiver.reason}
        </Text>
        {waiver.status !== "pending" ? (
          <Text size="sm" c="dimmed">
            {waiver.status === "approved" ? `${waiver.approved_percent}% waived` : "Not approved"}
            {waiver.decided_at ? ` on ${formatDateTime(waiver.decided_at)}` : ""}
            {waiver.decision_note ? `: ${waiver.decision_note}` : ""}
          </Text>
        ) : (
          <Group justify="flex-end">
            <Button size="sm" onClick={() => onDecide(waiver)}>
              Decide
            </Button>
          </Group>
        )}
      </Stack>
    </Card>
  );
}

export function WaiversPage() {
  const [status, setStatus] = useState("pending");
  const [deciding, setDeciding] = useState<WaiverRow | null>(null);
  const waivers = useQuery({
    queryKey: ["payments", "waivers", status],
    queryFn: () =>
      unwrap(api.GET("/api/v1/payments/waiver-requests", { params: { query: { status: status || null } } })),
  });
  return (
    <Stack>
      <PageHeader
        title="Waiver requests"
        description="Authors' requests to reduce or waive the publication fee. The editors never see them."
      />
      <SegmentedControl value={status} onChange={setStatus} data={FILTERS} w={{ base: "100%", sm: 480 }} />
      {waivers.data ? (
        waivers.data.length === 0 ? (
          <Text c="dimmed">{status === "pending" ? "Nothing to decide." : "No requests here."}</Text>
        ) : (
          <Stack gap="md">
            {waivers.data.map((waiver) => (
              <WaiverCard key={waiver.id} waiver={waiver} onDecide={setDeciding} />
            ))}
          </Stack>
        )
      ) : (
        <QueryState isPending={waivers.isPending} error={waivers.error} onRetry={() => waivers.refetch()} />
      )}
      {deciding ? <DecideModal waiver={deciding} onClose={() => setDeciding(null)} /> : null}
    </Stack>
  );
}
