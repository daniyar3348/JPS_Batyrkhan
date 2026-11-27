import type { ReviewerTask } from "@jps/api-client";
import { Anchor, Badge, Card, Group, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate } from "../lib/format";
import { ASSIGNMENT_STATUS, METHOD_LABELS } from "../workflow/labels";

export const reviewsKey = ["reviews"] as const;

const GROUPS: { title: string; statuses: string[]; empty: string }[] = [
  {
    title: "Waiting for your answer",
    statuses: ["invited"],
    empty: "No new review requests.",
  },
  { title: "In progress", statuses: ["accepted"], empty: "No reviews in progress." },
  { title: "Finished", statuses: ["completed", "declined"], empty: "Nothing here yet." },
];

function DueDate({ task }: { task: ReviewerTask }) {
  if (task.status === "invited") {
    return <Text size="sm">Please answer by {formatDate(task.response_due)}</Text>;
  }
  if (task.status === "accepted") {
    return <Text size="sm">Review due {formatDate(task.review_due)}</Text>;
  }
  if (task.status === "completed") {
    return (
      <Text size="sm" c="dimmed">
        Sent {formatDate(task.completed_at)}
      </Text>
    );
  }
  return null;
}

function TaskCard({ task }: { task: ReviewerTask }) {
  const look = ASSIGNMENT_STATUS[task.status] ?? { label: task.status, color: "gray" };
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4} style={{ minWidth: 0 }}>
          <Anchor component={Link} to={`/reviews/${task.id}`} fw={600} lineClamp={2}>
            {task.title || "Untitled manuscript"}
          </Anchor>
          <Text size="xs" c="dimmed">
            Round {task.round_number} · {METHOD_LABELS[task.method] ?? task.method} review · Invited{" "}
            {formatDate(task.invited_at)}
          </Text>
          <DueDate task={task} />
        </Stack>
        <Stack gap={6} align="flex-end">
          <Badge color={look.color} variant="light">
            {look.label}
          </Badge>
          {task.overdue ? (
            <Badge color="red" variant="filled">
              Overdue
            </Badge>
          ) : null}
        </Stack>
      </Group>
    </Card>
  );
}

export function MyReviewsPage() {
  const tasks = useQuery({
    queryKey: reviewsKey,
    queryFn: () => unwrap(api.GET("/api/v1/reviews")),
  });

  return (
    <Stack gap="lg">
      <PageHeader
        title="My reviews"
        description="Manuscripts the journal has asked you to review. Thank you for your help."
      />
      {tasks.data ? (
        tasks.data.length === 0 ? (
          <Text c="dimmed">You have no review requests yet.</Text>
        ) : (
          GROUPS.map((group) => {
            const items = tasks.data.filter((task) => group.statuses.includes(task.status));
            return (
              <Stack key={group.title} gap="sm">
                <Title order={4}>
                  {group.title}
                  {items.length ? (
                    <Text span c="dimmed" fw={400} ml="xs">
                      {items.length}
                    </Text>
                  ) : null}
                </Title>
                {items.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    {group.empty}
                  </Text>
                ) : (
                  items.map((task) => <TaskCard key={task.id} task={task} />)
                )}
              </Stack>
            );
          })
        )
      ) : (
        <QueryState isPending={tasks.isPending} error={tasks.error} onRetry={() => tasks.refetch()} />
      )}
    </Stack>
  );
}
