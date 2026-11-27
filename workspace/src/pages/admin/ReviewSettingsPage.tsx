import type { ReviewMethod, ReviewSettings, ReviewSettingsOut } from "@jps/api-client";
import {
  Button,
  Card,
  Group,
  NumberInput,
  Radio,
  SimpleGrid,
  Stack,
  Switch,
  TagsInput,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../../api";
import { PageHeader, QueryState } from "../../components/common";
import { notifySaved, showRequestError } from "../../lib/forms";
import { METHOD_HELP, METHOD_LABELS } from "../../workflow/labels";
import { reviewSettingsKey, useReviewSettings } from "../../workflow/queries";

const METHODS: ReviewMethod[] = ["double_blind", "single_blind", "open"];

/** Reminder days are edited as text tags ("-3", "0", "7") and sent as numbers. */
type FormValues = Omit<Required<ReviewSettings>, "response_reminder_days" | "review_reminder_days"> & {
  response_reminder_days: string[];
  review_reminder_days: string[];
};

function toForm(settings: ReviewSettingsOut): FormValues {
  return {
    method: settings.method,
    response_days: settings.response_days,
    review_days: settings.review_days,
    reminders_enabled: settings.reminders_enabled,
    response_reminder_days: settings.response_reminder_days.map(String),
    review_reminder_days: settings.review_reminder_days.map(String),
    reviewer_guidelines: settings.reviewer_guidelines,
  };
}

const INTEGER = /^-?\d+$/;

function validateDays(values: string[], min: number, max: number, most: number): string | null {
  if (values.length > most) return `At most ${most} reminders`;
  for (const value of values) {
    if (!INTEGER.test(value.trim())) return `“${value}” is not a whole number of days`;
    const days = Number(value);
    if (days < min || days > max) return `Use days from ${min} to ${max}`;
  }
  return null;
}

/** Unique, sorted numbers, as the server stores them. */
function toDays(values: string[]): number[] {
  return [...new Set(values.map((value) => Number(value.trim())))].sort((a, b) => a - b);
}

function SettingsForm({ settings }: { settings: ReviewSettingsOut }) {
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    initialValues: toForm(settings),
    validate: {
      response_reminder_days: (value) => validateDays(value, 0, 30, 5),
      review_reminder_days: (value) => validateDays(value, -30, 60, 8),
    },
  });

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      unwrap(
        api.PUT("/api/v1/journal/review-settings", {
          params: { header: { "if-match": `"${settings.version}"` } },
          body: {
            ...values,
            response_reminder_days: toDays(values.response_reminder_days),
            review_reminder_days: toDays(values.review_reminder_days),
          },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(reviewSettingsKey, saved);
      notifySaved("Review settings saved");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed the journal settings",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: reviewSettingsKey });
        return;
      }
      showRequestError(error, form);
    },
  });

  const reminders = form.values.reminders_enabled;

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Review method</Title>
            <Text size="sm" c="dimmed">
              The default for new invitations. Editors can choose another method for each reviewer.
            </Text>
            <Radio.Group {...form.getInputProps("method")}>
              <Stack gap="sm" mt={4}>
                {METHODS.map((method) => (
                  <Radio
                    key={method}
                    value={method}
                    label={METHOD_LABELS[method]}
                    description={METHOD_HELP[method]}
                  />
                ))}
              </Stack>
            </Radio.Group>
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Deadlines</Title>
            <Text size="sm" c="dimmed">
              Proposed when an editor invites a reviewer; the editor can change them.
            </Text>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <NumberInput
                label="Days to answer an invitation"
                min={1}
                max={60}
                {...form.getInputProps("response_days")}
              />
              <NumberInput
                label="Days to write the review"
                description="Counted from the answer deadline."
                min={1}
                max={180}
                {...form.getInputProps("review_days")}
              />
            </SimpleGrid>
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Reminders</Title>
            <Switch
              label="Send reminders to reviewers automatically"
              {...form.getInputProps("reminders_enabled", { type: "checkbox" })}
            />
            <Text size="sm" c="dimmed">
              Enter days relative to the deadline: a negative number means days before it, 0 the day itself, a
              positive number days after. Press Enter after each number.
            </Text>
            <TagsInput
              label="Unanswered invitation"
              description="Days after the answer deadline, for example 1."
              placeholder="Add a day"
              disabled={!reminders}
              {...form.getInputProps("response_reminder_days")}
            />
            <TagsInput
              label="Review due"
              description="Days relative to the review deadline, for example -3, 0, 3, 7."
              placeholder="Add a day"
              disabled={!reminders}
              {...form.getInputProps("review_reminder_days")}
            />
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Textarea
            label="Guidelines for reviewers"
            description="Shown to every reviewer on the review page."
            autosize
            minRows={5}
            maxRows={20}
            {...form.getInputProps("reviewer_guidelines")}
          />
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

export function ReviewSettingsPage() {
  const settings = useReviewSettings();
  return (
    <Stack>
      <PageHeader title="Review settings" description="How the journal runs peer review." />
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
