import type { EditorOut, WorkflowOut } from "@jps/api-client";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
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
import { PARTICIPANT_LABELS, PARTICIPANT_ROLES, type ParticipantRole } from "./labels";
import { workflowKey } from "./queries";

const AFTER_ACCEPTANCE = new Set(["copyediting", "production"]);

/** Assign one person to a role. Editors need a deciding editor; the other roles any editor of the manuscript. */
function AssignForm({
  submissionId,
  role,
  onDone,
}: {
  submissionId: number;
  role: ParticipantRole;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState<string | null>(null);
  const [recommendOnly, setRecommendOnly] = useState(false);
  const candidates = useQuery({
    queryKey: ["participant-candidates", submissionId, role],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/submissions/{submission_id}/participant-candidates", {
          params: { path: { submission_id: submissionId }, query: { role } },
        }),
      ),
  });
  const assign = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/participants", {
          params: { path: { submission_id: submissionId } },
          body: {
            user_id: Number(userId),
            role,
            recommend_only: role === "editor" && recommendOnly,
            notify: true,
          },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(workflowKey(submissionId), data);
      queryClient.invalidateQueries({ queryKey: ["participant-candidates", submissionId] });
      notifySaved(`${PARTICIPANT_LABELS[role].one} assigned`);
      onDone();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Stack gap="xs">
      <Select
        label={PARTICIPANT_LABELS[role].one}
        placeholder="Choose a person"
        searchable
        data={(candidates.data ?? []).map((user) => ({
          value: String(user.id),
          label: `${user.full_name} (${user.email})`,
        }))}
        value={userId}
        onChange={setUserId}
        nothingFoundMessage={
          candidates.isPending
            ? "Loading…"
            : `Nobody else has the ${PARTICIPANT_LABELS[role].one.toLowerCase()} role. Give it under Users and roles.`
        }
      />
      {role === "editor" ? (
        <Switch
          label="May only recommend a decision"
          checked={recommendOnly}
          onChange={(event) => setRecommendOnly(event.currentTarget.checked)}
        />
      ) : null}
      <Group justify="flex-end" gap="xs">
        <Button size="xs" variant="default" onClick={onDone}>
          Cancel
        </Button>
        <Button size="xs" disabled={!userId} loading={assign.isPending} onClick={() => assign.mutate()}>
          Assign
        </Button>
      </Group>
    </Stack>
  );
}

function PersonRow({
  person,
  canRemove,
  onRemove,
}: {
  person: EditorOut;
  canRemove: boolean;
  onRemove: () => void;
}) {
  return (
    <Group justify="space-between" wrap="nowrap">
      <div>
        <Text size="sm" fw={500}>
          {person.user.full_name}
          {person.recommend_only ? (
            <Badge ml="xs" size="xs" variant="light" color="gray">
              Recommends only
            </Badge>
          ) : null}
        </Text>
        <Text size="xs" c="dimmed">
          {person.user.email}
        </Text>
      </div>
      {canRemove ? (
        <Tooltip label="Remove">
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label={`Remove ${person.user.full_name}`}
            onClick={() =>
              modals.openConfirmModal({
                title: `Remove ${person.user.full_name}?`,
                children: "They will no longer work on this manuscript.",
                labels: { confirm: "Remove", cancel: "Cancel" },
                confirmProps: { color: "red" },
                onConfirm: onRemove,
              })
            }
          >
            <IconUserMinus size={16} />
          </ActionIcon>
        </Tooltip>
      ) : null}
    </Group>
  );
}

/**
 * Who works on the manuscript. Editors are assigned by deciding editors; after acceptance, any editor of
 * the manuscript assigns the copyeditor, layout editor and proofreader.
 */
export function ParticipantsCard({
  submissionId,
  workflow,
}: {
  submissionId: number;
  workflow: WorkflowOut;
}) {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState<ParticipantRole | null>(null);
  const people = workflow.editors ?? [];
  const accepted =
    AFTER_ACCEPTANCE.has(workflow.stage) || ["scheduled", "published"].includes(workflow.status);
  const roles = PARTICIPANT_ROLES.filter(
    (role) => role === "editor" || accepted || people.some((p) => p.role === role),
  );
  const mayAssign = (role: ParticipantRole) =>
    role === "editor" ? workflow.viewer.can_decide : workflow.viewer.can_manage;

  const remove = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: ParticipantRole }) =>
      unwrap(
        api.DELETE("/api/v1/submissions/{submission_id}/participants/{role}/{user_id}", {
          params: { path: { submission_id: submissionId, user_id: userId, role } },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(workflowKey(submissionId), data);
      notifySaved("Removed");
    },
    onError: (error) => showRequestError(error),
  });

  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={4}>People</Title>
        {roles.map((role, index) => {
          const assigned = people.filter((p) => p.role === role);
          return (
            <Stack key={role} gap="xs">
              {index > 0 ? <Divider /> : null}
              <Group justify="space-between">
                <div>
                  <Text size="sm" fw={600}>
                    {PARTICIPANT_LABELS[role].many}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {PARTICIPANT_LABELS[role].help}
                  </Text>
                </div>
                {mayAssign(role) && adding !== role ? (
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<IconUserPlus size={14} />}
                    onClick={() => setAdding(role)}
                  >
                    Assign
                  </Button>
                ) : null}
              </Group>
              {assigned.length === 0 ? (
                <Text size="sm" c="dimmed">
                  {role === "editor"
                    ? "Nobody is assigned yet. The editor-in-chief handles the manuscript."
                    : "Nobody is assigned."}
                </Text>
              ) : null}
              {assigned.map((person) => (
                <PersonRow
                  key={`${role}-${person.user.id}`}
                  person={person}
                  canRemove={mayAssign(role)}
                  onRemove={() => remove.mutate({ userId: person.user.id, role })}
                />
              ))}
              {adding === role ? (
                <AssignForm submissionId={submissionId} role={role} onDone={() => setAdding(null)} />
              ) : null}
            </Stack>
          );
        })}
      </Stack>
    </Card>
  );
}
