import type { JournalOut, JournalUpdate } from "@jps/api-client";
import { Button, Card, Group, SimpleGrid, Stack, Text, Textarea, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../../api";
import { PageHeader, QueryState } from "../../components/common";
import { formatDateTime } from "../../lib/format";
import { notifySaved, showRequestError } from "../../lib/forms";

const journalKey = ["journal"] as const;

function toForm(journal: JournalOut) {
  return {
    name: journal.name,
    abbreviation: journal.abbreviation,
    publisher: journal.publisher,
    issn_print: journal.issn_print ?? "",
    issn_online: journal.issn_online ?? "",
    contact_name: journal.contact_name,
    contact_email: journal.contact_email,
    description: journal.description,
    privacy_policy_version: journal.privacy_policy_version,
  };
}

function SettingsForm({ journal }: { journal: JournalOut }) {
  const queryClient = useQueryClient();
  // The parent remounts this form whenever a new version of the settings arrives.
  const form = useForm({
    initialValues: toForm(journal),
    validate: { name: (value) => (value.trim() ? null : "The journal needs a name") },
  });

  const save = useMutation({
    mutationFn: (values: ReturnType<typeof toForm>) => {
      // Send only what changed; empty e-mail is sent as-is so it can be cleared.
      const changed = Object.fromEntries(
        Object.entries(values).filter(([key]) => form.isDirty(key)),
      ) as JournalUpdate;
      return unwrap(
        api.PATCH("/api/v1/journal", {
          body: changed,
          params: { header: { "if-match": `"${journal.version}"` } },
        }),
      );
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(journalKey, updated);
      queryClient.invalidateQueries({ queryKey: ["public-journal"] });
      // Show what the server stored (e.g. a normalised ISSN), even when nothing actually changed.
      form.setValues(toForm(updated));
      form.resetDirty(toForm(updated));
      notifySaved("Journal settings saved");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed these settings",
          message: "The latest version is loaded. Review it and make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: journalKey });
        return;
      }
      showRequestError(error, form);
    },
  });

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack>
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Identity</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput label="Journal name" required {...form.getInputProps("name")} />
              <TextInput
                label="Abbreviation"
                placeholder="J. Appl. Sci."
                {...form.getInputProps("abbreviation")}
              />
            </SimpleGrid>
            <TextInput label="Publisher" {...form.getInputProps("publisher")} />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput label="Print ISSN" placeholder="0000-0000" {...form.getInputProps("issn_print")} />
              <TextInput
                label="Online ISSN (e-ISSN)"
                placeholder="0000-0000"
                {...form.getInputProps("issn_online")}
              />
            </SimpleGrid>
            <Textarea
              label="About the journal"
              description="Shown on the journal website."
              autosize
              minRows={4}
              maxRows={16}
              {...form.getInputProps("description")}
            />
          </Stack>
        </Card>
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Contact and policies</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput label="Contact person" {...form.getInputProps("contact_name")} />
              <TextInput label="Contact e-mail" type="email" {...form.getInputProps("contact_email")} />
            </SimpleGrid>
            <TextInput
              label="Privacy policy version"
              description="Increase it when the privacy policy changes. New consents record this version."
              maw={320}
              {...form.getInputProps("privacy_policy_version")}
            />
          </Stack>
        </Card>
        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            Last changed {formatDateTime(journal.updated_at)}
          </Text>
          <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
            Save settings
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function JournalSettingsPage() {
  const journal = useQuery({ queryKey: journalKey, queryFn: () => unwrap(api.GET("/api/v1/journal")) });
  return (
    <Stack>
      <PageHeader title="Journal settings" description="Basic information about the journal." />
      {journal.data ? (
        <SettingsForm key={journal.data.version} journal={journal.data} />
      ) : (
        <QueryState isPending={journal.isPending} error={journal.error} onRetry={() => journal.refetch()} />
      )}
    </Stack>
  );
}
