import type { DecisionOption, WorkflowOut } from "@jps/api-client";
import { Alert, Button, Checkbox, Group, Modal, Stack, Text, Textarea } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, unwrap } from "../api";
import { QueryState } from "../components/common";
import { notifySaved, showRequestError } from "../lib/forms";
import { GENRE_LABELS } from "../submissions/labels";
import { submissionKey } from "../submissions/queries";
import { type EmailDraft, EmailEditor } from "./EmailEditor";
import { workflowKey } from "./queries";

/** Confirm a decision: choose files for reviewers, give a reason, and check the letter to the authors. */
export function DecisionModal({
  submissionId,
  option,
  onClose,
}: {
  submissionId: number;
  option: DecisionOption | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const decision = option?.decision;
  const preview = useQuery({
    queryKey: ["decision-preview", submissionId, decision],
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/decisions/preview", {
          params: { path: { submission_id: submissionId } },
          // biome-ignore lint/style/noNonNullAssertion: the query only runs with a decision
          body: { decision: decision! },
        }),
      ),
    enabled: !!decision,
    gcTime: 0,
  });

  const [files, setFiles] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [letter, setLetter] = useState<EmailDraft>({ subject: "", body: "" });
  const [send, setSend] = useState(true);

  useEffect(() => {
    const data = preview.data;
    if (!data) return;
    // Every candidate is offered; the main manuscript files are chosen by default.
    setFiles(
      data.candidate_files
        .filter((file) => file.genre !== "cover_letter" && file.genre !== "title_page")
        .map((file) => String(file.id)),
    );
    setLetter({ subject: data.letter?.subject ?? "", body: data.letter?.body ?? "" });
    setSend(!!data.letter);
    setReason("");
  }, [preview.data]);

  const record = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/decisions", {
          params: { path: { submission_id: submissionId } },
          body: {
            // biome-ignore lint/style/noNonNullAssertion: the button is only shown with a decision
            decision: decision!,
            review_file_ids: files.map(Number),
            reason,
            letter: preview.data?.letter ? { send, subject: letter.subject, body: letter.body } : null,
          },
        }),
      ),
    onSuccess: (workflow: WorkflowOut) => {
      queryClient.setQueryData(workflowKey(submissionId), workflow);
      queryClient.invalidateQueries({ queryKey: submissionKey(submissionId) });
      queryClient.invalidateQueries({ queryKey: ["submissions"] });
      notifySaved(option?.is_recommendation ? "Recommendation sent" : "Decision recorded");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });

  const reasonLabel = option?.is_recommendation ? "Note for the deciding editors" : "Reason";
  const missingFiles = option?.needs_files && files.length === 0;
  const missingReason = option?.needs_reason && !reason.trim();

  return (
    <Modal opened={!!option} onClose={onClose} title={option?.label} size="xl">
      {!preview.data ? (
        <QueryState isPending={preview.isPending} error={preview.error} onRetry={() => preview.refetch()} />
      ) : (
        <Stack>
          <Text size="sm" c="dimmed">
            {option?.description}
          </Text>
          {option?.needs_files ? (
            <Checkbox.Group
              label="Files for the reviewers"
              description="Reviewers get copies with the authors' names removed from the files' properties. Check that the text itself does not name the authors."
              value={files}
              onChange={setFiles}
            >
              <Stack gap={6} mt="xs">
                {preview.data.candidate_files.map((file) => (
                  <Checkbox
                    key={file.id}
                    value={String(file.id)}
                    label={`${file.name} · ${GENRE_LABELS[file.genre]}`}
                  />
                ))}
                {preview.data.candidate_files.length === 0 ? (
                  <Alert color="orange" icon={<IconAlertTriangle />}>
                    There are no files ready to send.
                  </Alert>
                ) : null}
              </Stack>
            </Checkbox.Group>
          ) : null}
          {option?.needs_reason || option?.is_recommendation ? (
            <Textarea
              label={reasonLabel}
              autosize
              minRows={2}
              required={option?.needs_reason}
              value={reason}
              onChange={(event) => setReason(event.currentTarget.value)}
            />
          ) : null}
          {preview.data.letter ? (
            <EmailEditor
              value={letter}
              onChange={setLetter}
              to={preview.data.letter.to}
              send={send}
              onSendChange={setSend}
              sendLabel="Send a letter to the authors"
            />
          ) : null}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={record.isPending}
              disabled={missingFiles || missingReason}
              onClick={() => record.mutate()}
            >
              {option?.is_recommendation ? "Send recommendation" : `Record: ${option?.label}`}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
