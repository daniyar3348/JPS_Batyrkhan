import type { AssignmentOut, FileOut, RoundOut, WorkflowOut } from "@jps/api-client";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Menu,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import {
  IconAlertTriangle,
  IconBell,
  IconCalendar,
  IconDots,
  IconDownload,
  IconEye,
  IconUserPlus,
  IconX,
} from "@tabler/icons-react";
import { useState } from "react";
import { formatDate, formatDateTime } from "../lib/format";
import { FILE_STATUS, GENRE_LABELS } from "../submissions/labels";
import { AddReviewerModal } from "./AddReviewerModal";
import { ASSIGNMENT_STATUS, RECOMMENDATION_COLORS, RECOMMENDATION_LABELS, ROUND_STATUS } from "./labels";
import { DatesModal, ReadReviewModal, RemindModal, useCancelReview } from "./ReviewerActions";

export function FileList({ files, empty }: { files: FileOut[]; empty: string }) {
  if (files.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        {empty}
      </Text>
    );
  }
  return (
    <Stack gap={4}>
      {files.map((file) => (
        <Group key={file.id} gap="xs" wrap="nowrap">
          {file.download_url ? (
            <Anchor href={file.download_url} size="sm">
              <Group gap={6} wrap="nowrap">
                <IconDownload size={14} />
                {file.name}
              </Group>
            </Anchor>
          ) : (
            <Text size="sm">{file.name}</Text>
          )}
          <Text size="xs" c="dimmed">
            {GENRE_LABELS[file.genre]}
          </Text>
          {file.status !== "ready" ? (
            <Badge size="xs" variant="light" color={FILE_STATUS[file.status]?.color ?? "gray"}>
              {FILE_STATUS[file.status]?.label ?? file.status}
            </Badge>
          ) : null}
          {file.metadata_removed === false ? (
            <Tooltip label="The names in this file's properties could not be removed automatically. Check the file before reviewers use it.">
              <Badge size="xs" variant="light" color="orange" leftSection={<IconAlertTriangle size={10} />}>
                Check for names
              </Badge>
            </Tooltip>
          ) : null}
        </Group>
      ))}
    </Stack>
  );
}

function dueText(a: AssignmentOut): string {
  if (a.status === "invited") return `Answer by ${formatDate(a.response_due)}`;
  if (a.status === "accepted") return `Due ${formatDate(a.review_due)}`;
  if (a.status === "completed") return `Sent ${formatDate(a.completed_at)}`;
  if (a.status === "declined") return `Declined ${formatDate(a.responded_at)}`;
  return "";
}

function ReviewersTable({
  submissionId,
  round,
  canManage,
}: {
  submissionId: number;
  round: RoundOut;
  canManage: boolean;
}) {
  const [reading, setReading] = useState<AssignmentOut | null>(null);
  const [reminding, setReminding] = useState<AssignmentOut | null>(null);
  const [dating, setDating] = useState<AssignmentOut | null>(null);
  const cancel = useCancelReview(submissionId);
  const assignments = round.assignments ?? [];

  if (assignments.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No reviewers invited yet.
      </Text>
    );
  }
  return (
    <>
      <Table.ScrollContainer minWidth={640}>
        <Table verticalSpacing="sm">
          <Table.Tbody>
            {assignments.map((a) => {
              const look = ASSIGNMENT_STATUS[a.status] ?? { label: a.status, color: "gray" };
              const open = a.status === "invited" || a.status === "accepted";
              return (
                <Table.Tr key={a.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {a.reviewer.full_name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      Reviewer {a.reviewer_number}
                      {a.reviewer.affiliation ? ` · ${a.reviewer.affiliation}` : ""}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6}>
                      <Badge variant="light" color={look.color}>
                        {look.label}
                      </Badge>
                      {a.overdue ? (
                        <Badge color="red" variant="filled" size="sm">
                          Overdue
                        </Badge>
                      ) : null}
                      {a.recommendation ? (
                        <Badge variant="outline" color={RECOMMENDATION_COLORS[a.recommendation]}>
                          {RECOMMENDATION_LABELS[a.recommendation]}
                        </Badge>
                      ) : null}
                      {a.rating ? (
                        <Text size="xs" c="dimmed">
                          {"★".repeat(a.rating)}
                        </Text>
                      ) : null}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{dueText(a)}</Text>
                    {a.last_reminded_at ? (
                      <Text size="xs" c="dimmed">
                        Reminded {formatDateTime(a.last_reminded_at)}
                      </Text>
                    ) : null}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      {a.status === "completed" || a.status === "declined" ? (
                        <Button
                          size="compact-sm"
                          variant="light"
                          leftSection={<IconEye size={14} />}
                          onClick={() => setReading(a)}
                        >
                          {a.status === "completed" ? "Read" : "Details"}
                        </Button>
                      ) : null}
                      {canManage && open ? (
                        <Menu position="bottom-end">
                          <Menu.Target>
                            <ActionIcon variant="subtle" aria-label={`Actions for ${a.reviewer.full_name}`}>
                              <IconDots size={18} />
                            </ActionIcon>
                          </Menu.Target>
                          <Menu.Dropdown>
                            <Menu.Item leftSection={<IconBell size={14} />} onClick={() => setReminding(a)}>
                              Send a reminder
                            </Menu.Item>
                            <Menu.Item leftSection={<IconCalendar size={14} />} onClick={() => setDating(a)}>
                              Change the dates
                            </Menu.Item>
                            <Menu.Item
                              color="red"
                              leftSection={<IconX size={14} />}
                              onClick={() =>
                                modals.openConfirmModal({
                                  title: `Cancel the request to ${a.reviewer.full_name}?`,
                                  children:
                                    "They will be told by e-mail that the review is no longer needed.",
                                  labels: { confirm: "Cancel the request", cancel: "Keep it" },
                                  confirmProps: { color: "red" },
                                  onConfirm: () => cancel.mutate(a.id),
                                })
                              }
                            >
                              Cancel the request
                            </Menu.Item>
                          </Menu.Dropdown>
                        </Menu>
                      ) : null}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <ReadReviewModal submissionId={submissionId} assignment={reading} onClose={() => setReading(null)} />
      <RemindModal submissionId={submissionId} assignment={reminding} onClose={() => setReminding(null)} />
      <DatesModal submissionId={submissionId} assignment={dating} onClose={() => setDating(null)} />
    </>
  );
}

function RoundPanel({
  submissionId,
  round,
  canManage,
}: {
  submissionId: number;
  round: RoundOut;
  canManage: boolean;
}) {
  const [inviting, setInviting] = useState(false);
  const status = ROUND_STATUS[round.status] ?? { label: round.status, color: "gray" };
  const completed = (round.assignments ?? []).filter((a) => a.status === "completed").length;
  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Group gap="xs">
          <Badge color={status.color} variant="light" size="lg">
            {status.label}
          </Badge>
          <Text size="sm" c="dimmed">
            Started {formatDate(round.created_at)} · {completed} review{completed === 1 ? "" : "s"} received
          </Text>
        </Group>
        {canManage && round.status === "review" ? (
          <Button leftSection={<IconUserPlus size={16} />} onClick={() => setInviting(true)}>
            Invite a reviewer
          </Button>
        ) : null}
      </Group>
      <Card withBorder padding="md">
        <Stack gap="xs">
          <Title order={5}>Reviewers</Title>
          <ReviewersTable submissionId={submissionId} round={round} canManage={canManage} />
        </Stack>
      </Card>
      <Card withBorder padding="md">
        <Stack gap="xs">
          <Title order={5}>Files for the reviewers</Title>
          <FileList files={round.review_files} empty="No files." />
        </Stack>
      </Card>
      {round.revision_files.length || round.author_response ? (
        <Card withBorder padding="md">
          <Stack gap="xs">
            <Title order={5}>Authors' revision</Title>
            {round.revisions_submitted_at ? (
              <Text size="xs" c="dimmed">
                Sent {formatDateTime(round.revisions_submitted_at)}
              </Text>
            ) : (
              <Text size="xs" c="dimmed">
                Not sent yet.
              </Text>
            )}
            <FileList files={round.revision_files} empty="No revised files." />
            {round.author_response ? (
              <Text size="sm" className="pre-wrap">
                {round.author_response}
              </Text>
            ) : null}
          </Stack>
        </Card>
      ) : null}
      <AddReviewerModal
        submissionId={submissionId}
        roundId={round.id}
        opened={inviting}
        onClose={() => setInviting(false)}
      />
    </Stack>
  );
}

/** Peer review as the editors see it: one tab per round, the latest open. */
export function ReviewRounds({ submissionId, workflow }: { submissionId: number; workflow: WorkflowOut }) {
  const rounds = workflow.rounds;
  const latest = rounds[rounds.length - 1];
  const [tab, setTab] = useState<string | null>(null);
  if (!latest) {
    return (
      <Alert color="gray" variant="light">
        The manuscript has not been sent to review. Use “Send to review” to start the first round.
      </Alert>
    );
  }
  const canManage = workflow.viewer.can_manage && workflow.status === "queued";
  return (
    <Tabs value={tab ?? String(latest.id)} onChange={setTab} variant="pills">
      <Tabs.List mb="md">
        {rounds.map((round) => (
          <Tabs.Tab key={round.id} value={String(round.id)}>
            Round {round.number}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {rounds.map((round) => (
        <Tabs.Panel key={round.id} value={String(round.id)}>
          <RoundPanel
            submissionId={submissionId}
            round={round}
            canManage={canManage && round.id === latest.id}
          />
        </Tabs.Panel>
      ))}
    </Tabs>
  );
}
