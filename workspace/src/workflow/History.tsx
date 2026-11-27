import type { DecisionOut } from "@jps/api-client";
import { Accordion, Badge, Card, Group, Stack, Text, Timeline, Title } from "@mantine/core";
import { IconMail } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "../api";
import { QueryState } from "../components/common";
import { formatDateTime } from "../lib/format";
import { DECISION_LOOK, STAGE_LABELS } from "./labels";

function Letter({ decision }: { decision: DecisionOut }) {
  if (!decision.letter_body) return null;
  return (
    <Accordion variant="contained" mt={6}>
      <Accordion.Item value="letter">
        <Accordion.Control icon={<IconMail size={16} />}>
          <Text size="sm">{decision.letter_subject}</Text>
        </Accordion.Control>
        <Accordion.Panel>
          {decision.letter_to.length ? (
            <Text size="xs" c="dimmed" mb="xs">
              To: {decision.letter_to.join(", ")}
            </Text>
          ) : null}
          <Text size="sm" className="pre-wrap">
            {decision.letter_body}
          </Text>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}

/** Decisions on the manuscript, oldest first, with the letters sent. Authors see their letters. */
export function DecisionsList({ decisions, forAuthor }: { decisions: DecisionOut[]; forAuthor?: boolean }) {
  if (decisions.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        {forAuthor ? "No decisions yet." : "No decisions recorded yet."}
      </Text>
    );
  }
  return (
    <Timeline active={decisions.length - 1} bulletSize={18} lineWidth={2}>
      {decisions.map((decision) => (
        <Timeline.Item
          key={decision.id}
          color={DECISION_LOOK[decision.decision]?.color ?? "gray"}
          title={
            <Group gap="xs">
              <Text fw={600} size="sm">
                {decision.label}
              </Text>
              {decision.is_recommendation ? (
                <Badge size="xs" variant="light" color="gray">
                  Recommendation
                </Badge>
              ) : null}
              {decision.round_number ? (
                <Text size="xs" c="dimmed">
                  Round {decision.round_number}
                </Text>
              ) : null}
            </Group>
          }
        >
          <Text size="xs" c="dimmed">
            {formatDateTime(decision.created_at)}
            {decision.made_by ? ` · ${decision.made_by.full_name}` : ""}
            {decision.stage_after !== decision.stage_before
              ? ` · moved to ${STAGE_LABELS[decision.stage_after]}`
              : ""}
          </Text>
          {decision.reason ? (
            <Text size="sm" mt={4} className="pre-wrap">
              {decision.reason}
            </Text>
          ) : null}
          <Letter decision={decision} />
        </Timeline.Item>
      ))}
    </Timeline>
  );
}

const STATUS_COLOR: Record<string, string> = { sent: "teal", queued: "blue", failed: "red" };

/** Every e-mail sent about the manuscript. Editors only. */
export function EmailLog({ submissionId }: { submissionId: number }) {
  const log = useQuery({
    queryKey: ["email-log", submissionId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/submissions/{submission_id}/emails", {
          params: { path: { submission_id: submissionId } },
        }),
      ),
  });
  if (!log.data) {
    return <QueryState isPending={log.isPending} error={log.error} onRetry={() => log.refetch()} />;
  }
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={4}>E-mails</Title>
        {log.data.length === 0 ? (
          <Text size="sm" c="dimmed">
            No e-mails yet.
          </Text>
        ) : (
          <Accordion variant="separated">
            {log.data.map((email) => (
              <Accordion.Item key={email.id} value={String(email.id)}>
                <Accordion.Control>
                  <Group justify="space-between" wrap="nowrap" pr="sm">
                    <Stack gap={0}>
                      <Text size="sm" fw={500} lineClamp={1}>
                        {email.subject}
                      </Text>
                      <Text size="xs" c="dimmed">
                        To {email.recipient}
                        {email.sent_by ? ` · by ${email.sent_by}` : ""} · {formatDateTime(email.created_at)}
                      </Text>
                    </Stack>
                    <Badge size="xs" variant="light" color={STATUS_COLOR[email.status] ?? "gray"}>
                      {email.status}
                    </Badge>
                  </Group>
                </Accordion.Control>
                <Accordion.Panel>
                  <Text size="sm" className="pre-wrap">
                    {email.body}
                  </Text>
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
        )}
      </Stack>
    </Card>
  );
}
