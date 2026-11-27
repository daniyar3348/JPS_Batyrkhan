import type { BoardMember } from "@jps/api-client";
import type { Metadata } from "next";
import { OrcidLink } from "@/components/Orcid";
import { api } from "@/lib/api";

export const revalidate = 60;
export const metadata: Metadata = { title: "Editorial board", alternates: { canonical: "/editorial-board" } };

/** Members under their roles, in the order the editors listed them. */
function byRole(members: BoardMember[]): [string, BoardMember[]][] {
  const groups = new Map<string, BoardMember[]>();
  for (const member of members) {
    groups.set(member.role, [...(groups.get(member.role) ?? []), member]);
  }
  return [...groups.entries()];
}

export default async function EditorialBoardPage() {
  const journal = await api.journal();
  const members = journal?.editorial_board ?? [];
  return (
    <>
      <h1>Editorial board</h1>
      {members.length === 0 ? <p className="muted">The editorial board will be listed here.</p> : null}
      {byRole(members).map(([role, people]) => (
        <section key={role} className="board-group" aria-labelledby={`role-${role}`}>
          <h2 id={`role-${role}`}>{people.length > 1 && !role.endsWith("s") ? `${role}s` : role}</h2>
          <ul className="board-list">
            {people.map((person) => (
              <li key={`${person.name}-${person.affiliation}`} className="panel" style={{ margin: 0 }}>
                <strong>{person.name}</strong>
                {person.orcid ? <OrcidLink orcid={person.orcid} name={person.name} /> : null}
                {person.affiliation ? <div>{person.affiliation}</div> : null}
                {person.country ? <div className="muted small">{person.country}</div> : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
