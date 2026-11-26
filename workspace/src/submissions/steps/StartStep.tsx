import type { SubmissionOut, SubmissionSettingsOut } from "@jps/api-client";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Group,
  Select,
  Spoiler,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "../../api";
import { showRequestError } from "../../lib/forms";
import { storeSubmission, useActiveSections } from "../queries";

export function StartStep({
  submission,
  settings,
  onDone,
  onDirtyChange,
}: {
  submission: SubmissionOut;
  settings: SubmissionSettingsOut;
  onDone: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const sections = useActiveSections();
  const form = useForm({
    initialValues: {
      section_id: String(submission.section.id),
      checklist_confirmed: submission.checklist_confirmed.filter((item) => settings.checklist.includes(item)),
      comments_for_editor: submission.comments_for_editor,
    },
    onValuesChange: () => onDirtyChange(true),
  });

  const save = useMutation({
    mutationFn: (values: typeof form.values) =>
      unwrap(
        api.PATCH("/api/v1/submissions/{submission_id}", {
          params: {
            path: { submission_id: submission.id },
            header: { "if-match": `"${submission.row_version}"` },
          },
          body: { ...values, section_id: Number(values.section_id) },
        }),
      ),
    onSuccess: (updated) => {
      storeSubmission(queryClient, updated);
      onDirtyChange(false);
      onDone();
    },
    onError: (error) => showRequestError(error, form),
  });

  const allConfirmed = settings.checklist.every((item) => form.values.checklist_confirmed.includes(item));
  const sectionPolicy = sections.data?.find((s) => String(s.id) === form.values.section_id)?.policy;

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        {settings.author_guidelines ? (
          <Card withBorder padding="lg">
            <Title order={4} mb="xs">
              Author guidelines
            </Title>
            <Spoiler maxHeight={120} showLabel="Show all" hideLabel="Show less">
              <Text size="sm" className="pre-wrap">
                {settings.author_guidelines}
              </Text>
            </Spoiler>
          </Card>
        ) : null}

        <Card withBorder padding="lg">
          <Stack>
            <Select
              label="Section"
              description="The kind of article you are submitting."
              data={(sections.data ?? []).map((s) => ({ value: String(s.id), label: s.title }))}
              allowDeselect={false}
              {...form.getInputProps("section_id")}
            />
            {sectionPolicy ? (
              <Text size="sm" c="dimmed" className="pre-wrap">
                {sectionPolicy}
              </Text>
            ) : null}
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack gap="sm">
            <Title order={4}>Submission checklist</Title>
            <Text size="sm" c="dimmed">
              Confirm that your submission meets every requirement.
            </Text>
            <Checkbox.Group {...form.getInputProps("checklist_confirmed")}>
              <Stack gap="sm" mt={4}>
                {settings.checklist.map((item) => (
                  <Checkbox key={item} value={item} label={item} />
                ))}
              </Stack>
            </Checkbox.Group>
            {!allConfirmed ? (
              <Alert color="gray" variant="light">
                You can save now and come back, but every item must be confirmed before you submit.
              </Alert>
            ) : null}
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Textarea
            label="Comments for the editor"
            description="Anything the editor should know: suggested or excluded reviewers, related manuscripts."
            autosize
            minRows={3}
            maxRows={12}
            {...form.getInputProps("comments_for_editor")}
          />
        </Card>

        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending}>
            Save and continue
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
