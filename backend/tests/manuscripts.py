"""Helpers that prepare manuscripts through the API, shared by the submission and review tests."""

from __future__ import annotations

import io
from typing import Any

from httpx import AsyncClient
from pypdf import PdfWriter


def _pdf() -> bytes:
    """A real, small PDF whose metadata names its author (as word processors do)."""
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.add_metadata({"/Author": "Asel Author", "/Title": "Editorial workflows"})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


PDF = _pdf()
ABSTRACT = "This study examines how editorial workflows affect publication time in regional journals."


async def upload(
    http: AsyncClient, submission_id: int, name: str, content: bytes, genre: str = "manuscript"
) -> dict[str, Any]:
    ticket = await http.post(
        f"/api/v1/submissions/{submission_id}/files/uploads",
        json={"file_name": name, "size": len(content), "genre": genre},
    )
    assert ticket.status_code == 201, ticket.text
    target = ticket.json()["upload"]
    put = await http.request(target["method"], target["url"], content=content, headers=target["headers"])
    assert put.status_code == 204, put.text
    done = await http.post(
        f"/api/v1/submissions/{submission_id}/files/{ticket.json()['file']['id']}/complete"
    )
    assert done.status_code == 200, done.text
    result: dict[str, Any] = done.json()
    return result


async def complete_draft(
    http: AsyncClient, section_id: int, run_jobs, title: str = "Editorial workflows"
) -> dict[str, Any]:
    """Create a draft that can be submitted."""
    draft = (await http.post("/api/v1/submissions", json={"section_id": section_id})).json()
    sid = draft["id"]
    checklist = (await http.get("/api/v1/journal/submission-settings")).json()["checklist"]
    await http.patch(
        f"/api/v1/submissions/{sid}",
        json={"checklist_confirmed": checklist, "comments_for_editor": "Thank you."},
        headers={"If-Match": f'"{draft["row_version"]}"'},
    )
    await upload(http, sid, "manuscript.pdf", PDF)
    await run_jobs()
    current = (await http.get(f"/api/v1/submissions/{sid}")).json()
    publication = current["publication"]
    await http.patch(
        f"/api/v1/submissions/{sid}/publication",
        json={"title": title, "abstract": ABSTRACT, "keywords": ["peer review", "publishing", "workflow"]},
        headers={"If-Match": f'"{publication["row_version"]}"'},
    )
    first = publication["contributors"][0]
    await http.patch(
        f"/api/v1/submissions/{sid}/contributors/{first['id']}", json={"affiliation": "Nazarbayev University"}
    )
    ready: dict[str, Any] = (await http.get(f"/api/v1/submissions/{sid}")).json()
    assert ready["problems"] == [], ready["problems"]
    return ready
