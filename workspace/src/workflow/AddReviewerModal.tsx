import type { Suggestion } from "@jps/api-client";
import {
  Badge,
  Button,
  Card,
  Group,
  Modal,
  Radio,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconAlertTriangle, IconSearch } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, unwrap } from "../api";
import { notifySaved, showRequestError } from "../lib/forms";
import { type EmailDraft, EmailEditor } from "./EmailEditor";
import { addDays, isoDate, METHOD_HELP, METHOD_LABELS } from "./labels";
import { useReviewForms, useReviewSettings, workflowKey } from "./queries";

function averageDays(days: number): string {
  if (days < 1) return "reviews within a day";
  return `${Math.round(days)} day${Math.round(days) === 1 ? "" : "s"} per review`;
}

function SuggestionRow({ item }: { item: Suggestion }) {
  return (
    <Radio.Card value={String(item.reviewer.id)} p="sm" radius="md">
      <Group wrap="nowrap" align="flex-start">
        <Radio.Indicator mt={4} />
        <Stack gap={2} style={{ flex: 1 }}>
          <Group justify="space-between" wrap="nowrap">
            <Text fw={600} size="sm">
              {item.reviewer.full_name}
            </Text>
            <Text size="xs" c="dimmed">
              {item.active_reviews} open · {item.completed_reviews} done
              {item.average_days !== null ? ` · ${averageDays(item.average_days)}` : ""}
              {item.average_rating !== null ? ` · rated ${item.average_rating}` : ""}
            </Text>
          </Group>
          <Text size="xs" c="dimmed">
            {[item.reviewer.affiliation, item.reviewer.email].filter(Boolean).join(" · ")}
          </Text>
          {item.interests.length ? (
            <Group gap={4}>
              {item.interests.map((interest) => (
                <Badge
                  key={interest}
                  size="xs"
                  variant={
                    item.matched_keywords.some((k) => k.toLowerCase() === interest.toLowerCase())
                      ? "filled"
                      : "light"
                  }
                  color="indigo"
                >
                  {interest}
                </Badge>
              ))}
            </Group>
          ) : null}
          {item.warnings.map((warning) => (
            <Group key={warning} gap={4}>
              <IconAlertTriangle size={14} color="var(--mantine-color-orange-6)" />
              <Text size="xs" c="orange.8">
                {warning}
              </Text>
            </Group>
          ))}
        </Stack>
      </Group>
    </Radio.Card>
  );
}

/** Choose a reviewer (or someone new), set the deadlines, check the invitation, send it. */
export function AddReviewerModal({
  submissionId,
  roundId,
  opened,
  onClose,
}: {
  submissionId: number;
  roundId: number;
  opened: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const settings = useReviewSettings();
  const forms = useReviewForms(opened);
  const [mode, setMode] = useState<"journal" | "new">("journal");
  const [search, setSearch] = useState("");
  const [query] = useDebouncedValue(search, 300);
  const [reviewerId, setReviewerId] = useState<string | null>(null);
  const [person, setPerson] = useState({ email: "", given_name: "", family_name: "", affiliation: "" });
  const [method, setMethod] = useState<string | null>(null);
  const [responseDue, setResponseDue] = useState("");
  const [reviewDue, setReviewDue] = useState("");
  const [formId, setFormId] = useState<string | null>(null);
  const [email, setEmail] = useState<EmailDraft | null>(null);
  const [recipient, setRecipient] = useState<string[]>([]);

  useEffect(() => {
    if (!opened || !settings.data) return;
    const today = new Date();
    const respond = addDays(today, settings.data.response_days);
    setMethod(settings.data.method);
    setResponseDue(isoDate(respond));
    setReviewDue(isoDate(addDays(respond, settings.data.review_days)));
    setEmail(null);
    setReviewerId(null);
    setPerson({ email: "", given_name: "", family_name: "", affiliation: "" });
    setSearch("");
  }, [opened, settings.data]);

  useEffect(() => {
    const preferred = forms.data?.find((form) => form.is_default && form.is_active) ?? forms.data?.[0];
    if (preferred && !formId) setFormId(String(preferred.id));
  }, [forms.data, formId]);

  const suggestions = useQuery({
    queryKey: ["reviewer-suggestions", submissionId, roundId, query],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/submissions/{submission_id}/review-rounds/{round_id}/suggestions", {
          params: { path: { submission_id: submissionId, round_id: roundId }, query: { q: query || null } },
        }),
      ),
    enabled: opened && mode === "journal",
  });

  const who =
    mode === "journal"
      ? { reviewer_id: reviewerId ? Number(reviewerId) : null, new_reviewer: null }
      : { reviewer_id: null, new_reviewer: person };
  const chosen = mode === "journal" ? !!reviewerId : !!person.email.trim() && !!person.given_name.trim();

  const preview = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-rounds/{round_id}/invitation-preview", {
          params: { path: { submission_id: submissionId, round_id: roundId } },
          body: { ...who, response_due: responseDue || null, review_due: reviewDue || null },
        }),
      ),
    onSuccess: (data) => {
      setEmail({ subject: data.subject, body: data.body });
      setRecipient(data.to ?? []);
    },
    onError: (error) => showRequestError(error),
  });

  const invite = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/review-rounds/{round_id}/reviewers", {
          params: { path: { submission_id: submissionId, round_id: roundId } },
          body: {
            ...who,
            method: (method as "double_blind" | "single_blind" | "open" | null) ?? null,
            response_due: responseDue || null,
            review_due: reviewDue || null,
            form_id: formId ? Number(formId) : null,
            email,
          },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: workflowKey(submissionId) });
      queryClient.invalidateQueries({ queryKey: ["reviewer-suggestions", submissionId] });
      notifySaved("Invitation sent");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });

  return (
    <Modal opened={opened} onClose={onClose} title="Invite a reviewer" size="xl">
      {email === null ? (
        <Stack>
          <SegmentedControl
            value={mode}
            onChange={(value) => setMode(value as "journal" | "new")}
            data={[
              { value: "journal", label: "The journal's reviewers" },
              { value: "new", label: "Someone new" },
            ]}
          />
          {mode === "journal" ? (
            <Stack gap="xs">
              <TextInput
                placeholder="Search by name, e-mail, institution or interests"
                leftSection={<IconSearch size={16} />}
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
              />
              <Text size="xs" c="dimmed">
                Best matches first: shared interests and keywords, past reviews, and how busy they are.
                Authors and editors of this manuscript are left out.
              </Text>
              <ScrollArea.Autosize mah={340}>
                <Radio.Group value={reviewerId} onChange={setReviewerId}>
                  <Stack gap="xs">
                    {(suggestions.data ?? []).map((item) => (
                      <SuggestionRow key={item.reviewer.id} item={item} />
                    ))}
                    {suggestions.data?.length === 0 ? (
                      <Text size="sm" c="dimmed">
                        No reviewers found. Invite someone new instead.
                      </Text>
                    ) : null}
                  </Stack>
                </Radio.Group>
              </ScrollArea.Autosize>
            </Stack>
          ) : (
            <Card withBorder>
              <Stack gap="xs">
                <Text size="sm" c="dimmed">
                  They will get an account with the Reviewer role and an e-mail to set their password.
                </Text>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <TextInput
                    label="Given name"
                    required
                    value={person.given_name}
                    onChange={(e) => setPerson({ ...person, given_name: e.currentTarget.value })}
                  />
                  <TextInput
                    label="Family name"
                    value={person.family_name}
                    onChange={(e) => setPerson({ ...person, family_name: e.currentTarget.value })}
                  />
                </SimpleGrid>
                <TextInput
                  label="E-mail address"
                  type="email"
                  required
                  value={person.email}
                  onChange={(e) => setPerson({ ...person, email: e.currentTarget.value })}
                />
                <TextInput
                  label="Affiliation"
                  value={person.affiliation}
                  onChange={(e) => setPerson({ ...person, affiliation: e.currentTarget.value })}
                />
              </Stack>
            </Card>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label="Review method"
              description={method ? METHOD_HELP[method] : undefined}
              data={Object.entries(METHOD_LABELS).map(([value, label]) => ({ value, label }))}
              value={method}
              onChange={setMethod}
              allowDeselect={false}
            />
            <Select
              label="Review form"
              data={(forms.data ?? [])
                .filter((form) => form.is_active)
                .map((form) => ({ value: String(form.id), label: form.title }))}
              value={formId}
              onChange={setFormId}
              allowDeselect={false}
            />
            <TextInput
              type="date"
              label="Answer by"
              value={responseDue}
              onChange={(e) => setResponseDue(e.currentTarget.value)}
            />
            <TextInput
              type="date"
              label="Review due"
              value={reviewDue}
              onChange={(e) => setReviewDue(e.currentTarget.value)}
            />
          </SimpleGrid>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={!chosen} loading={preview.isPending} onClick={() => preview.mutate()}>
              Next: the e-mail
            </Button>
          </Group>
        </Stack>
      ) : (
        <Stack>
          <EmailEditor
            value={email}
            onChange={setEmail}
            to={recipient}
            hint="{reviewUrl} becomes the reviewer's personal link to the review when the e-mail is sent."
          />
          <Group justify="space-between">
            <Button variant="default" onClick={() => setEmail(null)}>
              Back
            </Button>
            <Button loading={invite.isPending} onClick={() => invite.mutate()}>
              Send invitation
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
