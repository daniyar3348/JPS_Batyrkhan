import type { SectionCreate, SectionOut } from "@jps/api-client";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useDisclosure } from "@mantine/hooks";
import { modals } from "@mantine/modals";
import { IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../../api";
import { PageHeader, QueryState } from "../../components/common";
import { notifySaved, showRequestError } from "../../lib/forms";

const sectionsKey = ["sections"] as const;

function useEditors() {
  return useQuery({
    queryKey: ["users", "editors"],
    queryFn: async () => {
      const [chiefs, editors] = await Promise.all(
        (["editor_in_chief", "section_editor"] as const).map((role) =>
          unwrap(api.GET("/api/v1/users", { params: { query: { role, limit: 200 } } })),
        ),
      );
      const byId = new Map(
        [...(chiefs?.items ?? []), ...(editors?.items ?? [])].map((user) => [user.id, user]),
      );
      return [...byId.values()]
        .filter((user) => user.is_active)
        .map((user) => ({ value: String(user.id), label: `${user.full_name} (${user.email})` }));
    },
  });
}

function SectionForm({ section, onDone }: { section: SectionOut | null; onDone: () => void }) {
  const queryClient = useQueryClient();
  const editors = useEditors();
  const form = useForm({
    initialValues: {
      title: section?.title ?? "",
      abbreviation: section?.abbreviation ?? "",
      policy: section?.policy ?? "",
      is_active: section?.is_active ?? true,
      sort_order: section?.sort_order ?? 0,
      editor_ids: (section?.editors ?? []).map((editor) => String(editor.id)),
    },
    validate: {
      title: (value) => (value.trim() ? null : "Enter a title"),
      abbreviation: (value) => (value.trim() ? null : "Enter a short code, for example ART"),
    },
  });

  const save = useMutation({
    mutationFn: async ({ editor_ids, ...fields }: typeof form.values) => {
      const body: SectionCreate = fields;
      const saved = section
        ? await unwrap(
            api.PATCH("/api/v1/sections/{section_id}", {
              params: { path: { section_id: section.id }, header: { "if-match": `"${section.version}"` } },
              body,
            }),
          )
        : await unwrap(api.POST("/api/v1/sections", { body }));
      return unwrap(
        api.PUT("/api/v1/sections/{section_id}/editors", {
          params: { path: { section_id: saved.id } },
          body: { user_ids: editor_ids.map(Number) },
        }),
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sectionsKey });
      queryClient.invalidateQueries({ queryKey: ["public-journal"] });
      notifySaved(section ? "Section saved" : "Section created");
      onDone();
    },
    onError: (error) => showRequestError(error, form),
  });

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack>
        <Group grow align="flex-start">
          <TextInput
            label="Title"
            placeholder="Research Articles"
            required
            {...form.getInputProps("title")}
          />
          <TextInput
            label="Abbreviation"
            placeholder="ART"
            required
            maw={140}
            {...form.getInputProps("abbreviation")}
          />
        </Group>
        <Textarea
          label="Section policy"
          description="What this section publishes; shown to authors when they submit."
          autosize
          minRows={3}
          {...form.getInputProps("policy")}
        />
        <MultiSelect
          label="Section editors"
          description="Only people with the Editor-in-chief or Section editor role can be chosen."
          data={editors.data ?? []}
          searchable
          nothingFoundMessage={editors.isPending ? "Loading…" : "No editors found"}
          {...form.getInputProps("editor_ids")}
        />
        <Group justify="space-between" align="flex-end">
          <NumberInput label="Order" min={0} max={10000} w={120} {...form.getInputProps("sort_order")} />
          <Switch label="Accepting submissions" {...form.getInputProps("is_active", { type: "checkbox" })} />
        </Group>
        <Group justify="flex-end">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            {section ? "Save section" : "Create section"}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function SectionsPage() {
  const queryClient = useQueryClient();
  const sections = useQuery({ queryKey: sectionsKey, queryFn: () => unwrap(api.GET("/api/v1/sections")) });
  const [editing, setEditing] = useState<SectionOut | null>(null);
  const [opened, { open, close }] = useDisclosure(false);

  const remove = useMutation({
    mutationFn: (section: SectionOut) =>
      unwrap(api.DELETE("/api/v1/sections/{section_id}", { params: { path: { section_id: section.id } } })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sectionsKey });
      notifySaved("Section deleted");
    },
    onError: (error) => showRequestError(error),
  });

  const openForm = (section: SectionOut | null) => {
    setEditing(section);
    open();
  };
  const confirmDelete = (section: SectionOut) =>
    modals.openConfirmModal({
      title: `Delete “${section.title}”?`,
      children: (
        <Text size="sm">
          This cannot be undone. To stop new submissions but keep the section, switch off “Accepting
          submissions” instead.
        </Text>
      ),
      labels: { confirm: "Delete", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(section),
    });

  return (
    <Stack>
      <PageHeader
        title="Sections"
        description="The kinds of articles the journal publishes. Authors choose a section when they submit."
        actions={
          <Button leftSection={<IconPlus size={16} />} onClick={() => openForm(null)}>
            New section
          </Button>
        }
      />
      {sections.data ? (
        <Card withBorder padding={0}>
          {sections.data.length === 0 ? (
            <Text c="dimmed" p="lg">
              No sections yet. Create the first one, for example “Research Articles”.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={640}>
              <Table verticalSpacing="sm" horizontalSpacing="md">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Section</Table.Th>
                    <Table.Th>Editors</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th w={90} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {sections.data.map((section) => (
                    <Table.Tr key={section.id}>
                      <Table.Td>
                        <Text fw={500}>{section.title}</Text>
                        <Text size="xs" c="dimmed">
                          {section.abbreviation}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">
                          {section.editors.map((editor) => editor.full_name).join(", ") || (
                            <Text span c="dimmed" size="sm">
                              None assigned
                            </Text>
                          )}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {section.is_active ? (
                          <Badge color="teal" variant="light">
                            Open
                          </Badge>
                        ) : (
                          <Badge color="gray" variant="light">
                            Closed
                          </Badge>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          <Tooltip label="Edit">
                            <ActionIcon variant="subtle" aria-label="Edit" onClick={() => openForm(section)}>
                              <IconPencil size={18} />
                            </ActionIcon>
                          </Tooltip>
                          <Tooltip label="Delete">
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              aria-label="Delete"
                              onClick={() => confirmDelete(section)}
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
          )}
        </Card>
      ) : (
        <QueryState
          isPending={sections.isPending}
          error={sections.error}
          onRetry={() => sections.refetch()}
        />
      )}
      <Modal opened={opened} onClose={close} title={editing ? "Edit section" : "New section"} size="lg">
        <SectionForm key={editing?.id ?? "new"} section={editing} onDone={close} />
      </Modal>
    </Stack>
  );
}
