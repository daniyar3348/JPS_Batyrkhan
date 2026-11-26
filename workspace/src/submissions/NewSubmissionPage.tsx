import { Alert, Button, Card, Group, Radio, Stack, Text } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { showRequestError } from "../lib/forms";
import { storeSubmission, useActiveSections } from "./queries";

export function NewSubmissionPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const sections = useActiveSections();
  const [sectionId, setSectionId] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: (section_id: number) => unwrap(api.POST("/api/v1/submissions", { body: { section_id } })),
    onSuccess: (submission) => {
      storeSubmission(queryClient, submission);
      navigate(`/submissions/${submission.id}/edit`, { replace: true });
    },
    onError: (error) => showRequestError(error),
  });

  return (
    <Stack>
      <PageHeader
        title="New submission"
        description="Choose the kind of article. You can change it later while the submission is a draft."
      />
      {sections.data ? (
        sections.data.length === 0 ? (
          <Alert color="orange">The journal is not accepting submissions at the moment.</Alert>
        ) : (
          <Card withBorder padding="lg">
            <Stack>
              <Radio.Group value={sectionId} onChange={setSectionId} label="Section" withAsterisk>
                <Stack gap="sm" mt="xs">
                  {sections.data.map((section) => (
                    <Radio.Card key={section.id} value={String(section.id)} p="md" radius="md">
                      <Group wrap="nowrap" align="flex-start">
                        <Radio.Indicator />
                        <Stack gap={2}>
                          <Text fw={600}>{section.title}</Text>
                          {section.policy ? (
                            <Text size="sm" c="dimmed">
                              {section.policy}
                            </Text>
                          ) : null}
                        </Stack>
                      </Group>
                    </Radio.Card>
                  ))}
                </Stack>
              </Radio.Group>
              <Group justify="flex-end">
                <Button
                  disabled={!sectionId}
                  loading={create.isPending}
                  onClick={() => sectionId && create.mutate(Number(sectionId))}
                >
                  Start submission
                </Button>
              </Group>
            </Stack>
          </Card>
        )
      ) : (
        <QueryState
          isPending={sections.isPending}
          error={sections.error}
          onRetry={() => sections.refetch()}
        />
      )}
    </Stack>
  );
}
