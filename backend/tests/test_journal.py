from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.journals.models import Journal
from app.modules.journals.permissions import Role
from tests.conftest import ClientFactory, UserFactory, problem


async def test_health_and_readiness(client: AsyncClient, db: AsyncSession):
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).json() == {"status": "ready", "journal": "journal"}

    await db.execute(delete(Journal))
    await db.commit()
    not_ready = await client.get("/ready")
    assert not_ready.status_code == 503
    assert problem(not_ready)["code"] == "journal_not_configured"


async def test_journal_settings_use_optimistic_locking(admin: AsyncClient):
    current = await admin.get("/api/v1/journal")
    assert current.status_code == 200
    etag = current.headers["etag"]
    assert etag == f'"{current.json()["version"]}"'

    missing = await admin.patch("/api/v1/journal", json={"name": "New name"})
    assert missing.status_code == 428

    updated = await admin.patch(
        "/api/v1/journal",
        json={
            "name": "Journal of Applied Science",
            "issn_online": "03178471",
            "contact_email": "office@example.org",
        },
        headers={"If-Match": etag},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "Journal of Applied Science"
    assert body["issn_online"] == "0317-8471"
    assert body["version"] == current.json()["version"] + 1
    assert updated.headers["etag"] == f'"{body["version"]}"'

    stale = await admin.patch("/api/v1/journal", json={"name": "Lost update"}, headers={"If-Match": etag})
    assert stale.status_code == 412
    assert problem(stale)["code"] == "version_mismatch"


async def test_journal_settings_validation(admin: AsyncClient):
    etag = (await admin.get("/api/v1/journal")).headers["etag"]
    response = await admin.patch(
        "/api/v1/journal", json={"issn_print": "0317-8470", "name": None}, headers={"If-Match": etag}
    )
    assert response.status_code == 422
    assert {error["field"] for error in problem(response)["errors"]} == {"issn_print", "name"}


async def test_only_admins_change_settings(make_user: UserFactory, signed_in: ClientFactory):
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF])
    chief = await signed_in("chief@example.org")
    etag = (await chief.get("/api/v1/journal")).headers["etag"]
    response = await chief.patch("/api/v1/journal", json={"name": "Mine now"}, headers={"If-Match": etag})
    assert response.status_code == 403


async def test_sections_crud(admin: AsyncClient):
    created = await admin.post(
        "/api/v1/sections", json={"title": "Research Articles", "abbreviation": "ART", "sort_order": 2}
    )
    assert created.status_code == 201, created.text
    section = created.json()
    assert section["is_active"] is True and section["editors"] == []
    await admin.post("/api/v1/sections", json={"title": "Reviews", "abbreviation": "REV", "sort_order": 1})

    duplicate = await admin.post("/api/v1/sections", json={"title": "Other", "abbreviation": "art"})
    assert duplicate.status_code == 422
    assert problem(duplicate)["code"] == "duplicate_abbreviation"

    titles = [s["title"] for s in (await admin.get("/api/v1/sections")).json()]
    assert titles == ["Reviews", "Research Articles"]

    url = f"/api/v1/sections/{section['id']}"
    patched = await admin.patch(
        url, json={"is_active": False}, headers={"If-Match": f'"{section["version"]}"'}
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    assert patched.json()["version"] == section["version"] + 1

    stale = await admin.patch(url, json={"title": "X"}, headers={"If-Match": f'"{section["version"]}"'})
    assert stale.status_code == 412

    assert (await admin.delete(url)).status_code == 204
    assert (await admin.get(url)).status_code == 404


async def test_authors_see_only_active_sections(
    admin: AsyncClient, make_user: UserFactory, signed_in: ClientFactory
):
    await admin.post("/api/v1/sections", json={"title": "Open", "abbreviation": "OPEN"})
    closed = (
        await admin.post(
            "/api/v1/sections", json={"title": "Closed", "abbreviation": "CL", "is_active": False}
        )
    ).json()

    await make_user("author@example.org", [Role.AUTHOR])
    author = await signed_in("author@example.org")
    assert [s["title"] for s in (await author.get("/api/v1/sections")).json()] == ["Open"]
    assert (await author.get(f"/api/v1/sections/{closed['id']}")).status_code == 404
    assert (
        await author.post("/api/v1/sections", json={"title": "Mine", "abbreviation": "M"})
    ).status_code == 403


async def test_section_editors_must_be_editors(admin: AsyncClient, make_user: UserFactory):
    section = (await admin.post("/api/v1/sections", json={"title": "Research", "abbreviation": "ART"})).json()
    editor = await make_user(
        "editor@example.org", [Role.SECTION_EDITOR], given_name="Elena", family_name="Editor"
    )
    author = await make_user("author@example.org", [Role.AUTHOR])
    url = f"/api/v1/sections/{section['id']}/editors"

    rejected = await admin.put(url, json={"user_ids": [editor.id, author.id]})
    assert rejected.status_code == 422
    assert problem(rejected)["code"] == "not_an_editor"

    unknown = await admin.put(url, json={"user_ids": [999999]})
    assert problem(unknown)["code"] == "unknown_users"

    accepted = await admin.put(url, json={"user_ids": [editor.id, editor.id]})
    assert accepted.status_code == 200
    assert [e["full_name"] for e in accepted.json()["editors"]] == ["Elena Editor"]

    # Losing the editorial role removes the person from the section.
    await admin.put(f"/api/v1/users/{editor.id}/roles", json={"roles": ["reviewer"]})
    assert (await admin.get(f"/api/v1/sections/{section['id']}")).json()["editors"] == []


async def test_public_journal_profile(client: AsyncClient, admin: AsyncClient):
    await admin.post(
        "/api/v1/sections", json={"title": "Open", "abbreviation": "OPEN", "policy": "Original work."}
    )
    await admin.post("/api/v1/sections", json={"title": "Closed", "abbreviation": "CL", "is_active": False})

    response = await client.get("/public/v1/journal")
    assert response.status_code == 200
    assert "s-maxage" in response.headers["cache-control"]
    body = response.json()
    assert body["name"] == "Test Journal"
    assert [(s["title"], s["policy"]) for s in body["sections"]] == [("Open", "Original work.")]
