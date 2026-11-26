from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.modules.identity.models import AuthSession, Consent, User, UserToken
from tests.conftest import PASSWORD, ClientFactory, UserFactory, link_token, problem

REGISTRATION = {
    "email": "Asel.Author@Example.org",
    "password": PASSWORD,
    "given_name": "Asel",
    "family_name": "Author",
    "affiliation": "Al-Farabi Kazakh National University",
    "country": "kz",
    "interests": ["Machine learning", "machine learning ", "Linguistics"],
    "accept_privacy_policy": True,
    "accept_cross_border_transfer": True,
}


async def test_register_signs_in_and_sends_confirmation(
    client: AsyncClient, db: AsyncSession, run_jobs, outbox
):
    response = await client.post("/api/v1/auth/register", json=REGISTRATION)

    assert response.status_code == 201, response.text
    me = response.json()
    assert me["user"]["email"] == "asel.author@example.org"
    assert me["user"]["country"] == "KZ"
    assert me["user"]["interests"] == ["Machine learning", "Linguistics"]
    assert me["user"]["email_verified"] is False
    assert me["roles"] == ["author"]
    assert (await db.scalar(select(User.last_login_at))) is not None
    assert me["csrf_token"]
    assert "jps_session" in response.cookies
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie

    consents = (await db.scalars(select(Consent.kind))).all()
    assert sorted(consents) == ["cross_border_transfer", "privacy_policy"]

    assert outbox == []  # nothing is sent until the worker runs
    assert await run_jobs() == 1
    assert len(outbox) == 1
    assert outbox[0].to == "asel.author@example.org"
    assert "Confirm your e-mail" in outbox[0].subject

    token = link_token(outbox[0], "verify-email")
    verified = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True

    reused = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert reused.status_code == 400
    assert problem(reused)["code"] == "invalid_token"


async def test_register_as_reviewer(client: AsyncClient):
    response = await client.post("/api/v1/auth/register", json=REGISTRATION | {"wants_to_review": True})
    assert response.status_code == 201
    assert response.json()["roles"] == ["author", "reviewer"]


async def test_register_requires_both_consents(client: AsyncClient):
    for missing in ("accept_privacy_policy", "accept_cross_border_transfer"):
        response = await client.post("/api/v1/auth/register", json=REGISTRATION | {missing: False})
        assert response.status_code == 422
        assert problem(response)["code"] == "validation_failed"


async def test_register_rejects_duplicate_email_case_insensitively(
    client: AsyncClient, make_user: UserFactory
):
    await make_user("asel.author@example.org")
    response = await client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 409
    assert problem(response)["code"] == "email_taken"


async def test_register_validates_input(client: AsyncClient):
    bad = REGISTRATION | {"password": "short", "email": "not-an-email", "country": "Kazakhstan"}
    response = await client.post("/api/v1/auth/register", json=bad)
    assert response.status_code == 422
    fields = {error["field"] for error in problem(response)["errors"]}
    assert {"password", "email", "country"} <= fields


async def test_login_logout(client: AsyncClient, make_user: UserFactory):
    await make_user("someone@example.org")
    response = await client.post(
        "/api/v1/auth/login", json={"email": " SomeOne@example.org ", "password": PASSWORD}
    )
    assert response.status_code == 200
    csrf = response.json()["csrf_token"]

    assert (await client.get("/api/v1/me")).status_code == 200

    # Mutating requests need the CSRF header.
    assert problem(await client.post("/api/v1/auth/logout"))["code"] == "csrf_failed"
    wrong = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})
    assert wrong.status_code == 403

    assert (await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})).status_code == 204
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_login_with_wrong_password_or_unknown_user(client: AsyncClient, make_user: UserFactory):
    await make_user("someone@example.org")
    for email, password in (("someone@example.org", "wrong-password"), ("nobody@example.org", PASSWORD)):
        response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 401
        assert problem(response)["code"] == "invalid_credentials"


async def test_repeated_failures_lock_the_account(client: AsyncClient, make_user: UserFactory, settings):
    await make_user("someone@example.org")
    for _ in range(settings.login_max_failures - 1):
        response = await client.post(
            "/api/v1/auth/login", json={"email": "someone@example.org", "password": "nope-nope"}
        )
        assert response.status_code == 401
    locked = await client.post(
        "/api/v1/auth/login", json={"email": "someone@example.org", "password": "nope-nope"}
    )
    assert locked.status_code == 429
    assert problem(locked)["code"] == "account_locked"
    assert int(locked.headers["retry-after"]) > 0

    # Even the right password is refused while locked.
    still = await client.post(
        "/api/v1/auth/login", json={"email": "someone@example.org", "password": PASSWORD}
    )
    assert still.status_code == 429


async def test_inactive_user_cannot_sign_in(client: AsyncClient, make_user: UserFactory, db: AsyncSession):
    user = await make_user("someone@example.org")
    await db.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"email": "someone@example.org", "password": PASSWORD}
    )
    assert response.status_code == 401


async def test_sessions_expire(signed_in: ClientFactory, make_user: UserFactory, db: AsyncSession, settings):
    await make_user("someone@example.org")
    http = await signed_in("someone@example.org")
    assert (await http.get("/api/v1/me")).status_code == 200

    idle = utcnow() - timedelta(days=settings.session_idle_days, minutes=1)
    await db.execute(update(AuthSession).values(last_seen_at=idle))
    await db.commit()
    expired = await http.get("/api/v1/me")
    assert expired.status_code == 401
    assert problem(expired)["code"] == "session_expired"


async def test_session_activity_is_recorded(
    signed_in: ClientFactory, make_user: UserFactory, db: AsyncSession
):
    await make_user("someone@example.org")
    http = await signed_in("someone@example.org")
    stale = utcnow() - timedelta(hours=1)
    await db.execute(update(AuthSession).values(last_seen_at=stale))
    await db.commit()
    assert (await http.get("/api/v1/me")).status_code == 200
    db.expire_all()
    last_seen = await db.scalar(select(AuthSession.last_seen_at))
    assert last_seen is not None and last_seen > stale + timedelta(minutes=30)


async def test_password_reset(
    client: AsyncClient, make_user: UserFactory, signed_in: ClientFactory, run_jobs, outbox
):
    await make_user("someone@example.org")
    other_session = await signed_in("someone@example.org")

    for email in ("someone@example.org", "nobody@example.org"):
        response = await client.post("/api/v1/auth/password-reset", json={"email": email})
        assert response.status_code == 202
    await run_jobs()
    assert [message.to for message in outbox] == ["someone@example.org"]

    token = link_token(outbox[0], "reset-password")
    info = await client.post("/api/v1/auth/token-info", json={"token": token})
    assert info.json() == {"kind": "password_reset", "email": "someone@example.org", "full_name": "Test User"}

    new_password = "a-brand-new-password"
    done = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": new_password}
    )
    assert done.status_code == 200
    assert done.json()["user"]["email"] == "someone@example.org"

    assert (await other_session.get("/api/v1/me")).status_code == 401  # all old sessions are gone
    again = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": new_password}
    )
    assert problem(again)["code"] == "invalid_token"
    old = await client.post("/api/v1/auth/login", json={"email": "someone@example.org", "password": PASSWORD})
    assert old.status_code == 401
    new = await client.post(
        "/api/v1/auth/login", json={"email": "someone@example.org", "password": new_password}
    )
    assert new.status_code == 200


async def test_reset_links_expire_and_only_the_newest_works(
    client: AsyncClient, make_user: UserFactory, db: AsyncSession, run_jobs, outbox
):
    await make_user("someone@example.org")
    await client.post("/api/v1/auth/password-reset", json={"email": "someone@example.org"})
    await db.execute(
        update(UserToken).values(created_at=utcnow() - timedelta(minutes=5))
    )  # skip the resend limit
    await db.commit()
    await client.post("/api/v1/auth/password-reset", json={"email": "someone@example.org"})
    await run_jobs()
    first, second = (link_token(message, "reset-password") for message in outbox)

    stale = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": first, "password": "x" * 12}
    )
    assert problem(stale)["code"] == "invalid_token"

    await db.execute(update(UserToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    await db.commit()
    expired = await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": second, "password": "x" * 12}
    )
    assert problem(expired)["code"] == "invalid_token"


async def test_reset_requests_are_rate_limited(client: AsyncClient, make_user: UserFactory, run_jobs, outbox):
    await make_user("someone@example.org")
    for _ in range(3):
        await client.post("/api/v1/auth/password-reset", json={"email": "someone@example.org"})
    await run_jobs()
    assert len(outbox) == 1


async def test_change_password_signs_out_other_sessions(signed_in: ClientFactory, make_user: UserFactory):
    await make_user("someone@example.org")
    current = await signed_in("someone@example.org")
    other = await signed_in("someone@example.org")

    wrong = await current.post(
        "/api/v1/me/password", json={"current_password": "wrong-one", "new_password": "another-password-1"}
    )
    assert wrong.status_code == 422
    assert problem(wrong)["errors"][0]["field"] == "current_password"

    ok = await current.post(
        "/api/v1/me/password", json={"current_password": PASSWORD, "new_password": "another-password-1"}
    )
    assert ok.status_code == 204
    assert (await current.get("/api/v1/me")).status_code == 200
    assert (await other.get("/api/v1/me")).status_code == 401


async def test_update_profile(signed_in: ClientFactory, make_user: UserFactory):
    await make_user("someone@example.org")
    http = await signed_in("someone@example.org")
    response = await http.patch(
        "/api/v1/me",
        json={
            "orcid": "https://orcid.org/0000-0002-1825-0097",
            "affiliation": "  Nazarbayev University ",
            "country": "kz",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["orcid"] == "0000-0002-1825-0097"
    assert body["affiliation"] == "Nazarbayev University"
    assert body["country"] == "KZ"
    assert body["given_name"] == "Test"  # untouched

    bad = await http.patch("/api/v1/me", json={"orcid": "0000-0002-1825-0096", "given_name": None})
    assert bad.status_code == 422
    assert {error["field"] for error in problem(bad)["errors"]} == {"orcid", "given_name"}


async def test_resend_verification(signed_in: ClientFactory, make_user: UserFactory, run_jobs, outbox):
    await make_user("someone@example.org", verified=False)
    http = await signed_in("someone@example.org")
    assert (await http.post("/api/v1/me/email-verification")).status_code == 202
    too_soon = await http.post("/api/v1/me/email-verification")
    assert too_soon.status_code == 429
    await run_jobs()
    assert len(outbox) == 1

    await make_user("verified@example.org")
    verified = await signed_in("verified@example.org")
    assert problem(await verified.post("/api/v1/me/email-verification"))["code"] == "already_verified"


async def test_me_requires_a_session(client: AsyncClient):
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert problem(response)["code"] == "unauthorized"
    assert response.headers["x-request-id"]
