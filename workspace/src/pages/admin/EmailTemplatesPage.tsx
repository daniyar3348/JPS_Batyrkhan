import type { EmailTemplateOut } from "@jps/api-client";
import {
  Badge,
  Button,
  Card,
  Code,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { IconPencil } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, unwrap } from "../../api";
import { PageHeader, QueryState } from "../../components/common";
import { formatDateTime } from "../../lib/format";
import { notifySaved, showRequestError } from "../../lib/forms";

const templatesKey = ["email-templates"] as const;

function useTemplates() {
  return useQuery({
    queryKey: templatesKey,
    queryFn: () => unwrap(api.GET("/api/v1/journal/email-templates")),
  });
}

/** Templates by group, in the order the server lists them. */
function grouped(templates: EmailTemplateOut[]): [string, EmailTemplateOut[]][] {
  const groups = new Map<string, EmailTemplateOut[]>();
  for (const template of templates) {
    groups.set(template.group, [...(groups.get(template.group) ?? []), template]);
  }
  return [...groups.entries()];
}

function TemplateEditor({ template, onDone }: { template: EmailTemplateOut; onDone: () => void }) {
  const queryClient = useQueryClient();
  const body = useRef<HTMLTextAreaElement>(null);
  const form = useForm({ initialValues: { subject: template.subject, body: template.body } });

  const save = useMutation({
    mutationFn: (values: typeof form.values) =>
      unwrap(
        api.PUT("/api/v1/journal/email-templates/{key}", {
          params: { path: { key: template.key } },
          body: values,
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: templatesKey });
      notifySaved("Template saved");
      onDone();
    },
    onError: (error) => showRequestError(error, form),
  });

  const reset = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/api/v1/journal/email-templates/{key}", { params: { path: { key: template.key } } }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: templatesKey });
      notifySaved("Default wording restored");
      onDone();
    },
    onError: (error) => showRequestError(error),
  });

  const confirmReset = () =>
    modals.openConfirmModal({
      title: "Restore the default wording?",
      children: <Text size="sm">The journal's own wording of this e-mail will be lost.</Text>,
      labels: { confirm: "Restore default", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => reset.mutate(),
    });

  /** Put a placeholder where the cursor is in the text (or at the end). */
  const insert = (name: string) => {
    const placeholder = `{${name}}`;
    const element = body.current;
    const text = form.values.body;
    const start = element?.selectionStart ?? text.length;
    const end = element?.selectionEnd ?? text.length;
    form.setFieldValue("body", text.slice(0, start) + placeholder + text.slice(end));
    requestAnimationFrame(() => {
      element?.focus();
      element?.setSelectionRange(start + placeholder.length, start + placeholder.length);
    });
  };

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack>
        <Text size="sm" c="dimmed">
          {template.description} Sent to: {template.recipient}.
        </Text>
        <TextInput label="Subject" required {...form.getInputProps("subject")} />
        <Textarea
          label="Text"
          required
          autosize
          minRows={10}
          maxRows={24}
          ref={body}
          {...form.getInputProps("body")}
        />
        <Stack gap={6}>
          <Text size="sm" fw={500}>
            Placeholders
          </Text>
          <Text size="xs" c="dimmed">
            Click one to insert it into the text. Each is replaced when the e-mail is sent.
          </Text>
          <ScrollArea.Autosize mah={180}>
            <Table verticalSpacing={4} horizontalSpacing="xs">
              <Table.Tbody>
                {template.variables.map((variable) => (
                  <Table.Tr key={variable.name}>
                    <Table.Td w={1}>
                      <Tooltip label="Insert">
                        <UnstyledButton
                          onClick={() => insert(variable.name)}
                          aria-label={`Insert {${variable.name}}`}
                        >
                          <Code>{`{${variable.name}}`}</Code>
                        </UnstyledButton>
                      </Tooltip>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {variable.description}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
        </Stack>
        <Group justify="space-between">
          {template.is_custom ? (
            <Button variant="subtle" color="red" onClick={confirmReset} loading={reset.isPending}>
              Restore default
            </Button>
          ) : (
            <span />
          )}
          <Group>
            <Button variant="default" onClick={onDone}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save template
            </Button>
          </Group>
        </Group>
      </Stack>
    </form>
  );
}

export function EmailTemplatesPage() {
  const templates = useTemplates();
  const [editing, setEditing] = useState<EmailTemplateOut | null>(null);

  return (
    <Stack>
      <PageHeader
        title="E-mail templates"
        description="The wording of every e-mail the journal sends about manuscripts."
      />
      {templates.data ? (
        grouped(templates.data).map(([group, items]) => (
          <Card key={group} withBorder padding={0}>
            <Title order={4} p="lg" pb="xs">
              {group}
            </Title>
            <Table.ScrollContainer minWidth={560}>
              <Table verticalSpacing="sm" horizontalSpacing="lg" highlightOnHover>
                <Table.Tbody>
                  {items.map((template) => (
                    <Table.Tr key={template.key}>
                      <Table.Td>
                        <Group gap="xs">
                          <Text size="sm" fw={500}>
                            {template.name}
                          </Text>
                          {template.is_custom ? (
                            <Tooltip label={`Changed ${formatDateTime(template.updated_at)}`}>
                              <Badge size="xs" variant="light">
                                Customised
                              </Badge>
                            </Tooltip>
                          ) : null}
                        </Group>
                        <Text size="xs" c="dimmed">
                          {template.description}
                        </Text>
                      </Table.Td>
                      <Table.Td w={170}>
                        <Text size="sm" c="dimmed">
                          {template.recipient}
                        </Text>
                      </Table.Td>
                      <Table.Td w={90}>
                        <Button
                          size="xs"
                          variant="subtle"
                          leftSection={<IconPencil size={14} />}
                          onClick={() => setEditing(template)}
                          aria-label={`Edit ${template.name}`}
                        >
                          Edit
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        ))
      ) : (
        <QueryState
          isPending={templates.isPending}
          error={templates.error}
          onRetry={() => templates.refetch()}
        />
      )}
      <Modal opened={editing !== null} onClose={() => setEditing(null)} title={editing?.name} size="xl">
        {editing ? (
          <TemplateEditor key={editing.key} template={editing} onDone={() => setEditing(null)} />
        ) : null}
      </Modal>
    </Stack>
  );
}
