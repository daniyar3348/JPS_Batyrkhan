import type { Metadata, Viewport } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { type NavItem, NavLinks } from "@/components/NavLinks";
import { api } from "@/lib/api";
import { config } from "@/lib/config";
import { licenceName } from "@/lib/format";
import "./globals.css";

/** Pages that do not change often; the platform asks for a rebuild when they do. */
export const revalidate = 3600;

export async function generateMetadata(): Promise<Metadata> {
  const journal = await api.journal();
  const name = journal?.name ?? "Journal";
  return {
    metadataBase: new URL(config.siteUrl),
    title: { default: name, template: `%s | ${name}` },
    description: journal?.tagline || journal?.description.slice(0, 200) || undefined,
    applicationName: name,
    alternates: { types: { "application/atom+xml": [{ url: "/feed.xml", title: `${name}: new articles` }] } },
    openGraph: { siteName: name, type: "website" },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#1d2026" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const [journal, pages] = await Promise.all([api.journal(), api.pages()]);
  const name = journal?.name ?? "Journal";
  const menu: NavItem[] = [
    { href: "/", label: "Current issue" },
    { href: "/issues", label: "Archive" },
    { href: "/about", label: "About" },
    { href: "/editorial-board", label: "Editorial board" },
    ...(pages ?? []).filter((p) => p.in_menu).map((p) => ({ href: `/${p.slug}`, label: p.title })),
    { href: "/announcements", label: "Announcements" },
    { href: "/search", label: "Search" },
  ];
  const issn = [
    journal?.issn_online ? `ISSN ${journal.issn_online} (online)` : "",
    journal?.issn_print ? `ISSN ${journal.issn_print} (print)` : "",
  ].filter(Boolean);
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#content">
          Skip to content
        </a>
        <header className="site-header">
          <div className="container">
            <div className="masthead">
              <div>
                <Link href="/" className="masthead-title">
                  {name}
                </Link>
                {journal?.tagline ? <p className="masthead-tagline">{journal.tagline}</p> : null}
              </div>
              <a className="button" href="/submit">
                Submit a manuscript
              </a>
            </div>
            <nav aria-label="Main" className="nav-wide">
              <NavLinks items={menu} />
            </nav>
            <details className="menu-toggle">
              <summary>Menu</summary>
              <nav aria-label="Main (small screens)">
                <NavLinks items={[...menu, { href: "/submit", label: "Submit a manuscript" }]} />
              </nav>
            </details>
          </div>
        </header>
        <main id="content">
          <div className="container">{children}</div>
        </main>
        <footer className="site-footer">
          <div className="container footer-grid">
            <section>
              <h2>{name}</h2>
              {journal?.publisher ? <p style={{ margin: 0 }}>Published by {journal.publisher}</p> : null}
              {issn.map((line) => (
                <p key={line} style={{ margin: 0 }}>
                  {line}
                </p>
              ))}
              {journal?.contact_email ? (
                <p style={{ marginTop: "0.5rem" }}>
                  <a href={`mailto:${journal.contact_email}`}>{journal.contact_email}</a>
                </p>
              ) : null}
            </section>
            <section>
              <h2>Open access</h2>
              <p>
                Articles are free to read
                {journal?.license_url ? (
                  <>
                    {" "}
                    under the <a href={journal.license_url}>{licenceName(journal.license_url)}</a> licence
                  </>
                ) : null}
                .
              </p>
            </section>
            <section>
              <h2>For indexers</h2>
              <ul>
                <li>
                  <a href="/feed.xml">Atom feed</a>
                </li>
                <li>
                  <a href="/sitemap.xml">Sitemap</a>
                </li>
                <li>
                  <a href={`${config.publicApiUrl}/oai?verb=Identify`}>OAI-PMH</a>
                </li>
              </ul>
            </section>
          </div>
        </footer>
      </body>
    </html>
  );
}
