import type { SubmissionOut } from "@jps/api-client";
import { Alert, Anchor, Button, Group, List, Stack, Text } from "@mantine/core";
import { modals } from "@mantine/modals";
import { IconAlertTriangle, IconSend } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../../api";
import { showRequestError } from "../../lib/forms";
import { submissionKey } from "../queries";
import { SubmissionSummaryCards } from "../SubmissionSummaryCards";

/** Which wizard step fixes each problem the server reports. */
export const STEP_OF_FIELD: Record<string, number> = {
  section_id: 0,
  checklist: 0,
  files: 1,
  title: 2,
  abstract: 2,
  keywords: 2,
  contributors: 3,
  account: 4,
};

export const STEP_NAMES = ["Start", "Files", "Details", "Authors", "Review"];

export function ReviewStep({
  submission,
  onGoTo,
  onBack,
  onSubmitted,
}: {
  submission: SubmissionOut;
  onGoTo: (step: number) => void;
  onBack: () => void;
  onSubmitted: (submission: SubmissionOut) => void;
}) {
  const queryClient = useQueryClient();
  const problems = submission.problems;

  const submit = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/submit", {
          params: { path: { submission_id: submission.id } },
        }),
      ),
    onSuccess: onSubmitted,
    onError: (error) => {
      if (error instanceof ApiError && error.code === "submission_incomplete") {
        queryClient.invalidateQueries({ queryKey: submissionKey(submission.id) });
      }
      showRequestError(error);
    },
  });

  const confirm = () =>
    modals.openConfirmModal({
      title: "Submit the manuscript?",
      children: (
        <Text size="sm">
          After you submit, the manuscript goes to the editors and can no longer be changed here. You will
          receive a confirmation by e-mail.
        </Text>
      ),
      labels: { confirm: "Submit", cancel: "Not yet" },
      onConfirm: () => submit.mutate(),
    });

  return (
    <Stack gap="lg">
      {problems.length > 0 ? (
        <Alert color="orange" icon={<IconAlertTriangle />} title="Before you can submit">
          <List size="sm" spacing={4}>
            {problems.map((problem) => {
              const step = STEP_OF_FIELD[problem.field];
              return (
                <List.Item key={`${problem.field}-${problem.message}`}>
                  {problem.message}{" "}
                  {step !== undefined && step !== 4 ? (
                    <Anchor component="button" type="button" size="sm" onClick={() => onGoTo(step)}>
                      Go to {STEP_NAMES[step]}
                    </Anchor>
                  ) : null}
                </List.Item>
              );
            })}
          </List>
        </Alert>
      ) : (
        <Alert color="teal" title="Ready to submit">
          Check the summary below. If everything is right, submit the manuscript.
        </Alert>
      )}
      <SubmissionSummaryCards submission={submission} />
      <Group justify="space-between">
        <Button variant="default" onClick={onBack}>
          Back
        </Button>
        <Button
          leftSection={<IconSend size={16} />}
          disabled={problems.length > 0}
          loading={submit.isPending}
          onClick={confirm}
        >
          Submit manuscript
        </Button>
      </Group>
    </Stack>
  );
}
