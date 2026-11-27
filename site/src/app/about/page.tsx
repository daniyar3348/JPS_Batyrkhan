import type { Metadata } from "next";
import Link from "next/link";
import { Paragraphs } from "@/components/Markdown";
import { api } from "@/lib/api";
import { config } from "@/lib/config";
import { formatMoney, licenceName } from "@/lib/format";

export const revalidate = 60;
export const metadata: Metadata = { title: "About the journal", alternates: { canonical: "/about" } };

export default async function AboutPage() {
  const [journal, pages] = await Promise.all([api.journal(), api.pages()]);
  if (!journal) return <h1>About the journal</h1>;
  const fees = journal.fees;
  return (
    <div className="layout-2">
      <div className="reading">
        <h1>About the journal</h1>
        {journal.description ? <Paragraphs text={journal.description} className="lead" /> : null}

        {journal.sections.length ? (
          <section>
            <h2>Sections</h2>
            {journal.sections.map((section) => (
              <div key={section.id} style={{ marginBottom: "1rem" }}>
                <h3>{section.title}</h3>
                {section.policy ? <Paragraphs text={section.policy} /> : null}
              </div>
            ))}
          </section>
        ) : null}

        <section id="fees">
          <h2>Fees</h2>
          {fees?.charged ? (
            <>
              <p>
                Submission and peer review are free. If a manuscript is accepted, the authors pay an article
                processing charge of <strong>{formatMoney(fees.amount, fees.currency)}</strong>
                {Number(fees.vat_percent) > 0 ? ` plus ${Number(fees.vat_percent)}% VAT` : ""}.
              </p>
              {fees.section_fees.length ? (
                <ul>
                  {fees.section_fees.map((fee) => (
                    <li key={fee.section_id}>
                      {fee.section_title}: {formatMoney(fee.amount, fees.currency)}
                    </li>
                  ))}
                </ul>
              ) : null}
              <p>
                The charge is paid only after acceptance; the editors decide without knowing whether or how
                the authors will pay.
              </p>
              {fees.waiver_policy ? (
                <>
                  <h3>Waivers</h3>
                  <Paragraphs text={fees.waiver_policy} />
                </>
              ) : null}
            </>
          ) : (
            <p>The journal charges no fees for submission, review or publication.</p>
          )}
        </section>
      </div>
      <aside aria-label="Journal details">
        <section className="panel">
          <h2>Journal details</h2>
          <dl className="facts">
            <dt>Title</dt>
            <dd>{journal.name}</dd>
            {journal.abbreviation ? (
              <>
                <dt>Abbreviation</dt>
                <dd>{journal.abbreviation}</dd>
              </>
            ) : null}
            {journal.issn_online ? (
              <>
                <dt>ISSN (online)</dt>
                <dd>{journal.issn_online}</dd>
              </>
            ) : null}
            {journal.issn_print ? (
              <>
                <dt>ISSN (print)</dt>
                <dd>{journal.issn_print}</dd>
              </>
            ) : null}
            {journal.publisher ? (
              <>
                <dt>Publisher</dt>
                <dd>{journal.publisher}</dd>
              </>
            ) : null}
            {journal.publication_frequency ? (
              <>
                <dt>Frequency</dt>
                <dd>{journal.publication_frequency}</dd>
              </>
            ) : null}
            {journal.license_url ? (
              <>
                <dt>Licence</dt>
                <dd>
                  <a href={journal.license_url}>{licenceName(journal.license_url)}</a>
                </dd>
              </>
            ) : null}
            {journal.contact_email ? (
              <>
                <dt>Contact</dt>
                <dd>
                  {journal.contact_name ? `${journal.contact_name}, ` : ""}
                  <a href={`mailto:${journal.contact_email}`}>{journal.contact_email}</a>
                </dd>
              </>
            ) : null}
          </dl>
        </section>
        <section className="panel">
          <h2>Policies</h2>
          <ul style={{ paddingLeft: "1.1rem", margin: 0 }}>
            <li>
              <Link href="/editorial-board">Editorial board</Link>
            </li>
            {(pages ?? []).map((page) => (
              <li key={page.slug}>
                <Link href={`/${page.slug}`}>{page.title}</Link>
              </li>
            ))}
            <li>
              <a href={`${config.publicApiUrl}/oai?verb=Identify`}>OAI-PMH repository</a>
            </li>
          </ul>
        </section>
      </aside>
    </div>
  );
}
