import type { FileOut, Genre, WorkflowOut } from "@jps/api-client";
import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Card,
  FileInput,
  Group,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { IconDownload, IconTrash, IconUpload } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../api";
import { formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { FILE_STATUS, formatSize, GENRE_LABELS } from "../submissions/labels";
import { sendToStorage } from "../submissions/upload";
import { workflowKey } from "./queries";

type StageName = "copyedit" | "production";

const COPY: Record<StageName, { title: string; help: string; empty: string }> = {
  copyedit: {
    title: "Copyediting files",
    help: "The copyeditor, the editors and the authors exchange versions of the text here.",
    empty: "No files yet. The copyeditor starts from the accepted manuscript.",
  },
  production: {
    title: "Production files",
    help: "Final text, figures and layout sources for typesetting. Readers' files are galleys, on the Publication tab.",
    empty: "No files yet.",
  },
};

const KINDS: Genre[] = ["manuscript", "figure", "table", "supplementary"];

/** Files of one stage after acceptance, with uploading for the people who work on it. */
export function StageFilesCard({
  submissionId,
  workflow,
  stage,
}: {
  submissionId: number;
  workflow: WorkflowOut;
  stage: StageName;
}) {
  const queryClient = useQueryClient();
  const files: FileOut[] = stage === "copyedit" ? workflow.copyedit_files : workflow.production_files;
  const canUpload = workflow.can_upload[stage] ?? false;
  const [file, setFile] = useState<File | null>(null);
  const [genre, setGenre] = useState<Genre>("manuscript");
  const [progress, setProgress] = useState<number | null>(null);
  const path = { submission_id: submissionId, stage };

  const upload = useMutation({
    mutationFn: async (chosen: File) => {
      const ticket = await unwrap(
        api.POST("/api/v1/submissions/{submission_id}/stage-files/{stage}/uploads", {
          params: { path },
          body: { file_name: chosen.name, size: chosen.size, genre },
        }),
      );
      await sendToStorage(ticket.upload, chosen, setProgress);
      return unwrap(
        api.POST("/api/v1/submissions/{submission_id}/stage-files/{stage}/{file_id}/complete", {
          params: { path: { ...path, file_id: ticket.file.id } },
        }),
      );
    },
    onSuccess: () => {
      notifySaved("File added");
      setFile(null);
      queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
    },
    onError: (error) => showRequestError(error),
    onSettled: () => setProgress(null),
  });

  const remove = useMutation({
    mutationFn: (fileId: number) =>
      unwrap(
        api.DELETE("/api/v1/submissions/{submission_id}/stage-files/{stage}/{file_id}", {
          params: { path: { ...path, file_id: fileId } },
        }),
      ),
    onSuccess: () => {
      notifySaved("File removed");
      queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
    },
    onError: (error) => showRequestError(error),
  });

  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <div>
          <Title order={4}>{COPY[stage].title}</Title>
          <Text size="sm" c="dimmed">
            {COPY[stage].help}
          </Text>
        </div>
        {files.length === 0 ? (
          <Text size="sm" c="dimmed">
            {COPY[stage].empty}
          </Text>
        ) : (
          <Table verticalSpacing="xs">
            <Table.Tbody>
              {files.map((item) => {
                const look = FILE_STATUS[item.status] ?? { label: item.status, color: "gray" };
                return (
                  <Table.Tr key={item.id}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {item.download_url ? (
                          <Anchor href={item.download_url} size="sm">
                            {item.name}
                          </Anchor>
                        ) : (
                          item.name
                        )}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {GENRE_LABELS[item.genre]} · {formatSize(item.size_bytes)} ·{" "}
                        {formatDateTime(item.uploaded_at)}
                      </Text>
                    </Table.Td>
                    <Table.Td w={110}>
                      <Badge size="sm" variant="light" color={look.color}>
                        {look.label}
                      </Badge>
                    </Table.Td>
                    <Table.Td w={80}>
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        {item.download_url ? (
                          <Tooltip label="Download">
                            <ActionIcon
                              component="a"
                              href={item.download_url}
                              variant="subtle"
                              aria-label={`Download ${item.name}`}
                            >
                              <IconDownload size={16} />
                            </ActionIcon>
                          </Tooltip>
                        ) : null}
                        {canUpload ? (
                          <Tooltip label="Remove">
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              aria-label={`Remove ${item.name}`}
                              onClick={() =>
                                modals.openConfirmModal({
                                  title: `Remove ${item.name}?`,
                                  labels: { confirm: "Remove", cancel: "Cancel" },
                                  confirmProps: { color: "red" },
                                  onConfirm: () => remove.mutate(item.id),
                                })
                              }
                            >
                              <IconTrash size={16} />
                            </ActionIcon>
                          </Tooltip>
                        ) : null}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        )}
        {canUpload ? (
          <Stack gap="xs">
            <Group align="flex-end" gap="xs" wrap="wrap">
              <Select
                label="Kind of file"
                data={KINDS.map((value) => ({ value, label: GENRE_LABELS[value] }))}
                value={genre}
                onChange={(value) => value && setGenre(value as Genre)}
                allowDeselect={false}
                w={200}
              />
              <FileInput
                label="File"
                placeholder="Choose a file"
                value={file}
                onChange={setFile}
                clearable
                style={{ flex: 1, minWidth: 200 }}
              />
              <Button
                leftSection={<IconUpload size={16} />}
                disabled={!file}
                loading={upload.isPending}
                onClick={() => file && upload.mutate(file)}
              >
                Upload
              </Button>
            </Group>
            {progress !== null ? <Progress value={progress * 100} size="sm" /> : null}
          </Stack>
        ) : null}
      </Stack>
    </Card>
  );
}
