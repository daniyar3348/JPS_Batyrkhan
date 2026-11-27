import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { IssuePage } from "./IssuePage";

/** Signed in with the right to create and publish issues. */
const MANAGER = {
  user: { id: 1, email: "chief@example.org", full_name: "Daniyar Chief" },
  roles: ["editor_in_chief"],
  capabilities: ["publishing.manage", "submissions.view_all"],
  csrf_token: "token",
};

const SECTION = { id: 1, title: "Research Articles", abbreviation: "ART" };
const ARTICLES = [
  {
    submission_id: 11,
    number: "JRN-2026-0011",
    title: "Editorial workflows",
    authors: "Asel Author",
    section: SECTION,
    status: "scheduled",
    pages: "1-12",
    doi: "10.12345/jrn.2026.0011",
    fee_settled: true,
  },
  {
    submission_id: 12,
    number: "JRN-2026-0012",
    title: "Peer review in practice",
    authors: "Bolat Writer",
    section: SECTION,
    status: "queued",
    pages: "",
    doi: null,
    fee_settled: false,
  },
];
const ISSUE = {
  id: 3,
  volume: 1,
  number: "2",
  year: 2026,
  title: "",
  description: "",
  label: "Vol. 1 No. 2 (2026)",
  status: "future",
  is_current: false,
  published_at: null,
  row_version: 4,
  article_count: 2,
  articles: ARTICLES,
};

const page = () => renderPage(<IssuePage />, { path: "/publishing/issues/:id", url: "/publishing/issues/3" });

describe("IssuePage", () => {
  it("shows the articles in reading order and their state", async () => {
    mockApi({
      "GET /api/v1/me": () => json(200, MANAGER),
      "GET /api/v1/issues/3": () => json(200, ISSUE),
    });
    page();

    expect(await screen.findByRole("heading", { name: "Vol. 1 No. 2 (2026)" })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    const first = within(rows[1] as HTMLElement);
    expect(first.getByRole("link", { name: "JRN-2026-0011" })).toHaveAttribute("href", "/submissions/11");
    expect(first.getByText("Scheduled")).toBeInTheDocument();
    expect(first.getByText("10.12345/jrn.2026.0011")).toBeInTheDocument();
    const second = within(rows[2] as HTMLElement);
    expect(second.getByText("Not scheduled")).toBeInTheDocument();
    expect(second.getByText("Fee not settled")).toBeInTheDocument();
    // An issue with articles cannot be deleted; a future one can be published.
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make current" })).not.toBeInTheDocument();
  });

  it("moves an article within its section", async () => {
    const calls = mockApi({
      "GET /api/v1/me": () => json(200, MANAGER),
      "GET /api/v1/issues/3": () => json(200, ISSUE),
      "PUT /api/v1/issues/3/order": () => json(200, { ...ISSUE, articles: [ARTICLES[1], ARTICLES[0]] }),
    });
    page();

    expect(await screen.findByRole("button", { name: "Move Editorial workflows up" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Move Peer review in practice up" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ submission_ids: [12, 11] });
    await waitFor(() =>
      expect(
        within(screen.getAllByRole("row")[1] as HTMLElement).getByText("Peer review in practice"),
      ).toBeInTheDocument(),
    );
  });

  it("publishes the issue, warning about articles that are not scheduled", async () => {
    const published = {
      ...ISSUE,
      status: "published",
      is_current: false,
      published_at: "2026-11-27T10:00:00Z",
      articles: [{ ...ARTICLES[0], status: "published" }, ARTICLES[1]],
    };
    const calls = mockApi({
      "GET /api/v1/me": () => json(200, MANAGER),
      "GET /api/v1/issues/3": () => json(200, ISSUE),
      "POST /api/v1/issues/3/publish": () => json(200, published),
    });
    page();

    await userEvent.click(await screen.findByRole("button", { name: "Publish issue" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/One article in this issue is not scheduled/)).toBeInTheDocument();
    const current = within(dialog).getByRole("checkbox", { name: /Make it the current issue/ });
    expect(current).toBeChecked();
    await userEvent.click(current);
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish issue" }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({ make_current: false });
    // Published, not current: it can be made current now.
    expect(await screen.findByRole("button", { name: "Make current" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish issue" })).not.toBeInTheDocument();
  });

  it("saves the details with the issue's version", async () => {
    const calls = mockApi({
      "GET /api/v1/me": () => json(200, MANAGER),
      "GET /api/v1/issues/3": () => json(200, ISSUE),
      "PUT /api/v1/issues/3": async (request) =>
        json(200, {
          ...ISSUE,
          ...(await request.json()),
          row_version: 5,
          label: "Vol. 1 No. 2 (2026): Methods",
        }),
    });
    page();

    await userEvent.type(await screen.findByRole("textbox", { name: "Title" }), "Methods");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"4"');
    expect(put?.body).toEqual({ volume: 1, number: "2", year: 2026, title: "Methods", description: "" });
    expect(await screen.findByRole("heading", { name: "Vol. 1 No. 2 (2026): Methods" })).toBeInTheDocument();
  });
});
