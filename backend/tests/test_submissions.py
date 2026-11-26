"""Stage 2: preparing, uploading and submitting manuscripts; who can see them."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.core.jobs import Job
from app.core.storage import LocalStorage
from app.modules.files.models import FileRevision, SubmissionFile
from app.modules.files.service import FileService
from app.modules.files.types import content_problem
from app.modules.journals.models import Journal, Section
from app.modules.journals.permissions import Role
from app.modules.similarity.providers import FakeSimilarityProvider
from tests.conftest import ClientFactory, UserFactory, problem

PDF = b"%PDF-1.7\n%test manuscript\n" + b"0" * 2048
ABSTRACT = "This study examines how editorial workflows affect publication time in regional journals."


@pytest.fixture
async def sections(app: FastAPI, journal: Journal) -> dict[str, Section]:
    async with app.state.session_factory() as db:
        created = {}
        for title, abbreviation in (("Research Articles", "ART"), ("Reviews", "REV")):
            section = Section(journal_id=journal.id, title=title, abbreviation=abbreviation)
            section.editors = []
            db.add(section)
            created[abbreviation] = section
        await db.commit()
        return created


@pytest.fixture
async def author(make_user: UserFactory, signed_in: ClientFactory) -> AsyncClient:
    await make_user("asel@example.org", [Role.AUTHOR], given_name="Asel", family_name="Author")
    return await signed_in("asel@example.org")


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


# ---------------------------------------------------------------------- drafts


async def test_draft_starts_with_the_submitter_as_corresponding_author(author: AsyncClient, sections):
    response = await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["status"] == "draft" and draft["number"] is None
    assert draft["viewer"] == {"is_author": True, "is_editor": False, "can_edit": True}
    [me] = draft["publication"]["contributors"]
    assert (me["full_name"], me["email"], me["is_corresponding"]) == ("Asel Author", "asel@example.org", True)
    fields = {p["field"] for p in draft["problems"]}
    assert {"checklist", "files", "title", "abstract", "keywords", "contributors"} <= fields
    assert draft["similarity_checks"] is None


async def test_only_authors_start_submissions_in_open_sections(
    make_user: UserFactory, signed_in: ClientFactory, author: AsyncClient, sections, db: AsyncSession
):
    await make_user("rev@example.org", [Role.REVIEWER])
    reviewer = await signed_in("rev@example.org")
    assert (
        await reviewer.post("/api/v1/submissions", json={"section_id": sections["ART"].id})
    ).status_code == 403

    await db.execute(update(Section).where(Section.id == sections["REV"].id).values(is_active=False))
    await db.commit()
    closed = await author.post("/api/v1/submissions", json={"section_id": sections["REV"].id})
    assert problem(closed)["code"] == "section_closed"


async def test_drafts_are_private(
    author: AsyncClient, make_user: UserFactory, signed_in: ClientFactory, sections
):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    await make_user("other@example.org", [Role.AUTHOR])
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF])
    for email in ("other@example.org", "chief@example.org"):
        http = await signed_in(email)
        assert (await http.get(f"/api/v1/submissions/{draft['id']}")).status_code == 404
    chief = await signed_in("chief@example.org")
    assert (await chief.get("/api/v1/submissions/editorial", params={"status": ""})).json()["items"] == []


async def test_metadata_editing_uses_versions(author: AsyncClient, sections):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    url = f"/api/v1/submissions/{draft['id']}/publication"
    version = draft["publication"]["row_version"]

    assert (await author.patch(url, json={"title": "X"})).status_code == 428
    saved = await author.patch(
        url,
        json={
            "title": "  A study  ",
            "keywords": ["Peer review", "peer review ", " ethics"],
            "abstract": "word " * 400,
        },
        headers={"If-Match": f'"{version}"'},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["publication"]["title"] == "A study"
    assert body["publication"]["keywords"] == ["Peer review", "ethics"]
    assert body["publication"]["row_version"] == version + 1
    messages = {p["field"]: p["message"] for p in body["problems"]}
    assert messages["abstract"] == "Shorten the abstract to 300 words (it has 400)."
    assert messages["keywords"] == "Add at least 3 keywords."

    stale = await author.patch(url, json={"title": "Lost"}, headers={"If-Match": f'"{version}"'})
    assert stale.status_code == 412


async def test_contributors(author: AsyncClient, sections):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    base = f"/api/v1/submissions/{draft['id']}/contributors"
    me = draft["publication"]["contributors"][0]

    added = await author.post(
        base,
        json={
            "given_name": "Nurlan",
            "family_name": "Bekov",
            "email": "Nurlan@Example.org",
            "affiliation": "KBTU",
            "orcid": "0000-0002-1825-0097",
            "is_corresponding": True,
        },
    )
    assert added.status_code == 201, added.text
    nurlan = added.json()
    assert nurlan["email"] == "nurlan@example.org" and nurlan["position"] == 1

    duplicate = await author.post(base, json={"given_name": "N", "email": "nurlan@example.org"})
    assert problem(duplicate)["code"] == "duplicate_contributor"
    bad_orcid = await author.post(base, json={"given_name": "N", "email": "n2@example.org", "orcid": "1234"})
    assert bad_orcid.status_code == 422

    current = (await author.get(f"/api/v1/submissions/{draft['id']}")).json()["publication"]["contributors"]
    assert [c["is_corresponding"] for c in current] == [False, True]  # only one corresponding author

    assert (await author.put(f"{base}/order", json={"contributor_ids": [me["id"]]})).status_code == 422
    assert (
        await author.put(f"{base}/order", json={"contributor_ids": [nurlan["id"], me["id"]]})
    ).status_code == 204
    patched = await author.patch(f"{base}/{me['id']}", json={"in_byline": False, "affiliation": "NU"})
    assert patched.json()["in_byline"] is False

    assert (await author.delete(f"{base}/{nurlan['id']}")).status_code == 204
    remaining = (await author.get(f"/api/v1/submissions/{draft['id']}")).json()["publication"]["contributors"]
    assert [(c["id"], c["position"]) for c in remaining] == [(me["id"], 0)]


# ---------------------------------------------------------------------- files


async def test_upload_is_checked_by_the_worker(author: AsyncClient, sections, run_jobs):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    sid = draft["id"]

    pending = await upload(author, sid, "C:\\Users\\asel\\Статья.pdf", PDF)
    assert pending["status"] == "processing" and pending["name"] == "Статья.pdf"
    assert pending["download_url"] is None
    assert await run_jobs() == 1
    [ready] = (await author.get(f"/api/v1/submissions/{sid}")).json()["files"]
    assert ready["status"] == "ready" and ready["content_type"] == "application/pdf"

    download = await author.get(ready["download_url"])
    assert download.status_code == 302
    content = await author.get(download.headers["location"])
    assert content.content == PDF
    assert "filename*=utf-8''%d0%a1" in content.headers["content-disposition"].lower()

    renamed = await author.patch(
        f"/api/v1/submissions/{sid}/files/{ready['id']}", json={"name": "Main text", "genre": "supplementary"}
    )
    assert renamed.json()["name"] == "Main text" and renamed.json()["genre"] == "supplementary"


async def test_files_with_wrong_contents_are_rejected(author: AsyncClient, sections, run_jobs, settings):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    sid = draft["id"]
    fake = await upload(author, sid, "paper.docx", b"MZ\x90\x00 this is really a program")
    await run_jobs()
    [rejected] = (await author.get(f"/api/v1/submissions/{sid}")).json()["files"]
    assert rejected["id"] == fake["id"] and rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "Programs and scripts cannot be uploaded."
    assert rejected["download_url"] is None
    await run_jobs()  # the rejected file is removed from storage
    assert not [
        p for p in Path(settings.storage_local_path).rglob("*.docx") if f"/submissions/{sid}/" in str(p)
    ]
    problems = {p["message"] for p in (await author.get(f"/api/v1/submissions/{sid}")).json()["problems"]}
    assert "Remove the files that were not accepted." in problems


async def test_upload_limits(author: AsyncClient, sections):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    url = f"/api/v1/submissions/{draft['id']}/files/uploads"
    exe = await author.post(url, json={"file_name": "setup.exe", "size": 10, "genre": "supplementary"})
    assert problem(exe)["code"] == "file_type_not_allowed"
    figure_as_manuscript = await author.post(
        url, json={"file_name": "fig.png", "size": 10, "genre": "manuscript"}
    )
    assert problem(figure_as_manuscript)["code"] == "file_type_not_allowed"
    huge = await author.post(
        url, json={"file_name": "a.pdf", "size": 51 * 1024 * 1024, "genre": "manuscript"}
    )
    assert problem(huge)["code"] == "file_too_large"

    ticket = (
        await author.post(url, json={"file_name": "a.pdf", "size": len(PDF), "genre": "manuscript"})
    ).json()
    early = await author.post(f"/api/v1/submissions/{draft['id']}/files/{ticket['file']['id']}/complete")
    assert problem(early)["code"] == "upload_missing"

    target = ticket["upload"]
    wrong_type = await author.put(target["url"], content=PDF, headers={"Content-Type": "text/plain"})
    assert problem(wrong_type)["code"] == "content_type_mismatch"
    wrong_size = await author.put(target["url"], content=PDF + b"!", headers=target["headers"])
    assert problem(wrong_size)["code"] == "size_mismatch"
    forged = await author.put(target["url"] + "x", content=PDF, headers=target["headers"])
    assert problem(forged)["code"] == "invalid_upload_link"


async def test_deleting_a_draft_removes_its_files(author: AsyncClient, sections, run_jobs, settings):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    await upload(author, draft["id"], "a.pdf", PDF)
    await run_jobs()
    stored = [
        p
        for p in Path(settings.storage_local_path).rglob("*.pdf")
        if f"/submissions/{draft['id']}/" in str(p)
    ]
    assert len(stored) == 1

    assert (await author.delete(f"/api/v1/submissions/{draft['id']}")).status_code == 204
    await run_jobs()
    assert not stored[0].exists()
    assert (await author.get(f"/api/v1/submissions/{draft['id']}")).status_code == 404


async def test_abandoned_uploads_are_cleaned_up(
    app: FastAPI, author: AsyncClient, sections, db: AsyncSession
):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    await author.post(
        f"/api/v1/submissions/{draft['id']}/files/uploads",
        json={"file_name": "never.pdf", "size": 100, "genre": "manuscript"},
    )
    await db.execute(update(FileRevision).values(created_at=utcnow() - timedelta(days=2)))
    await db.commit()
    async with app.state.session_factory() as session, session.begin():
        assert await FileService(session, app.state.storage).delete_abandoned_uploads() == 1
    assert await db.scalar(select(func.count()).select_from(SubmissionFile)) == 0


@pytest.mark.parametrize(
    ("head", "extension", "accepted"),
    [
        (b"%PDF-1.4", ".pdf", True),
        (b"PK\x03\x04", ".docx", True),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".doc", True),
        ("\\documentclass{article} Ω".encode(), ".tex", True),
        (b"\x89PNG\r\n\x1a\n", ".png", True),
        (b"PK\x03\x04", ".pdf", False),
        (b"%PDF-1.4", ".png", False),
        (b"text\x00with nul", ".tex", False),
        (b"#!/bin/sh", ".txt", False),
    ],
)
def test_content_checks(head: bytes, extension: str, accepted: bool):
    assert (content_problem(head, extension) is None) is accepted


# ---------------------------------------------------------------------- submitting


async def test_incomplete_submissions_are_refused(author: AsyncClient, sections):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()
    response = await author.post(f"/api/v1/submissions/{draft['id']}/submit")
    assert response.status_code == 422
    body = problem(response)
    assert body["code"] == "submission_incomplete"
    assert {"files", "title", "abstract", "keywords", "checklist"} <= {e["field"] for e in body["errors"]}


async def test_unverified_authors_cannot_submit(
    make_user: UserFactory, signed_in: ClientFactory, sections, run_jobs, db
):
    from app.modules.identity.models import User

    await make_user("new@example.org", [Role.AUTHOR], verified=True)
    http = await signed_in("new@example.org")
    draft = await complete_draft(http, sections["ART"].id, run_jobs)
    await db.execute(update(User).where(User.email == "new@example.org").values(email_verified_at=None))
    await db.commit()
    refused = await http.post(f"/api/v1/submissions/{draft['id']}/submit")
    assert [e["field"] for e in problem(refused)["errors"]] == ["account"]


async def test_submission(
    author: AsyncClient,
    make_user: UserFactory,
    signed_in: ClientFactory,
    sections,
    run_jobs,
    outbox,
    app: FastAPI,
):
    chief = await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF], given_name="Chief")
    editor = await make_user("editor@example.org", [Role.SECTION_EDITOR], given_name="Section")
    async with app.state.session_factory() as db:
        section = await db.get(Section, sections["ART"].id)
        assert section is not None
        await db.refresh(section, ["editors"])
        section.editors = [editor]
        await db.commit()
    await make_user("nurlan@example.org", [Role.AUTHOR], given_name="Nurlan", family_name="Bekov")

    draft = await complete_draft(author, sections["ART"].id, run_jobs)
    sid = draft["id"]
    await author.post(
        f"/api/v1/submissions/{sid}/contributors",
        json={
            "given_name": "Nurlan",
            "family_name": "Bekov",
            "email": "nurlan@example.org",
            "affiliation": "KBTU",
        },
    )
    outbox.clear()
    submitted = await author.post(f"/api/v1/submissions/{sid}/submit")
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    year = utcnow().year
    assert body["number"] == f"JRN-{year}-0001"
    assert body["status"] == "queued" and body["submitted_at"] is not None
    assert body["viewer"] == {"is_author": True, "is_editor": False, "can_edit": False}
    assert body["publication"]["contributors"][1]["has_account"] is True

    await run_jobs()
    recipients = sorted(message.to for message in outbox)
    assert recipients == ["asel@example.org", "chief@example.org", "editor@example.org", "nurlan@example.org"]
    subjects = {message.to: message.subject for message in outbox}
    assert subjects["asel@example.org"] == f"JRN-{year}-0001: submission received"
    assert subjects["editor@example.org"].startswith(f"New submission JRN-{year}-0001")
    assert chief.email == "chief@example.org"

    locked = await author.patch(
        f"/api/v1/submissions/{sid}", json={"comments_for_editor": "x"}, headers={"If-Match": '"9"'}
    )
    assert problem(locked)["code"] == "not_editable"
    assert problem(await author.delete(f"/api/v1/submissions/{sid}"))["code"] == "not_editable"

    # The co-author sees it among their submissions, read-only.
    nurlan = await signed_in("nurlan@example.org")
    mine = (await nurlan.get("/api/v1/submissions")).json()["items"]
    assert [s["number"] for s in mine] == [f"JRN-{year}-0001"]
    assert (await nurlan.get(f"/api/v1/submissions/{sid}")).json()["viewer"]["can_edit"] is False

    second = await complete_draft(author, sections["ART"].id, run_jobs, title="Second")
    assert (await author.post(f"/api/v1/submissions/{second['id']}/submit")).json()[
        "number"
    ] == f"JRN-{year}-0002"


async def test_editorial_queue(
    author: AsyncClient, make_user: UserFactory, signed_in: ClientFactory, sections, run_jobs, app: FastAPI
):
    first = await complete_draft(author, sections["ART"].id, run_jobs, title="Glacier melt in the Tien Shan")
    second = await complete_draft(author, sections["REV"].id, run_jobs, title="A review of steppe ecology")
    for draft in (first, second):
        await author.post(f"/api/v1/submissions/{draft['id']}/submit")

    editor = await make_user("editor@example.org", [Role.SECTION_EDITOR])
    async with app.state.session_factory() as db:
        section = await db.get(Section, sections["REV"].id)
        assert section is not None
        await db.refresh(section, ["editors"])
        section.editors = [editor]
        await db.commit()
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF])
    await make_user("rev@example.org", [Role.REVIEWER])

    chief = await signed_in("chief@example.org")
    titles = [s["title"] for s in (await chief.get("/api/v1/submissions/editorial")).json()["items"]]
    assert titles == ["A review of steppe ecology", "Glacier melt in the Tien Shan"]  # newest first
    found = (await chief.get("/api/v1/submissions/editorial", params={"q": "glacier"})).json()["items"]
    assert [s["id"] for s in found] == [first["id"]]
    detail = (await chief.get(f"/api/v1/submissions/{first['id']}")).json()
    assert detail["viewer"]["is_editor"] is True and detail["comments_for_editor"] == "Thank you."

    section_editor = await signed_in("editor@example.org")
    own = (await section_editor.get("/api/v1/submissions/editorial")).json()["items"]
    assert [s["id"] for s in own] == [second["id"]]
    assert (await section_editor.get(f"/api/v1/submissions/{first['id']}")).status_code == 404
    file_url = (await section_editor.get(f"/api/v1/submissions/{second['id']}")).json()["files"][0][
        "download_url"
    ]
    assert (await section_editor.get(file_url)).status_code == 302

    reviewer = await signed_in("rev@example.org")
    assert (await reviewer.get("/api/v1/submissions/editorial")).status_code == 403
    assert (await reviewer.get(file_url)).status_code == 404


async def test_editors_never_handle_their_own_manuscripts(
    make_user: UserFactory, signed_in: ClientFactory, sections, run_jobs
):
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF, Role.AUTHOR])
    chief = await signed_in("chief@example.org")
    draft = await complete_draft(chief, sections["ART"].id, run_jobs)
    await chief.post(f"/api/v1/submissions/{draft['id']}/submit")
    assert (await chief.get("/api/v1/submissions/editorial")).json()["items"] == []
    view = (await chief.get(f"/api/v1/submissions/{draft['id']}")).json()
    assert view["viewer"] == {"is_author": True, "is_editor": False, "can_edit": False}
    assert view["similarity_checks"] is None


async def test_similarity_check(
    author: AsyncClient,
    admin: AsyncClient,
    make_user: UserFactory,
    signed_in: ClientFactory,
    sections,
    run_jobs,
):
    current = await admin.get("/api/v1/journal/submission-settings")
    body = current.json()
    assert body["similarity_available"] is True
    enabled = {
        k: body[k]
        for k in (
            "checklist",
            "author_guidelines",
            "max_file_size_mb",
            "abstract_max_words",
            "keywords_min",
            "keywords_max",
            "number_prefix",
        )
    }
    enabled["similarity"] = {"enabled": True, "threshold_percent": 1}
    saved = await admin.put(
        "/api/v1/journal/submission-settings", json=enabled, headers={"If-Match": current.headers["etag"]}
    )
    assert saved.status_code == 200, saved.text

    draft = await complete_draft(author, sections["ART"].id, run_jobs)
    await author.post(f"/api/v1/submissions/{draft['id']}/submit")
    await run_jobs()

    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF])
    chief = await signed_in("chief@example.org")
    [check] = (await chief.get(f"/api/v1/submissions/{draft['id']}")).json()["similarity_checks"]
    assert check["status"] == "completed" and check["provider"] == "fake"
    assert check["flagged"] is (check["score_percent"] >= 1)
    [row] = (await chief.get("/api/v1/submissions/editorial")).json()["items"]
    assert row["similarity_score"] == check["score_percent"]

    assert (await author.get(f"/api/v1/submissions/{draft['id']}")).json()["similarity_checks"] is None
    assert (await author.post(f"/api/v1/submissions/{draft['id']}/similarity-checks")).status_code == 403

    rerun = await chief.post(f"/api/v1/submissions/{draft['id']}/similarity-checks")
    assert rerun.status_code == 201 and rerun.json()["status"] == "queued"
    await run_jobs()
    checks = (await chief.get(f"/api/v1/submissions/{draft['id']}")).json()["similarity_checks"]
    assert [c["status"] for c in checks] == ["completed", "completed"]
    report = await chief.get(f"/api/v1/submissions/{draft['id']}/similarity-checks/{check['id']}/report")
    assert report.status_code == 404  # the fake provider has no report pages


async def run_every_attempt(run_jobs, db: AsyncSession) -> None:
    """Run the queue until retries are used up, skipping the waits between attempts."""
    for _ in range(6):
        await run_jobs()
        await db.execute(update(Job).where(Job.status == "queued").values(run_at=func.now()))
        await db.commit()


async def test_unreachable_similarity_service_fails_the_check(
    author: AsyncClient,
    make_user: UserFactory,
    signed_in: ClientFactory,
    sections,
    run_jobs,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    draft = await complete_draft(author, sections["ART"].id, run_jobs)
    await author.post(f"/api/v1/submissions/{draft['id']}/submit")
    await run_jobs()
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF])
    chief = await signed_in("chief@example.org")

    async def unreachable(self: FakeSimilarityProvider, **kwargs: Any) -> str:
        raise ConnectionError("service down")

    monkeypatch.setattr(FakeSimilarityProvider, "submit", unreachable)
    assert (await chief.post(f"/api/v1/submissions/{draft['id']}/similarity-checks")).status_code == 201
    await run_every_attempt(run_jobs, db)

    [check] = (await chief.get(f"/api/v1/submissions/{draft['id']}")).json()["similarity_checks"]
    assert check["status"] == "failed"
    assert "could not be reached" in check["error"]


async def test_unreadable_upload_does_not_stay_in_checking(
    author: AsyncClient, sections, run_jobs, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    draft = (await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})).json()

    async def broken(self: LocalStorage, key: str) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(LocalStorage, "digest", broken)
    await upload(author, draft["id"], "paper.pdf", PDF)
    await run_every_attempt(run_jobs, db)

    [file] = (await author.get(f"/api/v1/submissions/{draft['id']}")).json()["files"]
    assert file["status"] == "rejected"
    assert "could not check this file" in file["rejection_reason"]


async def test_submission_settings(admin: AsyncClient, author: AsyncClient, app: FastAPI):
    readable = await author.get("/api/v1/journal/submission-settings")
    assert readable.status_code == 200
    body = readable.json()
    assert body["number_prefix"] == "JRN" and len(body["checklist"]) == 5
    assert ".docx" in body["allowed_file_types"]["manuscript"]

    payload = {
        k: body[k]
        for k in (
            "checklist",
            "author_guidelines",
            "max_file_size_mb",
            "abstract_max_words",
            "keywords_min",
            "keywords_max",
            "number_prefix",
            "similarity",
        )
    }
    assert (
        await author.put(
            "/api/v1/journal/submission-settings",
            json=payload,
            headers={"If-Match": readable.headers["etag"]},
        )
    ).status_code == 403

    invalid = await admin.put(
        "/api/v1/journal/submission-settings",
        json=payload | {"keywords_min": 9, "keywords_max": 3, "number_prefix": "jrn"},
        headers={"If-Match": readable.headers["etag"]},
    )
    assert invalid.status_code == 422

    saved = await admin.put(
        "/api/v1/journal/submission-settings",
        json=payload | {"checklist": ["Only this."], "number_prefix": "JAS"},
        headers={"If-Match": readable.headers["etag"]},
    )
    assert saved.status_code == 200 and saved.json()["checklist"] == ["Only this."]
    assert saved.json()["version"] == body["version"] + 1

    original = app.state.settings
    app.state.settings = original.model_copy(update={"similarity_provider": "disabled"})
    try:
        refused = await admin.put(
            "/api/v1/journal/submission-settings",
            json=payload | {"similarity": {"enabled": True, "threshold_percent": 30}},
            headers={"If-Match": saved.headers["etag"]},
        )
        assert problem(refused)["code"] == "similarity_unavailable"
    finally:
        app.state.settings = original


async def test_sections_with_submissions_cannot_be_deleted(admin: AsyncClient, author: AsyncClient, sections):
    await author.post("/api/v1/submissions", json={"section_id": sections["ART"].id})
    response = await admin.delete(f"/api/v1/sections/{sections['ART'].id}")
    assert problem(response)["code"] == "section_in_use"
