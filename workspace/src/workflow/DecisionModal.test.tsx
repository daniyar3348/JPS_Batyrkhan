import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { DecisionModal } from "./DecisionModal";

const FILE = {
  id: 11,
  genre: "manuscript",
  name: "manuscript.pdf",
  original_name: "manuscript.pdf",
  status: "ready",
  rejection_reason: null,
  size_bytes: 1000,
  content_type: "application/pdf",
  uploaded_at: "2026-11-27T10:00:00Z",
  download_url: "/api/v1/submissions/5/files/11/download",
  metadata_removed: null,
};
const COVER = { ...FILE, id: 12, genre: "cover_letter", name: "cover.pdf" };
const OPTION = {
  decision: "send_to_review" as const,
  label: "Send to review",
  description: "Start the first round of peer review.",
  is_recommendation: false,
  needs_files: true,
  needs_reason: false,
  has_letter: true,
};

describe("DecisionModal", () => {
  it("sends the chosen files and the letter as the editor changed it", async () => {
    const calls = mockApi({
      "POST /api/v1/submissions/5/decisions/preview": () =>
        json(200, {
          option: OPTION,
          letter: {
            subject: "Under review",
            body: "Dear Asel, it is under review.",
            to: ["asel@example.org"],
          },
          candidate_files: [FILE, COVER],
        }),
      "POST /api/v1/submissions/5/decisions": () => json(201, { rounds: [], decisions: [] }),
    });
    renderPage(<DecisionModal submissionId={5} option={OPTION} onClose={() => {}} />);

    // The manuscript is chosen for reviewers; the cover letter is not.
    expect(await screen.findByRole("checkbox", { name: /manuscript\.pdf/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /cover\.pdf/ })).not.toBeChecked();
    expect(screen.getByText("To: asel@example.org")).toBeInTheDocument();

    const message = screen.getByRole("textbox", { name: "Message" });
    await userEvent.clear(message);
    await userEvent.type(message, "Dear Asel, good news.");
    await userEvent.click(screen.getByRole("button", { name: "Record: Send to review" }));

    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/submissions/5/decisions")).toBe(true));
    const sent = calls.find((c) => c.path === "/api/v1/submissions/5/decisions");
    expect(sent?.body).toEqual({
      decision: "send_to_review",
      review_file_ids: [11],
      reason: "",
      letter: { send: true, subject: "Under review", body: "Dear Asel, good news." },
    });
  });

  it("cannot be recorded without files for the reviewers", async () => {
    mockApi({
      "POST /api/v1/submissions/5/decisions/preview": () =>
        json(200, { option: OPTION, letter: null, candidate_files: [FILE] }),
    });
    renderPage(<DecisionModal submissionId={5} option={OPTION} onClose={() => {}} />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /manuscript\.pdf/ }));
    expect(screen.getByRole("button", { name: "Record: Send to review" })).toBeDisabled();
  });
});
