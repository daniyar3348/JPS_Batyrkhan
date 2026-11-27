import type { AnnouncementIn, AnnouncementOut } from "@jps/api-client";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { MarkdownField } from "./MarkdownField";
import { announcementsKey, useAnnouncements } from "./queries";

type Editing = { item: AnnouncementOut | null } | null;

function AnnouncementModal({ item, onClose }: { item: AnnouncementOut | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const form = useForm<AnnouncementIn>({
    initialValues: {
      title: item?.title ?? "",
      summary: item?.summary ?? "",
      body: item?.body ?? "",
      published: item ? item.published_at !== null : false,
    },
    validate: { title: (value) => (value.trim() ? null : "Give the announcement a title") },
  });
  const save = useMutation({
    mutationFn: (values: AnnouncementIn) => {
      const body = { ...values, title: values.title.trim(), summary: values.summary.trim() };
      return item
        ? unwrap(
            api.PUT("/api/v1/site/announcements/{announcement_id}", {
              params: {
                path: { announcement_id: item.id },
                header: { "if-match": `"${item.row_version}"` },
              },
              body,
            }),
          )
        : unwrap(api.POST("/api/v1/site/announcements", { body }));
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: announcementsKey });
      notifySaved(saved.published_at ? "Announcement published" : "Draft saved");
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed this announcement",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: announcementsKey });
        onClose();
        return;
      }
      showRequestError(error, form);
    },
  });
  return (
    <Modal opened onClose={onClose} title={item ? "Edit announcement" : "New announcement"} size="xl">
      <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
        <Stack>
          <TextInput label="Title" required {...form.getInputProps("title")} />
          <Textarea
            label="Summary"
            description="One or two sentences for the home page and the news feed."
            autosize
            minRows={2}
            {...form.getInputProps("summary")}
          />
          <MarkdownField
            label="Text"
            value={form.values.body}
            onChange={(value) => form.setFieldValue("body", value)}
            minRows={8}
          />
          <Switch
            label="Published"
            description={
              item?.published_at
                ? `Published ${formatDate(item.published_at)}. Turn off to take it off the site.`
                : "Off: saved as a draft, not shown on the site."
            }
            {...form.getInputProps("published", { type: "checkbox" })}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

/** News on the journal's site: calls for papers, new issues, changes in policy. */
export function AnnouncementsPage() {
  const queryClient = useQueryClient();
  const announcements = useAnnouncements();
  const [editing, setEditing] = useState<Editing>(null);
  const remove = useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.DELETE("/api/v1/site/announcements/{announcement_id}", {
          params: { path: { announcement_id: id } },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: announcementsKey });
      notifySaved("Announcement deleted");
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Stack>
      <PageHeader
        title="Announcements"
        description="News on the journal's site: calls for papers, new issues, changes in policy."
        actions={
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing({ item: null })}>
            New announcement
          </Button>
        }
      />
      {announcements.data ? (
        announcements.data.length === 0 ? (
          <Text c="dimmed">No announcements yet.</Text>
        ) : (
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={560}>
              <Table verticalSpacing="sm" horizontalSpacing="md">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Title</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th aria-label="Actions" />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {announcements.data.map((item) => (
                    <Table.Tr key={item.id}>
                      <Table.Td>
                        <Text size="sm" fw={500}>
                          {item.title}
                        </Text>
                        {item.summary ? (
                          <Text size="xs" c="dimmed" lineClamp={1}>
                            {item.summary}
                          </Text>
                        ) : null}
                      </Table.Td>
                      <Table.Td>
                        {item.published_at ? (
                          <Badge variant="light" color="green">
                            Published {formatDate(item.published_at)}
                          </Badge>
                        ) : (
                          <Badge variant="light" color="gray">
                            Draft
                          </Badge>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} justify="flex-end" wrap="nowrap">
                          <Tooltip label="Edit">
                            <ActionIcon
                              variant="subtle"
                              aria-label={`Edit ${item.title}`}
                              onClick={() => setEditing({ item })}
                            >
                              <IconPencil size={16} />
                            </ActionIcon>
                          </Tooltip>
                          <Tooltip label="Delete">
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              aria-label={`Delete ${item.title}`}
                              onClick={() =>
                                modals.openConfirmModal({
                                  title: `Delete “${item.title}”?`,
                                  children: "The announcement is removed from the site for good.",
                                  labels: { confirm: "Delete", cancel: "Cancel" },
                                  confirmProps: { color: "red" },
                                  onConfirm: () => remove.mutate(item.id),
                                })
                              }
                            >
                              <IconTrash size={16} />
                            </ActionIcon>
                          </Tooltip>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        )
      ) : (
        <QueryState
          isPending={announcements.isPending}
          error={announcements.error}
          onRetry={() => announcements.refetch()}
        />
      )}
      {editing ? <AnnouncementModal item={editing.item} onClose={() => setEditing(null)} /> : null}
    </Stack>
  );
}
