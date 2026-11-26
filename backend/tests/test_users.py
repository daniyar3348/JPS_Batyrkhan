from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Consent
from app.modules.journals.permissions import Role
from tests.conftest import ClientFactory, UserFactory, link_token, problem


async def test_list_users_with_search_filter_and_pagination(admin: AsyncClient, make_user: UserFactory):
    await make_user("b@example.org", [Role.REVIEWER], given_name="Bolat", family_name="Bekov")
    await make_user("c@example.org", [Role.AUTHOR], given_name="Chingiz", family_name="Abenov")
    await make_user("d@example.org", [Role.REVIEWER, Role.AUTHOR], given_name="Dana", family_name="Zhaksybek")

    page = (await admin.get("/api/v1/users", params={"limit": 2})).json()
    assert [u["family_name"] for u in page["items"]] == ["Abenov", "Admin"]
    rest = (await admin.get("/api/v1/users", params={"limit": 2, "cursor": page["next_cursor"]})).json()
    assert [u["family_name"] for u in rest["items"]] == ["Bekov", "Zhaksybek"]
    assert rest["next_cursor"] is None

    reviewers = (await admin.get("/api/v1/users", params={"role": "reviewer"})).json()["items"]
    assert [u["email"] for u in reviewers] == ["b@example.org", "d@example.org"]
    assert reviewers[1]["roles"] == ["author", "reviewer"]

    found = (await admin.get("/api/v1/users", params={"q": "dana zha"})).json()["items"]
    assert [u["email"] for u in found] == ["d@example.org"]

    # LIKE wildcards in the search box are treated literally.
    assert (await admin.get("/api/v1/users", params={"q": "%"})).json()["items"] == []

    bad_cursor = await admin.get("/api/v1/users", params={"cursor": "garbage"})
    assert problem(bad_cursor)["code"] == "invalid_cursor"


async def test_user_admin_permissions(make_user: UserFactory, signed_in: ClientFactory):
    target = await make_user("target@example.org")
    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF])
    await make_user("author@example.org", [Role.AUTHOR])
    chief = await signed_in("chief@example.org")
    author = await signed_in("author@example.org")

    assert (await chief.get("/api/v1/users")).status_code == 200  # editors-in-chief can look people up
    assert (await chief.put(f"/api/v1/users/{target.id}/roles", json={"roles": ["admin"]})).status_code == 403
    assert (await author.get("/api/v1/users")).status_code == 403


async def test_set_roles_and_keep_one_admin(
    admin: AsyncClient, make_user: UserFactory, signed_in: ClientFactory
):
    me = (await admin.get("/api/v1/me")).json()["user"]
    last_admin = await admin.put(f"/api/v1/users/{me['id']}/roles", json={"roles": ["author"]})
    assert last_admin.status_code == 409
    assert problem(last_admin)["code"] == "last_admin"

    user = await make_user("someone@example.org")
    updated = await admin.put(
        f"/api/v1/users/{user.id}/roles", json={"roles": ["admin", "reviewer", "reviewer"]}
    )
    assert updated.status_code == 200
    assert updated.json()["roles"] == ["admin", "reviewer"]

    # The new administrator sees the change on their next request.
    newcomer = await signed_in("someone@example.org")
    assert "users.manage" in (await newcomer.get("/api/v1/me")).json()["capabilities"]

    # With a second admin, the first one can step down.
    assert (await admin.put(f"/api/v1/users/{me['id']}/roles", json={"roles": ["author"]})).status_code == 200

    events = (await newcomer.get("/api/v1/audit-events", params={"entity_type": "user"})).json()["items"]
    changes = [e for e in events if e["action"] == "user.roles_changed"]
    assert changes[0]["data"] == {"added": ["author"], "removed": ["admin"]}
    assert changes[0]["actor"]["email"] == "admin@example.org"


async def test_deactivation(admin: AsyncClient, make_user: UserFactory, signed_in: ClientFactory):
    await make_user("someone@example.org")
    session = await signed_in("someone@example.org")
    member = (await admin.get("/api/v1/users", params={"q": "someone"})).json()["items"][0]

    response = await admin.patch(f"/api/v1/users/{member['id']}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (await session.get("/api/v1/me")).status_code == 401

    me = (await admin.get("/api/v1/me")).json()["user"]
    self_off = await admin.patch(f"/api/v1/users/{me['id']}", json={"is_active": False})
    assert problem(self_off)["code"] == "self_deactivation"

    assert (await admin.patch(f"/api/v1/users/{member['id']}", json={"is_active": True})).json()[
        "is_active"
    ] is True


async def test_invitation(admin: AsyncClient, client: AsyncClient, db: AsyncSession, run_jobs, outbox):
    invited = await admin.post(
        "/api/v1/users",
        json={
            "email": "New.Editor@example.org",
            "given_name": "Nurlan",
            "family_name": "Editor",
            "roles": ["section_editor", "reviewer"],
        },
    )
    assert invited.status_code == 201, invited.text
    member = invited.json()
    assert member["has_password"] is False and member["roles"] == ["reviewer", "section_editor"]

    duplicate = await admin.post(
        "/api/v1/users", json={"email": "new.editor@example.org", "given_name": "X", "roles": ["author"]}
    )
    assert problem(duplicate)["code"] == "email_taken"

    await run_jobs()
    assert outbox[0].to == "new.editor@example.org"
    assert "Section editor" in outbox[0].text and "Ada Admin" in outbox[0].text
    token = link_token(outbox[0], "accept-invitation")

    info = (await client.post("/api/v1/auth/token-info", json={"token": token})).json()
    assert info["kind"] == "invitation"

    no_consent = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": "x" * 12}
    )
    assert problem(no_consent)["code"] == "consent_required"

    accepted = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": token,
            "password": "x" * 12,
            "accept_privacy_policy": True,
            "accept_cross_border_transfer": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["roles"] == ["reviewer", "section_editor"]
    assert accepted.json()["user"]["email_verified"] is True
    assert len((await db.scalars(select(Consent))).all()) == 2

    resend = await admin.post(f"/api/v1/users/{member['id']}/invitation")
    assert problem(resend)["code"] == "already_accepted"


async def test_audit_log_is_admin_only(admin: AsyncClient, make_user: UserFactory, signed_in: ClientFactory):
    await admin.post("/api/v1/sections", json={"title": "Research", "abbreviation": "ART"})
    events = (await admin.get("/api/v1/audit-events")).json()["items"]
    assert events[0]["action"] == "section.created"
    assert events[0]["data"] == {"title": "Research"}

    await make_user("chief@example.org", [Role.EDITOR_IN_CHIEF])
    chief = await signed_in("chief@example.org")
    assert (await chief.get("/api/v1/audit-events")).status_code == 403
