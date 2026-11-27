import type { PublishingOut, PublishingUpdate } from "@jps/api-client";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { IconCalendarEvent, IconCheck, IconCircleCheck, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../api";
import { QueryState } from "../components/common";
import { formatDate, formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { submissionKey } from "../submissions/queries";
import { workflowKey } from "../workflow/queries";
import { GalleysCard } from "./GalleysCard";

export const publicationKey = (id: number) => ["publication", id] as const;

const BUSY = new Set(["pending_upload", "processing"]);

const DEPOSIT_STATUS: Record<string, { label: string; color: string }> = {
  queued: { label: "Queued", color: "gray" },
  submitted: { label: "Sent, waiting for Crossref", color: "blue" },
  registered: { label: "Registered", color: "green" },
  failed: { label: "Failed", color: "red" },
};

const VERSION_STATUS: Record<string, { label: string; color: string }> = {
  draft: { label: "Draft", color: "gray" },
  queued: { label: "In preparation", color: "gray" },
  scheduled: { label: "Scheduled", color: "teal" },
  published: { label: "Published", color: "green" },
};

function usePublication(submissionId: number) {
  return useQuery({
    queryKey: publicationKey(submissionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/submissions/{submission_id}/publishing", {
          params: { path: { submission_id: submissionId } },
        }),
      ),
    // Galley files are checked by the worker: look again until they are ready.
    refetchInterval: (query) =>
      query.state.data?.galleys.some((galley) => BUSY.has(galley.file.status)) ? 1500 : false,
  });
}

/** Store a new state of the publication screen; the manuscript's status may have changed too. */
function useStore(submissionId: number) {
  const queryClient = useQueryClient();
  return (data: PublishingOut, { statusChanged = false } = {}) => {
    queryClient.setQueryData(publicationKey(submissionId), data);
    if (statusChanged) {
      queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
      queryClient.invalidateQueries({ queryKey: submissionKey(submissionId) });
      queryClient.invalidateQueries({ queryKey: ["submissions"] });
    }
  };
}

function actionText(data: PublishingOut): { button: string; help: string } | null {
  switch (data.action) {
    case "schedule":
      return {
        button: "Schedule for publication",
        help: "The article will appear when its issue is published.",
      };
    case "publish":
      return { button: "Publish now", help: "The issue is already out: the article appears at once." };
    case "publish_version":
      return {
        button: `Publish version ${data.publication.version}`,
        help: "Readers get the new version; the earlier one stays available.",
      };
    default:
      return null;
  }
}

function StateAlert({ data }: { data: PublishingOut }) {
  const { publication } = data;
  if (data.status === "scheduled") {
    return (
      <Alert
        color="teal"
        icon={<IconCalendarEvent />}
        title={`Scheduled in ${data.issue?.label ?? "its issue"}`}
      >
        The article will be published with the issue.
      </Alert>
    );
  }
  if (data.status === "published") {
    const published = data.versions.find((v) => v.version === 1)?.published_at ?? publication.published_at;
    return (
      <Alert color="green" icon={<IconCircleCheck />} title="Published">
        <Stack gap={4}>
          <Text size="sm">
            Published {formatDate(published)}
            {data.issue ? ` in ${data.issue.label}` : ""}.
          </Text>
          {publication.article_url ? (
            <Anchor href={publication.article_url} target="_blank" size="sm">
              {publication.article_url}
            </Anchor>
          ) : null}
          {publication.doi_url ? (
            <Anchor href={publication.doi_url} target="_blank" size="sm">
              {publication.doi_url}
            </Anchor>
          ) : null}
        </Stack>
      </Alert>
    );
  }
  return null;
}

function ReadinessCard({ data }: { data: PublishingOut }) {
  const store = useStore(data.submission_id);
  const [confirming, setConfirming] = useState(false);
  const path = { params: { path: { submission_id: data.submission_id } } };
  const text = actionText(data);

  const publish = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/submissions/{submission_id}/publish", path)),
    onSuccess: (result) => {
      store(result, { statusChanged: true });
      setConfirming(false);
      notifySaved(result.status === "scheduled" ? "Scheduled for publication" : "Published");
    },
    onError: (error) => showRequestError(error),
  });

  const unschedule = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/submissions/{submission_id}/unschedule", path)),
    onSuccess: (result) => {
      store(result, { statusChanged: true });
      notifySaved("Unscheduled. The article can be changed again.");
    },
    onError: (error) => showRequestError(error),
  });

  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={4}>{data.status === "published" && !text ? "Publication" : "Ready to publish"}</Title>
        <StateAlert data={data} />
        {text ? (
          <Stack gap={6}>
            {data.checks.map((check) => (
              <Group key={check.key} gap="sm" wrap="nowrap" align="flex-start">
                <ThemeIcon
                  size="sm"
                  radius="xl"
                  variant="light"
                  color={check.ok ? "teal" : "orange"}
                  aria-label={check.ok ? "Done" : "Missing"}
                >
                  {check.ok ? <IconCheck size={14} /> : <IconX size={14} />}
                </ThemeIcon>
                <div>
                  <Text size="sm" fw={500}>
                    {check.label}
                  </Text>
                  {check.detail ? (
                    <Text size="xs" c="dimmed">
                      {check.detail}
                    </Text>
                  ) : null}
                </div>
              </Group>
            ))}
          </Stack>
        ) : null}
        {text || data.can_unschedule ? (
          <Group gap="sm">
            {text ? (
              <Button disabled={!(data.ready && data.can_publish)} onClick={() => setConfirming(true)}>
                {text.button}
              </Button>
            ) : null}
            {data.can_unschedule ? (
              <Button
                variant="default"
                loading={unschedule.isPending}
                onClick={() =>
                  modals.openConfirmModal({
                    title: "Unschedule the article?",
                    children: "It leaves the issue's publication queue and can be changed again.",
                    labels: { confirm: "Unschedule", cancel: "Keep it scheduled" },
                    onConfirm: () => unschedule.mutate(),
                  })
                }
              >
                Unschedule
              </Button>
            ) : null}
          </Group>
        ) : null}
        {text ? (
          <Text size="xs" c="dimmed">
            {data.can_publish
              ? text.help
              : "Only an editor who makes decisions on the article can publish it."}
          </Text>
        ) : null}
      </Stack>
      <Modal opened={confirming} onClose={() => setConfirming(false)} title={text?.button ?? ""}>
        <Stack>
          <Text size="sm">
            {text?.help} A published version cannot be changed; corrections become a new version.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button loading={publish.isPending} onClick={() => publish.mutate()}>
              Confirm
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

interface DetailValues {
  issue_id: string | null;
  pages: string;
  url_path: string;
  license_url: string;
  copyright_holder: string;
  copyright_year: number | string;
  version_note: string;
}

function valuesOf(data: PublishingOut): DetailValues {
  const p = data.publication;
  return {
    issue_id: p.issue_id === null ? null : String(p.issue_id),
    pages: p.pages,
    url_path: p.url_path ?? "",
    license_url: p.license_url,
    copyright_holder: p.copyright_holder,
    copyright_year: p.copyright_year ?? "",
    version_note: p.version_note,
  };
}

/** Only the fields the editor changed, in the API's terms. */
function changesOf(initial: DetailValues, values: DetailValues): PublishingUpdate {
  const changes: PublishingUpdate = {};
  if (values.issue_id !== initial.issue_id) {
    changes.issue_id = values.issue_id === null ? null : Number(values.issue_id);
  }
  for (const field of ["pages", "license_url", "copyright_holder", "version_note"] as const) {
    if (values[field].trim() !== initial[field].trim()) changes[field] = values[field].trim();
  }
  if (values.url_path.trim() !== initial.url_path.trim()) changes.url_path = values.url_path.trim() || null;
  if (values.copyright_year !== initial.copyright_year) {
    changes.copyright_year = values.copyright_year === "" ? null : Number(values.copyright_year);
  }
  return changes;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm">{value || "—"}</Text>
    </div>
  );
}

function DetailsCard({ data }: { data: PublishingOut }) {
  const store = useStore(data.submission_id);
  const initial = valuesOf(data);
  const form = useForm<DetailValues>({ initialValues: initial });
  const { publication } = data;
  const issues = useQuery({
    queryKey: ["issues"],
    queryFn: () => unwrap(api.GET("/api/v1/issues")),
    enabled: data.can_edit,
  });

  const save = useMutation({
    mutationFn: (changes: PublishingUpdate) =>
      unwrap(
        api.PATCH("/api/v1/submissions/{submission_id}/publishing", {
          params: {
            path: { submission_id: data.submission_id },
            header: { "if-match": `"${publication.row_version}"` },
          },
          body: changes,
        }),
      ),
    onSuccess: (result) => {
      store(result);
      form.setInitialValues(valuesOf(result));
      form.setValues(valuesOf(result));
      notifySaved();
    },
    onError: (error) => showRequestError(error, form),
  });

  if (!data.can_edit) {
    return (
      <Card withBorder padding="lg">
        <Stack gap="sm">
          <Title order={4}>Issue and details</Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Detail label="Issue" value={data.issue?.label ?? ""} />
            <Detail label="Pages" value={publication.pages} />
            <Detail label="Address on the site" value={publication.slug} />
            <Detail label="Licence" value={publication.license_url} />
            <Detail
              label="Copyright"
              value={[publication.copyright_year, publication.copyright_holder].filter(Boolean).join(" ")}
            />
            {publication.version > 1 ? (
              <Detail label="What changed in this version" value={publication.version_note} />
            ) : null}
          </SimpleGrid>
        </Stack>
      </Card>
    );
  }

  const changes = changesOf(initial, form.values);
  return (
    <Card withBorder padding="lg">
      <form onSubmit={form.onSubmit(() => save.mutate(changesOf(initial, form.values)))}>
        <Stack gap="sm">
          <Title order={4}>Issue and details</Title>
          <Select
            label="Issue"
            placeholder="Choose the issue"
            data={(issues.data ?? []).map((issue) => ({
              value: String(issue.id),
              label: `${issue.label} (${issue.status === "published" ? "published" : "future"})`,
            }))}
            clearable
            nothingFoundMessage={issues.isPending ? "Loading…" : "No issues yet. Create one under Issues."}
            {...form.getInputProps("issue_id")}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label="Pages"
              placeholder="e.g. 1-12 or e1234"
              maxLength={30}
              {...form.getInputProps("pages")}
            />
            <TextInput
              label="Address on the site"
              description={`The article's address: /articles/${publication.slug}`}
              placeholder={publication.slug}
              maxLength={100}
              {...form.getInputProps("url_path")}
            />
          </SimpleGrid>
          <TextInput
            label="Licence"
            placeholder="https://creativecommons.org/licenses/by/4.0/"
            maxLength={300}
            {...form.getInputProps("license_url")}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label="Copyright holder"
              placeholder="Filled in on publication"
              maxLength={300}
              {...form.getInputProps("copyright_holder")}
            />
            <NumberInput
              label="Copyright year"
              placeholder="Filled in on publication"
              min={1900}
              max={2200}
              allowDecimal={false}
              {...form.getInputProps("copyright_year")}
            />
          </SimpleGrid>
          {publication.version > 1 ? (
            <Textarea
              label="What changed in this version"
              description="Shown to readers next to the version"
              autosize
              minRows={2}
              maxLength={2000}
              {...form.getInputProps("version_note")}
            />
          ) : null}
          <Group justify="flex-end">
            <Button type="submit" disabled={Object.keys(changes).length === 0} loading={save.isPending}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

function VersionsCard({ data }: { data: PublishingOut }) {
  const store = useStore(data.submission_id);
  const [creating, setCreating] = useState(false);
  const [note, setNote] = useState("");
  const path = { params: { path: { submission_id: data.submission_id } } };

  const create = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/submissions/{submission_id}/versions", { ...path, body: { note } })),
    onSuccess: (result) => {
      store(result, { statusChanged: true });
      setCreating(false);
      setNote("");
      notifySaved(`Version ${result.publication.version} started`);
    },
    onError: (error) => showRequestError(error),
  });

  const discard = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/submissions/{submission_id}/versions/draft", path)),
    onSuccess: (result) => {
      store(result, { statusChanged: true });
      notifySaved("Version discarded");
    },
    onError: (error) => showRequestError(error),
  });

  if (data.versions.length <= 1 && !data.can_create_version) return null;
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>Versions</Title>
          <Group gap="xs">
            {data.can_discard_version ? (
              <Button
                size="xs"
                variant="subtle"
                color="red"
                loading={discard.isPending}
                onClick={() =>
                  modals.openConfirmModal({
                    title: `Discard version ${data.publication.version}?`,
                    children: "Its changes are lost. Readers keep the published version.",
                    labels: { confirm: "Discard", cancel: "Keep it" },
                    confirmProps: { color: "red" },
                    onConfirm: () => discard.mutate(),
                  })
                }
              >
                Discard version {data.publication.version}
              </Button>
            ) : null}
            {data.can_create_version ? (
              <Button size="xs" variant="light" onClick={() => setCreating(true)}>
                Create a new version
              </Button>
            ) : null}
          </Group>
        </Group>
        <Text size="sm" c="dimmed">
          A published version is never changed. To correct the article, create a new version and publish it.
        </Text>
        <Table verticalSpacing="xs">
          <Table.Tbody>
            {data.versions.map((version) => {
              const look = VERSION_STATUS[version.status] ?? { label: version.status, color: "gray" };
              return (
                <Table.Tr key={version.id}>
                  <Table.Td>
                    <Text size="sm" fw={600}>
                      v{version.version}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={look.color} variant="light">
                      {look.label}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{version.published_at ? formatDate(version.published_at) : "—"}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {version.version_note}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Stack>
      <Modal opened={creating} onClose={() => setCreating(false)} title="Create a new version">
        <Stack>
          <Textarea
            label="What is being corrected"
            description="Shown to readers next to the new version"
            autosize
            minRows={3}
            maxLength={2000}
            value={note}
            onChange={(event) => setNote(event.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button loading={create.isPending} onClick={() => create.mutate()}>
              Create version
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

function DoiCard({ data, onChanged }: { data: PublishingOut; onChanged: () => void }) {
  const store = useStore(data.submission_id);
  const path = { params: { path: { submission_id: data.submission_id } } };
  const assign = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/submissions/{submission_id}/doi", path)),
    onSuccess: (result) => {
      store(result);
      notifySaved("DOI assigned");
    },
    onError: (error) => showRequestError(error),
  });
  const deposit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/submissions/{submission_id}/doi/deposits", path)),
    onSuccess: () => {
      notifySaved("Sent to Crossref");
      onChanged();
    },
    onError: (error) => showRequestError(error),
  });

  if (!data.doi_enabled) return null;
  const { publication } = data;
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>DOI</Title>
          <Group gap="xs">
            {data.can_assign_doi ? (
              <Button size="xs" variant="light" loading={assign.isPending} onClick={() => assign.mutate()}>
                Assign DOI now
              </Button>
            ) : null}
            {data.can_deposit ? (
              <Button size="xs" variant="light" loading={deposit.isPending} onClick={() => deposit.mutate()}>
                Send to Crossref again
              </Button>
            ) : null}
          </Group>
        </Group>
        {publication.doi ? (
          publication.doi_url ? (
            <Anchor href={publication.doi_url} target="_blank" size="sm">
              {publication.doi}
            </Anchor>
          ) : (
            <Text size="sm">{publication.doi}</Text>
          )
        ) : (
          <Text size="sm" c="dimmed">
            Not assigned yet.
          </Text>
        )}
        <Text size="xs" c="dimmed">
          The DOI is registered with Crossref when the article is published.
        </Text>
        {data.deposits.length > 0 ? (
          <Table verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Status</Table.Th>
                <Table.Th>Sent</Table.Th>
                <Table.Th>Crossref's answer</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.deposits.map((d) => {
                const look = DEPOSIT_STATUS[d.status] ?? { label: d.status, color: "gray" };
                return (
                  <Table.Tr key={d.id}>
                    <Table.Td>
                      <Badge color={look.color} variant="light">
                        {look.label}
                      </Badge>
                      {d.mode !== "production" ? (
                        <Text size="xs" c="dimmed">
                          {d.mode} mode
                        </Text>
                      ) : null}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{formatDateTime(d.submitted_at ?? d.created_at)}</Text>
                      {d.completed_at ? (
                        <Text size="xs" c="dimmed">
                          Done {formatDateTime(d.completed_at)}
                        </Text>
                      ) : null}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{d.message || "—"}</Text>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        ) : null}
      </Stack>
    </Card>
  );
}

/** The article's publication: readiness, issue and details, galleys, versions and DOI. */
export function PublicationPanel({ submissionId }: { submissionId: number }) {
  const queryClient = useQueryClient();
  const query = usePublication(submissionId);
  if (!query.data) {
    return <QueryState isPending={query.isPending} error={query.error} onRetry={() => query.refetch()} />;
  }
  const data = query.data;
  const refresh = () => queryClient.invalidateQueries({ queryKey: publicationKey(submissionId) });
  return (
    <Stack gap="lg">
      <ReadinessCard data={data} />
      <DetailsCard key={`${data.publication.id}-${data.publication.row_version}`} data={data} />
      <GalleysCard data={data} onChanged={refresh} />
      <VersionsCard data={data} />
      <DoiCard data={data} onChanged={refresh} />
    </Stack>
  );
}
