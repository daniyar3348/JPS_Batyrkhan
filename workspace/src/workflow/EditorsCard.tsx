import type { WorkflowOut } from "@jps/api-client";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Switch,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { IconUserMinus, IconUserPlus } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../api";
import { notifySaved, showRequestError } from "../lib/forms";
import { workflowKey } from "./queries";

/** Who handles the manuscript. Deciding editors can add and remove editors. */
export function EditorsCard({ submissionId, workflow }: { submissionId: number; workflow: WorkflowOut }) {
  const queryClient = useQueryClient();
  const canChange = workflow.viewer.can_decide;
  const [adding, setAdding] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [recommendOnly, setRecommendOnly] = useState(false);
  const path = { params: { path: { submission_id: submissionId } } };

  const candidates = useQuery({
    queryKey: ["editor-candidates", submissionId],
    queryFn: () => unwrap(api.GET("/api/v1/submissions/{submission_id}/editor-candidates", path)),
    enabled: adding,
  });

  const store = (data: WorkflowOut) => {
    queryClient.setQueryData(workflowKey(submissionId), data);
    queryClient.invalidateQueries({ queryKey: ["editor-candidates", submissionId] });
  };

  const assign = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/editors", {
          ...path,
          body: { user_id: Number(userId), recommend_only: recommendOnly, notify: true },
        }),
      ),
    onSuccess: (data) => {
      store(data);
      notifySaved("Editor assigned");
      setAdding(false);
      setUserId(null);
      setRecommendOnly(false);
    },
    onError: (error) => showRequestError(error),
  });

  const remove = useMutation({
    mutationFn: (user: number) =>
      unwrap(
        api.DELETE("/api/v1/submissions/{submission_id}/editors/{user_id}", {
          params: { path: { submission_id: submissionId, user_id: user } },
        }),
      ),
    onSuccess: (data) => {
      store(data);
      notifySaved("Editor removed");
    },
    onError: (error) => showRequestError(error),
  });

  const editors = workflow.editors ?? [];
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>Editors</Title>
          {canChange && !adding ? (
            <Button
              size="xs"
              variant="light"
              leftSection={<IconUserPlus size={14} />}
              onClick={() => setAdding(true)}
            >
              Assign editor
            </Button>
          ) : null}
        </Group>
        {editors.length === 0 ? (
          <Text size="sm" c="dimmed">
            Nobody is assigned yet. The editor-in-chief handles the manuscript.
          </Text>
        ) : null}
        {editors.map((editor) => (
          <Group key={editor.user.id} justify="space-between" wrap="nowrap">
            <div>
              <Text size="sm" fw={500}>
                {editor.user.full_name}
                {editor.recommend_only ? (
                  <Badge ml="xs" size="xs" variant="light" color="gray">
                    Recommends only
                  </Badge>
                ) : null}
              </Text>
              <Text size="xs" c="dimmed">
                {editor.user.email}
              </Text>
            </div>
            {canChange ? (
              <Tooltip label="Remove">
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label={`Remove ${editor.user.full_name}`}
                  onClick={() =>
                    modals.openConfirmModal({
                      title: `Remove ${editor.user.full_name}?`,
                      children: "They will no longer handle this manuscript.",
                      labels: { confirm: "Remove", cancel: "Cancel" },
                      confirmProps: { color: "red" },
                      onConfirm: () => remove.mutate(editor.user.id),
                    })
                  }
                >
                  <IconUserMinus size={16} />
                </ActionIcon>
              </Tooltip>
            ) : null}
          </Group>
        ))}
        {adding ? (
          <Stack gap="xs">
            <Select
              label="Editor"
              placeholder="Choose an editor"
              searchable
              data={(candidates.data ?? []).map((user) => ({
                value: String(user.id),
                label: `${user.full_name} (${user.email})`,
              }))}
              value={userId}
              onChange={setUserId}
              nothingFoundMessage={candidates.isPending ? "Loading…" : "No other editors"}
            />
            <Switch
              label="May only recommend a decision"
              checked={recommendOnly}
              onChange={(event) => setRecommendOnly(event.currentTarget.checked)}
            />
            <Group justify="flex-end" gap="xs">
              <Button size="xs" variant="default" onClick={() => setAdding(false)}>
                Cancel
              </Button>
              <Button size="xs" disabled={!userId} loading={assign.isPending} onClick={() => assign.mutate()}>
                Assign
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Stack>
    </Card>
  );
}
