import type { PublishingSettings, PublishingSettingsOut } from "@jps/api-client";
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  List,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { notifySaved, showRequestError } from "../lib/forms";
import {
  type PublishingSettingsState,
  publishingSettingsKey,
  usePublishingSettings,
  withEtag,
} from "./queries";

const CUSTOM = "custom";
const LICENCES = [
  { value: "https://creativecommons.org/licenses/by/4.0/", label: "CC BY 4.0" },
  { value: "https://creativecommons.org/licenses/by-sa/4.0/", label: "CC BY-SA 4.0" },
  { value: "https://creativecommons.org/licenses/by-nc/4.0/", label: "CC BY-NC 4.0" },
  { value: "https://creativecommons.org/licenses/by-nc-sa/4.0/", label: "CC BY-NC-SA 4.0" },
  { value: "https://creativecommons.org/licenses/by-nd/4.0/", label: "CC BY-ND 4.0" },
  { value: "https://creativecommons.org/licenses/by-nc-nd/4.0/", label: "CC BY-NC-ND 4.0" },
  { value: "https://creativecommons.org/publicdomain/zero/1.0/", label: "CC0 1.0 (public domain)" },
];

const CROSSREF_MODES: Record<string, { label: string; color: string; text: string }> = {
  disabled: {
    label: "Off",
    color: "gray",
    text: "DOIs are not registered: the server has no Crossref account configured.",
  },
  fake: { label: "Fake", color: "orange", text: "Fake mode (development): nothing is sent to Crossref." },
  test: {
    label: "Test",
    color: "blue",
    text: "Crossref test system: deposits are checked but register nothing.",
  },
  production: { label: "Production", color: "green", text: "Registering with Crossref." },
};

interface FormValues {
  site_url: string;
  licence: string;
  custom_licence: string;
  copyright_holder: "authors" | "journal";
  doi_enabled: boolean;
  prefix: string;
  suffix_pattern: string;
  depositor_name: string;
  depositor_email: string;
}

function toForm(settings: PublishingSettings): FormValues {
  const known = LICENCES.some((licence) => licence.value === settings.license_url);
  return {
    site_url: settings.site_url,
    licence: known || !settings.license_url ? settings.license_url || LICENCES[0]?.value || "" : CUSTOM,
    custom_licence: known ? "" : settings.license_url,
    copyright_holder: settings.copyright_holder,
    doi_enabled: settings.doi?.enabled ?? false,
    prefix: settings.doi?.prefix ?? "",
    suffix_pattern: settings.doi?.suffix_pattern ?? "{journal}.{year}.{number}",
    depositor_name: settings.doi?.depositor_name ?? "",
    depositor_email: settings.doi?.depositor_email ?? "",
  };
}

function toSettings(values: FormValues): PublishingSettings {
  return {
    site_url: values.site_url.trim(),
    license_url: values.licence === CUSTOM ? values.custom_licence.trim() : values.licence,
    copyright_holder: values.copyright_holder,
    doi: {
      enabled: values.doi_enabled,
      prefix: values.prefix.trim(),
      suffix_pattern: values.suffix_pattern.trim(),
      depositor_name: values.depositor_name.trim(),
      depositor_email: values.depositor_email.trim(),
    },
  };
}

function Registration({ data }: { data: PublishingSettingsOut }) {
  const mode = CROSSREF_MODES[data.crossref_mode] ?? {
    label: data.crossref_mode,
    color: "gray",
    text: "",
  };
  const yes = (value: boolean) => (
    <Badge color={value ? "teal" : "gray"} variant="light">
      {value ? "Configured" : "Not configured"}
    </Badge>
  );
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={4}>Registration</Title>
        <Text size="sm" c="dimmed">
          Set on the server by the administrator, not here. The Crossref password never reaches the browser.
        </Text>
        <Table verticalSpacing="xs">
          <Table.Tbody>
            <Table.Tr>
              <Table.Td w={220}>
                <Text size="sm">DOI registration</Text>
              </Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Badge color={mode.color} variant="light">
                    {mode.label}
                  </Badge>
                  <Text size="sm">{mode.text}</Text>
                </Group>
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                <Text size="sm">Crossref account</Text>
              </Table.Td>
              <Table.Td>{yes(data.crossref_account_configured)}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                <Text size="sm">Updates to the journal's site</Text>
              </Table.Td>
              <Table.Td>{yes(data.site_revalidation_configured)}</Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  );
}

function SettingsForm({ state }: { state: PublishingSettingsState }) {
  const queryClient = useQueryClient();
  const { data } = state;
  const form = useForm<FormValues>({
    initialValues: toForm(data.settings),
    validate: {
      site_url: (value) =>
        value.trim() && !/^https?:\/\/\S+$/.test(value.trim())
          ? "Enter a full address starting with https://"
          : null,
      custom_licence: (value, values) =>
        values.licence === CUSTOM && !/^https?:\/\/\S+$/.test(value.trim())
          ? "Enter the licence's full address, starting with https://"
          : null,
      prefix: (value, values) =>
        values.doi_enabled && !/^10\.\d{4,9}$/.test(value.trim()) ? "A DOI prefix looks like 10.12345" : null,
      depositor_email: (value) =>
        value.trim() && !/^\S+@\S+\.\S+$/.test(value.trim()) ? "Enter a valid e-mail address" : null,
    },
  });

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      withEtag(
        api.PUT("/api/v1/journal/publishing-settings", {
          params: { header: { "if-match": state.etag } },
          body: toSettings(values),
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(publishingSettingsKey, saved);
      form.resetDirty();
      notifySaved("Publishing settings saved");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed the journal settings",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: publishingSettingsKey });
        return;
      }
      showRequestError(error, form);
    },
  });

  const placeholders = Object.entries(data.suffix_placeholders);
  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        {data.problems.length > 0 ? (
          <Alert color="orange" icon={<IconAlertTriangle />} title="DOIs cannot be registered yet">
            <List size="sm">
              {data.problems.map((problem) => (
                <List.Item key={problem}>{problem}</List.Item>
              ))}
            </List>
          </Alert>
        ) : null}
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>The journal's site</Title>
            <TextInput
              label="Address of the site"
              description="Article pages are at this address followed by /articles/…. Crossref and indexers link there, so set it before the first DOI is registered."
              placeholder="https://journal.example.org"
              {...form.getInputProps("site_url")}
            />
          </Stack>
        </Card>
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Licence and copyright</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select
                label="Licence"
                description="Applied to articles published from now on."
                allowDeselect={false}
                data={[...LICENCES, { value: CUSTOM, label: "Another licence…" }]}
                {...form.getInputProps("licence")}
              />
              {form.values.licence === CUSTOM ? (
                <TextInput
                  label="Licence address"
                  placeholder="https://…"
                  {...form.getInputProps("custom_licence")}
                />
              ) : null}
            </SimpleGrid>
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Copyright holder
              </Text>
              <SegmentedControl
                w={{ base: "100%", sm: 360 }}
                data={[
                  { value: "authors", label: "The authors" },
                  { value: "journal", label: "The journal's publisher" },
                ]}
                {...form.getInputProps("copyright_holder")}
              />
            </Stack>
          </Stack>
        </Card>
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>DOIs</Title>
            <Switch
              label="Assign DOIs to articles"
              description="A DOI is assigned when the article enters production, so it can be printed on the galleys, and registered with Crossref when it is published."
              {...form.getInputProps("doi_enabled", { type: "checkbox" })}
            />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                label="DOI prefix"
                description="Given by Crossref when the journal joins."
                placeholder="10.12345"
                {...form.getInputProps("prefix")}
              />
              <TextInput
                label="Suffix pattern"
                description={
                  data.example_doi ? (
                    <>
                      For example: <Code>{data.example_doi}</Code>
                    </>
                  ) : (
                    "Each article's DOI is the prefix, a slash and this pattern."
                  )
                }
                {...form.getInputProps("suffix_pattern")}
              />
            </SimpleGrid>
            {placeholders.length > 0 ? (
              <Stack gap={4}>
                <Text size="sm" c="dimmed">
                  The pattern may use:
                </Text>
                {placeholders.map(([name, help]) => (
                  <Text key={name} size="sm">
                    <Code>{name}</Code> {help}
                  </Text>
                ))}
              </Stack>
            ) : null}
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                label="Depositor name"
                description="Who Crossref writes to about deposits."
                {...form.getInputProps("depositor_name")}
              />
              <TextInput label="Depositor e-mail" type="email" {...form.getInputProps("depositor_email")} />
            </SimpleGrid>
          </Stack>
        </Card>
        <Registration data={data} />
        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending}>
            Save
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function PublishingSettingsPage() {
  const settings = usePublishingSettings();
  return (
    <Stack>
      <PageHeader
        title="Publishing settings"
        description="Where articles appear, under which licence, and how they get their DOIs."
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
