import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { SitePageEditor, slugify } from "./SitePageEditor";

const PAGE = {
  id: 5,
  slug: "aims-scope",
  title: "Aims & Scope",
  body: "## Topics\n\n- Soil science",
  position: 0,
  in_menu: true,
  is_published: true,
  row_version: 3,
  updated_at: "2026-11-27T10:00:00Z",
};

describe("SitePageEditor", () => {
  it("makes the address from the title", () => {
    expect(slugify("Aims & Scope")).toBe("aims-scope");
    expect(slugify("  Peer-review policy (2026) ")).toBe("peer-review-policy-2026");
  });

  it("creates a page, with the address taken from the title", async () => {
    const calls = mockApi({
      "POST /api/v1/site/pages": async (request) => json(201, { ...PAGE, ...(await request.json()) }),
      "GET /api/v1/site/pages/5": () => json(200, PAGE),
    });
    renderPage(<SitePageEditor />, { path: "/site/pages/:id", url: "/site/pages/new" });

    await userEvent.type(screen.getByRole("textbox", { name: /^Title/ }), "Aims & Scope");
    expect(screen.getByRole("textbox", { name: /^Address/ })).toHaveValue("aims-scope");
    await userEvent.type(screen.getByRole("textbox", { name: "Text" }), "## Topics");
    await userEvent.click(screen.getByRole("switch", { name: /Published/ }));
    await userEvent.click(screen.getByText("Preview"));
    expect(await screen.findByRole("heading", { name: "Topics" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create page" }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      title: "Aims & Scope",
      slug: "aims-scope",
      position: 0,
      in_menu: true,
      is_published: true,
      body: "## Topics",
    });
    // The editor moves to the new page's address.
    await waitFor(() => expect(calls.some((call) => call.path === "/api/v1/site/pages/5")).toBe(true));
  });

  it("saves changes with the page's version", async () => {
    const calls = mockApi({
      "GET /api/v1/site/pages/5": () => json(200, PAGE),
      "PUT /api/v1/site/pages/5": async (request) =>
        json(200, { ...PAGE, ...(await request.json()), row_version: 4 }),
    });
    renderPage(<SitePageEditor />, { path: "/site/pages/:id", url: "/site/pages/5" });

    const title = await screen.findByRole("textbox", { name: /^Title/ });
    await userEvent.clear(title);
    await userEvent.type(title, "Aims and scope");
    // Editing an existing page's title does not move its address.
    expect(screen.getByRole("textbox", { name: /^Address/ })).toHaveValue("aims-scope");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"3"');
    expect(put?.body).toMatchObject({ title: "Aims and scope", slug: "aims-scope" });
  });
});
