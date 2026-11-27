import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderPage } from "../test/render";
import { SiteSettingsPage } from "./SiteSettingsPage";

const SETTINGS = {
  tagline: "Open-access research",
  publication_frequency: "",
  editorial_board: [
    {
      name: "Daniyar Chief",
      role: "Editor-in-Chief",
      affiliation: "Demo University",
      country: "Kazakhstan",
      orcid: null,
    },
  ],
  version: 4,
};

function withVersion(body: unknown, version: number): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ETag: `"${version}"` },
  });
}

describe("SiteSettingsPage", () => {
  it("adds a board member and saves with the journal's version", async () => {
    const calls = mockApi({
      "GET /api/v1/journal/site-settings": () => withVersion(SETTINGS, 4),
      "PUT /api/v1/journal/site-settings": async (request) =>
        withVersion({ ...(await request.json()), version: 5 }, 5),
    });
    renderPage(<SiteSettingsPage />);

    expect(await screen.findByDisplayValue("Daniyar Chief")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add a member" }));
    const names = screen.getAllByRole("textbox", { name: /^Name/ });
    await userEvent.type(names[1] as HTMLElement, "Elena Editor");
    await userEvent.type(
      screen.getAllByRole("textbox", { name: /^Affiliation/ })[1] as HTMLElement,
      "Satbayev University",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"4"');
    expect(put?.body).toEqual({
      tagline: "Open-access research",
      publication_frequency: "",
      editorial_board: [
        {
          name: "Daniyar Chief",
          role: "Editor-in-Chief",
          affiliation: "Demo University",
          country: "Kazakhstan",
          orcid: null,
        },
        {
          name: "Elena Editor",
          role: "Editorial Board Member",
          affiliation: "Satbayev University",
          country: "",
          orcid: null,
        },
      ],
    });
  });
});
