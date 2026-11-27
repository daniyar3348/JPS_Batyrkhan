import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { ReviewPage } from "./ReviewPage";

const QUESTIONS = [
  {
    id: "summary",
    type: "textarea",
    label: "Summarize the manuscript",
    help: "",
    options: [],
    required: true,
    visible_to_author: true,
  },
  {
    id: "originality",
    type: "choice",
    label: "How original is the work?",
    help: "",
    options: ["Highly original", "Not original"],
    required: true,
    visible_to_author: false,
  },
];

const REVIEW = {
  id: 7,
  status: "invited",
  method: "double_blind",
  round_number: 1,
  invited_at: "2026-11-20T10:00:00Z",
  response_due: "2026-11-27",
  review_due: "2026-12-25",
  overdue: false,
  responded_at: null,
  completed_at: null,
  can_edit: false,
  manuscript: {
    title: "Soil carbon in the steppe",
    subtitle: "",
    abstract: "We measured soil carbon.",
    keywords: ["soil carbon"],
    section: { id: 1, title: "Research Articles", abbreviation: "ART" },
    references: "",
    authors: null,
    comments_for_editor: null,
  },
  files: [],
  guidelines: "Be kind and specific.",
  questions: QUESTIONS,
  answers: {},
  recommendation: null,
  comments_for_author: "",
  comments_for_editor: "",
  competing_interests: "",
  attachments: [],
  row_version: 1,
};

const FILE = {
  id: 3,
  genre: "manuscript",
  name: "manuscript.pdf",
  original_name: "manuscript.pdf",
  status: "ready",
  rejection_reason: null,
  size_bytes: 2048,
  content_type: "application/pdf",
  uploaded_at: "2026-11-20T10:00:00Z",
  download_url: "/api/v1/reviews/7/files/3/download",
  metadata_removed: true,
};

describe("ReviewPage", () => {
  it("hides the authors in a double-blind request, and accepting sends competing interests", async () => {
    const calls = mockApi({
      "GET /api/v1/reviews/7": () => json(200, REVIEW),
      "POST /api/v1/reviews/7/accept": () =>
        json(200, { ...REVIEW, status: "accepted", can_edit: true, files: [FILE] }),
    });
    renderPage(<ReviewPage />, { path: "/reviews/:id", url: "/reviews/7" });

    expect(await screen.findByText("Soil carbon in the steppe")).toBeInTheDocument();
    expect(
      screen.getByText("The authors' names are hidden: this is a double-blind review."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("You will get the manuscript files once you accept the request."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Cover letter")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Competing interests" }), "None");
    await userEvent.click(screen.getByRole("button", { name: "Accept and start reviewing" }));

    await waitFor(() => expect(calls.some((call) => call.path === "/api/v1/reviews/7/accept")).toBe(true));
    expect(calls.find((call) => call.path === "/api/v1/reviews/7/accept")?.body).toEqual({
      competing_interests: "None",
    });
    // Now the files and the review form are there.
    expect(await screen.findByRole("link", { name: /manuscript\.pdf/ })).toHaveAttribute(
      "href",
      "/api/v1/reviews/7/files/3/download",
    );
    expect(screen.getByRole("textbox", { name: "Summarize the manuscript" })).toBeInTheDocument();
    expect(screen.getByText("Only the editors see this answer.")).toBeInTheDocument();
  });

  it("shows the server's complaints next to the questions when a review is incomplete", async () => {
    const calls = mockApi({
      "GET /api/v1/reviews/7": () =>
        json(200, { ...REVIEW, status: "accepted", can_edit: true, files: [FILE] }),
      "POST /api/v1/reviews/7/submit": () =>
        json(422, {
          code: "review_incomplete",
          detail: "The review is not complete yet.",
          errors: [
            { field: "answers.originality", message: "This question needs an answer" },
            { field: "recommendation", message: "Choose a recommendation" },
          ],
        }),
    });
    renderPage(<ReviewPage />, { path: "/reviews/:id", url: "/reviews/7" });

    await userEvent.type(
      await screen.findByRole("textbox", { name: "Summarize the manuscript" }),
      "A sound study.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send review" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send" }));

    expect(await screen.findByText("This question needs an answer")).toBeInTheDocument();
    expect(screen.getByText("Choose a recommendation")).toBeInTheDocument();
    const sent = calls.find((call) => call.path === "/api/v1/reviews/7/submit");
    // Empty answers are not sent; the typed one is.
    expect(sent?.body).toEqual({
      answers: { summary: "A sound study." },
      recommendation: null,
      comments_for_author: "",
      comments_for_editor: "",
    });
  });
});
