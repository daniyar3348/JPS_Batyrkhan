import type { IssueIn, IssueOut } from "@jps/api-client";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  NumberInput,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { type UseFormReturnType, useForm } from "@mantine/form";
import { IconPlus } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, unwrap } from "../api";
import { can, useMe } from "../auth";
import { PageHeader, QueryState } from "../components/common";
import { formatDate } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { issuesKey, useIssues } from "./queries";

export interface IssueFormValues {
  volume: number | string;
  number: string;
  year: number | string;
  title: string;
  description: string;
}

export function issueFormValues(issue?: IssueOut): IssueFormValues {
  return {
    volume: issue?.volume ?? "",
    number: issue?.number ?? "",
    year: issue?.year ?? (issue ? "" : new Date().getFullYear()),
    title: issue?.title ?? "",
    description: issue?.description ?? "",
  };
}

/** Empty fields are sent as null; the server requires at least one of volume, number, year or title. */
export function issueBody(values: IssueFormValues): IssueIn {
  return {
    volume: values.volume === "" ? null : Number(values.volume),
    number: values.number.trim() || null,
    year: values.year === "" ? null : Number(values.year),
    title: values.title.trim(),
    description: values.description.trim(),
  };
}

export function validateIssue(values: IssueFormValues): Record<string, string> {
  const empty = values.volume === "" && !values.number.trim() && values.year === "" && !values.title.trim();
  return empty ? { title: "Give the issue a volume, number, year or title" } : {};
}

/** Volume, number, year, title and description of an issue. */
export function IssueFields({ form }: { form: UseFormReturnType<IssueFormValues> }) {
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <NumberInput label="Volume" min={1} allowDecimal={false} {...form.getInputProps("volume")} />
        <TextInput label="Number" maxLength={20} {...form.getInputProps("number")} />
        <NumberInput
          label="Year"
          min={1900}
          max={2200}
          allowDecimal={false}
          {...form.getInputProps("year")}
        />
      </SimpleGrid>
      <TextInput
        label="Title"
        description="Optional, e.g. for a special issue."
        maxLength={300}
        {...form.getInputProps("title")}
      />
      <Textarea
        label="Description"
        description="Shown on the issue's page on the journal's site."
        autosize
        minRows={2}
        maxLength={5000}
        {...form.getInputProps("description")}
      />
    </Stack>
  );
}

function NewIssueModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<IssueFormValues>({ initialValues: issueFormValues(), validate: validateIssue });
  const create = useMutation({
    mutationFn: (values: IssueFormValues) => unwrap(api.POST("/api/v1/issues", { body: issueBody(values) })),
    onSuccess: (issue) => {
      queryClient.invalidateQueries({ queryKey: issuesKey });
      notifySaved("Issue created");
      onClose();
      navigate(`/publishing/issues/${issue.id}`);
    },
    onError: (error) => showRequestError(error, form),
  });
  return (
    <Modal opened onClose={onClose} title="New issue" size="lg">
      <form onSubmit={form.onSubmit((values) => create.mutate(values))} noValidate>
        <Stack>
          <IssueFields form={form} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create issue
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

export function IssueStatusBadges({ issue }: { issue: Pick<IssueOut, "status" | "is_current"> }) {
  return (
    <Group gap={6} wrap="nowrap">
      {issue.status === "published" ? (
        <Badge color="green" variant="light">
          Published
        </Badge>
      ) : (
        <Badge color="blue" variant="light">
          Future
        </Badge>
      )}
      {issue.is_current ? (
        <Badge color="grape" variant="filled">
          Current
        </Badge>
      ) : null}
    </Group>
  );
}

export function IssuesPage() {
  const issues = useIssues();
  const [creating, setCreating] = useState(false);
  const manage = can(useMe().data, "publishing.manage");
  return (
    <Stack>
      <PageHeader
        title="Issues"
        description="Future issues collect scheduled articles; publishing an issue publishes them all."
        actions={
          manage ? (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
              New issue
            </Button>
          ) : null
        }
      />
      {issues.data ? (
        issues.data.length === 0 ? (
          <Text c="dimmed">No issues yet. Create the first one to schedule articles into it.</Text>
        ) : (
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={560}>
              <Table verticalSpacing="sm" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Issue</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Articles</Table.Th>
                    <Table.Th>Published</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {issues.data.map((issue) => (
                    <Table.Tr key={issue.id}>
                      <Table.Td>
                        <Anchor component={Link} to={`/publishing/issues/${issue.id}`} fw={500}>
                          {issue.label}
                        </Anchor>
                      </Table.Td>
                      <Table.Td>
                        <IssueStatusBadges issue={issue} />
                      </Table.Td>
                      <Table.Td>{issue.article_count}</Table.Td>
                      <Table.Td>{formatDate(issue.published_at)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        )
      ) : (
        <QueryState isPending={issues.isPending} error={issues.error} onRetry={() => issues.refetch()} />
      )}
      {creating ? <NewIssueModal onClose={() => setCreating(false)} /> : null}
    </Stack>
  );
}
