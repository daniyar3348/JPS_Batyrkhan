import { describe, expect, it } from "vitest";
import { bibtex, type CitedArticle, type CitedJournal, cite, initials, plain, ris } from "./citation";

const JOURNAL: CitedJournal = {
  name: "Journal of Applied Science",
  abbreviation: "J Appl Sci",
  issn: "2958-0412",
  publisher: "Demo Journal LLP",
};

const ARTICLE: CitedArticle = {
  title: "Grazing pressure and soil carbon",
  subtitle: "Evidence from the Kazakh steppe",
  authors: [
    { given_name: "Asel", family_name: "Nurlanova" },
    { given_name: "Jean-Paul", family_name: "Martin" },
    { given_name: "Madina", family_name: "" },
  ],
  published: "2026-11-27T07:45:00+00:00",
  volume: 1,
  issue: "2",
  pages: "1-14",
  doi: "10.99999/dj.2026.0001",
  url: "https://journal.example.org/articles/jrn-2026-0001",
  abstract: "We measured\nsoil carbon.",
  keywords: ["soil carbon", "grazing"],
};

describe("citation styles", () => {
  it("formats APA 7", () => {
    expect(plain(cite("apa", ARTICLE, JOURNAL))).toBe(
      "Nurlanova, A., Martin, J.-P., & Madina (2026). Grazing pressure and soil carbon: Evidence from the " +
        "Kazakh steppe. Journal of Applied Science, 1(2), 1–14. https://doi.org/10.99999/dj.2026.0001",
    );
    // The journal and the volume are in italics.
    expect(cite("apa", ARTICLE, JOURNAL)).toContainEqual({ i: "Journal of Applied Science" });
    expect(cite("apa", ARTICLE, JOURNAL)).toContainEqual({ i: "1" });
  });

  it("formats MLA 9 with et al. for three or more authors", () => {
    expect(plain(cite("mla", ARTICLE, JOURNAL))).toBe(
      "Nurlanova, Asel, et al. “Grazing pressure and soil carbon: Evidence from the Kazakh steppe.” " +
        "Journal of Applied Science, vol. 1, no. 2, 2026, pp. 1–14, https://doi.org/10.99999/dj.2026.0001.",
    );
    const two = { ...ARTICLE, authors: ARTICLE.authors.slice(0, 2) };
    expect(plain(cite("mla", two, JOURNAL))).toMatch(/^Nurlanova, Asel, and Jean-Paul Martin\. /);
  });

  it("formats Chicago author-date", () => {
    expect(plain(cite("chicago", ARTICLE, JOURNAL))).toBe(
      "Nurlanova, Asel, Jean-Paul Martin, and Madina. 2026. “Grazing pressure and soil carbon: Evidence " +
        "from the Kazakh steppe.” Journal of Applied Science 1 (2): 1–14. https://doi.org/10.99999/dj.2026.0001.",
    );
  });

  it("formats Harvard", () => {
    expect(plain(cite("harvard", ARTICLE, JOURNAL))).toBe(
      "Nurlanova, A., Martin, J.-P. and Madina (2026) ‘Grazing pressure and soil carbon: Evidence from the " +
        "Kazakh steppe’, Journal of Applied Science, 1(2), pp. 1–14. doi: 10.99999/dj.2026.0001.",
    );
  });

  it("formats Vancouver with the journal's abbreviation", () => {
    expect(plain(cite("vancouver", ARTICLE, JOURNAL))).toBe(
      "Nurlanova A, Martin JP, Madina. Grazing pressure and soil carbon: Evidence from the Kazakh steppe. " +
        "J Appl Sci. 2026;1(2):1-14. doi:10.99999/dj.2026.0001",
    );
    const many = {
      ...ARTICLE,
      authors: Array.from({ length: 8 }, (_, n) => ({ given_name: "A", family_name: `P${n}` })),
    };
    expect(plain(cite("vancouver", many, JOURNAL))).toMatch(/^P0 A, P1 A, P2 A, P3 A, P4 A, P5 A, et al\. /);
  });

  it("copes with no DOI, no volume and no pages", () => {
    const bare = { ...ARTICLE, doi: null, volume: null, issue: null, pages: "" };
    expect(plain(cite("apa", bare, JOURNAL))).toMatch(
      /Journal of Applied Science\. https:\/\/journal\.example\.org\/articles\/jrn-2026-0001$/,
    );
    expect(plain(cite("harvard", bare, JOURNAL))).toMatch(/Available at: https:\/\/journal\.example\.org/);
  });

  it("makes initials from compound and multiple given names", () => {
    expect(initials("Jean-Paul Marie")).toBe("J.-P. M.");
    expect(initials("Jean-Paul Marie", false)).toBe("JPM");
  });
});

describe("reference manager formats", () => {
  it("writes BibTeX with escaped characters and a stable key", () => {
    const text = bibtex({ ...ARTICLE, title: "Carbon & nitrogen in 50% of sites" }, JOURNAL);
    expect(text.startsWith("@article{nurlanova2026carbon,\n")).toBe(true);
    expect(text).toContain("author = {Nurlanova, Asel and Martin, Jean-Paul and {Madina}}");
    expect(text).toContain(
      "title = {{Carbon \\& nitrogen in 50\\% of sites: Evidence from the Kazakh steppe}}",
    );
    expect(text).toContain("pages = {1--14}");
    expect(text).toContain("doi = {10.99999/dj.2026.0001}");
  });

  it("writes RIS with one author and keyword per line", () => {
    const text = ris(ARTICLE, JOURNAL);
    const lines = text.split("\r\n");
    expect(lines[0]).toBe("TY  - JOUR");
    expect(lines.filter((l) => l.startsWith("AU  - "))).toEqual([
      "AU  - Nurlanova, Asel",
      "AU  - Martin, Jean-Paul",
      "AU  - Madina",
    ]);
    expect(lines).toContain("SP  - 1");
    expect(lines).toContain("EP  - 14");
    expect(lines).toContain("DA  - 2026/11/27");
    expect(lines).toContain("AB  - We measured soil carbon.");
    expect(lines.filter((l) => l.startsWith("KW  - "))).toHaveLength(2);
    expect(text.endsWith("ER  - \r\n")).toBe(true);
  });
});
