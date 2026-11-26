import type { SubmissionSettings, SubmissionSettingsOut } from "@jps/api-client";
import {
  ActionIcon,
  Alert,
  Button,
  Card,
  Group,
  NumberInput,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { randomId } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../../api";
import { PageHeader, QueryState } from "../../components/common";
import { notifySaved, showRequestError } from "../../lib/forms";
import { submissionSettingsKey, useSubmissionSettings } from "../../submissions/queries";

/** Every field is filled in; checklist items carry a stable key so reordering keeps their inputs. */
type FormValues = Omit<Required<SubmissionSettings>, "checklist"> & {
  checklist: { key: string; text: string }[];
};

function toForm(settings: SubmissionSettingsOut): FormValues {
  return {
    checklist: settings.checklist.map((text) => ({ key: randomId(), text })),
    author_guidelines: settings.author_guidelines,
    max_file_size_mb: settings.max_file_size_mb,
    abstract_max_words: settings.abstract_max_words,
    keywords_min: settings.keywords_min,
    keywords_max: settings.keywords_max,
    number_prefix: settings.number_prefix,
    similarity: settings.similarity,
  };
}

function SettingsForm({ settings }: { settings: SubmissionSettingsOut }) {
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    initialValues: toForm(settings),
    validate: {
      number_prefix: (value) => (/^[A-Z0-9]{2,10}$/.test(value) ? null : "2–10 capital letters or digits"),
      keywords_max: (value, values) =>
        value >= values.keywords_min ? null : "Must be at least the minimum number of keywords",
    },
  });

  const save = useMutation({
    mutationFn: (body: FormValues) =>
      unwrap(
        api.PUT("/api/v1/journal/submission-settings", {
          params: { header: { "if-match": `"${settings.version}"` } },
          body: { ...body, checklist: body.checklist.map((item) => item.text.trim()).filter(Boolean) },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(submissionSettingsKey, saved);
      notifySaved("Submission settings saved");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed the journal settings",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: submissionSettingsKey });
        return;
      }
      showRequestError(error, form);
    },
  });

  const checklist = form.values.checklist;
  const moveItem = (index: number, offset: number) =>
    form.reorderListItem("checklist", { from: index, to: index + offset });

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Submission checklist</Title>
            <Text size="sm" c="dimmed">
              Authors must confirm every item before they can submit. Changes apply to new submissions.
            </Text>
            {checklist.map((item, index) => (
              <Group key={item.key} align="flex-start" wrap="nowrap" gap="xs">
                <Textarea
                  autosize
                  minRows={1}
                  style={{ flex: 1 }}
                  aria-label={`Checklist item ${index + 1}`}
                  {...form.getInputProps(`checklist.${index}.text`)}
                />
                <Tooltip label="Move up">
                  <ActionIcon
                    variant="subtle"
                    mt={6}
                    disabled={index === 0}
                    onClick={() => moveItem(index, -1)}
                    aria-label="Move up"
                  >
                    <IconArrowUp size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Move down">
                  <ActionIcon
                    variant="subtle"
                    mt={6}
                    disabled={index === checklist.length - 1}
                    onClick={() => moveItem(index, 1)}
                    aria-label="Move down"
                  >
                    <IconArrowDown size={16} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Remove">
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    mt={6}
                    onClick={() => form.removeListItem("checklist", index)}
                    aria-label="Remove"
                  >
                    <IconTrash size={16} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            ))}
            <Group>
              <Button
                variant="light"
                size="xs"
                leftSection={<IconPlus size={14} />}
                disabled={checklist.length >= 20}
                onClick={() => form.insertListItem("checklist", { key: randomId(), text: "" })}
              >
                Add item
              </Button>
            </Group>
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Textarea
            label="Author guidelines"
            description="Shown at the start of every submission."
            autosize
            minRows={5}
            maxRows={20}
            {...form.getInputProps("author_guidelines")}
          />
        </Card>

        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Limits and numbering</Title>
            <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
              <NumberInput
                label="Largest file, MB"
                min={1}
                max={200}
                {...form.getInputProps("max_file_size_mb")}
              />
              <NumberInput
                label="Abstract, words"
                min={50}
                max={2000}
                {...form.getInputProps("abstract_max_words")}
              />
              <NumberInput
                label="Keywords, at least"
                min={0}
                max={20}
                {...form.getInputProps("keywords_min")}
              />
              <NumberInput
                label="Keywords, at most"
                min={1}
                max={30}
                {...form.getInputProps("keywords_max")}
              />
            </SimpleGrid>
            <TextInput
              label="Manuscript number prefix"
              description={`Numbers look like ${form.values.number_prefix || "JRN"}-${new Date().getFullYear()}-0001.`}
              maw={260}
              {...form.getInputProps("number_prefix")}
              onChange={(event) =>
                form.setFieldValue("number_prefix", event.currentTarget.value.toUpperCase())
              }
            />
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Similarity check</Title>
            {!settings.similarity_available ? (
              <Alert color="gray" variant="light">
                No similarity checking service is connected to the platform yet. It can be turned on once the
                journal has access (for example, Crossref Similarity Check).
              </Alert>
            ) : null}
            <Switch
              label="Check every new submission automatically"
              disabled={!settings.similarity_available}
              {...form.getInputProps("similarity.enabled", { type: "checkbox" })}
            />
            <NumberInput
              label="Flag manuscripts at or above, %"
              description="Editors see these marked for attention. Nothing is rejected automatically."
              min={1}
              max={100}
              maw={260}
              disabled={!settings.similarity_available}
              {...form.getInputProps("similarity.threshold_percent")}
            />
          </Stack>
        </Card>

        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
            Save settings
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function SubmissionSettingsPage() {
  const settings = useSubmissionSettings();
  return (
    <Stack>
      <PageHeader title="Submission settings" description="How authors submit manuscripts to the journal." />
      {settings.data ? (
        <SettingsForm key={settings.data.version} settings={settings.data} />
      ) : (
        <QueryState
          isPending={settings.isPending}
          error={settings.error}
          onRetry={() => settings.refetch()}
        />
      )}
    </Stack>
  );
}
