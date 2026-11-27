import type { PublicArticle, PublicJournalOut } from "@jps/api-client";
import { describe, expect, it } from "vitest";
import { dublinCoreTags, highwireTags, jsonForScript, scholarlyArticleLd } from "./scholar";

const JOURNAL = {
  name: "Journal of Applied Science",
  abbreviation: "J Appl Sci",
  publisher: "Demo Journal LLP",
  issn_online: "2958-0412",
  issn_print: null,
} as PublicJournalOut;

const ARTICLE = {
  slug: "jrn-2026-0001",
  title: "Grazing pressure and soil carbon",
  subtitle: "",
  abstract: "We measured soil carbon.",
  keywords: ["soil carbon", "grazing"],
  authors: [
    {
      name: "Asel Nurlanova",
      given_name: "Asel",
      family_name: "Nurlanova",
      affiliation: "Nazarbayev University",
      orcid: "0000-0002-1825-0097",
      country: "KZ",
      is_corresponding: true,
    },
    {
      name: "Madina",
      given_name: "Madina",
      family_name: "",
      affiliation: "",
      orcid: null,
      country: null,
      is_corresponding: false,
    },
  ],
  issue: {
    id: 1,
    volume: 1,
    number: "2",
    year: 2026,
    title: "",
    label: "Vol. 1 No. 2 (2026)",
    published_at: "2026-11-27T07:45:00Z",
  },
  pages: "1-14",
  doi: "10.99999/dj.2026.0001",
  doi_url: "https://doi.org/10.99999/dj.2026.0001",
  license_url: "https://creativecommons.org/licenses/by/4.0/",
  references: ["Smith J. (2020). A study."],
  dates: { submitted: null, accepted: null, published: "2026-11-27T07:45:00+00:00", updated: null },
  section: { id: 1, title: "Research Articles" },
} as unknown as PublicArticle;

const PAGE = "https://journal.example.org/articles/jrn-2026-0001";

describe("Google Scholar tags", () => {
  it("puts each author's institution right after the author", () => {
    const tags = highwireTags(ARTICLE, JOURNAL, { page: PAGE, pdf: `${PAGE}/download/7` });
    const names = tags.map(([name]) => name);
    expect(names.slice(0, 5)).toEqual([
      "citation_title",
      "citation_author",
      "citation_author_institution",
      "citation_author_orcid",
      "citation_author",
    ]);
    const value = (name: string) => tags.find(([n]) => n === name)?.[1];
    expect(value("citation_author")).toBe("Nurlanova, Asel");
    expect(value("citation_publication_date")).toBe("2026/11/27");
    expect(value("citation_firstpage")).toBe("1");
    expect(value("citation_lastpage")).toBe("14");
    expect(value("citation_volume")).toBe("1");
    expect(value("citation_issue")).toBe("2");
    expect(value("citation_pdf_url")).toBe(`${PAGE}/download/7`);
    expect(tags.filter(([n]) => n === "citation_keywords")).toHaveLength(2);
  });
});

describe("Dublin Core and JSON-LD", () => {
  it("describes the article", () => {
    const dc = dublinCoreTags(ARTICLE, JOURNAL, PAGE);
    expect(dc).toContainEqual(["DC.identifier", "https://doi.org/10.99999/dj.2026.0001"]);
    expect(dc).toContainEqual(["DC.source", "Journal of Applied Science; Vol. 1 No. 2 (2026); 1-14"]);
    const ld = scholarlyArticleLd(ARTICLE, JOURNAL, PAGE);
    expect(ld["@type"]).toBe("ScholarlyArticle");
    expect(ld.identifier).toEqual({
      "@type": "PropertyValue",
      propertyID: "DOI",
      value: "10.99999/dj.2026.0001",
    });
    expect(ld.isPartOf).toMatchObject({
      "@type": "PublicationIssue",
      issueNumber: "2",
      isPartOf: {
        "@type": "PublicationVolume",
        volumeNumber: "1",
        isPartOf: { name: "Journal of Applied Science" },
      },
    });
    expect((ld.author as unknown[])[1]).toEqual({ "@type": "Person", name: "Madina", givenName: "Madina" });
  });

  it("escapes markup in JSON-LD", () => {
    expect(jsonForScript({ title: "</script><script>alert(1)</script>" })).not.toContain("</script>");
  });
});
