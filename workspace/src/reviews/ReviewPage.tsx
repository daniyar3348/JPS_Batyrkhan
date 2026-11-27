import type { FileOut, QuestionOutput, ReviewerAssignmentOut } from "@jps/api-client";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  Progress,
  Radio,
  Select,
  Spoiler,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { type GetInputPropsReturnType, useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconDownload,
  IconFileUpload,
  IconSend,
  IconTrash,
} from "@tabler/icons-react";
import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, errorMessage, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate, formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { FILE_STATUS, formatSize } from "../submissions/labels";
import { sendToStorage } from "../submissions/upload";
import {
  ASSIGNMENT_STATUS,
  DECLINE_REASONS,
  METHOD_HELP,
  METHOD_LABELS,
  RECOMMENDATION_LABELS,
  RECOMMENDATIONS,
} from "../workflow/labels";
import { reviewsKey } from "./MyReviewsPage";

export const reviewKey = (id: number) => ["review", id] as const;

const BUSY = new Set(["pending_upload", "processing"]);

type Answer = string | string[];

function useReview(id: number) {
  return useQuery({
    queryKey: reviewKey(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/reviews/{assignment_id}", { params: { path: { assignment_id: id } } })),
    // Attachments are checked by the worker (and names removed from them): look again until they are ready.
    refetchInterval: (query) =>
      query.state.data?.attachments.some((file) => BUSY.has(file.status)) ? 1500 : false,
  });
}

function storeReview(queryClient: QueryClient, review: ReviewerAssignmentOut): void {
  queryClient.setQueryData(reviewKey(review.id), review);
  queryClient.invalidateQueries({ queryKey: reviewsKey });
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      {children}
    </Stack>
  );
}

function answerText(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  return value === null || value === undefined ? "" : String(value);
}

// ---------------------------------------------------------------------- the manuscript

function FileList({ files }: { files: FileOut[] }) {
  return (
    <Stack gap={6}>
      {files.map((file) => (
        <Group key={file.id} gap="xs" wrap="nowrap">
          {file.download_url ? (
            <Anchor href={file.download_url} size="sm">
              <Group gap={6} wrap="nowrap">
                <IconDownload size={16} />
                {file.name}
              </Group>
            </Anchor>
          ) : (
            <Text size="sm">{file.name}</Text>
          )}
          <Text size="xs" c="dimmed">
            {formatSize(file.size_bytes)}
          </Text>
          {file.metadata_removed === false ? (
            <Badge size="xs" color="orange" variant="light">
              Check this file for the authors' names
            </Badge>
          ) : null}
        </Group>
      ))}
    </Stack>
  );
}

function ManuscriptCard({ review }: { review: ReviewerAssignmentOut }) {
  const manuscript = review.manuscript;
  const accepted = review.status === "accepted" || review.status === "completed";
  return (
    <Card withBorder padding="lg">
      <Stack gap="md">
        <Stack gap={2}>
          <Title order={3}>{manuscript.title || "Untitled manuscript"}</Title>
          {manuscript.subtitle ? <Text c="dimmed">{manuscript.subtitle}</Text> : null}
          <Text size="sm" c="dimmed">
            {manuscript.section.title}
          </Text>
        </Stack>
        {manuscript.authors ? (
          <Field label="Authors">
            <Text size="sm">{manuscript.authors.join(", ")}</Text>
          </Field>
        ) : review.method === "double_blind" ? (
          <Text size="sm" c="dimmed">
            The authors' names are hidden: this is a double-blind review.
          </Text>
        ) : null}
        <Field label="Abstract">
          <Text size="sm" className="pre-wrap">
            {manuscript.abstract || "—"}
          </Text>
        </Field>
        {manuscript.keywords.length ? (
          <Field label="Keywords">
            <Group gap={6}>
              {manuscript.keywords.map((keyword) => (
                <Badge key={keyword} variant="light" color="gray">
                  {keyword}
                </Badge>
              ))}
            </Group>
          </Field>
        ) : null}
        {manuscript.comments_for_editor ? (
          <Field label="Cover letter">
            <Text size="sm" className="pre-wrap">
              {manuscript.comments_for_editor}
            </Text>
          </Field>
        ) : null}
        {manuscript.references ? (
          <Field label="References">
            <Spoiler maxHeight={90} showLabel="Show all" hideLabel="Show less">
              <Text size="sm" className="pre-wrap">
                {manuscript.references}
              </Text>
            </Spoiler>
          </Field>
        ) : null}
        <Field label="Files">
          {!accepted ? (
            <Text size="sm" c="dimmed">
              You will get the manuscript files once you accept the request.
            </Text>
          ) : review.files.length ? (
            <FileList files={review.files} />
          ) : (
            <Text size="sm" c="dimmed">
              The files are being prepared. Look again in a minute.
            </Text>
          )}
        </Field>
      </Stack>
    </Card>
  );
}

// ---------------------------------------------------------------------- answering the request

function RespondCard({ review }: { review: ReviewerAssignmentOut }) {
  const queryClient = useQueryClient();
  const [accepting, setAccepting] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [competing, setCompeting] = useState("");
  const [reason, setReason] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const path = { params: { path: { assignment_id: review.id } } };

  const accept = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/reviews/{assignment_id}/accept", {
          ...path,
          body: { competing_interests: competing },
        }),
      ),
    onSuccess: (updated) => {
      setAccepting(false);
      storeReview(queryClient, updated);
      notifySaved("Thank you for accepting. The manuscript files are below.");
    },
    onError: (error) => showRequestError(error),
  });

  const decline = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/reviews/{assignment_id}/decline", {
          ...path,
          body: {
            reason: (reason ?? "other") as "conflict_of_interest" | "no_time" | "outside_expertise" | "other",
            comment,
          },
        }),
      ),
    onSuccess: (updated) => {
      setDeclining(false);
      storeReview(queryClient, updated);
      notifySaved("Thank you for letting us know.");
    },
    onError: (error) => showRequestError(error),
  });

  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={4}>Can you review this manuscript?</Title>
        <Text size="sm">
          Please answer by <b>{formatDate(review.response_due)}</b>. If you accept, the review is due on{" "}
          <b>{formatDate(review.review_due)}</b>.
        </Text>
        <Group>
          <Button onClick={() => setAccepting(true)}>Accept</Button>
          <Button variant="default" onClick={() => setDeclining(true)}>
            Decline
          </Button>
        </Group>
      </Stack>

      <Modal opened={accepting} onClose={() => setAccepting(false)} title="Accept the review request">
        <Stack>
          <Textarea
            label="Competing interests"
            description="Anything that could be seen as influencing your review, such as a recent collaboration with the authors. Leave empty if there is none."
            autosize
            minRows={3}
            value={competing}
            onChange={(event) => setCompeting(event.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setAccepting(false)}>
              Cancel
            </Button>
            <Button loading={accept.isPending} onClick={() => accept.mutate()}>
              Accept and start reviewing
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={declining} onClose={() => setDeclining(false)} title="Decline the review request">
        <Stack>
          <Radio.Group label="Why?" value={reason} onChange={setReason} withAsterisk>
            <Stack gap="xs" mt="xs">
              {DECLINE_REASONS.map((option) => (
                <Radio key={option.value} value={option.value} label={option.label} />
              ))}
            </Stack>
          </Radio.Group>
          <Textarea
            label="Comment for the editor"
            description="Optional. You could suggest another reviewer."
            autosize
            minRows={2}
            value={comment}
            onChange={(event) => setComment(event.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeclining(false)}>
              Cancel
            </Button>
            <Button
              color="red"
              disabled={!reason}
              loading={decline.isPending}
              onClick={() => decline.mutate()}
            >
              Decline
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

// ---------------------------------------------------------------------- the review form

interface FormValues {
  answers: Record<string, Answer>;
  recommendation: string | null;
  comments_for_author: string;
  comments_for_editor: string;
}

function initialValues(review: ReviewerAssignmentOut): FormValues {
  const answers: Record<string, Answer> = {};
  for (const question of review.questions) {
    const value = review.answers[question.id];
    if (question.type === "checkboxes") {
      answers[question.id] = Array.isArray(value) ? value.map(String) : [];
    } else {
      answers[question.id] = typeof value === "string" ? value : "";
    }
  }
  return {
    answers,
    recommendation: review.recommendation,
    comments_for_author: review.comments_for_author,
    comments_for_editor: review.comments_for_editor,
  };
}

function requestBody(values: FormValues) {
  const answers = Object.fromEntries(
    Object.entries(values.answers).filter(([, value]) =>
      Array.isArray(value) ? value.length > 0 : value.trim() !== "",
    ),
  );
  return {
    answers,
    recommendation: (values.recommendation || null) as
      | "accept"
      | "minor_revisions"
      | "major_revisions"
      | "resubmit_elsewhere"
      | "decline"
      | "see_comments"
      | null,
    comments_for_author: values.comments_for_author,
    comments_for_editor: values.comments_for_editor,
  };
}

function QuestionInput({
  question,
  inputProps,
}: {
  question: QuestionOutput;
  inputProps: GetInputPropsReturnType;
}) {
  const description =
    [question.help, question.visible_to_author ? "" : "Only the editors see this answer."]
      .filter(Boolean)
      .join(" ") || undefined;
  const common = { label: question.label, description, withAsterisk: question.required };
  if (question.type === "text") return <TextInput {...common} {...inputProps} />;
  if (question.type === "textarea")
    return <Textarea {...common} autosize minRows={3} maxRows={20} {...inputProps} />;
  if (question.type === "choice") {
    return (
      <Radio.Group {...common} {...inputProps}>
        <Stack gap="xs" mt="xs">
          {question.options.map((option) => (
            <Radio key={option} value={option} label={option} />
          ))}
        </Stack>
      </Radio.Group>
    );
  }
  return (
    <Checkbox.Group {...common} {...inputProps}>
      <Stack gap="xs" mt="xs">
        {question.options.map((option) => (
          <Checkbox key={option} value={option} label={option} />
        ))}
      </Stack>
    </Checkbox.Group>
  );
}

interface Upload {
  id: string;
  name: string;
  progress: number;
  error?: string;
}

function Attachments({ review }: { review: ReviewerAssignmentOut }) {
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState<Upload[]>([]);
  const refresh = () => queryClient.invalidateQueries({ queryKey: reviewKey(review.id) });
  const patch = (id: string, change: Partial<Upload>) =>
    setUploads((current) => current.map((u) => (u.id === id ? { ...u, ...change } : u)));

  async function uploadOne(file: File) {
    const id = `${file.name}-${Date.now()}-${Math.random()}`;
    setUploads((current) => [...current, { id, name: file.name, progress: 0 }]);
    try {
      const ticket = await unwrap(
        api.POST("/api/v1/reviews/{assignment_id}/files/uploads", {
          params: { path: { assignment_id: review.id } },
          body: { file_name: file.name, size: file.size, genre: "supplementary" },
        }),
      );
      await sendToStorage(ticket.upload, file, (fraction) => patch(id, { progress: fraction }));
      await unwrap(
        api.POST("/api/v1/reviews/{assignment_id}/files/{file_id}/complete", {
          params: { path: { assignment_id: review.id, file_id: ticket.file.id } },
        }),
      );
      setUploads((current) => current.filter((u) => u.id !== id));
    } catch (error) {
      patch(id, { error: errorMessage(error) });
    } finally {
      await refresh();
    }
  }

  const remove = useMutation({
    mutationFn: (file: FileOut) =>
      unwrap(
        api.DELETE("/api/v1/reviews/{assignment_id}/files/{file_id}", {
          params: { path: { assignment_id: review.id, file_id: file.id } },
        }),
      ),
    onSettled: refresh,
    onError: (error) => showRequestError(error),
  });

  return (
    <Stack gap="sm">
      <Stack gap={2}>
        <Text fw={500} size="sm">
          Files for the authors and editors
        </Text>
        <Text size="xs" c="dimmed">
          For example, the manuscript with your comments. Your name is removed from the files' metadata before
          the authors see them; please also keep it out of the text.
        </Text>
      </Stack>
      {review.attachments.map((file) => {
        const look = FILE_STATUS[file.status] ?? { label: file.status, color: "gray" };
        return (
          <Group key={file.id} justify="space-between" wrap="nowrap">
            <Stack gap={0} style={{ minWidth: 0 }}>
              {file.download_url ? (
                <Anchor href={file.download_url} size="sm">
                  {file.name}
                </Anchor>
              ) : (
                <Text size="sm">{file.name}</Text>
              )}
              <Text size="xs" c={file.rejection_reason ? "red" : "dimmed"}>
                {file.rejection_reason ?? formatSize(file.size_bytes)}
              </Text>
            </Stack>
            <Group gap="xs" wrap="nowrap">
              {file.status !== "ready" ? (
                <Badge size="sm" variant="light" color={look.color}>
                  {look.label}
                </Badge>
              ) : null}
              <Tooltip label="Remove">
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label={`Remove ${file.name}`}
                  loading={remove.isPending && remove.variables?.id === file.id}
                  onClick={() => remove.mutate(file)}
                >
                  <IconTrash size={18} />
                </ActionIcon>
              </Tooltip>
            </Group>
          </Group>
        );
      })}
      {uploads.map((upload) => (
        <Stack key={upload.id} gap={4}>
          <Group justify="space-between">
            <Text size="sm">{upload.name}</Text>
            {upload.error ? (
              <Button
                size="compact-xs"
                variant="subtle"
                color="gray"
                onClick={() => setUploads((current) => current.filter((u) => u.id !== upload.id))}
              >
                Dismiss
              </Button>
            ) : null}
          </Group>
          {upload.error ? (
            <Text size="xs" c="red">
              {upload.error}
            </Text>
          ) : (
            <Progress value={upload.progress * 100} size="sm" animated />
          )}
        </Stack>
      ))}
      <Dropzone
        onDrop={(files) => {
          for (const file of files) void uploadOne(file);
        }}
        multiple
      >
        <Group justify="center" gap="md" mih={70} style={{ pointerEvents: "none" }}>
          <IconFileUpload size={28} stroke={1.4} color="var(--mantine-color-indigo-6)" />
          <Text size="sm">Drop files here or click to choose</Text>
        </Group>
      </Dropzone>
    </Stack>
  );
}

function ReviewForm({ review }: { review: ReviewerAssignmentOut }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const form = useForm<FormValues>({ initialValues: initialValues(review) });
  const path = { params: { path: { assignment_id: review.id } } };

  const onError = (error: unknown) => {
    if (error instanceof ApiError && Object.keys(error.fieldErrors).length > 0) {
      form.setErrors(
        Object.fromEntries(
          Object.entries(error.fieldErrors).map(([field, message]) => [
            field,
            message.replace(/^Value error, /, ""),
          ]),
        ),
      );
      notifications.show({ color: "red", title: "Please check the review", message: error.detail });
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      queryClient.invalidateQueries({ queryKey: reviewKey(review.id) });
    }
    showRequestError(error);
  };

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      unwrap(api.PUT("/api/v1/reviews/{assignment_id}/draft", { ...path, body: requestBody(values) })),
    onSuccess: (updated, values) => {
      form.resetDirty(values);
      storeReview(queryClient, updated);
      notifySaved("Draft saved");
    },
    onError,
  });

  const submit = useMutation({
    mutationFn: (values: FormValues) =>
      unwrap(api.POST("/api/v1/reviews/{assignment_id}/submit", { ...path, body: requestBody(values) })),
    onSuccess: (updated) => {
      storeReview(queryClient, updated);
      window.scrollTo({ top: 0 });
    },
    onError,
  });

  const busy = review.attachments.some((file) => BUSY.has(file.status));

  return (
    <form onSubmit={form.onSubmit(() => setConfirming(true))} noValidate>
      <Stack gap="lg">
        <Card withBorder padding="lg">
          <Stack gap="lg">
            <Stack gap={2}>
              <Title order={4}>Your review</Title>
              <Text size="sm" c="dimmed">
                Due {formatDate(review.review_due)}. You can save a draft and come back; once sent, the review
                cannot be changed.
              </Text>
            </Stack>
            {review.questions.map((question) => (
              <QuestionInput
                key={question.id}
                question={question}
                inputProps={form.getInputProps(`answers.${question.id}`)}
              />
            ))}
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack gap="lg">
            <Select
              label="Your recommendation"
              data={RECOMMENDATIONS}
              withAsterisk
              clearable
              maw={320}
              {...form.getInputProps("recommendation")}
            />
            <Textarea
              label="Comments for the authors"
              description="Sent to the authors with the editor's decision, without your name."
              autosize
              minRows={6}
              maxRows={30}
              {...form.getInputProps("comments_for_author")}
            />
            <Textarea
              label="Confidential comments for the editor"
              description="Only the editors see these."
              autosize
              minRows={3}
              maxRows={20}
              {...form.getInputProps("comments_for_editor")}
            />
            <Attachments review={review} />
          </Stack>
        </Card>

        <Group justify="flex-end">
          <Button
            variant="default"
            loading={save.isPending}
            disabled={!form.isDirty()}
            onClick={() => save.mutate(form.values)}
          >
            Save draft
          </Button>
          <Button type="submit" leftSection={<IconSend size={16} />} disabled={busy}>
            Send review
          </Button>
        </Group>
      </Stack>

      <Modal opened={confirming} onClose={() => setConfirming(false)} title="Send the review?">
        <Stack>
          <Text size="sm">The editors will receive it now. After that the review cannot be changed.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(false)}>
              Not yet
            </Button>
            <Button
              loading={submit.isPending}
              onClick={() => {
                setConfirming(false);
                submit.mutate(form.values);
              }}
            >
              Send
            </Button>
          </Group>
        </Stack>
      </Modal>
    </form>
  );
}

// ---------------------------------------------------------------------- after the review

function SentReview({ review }: { review: ReviewerAssignmentOut }) {
  return (
    <Card withBorder padding="lg">
      <Stack gap="md">
        <Title order={4}>The review you sent</Title>
        {review.questions
          .filter((question) => answerText(review.answers[question.id]))
          .map((question) => (
            <Field key={question.id} label={question.label}>
              <Text size="sm" className="pre-wrap">
                {answerText(review.answers[question.id])}
              </Text>
            </Field>
          ))}
        <Field label="Recommendation">
          <Text size="sm">
            {review.recommendation
              ? (RECOMMENDATION_LABELS[review.recommendation] ?? review.recommendation)
              : "—"}
          </Text>
        </Field>
        {review.comments_for_author ? (
          <Field label="Comments for the authors">
            <Text size="sm" className="pre-wrap">
              {review.comments_for_author}
            </Text>
          </Field>
        ) : null}
        {review.comments_for_editor ? (
          <Field label="Confidential comments for the editor">
            <Text size="sm" className="pre-wrap">
              {review.comments_for_editor}
            </Text>
          </Field>
        ) : null}
        {review.attachments.length ? (
          <Field label="Files">
            <FileList files={review.attachments} />
          </Field>
        ) : null}
      </Stack>
    </Card>
  );
}

// ---------------------------------------------------------------------- the page

export function ReviewPage() {
  const id = Number(useParams().id);
  const review = useReview(id);

  if (!review.data) {
    return <QueryState isPending={review.isPending} error={review.error} onRetry={() => review.refetch()} />;
  }
  const data = review.data;
  const look = ASSIGNMENT_STATUS[data.status] ?? { label: data.status, color: "gray" };

  return (
    <Stack gap="lg">
      <PageHeader
        title="Review request"
        description={
          <Stack gap={4}>
            <Group gap="xs">
              <Badge color={look.color} variant="light">
                {look.label}
              </Badge>
              {data.overdue ? (
                <Badge color="red" variant="filled">
                  Overdue
                </Badge>
              ) : null}
              <Text size="sm" c="dimmed">
                Round {data.round_number} · {METHOD_LABELS[data.method] ?? data.method} review · Invited{" "}
                {formatDate(data.invited_at)}
              </Text>
            </Group>
            <Text size="sm" c="dimmed">
              {METHOD_HELP[data.method]}
            </Text>
          </Stack>
        }
        actions={
          <Button component={Link} to="/reviews" variant="subtle">
            My reviews
          </Button>
        }
      />

      {data.status === "invited" ? <RespondCard review={data} /> : null}
      {data.status === "declined" ? (
        <Alert color="gray" title="You declined this request">
          Thank you for letting us know{data.responded_at ? ` (${formatDateTime(data.responded_at)})` : ""}.
        </Alert>
      ) : null}
      {data.status === "completed" ? (
        <Alert color="teal" icon={<IconCircleCheck />} title="Thank you, your review has been sent">
          The editors received it on {formatDateTime(data.completed_at)}.
        </Alert>
      ) : null}
      {data.status === "accepted" && !data.can_edit ? (
        <Alert color="orange" icon={<IconAlertTriangle />} title="This review is no longer needed">
          The editors have closed this round of review. Thank you for your time.
        </Alert>
      ) : null}

      <ManuscriptCard review={data} />

      {data.guidelines ? (
        <Card withBorder padding="lg">
          <Title order={4} mb="xs">
            Guidelines for reviewers
          </Title>
          <Spoiler maxHeight={120} showLabel="Show all" hideLabel="Show less">
            <Text size="sm" className="pre-wrap">
              {data.guidelines}
            </Text>
          </Spoiler>
        </Card>
      ) : null}

      {data.status === "accepted" && data.can_edit ? <ReviewForm key={data.id} review={data} /> : null}
      {data.status === "completed" ? <SentReview review={data} /> : null}
    </Stack>
  );
}
