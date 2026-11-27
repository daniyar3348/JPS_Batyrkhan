import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi, renderPage } from "../test/render";
import { PublishingSettingsPage } from "./PublishingSettingsPage";

const SETTINGS = {
  settings: {
    site_url: "",
    license_url: "https://creativecommons.org/licenses/by/4.0/",
    copyright_holder: "authors",
    doi: {
      enabled: false,
      prefix: "",
      suffix_pattern: "{journal}.{year}.{number}",
      depositor_name: "",
      depositor_email: "",
    },
  },
  crossref_mode: "test",
  crossref_account_configured: true,
  site_revalidation_configured: false,
  problems: [] as string[],
  suffix_placeholders: { "{journal}": "The journal's abbreviation", "{number}": "The manuscript's number" },
  example_doi: null as string | null,
};

function withVersion(body: unknown, version: number): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ETag: `"${version}"` },
  });
}

describe("PublishingSettingsPage", () => {
  it("saves with the journal's version and shows what is still missing", async () => {
    const calls = mockApi({
      "GET /api/v1/journal/publishing-settings": () => withVersion(SETTINGS, 7),
      "PUT /api/v1/journal/publishing-settings": async (request) =>
        withVersion(
          {
            ...SETTINGS,
            settings: await request.json(),
            example_doi: "10.12345/jrn.2026.0042",
            problems: ["The journal has no ISSN: Crossref needs one for journal articles."],
          },
          8,
        ),
    });
    renderPage(<PublishingSettingsPage />);

    expect(
      await screen.findByText("Crossref test system: deposits are checked but register nothing."),
    ).toBeInTheDocument();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Address of the site" }),
      "https://journal.example.org",
    );
    await userEvent.click(screen.getByRole("switch", { name: /Assign DOIs to articles/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "DOI prefix" }), "10.12345");
    await userEvent.type(screen.getByRole("textbox", { name: "Depositor name" }), "Journal office");
    await userEvent.type(screen.getByRole("textbox", { name: "Depositor e-mail" }), "office@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"7"');
    expect(put?.body).toEqual({
      site_url: "https://journal.example.org",
      license_url: "https://creativecommons.org/licenses/by/4.0/",
      copyright_holder: "authors",
      doi: {
        enabled: true,
        prefix: "10.12345",
        suffix_pattern: "{journal}.{year}.{number}",
        depositor_name: "Journal office",
        depositor_email: "office@example.org",
      },
    });
    expect(await screen.findByText("DOIs cannot be registered yet")).toBeInTheDocument();
    expect(screen.getByText(/The journal has no ISSN/)).toBeInTheDocument();
    expect(screen.getByText("10.12345/jrn.2026.0042")).toBeInTheDocument();

    // The next save sends the new version.
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.filter((call) => call.method === "PUT")).toHaveLength(2));
    expect(calls.filter((call) => call.method === "PUT")[1]?.headers.get("If-Match")).toBe('"8"');
  });

  it("does not send a prefix Crossref would not give", async () => {
    const calls = mockApi({ "GET /api/v1/journal/publishing-settings": () => withVersion(SETTINGS, 7) });
    renderPage(<PublishingSettingsPage />);

    await userEvent.click(await screen.findByRole("switch", { name: /Assign DOIs to articles/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "DOI prefix" }), "12345");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("A DOI prefix looks like 10.12345")).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "PUT")).toHaveLength(0);
  });
});
