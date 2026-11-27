/** Words and colours for the editorial workflow and peer review, shared by every page that shows them. */

interface Look {
  label: string;
  color: string;
}

export const STAGES = ["submission", "review", "copyediting", "production"] as const;

export const STAGE_LABELS: Record<string, string> = {
  submission: "Submission",
  review: "Review",
  copyediting: "Copyediting",
  production: "Production",
};

export const ROUND_STATUS: Record<string, Look> = {
  review: { label: "Under review", color: "blue" },
  revisions_requested: { label: "Revisions requested", color: "orange" },
  resubmit_requested: { label: "Revise and resubmit", color: "orange" },
  revisions_submitted: { label: "Revision received", color: "teal" },
  closed: { label: "Closed", color: "gray" },
};

export const ASSIGNMENT_STATUS: Record<string, Look> = {
  invited: { label: "Invited", color: "blue" },
  accepted: { label: "Reviewing", color: "indigo" },
  declined: { label: "Declined", color: "gray" },
  cancelled: { label: "Cancelled", color: "gray" },
  completed: { label: "Review received", color: "teal" },
};

export const METHOD_LABELS: Record<string, string> = {
  double_blind: "Double-blind",
  single_blind: "Single-blind",
  open: "Open",
};

export const METHOD_HELP: Record<string, string> = {
  double_blind: "Reviewers and authors do not know each other's names.",
  single_blind: "Reviewers see the authors' names; authors do not see the reviewers'.",
  open: "Reviewers and authors see each other's names.",
};

export const RECOMMENDATIONS: { value: string; label: string }[] = [
  { value: "accept", label: "Accept" },
  { value: "minor_revisions", label: "Minor revisions" },
  { value: "major_revisions", label: "Major revisions" },
  { value: "resubmit_elsewhere", label: "Resubmit elsewhere" },
  { value: "decline", label: "Decline" },
  { value: "see_comments", label: "See comments" },
];

export const RECOMMENDATION_LABELS: Record<string, string> = Object.fromEntries(
  RECOMMENDATIONS.map((r) => [r.value, r.label]),
);

export const RECOMMENDATION_COLORS: Record<string, string> = {
  accept: "teal",
  minor_revisions: "lime",
  major_revisions: "orange",
  resubmit_elsewhere: "red",
  decline: "red",
  see_comments: "gray",
};

export const DECLINE_REASONS: { value: string; label: string }[] = [
  { value: "no_time", label: "I do not have time at the moment" },
  { value: "outside_expertise", label: "The topic is outside my expertise" },
  { value: "conflict_of_interest", label: "I have a conflict of interest" },
  { value: "other", label: "Another reason" },
];

export const DECLINE_REASON_LABELS: Record<string, string> = Object.fromEntries(
  DECLINE_REASONS.map((r) => [r.value, r.label]),
);

/** How decisions look on buttons: the ones that end things are red, the ones that move on are filled. */
export const DECISION_LOOK: Record<string, { color: string; variant: "filled" | "light" | "outline" }> = {
  send_to_review: { color: "indigo", variant: "filled" },
  new_round: { color: "indigo", variant: "light" },
  accept: { color: "teal", variant: "filled" },
  request_revisions: { color: "orange", variant: "light" },
  resubmit: { color: "orange", variant: "light" },
  decline: { color: "red", variant: "light" },
  reinstate: { color: "gray", variant: "light" },
  recommend_accept: { color: "teal", variant: "light" },
  recommend_revisions: { color: "orange", variant: "light" },
  recommend_resubmit: { color: "orange", variant: "light" },
  recommend_decline: { color: "red", variant: "light" },
};

/** Today as YYYY-MM-DD, for date inputs. */
export function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addDays(base: Date, days: number): Date {
  const result = new Date(base);
  result.setUTCDate(result.getUTCDate() + days);
  return result;
}
