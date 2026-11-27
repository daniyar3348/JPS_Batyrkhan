"use client";

import { useState } from "react";
import {
  bibtex,
  type CitedArticle,
  type CitedJournal,
  citationKey,
  cite,
  type Part,
  plain,
  ris,
  STYLES,
  type Style,
} from "@/lib/citation";

type Tab = Style | "bibtex" | "ris";

function Formatted({ parts }: { parts: Part[] }) {
  return (
    <>
      {parts.map((part, index) =>
        // biome-ignore lint/suspicious/noArrayIndexKey: the parts never move; they are rebuilt together.
        typeof part === "string" ? part : <i key={index}>{part.i}</i>,
      )}
    </>
  );
}

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** "How to cite": the reference in five styles, and files for reference managers. */
export function CiteBox({ article, journal }: { article: CitedArticle; journal: CitedJournal }) {
  const [tab, setTab] = useState<Tab>("apa");
  const [copied, setCopied] = useState(false);
  const tabs: { id: Tab; label: string }[] = [
    ...STYLES,
    { id: "bibtex", label: "BibTeX" },
    { id: "ris", label: "RIS" },
  ];
  const code = tab === "bibtex" ? bibtex(article, journal) : tab === "ris" ? ris(article, journal) : null;
  const parts = code === null ? cite(tab as Style, article, journal) : [];
  const text = code ?? plain(parts);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="cite-heading">
      <h2 id="cite-heading">How to cite</h2>
      <div className="cite-tabs" role="tablist" aria-label="Citation style">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => {
              setTab(item.id);
              setCopied(false);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {code === null ? (
          <p className="cite-text">
            <Formatted parts={parts} />
          </p>
        ) : (
          <pre className="cite-code">{code}</pre>
        )}
      </div>
      <div className="cite-actions">
        <button type="button" className="button button-quiet" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
        {code !== null ? (
          <button
            type="button"
            className="button button-quiet"
            onClick={() =>
              download(
                `${citationKey(article)}.${tab === "bibtex" ? "bib" : "ris"}`,
                code,
                tab === "bibtex" ? "application/x-bibtex" : "application/x-research-info-systems",
              )
            }
          >
            Download .{tab === "bibtex" ? "bib" : "ris"}
          </button>
        ) : null}
      </div>
    </section>
  );
}
