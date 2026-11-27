import type { GalleyOut, PublishingOut } from "@jps/api-client";
import {
  ActionIcon,
  Anchor,
  Autocomplete,
  Badge,
  Button,
  Card,
  FileInput,
  Group,
  Progress,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { IconCheck, IconPencil, IconTrash, IconUpload, IconX } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../api";
import { notifySaved, showRequestError } from "../lib/forms";
import { FILE_STATUS, formatSize } from "../submissions/labels";
import { sendToStorage } from "../submissions/upload";

export const GALLEY_LABELS = ["PDF", "HTML", "XML", "EPUB"];
const ACCEPT = ".pdf,.html,.xml,.epub";

function GalleyRow({
  galley,
  submissionId,
  editable,
  onChanged,
}: {
  galley: GalleyOut;
  submissionId: number;
  editable: boolean;
  onChanged: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [label, setLabel] = useState(galley.label);
  const path = { params: { path: { submission_id: submissionId, galley_id: galley.id } } };
  const status = FILE_STATUS[galley.file.status] ?? { label: galley.file.status, color: "gray" };

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/submissions/{submission_id}/galleys/{galley_id}", {
          ...path,
          body: { label: label.trim() },
        }),
      ),
    onSuccess: () => {
      setRenaming(false);
      notifySaved("Galley renamed");
      onChanged();
    },
    onError: (error) => showRequestError(error),
  });

  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/submissions/{submission_id}/galleys/{galley_id}", path)),
    onSuccess: () => {
      notifySaved("Galley removed");
      onChanged();
    },
    onError: (error) => showRequestError(error),
  });

  return (
    <Table.Tr>
      <Table.Td>
        {renaming ? (
          <Group gap={4} wrap="nowrap">
            <TextInput
              size="xs"
              aria-label="Galley label"
              value={label}
              onChange={(event) => setLabel(event.currentTarget.value)}
              maxLength={50}
            />
            <ActionIcon
              variant="subtle"
              aria-label="Save label"
              disabled={!label.trim()}
              loading={rename.isPending}
              onClick={() => rename.mutate()}
            >
              <IconCheck size={16} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label="Cancel"
              onClick={() => {
                setRenaming(false);
                setLabel(galley.label);
              }}
            >
              <IconX size={16} />
            </ActionIcon>
          </Group>
        ) : (
          <Text size="sm" fw={600}>
            {galley.label}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        {galley.file.download_url ? (
          <Anchor href={galley.file.download_url} size="sm">
            {galley.file.name}
          </Anchor>
        ) : (
          <Text size="sm">{galley.file.name}</Text>
        )}
        <Text size="xs" c="dimmed">
          {formatSize(galley.file.size_bytes)}
          {galley.file.rejection_reason ? ` · ${galley.file.rejection_reason}` : ""}
        </Text>
      </Table.Td>
      <Table.Td>
        <Badge color={status.color} variant="light">
          {status.label}
        </Badge>
      </Table.Td>
      <Table.Td>
        {editable && !renaming ? (
          <Group gap={4} justify="flex-end" wrap="nowrap">
            <Tooltip label="Rename">
              <ActionIcon
                variant="subtle"
                aria-label={`Rename ${galley.label}`}
                onClick={() => setRenaming(true)}
              >
                <IconPencil size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Remove">
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={`Remove ${galley.label}`}
                loading={remove.isPending}
                onClick={() =>
                  modals.openConfirmModal({
                    title: `Remove the ${galley.label} galley?`,
                    children: "Readers will not get this file. Earlier versions keep their own files.",
                    labels: { confirm: "Remove", cancel: "Cancel" },
                    confirmProps: { color: "red" },
                    onConfirm: () => remove.mutate(),
                  })
                }
              >
                <IconTrash size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        ) : null}
      </Table.Td>
    </Table.Tr>
  );
}

function AddGalley({ submissionId, onAdded }: { submissionId: number; onAdded: () => void }) {
  const [label, setLabel] = useState("PDF");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const path = { params: { path: { submission_id: submissionId } } };

  const add = useMutation({
    mutationFn: async () => {
      if (!file) return;
      const ticket = await unwrap(
        api.POST("/api/v1/submissions/{submission_id}/galleys/uploads", {
          ...path,
          body: { label: label.trim(), file_name: file.name, size: file.size },
        }),
      );
      setProgress(0);
      await sendToStorage(ticket.upload, file, setProgress);
      await unwrap(
        api.POST("/api/v1/submissions/{submission_id}/galleys/{galley_id}/complete", {
          params: { path: { submission_id: submissionId, galley_id: ticket.galley.id } },
        }),
      );
    },
    onSuccess: () => {
      notifySaved("Galley added. It is being checked.");
      setFile(null);
      setLabel("PDF");
      onAdded();
    },
    onError: (error) => {
      showRequestError(error);
      onAdded(); // a galley may have been created before the upload failed
    },
    onSettled: () => setProgress(null),
  });

  return (
    <Stack gap="xs">
      <Group align="flex-end" gap="sm">
        <Autocomplete
          label="Label"
          description="What readers see on the download button"
          data={GALLEY_LABELS}
          value={label}
          onChange={setLabel}
          maxLength={50}
          w={180}
        />
        <FileInput
          label="File"
          placeholder="PDF, HTML, XML or EPUB"
          accept={ACCEPT}
          value={file}
          onChange={setFile}
          clearable
          style={{ flex: 1, minWidth: 200 }}
        />
        <Button
          leftSection={<IconUpload size={16} />}
          disabled={!file || !label.trim()}
          loading={add.isPending}
          onClick={() => add.mutate()}
        >
          Add galley
        </Button>
      </Group>
      {progress !== null ? <Progress value={progress * 100} size="sm" animated /> : null}
    </Stack>
  );
}

/** The files readers download: typeset PDF, HTML, XML. */
export function GalleysCard({ data, onChanged }: { data: PublishingOut; onChanged: () => void }) {
  const editable = data.can_edit_galleys;
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Title order={4}>Galleys</Title>
        <Text size="sm" c="dimmed">
          The files readers download. Each is checked before it can be published.
        </Text>
        {data.galleys.length === 0 ? (
          <Text size="sm">No galleys yet.</Text>
        ) : (
          <Table verticalSpacing="xs">
            <Table.Tbody>
              {data.galleys.map((galley) => (
                <GalleyRow
                  key={galley.id}
                  galley={galley}
                  submissionId={data.submission_id}
                  editable={editable}
                  onChanged={onChanged}
                />
              ))}
            </Table.Tbody>
          </Table>
        )}
        {editable ? <AddGalley submissionId={data.submission_id} onAdded={onChanged} /> : null}
      </Stack>
    </Card>
  );
}
