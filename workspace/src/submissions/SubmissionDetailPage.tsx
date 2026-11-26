import type { SimilarityCheckOut, SubmissionOut } from "@jps/api-client";
import { Alert, Anchor, Badge, Button, Card, Group, Stack, Table, Text, Title } from "@mantine/core";
import { IconCircleCheck, IconPencil, IconRefresh } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { statusLook } from "./labels";
import { submissionKey, useSubmission } from "./queries";
import { SubmissionSummaryCards } from "./SubmissionSummaryCards";

function SimilarityPanel({ submission }: { submission: SubmissionOut }) {
  const queryClient = useQueryClient();
  const checks = submission.similarity_checks ?? [];
  const rerun = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/similarity-checks", {
          params: { path: { submission_id: submission.id } },
        }),
      ),
    onSuccess: () => {
      notifySaved("Similarity check started");
      queryClient.invalidateQueries({ queryKey: submissionKey(submission.id) });
    },
    onError: (error) => showRequestError(error),
  });

  const scoreBadge = (check: SimilarityCheckOut) => {
    if (check.status === "completed") {
      return (
        <Badge color={check.flagged ? "red" : "teal"} variant="light" size="lg">
          {check.score_percent}% similar{check.flagged ? " — please review" : ""}
        </Badge>
      );
    }
    if (check.status === "failed") return <Badge color="red">Failed</Badge>;
    return <Badge color="blue">In progress</Badge>;
  };

  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>Similarity check</Title>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconRefresh size={14} />}
            loading={rerun.isPending}
            onClick={() => rerun.mutate()}
          >
            Check again
          </Button>
        </Group>
        <Text size="sm" c="dimmed">
          Visible to editors only. A high score is a reason to read the report, not a verdict.
        </Text>
        {checks.length === 0 ? (
          <Text size="sm">No check has been run for this manuscript.</Text>
        ) : (
          <Table verticalSpacing="xs">
            <Table.Tbody>
              {checks.map((check) => (
                <Table.Tr key={check.id}>
                  <Table.Td>{scoreBadge(check)}</Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {formatDateTime(check.completed_at ?? check.created_at)} · {check.provider}
                    </Text>
                    {check.error ? (
                      <Text size="sm" c="red">
                        {check.error}
                      </Text>
                    ) : null}
                  </Table.Td>
                  <Table.Td>
                    {check.status === "completed" && check.provider !== "fake" ? (
                      <Anchor
                        href={`/api/v1/submissions/${submission.id}/similarity-checks/${check.id}/report`}
                        target="_blank"
                        size="sm"
                      >
                        Open report
                      </Anchor>
                    ) : null}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Card>
  );
}

export function SubmissionDetailPage() {
  const id = Number(useParams().id);
  const [params] = useSearchParams();
  const submission = useSubmission(id);

  if (!submission.data) {
    return (
      <QueryState
        isPending={submission.isPending}
        error={submission.error}
        onRetry={() => submission.refetch()}
      />
    );
  }
  const data = submission.data;
  const look = statusLook(data);
  return (
    <Stack gap="lg">
      <PageHeader
        title={data.number ?? "Draft"}
        description={
          <Group gap="xs">
            <Badge color={look.color} variant="light">
              {look.label}
            </Badge>
            <Text size="sm" c="dimmed">
              {data.submitted_at
                ? `Submitted ${formatDateTime(data.submitted_at)} by ${data.submitter.full_name}`
                : `Started ${formatDateTime(data.created_at)}`}
            </Text>
          </Group>
        }
        actions={
          data.viewer.can_edit ? (
            <Button component={Link} to={`/submissions/${id}/edit`} leftSection={<IconPencil size={16} />}>
              Continue editing
            </Button>
          ) : null
        }
      />
      {params.get("submitted") && data.viewer.is_author ? (
        <Alert color="teal" icon={<IconCircleCheck />} title="Thank you, your manuscript has been submitted">
          Its number is <b>{data.number}</b>. We have sent you a confirmation by e-mail, and the editors have
          been notified. You will hear from the journal when there is a decision about peer review.
        </Alert>
      ) : null}
      {data.viewer.is_editor ? <SimilarityPanel submission={data} /> : null}
      <SubmissionSummaryCards submission={data} />
    </Stack>
  );
}
