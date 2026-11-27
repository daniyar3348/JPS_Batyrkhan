"""Stage 6: what the journal's public site shows besides articles — pages, announcements, editorial board."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.journals.models import Section
from app.modules.journals.permissions import Role
from app.modules.publishing.revalidate import SiteNotifier
from tests.conftest import ClientFactory, UserFactory, problem
from tests.test_payments import save_settings

GUIDELINES = {
    "slug": "author-guidelines",
    "title": "Author guidelines",
    "body": "## Preparing the manuscript\n\nUse **APA** style.",
    "position": 2,
    "in_menu": True,
    "is_published": True,
}


@pytest.fixture
async def chief(make_user: UserFactory, signed_in: ClientFactory) -> AsyncClient:
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF], given_name="Daniyar", family_name="Chief")
    return await signed_in("chief@example.org")


@pytest.fixture
def site_calls(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Paths the site is asked to rebuild, one list per request."""
    monkeypatch.setattr(settings, "site_revalidate_url", "https://site.example/api/revalidate")
    monkeypatch.setattr(settings, "site_revalidate_secret", SecretStr("shared-secret"))
    calls: list[list[str]] = []

    def site(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["paths"])
        return httpx.Response(200)

    monkeypatch.setattr(SiteNotifier, "transport", httpx.MockTransport(site))
    return calls


async def test_pages(chief: AsyncClient, client: AsyncClient, author: AsyncClient, site_calls, run_jobs):
    created = await chief.post("/api/v1/site/pages", json=GUIDELINES)
    assert created.status_code == 201, created.text
    page = created.json()
    await run_jobs()
    assert site_calls == [["*"]]  # a new page in the menu: every page shows the menu

    # Reserved and taken addresses.
    reserved = await chief.post("/api/v1/site/pages", json={**GUIDELINES, "slug": "articles"})
    assert reserved.status_code == 422
    taken = await chief.post("/api/v1/site/pages", json={**GUIDELINES, "title": "Copy"})
    assert problem(taken)["code"] == "slug_taken"
    assert (await author.post("/api/v1/site/pages", json=GUIDELINES)).status_code == 403

    # A draft is not public.
    draft = await chief.post(
        "/api/v1/site/pages", json={**GUIDELINES, "slug": "ethics", "title": "Ethics", "is_published": False}
    )
    assert (await client.get("/public/v1/pages/ethics")).status_code == 404
    listed = (await client.get("/public/v1/pages")).json()
    assert listed == [{"slug": "author-guidelines", "title": "Author guidelines", "in_menu": True}]
    public = await client.get("/public/v1/pages/author-guidelines")
    assert public.json()["body"].startswith("## Preparing") and "s-maxage" in public.headers["cache-control"]

    # Editing only the text rebuilds only that page.
    site_calls.clear()
    edited = await chief.put(
        f"/api/v1/site/pages/{page['id']}",
        json={**GUIDELINES, "body": "Use **Vancouver** style."},
        headers={"If-Match": f'"{page["row_version"]}"'},
    )
    assert edited.status_code == 200, edited.text
    stale = await chief.put(
        f"/api/v1/site/pages/{page['id']}", json=GUIDELINES, headers={"If-Match": f'"{page["row_version"]}"'}
    )
    assert stale.status_code == 412
    await run_jobs()
    assert site_calls == [["/author-guidelines"]]
    assert (await chief.delete(f"/api/v1/site/pages/{draft.json()['id']}")).status_code == 204


async def test_announcements(chief: AsyncClient, client: AsyncClient, site_calls, run_jobs):
    draft = (
        await chief.post("/api/v1/site/announcements", json={"title": "Call for papers", "summary": "Soon."})
    ).json()
    assert draft["published_at"] is None
    assert (await client.get("/public/v1/announcements")).json() == []
    await run_jobs()
    assert site_calls == []  # drafts are not on the site

    published = await chief.put(
        f"/api/v1/site/announcements/{draft['id']}",
        json={
            "title": "Call for papers",
            "summary": "Submissions are open.",
            "body": "Send by **1 March**.",
            "published": True,
        },
        headers={"If-Match": f'"{draft["row_version"]}"'},
    )
    assert published.status_code == 200, published.text
    assert published.json()["published_at"] is not None
    await run_jobs()
    assert site_calls == [["/", "/announcements", f"/announcements/{draft['id']}", "/feed.xml"]]
    public = (await client.get("/public/v1/announcements")).json()
    assert [a["title"] for a in public] == ["Call for papers"]
    assert (await client.get(f"/public/v1/announcements/{draft['id']}")).json()[
        "body"
    ] == "Send by **1 March**."

    second = await chief.post(
        "/api/v1/site/announcements", json={"title": "Issue 1 is out", "published": True}
    )
    titles = [a["title"] for a in (await client.get("/public/v1/announcements")).json()]
    assert titles == ["Issue 1 is out", "Call for papers"]
    assert (await chief.delete(f"/api/v1/site/announcements/{second.json()['id']}")).status_code == 204


async def test_journal_profile_for_the_site(
    chief: AsyncClient,
    client: AsyncClient,
    make_user: UserFactory,
    signed_in: ClientFactory,
    sections: dict[str, Section],
    site_calls,
    run_jobs,
):
    current = await chief.get("/api/v1/journal/site-settings")
    assert current.status_code == 200
    board: dict[str, Any] = {
        "tagline": "Applied science from Central Asia",
        "publication_frequency": "Two issues a year, with continuous publication.",
        "editorial_board": [
            {
                "name": "Daniyar Chief",
                "role": "Editor-in-Chief",
                "affiliation": "Nazarbayev University",
                "country": "Kazakhstan",
                "orcid": "https://orcid.org/0000-0002-1825-0097",
            },
            {"name": "Elena Editor", "role": "Associate Editor"},
        ],
    }
    saved = await chief.put(
        "/api/v1/journal/site-settings", json=board, headers={"If-Match": current.headers["etag"]}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["editorial_board"][0]["orcid"] == "0000-0002-1825-0097"
    await run_jobs()
    assert site_calls == [["*"]]

    await make_user("money@example.org", [Role.FINANCE_MANAGER])
    await save_settings(
        await signed_in("money@example.org"), section_fees={str(sections["REV"].id): "50000.00"}
    )
    profile = (await client.get("/public/v1/journal")).json()
    assert profile["tagline"] == "Applied science from Central Asia"
    assert [m["role"] for m in profile["editorial_board"]] == ["Editor-in-Chief", "Associate Editor"]
    fees = profile["fees"]
    assert fees["charged"] and fees["currency"] == "KZT" and fees["amount"] == "100000.00"
    assert fees["section_fees"] == [
        {"section_id": sections["REV"].id, "section_title": "Reviews", "amount": "50000.00"}
    ]
    assert "waiver" in fees["waiver_policy"]
