import type { AssignmentOut } from "@jps/api-client";
import {
  Anchor,
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Rating,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconDownload, IconEyeOff } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, unwrap } from "../api";
import { QueryState } from "../components/common";
import { formatDate, formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { type EmailDraft, EmailEditor } from "./EmailEditor";
import { DECLINE_REASON_LABELS, METHOD_LABELS, RECOMMENDATION_COLORS, RECOMMENDATION_LABELS } from "./labels";
import { workflowKey } from "./queries";

function useRefresh(submissionId: number) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
}

function answerText(value: unknown): string {
  return Array.isArray(value) ? value.join(", ") : String(value ?? "");
}

function Block({ label, children, hidden }: { label: string; children: React.ReactNode; hidden?: boolean }) {
  return (
    <Stack gap={2}>
      <Group gap={6}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          {label}
        </Text>
        {hidden ? (
          <Badge size="xs" variant="light" color="gray" leftSection={<IconEyeOff size={10} />}>
            Editors only
          </Badge>
        ) : null}
      </Group>
      {children}
    </Stack>
  );
}

/** The whole review as the editors see it; a finished review can be rated and the reviewer thanked. */
export function ReadReviewModal({
  submissionId,
  assignment,
  onClose,
}: {
  submissionId: number;
  assignment: AssignmentOut | null;
  onClose: () => void;
}) {
  const refresh = useRefresh(submissionId);
  const [rating, setRating] = useState(0);
  const [thank, setThank] = useState(true);
  const [email, setEmail] = useState<EmailDraft>({ subject: "", body: "" });
  const completed = assignment?.status === "completed";
  const acknowledged = !!assignment?.acknowledged_at;

  const thanks = useQuery({
    queryKey: ["thanks-preview", assignment?.id],
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-assignments/{assignment_id}/thanks-preview", {
          // biome-ignore lint/style/noNonNullAssertion: enabled only with an assignment
          params: { path: { submission_id: submissionId, assignment_id: assignment!.id } },
        }),
      ),
    enabled: completed && !acknowledged,
    gcTime: 0,
  });
  useEffect(() => {
    if (thanks.data) setEmail({ subject: thanks.data.subject, body: thanks.data.body });
  }, [thanks.data]);
  useEffect(() => {
    setRating(assignment?.rating ?? 0);
    setThank(true);
  }, [assignment]);

  const acknowledge = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-assignments/{assignment_id}/acknowledge", {
          // biome-ignore lint/style/noNonNullAssertion: the button is only shown with an assignment
          params: { path: { submission_id: submissionId, assignment_id: assignment!.id } },
          body: {
            rating: rating || null,
            send_thanks: thank && !acknowledged,
            email: thank && !acknowledged ? email : null,
          },
        }),
      ),
    onSuccess: () => {
      refresh();
      notifySaved(acknowledged ? "Rating saved" : "Review acknowledged");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });

  if (!assignment) return null;
  const a = assignment;
  return (
    <Modal opened onClose={onClose} title={`Review by ${a.reviewer.full_name}`} size="xl">
      <Stack>
        <Group gap="xs">
          <Badge variant="light">{METHOD_LABELS[a.method]}</Badge>
          <Text size="sm" c="dimmed">
            Reviewer {a.reviewer_number} to the authors · round {a.round_number}
          </Text>
        </Group>
        {a.status === "declined" ? (
          <Block label="Declined">
            <Text size="sm">
              {DECLINE_REASON_LABELS[a.decline_reason ?? ""] ?? a.decline_reason}
              {a.decline_comment ? ` — ${a.decline_comment}` : ""}
            </Text>
          </Block>
        ) : null}
        {a.competing_interests ? (
          <Block label="Competing interests" hidden>
            <Text size="sm" className="pre-wrap">
              {a.competing_interests}
            </Text>
          </Block>
        ) : null}
        {a.recommendation ? (
          <Block label="Recommendation" hidden>
            <Badge color={RECOMMENDATION_COLORS[a.recommendation]} size="lg" variant="light">
              {RECOMMENDATION_LABELS[a.recommendation]}
            </Badge>
          </Block>
        ) : null}
        {a.questions
          .filter((q) => q.id && a.answers[q.id] !== undefined)
          .map((q) => (
            <Block key={q.id} label={q.label} hidden={!q.visible_to_author}>
              <Text size="sm" className="pre-wrap">
                {answerText(a.answers[q.id ?? ""])}
              </Text>
            </Block>
          ))}
        {a.comments_for_author ? (
          <Block label="Comments for the authors">
            <Text size="sm" className="pre-wrap">
              {a.comments_for_author}
            </Text>
          </Block>
        ) : null}
        {a.comments_for_editor ? (
          <Block label="Confidential comments for the editor" hidden>
            <Text size="sm" className="pre-wrap">
              {a.comments_for_editor}
            </Text>
          </Block>
        ) : null}
        {a.attachments.length ? (
          <Block label="Files">
            {a.attachments.map((file) =>
              file.download_url ? (
                <Anchor key={file.id} href={file.download_url} size="sm">
                  <Group gap={6}>
                    <IconDownload size={14} />
                    {file.name}
                  </Group>
                </Anchor>
              ) : (
                <Text key={file.id} size="sm" c="dimmed">
                  {file.name} (being checked)
                </Text>
              ),
            )}
          </Block>
        ) : null}
        {!completed && a.status !== "declined" ? (
          <Text size="sm" c="dimmed">
            The review has not been sent yet.
          </Text>
        ) : null}
        {completed ? (
          <>
            <Divider />
            <Title order={5}>{acknowledged ? "Your rating" : "Acknowledge the review"}</Title>
            <Group gap="xs">
              <Rating value={rating} onChange={setRating} />
              <Text size="xs" c="dimmed">
                Used when suggesting reviewers. The reviewer does not see it.
              </Text>
            </Group>
            {!acknowledged ? (
              thanks.data ? (
                <EmailEditor
                  value={email}
                  onChange={setEmail}
                  to={[a.reviewer.email]}
                  send={thank}
                  onSendChange={setThank}
                  sendLabel="Thank the reviewer by e-mail"
                />
              ) : (
                <QueryState
                  isPending={thanks.isPending}
                  error={thanks.error}
                  onRetry={() => thanks.refetch()}
                />
              )
            ) : (
              <Text size="sm" c="dimmed">
                Acknowledged {formatDateTime(a.acknowledged_at)}.
              </Text>
            )}
            <Group justify="flex-end">
              <Button loading={acknowledge.isPending} onClick={() => acknowledge.mutate()}>
                {acknowledged ? "Save rating" : "Acknowledge"}
              </Button>
            </Group>
          </>
        ) : null}
      </Stack>
    </Modal>
  );
}

/** Follow up with a reviewer who has not answered or whose review is due. */
export function RemindModal({
  submissionId,
  assignment,
  onClose,
}: {
  submissionId: number;
  assignment: AssignmentOut | null;
  onClose: () => void;
}) {
  const refresh = useRefresh(submissionId);
  const [email, setEmail] = useState<EmailDraft>({ subject: "", body: "" });
  const preview = useQuery({
    queryKey: ["reminder-preview", assignment?.id],
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-assignments/{assignment_id}/reminder-preview", {
          // biome-ignore lint/style/noNonNullAssertion: enabled only with an assignment
          params: { path: { submission_id: submissionId, assignment_id: assignment!.id } },
        }),
      ),
    enabled: !!assignment,
    gcTime: 0,
  });
  useEffect(() => {
    if (preview.data) setEmail({ subject: preview.data.subject, body: preview.data.body });
  }, [preview.data]);
  const send = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-assignments/{assignment_id}/remind", {
          // biome-ignore lint/style/noNonNullAssertion: the button is only shown with an assignment
          params: { path: { submission_id: submissionId, assignment_id: assignment!.id } },
          body: { email },
        }),
      ),
    onSuccess: () => {
      refresh();
      notifySaved("Reminder sent");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Modal opened={!!assignment} onClose={onClose} title="Send a reminder" size="xl">
      {preview.data ? (
        <Stack>
          <EmailEditor value={email} onChange={setEmail} to={preview.data.to} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button loading={send.isPending} onClick={() => send.mutate()}>
              Send reminder
            </Button>
          </Group>
        </Stack>
      ) : (
        <QueryState isPending={preview.isPending} error={preview.error} onRetry={() => preview.refetch()} />
      )}
    </Modal>
  );
}

/** Move a reviewer's deadlines. */
export function DatesModal({
  submissionId,
  assignment,
  onClose,
}: {
  submissionId: number;
  assignment: AssignmentOut | null;
  onClose: () => void;
}) {
  const refresh = useRefresh(submissionId);
  const [responseDue, setResponseDue] = useState("");
  const [reviewDue, setReviewDue] = useState("");
  useEffect(() => {
    setResponseDue(assignment?.response_due ?? "");
    setReviewDue(assignment?.review_due ?? "");
  }, [assignment]);
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/submissions/{submission_id}/review-assignments/{assignment_id}", {
          // biome-ignore lint/style/noNonNullAssertion: the button is only shown with an assignment
          params: { path: { submission_id: submissionId, assignment_id: assignment!.id } },
          body: { response_due: responseDue, review_due: reviewDue },
        }),
      ),
    onSuccess: () => {
      refresh();
      notifySaved("Dates changed");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Modal opened={!!assignment} onClose={onClose} title="Change the dates">
      <Stack>
        <Text size="sm" c="dimmed">
          Now: answer by {formatDate(assignment?.response_due)}, review due{" "}
          {formatDate(assignment?.review_due)}. Reminders follow the new dates.
        </Text>
        <SimpleGrid cols={2}>
          <TextInput
            type="date"
            label="Answer by"
            value={responseDue}
            onChange={(e) => setResponseDue(e.currentTarget.value)}
          />
          <TextInput
            type="date"
            label="Review due"
            value={reviewDue}
            onChange={(e) => setReviewDue(e.currentTarget.value)}
          />
        </SimpleGrid>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function useCancelReview(submissionId: number) {
  const refresh = useRefresh(submissionId);
  return useMutation({
    mutationFn: (assignmentId: number) =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-assignments/{assignment_id}/cancel", {
          params: { path: { submission_id: submissionId, assignment_id: assignmentId } },
          body: { notify: true },
        }),
      ),
    onSuccess: () => {
      refresh();
      notifySaved("Review request cancelled");
    },
    onError: (error) => showRequestError(error),
  });
}
