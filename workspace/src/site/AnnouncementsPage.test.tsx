import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { AnnouncementsPage } from "./AnnouncementsPage";

const DRAFT = {
  id: 2,
  title: "Call for papers",
  summary: "Submissions are open.",
  body: "Send by **1 March**.",
  published_at: null,
  row_version: 1,
  updated_at: "2026-11-27T10:00:00Z",
};

describe("AnnouncementsPage", () => {
  it("publishes a draft", async () => {
    let published = false;
    const calls = mockApi({
      "GET /api/v1/site/announcements": () =>
        json(200, [published ? { ...DRAFT, published_at: "2026-11-27T11:00:00Z", row_version: 2 } : DRAFT]),
      "PUT /api/v1/site/announcements/2": async (request) => {
        published = true;
        return json(200, { ...DRAFT, ...(await request.json()), published_at: "2026-11-27T11:00:00Z" });
      },
    });
    renderPage(<AnnouncementsPage />);

    expect(await screen.findByText("Draft")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit Call for papers" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("switch", { name: /Published/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"1"');
    expect(put?.body).toEqual({
      title: "Call for papers",
      summary: "Submissions are open.",
      body: "Send by **1 March**.",
      published: true,
    });
    expect(await screen.findByText(/^Published /)).toBeInTheDocument();
  });
});
