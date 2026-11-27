import type { DiscussionOut, WorkflowOut } from "@jps/api-client";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  MultiSelect,
  Paper,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconLock, IconLockOpen, IconMessagePlus } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../api";
import { useSignedInUser } from "../auth";
import { QueryState } from "../components/common";
import { formatDateTime, initials } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { STAGE_LABELS } from "./labels";
import { workflowKey } from "./queries";

function NewDiscussionModal({
  submissionId,
  workflow,
  opened,
  onClose,
}: {
  submissionId: number;
  workflow: WorkflowOut;
  opened: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [people, setPeople] = useState<string[]>([]);
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/discussions", {
          params: { path: { submission_id: submissionId } },
          body: { subject, message, participant_ids: people.map(Number) },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
      notifySaved("Discussion started");
      setSubject("");
      setMessage("");
      setPeople([]);
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Start a discussion" size="lg">
      <Stack>
        <MultiSelect
          label="With"
          placeholder="Choose people"
          data={[
            {
              group: "Editors",
              items: workflow.people
                .filter((p) => p.role === "editor")
                .map((p) => ({ value: String(p.user.id), label: p.user.full_name })),
            },
            {
              group: "Authors",
              items: workflow.people
                .filter((p) => p.role === "author")
                .map((p) => ({ value: String(p.user.id), label: p.user.full_name })),
            },
          ]}
          value={people}
          onChange={setPeople}
          searchable
        />
        <TextInput label="Subject" value={subject} onChange={(e) => setSubject(e.currentTarget.value)} />
        <Textarea
          label="Message"
          autosize
          minRows={4}
          value={message}
          onChange={(e) => setMessage(e.currentTarget.value)}
        />
        <Text size="xs" c="dimmed">
          Everyone in the discussion is told by e-mail. The manuscript's editors can read every discussion.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!subject.trim() || !message.trim() || people.length === 0}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            Start
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DiscussionModal({
  submissionId,
  discussionId,
  onClose,
}: {
  submissionId: number;
  discussionId: number | null;
  onClose: () => void;
}) {
  const me = useSignedInUser();
  const queryClient = useQueryClient();
  const [reply, setReply] = useState("");
  const key = ["discussion", submissionId, discussionId];
  const discussion = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/submissions/{submission_id}/discussions/{discussion_id}", {
          // biome-ignore lint/style/noNonNullAssertion: enabled only with an id
          params: { path: { submission_id: submissionId, discussion_id: discussionId! } },
        }),
      ),
    enabled: discussionId !== null,
  });
  const store = (data: DiscussionOut) => {
    queryClient.setQueryData(key, data);
    queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
  };
  const post = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/discussions/{discussion_id}/messages", {
          // biome-ignore lint/style/noNonNullAssertion: the form is only shown with an id
          params: { path: { submission_id: submissionId, discussion_id: discussionId! } },
          body: { body: reply },
        }),
      ),
    onSuccess: (data) => {
      store(data);
      setReply("");
    },
    onError: (error) => showRequestError(error),
  });
  const toggle = useMutation({
    mutationFn: (closed: boolean) =>
      unwrap(
        api.PATCH("/api/v1/submissions/{submission_id}/discussions/{discussion_id}", {
          // biome-ignore lint/style/noNonNullAssertion: the button is only shown with an id
          params: { path: { submission_id: submissionId, discussion_id: discussionId! } },
          body: { is_closed: closed },
        }),
      ),
    onSuccess: store,
    onError: (error) => showRequestError(error),
  });
  const data = discussion.data;
  return (
    <Modal opened={discussionId !== null} onClose={onClose} title={data?.subject ?? "Discussion"} size="lg">
      {!data ? (
        <QueryState
          isPending={discussion.isPending}
          error={discussion.error}
          onRetry={() => discussion.refetch()}
        />
      ) : (
        <Stack>
          <Text size="xs" c="dimmed">
            {data.participants.map((p) => p.full_name).join(", ")}
          </Text>
          {data.messages.map((message) => {
            const mine = message.author?.id === me.user.id;
            return (
              <Paper
                key={message.id}
                withBorder
                p="sm"
                bg={mine ? "var(--mantine-color-indigo-0)" : undefined}
              >
                <Group gap="xs" mb={4}>
                  <Avatar size="sm" radius="xl" color="indigo">
                    {initials(message.author?.full_name ?? "?")}
                  </Avatar>
                  <Text size="sm" fw={500}>
                    {message.author?.full_name ?? "Former user"}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {formatDateTime(message.created_at)}
                  </Text>
                </Group>
                <Text size="sm" className="pre-wrap">
                  {message.body}
                </Text>
              </Paper>
            );
          })}
          {data.is_closed ? (
            <Text size="sm" c="dimmed">
              This discussion is closed.
            </Text>
          ) : (
            <>
              <Textarea
                placeholder="Write a reply"
                autosize
                minRows={3}
                value={reply}
                onChange={(e) => setReply(e.currentTarget.value)}
              />
              <Group justify="flex-end">
                <Button disabled={!reply.trim()} loading={post.isPending} onClick={() => post.mutate()}>
                  Reply
                </Button>
              </Group>
            </>
          )}
          <Group justify="flex-start">
            <Button
              size="xs"
              variant="subtle"
              color="gray"
              leftSection={data.is_closed ? <IconLockOpen size={14} /> : <IconLock size={14} />}
              loading={toggle.isPending}
              onClick={() => toggle.mutate(!data.is_closed)}
            >
              {data.is_closed ? "Reopen" : "Close the discussion"}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}

/** Conversations about the manuscript between its editors and authors. */
export function Discussions({ submissionId, workflow }: { submissionId: number; workflow: WorkflowOut }) {
  const [starting, setStarting] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>Discussions</Title>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconMessagePlus size={14} />}
            onClick={() => setStarting(true)}
          >
            Start a discussion
          </Button>
        </Group>
        {workflow.discussions.length === 0 ? (
          <Text size="sm" c="dimmed">
            No discussions yet.
          </Text>
        ) : null}
        {workflow.discussions.map((discussion) => (
          <UnstyledButton key={discussion.id} onClick={() => setOpen(discussion.id)}>
            <Paper withBorder p="sm">
              <Group justify="space-between" wrap="nowrap">
                <Stack gap={0}>
                  <Group gap="xs">
                    <Text size="sm" fw={600}>
                      {discussion.subject}
                    </Text>
                    {discussion.is_closed ? (
                      <Badge size="xs" color="gray" variant="light">
                        Closed
                      </Badge>
                    ) : null}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {discussion.participants.map((p) => p.full_name).join(", ")} ·{" "}
                    {STAGE_LABELS[discussion.stage]}
                  </Text>
                </Stack>
                <Stack gap={0} align="flex-end">
                  <Text size="xs">
                    {discussion.message_count} message{discussion.message_count === 1 ? "" : "s"}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {discussion.last_message_by}, {formatDateTime(discussion.last_message_at)}
                  </Text>
                </Stack>
              </Group>
            </Paper>
          </UnstyledButton>
        ))}
      </Stack>
      <NewDiscussionModal
        submissionId={submissionId}
        workflow={workflow}
        opened={starting}
        onClose={() => setStarting(false)}
      />
      <DiscussionModal submissionId={submissionId} discussionId={open} onClose={() => setOpen(null)} />
    </Card>
  );
}
