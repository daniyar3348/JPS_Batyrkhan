import type { SubmissionOut, SubmissionSettingsOut } from "@jps/api-client";
import { Button, Card, Group, Stack, TagsInput, Text, Textarea, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../../api";
import { showRequestError } from "../../lib/forms";
import { wordCount } from "../labels";
import { storeSubmission, submissionKey } from "../queries";

export function DetailsStep({
  submission,
  settings,
  onDone,
  onBack,
  onDirtyChange,
}: {
  submission: SubmissionOut;
  settings: SubmissionSettingsOut;
  onDone: () => void;
  onBack: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const publication = submission.publication;
  const form = useForm({
    initialValues: {
      title: publication.title,
      subtitle: publication.subtitle,
      abstract: publication.abstract,
      keywords: publication.keywords,
      references: publication.references,
      funding_statement: publication.funding_statement,
      competing_interests: publication.competing_interests,
    },
    onValuesChange: () => onDirtyChange(true),
  });

  const save = useMutation({
    mutationFn: (body: typeof form.values) =>
      unwrap(
        api.PATCH("/api/v1/submissions/{submission_id}/publication", {
          params: {
            path: { submission_id: submission.id },
            header: { "if-match": `"${publication.row_version}"` },
          },
          body,
        }),
      ),
    onSuccess: (updated) => {
      storeSubmission(queryClient, updated);
      onDirtyChange(false);
      onDone();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "These details were changed in another window",
          message: "The latest version has been loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: submissionKey(submission.id) });
        return;
      }
      showRequestError(error, form);
    },
  });

  const words = wordCount(form.values.abstract);
  const overLimit = words > settings.abstract_max_words;
  const keywordRange =
    settings.keywords_min === settings.keywords_max
      ? `${settings.keywords_min}`
      : `${settings.keywords_min}–${settings.keywords_max}`;

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Title and abstract</Title>
            <TextInput label="Title" required {...form.getInputProps("title")} />
            <TextInput label="Subtitle" {...form.getInputProps("subtitle")} />
            <Textarea
              label="Abstract"
              required
              autosize
              minRows={6}
              maxRows={20}
              description={
                <Text span size="xs" c={overLimit ? "red" : "dimmed"}>
                  {words} of {settings.abstract_max_words} words
                </Text>
              }
              {...form.getInputProps("abstract")}
            />
            <TagsInput
              label="Keywords"
              description={`${keywordRange} keywords. Press Enter after each.`}
              maxTags={settings.keywords_max}
              {...form.getInputProps("keywords")}
            />
          </Stack>
        </Card>
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>References and statements</Title>
            <Textarea
              label="References"
              description="One reference per line. Include DOIs where they exist."
              autosize
              minRows={4}
              maxRows={20}
              {...form.getInputProps("references")}
            />
            <Textarea
              label="Funding"
              description="Grants and other support for this work, or “None”."
              autosize
              minRows={2}
              {...form.getInputProps("funding_statement")}
            />
            <Textarea
              label="Competing interests"
              description="Financial or personal interests that could be seen as influencing the work, or “None”."
              autosize
              minRows={2}
              {...form.getInputProps("competing_interests")}
            />
          </Stack>
        </Card>
        <Group justify="space-between">
          <Button variant="default" onClick={onBack}>
            Back
          </Button>
          <Button type="submit" loading={save.isPending}>
            Save and continue
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
