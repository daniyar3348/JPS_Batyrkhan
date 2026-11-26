import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../../test/render";
import { SubmissionSettingsPage } from "./SubmissionSettingsPage";

const SETTINGS = {
  checklist: ["Not published before", "Follows the guidelines"],
  author_guidelines: "Write clearly.",
  max_file_size_mb: 50,
  abstract_max_words: 300,
  keywords_min: 3,
  keywords_max: 8,
  number_prefix: "JRN",
  similarity: { enabled: false, threshold_percent: 30 },
  version: 4,
  similarity_available: true,
  allowed_file_types: { manuscript: [".docx", ".pdf"] },
};

describe("SubmissionSettingsPage", () => {
  it("keeps each checklist item with its text when items move, and saves plain strings", async () => {
    const calls = mockApi({
      "GET /api/v1/journal/submission-settings": () => json(200, SETTINGS),
      "PUT /api/v1/journal/submission-settings": async (request) =>
        json(200, { ...SETTINGS, ...(await request.json()), version: 5 }),
    });
    renderPage(<SubmissionSettingsPage />);

    const first = await screen.findByRole("textbox", { name: "Checklist item 1" });
    expect(first).toHaveValue("Not published before");

    await userEvent.click(screen.getAllByRole("button", { name: "Move down" })[0] as HTMLElement);
    expect(screen.getByRole("textbox", { name: "Checklist item 1" })).toHaveValue("Follows the guidelines");
    expect(screen.getByRole("textbox", { name: "Checklist item 2" })).toHaveValue("Not published before");

    await userEvent.click(screen.getByRole("button", { name: "Add item" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Checklist item 3" }), "  Data is available  ");
    await userEvent.click(screen.getByRole("button", { name: "Add item" }));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"4"');
    expect(put?.body).toMatchObject({
      checklist: ["Follows the guidelines", "Not published before", "Data is available"],
      number_prefix: "JRN",
    });
  });

  it("does not send a prefix the server would refuse", async () => {
    const calls = mockApi({ "GET /api/v1/journal/submission-settings": () => json(200, SETTINGS) });
    renderPage(<SubmissionSettingsPage />);

    const prefix = await screen.findByRole("textbox", { name: "Manuscript number prefix" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "j");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByText("2–10 capital letters or digits")).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "PUT")).toHaveLength(0);
  });
});
