"""Stage 3: decisions, peer review and revisions; above all, who sees what in blind review."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.email import EmailMessage
from app.modules.identity.models import User
from app.modules.journals.models import Section, SectionEditor
from app.modules.journals.permissions import Role
from app.modules.review.models import ReviewAssignment, ReviewReminder
from app.modules.review.tasks import send_due_reminders
from tests.conftest import ClientFactory, UserFactory, problem
from tests.manuscripts import PDF, complete_draft

ANSWERS = {
    "summary": "A study of how editorial workflows change publication times.",
    "originality": "Moderately original",
    "methods": "Sound, but the sample of journals is small.",
    "conclusions": "Partly",
}


@dataclass
class Office:
    author: AsyncClient
    chief: AsyncClient
    editor: AsyncClient
    reviewer: AsyncClient
    chief_user: User
    editor_user: User
    reviewer_user: User
    other_reviewer: User
    submission_id: int
    run_jobs: Any
    outbox: list[EmailMessage]

    async def mail(self, address: str) -> list[EmailMessage]:
        """E-mails delivered to an address so far (the worker runs first)."""
        await self.run_jobs()
        return [m for m in self.outbox if m.to == address]

    def url(self, path: str = "") -> str:
        return f"/api/v1/submissions/{self.submission_id}{path}"


@pytest.fixture
async def office(
    app: FastAPI,
    make_user: UserFactory,
    signed_in: ClientFactory,
    author: AsyncClient,
    sections: dict[str, Section],
    run_jobs,
    outbox: list[EmailMessage],
) -> Office:
    chief = await make_user(
        "chief@example.org", [Role.EDITOR_IN_CHIEF], given_name="Daniyar", family_name="Chief"
    )
    editor = await make_user(
        "editor@example.org", [Role.SECTION_EDITOR], given_name="Elena", family_name="Editor"
    )
    reviewer = await make_user(
        "rev@example.org", [Role.REVIEWER], given_name="Ruslan", family_name="Reviewer"
    )
    other = await make_user("rita@example.org", [Role.REVIEWER], given_name="Rita", family_name="Reviewer")
    async with app.state.session_factory() as db:
        db.add(SectionEditor(section_id=sections["ART"].id, user_id=editor.id))
        await db.commit()
    draft = await complete_draft(author, sections["ART"].id, run_jobs)
    submitted = await author.post(f"/api/v1/submissions/{draft['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    await run_jobs()
    return Office(
        author=author,
        chief=await signed_in("chief@example.org"),
        editor=await signed_in("editor@example.org"),
        reviewer=await signed_in("rev@example.org"),
        chief_user=chief,
        editor_user=editor,
        reviewer_user=reviewer,
        other_reviewer=other,
        submission_id=draft["id"],
        run_jobs=run_jobs,
        outbox=outbox,
    )


async def workflow(http: AsyncClient, office: Office) -> dict[str, Any]:
    response = await http.get(office.url("/workflow"))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def send_to_review(office: Office, run_jobs) -> dict[str, Any]:
    preview = (
        await office.chief.post(office.url("/decisions/preview"), json={"decision": "send_to_review"})
    ).json()
    file_ids = [f["id"] for f in preview["candidate_files"]]
    decided = await office.chief.post(
        office.url("/decisions"), json={"decision": "send_to_review", "review_file_ids": file_ids}
    )
    assert decided.status_code == 201, decided.text
    await run_jobs()
    return await workflow(office.chief, office)


async def invite(office: Office, round_id: int, reviewer_id: int, **extra: Any) -> dict[str, Any]:
    response = await office.chief.post(
        office.url(f"/review-rounds/{round_id}/reviewers"), json={"reviewer_id": reviewer_id, **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def write_review(reviewer: AsyncClient, assignment_id: int, run_jobs) -> dict[str, Any]:
    if (await reviewer.get(f"/api/v1/reviews/{assignment_id}")).json()["status"] == "invited":
        accepted = await reviewer.post(f"/api/v1/reviews/{assignment_id}/accept", json={})
        assert accepted.status_code == 200, accepted.text
    submitted = await reviewer.post(
        f"/api/v1/reviews/{assignment_id}/submit",
        json={
            "answers": ANSWERS,
            "recommendation": "minor_revisions",
            "comments_for_author": "Please add the 2024 data.",
            "comments_for_editor": "Confidential: the authors overstate the novelty.",
        },
    )
    assert submitted.status_code == 200, submitted.text
    await run_jobs()
    body: dict[str, Any] = submitted.json()
    return body


# ---------------------------------------------------------------------- the whole path


async def test_review_from_invitation_to_acceptance(office: Office, run_jobs, outbox: list[EmailMessage]):
    # The section's editor was assigned on submission.
    chief_view = await workflow(office.chief, office)
    assert [e["user"]["email"] for e in chief_view["editors"]] == ["editor@example.org"]
    assert {d["decision"] for d in chief_view["available_decisions"]} == {
        "send_to_review",
        "accept",
        "decline",
    }
    author_view = await workflow(office.author, office)
    assert author_view["available_decisions"] == [] and author_view["editors"] is None
    assert author_view["can_withdraw"] is True

    # Sending to review: the letter and the files to give reviewers are shown first.
    preview = (
        await office.chief.post(office.url("/decisions/preview"), json={"decision": "send_to_review"})
    ).json()
    assert preview["letter"]["to"] == ["asel@example.org"]
    assert "has been sent to peer review" in preview["letter"]["body"]
    assert [f["name"] for f in preview["candidate_files"]] == ["manuscript.pdf"]

    view = await send_to_review(office, run_jobs)
    assert view["stage"] == "review"
    [review_round] = view["rounds"]
    [copy] = review_round["review_files"]
    assert copy["status"] == "ready" and copy["metadata_removed"] is True
    assert (await office.mail("asel@example.org"))[-1].subject.endswith("your manuscript is under review")

    # Inviting a reviewer: the e-mail links to the review.
    assignment = await invite(office, review_round["id"], office.reviewer_user.id)
    assert assignment["status"] == "invited" and assignment["reviewer_number"] == 1
    assert assignment["method"] == "double_blind"
    invitation = (await office.mail("rev@example.org"))[-1]
    assert f"/reviews/{assignment['id']}" in invitation.text
    assert "Asel" not in invitation.text  # the authors are not named

    # Before accepting, the reviewer sees the title and abstract but no files and no authors.
    tasks = (await office.reviewer.get("/api/v1/reviews")).json()
    assert [t["id"] for t in tasks] == [assignment["id"]]
    page = await office.reviewer.get(f"/api/v1/reviews/{assignment['id']}")
    review = page.json()
    assert review["files"] == [] and review["manuscript"]["authors"] is None
    assert review["manuscript"]["comments_for_editor"] is None
    assert "Asel" not in page.text and "asel@example.org" not in page.text and "Nazarbayev" not in page.text
    # A reviewer has no other way into the manuscript.
    assert (await office.reviewer.get(office.url())).status_code == 404
    assert (await office.reviewer.get(office.url("/workflow"))).status_code == 404

    accepted = (await office.reviewer.post(f"/api/v1/reviews/{assignment['id']}/accept", json={})).json()
    [reviewer_file] = accepted["files"]
    download = await office.reviewer.get(reviewer_file["download_url"])
    assert download.status_code == 302
    reviewer_copy = (await office.reviewer.get(download.headers["location"])).content
    assert reviewer_copy.startswith(b"%PDF") and b"Asel Author" in PDF and b"Asel Author" not in reviewer_copy

    # The review: a draft can be incomplete; sending it cannot.
    draft = await office.reviewer.put(
        f"/api/v1/reviews/{assignment['id']}/draft", json={"answers": {"summary": "Half done"}}
    )
    assert draft.status_code == 200 and draft.json()["answers"] == {"summary": "Half done"}
    incomplete = await office.reviewer.post(
        f"/api/v1/reviews/{assignment['id']}/submit", json={"answers": {}}
    )
    assert incomplete.status_code == 422
    fields = {e["field"] for e in problem(incomplete)["errors"]}
    assert {"answers.summary", "answers.originality", "recommendation"} <= fields
    bad = await office.reviewer.put(
        f"/api/v1/reviews/{assignment['id']}/draft", json={"answers": {"originality": "Invented option"}}
    )
    assert bad.status_code == 422

    # Before the editor decides, the author sees nothing of the review.
    await write_review(office.reviewer, assignment["id"], run_jobs)
    assert "review received from Ruslan Reviewer" in (await office.mail("editor@example.org"))[-1].subject
    author_round = (await workflow(office.author, office))["rounds"][0]
    assert author_round["assignments"] is None and author_round["reviews_for_author"] is None

    # Requesting revisions: the letter carries the comments for the authors, nothing confidential.
    preview = (
        await office.chief.post(office.url("/decisions/preview"), json={"decision": "request_revisions"})
    ).json()
    letter = preview["letter"]["body"]
    assert "Reviewer 1:" in letter and "Please add the 2024 data." in letter
    assert "Sound, but the sample" in letter  # a visible answer
    assert "Moderately original" not in letter  # an answer for the editors only
    assert "Confidential" not in letter and "Ruslan" not in letter
    decided = await office.chief.post(office.url("/decisions"), json={"decision": "request_revisions"})
    assert decided.status_code == 201, decided.text

    author_view = await workflow(office.author, office)
    [shown] = author_view["rounds"][0]["reviews_for_author"]
    assert shown["label"] == "Reviewer 1" and shown["comments"] == "Please add the 2024 data."
    assert all("original" not in a["question"] for a in shown["answers"])
    assert "Ruslan" not in str(author_view) and "Confidential" not in str(author_view)
    [request] = [d for d in author_view["decisions"] if d["decision"] == "request_revisions"]
    assert request["made_by"] is None and "Reviewer 1:" in request["letter_body"]

    # The author revises and sends the revision.
    round_id = author_view["rounds"][0]["id"]
    ticket = await office.author.post(
        office.url(f"/review-rounds/{round_id}/revisions/uploads"),
        json={"file_name": "revised.pdf", "size": len(PDF), "genre": "manuscript"},
    )
    assert ticket.status_code == 201, ticket.text
    target = ticket.json()["upload"]
    await office.author.request(target["method"], target["url"], content=PDF, headers=target["headers"])
    file_id = ticket.json()["file"]["id"]
    assert (
        await office.author.post(office.url(f"/review-rounds/{round_id}/revisions/{file_id}/complete"))
    ).status_code == 200
    await run_jobs()
    sent = await office.author.post(
        office.url(f"/review-rounds/{round_id}/revisions/submit"),
        json={"response": "We added the 2024 data."},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()[0]["status"] == "revisions_submitted"
    assert "revised manuscript received" in (await office.mail("editor@example.org"))[-1].subject

    # Accepting closes the round and moves the manuscript on.
    accepted = await office.editor.post(office.url("/decisions"), json={"decision": "accept"})
    assert accepted.status_code == 201, accepted.text
    final = accepted.json()
    assert final["stage"] == "copyediting" and final["rounds"][0]["status"] == "closed"
    assert [d["decision"] for d in final["decisions"]] == ["send_to_review", "request_revisions", "accept"]
    assert (await office.chief.post(office.url("/decisions"), json={"decision": "accept"})).status_code == 409

    # Everything sent about the manuscript is in its e-mail log, for editors only.
    log = (await office.chief.get(office.url("/emails"))).json()
    assert {"review_request", "decision_revisions", "decision_accept"} <= {e["template_key"] for e in log}
    assert (await office.author.get(office.url("/emails"))).status_code == 403


async def test_open_and_single_blind_reviews_show_names(office: Office, run_jobs):
    view = await send_to_review(office, run_jobs)
    round_id = view["rounds"][0]["id"]
    single = await invite(office, round_id, office.reviewer_user.id, method="single_blind")
    page = (await office.reviewer.get(f"/api/v1/reviews/{single['id']}")).json()
    assert page["manuscript"]["authors"] == ["Asel Author (Nazarbayev University)"]
    assert page["manuscript"]["comments_for_editor"] == "Thank you."

    open_review = await invite(office, round_id, office.other_reviewer.id, method="open")
    await write_review(office.reviewer, single["id"], run_jobs)
    await office.chief.post(office.url("/decisions"), json={"decision": "resubmit"})
    labels = [r["label"] for r in (await workflow(office.author, office))["rounds"][0]["reviews_for_author"]]
    assert labels == ["Reviewer 1"]
    assert open_review["reviewer_number"] == 2


# ---------------------------------------------------------------------- reviewers


async def test_inviting_someone_new(office: Office, run_jobs, outbox: list[EmailMessage]):
    view = await send_to_review(office, run_jobs)
    round_id = view["rounds"][0]["id"]
    new = {"email": "new.reviewer@example.org", "given_name": "Nurlan", "family_name": "New"}
    preview = await office.chief.post(
        office.url(f"/review-rounds/{round_id}/invitation-preview"), json={"new_reviewer": new}
    )
    assert preview.status_code == 200
    assert "{reviewUrl}" in preview.json()["body"]  # filled in when sent
    assert "separate e-mail to set up your account" in preview.json()["body"]

    edited = preview.json()["body"].replace("I would like to invite you", "Could you please")
    invited = await office.chief.post(
        office.url(f"/review-rounds/{round_id}/reviewers"),
        json={"new_reviewer": new, "email": {"subject": "Review request", "body": edited}},
    )
    assert invited.status_code == 201, invited.text
    messages = await office.mail("new.reviewer@example.org")
    account, request = messages
    assert "token=" in account.text  # the account invitation
    assert "Could you please" in request.text and f"/reviews/{invited.json()['id']}" in request.text
    # The account e-mail carries a personal link and is never kept in the manuscript's log.
    log = (await office.chief.get(office.url("/emails"))).json()
    assert not any("token=" in e["body"] for e in log)
    assert any(e["recipient"] == "new.reviewer@example.org" and e["subject"] == "Review request" for e in log)


async def test_who_can_review(office: Office, make_user: UserFactory, run_jobs):
    view = await send_to_review(office, run_jobs)
    round_id = view["rounds"][0]["id"]
    url = office.url(f"/review-rounds/{round_id}/reviewers")
    # The author: by account, and by e-mail as a "new" reviewer.
    author_id = (await office.author.get("/api/v1/me")).json()["user"]["id"]
    as_new = await office.chief.post(
        url, json={"new_reviewer": {"email": "asel@example.org", "given_name": "Asel"}}
    )
    assert problem(as_new)["code"] == "reviewer_is_author"
    not_reviewer = await office.chief.post(url, json={"reviewer_id": author_id})
    assert problem(not_reviewer)["code"] == "not_a_reviewer"
    # The manuscript's editor.
    await make_user("both@example.org", [Role.REVIEWER, Role.SECTION_EDITOR])
    editors = await office.chief.get(office.url("/participant-candidates?role=editor"))
    both = next(u for u in editors.json() if u["email"] == "both@example.org")
    await office.chief.post(office.url("/participants"), json={"user_id": both["id"]})
    assert (
        problem(await office.chief.post(url, json={"reviewer_id": both["id"]}))["code"]
        == "reviewer_is_editor"
    )
    # Twice in a round: no; again after declining: yes.
    first = await invite(office, round_id, office.reviewer_user.id)
    assert (
        problem(await office.chief.post(url, json={"reviewer_id": office.reviewer_user.id}))["code"]
        == "already_invited"
    )
    declined = await office.reviewer.post(
        f"/api/v1/reviews/{first['id']}/decline", json={"reason": "no_time", "comment": "Travelling"}
    )
    assert declined.json()["status"] == "declined"
    again = await invite(office, round_id, office.reviewer_user.id)
    assert again["id"] == first["id"] and again["status"] == "invited"
    # Only the manuscript's editors manage reviewers.
    assert (await office.author.post(url, json={"reviewer_id": office.other_reviewer.id})).status_code == 403
    assert (
        await office.reviewer.post(url, json={"reviewer_id": office.other_reviewer.id})
    ).status_code == 404


async def test_declining_cancelling_and_suggestions(
    office: Office, app: FastAPI, make_user: UserFactory, run_jobs, outbox: list[EmailMessage]
):
    async with app.state.session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == office.other_reviewer.id)
            .values(interests=["peer review", "open science"])
        )
        await db.execute(
            update(User).where(User.id == office.reviewer_user.id).values(affiliation="Nazarbayev University")
        )
        await db.commit()
    await make_user("idle@example.org", [Role.REVIEWER], given_name="Idle")
    view = await send_to_review(office, run_jobs)
    round_id = view["rounds"][0]["id"]

    suggestions = (await office.chief.get(office.url(f"/review-rounds/{round_id}/suggestions"))).json()
    names = [s["reviewer"]["email"] for s in suggestions]
    assert names[0] == "rita@example.org"  # interests match the keywords
    assert suggestions[0]["matched_keywords"] == ["peer review"]
    same_place = next(s for s in suggestions if s["reviewer"]["email"] == "rev@example.org")
    assert same_place["warnings"] == ["Same institution as an author"]
    assert "asel@example.org" not in names and "editor@example.org" not in names
    searched = (
        await office.chief.get(office.url(f"/review-rounds/{round_id}/suggestions"), params={"q": "idle"})
    ).json()
    assert [s["reviewer"]["email"] for s in searched] == ["idle@example.org"]

    first = await invite(office, round_id, office.reviewer_user.id)
    await office.reviewer.post(
        f"/api/v1/reviews/{first['id']}/decline",
        json={"reason": "conflict_of_interest", "comment": "I know them"},
    )
    told = (await office.mail("editor@example.org"))[-1]
    assert "declined to review" in told.subject and "Conflict of interest — I know them" in told.text
    after = (await office.chief.get(office.url(f"/review-rounds/{round_id}/suggestions"))).json()
    assert "rev@example.org" not in [s["reviewer"]["email"] for s in after]

    second = await invite(office, round_id, office.other_reviewer.id)
    cancelled = await office.chief.post(
        office.url(f"/review-assignments/{second['id']}/cancel"), json={"notify": True}
    )
    assert cancelled.json()["status"] == "cancelled"
    assert (await office.mail("rita@example.org"))[-1].subject.startswith("Review no longer needed")


async def test_reminders_are_sent_once(
    office: Office, app: FastAPI, settings: Settings, run_jobs, outbox: list[EmailMessage]
):
    view = await send_to_review(office, run_jobs)
    assignment = await invite(office, view["rounds"][0]["id"], office.reviewer_user.id)
    today = utcnow().date()
    async with app.state.session_factory() as db:
        await db.execute(
            update(ReviewAssignment)
            .where(ReviewAssignment.id == assignment["id"])
            .values(response_due=today - timedelta(days=3))
        )
        await db.commit()

    async def run() -> int:
        async with app.state.session_factory() as db:
            sent = await send_due_reminders(db, settings, app.state.storage)
            await db.commit()
            return sent

    before = len(await office.mail("rev@example.org"))
    assert await run() == 1
    assert await run() == 0
    await run_jobs()
    reminders = (await office.mail("rev@example.org"))[before:]
    assert [m.subject for m in reminders] == ["Reminder: review request from Test Journal"]

    # Once accepted, several review reminders became due at once: only the latest is sent.
    await office.reviewer.post(f"/api/v1/reviews/{assignment['id']}/accept", json={})
    async with app.state.session_factory() as db:
        await db.execute(
            update(ReviewAssignment)
            .where(ReviewAssignment.id == assignment["id"])
            .values(review_due=today - timedelta(days=4))
        )
        await db.commit()
    assert await run() == 1
    async with app.state.session_factory() as db:
        offsets = (
            await db.scalars(
                select(ReviewReminder.offset_days).where(
                    ReviewReminder.assignment_id == assignment["id"], ReviewReminder.kind == "review"
                )
            )
        ).all()
    assert sorted(offsets) == [-3, 0, 3]
    assert await run() == 0

    # Moving the deadline makes reminders due again later; the editor's own reminder is recorded too.
    preview = (
        await office.chief.post(office.url(f"/review-assignments/{assignment['id']}/reminder-preview"))
    ).json()
    assert preview["subject"].startswith("Reminder: review due")
    reminded = await office.chief.post(
        office.url(f"/review-assignments/{assignment['id']}/remind"),
        json={"email": {"subject": preview["subject"], "body": preview["body"]}},
    )
    assert reminded.json()["last_reminded_at"] is not None


# ---------------------------------------------------------------------- decisions and editors


async def test_recommend_only_editors_recommend(office: Office, run_jobs, outbox: list[EmailMessage]):
    # The chief makes the section editor recommend-only.
    await office.chief.delete(office.url(f"/participants/editor/{office.editor_user.id}"))
    assigned = await office.chief.post(
        office.url("/participants"), json={"user_id": office.editor_user.id, "recommend_only": True}
    )
    assert assigned.status_code == 201, assigned.text
    assert "and recommend a decision" in (await office.mail("editor@example.org"))[-1].text
    view = await workflow(office.editor, office)
    assert view["viewer"]["recommend_only"] is True
    assert {d["decision"] for d in view["available_decisions"]} == {"recommend_accept", "recommend_decline"}
    assert (
        await office.editor.post(office.url("/decisions"), json={"decision": "accept"})
    ).status_code == 403

    recommended = await office.editor.post(
        office.url("/decisions"), json={"decision": "recommend_accept", "reason": "Strong paper."}
    )
    assert recommended.status_code == 201, recommended.text
    body = recommended.json()
    assert body["stage"] == "submission" and body["decisions"][-1]["is_recommendation"] is True
    note = (await office.mail("chief@example.org"))[-1]
    assert "recommends “Accepting”" in note.subject and "Strong paper." in note.text
    # Authors never see recommendations.
    assert (await workflow(office.author, office))["decisions"] == []
    # Authors cannot decide, or recommend.
    assert (
        await office.author.post(office.url("/decisions"), json={"decision": "accept"})
    ).status_code == 403


async def test_desk_decline_and_reinstate(office: Office, outbox: list[EmailMessage]):
    preview = (await office.chief.post(office.url("/decisions/preview"), json={"decision": "decline"})).json()
    assert "After an editorial assessment" in preview["letter"]["body"]
    declined = await office.chief.post(
        office.url("/decisions"),
        json={"decision": "decline", "letter": {"send": True, "subject": "Decision", "body": "Not for us."}},
    )
    assert declined.json()["status"] == "declined"
    assert (await office.mail("asel@example.org"))[-1].text == "Not for us."
    assert {d["decision"] for d in declined.json()["available_decisions"]} == {"reinstate"}

    no_reason = await office.chief.post(office.url("/decisions"), json={"decision": "reinstate"})
    assert problem(no_reason)["code"] == "reason_required"
    reinstated = await office.chief.post(
        office.url("/decisions"),
        json={
            "decision": "reinstate",
            "reason": "Declined by mistake",
            "letter": {"send": False, "subject": "x", "body": "x"},
        },
    )
    assert reinstated.json()["status"] == "queued"
    assert reinstated.json()["decisions"][-1]["letter_to"] == []
    author_decisions = (await workflow(office.author, office))["decisions"]
    assert author_decisions[-1]["reason"] == ""  # internal notes stay with the editors


async def test_withdrawal_stops_reviews(office: Office, run_jobs, outbox: list[EmailMessage]):
    view = await send_to_review(office, run_jobs)
    assignment = await invite(office, view["rounds"][0]["id"], office.reviewer_user.id)
    await office.reviewer.post(f"/api/v1/reviews/{assignment['id']}/accept", json={})
    assert (await office.chief.post(office.url("/withdraw"), json={"reason": "x"})).status_code == 403
    withdrawn = await office.author.post(office.url("/withdraw"), json={"reason": "Published elsewhere"})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "withdrawn" and withdrawn.json()["can_withdraw"] is False
    assert (await office.mail("rev@example.org"))[-1].subject.startswith("Review no longer needed")
    assert "Published elsewhere" in (await office.mail("editor@example.org"))[-1].text
    assert (await office.reviewer.get(f"/api/v1/reviews/{assignment['id']}")).status_code == 404


# ---------------------------------------------------------------------- files across the review


def docx_by(name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "docProps/core.xml", f"<cp:coreProperties><dc:creator>{name}</dc:creator></cp:coreProperties>"
        )
        archive.writestr("word/document.xml", f'<w:document><w:ins w:author="{name}"/></w:document>')
    return buffer.getvalue()


async def test_reviewer_attachments_reach_the_author_without_names(office: Office, run_jobs):
    view = await send_to_review(office, run_jobs)
    round_id = view["rounds"][0]["id"]
    assignment = await invite(office, round_id, office.reviewer_user.id)
    aid = assignment["id"]
    await office.reviewer.post(f"/api/v1/reviews/{aid}/accept", json={})
    content = docx_by("Ruslan Reviewer")
    ticket = await office.reviewer.post(
        f"/api/v1/reviews/{aid}/files/uploads",
        json={"file_name": "annotated.docx", "size": len(content), "genre": "supplementary"},
    )
    assert ticket.status_code == 201, ticket.text
    target = ticket.json()["upload"]
    await office.reviewer.request(target["method"], target["url"], content=content, headers=target["headers"])
    await office.reviewer.post(f"/api/v1/reviews/{aid}/files/{ticket.json()['file']['id']}/complete")
    await run_jobs()
    await office.reviewer.post(
        f"/api/v1/reviews/{aid}/submit",
        json={"answers": ANSWERS, "recommendation": "accept", "comments_for_author": "See the file."},
    )
    attachment = (await workflow(office.chief, office))["rounds"][0]["assignments"][0]["attachments"][0]
    assert attachment["metadata_removed"] is True

    # Before the decision the author cannot fetch it, by any address.
    file_id = attachment["id"]
    assert (
        await office.author.get(office.url(f"/review-rounds/{round_id}/files/{file_id}/download"))
    ).status_code == 404
    assert (await office.author.get(office.url(f"/files/{file_id}/download"))).status_code == 404
    review_copy = (await workflow(office.chief, office))["rounds"][0]["review_files"][0]["id"]
    assert (
        await office.author.get(office.url(f"/review-rounds/{round_id}/files/{review_copy}/download"))
    ).status_code == 404

    await office.chief.post(office.url("/decisions"), json={"decision": "accept"})
    [review] = (await workflow(office.author, office))["rounds"][0]["reviews_for_author"]
    [shared] = review["attachments"]
    redirect = await office.author.get(shared["download_url"])
    assert redirect.status_code == 302
    data = (await office.author.get(redirect.headers["location"])).content
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert all(b"Ruslan" not in archive.read(name) for name in archive.namelist())


# ---------------------------------------------------------------------- discussions


async def test_discussions(office: Office, outbox: list[EmailMessage]):
    view = await workflow(office.author, office)
    editors = [p["user"]["id"] for p in view["people"] if p["role"] == "editor"]
    assert office.reviewer_user.id not in [p["user"]["id"] for p in view["people"]]
    started = await office.author.post(
        office.url("/discussions"),
        json={
            "subject": "Figure 3",
            "message": "May we replace Figure 3?",
            "participant_ids": [office.editor_user.id],
        },
    )
    assert started.status_code == 201, started.text
    discussion = started.json()
    assert discussion["message_count"] == 1
    assert "May we replace Figure 3?" in (await office.mail("editor@example.org"))[-1].text
    assert office.chief_user.id in editors

    # The chief oversees it without being in it, and joins by replying.
    assert [d["subject"] for d in (await workflow(office.chief, office))["discussions"]] == ["Figure 3"]
    replied = await office.chief.post(
        office.url(f"/discussions/{discussion['id']}/messages"), json={"body": "Yes, please."}
    )
    assert replied.json()["message_count"] == 2
    assert (await office.mail("asel@example.org"))[-1].subject.endswith("Figure 3")

    closed = await office.author.patch(
        office.url(f"/discussions/{discussion['id']}"), json={"is_closed": True}
    )
    assert closed.json()["is_closed"] is True
    late = await office.chief.post(
        office.url(f"/discussions/{discussion['id']}/messages"), json={"body": "One more"}
    )
    assert problem(late)["code"] == "discussion_closed"
    outsider = await office.author.post(
        office.url("/discussions"),
        json={"subject": "x", "message": "x", "participant_ids": [office.reviewer_user.id]},
    )
    assert problem(outsider)["code"] == "invalid_participant"


# ---------------------------------------------------------------------- settings


async def test_email_templates(admin: AsyncClient, author: AsyncClient, office: Office):
    templates = (await admin.get("/api/v1/journal/email-templates")).json()
    keys = {t["key"] for t in templates}
    assert {"submission_received", "review_request", "decision_accept", "discussion_message"} <= keys
    request = next(t for t in templates if t["key"] == "review_request")
    assert "submitterName" not in {
        v["name"] for v in request["variables"]
    }  # reviewers never get author names

    bad = await admin.put(
        "/api/v1/journal/email-templates/review_request",
        json={"subject": "Review for {submitterName}", "body": request["body"]},
    )
    assert problem(bad)["code"] == "unknown_placeholder"
    saved = await admin.put(
        "/api/v1/journal/email-templates/decision_desk_decline",
        json={
            "subject": "Our decision on {submissionNumber}",
            "body": "Dear {recipientName}, no.\n\n{journalName}",
        },
    )
    assert saved.json()["is_custom"] is True
    preview = (await office.chief.post(office.url("/decisions/preview"), json={"decision": "decline"})).json()
    assert preview["letter"]["subject"].startswith("Our decision on JRN-")
    assert preview["letter"]["body"] == "Dear Asel Author, no.\n\nTest Journal\n"
    reset = await admin.delete("/api/v1/journal/email-templates/decision_desk_decline")
    assert reset.json()["is_custom"] is False
    assert (await author.get("/api/v1/journal/email-templates")).status_code == 403


async def test_review_forms_and_settings(admin: AsyncClient, office: Office, run_jobs):
    forms = (await admin.get("/api/v1/journal/review-forms")).json()
    [standard] = forms
    assert standard["is_default"] and [q["id"] for q in standard["questions"]][:2] == [
        "summary",
        "originality",
    ]
    one_option = await admin.post(
        "/api/v1/journal/review-forms",
        json={"title": "Short", "questions": [{"type": "choice", "label": "Pick", "options": ["Only"]}]},
    )
    assert one_option.status_code == 422

    settings = await admin.get("/api/v1/journal/review-settings")
    saved = await admin.put(
        "/api/v1/journal/review-settings",
        json={**settings.json(), "method": "single_blind", "review_reminder_days": [7, -2, 7]},
        headers={"If-Match": settings.headers["etag"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["review_reminder_days"] == [-2, 7]

    view = await send_to_review(office, run_jobs)
    assignment = await invite(office, view["rounds"][0]["id"], office.reviewer_user.id)
    assert assignment["method"] == "single_blind"
    # Changing the form later does not change what this reviewer was asked.
    changed = await admin.put(
        f"/api/v1/journal/review-forms/{standard['id']}",
        json={
            **{k: standard[k] for k in ("title", "description", "is_active", "is_default")},
            "questions": [{"type": "textarea", "label": "Anything else?"}],
        },
        headers={"If-Match": f'"{standard["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    page = (await office.reviewer.get(f"/api/v1/reviews/{assignment['id']}")).json()
    assert [q["id"] for q in page["questions"]][:1] == ["summary"]


async def test_editorial_queue_filters(office: Office, run_jobs, db: AsyncSession):
    mine = (await office.editor.get("/api/v1/submissions/editorial", params={"assigned": "true"})).json()[
        "items"
    ]
    assert [s["id"] for s in mine] == [office.submission_id]
    assert (await office.chief.get("/api/v1/submissions/editorial", params={"assigned": "true"})).json()[
        "items"
    ] == []
    await send_to_review(office, run_jobs)
    in_review = (await office.chief.get("/api/v1/submissions/editorial", params={"stage": "review"})).json()[
        "items"
    ]
    assert [s["stage"] for s in in_review] == ["review"]
