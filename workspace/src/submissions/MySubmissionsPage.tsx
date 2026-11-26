import type { SubmissionSummary } from "@jps/api-client";
import { ActionIcon, Anchor, Badge, Button, Card, Group, Stack, Table, Text, Tooltip } from "@mantine/core";
import { modals } from "@mantine/modals";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import { api, unwrap } from "../api";
import { can, useSignedInUser } from "../auth";
import { PageHeader, QueryState } from "../components/common";
import { formatDate } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { statusLook } from "./labels";

export function MySubmissionsPage() {
  const me = useSignedInUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const submissions = useInfiniteQuery({
    queryKey: ["submissions", "mine"],
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/submissions", { params: { query: { cursor: pageParam ?? undefined } } })),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
  });
  const rows = submissions.data?.pages.flatMap((page) => page.items) ?? [];

  const remove = useMutation({
    mutationFn: (submission: SubmissionSummary) =>
      unwrap(
        api.DELETE("/api/v1/submissions/{submission_id}", {
          params: { path: { submission_id: submission.id } },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["submissions"] });
      notifySaved("Draft deleted");
    },
    onError: (error) => showRequestError(error),
  });

  const pathOf = (submission: SubmissionSummary) =>
    submission.status === "draft" ? `/submissions/${submission.id}/edit` : `/submissions/${submission.id}`;

  const confirmDelete = (submission: SubmissionSummary) =>
    modals.openConfirmModal({
      title: "Delete this draft?",
      children: <Text size="sm">The draft and its files will be removed. This cannot be undone.</Text>,
      labels: { confirm: "Delete draft", cancel: "Keep it" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(submission),
    });

  return (
    <Stack>
      <PageHeader
        title="My submissions"
        description="Manuscripts you have started or are listed on as an author."
        actions={
          can(me, "submissions.create") ? (
            <Button component={Link} to="/submissions/new" leftSection={<IconPlus size={16} />}>
              New submission
            </Button>
          ) : null
        }
      />
      {submissions.data ? (
        <Card withBorder padding={0}>
          {rows.length === 0 ? (
            <Stack p="lg" gap="sm" align="flex-start">
              <Text>You have no submissions yet.</Text>
              {can(me, "submissions.create") ? (
                <Button component={Link} to="/submissions/new" variant="light">
                  Submit a manuscript
                </Button>
              ) : null}
            </Stack>
          ) : (
            <Table.ScrollContainer minWidth={680}>
              <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={150}>Number</Table.Th>
                    <Table.Th>Title</Table.Th>
                    <Table.Th w={170}>Status</Table.Th>
                    <Table.Th w={130}>Date</Table.Th>
                    <Table.Th w={50} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((submission) => {
                    const look = statusLook(submission);
                    return (
                      <Table.Tr
                        key={submission.id}
                        className="clickable-row"
                        onClick={() => navigate(pathOf(submission))}
                      >
                        <Table.Td>
                          <Text size="sm" ff="monospace">
                            {submission.number ?? "—"}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          {/* A real link, so the row also works from the keyboard and opens in a new tab. */}
                          <Anchor
                            component={Link}
                            to={pathOf(submission)}
                            size="sm"
                            fw={500}
                            c="inherit"
                            lineClamp={2}
                            onClick={(event) => event.stopPropagation()}
                          >
                            {submission.title || "Untitled manuscript"}
                          </Anchor>
                          <Text size="xs" c="dimmed">
                            {submission.section.title}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Badge color={look.color} variant="light">
                            {look.label}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">
                            {formatDate(submission.submitted_at ?? submission.updated_at)}
                          </Text>
                        </Table.Td>
                        <Table.Td onClick={(event) => event.stopPropagation()}>
                          {submission.status === "draft" ? (
                            <Tooltip label="Delete draft">
                              <ActionIcon
                                variant="subtle"
                                color="red"
                                aria-label="Delete draft"
                                onClick={() => confirmDelete(submission)}
                              >
                                <IconTrash size={18} />
                              </ActionIcon>
                            </Tooltip>
                          ) : null}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          {submissions.hasNextPage ? (
            <Group justify="center" p="md">
              <Button
                variant="light"
                loading={submissions.isFetchingNextPage}
                onClick={() => submissions.fetchNextPage()}
              >
                Show more
              </Button>
            </Group>
          ) : null}
        </Card>
      ) : (
        <QueryState
          isPending={submissions.isPending}
          error={submissions.error}
          onRetry={() => submissions.refetch()}
        />
      )}
    </Stack>
  );
}
