import type { PublishingOut } from "@jps/api-client";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { PublicationPanel } from "./PublicationPanel";

const ISSUE = {
  id: 3,
  volume: 1,
  number: "1",
  year: 2026,
  title: "",
  description: "",
  label: "Vol. 1 No. 1 (2026)",
  status: "future",
  is_current: false,
  published_at: null,
  row_version: 1,
  article_count: 0,
};

const GALLEY = {
  id: 5,
  label: "PDF",
  position: 0,
  file: {
    id: 11,
    genre: "galley" as const,
    name: "article.pdf",
    original_name: "article.pdf",
    status: "ready",
    rejection_reason: null,
    size_bytes: 20480,
    content_type: "application/pdf",
    uploaded_at: "2026-11-27T10:00:00Z",
    download_url: "/api/v1/submissions/9/galleys/5/file/11/download",
    metadata_removed: null,
  },
};

function publishing(changes: Partial<PublishingOut> = {}): PublishingOut {
  return {
    submission_id: 9,
    stage: "production",
    status: "queued",
    publication: {
      id: 21,
      version: 1,
      status: "queued",
      row_version: 4,
      doi: "10.12345/jrn.2026.0001",
      doi_url: "https://doi.org/10.12345/jrn.2026.0001",
      url_path: null,
      slug: "jrn-2026-0001",
      article_url: "https://journal.example.org/articles/jrn-2026-0001",
      pages: "",
      license_url: "https://creativecommons.org/licenses/by/4.0/",
      copyright_holder: "",
      copyright_year: null,
      issue_id: null,
      version_note: "",
      published_at: null,
    },
    issue: null,
    galleys: [],
    checks: [
      { key: "metadata", label: "Title, abstract and authors", ok: true, detail: "" },
      { key: "issue", label: "Issue", ok: false, detail: "Choose the issue the article appears in." },
      {
        key: "galleys",
        label: "Galleys",
        ok: false,
        detail: "Add the PDF (or another file) readers download.",
      },
    ],
    action: "schedule",
    ready: false,
    fee_settled: true,
    can_edit: true,
    can_edit_galleys: true,
    can_publish: true,
    can_unschedule: false,
    can_create_version: false,
    can_discard_version: false,
    versions: [{ id: 21, version: 1, status: "queued", published_at: null, version_note: "" }],
    doi_enabled: true,
    can_assign_doi: false,
    can_deposit: false,
    deposits: [],
    ...changes,
  };
}

const READY = publishing({
  ready: true,
  issue: ISSUE,
  galleys: [GALLEY],
  publication: { ...publishing().publication, issue_id: 3, pages: "1-12" },
  checks: [
    { key: "metadata", label: "Title, abstract and authors", ok: true, detail: "" },
    { key: "issue", label: "Issue", ok: true, detail: ISSUE.label },
    { key: "galleys", label: "Galleys", ok: true, detail: "PDF" },
  ],
});

afterEach(() => vi.restoreAllMocks());

describe("PublicationPanel", () => {
  it("shows what is missing and does not let the editor publish yet", async () => {
    mockApi({
      "GET /api/v1/submissions/9/publishing": () => json(200, publishing()),
      "GET /api/v1/issues": () => json(200, [ISSUE]),
    });
    renderPage(<PublicationPanel submissionId={9} />);
    expect(await screen.findByText("Choose the issue the article appears in.")).toBeInTheDocument();
    expect(screen.getByText("Add the PDF (or another file) readers download.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schedule for publication" })).toBeDisabled();
    expect(screen.getByText("The article will appear when its issue is published.")).toBeInTheDocument();
    expect(screen.getByText("No galleys yet.")).toBeInTheDocument();
    expect(screen.getByText("10.12345/jrn.2026.0001")).toBeInTheDocument();
  });

  it("schedules the article after confirmation", async () => {
    const calls = mockApi({
      "GET /api/v1/submissions/9/publishing": () => json(200, READY),
      "GET /api/v1/issues": () => json(200, [ISSUE]),
      "POST /api/v1/submissions/9/publish": () =>
        json(200, {
          ...READY,
          status: "scheduled",
          action: null,
          can_edit: false,
          can_edit_galleys: false,
          can_unschedule: true,
          publication: { ...READY.publication, status: "scheduled" },
        }),
    });
    renderPage(<PublicationPanel submissionId={9} />);
    const button = await screen.findByRole("button", { name: "Schedule for publication" });
    expect(button).toBeEnabled();
    expect(screen.getByText("article.pdf")).toBeInTheDocument();
    await userEvent.click(button);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(await screen.findByText(`Scheduled in ${ISSUE.label}`)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual([
      "/api/v1/submissions/9/publish",
    ]);
    expect(screen.getByRole("button", { name: "Unschedule" })).toBeInTheDocument();
  });

  it("saves only the changed details, with the version it edited", async () => {
    const calls = mockApi({
      "GET /api/v1/submissions/9/publishing": () => json(200, READY),
      "GET /api/v1/issues": () => json(200, [ISSUE]),
      "PATCH /api/v1/submissions/9/publishing": () =>
        json(200, { ...READY, publication: { ...READY.publication, pages: "1-14", row_version: 5 } }),
    });
    renderPage(<PublicationPanel submissionId={9} />);
    const pages = await screen.findByLabelText("Pages");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(pages);
    await userEvent.type(pages, "1-14");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({ pages: "1-14" });
    expect(patch?.headers.get("if-match")).toBe('"4"');
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
  });
});
