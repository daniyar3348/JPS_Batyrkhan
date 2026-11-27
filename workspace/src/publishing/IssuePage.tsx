import type { IssueArticle, IssueDetail } from "@jps/api-client";
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
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconArrowDown, IconArrowUp, IconStar, IconTrash, IconWorldUpload } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, api, unwrap } from "../api";
import { can, useMe } from "../auth";
import { PageHeader, QueryState } from "../components/common";
import { formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import {
  IssueFields,
  type IssueFormValues,
  IssueStatusBadges,
  issueBody,
  issueFormValues,
  validateIssue,
} from "./IssuesPage";
import { issueKey, issuesKey, useIssue } from "./queries";

const ARTICLE_STATUS: Record<string, { label: string; color: string }> = {
  queued: { label: "Not scheduled", color: "gray" },
  scheduled: { label: "Scheduled", color: "teal" },
  published: { label: "Published", color: "green" },
};

function useStore(issueId: number) {
  const queryClient = useQueryClient();
  return (issue: IssueDetail) => {
    queryClient.setQueryData(issueKey(issueId), issue);
    queryClient.invalidateQueries({ queryKey: issuesKey, exact: true });
  };
}

function EditIssueCard({ issue }: { issue: IssueDetail }) {
  const queryClient = useQueryClient();
  const store = useStore(issue.id);
  const form = useForm<IssueFormValues>({ initialValues: issueFormValues(issue), validate: validateIssue });
  // Load the saved values again after a save, or when someone else's change is loaded.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset only when the issue's version changes
  useEffect(() => {
    form.setValues(issueFormValues(issue));
    form.resetDirty(issueFormValues(issue));
  }, [issue.row_version]);
  const save = useMutation({
    mutationFn: (values: IssueFormValues) =>
      unwrap(
        api.PUT("/api/v1/issues/{issue_id}", {
          params: { path: { issue_id: issue.id }, header: { "if-match": `"${issue.row_version}"` } },
          body: issueBody(values),
        }),
      ),
    onSuccess: (saved) => {
      store(saved);
      notifySaved("Issue saved");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed this issue",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: issueKey(issue.id) });
        return;
      }
      showRequestError(error, form);
    },
  });
  return (
    <Card withBorder padding="lg">
      <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
        <Stack>
          <Title order={4}>Details</Title>
          {issue.status === "published" ? (
            <Text size="sm" c="dimmed">
              The issue is published: changes appear in its articles' citations on the site.
            </Text>
          ) : null}
          <IssueFields form={form} />
          <Group justify="flex-end">
            <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

function ArticlesCard({ issue, manage }: { issue: IssueDetail; manage: boolean }) {
  const store = useStore(issue.id);
  const reorder = useMutation({
    mutationFn: (submissionIds: number[]) =>
      unwrap(
        api.PUT("/api/v1/issues/{issue_id}/order", {
          params: { path: { issue_id: issue.id } },
          body: { submission_ids: submissionIds },
        }),
      ),
    onSuccess: (saved) => store(saved),
    onError: (error) => showRequestError(error),
  });
  const articles = issue.articles;
  // Articles keep their section's place; they move only within it.
  const move = (index: number, by: -1 | 1) => {
    const other = articles[index + by];
    const article = articles[index];
    if (!other || !article || other.section.id !== article.section.id) return;
    const ids = articles.map((a) => a.submission_id);
    [ids[index], ids[index + by]] = [ids[index + by] as number, ids[index] as number];
    reorder.mutate(ids);
  };
  const canMove = (index: number, by: -1 | 1) =>
    articles[index + by]?.section.id === articles[index]?.section.id;

  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={4}>Articles</Title>
        {articles.length === 0 ? (
          <Text size="sm" c="dimmed">
            No articles yet. Choose this issue on an article's Publication tab to add it.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={760}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Manuscript</Table.Th>
                  <Table.Th>Article</Table.Th>
                  <Table.Th>Section</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Pages</Table.Th>
                  <Table.Th>DOI</Table.Th>
                  <Table.Th aria-label="Order" />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {articles.map((article: IssueArticle, index) => {
                  const state = ARTICLE_STATUS[article.status] ?? { label: article.status, color: "gray" };
                  return (
                    <Table.Tr key={article.submission_id}>
                      <Table.Td>
                        <Anchor
                          component={Link}
                          to={`/submissions/${article.submission_id}`}
                          size="sm"
                          ff="monospace"
                          style={{ whiteSpace: "nowrap" }}
                        >
                          {article.number ?? article.submission_id}
                        </Anchor>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" fw={500} lineClamp={2}>
                          {article.title}
                        </Text>
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {article.authors}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{article.section.title}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Stack gap={4} align="flex-start">
                          <Badge color={state.color} variant="light">
                            {state.label}
                          </Badge>
                          {article.fee_settled === false ? (
                            <Badge color="orange" variant="light">
                              Fee not settled
                            </Badge>
                          ) : null}
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{article.pages || "—"}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" ff="monospace">
                          {article.doi ?? "—"}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap" display={manage ? undefined : "none"}>
                          <ActionIcon
                            variant="subtle"
                            aria-label={`Move ${article.title} up`}
                            disabled={!canMove(index, -1) || reorder.isPending}
                            onClick={() => move(index, -1)}
                          >
                            <IconArrowUp size={16} />
                          </ActionIcon>
                          <ActionIcon
                            variant="subtle"
                            aria-label={`Move ${article.title} down`}
                            disabled={!canMove(index, 1) || reorder.isPending}
                            onClick={() => move(index, 1)}
                          >
                            <IconArrowDown size={16} />
                          </ActionIcon>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>
    </Card>
  );
}

function PublishModal({ issue, onClose }: { issue: IssueDetail; onClose: () => void }) {
  const store = useStore(issue.id);
  const [makeCurrent, setMakeCurrent] = useState(true);
  const scheduled = issue.articles.filter((a) => a.status === "scheduled").length;
  const notScheduled = issue.articles.filter((a) => a.status === "queued").length;
  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/issues/{issue_id}/publish", {
          params: { path: { issue_id: issue.id } },
          body: { make_current: makeCurrent },
        }),
      ),
    onSuccess: (saved) => {
      store(saved);
      notifySaved("The issue is published");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Modal opened onClose={onClose} title={`Publish ${issue.label}?`}>
      <Stack>
        <Text size="sm">
          {scheduled === 1
            ? "The scheduled article is published with the issue,"
            : `All ${scheduled} scheduled articles are published with the issue,`}{" "}
          at once. Readers see them on the journal's site, and their DOIs are registered. Published articles
          are never changed; corrections become new versions.
        </Text>
        {notScheduled > 0 ? (
          <Alert color="orange">
            {notScheduled === 1
              ? "One article in this issue is not scheduled and will not be published."
              : `${notScheduled} articles in this issue are not scheduled and will not be published.`}
          </Alert>
        ) : null}
        <Checkbox
          label="Make it the current issue"
          description="The issue the site's home page shows."
          checked={makeCurrent}
          onChange={(event) => setMakeCurrent(event.currentTarget.checked)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            leftSection={<IconWorldUpload size={16} />}
            loading={publish.isPending}
            onClick={() => publish.mutate()}
          >
            Publish issue
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function IssueActions({ issue }: { issue: IssueDetail }) {
  const store = useStore(issue.id);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [publishing, setPublishing] = useState(false);
  const makeCurrent = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/issues/{issue_id}/current", { params: { path: { issue_id: issue.id } } })),
    onSuccess: (saved) => {
      store(saved);
      notifySaved("This is now the current issue");
    },
    onError: (error) => showRequestError(error),
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE("/api/v1/issues/{issue_id}", { params: { path: { issue_id: issue.id } } })),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: issueKey(issue.id) });
      queryClient.invalidateQueries({ queryKey: issuesKey });
      notifySaved("Issue deleted");
      navigate("/publishing/issues");
    },
    onError: (error) => showRequestError(error),
  });
  const future = issue.status === "future";
  return (
    <Group gap="xs">
      {future && issue.articles.length === 0 ? (
        <Button
          variant="subtle"
          color="red"
          leftSection={<IconTrash size={16} />}
          loading={remove.isPending}
          onClick={() =>
            modals.openConfirmModal({
              title: `Delete ${issue.label}?`,
              children: "The issue has no articles. It is removed for good.",
              labels: { confirm: "Delete", cancel: "Cancel" },
              confirmProps: { color: "red" },
              onConfirm: () => remove.mutate(),
            })
          }
        >
          Delete
        </Button>
      ) : null}
      {!future && !issue.is_current ? (
        <Button
          variant="light"
          leftSection={<IconStar size={16} />}
          loading={makeCurrent.isPending}
          onClick={() => makeCurrent.mutate()}
        >
          Make current
        </Button>
      ) : null}
      {future ? (
        <Button leftSection={<IconWorldUpload size={16} />} onClick={() => setPublishing(true)}>
          Publish issue
        </Button>
      ) : null}
      {publishing ? <PublishModal issue={issue} onClose={() => setPublishing(false)} /> : null}
    </Group>
  );
}

export function IssuePage() {
  const id = Number(useParams().id);
  const issue = useIssue(id);
  // Everyone who puts articles into issues sees them; creating, changing and publishing needs publishing.manage.
  const manage = can(useMe().data, "publishing.manage");
  if (!issue.data) {
    return <QueryState isPending={issue.isPending} error={issue.error} onRetry={() => issue.refetch()} />;
  }
  const data = issue.data;
  return (
    <Stack gap="lg">
      <PageHeader
        title={data.label}
        description={
          <Group gap="xs">
            <IssueStatusBadges issue={data} />
            <Text size="sm" c="dimmed">
              {data.published_at
                ? `Published ${formatDateTime(data.published_at)}`
                : "Not published yet. Articles scheduled into it appear when it is published."}
            </Text>
          </Group>
        }
        actions={manage ? <IssueActions issue={data} /> : null}
      />
      <Anchor component={Link} to="/publishing/issues" size="sm">
        ← All issues
      </Anchor>
      <ArticlesCard issue={data} manage={manage} />
      {manage ? <EditIssueCard issue={data} /> : null}
    </Stack>
  );
}
