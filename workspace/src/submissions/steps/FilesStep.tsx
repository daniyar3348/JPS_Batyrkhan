import type { FileOut, Genre, SubmissionOut, SubmissionSettingsOut } from "@jps/api-client";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { modals } from "@mantine/modals";
import { IconDownload, IconFileUpload, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorMessage, unwrap } from "../../api";
import { showRequestError } from "../../lib/forms";
import { FILE_STATUS, formatSize, GENRE_HELP, GENRE_LABELS } from "../labels";
import { submissionKey } from "../queries";
import { sendToStorage } from "../upload";

interface Upload {
  id: string;
  name: string;
  progress: number;
  error?: string;
}

const GENRES = Object.keys(GENRE_LABELS) as Genre[];

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}

export function FilesStep({
  submission,
  settings,
  onDone,
  onBack,
}: {
  submission: SubmissionOut;
  settings: SubmissionSettingsOut;
  onDone: () => void;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const hasManuscript = submission.files.some((f) => f.genre === "manuscript" && f.status !== "rejected");
  const [genre, setGenre] = useState<Genre>(hasManuscript ? "supplementary" : "manuscript");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const allowed = settings.allowed_file_types[genre] ?? [];
  const refresh = () => queryClient.invalidateQueries({ queryKey: submissionKey(submission.id) });

  const patch = (id: string, change: Partial<Upload>) =>
    setUploads((current) => current.map((u) => (u.id === id ? { ...u, ...change } : u)));

  async function uploadOne(file: File, kind: Genre) {
    const id = `${file.name}-${Date.now()}-${Math.random()}`;
    setUploads((current) => [...current, { id, name: file.name, progress: 0 }]);
    try {
      if (!(settings.allowed_file_types[kind] ?? []).includes(extension(file.name))) {
        throw new Error(
          `${GENRE_LABELS[kind]} files must be: ${(settings.allowed_file_types[kind] ?? []).join(", ")}`,
        );
      }
      const ticket = await unwrap(
        api.POST("/api/v1/submissions/{submission_id}/files/uploads", {
          params: { path: { submission_id: submission.id } },
          body: { file_name: file.name, size: file.size, genre: kind },
        }),
      );
      await sendToStorage(ticket.upload, file, (fraction) => patch(id, { progress: fraction }));
      await unwrap(
        api.POST("/api/v1/submissions/{submission_id}/files/{file_id}/complete", {
          params: { path: { submission_id: submission.id, file_id: ticket.file.id } },
        }),
      );
      setUploads((current) => current.filter((u) => u.id !== id));
    } catch (error) {
      patch(id, { error: errorMessage(error) });
    } finally {
      await refresh();
    }
  }

  const update = useMutation({
    mutationFn: ({ file, genre }: { file: FileOut; genre: Genre }) =>
      unwrap(
        api.PATCH("/api/v1/submissions/{submission_id}/files/{file_id}", {
          params: { path: { submission_id: submission.id, file_id: file.id } },
          body: { genre },
        }),
      ),
    onSettled: refresh,
    onError: (error) => showRequestError(error),
  });

  const remove = useMutation({
    mutationFn: (file: FileOut) =>
      unwrap(
        api.DELETE("/api/v1/submissions/{submission_id}/files/{file_id}", {
          params: { path: { submission_id: submission.id, file_id: file.id } },
        }),
      ),
    onSettled: refresh,
    onError: (error) => showRequestError(error),
  });

  const confirmRemove = (file: FileOut) =>
    modals.openConfirmModal({
      title: `Remove “${file.name}”?`,
      labels: { confirm: "Remove", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(file),
    });

  const busy = uploads.some((u) => !u.error) || submission.files.some((f) => f.status === "processing");

  return (
    <Stack gap="lg">
      <Card withBorder padding="lg">
        <Stack>
          <Group align="flex-end" gap="md">
            <Select
              label="Type of file"
              data={GENRES.map((value) => ({ value, label: GENRE_LABELS[value] }))}
              value={genre}
              onChange={(value) => value && setGenre(value as Genre)}
              allowDeselect={false}
              w={240}
            />
            <Text size="sm" c="dimmed" style={{ flex: 1 }} mb={6}>
              {GENRE_HELP[genre]}
            </Text>
          </Group>
          <Dropzone
            onDrop={(files) => {
              for (const file of files) void uploadOne(file, genre);
            }}
            onReject={(rejections) => {
              for (const rejection of rejections) {
                setUploads((current) => [
                  ...current,
                  {
                    id: `${rejection.file.name}-${Date.now()}`,
                    name: rejection.file.name,
                    progress: 0,
                    error: `Files must be ${settings.max_file_size_mb} MB or smaller.`,
                  },
                ]);
              }
            }}
            maxSize={settings.max_file_size_mb * 1024 * 1024}
          >
            <Group justify="center" gap="md" mih={110} style={{ pointerEvents: "none" }}>
              <IconFileUpload size={40} stroke={1.4} color="var(--mantine-color-indigo-6)" />
              <Stack gap={2}>
                <Text fw={500}>Drop files here or click to choose</Text>
                <Text size="sm" c="dimmed">
                  {allowed.join(", ")} · up to {settings.max_file_size_mb} MB each
                </Text>
              </Stack>
            </Group>
          </Dropzone>
          {uploads.map((upload) => (
            <Stack key={upload.id} gap={4}>
              <Group justify="space-between">
                <Text size="sm">{upload.name}</Text>
                {upload.error ? (
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="gray"
                    onClick={() => setUploads((current) => current.filter((u) => u.id !== upload.id))}
                  >
                    Dismiss
                  </Button>
                ) : (
                  <Text size="sm" c="dimmed">
                    {Math.round(upload.progress * 100)}%
                  </Text>
                )}
              </Group>
              {upload.error ? (
                <Text size="sm" c="red">
                  {upload.error}
                </Text>
              ) : (
                <Progress value={upload.progress * 100} size="sm" animated={upload.progress < 1} />
              )}
            </Stack>
          ))}
        </Stack>
      </Card>

      <Card withBorder padding={0}>
        {submission.files.length === 0 ? (
          <Text c="dimmed" p="lg">
            No files yet. Start with the manuscript.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={640}>
            <Table verticalSpacing="sm" horizontalSpacing="md">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>File</Table.Th>
                  <Table.Th w={220}>Type</Table.Th>
                  <Table.Th w={150}>Status</Table.Th>
                  <Table.Th w={90} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {submission.files.map((file) => {
                  const look = FILE_STATUS[file.status] ?? { label: file.status, color: "gray" };
                  return (
                    <Table.Tr key={file.id}>
                      <Table.Td>
                        <Text size="sm" fw={500}>
                          {file.name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {formatSize(file.size_bytes)}
                        </Text>
                        {file.rejection_reason ? (
                          <Text size="xs" c="red">
                            {file.rejection_reason}
                          </Text>
                        ) : null}
                      </Table.Td>
                      <Table.Td>
                        <Select
                          size="xs"
                          aria-label={`Type of ${file.name}`}
                          data={GENRES.filter((g) =>
                            (settings.allowed_file_types[g] ?? []).includes(extension(file.original_name)),
                          ).map((value) => ({ value, label: GENRE_LABELS[value] }))}
                          value={file.genre}
                          onChange={(value) => value && update.mutate({ file, genre: value as Genre })}
                          allowDeselect={false}
                        />
                      </Table.Td>
                      <Table.Td>
                        <Badge color={look.color} variant="light">
                          {look.label}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          {file.download_url ? (
                            <Tooltip label="Download">
                              <ActionIcon
                                component="a"
                                href={file.download_url}
                                variant="subtle"
                                aria-label="Download"
                              >
                                <IconDownload size={18} />
                              </ActionIcon>
                            </Tooltip>
                          ) : null}
                          <Tooltip label="Remove">
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              aria-label={`Remove ${file.name}`}
                              onClick={() => confirmRemove(file)}
                            >
                              <IconTrash size={18} />
                            </ActionIcon>
                          </Tooltip>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>

      {!hasManuscript ? (
        <Alert color="gray" variant="light">
          The manuscript file is required. Figures, tables and other files are optional.
        </Alert>
      ) : null}

      <Group justify="space-between">
        <Button variant="default" onClick={onBack}>
          Back
        </Button>
        <Group gap="sm">
          {busy ? (
            <Text size="sm" c="dimmed">
              Files are still being uploaded or checked…
            </Text>
          ) : null}
          <Button onClick={onDone}>Continue</Button>
        </Group>
      </Group>
    </Stack>
  );
}
