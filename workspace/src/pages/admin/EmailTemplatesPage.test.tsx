import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../../test/render";
import { EmailTemplatesPage } from "./EmailTemplatesPage";

const REQUEST = {
  key: "review_request",
  group: "Peer review",
  name: "Review request",
  description: "Invites a reviewer.",
  recipient: "Reviewer",
  subject: "Invitation to review for {journalName}",
  body: "Dear {recipientName},\n\nPlease review.",
  default_subject: "Invitation to review for {journalName}",
  default_body: "Dear {recipientName},\n\nPlease review.",
  is_custom: false,
  updated_at: null,
  variables: [
    { name: "recipientName", description: "Full name of the person the e-mail is sent to" },
    { name: "reviewDueDate", description: "Date by which the review is due" },
  ],
};

const RECEIVED = {
  ...REQUEST,
  key: "submission_received",
  group: "Submission",
  name: "Submission received",
  recipient: "Submitting author",
  is_custom: true,
  updated_at: "2026-11-20T10:00:00Z",
};

describe("EmailTemplatesPage", () => {
  it("lists templates by group and marks the journal's own wording", async () => {
    mockApi({ "GET /api/v1/journal/email-templates": () => json(200, [REQUEST, RECEIVED]) });
    renderPage(<EmailTemplatesPage />);

    expect(await screen.findByRole("heading", { name: "Peer review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Submission" })).toBeInTheDocument();
    const row = screen.getByText("Submission received").closest("tr") as HTMLElement;
    expect(within(row).getByText("Customised")).toBeInTheDocument();
  });

  it("inserts placeholders, saves the wording and shows the server's complaint next to the field", async () => {
    let attempt = 0;
    const calls = mockApi({
      "GET /api/v1/journal/email-templates": () => json(200, [REQUEST]),
      "PUT /api/v1/journal/email-templates/review_request": async (request) => {
        attempt += 1;
        if (attempt === 1) {
          return json(422, {
            code: "unknown_placeholder",
            detail: "The template uses placeholders this e-mail does not have.",
            errors: [{ field: "subject", message: "Unknown placeholder: {submitterName}" }],
          });
        }
        return json(200, { ...REQUEST, ...(await request.json()), is_custom: true });
      },
    });
    renderPage(<EmailTemplatesPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Edit Review request" }));
    const dialog = await screen.findByRole("dialog");
    const subject = within(dialog).getByRole("textbox", { name: "Subject" });
    await userEvent.clear(subject);
    await userEvent.type(subject, "Review for {{submitterName}");

    const body = within(dialog).getByRole("textbox", { name: "Text" });
    await userEvent.click(body); // the cursor goes to the end of the text
    await userEvent.click(within(dialog).getByRole("button", { name: "Insert {reviewDueDate}" }));
    expect(body).toHaveValue("Dear {recipientName},\n\nPlease review.{reviewDueDate}");

    await userEvent.click(within(dialog).getByRole("button", { name: "Save template" }));
    expect(await within(dialog).findByText("Unknown placeholder: {submitterName}")).toBeInTheDocument();
    const first = calls.find((call) => call.method === "PUT");
    expect(first?.body).toEqual({
      subject: "Review for {submitterName}",
      body: "Dear {recipientName},\n\nPlease review.{reviewDueDate}",
    });

    await userEvent.clear(subject);
    await userEvent.type(subject, "Review request");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save template" }));
    await waitFor(() => expect(calls.filter((call) => call.method === "PUT")).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
