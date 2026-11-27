import type { RoundOut, WorkflowOut } from "@jps/api-client";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Progress,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
  Tooltip,
} from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { modals } from "@mantine/modals";
import { IconFileUpload, IconSend, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../api";
import { formatDate } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { GENRE_LABELS } from "../submissions/labels";
import { useSubmissionSettings } from "../submissions/queries";
import { sendToStorage } from "../submissions/upload";
import { ROUND_STATUS } from "./labels";
import { workflowKey } from "./queries";
import { FileList } from "./ReviewRounds";

const GENRES = ["manuscript", "supplementary", "figure", "table", "cover_letter"] as const;
type Genre = (typeof GENRES)[number];

interface Upload {
  id: string;
  name: string;
  progress: number;
  error?: string;
}

/** Where the authors send their revised files and their reply to the reviewers. */
function RevisionPanel({ submissionId, round }: { submissionId: number; round: RoundOut }) {
  const queryClient = useQueryClient();
  const settings = useSubmissionSettings();
  const [genre, setGenre] = useState<Genre>("manuscript");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [response, setResponse] = useState(round.author_response);
  const refresh = () => queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
  const path = { submission_id: submissionId, round_id: round.id };

  const uploadOne = async (file: File) => {
    const id = `${file.name}-${Date.now()}`;
    setUploads((current) => [...current, { id, name: file.name, progress: 0 }]);
    const update = (patch: Partial<Upload>) =>
      setUploads((current) => current.map((u) => (u.id === id ? { ...u, ...patch } : u)));
    try {
      const ticket = await unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-rounds/{round_id}/revisions/uploads", {
          params: { path },
          body: { file_name: file.name, size: file.size, genre },
        }),
      );
      await sendToStorage(ticket.upload, file, (progress) => update({ progress }));
      await unwrap(
        api.POST(
          "/api/v1/submissions/{submission_id}/review-rounds/{round_id}/revisions/{file_id}/complete",
          {
            params: { path: { ...path, file_id: ticket.file.id } },
          },
        ),
      );
      setUploads((current) => current.filter((u) => u.id !== id));
      refresh();
    } catch (error) {
      update({ error: error instanceof Error ? error.message : "The upload failed." });
    }
  };

  const remove = useMutation({
    mutationFn: (fileId: number) =>
      unwrap(
        api.DELETE("/api/v1/submissions/{submission_id}/review-rounds/{round_id}/revisions/{file_id}", {
          params: { path: { ...path, file_id: fileId } },
        }),
      ),
    onSuccess: refresh,
    onError: (error) => showRequestError(error),
  });

  const submit = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-rounds/{round_id}/revisions/submit", {
          params: { path },
          body: { response },
        }),
      ),
    onSuccess: () => {
      refresh();
      notifySaved("Your revision has been sent to the editors");
    },
    onError: (error) => showRequestError(error),
  });

  const ready = round.revision_files.some((f) => f.status === "ready");
  const busy = uploads.some((u) => !u.error) || round.revision_files.some((f) => f.status === "processing");
  const maxMb = settings.data?.max_file_size_mb ?? 50;

  return (
    <Card withBorder padding="lg" bg="var(--mantine-color-orange-0)">
      <Stack>
        <Title order={4}>Send your revision</Title>
        <Text size="sm">
          {round.status === "resubmit_requested"
            ? "Your revised manuscript will go to another round of review."
            : "The editor will decide on your revised manuscript."}{" "}
          Upload the revised files and explain how you answered each comment.
        </Text>
        <Group align="flex-end">
          <Select
            label="Type of file"
            data={GENRES.map((value) => ({ value, label: GENRE_LABELS[value] }))}
            value={genre}
            onChange={(value) => value && setGenre(value as Genre)}
            allowDeselect={false}
            w={220}
          />
        </Group>
        <Dropzone
          onDrop={(files) => {
            for (const file of files) void uploadOne(file);
          }}
          maxSize={maxMb * 1024 * 1024}
        >
          <Group justify="center" gap="md" mih={80} style={{ pointerEvents: "none" }}>
            <IconFileUpload size={32} stroke={1.4} color="var(--mantine-color-indigo-6)" />
            <Stack gap={0}>
              <Text fw={500}>Drop files here or click to choose</Text>
              <Text size="sm" c="dimmed">
                Up to {maxMb} MB each
              </Text>
            </Stack>
          </Group>
        </Dropzone>
        {uploads.map((upload) => (
          <Stack key={upload.id} gap={4}>
            <Text size="sm">{upload.name}</Text>
            {upload.error ? (
              <Text size="sm" c="red">
                {upload.error}
              </Text>
            ) : (
              <Progress value={upload.progress * 100} size="sm" animated />
            )}
          </Stack>
        ))}
        {round.revision_files.length ? (
          <Stack gap={4}>
            {round.revision_files.map((file) => (
              <Group key={file.id} justify="space-between" wrap="nowrap">
                <FileList files={[file]} empty="" />
                <Tooltip label="Remove">
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    aria-label={`Remove ${file.name}`}
                    onClick={() => remove.mutate(file.id)}
                  >
                    <IconTrash size={16} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            ))}
          </Stack>
        ) : null}
        <Textarea
          label="Response to the reviewers"
          description="How you addressed each comment, or why you did not."
          autosize
          minRows={4}
          maxRows={16}
          value={response}
          onChange={(event) => setResponse(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button
            leftSection={<IconSend size={16} />}
            disabled={!ready || busy}
            loading={submit.isPending}
            onClick={() =>
              modals.openConfirmModal({
                title: "Send the revision?",
                children: "The editors will be told. You cannot change the files afterwards.",
                labels: { confirm: "Send", cancel: "Not yet" },
                onConfirm: () => submit.mutate(),
              })
            }
          >
            Send revision
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

/** Reviews and revisions, as the authors see them: reviews appear once the editor has decided. */
export function AuthorReviews({ submissionId, workflow }: { submissionId: number; workflow: WorkflowOut }) {
  const rounds = [...workflow.rounds].reverse();
  if (rounds.length === 0) {
    return (
      <Alert color="gray" variant="light">
        Your manuscript has not been sent to review yet.
      </Alert>
    );
  }
  const latest = workflow.rounds[workflow.rounds.length - 1];
  return (
    <Stack gap="lg">
      {rounds.map((round) => {
        const status = ROUND_STATUS[round.status] ?? { label: round.status, color: "gray" };
        const awaiting =
          round.id === latest?.id &&
          workflow.status === "queued" &&
          (round.status === "revisions_requested" || round.status === "resubmit_requested");
        return (
          <Stack key={round.id} gap="sm">
            <Group gap="xs">
              <Title order={4}>Round {round.number}</Title>
              <Badge variant="light" color={status.color}>
                {status.label}
              </Badge>
              <Text size="sm" c="dimmed">
                since {formatDate(round.created_at)}
              </Text>
            </Group>
            {awaiting ? <RevisionPanel submissionId={submissionId} round={round} /> : null}
            {round.reviews_for_author === null ? (
              <Text size="sm" c="dimmed">
                The reviews will appear here when the editor has made a decision.
              </Text>
            ) : round.reviews_for_author.length === 0 ? (
              <Text size="sm" c="dimmed">
                No reviews were received in this round.
              </Text>
            ) : (
              round.reviews_for_author.map((review) => (
                <Card key={review.label} withBorder padding="lg">
                  <Stack gap="sm">
                    <Title order={5}>{review.label}</Title>
                    {review.answers.map((answer) => (
                      <Stack key={answer.question} gap={2}>
                        <Text size="xs" c="dimmed" fw={600}>
                          {answer.question}
                        </Text>
                        <Text size="sm" className="pre-wrap">
                          {answer.answer}
                        </Text>
                      </Stack>
                    ))}
                    {review.comments ? (
                      <Text size="sm" className="pre-wrap">
                        {review.comments}
                      </Text>
                    ) : null}
                    {review.attachments.length ? <FileList files={review.attachments} empty="" /> : null}
                  </Stack>
                </Card>
              ))
            )}
            {!awaiting && (round.revision_files.length || round.author_response) ? (
              <Card withBorder padding="md">
                <Stack gap="xs">
                  <Text size="sm" fw={600}>
                    Your revision
                  </Text>
                  <FileList files={round.revision_files} empty="" />
                  {round.author_response ? (
                    <Text size="sm" className="pre-wrap">
                      {round.author_response}
                    </Text>
                  ) : null}
                </Stack>
              </Card>
            ) : null}
          </Stack>
        );
      })}
    </Stack>
  );
}
