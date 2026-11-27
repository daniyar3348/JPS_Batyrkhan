import type { DecisionOption, SimilarityCheckOut, SubmissionOut, WorkflowOut } from "@jps/api-client";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  Stack,
  Stepper,
  Table,
  Tabs,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconBook,
  IconCircleCheck,
  IconEdit,
  IconFileText,
  IconHistory,
  IconMessages,
  IconPencil,
  IconReceipt,
  IconRefresh,
  IconUsersGroup,
} from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { FeePanel } from "../payments/FeePanel";
import { useBilling } from "../payments/queries";
import { PublicationPanel } from "../publishing/PublicationPanel";
import { AuthorReviews } from "../workflow/AuthorReviews";
import { DecisionModal } from "../workflow/DecisionModal";
import { Discussions } from "../workflow/Discussions";
import { DecisionsList, EmailLog } from "../workflow/History";
import { DECISION_LOOK, STAGE_LABELS, STAGES } from "../workflow/labels";
import { ParticipantsCard } from "../workflow/ParticipantsCard";
import { useWorkflow, workflowKey } from "../workflow/queries";
import { ReviewRounds } from "../workflow/ReviewRounds";
import { StageFilesCard } from "../workflow/StageFilesCard";
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

/** The four stages of the editorial process, with where the manuscript is now. */
function StageProgress({ workflow }: { workflow: WorkflowOut }) {
  const ended = workflow.status === "declined" || workflow.status === "withdrawn";
  return (
    <Stepper
      active={
        workflow.status === "published"
          ? STAGES.length
          : STAGES.indexOf(workflow.stage as (typeof STAGES)[number])
      }
      size="xs"
      color={ended ? "gray" : undefined}
    >
      {STAGES.map((stage) => (
        <Stepper.Step key={stage} label={STAGE_LABELS[stage]} />
      ))}
    </Stepper>
  );
}

const AFTER_ACCEPTANCE = new Set(["copyediting", "production"]);

/** Accepted and on its way to readers (or already with them). */
function isAccepted(workflow: WorkflowOut): boolean {
  return AFTER_ACCEPTANCE.has(workflow.stage) || ["scheduled", "published"].includes(workflow.status);
}

function inProduction(workflow: WorkflowOut): boolean {
  return workflow.stage === "production" || ["scheduled", "published"].includes(workflow.status);
}

/** Copyediting and production files, for everyone who works on them. */
function StageFiles({ submissionId, workflow }: { submissionId: number; workflow: WorkflowOut }) {
  return (
    <Stack gap="lg">
      <StageFilesCard submissionId={submissionId} workflow={workflow} stage="copyedit" />
      {inProduction(workflow) && !workflow.viewer.is_author ? (
        <StageFilesCard submissionId={submissionId} workflow={workflow} stage="production" />
      ) : null}
    </Stack>
  );
}

function DecisionBar({
  options,
  onChoose,
}: {
  options: DecisionOption[];
  onChoose: (option: DecisionOption) => void;
}) {
  if (options.length === 0) return null;
  return (
    <Card withBorder padding="sm">
      <Group gap="xs">
        <Text size="sm" fw={600} mr="xs">
          {options[0]?.is_recommendation ? "Recommend:" : "Decision:"}
        </Text>
        {options.map((option) => {
          const look = DECISION_LOOK[option.decision] ?? { color: "gray", variant: "light" as const };
          return (
            <Button
              key={option.decision}
              size="sm"
              color={look.color}
              variant={look.variant}
              title={option.description}
              onClick={() => onChoose(option)}
            >
              {option.label}
            </Button>
          );
        })}
      </Group>
    </Card>
  );
}

/** What is happening with the manuscript, in the authors' terms, and what they need to do. */
function AuthorStatus({ workflow, onOpenReviews }: { workflow: WorkflowOut; onOpenReviews: () => void }) {
  const latest = workflow.rounds[workflow.rounds.length - 1];
  let title: string;
  let text: string;
  let color = "blue";
  let action = false;
  if (workflow.status === "declined") {
    [title, text, color] = [
      "Declined",
      "The editors have declined the manuscript. Their letter is under Reviews and decisions.",
      "red",
    ];
  } else if (workflow.status === "withdrawn") {
    [title, text, color] = ["Withdrawn", "You have withdrawn the manuscript.", "gray"];
  } else if (workflow.stage === "submission") {
    [title, text] = [
      "With the editors",
      "The editors are checking your manuscript before deciding whether to send it for review.",
    ];
  } else if (workflow.stage === "review" && latest) {
    if (latest.status === "revisions_requested" || latest.status === "resubmit_requested") {
      [title, text, color, action] = [
        "Revisions requested",
        "The editor has asked you to revise the manuscript. Read the reviews and send your revision.",
        "orange",
        true,
      ];
    } else if (latest.status === "revisions_submitted") {
      [title, text, color] = ["Revision sent", "The editors have your revised manuscript.", "teal"];
    } else {
      [title, text] = [
        `Under review (round ${latest.number})`,
        "Reviewers are reading your manuscript. We will write when there is a decision.",
      ];
    }
  } else if (workflow.status === "published") {
    [title, text, color] = [
      "Published",
      "Your article has been published. Thank you for publishing with us.",
      "green",
    ];
  } else if (workflow.status === "scheduled") {
    [title, text, color] = [
      "Scheduled for publication",
      "Your article will appear when its issue is published.",
      "teal",
    ];
  } else if (workflow.stage === "production") {
    [title, text, color] = [
      "In production",
      "Your article is being typeset. The editors may ask you to check the proofs in a discussion.",
      "teal",
    ];
  } else if (workflow.stage === "copyediting") {
    [title, text, color] = [
      "Accepted: copyediting",
      "The copyeditor is preparing the text. Their questions and versions of the text come under Copyediting.",
      "teal",
    ];
  } else {
    [title, text, color] = [
      "Accepted",
      "Your manuscript has been accepted. We will contact you about copyediting and proofs.",
      "teal",
    ];
  }
  return (
    <Alert color={color} title={title} icon={color === "teal" ? <IconCircleCheck /> : <IconAlertCircle />}>
      <Stack gap="xs" align="flex-start">
        <Text size="sm">{text}</Text>
        {action ? (
          <Button size="xs" color="orange" onClick={onOpenReviews}>
            Read the reviews and revise
          </Button>
        ) : null}
      </Stack>
    </Alert>
  );
}

function WithdrawButton({ submissionId }: { submissionId: number }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const withdraw = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/withdraw", {
          params: { path: { submission_id: submissionId } },
          body: { reason },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(workflowKey(submissionId), data);
      queryClient.invalidateQueries({ queryKey: submissionKey(submissionId) });
      queryClient.invalidateQueries({ queryKey: ["submissions"] });
      notifySaved("The manuscript has been withdrawn");
      setOpen(false);
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <>
      <Button variant="subtle" color="red" onClick={() => setOpen(true)}>
        Withdraw
      </Button>
      <Modal opened={open} onClose={() => setOpen(false)} title="Withdraw the manuscript?">
        <Stack>
          <Text size="sm">
            The editors and any reviewers will be told. This cannot be undone here; to submit again you would
            start a new submission.
          </Text>
          <Textarea
            label="Reason"
            required
            autosize
            minRows={3}
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpen(false)}>
              Keep it
            </Button>
            <Button
              color="red"
              disabled={!reason.trim()}
              loading={withdraw.isPending}
              onClick={() => withdraw.mutate()}
            >
              Withdraw
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

function EditorView({ data, workflow }: { data: SubmissionOut; workflow: WorkflowOut }) {
  const [params, setParams] = useSearchParams();
  const [deciding, setDeciding] = useState<DecisionOption | null>(null);
  const tab = params.get("tab") ?? "overview";
  const reviewing = workflow.rounds
    .flatMap((r) => r.assignments ?? [])
    .filter((a) => a.status === "accepted").length;
  return (
    <Stack gap="lg">
      <DecisionBar options={workflow.available_decisions} onChoose={setDeciding} />
      {workflow.fee_settled !== null ? (
        <Group gap="xs">
          <Text size="sm" c="dimmed">
            Publication fee:
          </Text>
          <Badge color={workflow.fee_settled ? "teal" : "orange"} variant="light">
            {workflow.fee_settled ? "Settled — can be published" : "Not settled yet — cannot be published"}
          </Badge>
        </Group>
      ) : null}
      <Tabs value={tab} onChange={(value) => setParams({ tab: value ?? "overview" }, { replace: true })}>
        <Tabs.List>
          <Tabs.Tab value="overview" leftSection={<IconFileText size={16} />}>
            Manuscript
          </Tabs.Tab>
          <Tabs.Tab value="review" leftSection={<IconUsersGroup size={16} />}>
            Review{workflow.rounds.length ? ` · round ${workflow.rounds.length}` : ""}
            {reviewing ? ` (${reviewing} reviewing)` : ""}
          </Tabs.Tab>
          {isAccepted(workflow) ? (
            <Tabs.Tab value="copyediting" leftSection={<IconEdit size={16} />}>
              Copyediting and production
            </Tabs.Tab>
          ) : null}
          {inProduction(workflow) ? (
            <Tabs.Tab value="publication" leftSection={<IconBook size={16} />}>
              Publication
            </Tabs.Tab>
          ) : null}
          <Tabs.Tab value="discussions" leftSection={<IconMessages size={16} />}>
            Discussions{workflow.discussions.length ? ` (${workflow.discussions.length})` : ""}
          </Tabs.Tab>
          <Tabs.Tab value="history" leftSection={<IconHistory size={16} />}>
            History
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview" pt="lg">
          <Stack gap="lg">
            <ParticipantsCard submissionId={data.id} workflow={workflow} />
            <SimilarityPanel submission={data} />
            <SubmissionSummaryCards submission={data} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="review" pt="lg">
          <ReviewRounds submissionId={data.id} workflow={workflow} />
        </Tabs.Panel>
        <Tabs.Panel value="copyediting" pt="lg">
          {tab === "copyediting" ? <StageFiles submissionId={data.id} workflow={workflow} /> : null}
        </Tabs.Panel>
        <Tabs.Panel value="publication" pt="lg">
          {tab === "publication" ? <PublicationPanel submissionId={data.id} /> : null}
        </Tabs.Panel>
        <Tabs.Panel value="discussions" pt="lg">
          <Discussions submissionId={data.id} workflow={workflow} />
        </Tabs.Panel>
        <Tabs.Panel value="history" pt="lg">
          <Stack gap="lg">
            <Card withBorder padding="lg">
              <Stack gap="sm">
                <Title order={4}>Decisions</Title>
                <DecisionsList decisions={workflow.decisions} />
              </Stack>
            </Card>
            {tab === "history" ? <EmailLog submissionId={data.id} /> : null}
          </Stack>
        </Tabs.Panel>
      </Tabs>
      <DecisionModal submissionId={data.id} option={deciding} onClose={() => setDeciding(null)} />
    </Stack>
  );
}

function AuthorView({ data, workflow }: { data: SubmissionOut; workflow: WorkflowOut }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const select = (value: string | null) => setParams({ tab: value ?? "overview" }, { replace: true });
  const billing = useBilling(data.id);
  return (
    <Stack gap="lg">
      <AuthorStatus workflow={workflow} onOpenReviews={() => select("reviews")} />
      <Tabs value={tab} onChange={select}>
        <Tabs.List>
          <Tabs.Tab value="overview" leftSection={<IconFileText size={16} />}>
            Manuscript
          </Tabs.Tab>
          <Tabs.Tab value="reviews" leftSection={<IconUsersGroup size={16} />}>
            Reviews and decisions
          </Tabs.Tab>
          {isAccepted(workflow) ? (
            <Tabs.Tab value="copyediting" leftSection={<IconEdit size={16} />}>
              Copyediting
            </Tabs.Tab>
          ) : null}
          <Tabs.Tab value="discussions" leftSection={<IconMessages size={16} />}>
            Discussions{workflow.discussions.length ? ` (${workflow.discussions.length})` : ""}
          </Tabs.Tab>
          {billing.data?.enabled ? (
            <Tabs.Tab value="fee" leftSection={<IconReceipt size={16} />}>
              Publication fee
              {billing.data.invoices.some((i) => i.status === "issued") ? (
                <Badge ml={6} size="xs" color="orange" variant="filled" circle>
                  1
                </Badge>
              ) : null}
            </Tabs.Tab>
          ) : null}
        </Tabs.List>
        <Tabs.Panel value="overview" pt="lg">
          <SubmissionSummaryCards submission={data} />
        </Tabs.Panel>
        <Tabs.Panel value="fee" pt="lg">
          {tab === "fee" ? <FeePanel submissionId={data.id} /> : null}
        </Tabs.Panel>
        <Tabs.Panel value="copyediting" pt="lg">
          {tab === "copyediting" ? <StageFiles submissionId={data.id} workflow={workflow} /> : null}
        </Tabs.Panel>
        <Tabs.Panel value="reviews" pt="lg">
          <Stack gap="lg">
            <AuthorReviews submissionId={data.id} workflow={workflow} />
            <Card withBorder padding="lg">
              <Stack gap="sm">
                <Title order={4}>Decisions and letters</Title>
                <DecisionsList decisions={workflow.decisions} forAuthor />
              </Stack>
            </Card>
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="discussions" pt="lg">
          <Discussions submissionId={data.id} workflow={workflow} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

/** Copyeditors, layout editors and proofreaders: the accepted article, its files, and the discussions. */
function ProductionView({ data, workflow }: { data: SubmissionOut; workflow: WorkflowOut }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "files";
  return (
    <Tabs value={tab} onChange={(value) => setParams({ tab: value ?? "files" }, { replace: true })}>
      <Tabs.List>
        <Tabs.Tab value="files" leftSection={<IconEdit size={16} />}>
          Files
        </Tabs.Tab>
        {inProduction(workflow) ? (
          <Tabs.Tab value="publication" leftSection={<IconBook size={16} />}>
            Publication
          </Tabs.Tab>
        ) : null}
        <Tabs.Tab value="overview" leftSection={<IconFileText size={16} />}>
          Manuscript
        </Tabs.Tab>
        <Tabs.Tab value="discussions" leftSection={<IconMessages size={16} />}>
          Discussions{workflow.discussions.length ? ` (${workflow.discussions.length})` : ""}
        </Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="files" pt="lg">
        {tab === "files" ? <StageFiles submissionId={data.id} workflow={workflow} /> : null}
      </Tabs.Panel>
      <Tabs.Panel value="publication" pt="lg">
        {tab === "publication" ? <PublicationPanel submissionId={data.id} /> : null}
      </Tabs.Panel>
      <Tabs.Panel value="overview" pt="lg">
        <Stack gap="lg">
          <ParticipantsCard submissionId={data.id} workflow={workflow} />
          <SubmissionSummaryCards submission={data} />
        </Stack>
      </Tabs.Panel>
      <Tabs.Panel value="discussions" pt="lg">
        <Discussions submissionId={data.id} workflow={workflow} />
      </Tabs.Panel>
    </Tabs>
  );
}

export function SubmissionDetailPage() {
  const id = Number(useParams().id);
  const [params] = useSearchParams();
  const submission = useSubmission(id);
  const submitted = !!submission.data && submission.data.status !== "draft";
  const workflow = useWorkflow(id, submitted);

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
          ) : workflow.data?.can_withdraw ? (
            <WithdrawButton submissionId={id} />
          ) : null
        }
      />
      {params.get("submitted") && data.viewer.is_author ? (
        <Alert color="teal" icon={<IconCircleCheck />} title="Thank you, your manuscript has been submitted">
          Its number is <b>{data.number}</b>. We have sent you a confirmation by e-mail, and the editors have
          been notified. You will hear from the journal when there is a decision about peer review.
        </Alert>
      ) : null}
      {!submitted ? (
        <SubmissionSummaryCards submission={data} />
      ) : !workflow.data ? (
        <QueryState
          isPending={workflow.isPending}
          error={workflow.error}
          onRetry={() => workflow.refetch()}
        />
      ) : (
        <>
          <StageProgress workflow={workflow.data} />
          {data.viewer.is_editor ? (
            <EditorView data={data} workflow={workflow.data} />
          ) : data.viewer.is_author ? (
            <AuthorView data={data} workflow={workflow.data} />
          ) : (
            <ProductionView data={data} workflow={workflow.data} />
          )}
        </>
      )}
    </Stack>
  );
}
