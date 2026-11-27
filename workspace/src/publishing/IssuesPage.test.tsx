import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { IssuesPage } from "./IssuesPage";

/** Signed in with the right to create and publish issues. */
const MANAGER = {
  user: { id: 1, email: "chief@example.org", full_name: "Daniyar Chief" },
  roles: ["editor_in_chief"],
  capabilities: ["publishing.manage", "submissions.view_all"],
  csrf_token: "token",
};

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
  row_version: 1,
  article_count: 2,
};

const PUBLISHED = {
  ...ISSUE,
  id: 2,
  number: "1",
  label: "Vol. 1 No. 1 (2026)",
  status: "published",
  is_current: true,
  published_at: "2026-06-01T09:00:00Z",
  article_count: 5,
};

describe("IssuesPage", () => {
  it("lists future issues first, with their state", async () => {
    mockApi({
      "GET /api/v1/me": () => json(200, MANAGER),
      "GET /api/v1/issues": () => json(200, [ISSUE, PUBLISHED]),
    });
    renderPage(<IssuesPage />);

    const rows = await screen.findAllByRole("row");
    expect(within(rows[1] as HTMLElement).getByRole("link", { name: "Vol. 1 No. 2 (2026)" })).toHaveAttribute(
      "href",
      "/publishing/issues/3",
    );
    expect(within(rows[1] as HTMLElement).getByText("Future")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Published")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Current")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("5")).toBeInTheDocument();
  });

  it("creates an issue and opens it", async () => {
    const calls = mockApi({
      "GET /api/v1/me": () => json(200, MANAGER),
      "GET /api/v1/issues": () => json(200, []),
      "POST /api/v1/issues": () => json(201, { ...ISSUE, id: 9, articles: [] }),
    });
    const { router } = renderPage(<IssuesPage />, { path: "/publishing/issues" });

    expect(await screen.findByText(/No issues yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New issue" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Volume" }), "1");
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Number" }), "2");
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Title" }), "  Special issue ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create issue" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/publishing/issues/9"));
    const post = calls.find((call) => call.method === "POST");
    expect(post?.body).toEqual({
      volume: 1,
      number: "2",
      year: new Date().getFullYear(),
      title: "Special issue",
      description: "",
    });
  });

  it("asks for at least something that identifies the issue", async () => {
    const calls = mockApi({
      "GET /api/v1/me": () => json(200, MANAGER),
      "GET /api/v1/issues": () => json(200, []),
    });
    renderPage(<IssuesPage />);

    await userEvent.click(await screen.findByRole("button", { name: "New issue" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.clear(within(dialog).getByRole("textbox", { name: "Year" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create issue" }));

    expect(
      await within(dialog).findByText("Give the issue a volume, number, year or title"),
    ).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });
});
