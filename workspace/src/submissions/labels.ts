import type { Genre, SubmissionSummary } from "@jps/api-client";

export const GENRE_LABELS: Record<Genre, string> = {
  manuscript: "Manuscript",
  title_page: "Title page",
  figure: "Figure",
  table: "Table",
  supplementary: "Supplementary material",
  cover_letter: "Cover letter",
  galley: "Galley",
};

export const GENRE_HELP: Record<Genre, string> = {
  manuscript: "The full text. For anonymous review, remove the authors' names from it.",
  title_page: "Authors, affiliations and acknowledgements, kept separate from an anonymous manuscript.",
  figure: "Figures in high resolution, one file each.",
  table: "Tables that are too large for the manuscript.",
  supplementary: "Data, code or other material that supports the article.",
  cover_letter: "A letter to the editor (you can also write it in the first step).",
  galley: "The typeset file readers download. Added in production.",
};

/** Kinds of file a person chooses when uploading (galleys are added on the publication screen). */
export const UPLOAD_GENRES = (Object.keys(GENRE_LABELS) as Genre[]).filter((genre) => genre !== "galley");

interface StatusLook {
  label: string;
  color: string;
}

/** What a submission's status means to the people who see it. */
export function statusLook(submission: Pick<SubmissionSummary, "status" | "stage">): StatusLook {
  switch (submission.status) {
    case "draft":
      return { label: "Draft", color: "gray" };
    case "queued":
      return submission.stage === "submission"
        ? { label: "Submitted", color: "blue" }
        : { label: `In ${submission.stage}`, color: "indigo" };
    case "scheduled":
      return { label: "Scheduled", color: "teal" };
    case "published":
      return { label: "Published", color: "green" };
    case "declined":
      return { label: "Declined", color: "red" };
    case "withdrawn":
      return { label: "Withdrawn", color: "gray" };
    default:
      return { label: submission.status, color: "gray" };
  }
}

export const FILE_STATUS: Record<string, StatusLook> = {
  pending_upload: { label: "Uploading", color: "gray" },
  processing: { label: "Checking", color: "blue" },
  ready: { label: "Ready", color: "teal" },
  rejected: { label: "Not accepted", color: "red" },
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}
