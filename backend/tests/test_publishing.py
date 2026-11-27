"""Stage 5: copyediting, production, issues, publishing, versions, DOIs, the public API and OAI-PMH."""

from __future__ import annotations

import hashlib
import hmac
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from defusedxml import ElementTree as SafeET
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import update

from app.core.config import Settings
from app.core.email import EmailMessage
from app.modules.journals.models import Journal, Section
from app.modules.journals.permissions import Role
from app.modules.publishing import crossref
from app.modules.publishing import oai as oai_module
from app.modules.publishing.crossref import CrossrefClient, build_deposit, parse_result
from app.modules.publishing.revalidate import SiteNotifier
from tests.conftest import ClientFactory, UserFactory, problem
from tests.manuscripts import PDF, complete_draft
from tests.test_payments import save_settings

CR = "{http://www.crossref.org/schema/5.3.1}"
OAI = "{http://www.openarchives.org/OAI/2.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"
PUBLISHING: dict[str, Any] = {
    "site_url": "https://journal.example.org",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "copyright_holder": "authors",
    "doi": {
        "enabled": True,
        "prefix": "10.12345",
        "suffix_pattern": "{journal}.{year}.{number}",
        "depositor_name": "Journal office",
        "depositor_email": "office@example.org",
    },
}


@dataclass
class Press:
    author: AsyncClient
    chief: AsyncClient
    copyeditor: AsyncClient
    layout: AsyncClient
    submission_id: int
    copyeditor_id: int
    layout_id: int
    run_jobs: Any
    outbox: list[EmailMessage]

    def url(self, path: str = "") -> str:
        return f"/api/v1/submissions/{self.submission_id}{path}"

    async def mail(self, address: str) -> list[EmailMessage]:
        await self.run_jobs()
        return [m for m in self.outbox if m.to == address]

    async def decide(self, decision: str) -> None:
        response = await self.chief.post(self.url("/decisions"), json={"decision": decision})
        assert response.status_code == 201, response.text
        await self.run_jobs()

    async def publishing(self, http: AsyncClient | None = None) -> dict[str, Any]:
        response = await (http or self.chief).get(self.url("/publishing"))
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def update(self, **changes: Any) -> dict[str, Any]:
        current = await self.publishing()
        response = await self.chief.patch(
            self.url("/publishing"),
            json=changes,
            headers={"If-Match": f'"{current["publication"]["row_version"]}"'},
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


async def put_file(http: AsyncClient, upload: dict[str, Any], content: bytes) -> None:
    sent = await http.request(upload["method"], upload["url"], content=content, headers=upload["headers"])
    assert sent.status_code == 204, sent.text


async def add_galley(press: Press, http: AsyncClient, label: str = "PDF") -> dict[str, Any]:
    ticket = await http.post(
        press.url("/galleys/uploads"), json={"label": label, "file_name": "article.pdf", "size": len(PDF)}
    )
    assert ticket.status_code == 201, ticket.text
    await put_file(http, ticket.json()["upload"], PDF)
    galley_id = ticket.json()["galley"]["id"]
    done = await http.post(press.url(f"/galleys/{galley_id}/complete"))
    assert done.status_code == 200, done.text
    await press.run_jobs()  # the worker checks the file
    body: dict[str, Any] = done.json()
    return body


async def create_issue(chief: AsyncClient, **fields: Any) -> dict[str, Any]:
    response = await chief.post("/api/v1/issues", json={"volume": 1, "number": "1", "year": 2026, **fields})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def save_publishing(chief: AsyncClient, **changes: Any) -> dict[str, Any]:
    current = await chief.get("/api/v1/journal/publishing-settings")
    assert current.status_code == 200, current.text
    saved = await chief.put(
        "/api/v1/journal/publishing-settings",
        json={**PUBLISHING, **changes},
        headers={"If-Match": current.headers["etag"]},
    )
    assert saved.status_code == 200, saved.text
    body: dict[str, Any] = saved.json()
    return body


@pytest.fixture(autouse=True)
def fake_crossref(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "crossref_mode", "fake")


@pytest.fixture
async def press(
    app: FastAPI,
    journal: Journal,
    make_user: UserFactory,
    signed_in: ClientFactory,
    author: AsyncClient,
    sections: dict[str, Section],
    run_jobs,
    outbox: list[EmailMessage],
) -> Press:
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF], given_name="Daniyar", family_name="Chief")
    copyeditor = await make_user(
        "copy@example.org", [Role.COPYEDITOR], given_name="Kamila", family_name="Copy"
    )
    layout = await make_user(
        "layout@example.org", [Role.LAYOUT_EDITOR], given_name="Lev", family_name="Layout"
    )
    async with app.state.session_factory() as db:
        await db.execute(
            update(Journal)
            .where(Journal.id == journal.id)
            .values(issn_online="1234-5678", abbreviation="JRN", publisher="Demo Journal LLP")
        )
        await db.commit()
    chief = await signed_in("chief@example.org")
    await save_publishing(chief)
    draft = await complete_draft(author, sections["ART"].id, run_jobs)
    assert (await author.post(f"/api/v1/submissions/{draft['id']}/submit")).status_code == 200
    await run_jobs()
    return Press(
        author=author,
        chief=chief,
        copyeditor=await signed_in("copy@example.org"),
        layout=await signed_in("layout@example.org"),
        submission_id=draft["id"],
        copyeditor_id=copyeditor.id,
        layout_id=layout.id,
        run_jobs=run_jobs,
        outbox=outbox,
    )


async def to_production(press: Press) -> None:
    await press.decide("accept")
    await press.decide("send_to_production")
    assigned = await press.chief.post(
        press.url("/participants"), json={"user_id": press.layout_id, "role": "layout_editor"}
    )
    assert assigned.status_code == 201, assigned.text


async def publish_in_new_issue(press: Press) -> dict[str, Any]:
    await to_production(press)
    await add_galley(press, press.layout)
    issue = await create_issue(press.chief)
    await press.update(issue_id=issue["id"], pages="1-12")
    scheduled = await press.chief.post(press.url("/publish"))
    assert scheduled.status_code == 200, scheduled.text
    published = await press.chief.post(f"/api/v1/issues/{issue['id']}/publish", json={"make_current": True})
    assert published.status_code == 200, published.text
    await press.run_jobs()
    return issue


# ---------------------------------------------------------------------- copyediting and production


async def test_copyediting_and_production_files(press: Press):
    await press.decide("accept")
    candidates = await press.chief.get(press.url("/participant-candidates"), params={"role": "copyeditor"})
    assert [c["email"] for c in candidates.json()] == ["copy@example.org"]
    assigned = await press.chief.post(
        press.url("/participants"), json={"user_id": press.copyeditor_id, "role": "copyeditor"}
    )
    assert assigned.status_code == 201, assigned.text
    letter = (await press.mail("copy@example.org"))[-1]
    assert letter.subject.startswith("Please copyedit JRN-")

    # The copyeditor sees the article, never its review.
    view = (await press.copyeditor.get(press.url("/workflow"))).json()
    assert view["rounds"] == [] and view["decisions"] == []
    assert view["can_upload"] == {"copyedit": True, "production": False}
    assert (await press.copyeditor.get(press.url("/review-rounds"))).status_code == 404

    # The copyeditor and the author exchange versions of the text.
    for http, name in ((press.copyeditor, "copyedited.docx"), (press.author, "answers.docx")):
        ticket = await http.post(
            press.url("/stage-files/copyedit/uploads"),
            json={"file_name": name, "size": len(PDF), "genre": "manuscript"},
        )
        assert ticket.status_code == 201, ticket.text
    files = (await press.author.get(press.url("/workflow"))).json()["copyedit_files"]
    assert sorted(f["name"] for f in files) == ["answers.docx", "copyedited.docx"]
    # Production files only once the article is in production, and only from the layout editor or editors.
    early = await press.chief.post(
        press.url("/stage-files/production/uploads"),
        json={"file_name": "layout.zip", "size": 10, "genre": "supplementary"},
    )
    assert problem(early)["code"] == "stage_closed"
    # The copyeditor cannot remove the author's file.
    theirs = next(f for f in files if f["name"] == "answers.docx")
    removed = await press.copyeditor.delete(press.url(f"/stage-files/copyedit/{theirs['id']}"))
    assert removed.status_code == 403

    # After acceptance the editors correct the metadata; the author no longer can.
    current = (await press.chief.get(press.url())).json()["publication"]
    fixed = await press.chief.patch(
        press.url("/publication"),
        json={"title": "Editorial workflows in regional journals"},
        headers={"If-Match": f'"{current["row_version"]}"'},
    )
    assert fixed.status_code == 200, fixed.text
    refused = await press.author.patch(
        press.url("/publication"),
        json={"title": "x"},
        headers={"If-Match": f'"{current["row_version"] + 1}"'},
    )
    assert problem(refused)["code"] == "not_editable"

    # Production: the DOI is reserved at once, because it is printed on the galleys.
    await press.decide("send_to_production")
    publishing = await press.publishing()
    year = publishing["publication"]["doi"].split(".")[2]
    assert publishing["publication"]["doi"] == f"10.12345/jrn.{year}.0001"
    work = (await press.copyeditor.get("/api/v1/submissions/production-work")).json()["items"]
    assert [w["id"] for w in work] == [press.submission_id]
    # Galleys are not uploaded as ordinary files.
    wrong = await press.author.post(
        press.url("/files/uploads"), json={"file_name": "a.pdf", "size": 10, "genre": "galley"}
    )
    assert wrong.status_code == 422


# ---------------------------------------------------------------------- publishing


async def test_from_production_to_publication(press: Press, settings: Settings):
    await to_production(press)
    # Not ready: no issue, no galley.
    before = await press.publishing()
    assert before["action"] == "schedule" and not before["ready"]
    assert {c["key"]: c["ok"] for c in before["checks"]} == {
        "metadata": True,
        "issue": False,
        "galleys": False,
        "fee": True,
        "doi": True,
        "address": True,
    }
    assert problem(await press.chief.post(press.url("/publish")))["code"] == "not_ready"
    # The author does not see the publication screen; the layout editor does, and adds the galley.
    assert (await press.author.get(press.url("/publishing"))).status_code == 404
    layout_view = await press.publishing(press.layout)
    assert layout_view["can_edit_galleys"] and not layout_view["can_publish"]
    galley = await add_galley(press, press.layout)
    assert galley["file"]["status"] == "processing"

    issue = await create_issue(press.chief, title="Inaugural issue")
    assert issue["label"] == "Vol. 1 No. 1 (2026): Inaugural issue"
    duplicate = await press.chief.post("/api/v1/issues", json={"volume": 1, "number": "1"})
    assert problem(duplicate)["code"] == "issue_exists"
    ready = await press.update(issue_id=issue["id"], pages="1-12", url_path="editorial-workflows")
    assert ready["ready"] and ready["action"] == "schedule"
    assert ready["galleys"][0]["file"]["status"] == "ready"
    # Only deciding editors publish.
    assert (await press.layout.post(press.url("/publish"))).status_code == 403

    scheduled = (await press.chief.post(press.url("/publish"))).json()
    assert scheduled["status"] == "scheduled" and scheduled["publication"]["status"] == "scheduled"
    assert not scheduled["can_edit"]  # a scheduled version is locked; unschedule to change it
    assert (await press.chief.get("/public/v1/articles/editorial-workflows")).status_code == 404
    deleted = await press.chief.delete(f"/api/v1/issues/{issue['id']}")
    assert problem(deleted)["code"] == "issue_not_empty"
    unscheduled = (await press.chief.post(press.url("/unschedule"))).json()
    assert unscheduled["status"] == "queued" and unscheduled["can_edit"]
    await press.chief.post(press.url("/publish"))

    detail = await press.chief.post(f"/api/v1/issues/{issue['id']}/publish", json={"make_current": True})
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "published" and detail.json()["is_current"]
    assert [a["status"] for a in detail.json()["articles"]] == ["published"]
    after = await press.publishing()
    assert after["status"] == "published" and after["publication"]["copyright_year"] is not None
    assert after["publication"]["copyright_holder"] == "Asel Author"
    assert after["can_create_version"] and after["action"] is None

    # The DOI is registered (fake mode) and the authors are told.
    await press.run_jobs()
    deposits = (await press.chief.get("/api/v1/publishing/doi-deposits")).json()
    assert [(d["status"], d["mode"]) for d in deposits] == [("registered", "fake")]
    letter = (await press.mail("asel@example.org"))[-1]
    assert "has been published" in letter.subject
    assert "https://doi.org/10.12345/jrn." in letter.text and "Vol. 1 No. 1 (2026)" in letter.text

    # Readers.
    article = await press.author.get("/public/v1/articles/editorial-workflows")
    assert article.status_code == 200, article.text
    assert "s-maxage=" in article.headers["cache-control"]
    body = article.json()
    assert body["doi"].startswith("10.12345/jrn.") and body["url"].endswith("/articles/editorial-workflows")
    assert body["authors"][0]["name"] == "Asel Author" and body["issue"]["label"].startswith("Vol. 1")
    assert body["dates"]["accepted"] and body["pages"] == "1-12" and body["version"] == 1
    download = await press.author.get(body["galleys"][0]["download_path"])
    assert download.status_code == 302 and download.headers["cache-control"] == "no-store"
    current = (await press.author.get("/public/v1/issues/current")).json()
    assert current["sections"][0]["section"]["title"] == "Research Articles"
    assert [a["slug"] for a in current["sections"][0]["articles"]] == ["editorial-workflows"]
    assert (await press.author.get("/public/v1/issues/1/1")).json()["id"] == issue["id"]
    archive = (await press.author.get("/public/v1/issues")).json()
    assert [(i["label"], i["article_count"]) for i in archive] == [(issue["label"], 1)]
    found = (await press.author.get("/public/v1/search", params={"q": "editorial workflow"})).json()
    assert found["total"] == 1 and found["items"][0]["slug"] == "editorial-workflows"
    assert (await press.author.get("/public/v1/search", params={"q": "astronomy"})).json()["total"] == 0
    latest = (await press.author.get("/public/v1/articles")).json()
    assert [a["slug"] for a in latest["items"]] == ["editorial-workflows"]


async def test_corrections_are_new_versions(press: Press):
    await publish_in_new_issue(press)
    started = await press.chief.post(press.url("/versions"), json={"note": "Corrected the affiliation."})
    assert started.status_code == 201, started.text
    draft = started.json()
    assert draft["publication"]["version"] == 2 and draft["action"] == "publish_version"
    assert len(draft["galleys"]) == 1 and draft["can_discard_version"]
    # The editor corrects the new version's metadata; readers still see version 1.
    pub = (await press.chief.get(press.url())).json()["publication"]
    fixed = await press.chief.patch(
        press.url("/publication"),
        json={"title": "Editorial workflows (corrected)"},
        headers={"If-Match": f'"{pub["row_version"]}"'},
    )
    assert fixed.status_code == 200, fixed.text
    slug = draft["publication"]["slug"]
    assert (await press.author.get(f"/public/v1/articles/{slug}")).json()["title"] == "Editorial workflows"

    published = await press.chief.post(press.url("/publish"))
    assert published.status_code == 200, published.text
    await press.run_jobs()
    article = (await press.author.get(f"/public/v1/articles/{slug}")).json()
    assert article["title"] == "Editorial workflows (corrected)" and article["version"] == 2
    assert [(v["version"], v["title"]) for v in article["versions"]] == [
        (1, "Editorial workflows"),
        (2, "Editorial workflows (corrected)"),
    ]
    assert article["versions"][1]["note"] == "Corrected the affiliation." and article["dates"]["updated"]
    # Both versions' files stay available; the metadata is deposited again.
    assert all(v["galleys"] for v in article["versions"])
    deposits = (await press.chief.get("/api/v1/publishing/doi-deposits")).json()
    assert [d["status"] for d in deposits] == ["registered", "registered"]
    # Only one e-mail to the authors: for the first publication.
    letters = [m for m in await press.mail("asel@example.org") if "has been published" in m.subject]
    assert len(letters) == 1

    # A draft version can be discarded.
    await press.chief.post(press.url("/versions"), json={})
    discarded = (await press.chief.delete(press.url("/versions/draft"))).json()
    assert [v["version"] for v in discarded["versions"]] == [1, 2] and discarded["can_create_version"]


async def test_publishing_into_a_published_issue_is_immediate(press: Press, monkeypatch: pytest.MonkeyPatch):
    first = await publish_in_new_issue(press)
    # Continuous publication: a second article goes straight into the current issue.
    draft = await complete_draft(
        press.author,
        (await press.chief.get(press.url())).json()["section"]["id"],
        press.run_jobs,
        title="Second",
    )
    await press.author.post(f"/api/v1/submissions/{draft['id']}/submit")
    second = Press(**{**press.__dict__, "submission_id": draft["id"]})
    await to_production(second)
    await add_galley(second, second.layout)
    view = await second.update(issue_id=first["id"])
    assert view["action"] == "publish"
    published = (await second.chief.post(second.url("/publish"))).json()
    assert published["status"] == "published"
    issue = (await press.author.get(f"/public/v1/issues/{first['id']}")).json()
    assert [a["title"] for a in issue["sections"][0]["articles"]] == ["Editorial workflows", "Second"]
    # The editors reorder the issue; readers see the new order.
    order = await press.chief.put(
        f"/api/v1/issues/{first['id']}/order", json={"submission_ids": [draft["id"], press.submission_id]}
    )
    assert order.status_code == 200, order.text
    issue = (await press.author.get(f"/public/v1/issues/{first['id']}")).json()
    assert [a["title"] for a in issue["sections"][0]["articles"]] == ["Second", "Editorial workflows"]

    # Harvesters page through the records with resumption tokens.
    monkeypatch.setattr(oai_module, "PAGE_SIZE", 1)
    page = await oai(press.author, verb="ListIdentifiers", metadataPrefix="oai_dc")
    token = page.find(f"{OAI}ListIdentifiers/{OAI}resumptionToken")
    assert token is not None and token.text and token.get("completeListSize") == "2"
    last = await oai(press.author, verb="ListIdentifiers", resumptionToken=token.text)
    end = last.find(f"{OAI}ListIdentifiers/{OAI}resumptionToken")
    assert end is not None and not end.text and end.get("cursor") == "1"
    assert len(last.findall(f"{OAI}ListIdentifiers/{OAI}header")) == 1


async def test_the_fee_must_be_settled(press: Press, make_user: UserFactory, signed_in: ClientFactory):
    await make_user("money@example.org", [Role.FINANCE_MANAGER])
    finance = await signed_in("money@example.org")
    await save_settings(finance)
    await to_production(press)
    await add_galley(press, press.layout)
    issue = await create_issue(press.chief)
    view = await press.update(issue_id=issue["id"])
    fee = next(c for c in view["checks"] if c["key"] == "fee")
    assert not fee["ok"] and fee["detail"] == "The invoice is not paid yet." and view["fee_settled"] is False
    assert problem(await press.chief.post(press.url("/publish")))["code"] == "not_ready"
    invoice = (await press.author.get(press.url("/billing"))).json()["invoices"][0]
    paid = await finance.post(
        f"/api/v1/payments/invoices/{invoice['id']}/transfers",
        json={"amount": invoice["total"], "reference": "PP-1", "paid_on": "2026-11-20"},
    )
    assert paid.json()["status"] == "paid"
    assert (await press.chief.post(press.url("/publish"))).json()["status"] == "scheduled"


async def test_who_manages_issues_and_settings(
    press: Press, make_user: UserFactory, signed_in: ClientFactory
):
    await make_user("section@example.org", [Role.SECTION_EDITOR])
    section_editor = await signed_in("section@example.org")
    assert (await section_editor.get("/api/v1/issues")).status_code == 200
    assert (await section_editor.post("/api/v1/issues", json={"volume": 3})).status_code == 403
    assert (await section_editor.get("/api/v1/journal/publishing-settings")).status_code == 403
    assert (await press.author.get("/api/v1/issues")).status_code == 403
    invalid = await press.chief.put(
        "/api/v1/journal/publishing-settings",
        json={**PUBLISHING, "doi": {**PUBLISHING["doi"], "suffix_pattern": "{journal}.{year}"}},
        headers={"If-Match": (await press.chief.get("/api/v1/journal/publishing-settings")).headers["etag"]},
    )
    assert invalid.status_code == 422
    saved = await press.chief.get("/api/v1/journal/publishing-settings")
    assert saved.json()["example_doi"] == "10.12345/jrn.2026.0042"
    assert saved.json()["problems"] == [] and saved.json()["crossref_mode"] == "fake"
    empty = await create_issue(press.chief, volume=9)
    assert (await press.chief.delete(f"/api/v1/issues/{empty['id']}")).status_code == 204


# ---------------------------------------------------------------------- Crossref


def published_snapshot() -> dict[str, Any]:
    return {
        "slug": "editorial-workflows",
        "doi": "10.12345/jrn.2026.0001",
        "title": "Editorial workflows",
        "subtitle": "",
        "abstract": "First paragraph.\n\nSecond paragraph.",
        "authors": [
            {
                "given_name": "Asel",
                "family_name": "Author",
                "affiliation": "Nazarbayev University",
                "orcid": "0000-0002-1825-0097",
            },
            {"given_name": "Madina", "family_name": "", "affiliation": "", "orcid": None},
        ],
        "issue": {"volume": 1, "number": "2", "published_at": "2026-11-27T10:00:00+00:00"},
        "pages": "1-12",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "references": ["Smith J. (2020). A study.", "Doe A. (2021). Another."],
        "dates": {"published": "2026-11-27T10:00:00+00:00"},
        "galleys": [{"id": 7, "content_type": "application/pdf"}],
    }


def test_deposit_xml(journal: Journal):
    from app.modules.journals.publishing_settings import PublishingSettings

    journal.issn_online, journal.abbreviation, journal.publisher = "1234-5678", "JRN", "Demo LLP"
    xml = build_deposit(
        journal=journal,
        settings=PublishingSettings.model_validate(PUBLISHING),
        article=published_snapshot(),
        batch_id="batch-1",
        timestamp=20261127100000000,
    )
    root = SafeET.fromstring(xml)
    assert root.get("version") == "5.3.1"
    assert root.findtext(f"{CR}head/{CR}doi_batch_id") == "batch-1"
    item = root.find(f"{CR}body/{CR}journal/{CR}journal_article")
    assert item is not None
    # The schema prescribes the order of the elements.
    assert [child.tag.rsplit("}", 1)[1] for child in item] == [
        "titles",
        "contributors",
        "abstract",
        "publication_date",
        "pages",
        "program",
        "doi_data",
        "citation_list",
    ]
    people = item.findall(f"{CR}contributors/{CR}person_name")
    assert [p.get("sequence") for p in people] == ["first", "additional"]
    assert people[0].findtext(f"{CR}ORCID") == "https://orcid.org/0000-0002-1825-0097"
    # A single name is recorded as the surname, which Crossref requires.
    assert people[1].findtext(f"{CR}surname") == "Madina" and people[1].find(f"{CR}given_name") is None
    assert (
        item.findtext(f"{CR}doi_data/{CR}resource")
        == "https://journal.example.org/articles/editorial-workflows"
    )
    crawler = item.find(f"{CR}doi_data/{CR}collection[@property='crawler-based']/{CR}item")
    assert crawler is not None and crawler.get("crawler") == "iParadigms"
    assert root.findtext(f"{CR}body/{CR}journal/{CR}journal_issue/{CR}issue") == "2"
    assert len(item.findall(f"{CR}citation_list/{CR}citation")) == 2

    journal.issn_online = None
    with pytest.raises(crossref.NotReady, match="ISSN"):
        build_deposit(
            journal=journal,
            settings=PublishingSettings.model_validate(PUBLISHING),
            article=published_snapshot(),
            batch_id="b",
            timestamp=1,
        )


DIAGNOSTIC = """<?xml version="1.0" encoding="UTF-8"?>
<doi_batch_diagnostic status="{status}" sp="cr-test">
  <submission_id>1432</submission_id>
  <batch_id>{batch}</batch_id>
  <record_diagnostic status="{record}">
    <doi>10.12345/jrn.2026.0001</doi>
    <msg>{message}</msg>
  </record_diagnostic>
</doi_batch_diagnostic>"""


def test_reading_crossref_results():
    pending = parse_result(DIAGNOSTIC.format(status="queued", batch="b", record="", message=""))
    assert pending.state == "pending"
    done = parse_result(DIAGNOSTIC.format(status="completed", batch="b", record="Success", message="Added"))
    assert (done.state, done.message) == ("registered", "Success: Added")
    failed = parse_result(
        DIAGNOSTIC.format(status="completed", batch="b", record="Failure", message="Invalid ISSN")
    )
    assert failed.state == "failed" and "Invalid ISSN" in failed.message
    assert parse_result("<html>Not found</html>").state == "pending"


async def test_deposits_with_crossref(press: Press, settings: Settings, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "crossref_mode", "test")
    monkeypatch.setattr(settings, "crossref_username", "journal/role")
    monkeypatch.setattr(settings, "crossref_password", SecretStr("secret"))
    monkeypatch.setattr(settings, "crossref_check_delay_seconds", 0)
    seen: list[httpx.Request] = []
    answers = iter(["queued", "completed"])

    def crossref_api(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/servlet/deposit":
            return httpx.Response(200, text="<html><h2>SUCCESS</h2></html>")
        batch = request.url.params["doi_batch_id"]
        return httpx.Response(
            200, text=DIAGNOSTIC.format(status=next(answers), batch=batch, record="Success", message="Added")
        )

    monkeypatch.setattr(CrossrefClient, "transport", httpx.MockTransport(crossref_api))
    await publish_in_new_issue(press)
    deposit = (await press.chief.get("/api/v1/publishing/doi-deposits")).json()[0]
    assert deposit["status"] == "registered" and deposit["mode"] == "test", deposit
    upload, first_check, _second_check = seen
    assert upload.url.host == "test.crossref.org" and b'name="operation"' in upload.content
    assert b"doMDUpload" in upload.content and b"<doi_batch " in upload.content
    assert first_check.url.params["type"] == "result" and first_check.url.params["usr"] == "journal/role"

    # A refused login is final: no retries, the reason is shown.
    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    monkeypatch.setattr(CrossrefClient, "transport", httpx.MockTransport(refused))
    again = await press.chief.post(press.url("/doi/deposits"))
    assert again.status_code == 202, again.text
    await press.run_jobs()
    latest = (await press.chief.get("/api/v1/publishing/doi-deposits", params={"status": "failed"})).json()
    assert len(latest) == 1 and "login" in latest[0]["message"]


async def test_the_site_is_told_what_to_rebuild(
    press: Press, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "site_revalidate_url", "https://site.example/api/revalidate")
    monkeypatch.setattr(settings, "site_revalidate_secret", SecretStr("shared-secret"))
    calls: list[httpx.Request] = []

    def site(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"revalidated": True})

    monkeypatch.setattr(SiteNotifier, "transport", httpx.MockTransport(site))
    await publish_in_new_issue(press)
    assert calls
    paths = set()
    for request in calls:
        expected = "sha256=" + hmac.new(b"shared-secret", request.content, hashlib.sha256).hexdigest()
        assert request.headers["x-jps-signature"] == expected
        paths |= set(json.loads(request.content)["paths"])
    assert {"/", "/issues", "/articles/jrn-2026-0001"} <= paths


# ---------------------------------------------------------------------- OAI-PMH


async def oai(http: AsyncClient, **args: str) -> ET.Element:
    response = await http.get("/oai", params=args)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/xml")
    return SafeET.fromstring(response.content)


async def test_oai_pmh(press: Press, client: AsyncClient):
    await publish_in_new_issue(press)
    identify = await oai(client, verb="Identify")
    assert identify.findtext(f"{OAI}Identify/{OAI}protocolVersion") == "2.0"
    assert identify.findtext(f"{OAI}Identify/{OAI}granularity") == "YYYY-MM-DDThh:mm:ssZ"

    records = await oai(client, verb="ListRecords", metadataPrefix="oai_dc")
    record = records.find(f"{OAI}ListRecords/{OAI}record")
    assert record is not None
    identifier = record.findtext(f"{OAI}header/{OAI}identifier")
    assert identifier == f"oai:journal.example.org:article/{press.submission_id}"
    assert [s.text for s in record.findall(f"{OAI}header/{OAI}setSpec")] == ["journal", "journal:ART"]
    dc = record.find(f"{OAI}metadata/{{http://www.openarchives.org/OAI/2.0/oai_dc/}}dc")
    assert dc is not None
    assert dc.findtext(f"{DC}title") == "Editorial workflows"
    assert dc.findtext(f"{DC}creator") == "Author, Asel"
    identifiers = [e.text for e in dc.findall(f"{DC}identifier")]
    assert any(i and i.startswith("https://doi.org/10.12345/") for i in identifiers)

    single = await oai(client, verb="GetRecord", identifier=identifier, metadataPrefix="oai_dc")
    assert single.find(f"{OAI}GetRecord/{OAI}record") is not None
    sets = await oai(client, verb="ListSets")
    assert [s.text for s in sets.iter(f"{OAI}setSpec")] == ["journal", "journal:ART", "journal:REV"]
    in_set = await oai(client, verb="ListIdentifiers", metadataPrefix="oai_dc", set="journal:REV")
    assert in_set.find(f"{OAI}error").get("code") == "noRecordsMatch"  # type: ignore[union-attr]

    def error(root: ET.Element) -> str | None:
        element = root.find(f"{OAI}error")
        return element.get("code") if element is not None else None

    assert error(await oai(client, verb="Dance")) == "badVerb"
    assert error(await oai(client, verb="ListRecords")) == "badArgument"
    assert error(await oai(client, verb="ListRecords", metadataPrefix="marc")) == "cannotDisseminateFormat"
    assert error(await oai(client, verb="GetRecord", identifier="oai:x:1", metadataPrefix="oai_dc")) == (
        "idDoesNotExist"
    )
    assert error(
        await oai(client, verb="ListRecords", metadataPrefix="oai_dc", **{"from": "2999-01-01"})
    ) == ("noRecordsMatch")
    assert error(await oai(client, verb="ListRecords", resumptionToken="nonsense")) == "badResumptionToken"
    repeated = await client.get("/oai?verb=Identify&verb=Identify")
    assert error(SafeET.fromstring(repeated.content)) == "badArgument"
    posted = await client.post(
        "/oai", content="verb=Identify", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert error(SafeET.fromstring(posted.content)) is None
