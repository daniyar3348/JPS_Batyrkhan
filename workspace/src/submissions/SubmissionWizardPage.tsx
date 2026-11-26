import type { SubmissionOut } from "@jps/api-client";
import { Alert, Button, Stack, Stepper } from "@mantine/core";
import { modals } from "@mantine/modals";
import { useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router";
import { PageHeader, QueryState } from "../components/common";
import { storeSubmission, useSubmission, useSubmissionSettings } from "./queries";
import { AuthorsStep } from "./steps/AuthorsStep";
import { DetailsStep } from "./steps/DetailsStep";
import { FilesStep } from "./steps/FilesStep";
import { ReviewStep, STEP_NAMES, STEP_OF_FIELD } from "./steps/ReviewStep";
import { StartStep } from "./steps/StartStep";

const STEP_DESCRIPTIONS = [
  "Section and checklist",
  "Manuscript and files",
  "Title and abstract",
  "Who wrote it",
  "Check and submit",
];

export function SubmissionWizardPage() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const step = Math.min(Math.max(Number(params.get("step") ?? 0) || 0, 0), STEP_NAMES.length - 1);
  const submission = useSubmission(id);
  const settings = useSubmissionSettings();
  // A ref, not state: a step reports "saved" and moves on in the same handler, before a re-render.
  const dirty = useRef(false);
  // Set when the author submits here, so the page that follows can thank them.
  const justSubmitted = useRef(false);
  const queryClient = useQueryClient();
  const setDirty = (value: boolean) => {
    dirty.current = value;
  };

  const goTo = (next: number) => {
    const go = () => {
      dirty.current = false;
      setParams({ step: String(next) });
      window.scrollTo({ top: 0 });
    };
    if (!dirty.current) return go();
    modals.openConfirmModal({
      title: "Leave without saving?",
      children: "Your changes on this step have not been saved.",
      labels: { confirm: "Leave", cancel: "Stay" },
      confirmProps: { color: "red" },
      onConfirm: go,
    });
  };

  if (!submission.data || !settings.data) {
    return (
      <QueryState
        isPending={submission.isPending || settings.isPending}
        error={submission.error ?? settings.error}
        onRetry={() => {
          submission.refetch();
          settings.refetch();
        }}
      />
    );
  }
  const data = submission.data;
  // Once the submission leaves the draft state, its own page takes over: this is also how the wizard
  // moves on after "Submit", so there is exactly one navigation.
  if (data.status !== "draft") {
    return <Navigate to={`/submissions/${id}${justSubmitted.current ? "?submitted=1" : ""}`} replace />;
  }
  if (!data.viewer.can_edit) {
    return <Alert color="red">Only the person who started this submission can edit it.</Alert>;
  }

  const stepsWithProblems = new Set(
    data.problems.map((p) => STEP_OF_FIELD[p.field]).filter((s) => s !== undefined),
  );
  const next = () => goTo(step + 1);
  const back = () => goTo(step - 1);

  return (
    <Stack gap="lg">
      <PageHeader
        title={data.publication.title || "New submission"}
        description="Your progress is saved at every step; you can leave and come back."
        actions={
          <Button component={Link} to="/submissions" variant="subtle">
            My submissions
          </Button>
        }
      />
      <Stepper active={step} onStepClick={goTo} size="sm" allowNextStepsSelect>
        {STEP_NAMES.map((name, index) => (
          <Stepper.Step
            key={name}
            label={name}
            description={STEP_DESCRIPTIONS[index]}
            color={index !== step && stepsWithProblems.has(index) ? "orange" : undefined}
          />
        ))}
      </Stepper>
      {step === 0 ? (
        <StartStep submission={data} settings={settings.data} onDone={next} onDirtyChange={setDirty} />
      ) : step === 1 ? (
        <FilesStep submission={data} settings={settings.data} onDone={next} onBack={back} />
      ) : step === 2 ? (
        <DetailsStep
          submission={data}
          settings={settings.data}
          onDone={next}
          onBack={back}
          onDirtyChange={setDirty}
        />
      ) : step === 3 ? (
        <AuthorsStep submission={data} onDone={next} onBack={back} />
      ) : (
        <ReviewStep
          submission={data}
          onGoTo={goTo}
          onBack={back}
          onSubmitted={(updated: SubmissionOut) => {
            justSubmitted.current = true;
            storeSubmission(queryClient, updated);
            window.scrollTo({ top: 0 });
          }}
        />
      )}
    </Stack>
  );
}
