import type { SubmissionOut } from "@jps/api-client";
import { Anchor, Badge, Card, Group, Spoiler, Stack, Table, Text, Title } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import type { ReactNode } from "react";
import { FILE_STATUS, formatSize, GENRE_LABELS } from "./labels";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      {children}
    </Stack>
  );
}

/** The manuscript as submitted: metadata, authors and files. Used in the wizard's last step and on its page. */
export function SubmissionSummaryCards({
  submission,
  action,
}: {
  submission: SubmissionOut;
  action?: ReactNode;
}) {
  const publication = submission.publication;
  const authors = publication.contributors.filter((c) => c.in_byline);
  const acknowledged = publication.contributors.filter((c) => !c.in_byline);
  return (
    <Stack gap="lg">
      <Card withBorder padding="lg">
        <Stack gap="md">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={3}>{publication.title || "Untitled manuscript"}</Title>
              {publication.subtitle ? <Text c="dimmed">{publication.subtitle}</Text> : null}
            </Stack>
            {action}
          </Group>
          <Text size="sm">
            {authors.map((a) => a.full_name).join(", ")}
            {" · "}
            <Text span c="dimmed" size="sm">
              {submission.section.title}
            </Text>
          </Text>
          <Field label="Abstract">
            <Text size="sm" className="pre-wrap">
              {publication.abstract || "—"}
            </Text>
          </Field>
          <Field label="Keywords">
            <Group gap={6}>
              {publication.keywords.length ? (
                publication.keywords.map((keyword) => (
                  <Badge key={keyword} variant="light" color="gray">
                    {keyword}
                  </Badge>
                ))
              ) : (
                <Text size="sm">—</Text>
              )}
            </Group>
          </Field>
          {publication.funding_statement ? (
            <Field label="Funding">
              <Text size="sm" className="pre-wrap">
                {publication.funding_statement}
              </Text>
            </Field>
          ) : null}
          {publication.competing_interests ? (
            <Field label="Competing interests">
              <Text size="sm" className="pre-wrap">
                {publication.competing_interests}
              </Text>
            </Field>
          ) : null}
          {publication.references ? (
            <Field label="References">
              <Spoiler maxHeight={90} showLabel="Show all" hideLabel="Show less">
                <Text size="sm" className="pre-wrap">
                  {publication.references}
                </Text>
              </Spoiler>
            </Field>
          ) : null}
        </Stack>
      </Card>

      <Card withBorder padding="lg">
        <Stack gap="sm">
          <Title order={4}>Authors</Title>
          {publication.contributors.length === 0 ? <Text c="dimmed">No authors yet.</Text> : null}
          {[...authors, ...acknowledged].map((contributor) => (
            <Group key={contributor.id} justify="space-between" wrap="nowrap" align="flex-start">
              <Stack gap={0}>
                <Text size="sm" fw={500}>
                  {contributor.full_name}
                  {contributor.is_corresponding ? (
                    <Badge ml="xs" size="xs" variant="light">
                      Corresponding
                    </Badge>
                  ) : null}
                  {!contributor.in_byline ? (
                    <Badge ml="xs" size="xs" variant="light" color="gray">
                      Acknowledged only
                    </Badge>
                  ) : null}
                </Text>
                <Text size="xs" c="dimmed">
                  {[contributor.affiliation, contributor.email].filter(Boolean).join(" · ")}
                </Text>
              </Stack>
              {contributor.orcid ? (
                <Anchor
                  href={`https://orcid.org/${contributor.orcid}`}
                  target="_blank"
                  rel="noreferrer"
                  size="xs"
                >
                  ORCID {contributor.orcid}
                </Anchor>
              ) : null}
            </Group>
          ))}
        </Stack>
      </Card>

      <Card withBorder padding={0}>
        <Title order={4} p="lg" pb="xs">
          Files
        </Title>
        {submission.files.length === 0 ? (
          <Text c="dimmed" px="lg" pb="lg">
            No files.
          </Text>
        ) : (
          <Table verticalSpacing="xs" horizontalSpacing="lg">
            <Table.Tbody>
              {submission.files.map((file) => (
                <Table.Tr key={file.id}>
                  <Table.Td>
                    {file.download_url ? (
                      <Anchor href={file.download_url} size="sm">
                        <Group gap={6} wrap="nowrap">
                          <IconDownload size={16} />
                          {file.name}
                        </Group>
                      </Anchor>
                    ) : (
                      <Text size="sm">{file.name}</Text>
                    )}
                    {/* On a phone the type and size sit under the name instead of in their own columns. */}
                    <Text size="xs" c="dimmed" hiddenFrom="sm">
                      {GENRE_LABELS[file.genre]} · {formatSize(file.size_bytes)}
                    </Text>
                  </Table.Td>
                  <Table.Td visibleFrom="sm">
                    <Text size="sm" c="dimmed">
                      {GENRE_LABELS[file.genre]}
                    </Text>
                  </Table.Td>
                  <Table.Td visibleFrom="sm">
                    <Text size="sm" c="dimmed">
                      {formatSize(file.size_bytes)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {file.status !== "ready" ? (
                      <Badge size="sm" variant="light" color={FILE_STATUS[file.status]?.color ?? "gray"}>
                        {FILE_STATUS[file.status]?.label ?? file.status}
                      </Badge>
                    ) : null}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Card>

      {submission.comments_for_editor ? (
        <Card withBorder padding="lg">
          <Field label="Comments for the editor">
            <Text size="sm" className="pre-wrap">
              {submission.comments_for_editor}
            </Text>
          </Field>
        </Card>
      ) : null}
    </Stack>
  );
}
