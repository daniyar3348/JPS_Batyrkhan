import type { ContributorIn, ContributorOut, SubmissionOut } from "@jps/api-client";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { IconArrowDown, IconArrowUp, IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../../api";
import { COUNTRIES } from "../../lib/countries";
import { notifySaved, showRequestError, validateEmail } from "../../lib/forms";
import { submissionKey } from "../queries";

function ContributorForm({
  submissionId,
  contributor,
  onDone,
}: {
  submissionId: number;
  contributor: ContributorOut | null;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const form = useForm({
    initialValues: {
      given_name: contributor?.given_name ?? "",
      family_name: contributor?.family_name ?? "",
      email: contributor?.email ?? "",
      affiliation: contributor?.affiliation ?? "",
      country: contributor?.country ?? null,
      orcid: contributor?.orcid ?? "",
      is_corresponding: contributor?.is_corresponding ?? false,
      in_byline: contributor?.in_byline ?? true,
    },
    validate: {
      given_name: (value) => (value.trim() ? null : "Enter the given name"),
      email: validateEmail,
      affiliation: (value) => (value.trim() ? null : "Enter the affiliation, or “Independent researcher”"),
    },
  });

  const save = useMutation({
    mutationFn: (values: typeof form.values) => {
      const body: ContributorIn = { ...values, orcid: values.orcid || null };
      return contributor
        ? unwrap(
            api.PATCH("/api/v1/submissions/{submission_id}/contributors/{contributor_id}", {
              params: { path: { submission_id: submissionId, contributor_id: contributor.id } },
              body,
            }),
          )
        : unwrap(
            api.POST("/api/v1/submissions/{submission_id}/contributors", {
              params: { path: { submission_id: submissionId } },
              body,
            }),
          );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: submissionKey(submissionId) });
      notifySaved(contributor ? "Author updated" : "Author added");
      onDone();
    },
    onError: (error) => showRequestError(error, form),
  });

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput label="Given name" required {...form.getInputProps("given_name")} />
          <TextInput label="Family name" {...form.getInputProps("family_name")} />
        </SimpleGrid>
        <TextInput label="E-mail address" type="email" required {...form.getInputProps("email")} />
        <TextInput
          label="Affiliation"
          required
          placeholder="Department, university, city"
          {...form.getInputProps("affiliation")}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select label="Country" data={COUNTRIES} searchable clearable {...form.getInputProps("country")} />
          <TextInput label="ORCID iD" placeholder="0000-0002-1825-0097" {...form.getInputProps("orcid")} />
        </SimpleGrid>
        <Checkbox
          label="Corresponding author — receives the journal's messages about this manuscript"
          {...form.getInputProps("is_corresponding", { type: "checkbox" })}
        />
        <Checkbox
          label="List among the authors of the published article"
          description="Clear this for contributors who are only acknowledged."
          {...form.getInputProps("in_byline", { type: "checkbox" })}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            {contributor ? "Save" : "Add author"}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function AuthorsStep({
  submission,
  onDone,
  onBack,
}: {
  submission: SubmissionOut;
  onDone: () => void;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const contributors = submission.publication.contributors;
  const [editing, setEditing] = useState<ContributorOut | "new" | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: submissionKey(submission.id) });

  const reorder = useMutation({
    mutationFn: (ids: number[]) =>
      unwrap(
        api.PUT("/api/v1/submissions/{submission_id}/contributors/order", {
          params: { path: { submission_id: submission.id } },
          body: { contributor_ids: ids },
        }),
      ),
    onSettled: refresh,
    onError: (error) => showRequestError(error),
  });

  const remove = useMutation({
    mutationFn: (contributor: ContributorOut) =>
      unwrap(
        api.DELETE("/api/v1/submissions/{submission_id}/contributors/{contributor_id}", {
          params: { path: { submission_id: submission.id, contributor_id: contributor.id } },
        }),
      ),
    onSettled: refresh,
    onError: (error) => showRequestError(error),
  });

  const move = (index: number, offset: number) => {
    const ids = contributors.map((c) => c.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + offset, 0, moved);
    reorder.mutate(ids);
  };

  const confirmRemove = (contributor: ContributorOut) =>
    modals.openConfirmModal({
      title: `Remove ${contributor.full_name}?`,
      labels: { confirm: "Remove", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(contributor),
    });

  return (
    <Stack gap="lg">
      <Card withBorder padding={0}>
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="sm" horizontalSpacing="md">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={70}>Order</Table.Th>
                <Table.Th>Author</Table.Th>
                <Table.Th>Affiliation</Table.Th>
                <Table.Th w={90} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {contributors.map((contributor, index) => (
                <Table.Tr key={contributor.id}>
                  <Table.Td>
                    <Group gap={2} wrap="nowrap">
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        aria-label="Move up"
                        disabled={index === 0 || reorder.isPending}
                        onClick={() => move(index, -1)}
                      >
                        <IconArrowUp size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        aria-label="Move down"
                        disabled={index === contributors.length - 1 || reorder.isPending}
                        onClick={() => move(index, 1)}
                      >
                        <IconArrowDown size={16} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs">
                      <Text size="sm" fw={500}>
                        {contributor.full_name}
                      </Text>
                      {contributor.is_corresponding ? (
                        <Badge size="xs" variant="light">
                          Corresponding
                        </Badge>
                      ) : null}
                      {!contributor.in_byline ? (
                        <Badge size="xs" variant="light" color="gray">
                          Acknowledged only
                        </Badge>
                      ) : null}
                    </Group>
                    <Text size="xs" c="dimmed">
                      {contributor.email}
                      {contributor.orcid ? ` · ORCID ${contributor.orcid}` : ""}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {contributor.affiliation ? (
                      <Text size="sm">{contributor.affiliation}</Text>
                    ) : (
                      <Text size="sm" c="red">
                        Missing
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Tooltip label="Edit">
                        <ActionIcon
                          variant="subtle"
                          aria-label={`Edit ${contributor.full_name}`}
                          onClick={() => setEditing(contributor)}
                        >
                          <IconPencil size={18} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Remove">
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={`Remove ${contributor.full_name}`}
                          onClick={() => confirmRemove(contributor)}
                        >
                          <IconTrash size={18} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        <Group p="md">
          <Button variant="light" leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            Add author
          </Button>
        </Group>
      </Card>
      <Text size="sm" c="dimmed">
        List the authors in the order they should appear on the article. Co-authors receive an e-mail when you
        submit, so they know about the manuscript.
      </Text>
      <Group justify="space-between">
        <Button variant="default" onClick={onBack}>
          Back
        </Button>
        <Button onClick={onDone}>Continue</Button>
      </Group>
      <Modal
        opened={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Add an author" : "Edit author"}
        size="lg"
      >
        {editing !== null ? (
          <ContributorForm
            key={editing === "new" ? "new" : editing.id}
            submissionId={submission.id}
            contributor={editing === "new" ? null : editing}
            onDone={() => setEditing(null)}
          />
        ) : null}
      </Modal>
    </Stack>
  );
}
