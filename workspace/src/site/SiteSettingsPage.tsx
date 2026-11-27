import type { BoardMember, SiteSettings } from "@jps/api-client";
import {
  ActionIcon,
  Autocomplete,
  Button,
  Card,
  Group,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { randomId } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { notifySaved, showRequestError } from "../lib/forms";
import { type SiteSettingsState, siteSettingsKey, useSiteSettings, withEtag } from "./queries";

export const BOARD_ROLES = [
  "Editor-in-Chief",
  "Deputy Editor-in-Chief",
  "Associate Editor",
  "Section Editor",
  "Managing Editor",
  "Editorial Board Member",
];

interface MemberValues {
  key: string; // keeps each row's inputs (and focus) in place while rows move
  name: string;
  role: string;
  affiliation: string;
  country: string;
  orcid: string;
}

interface FormValues {
  tagline: string;
  publication_frequency: string;
  editorial_board: MemberValues[];
}

function toForm(settings: SiteSettings): FormValues {
  return {
    tagline: settings.tagline,
    publication_frequency: settings.publication_frequency,
    editorial_board: (settings.editorial_board ?? []).map((member) => ({
      key: randomId(),
      name: member.name,
      role: member.role,
      affiliation: member.affiliation,
      country: member.country,
      orcid: member.orcid ?? "",
    })),
  };
}

function toSettings(values: FormValues): SiteSettings {
  return {
    tagline: values.tagline.trim(),
    publication_frequency: values.publication_frequency.trim(),
    editorial_board: values.editorial_board.map(
      (member): BoardMember => ({
        name: member.name.trim(),
        role: member.role.trim(),
        affiliation: member.affiliation.trim(),
        country: member.country.trim(),
        orcid: member.orcid.trim() || null,
      }),
    ),
  };
}

const EMPTY_MEMBER: Omit<MemberValues, "key"> = {
  name: "",
  role: "Editorial Board Member",
  affiliation: "",
  country: "",
  orcid: "",
};

function SettingsForm({ state }: { state: SiteSettingsState }) {
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    initialValues: toForm(state.data),
    validate: {
      editorial_board: {
        name: (value) => (value.trim() ? null : "Enter the name"),
        role: (value) => (value.trim() ? null : "Enter the role"),
      },
    },
  });
  const save = useMutation({
    mutationFn: (values: FormValues) =>
      withEtag(
        api.PUT("/api/v1/journal/site-settings", {
          params: { header: { "if-match": state.etag } },
          body: toSettings(values),
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(siteSettingsKey, saved);
      form.setValues(toForm(saved.data));
      form.resetDirty(toForm(saved.data));
      notifySaved("Site settings saved");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed the journal settings",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: siteSettingsKey });
        return;
      }
      showRequestError(error, form);
    },
  });
  const members = form.values.editorial_board;
  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>About the journal</Title>
            <TextInput
              label="Tagline"
              description="A line under the journal's name on every page."
              placeholder="Open-access research in applied science"
              {...form.getInputProps("tagline")}
            />
            <TextInput
              label="Publication frequency"
              description="Shown on the About page."
              placeholder="Two issues a year, with continuous publication"
              {...form.getInputProps("publication_frequency")}
            />
          </Stack>
        </Card>
        <Card withBorder padding="lg">
          <Stack>
            <div>
              <Title order={4}>Editorial board</Title>
              <Text size="sm" c="dimmed">
                In the order shown on the site; people with the same role are listed together.
              </Text>
            </div>
            {members.length === 0 ? (
              <Text size="sm" c="dimmed">
                Nobody yet.
              </Text>
            ) : null}
            {members.map((member, index) => (
              <Card
                key={member.key}
                withBorder
                padding="sm"
                radius="sm"
                aria-label={`Board member ${index + 1}`}
              >
                <Group align="flex-start" wrap="nowrap" gap="sm">
                  <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} style={{ flex: 1 }} spacing="sm">
                    <TextInput
                      label="Name"
                      required
                      {...form.getInputProps(`editorial_board.${index}.name`)}
                    />
                    <Autocomplete
                      label="Role"
                      required
                      data={BOARD_ROLES}
                      {...form.getInputProps(`editorial_board.${index}.role`)}
                    />
                    <TextInput
                      label="Affiliation"
                      {...form.getInputProps(`editorial_board.${index}.affiliation`)}
                    />
                    <TextInput label="Country" {...form.getInputProps(`editorial_board.${index}.country`)} />
                    <TextInput
                      label="ORCID"
                      placeholder="0000-0000-0000-0000"
                      {...form.getInputProps(`editorial_board.${index}.orcid`)}
                    />
                  </SimpleGrid>
                  <Stack gap={4} pt={24}>
                    <Tooltip label="Move up">
                      <ActionIcon
                        variant="subtle"
                        aria-label={`Move ${member.name || "member"} up`}
                        disabled={index === 0}
                        onClick={() =>
                          form.reorderListItem("editorial_board", { from: index, to: index - 1 })
                        }
                      >
                        <IconArrowUp size={16} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Move down">
                      <ActionIcon
                        variant="subtle"
                        aria-label={`Move ${member.name || "member"} down`}
                        disabled={index === members.length - 1}
                        onClick={() =>
                          form.reorderListItem("editorial_board", { from: index, to: index + 1 })
                        }
                      >
                        <IconArrowDown size={16} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Remove">
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={`Remove ${member.name || "member"}`}
                        onClick={() => form.removeListItem("editorial_board", index)}
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Tooltip>
                  </Stack>
                </Group>
              </Card>
            ))}
            <Group>
              <Button
                variant="light"
                leftSection={<IconPlus size={16} />}
                onClick={() => form.insertListItem("editorial_board", { ...EMPTY_MEMBER, key: randomId() })}
              >
                Add a member
              </Button>
            </Group>
          </Stack>
        </Card>
        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending}>
            Save
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

/** The site's tagline, publication frequency and editorial board. */
export function SiteSettingsPage() {
  const settings = useSiteSettings();
  return (
    <Stack>
      <PageHeader
        title="Site settings"
        description="What the journal's site shows about the journal and its editors."
      />
      {settings.data ? (
        <SettingsForm key={settings.data.etag} state={settings.data} />
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
