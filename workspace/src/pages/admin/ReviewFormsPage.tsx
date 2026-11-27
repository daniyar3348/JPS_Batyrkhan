import type { QuestionType, ReviewFormIn, ReviewFormOut } from "@jps/api-client";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { randomId, useDisclosure } from "@mantine/hooks";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconArrowDown, IconArrowUp, IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, unwrap } from "../../api";
import { PageHeader, QueryState } from "../../components/common";
import { notifySaved, showRequestError } from "../../lib/forms";
import { reviewFormsKey, useReviewForms } from "../../workflow/queries";

const QUESTION_TYPES: { value: QuestionType; label: string }[] = [
  { value: "textarea", label: "Paragraphs" },
  { value: "text", label: "One line" },
  { value: "choice", label: "One of several options" },
  { value: "checkboxes", label: "Any of several options" },
];

const hasOptions = (type: QuestionType) => type === "choice" || type === "checkboxes";

interface QuestionValues {
  /** For React only: stays with the question when it moves. */
  key: string;
  /** The server's id; empty for new questions (the server gives them one). */
  id: string;
  type: QuestionType;
  label: string;
  help: string;
  options: string[];
  required: boolean;
  visible_to_author: boolean;
}

interface FormValues {
  title: string;
  description: string;
  is_active: boolean;
  is_default: boolean;
  questions: QuestionValues[];
}

function newQuestion(): QuestionValues {
  return {
    key: randomId(),
    id: "",
    type: "textarea",
    label: "",
    help: "",
    options: [],
    required: false,
    visible_to_author: true,
  };
}

function toForm(form: ReviewFormOut | null): FormValues {
  if (!form) {
    return { title: "", description: "", is_active: true, is_default: false, questions: [newQuestion()] };
  }
  return {
    title: form.title,
    description: form.description,
    is_active: form.is_active,
    is_default: form.is_default,
    questions: form.questions.map((q) => ({ ...q, key: randomId() })),
  };
}

function toBody(values: FormValues): ReviewFormIn {
  return {
    title: values.title.trim(),
    description: values.description.trim(),
    is_active: values.is_active,
    is_default: values.is_default && values.is_active,
    questions: values.questions.map(({ key: _key, ...question }) => ({
      ...question,
      label: question.label.trim(),
      help: question.help.trim(),
      options: hasOptions(question.type) ? question.options.map((o) => o.trim()).filter(Boolean) : [],
    })),
  };
}

function useEditorForm(reviewForm: ReviewFormOut | null) {
  return useForm<FormValues>({
    initialValues: toForm(reviewForm),
    validate: {
      title: (value) => (value.trim() ? null : "Enter a title"),
      questions: {
        label: (value) => (value.trim() ? null : "Write the question"),
        options: (value, values, path) => {
          const index = Number(path.split(".")[1]);
          const type = values.questions[index]?.type;
          if (!type || !hasOptions(type)) return null;
          const options = value.map((o) => o.trim()).filter(Boolean);
          if (options.length < 2) return "Add at least two options";
          return new Set(options).size === options.length ? null : "Options must be different";
        },
      },
    },
  });
}

type EditorForm = ReturnType<typeof useEditorForm>;

function QuestionEditor({ form, index, count }: { form: EditorForm; index: number; count: number }) {
  const question = form.values.questions[index];
  if (!question) return null;
  const path = `questions.${index}`;
  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap">
          <Text fw={600} size="sm">
            Question {index + 1}
          </Text>
          <Group gap={4} wrap="nowrap">
            <Tooltip label="Move up">
              <ActionIcon
                variant="subtle"
                disabled={index === 0}
                onClick={() => form.reorderListItem("questions", { from: index, to: index - 1 })}
                aria-label={`Move question ${index + 1} up`}
              >
                <IconArrowUp size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Move down">
              <ActionIcon
                variant="subtle"
                disabled={index === count - 1}
                onClick={() => form.reorderListItem("questions", { from: index, to: index + 1 })}
                aria-label={`Move question ${index + 1} down`}
              >
                <IconArrowDown size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Remove">
              <ActionIcon
                variant="subtle"
                color="red"
                disabled={count === 1}
                onClick={() => form.removeListItem("questions", index)}
                aria-label={`Remove question ${index + 1}`}
              >
                <IconTrash size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
        <Textarea label="Question" required autosize minRows={1} {...form.getInputProps(`${path}.label`)} />
        <TextInput
          label="Help text"
          placeholder="Optional explanation shown under the question"
          {...form.getInputProps(`${path}.help`)}
        />
        <Select
          label="Answer"
          data={QUESTION_TYPES}
          allowDeselect={false}
          w={260}
          {...form.getInputProps(`${path}.type`)}
        />
        {hasOptions(question.type) ? (
          <TagsInput
            label="Options"
            description="At least two. Press Enter after each."
            placeholder="Add an option"
            {...form.getInputProps(`${path}.options`)}
          />
        ) : null}
        <Group gap="lg">
          <Checkbox label="Required" {...form.getInputProps(`${path}.required`, { type: "checkbox" })} />
          <Checkbox
            label="Authors see the answer"
            {...form.getInputProps(`${path}.visible_to_author`, { type: "checkbox" })}
          />
        </Group>
      </Stack>
    </Card>
  );
}

function FormEditor({ reviewForm, onDone }: { reviewForm: ReviewFormOut | null; onDone: () => void }) {
  const queryClient = useQueryClient();
  const form = useEditorForm(reviewForm);

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const body = toBody(values);
      return reviewForm
        ? unwrap(
            api.PUT("/api/v1/journal/review-forms/{form_id}", {
              params: { path: { form_id: reviewForm.id }, header: { "if-match": `"${reviewForm.version}"` } },
              body,
            }),
          )
        : unwrap(api.POST("/api/v1/journal/review-forms", { body }));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: reviewFormsKey });
      notifySaved(reviewForm ? "Review form saved" : "Review form created");
      onDone();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed this form",
          message: "Close it and open it again to see the latest version.",
        });
        queryClient.invalidateQueries({ queryKey: reviewFormsKey });
        return;
      }
      showRequestError(error, form);
    },
  });

  const questions = form.values.questions;

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack>
        {reviewForm ? (
          <Alert color="blue" variant="light">
            Changes apply to new invitations. Reviewers already invited keep the questions they were sent.
          </Alert>
        ) : null}
        <TextInput label="Title" required {...form.getInputProps("title")} />
        <Textarea
          label="Introduction"
          description="Shown to reviewers above the questions."
          autosize
          minRows={2}
          {...form.getInputProps("description")}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Switch label="In use" {...form.getInputProps("is_active", { type: "checkbox" })} />
          <Switch
            label="Default form for new invitations"
            disabled={!form.values.is_active}
            {...form.getInputProps("is_default", { type: "checkbox" })}
          />
        </SimpleGrid>
        <Title order={5} mt="xs">
          Questions
        </Title>
        <Text size="sm" c="dimmed">
          Every review also has comments for the authors, confidential comments for the editor and a
          recommendation; you do not need questions for those.
        </Text>
        {questions.map((question, index) => (
          <QuestionEditor key={question.key} form={form} index={index} count={questions.length} />
        ))}
        <Group>
          <Button
            variant="light"
            size="xs"
            leftSection={<IconPlus size={14} />}
            disabled={questions.length >= 40}
            onClick={() => form.insertListItem("questions", newQuestion())}
          >
            Add question
          </Button>
        </Group>
        <Group justify="flex-end">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            {reviewForm ? "Save form" : "Create form"}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function ReviewFormsPage() {
  const queryClient = useQueryClient();
  const forms = useReviewForms();
  const [opened, { open, close }] = useDisclosure(false);
  const [editing, setEditing] = useState<ReviewFormOut | null>(null);

  const remove = useMutation({
    mutationFn: (form: ReviewFormOut) =>
      unwrap(
        api.DELETE("/api/v1/journal/review-forms/{form_id}", { params: { path: { form_id: form.id } } }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: reviewFormsKey });
      notifySaved("Review form deleted");
    },
    onError: (error) => showRequestError(error),
  });

  const edit = (form: ReviewFormOut | null) => {
    setEditing(form);
    open();
  };

  const confirmDelete = (form: ReviewFormOut) =>
    modals.openConfirmModal({
      title: `Delete “${form.title}”?`,
      children: (
        <Text size="sm">
          Reviewers already invited with this form keep their questions and answers. New invitations will use
          another form.
        </Text>
      ),
      labels: { confirm: "Delete", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(form),
    });

  return (
    <Stack>
      <PageHeader
        title="Review forms"
        description="The questions reviewers answer. Editors choose a form when they invite a reviewer."
        actions={
          <Button leftSection={<IconPlus size={16} />} onClick={() => edit(null)}>
            New form
          </Button>
        }
      />
      {forms.data ? (
        <Stack gap="sm">
          {forms.data.map((form) => (
            <Card key={form.id} withBorder padding="lg">
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Stack gap={4}>
                  <Group gap="xs">
                    <Text fw={600}>{form.title}</Text>
                    {form.is_default ? (
                      <Badge variant="light" size="sm">
                        Default
                      </Badge>
                    ) : null}
                    {!form.is_active ? (
                      <Badge variant="light" color="gray" size="sm">
                        Not in use
                      </Badge>
                    ) : null}
                  </Group>
                  <Text size="sm" c="dimmed">
                    {form.questions.length === 1 ? "1 question" : `${form.questions.length} questions`}
                    {form.description ? ` · ${form.description}` : ""}
                  </Text>
                </Stack>
                <Group gap={4} wrap="nowrap">
                  <Tooltip label="Edit">
                    <ActionIcon variant="subtle" onClick={() => edit(form)} aria-label={`Edit ${form.title}`}>
                      <IconPencil size={18} />
                    </ActionIcon>
                  </Tooltip>
                  <Tooltip label="Delete">
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      onClick={() => confirmDelete(form)}
                      aria-label={`Delete ${form.title}`}
                    >
                      <IconTrash size={18} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
              </Group>
            </Card>
          ))}
        </Stack>
      ) : (
        <QueryState isPending={forms.isPending} error={forms.error} onRetry={() => forms.refetch()} />
      )}
      <Modal
        opened={opened}
        onClose={close}
        title={editing ? `Edit “${editing.title}”` : "New review form"}
        size="xl"
      >
        {opened ? <FormEditor key={editing?.id ?? "new"} reviewForm={editing} onDone={close} /> : null}
      </Modal>
    </Stack>
  );
}
