"""Administrative commands.

python -m app.cli bootstrap --journal-name "..." --admin-email ... [--admin-given-name ...]
python -m app.cli seed-demo
python -m app.cli openapi --output openapi.json
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.security import configure_password_hashing
from app.modules.identity.service import IdentityService
from app.modules.journals.permissions import Role
from app.modules.journals.schemas import SectionCreate
from app.modules.journals.service import JournalService

DEMO_PASSWORD = "demo-password-2026"  # noqa: S105 - development-only demo accounts
DEMO_USERS = [
    ("admin@example.org", "Aigerim", "Admin", [Role.ADMIN]),
    ("chief@example.org", "Daniyar", "Chief", [Role.EDITOR_IN_CHIEF, Role.AUTHOR]),
    ("editor@example.org", "Elena", "Editor", [Role.SECTION_EDITOR, Role.REVIEWER]),
    ("reviewer@example.org", "Ruslan", "Reviewer", [Role.REVIEWER, Role.AUTHOR]),
    ("author@example.org", "Asel", "Author", [Role.AUTHOR]),
    ("finance@example.org", "Farida", "Finance", [Role.FINANCE_MANAGER]),
    ("copyeditor@example.org", "Kamila", "Copyeditor", [Role.COPYEDITOR, Role.PROOFREADER]),
    ("layout@example.org", "Lev", "Layout", [Role.LAYOUT_EDITOR]),
]
DEMO_SECTIONS = [
    SectionCreate(title="Research Articles", abbreviation="ART", sort_order=1, policy="Original research."),
    SectionCreate(title="Review Articles", abbreviation="REV", sort_order=2, policy="Comprehensive reviews."),
    SectionCreate(title="Short Communications", abbreviation="SC", sort_order=3, policy="Brief reports."),
]


def _configure(settings: Settings) -> None:
    configure_password_hashing(
        time_cost=settings.argon2_time_cost,
        memory_kib=settings.argon2_memory_kib,
        parallelism=settings.argon2_parallelism,
    )


async def bootstrap(args: argparse.Namespace) -> None:
    settings = get_settings()
    _configure(settings)
    engine = create_engine(settings.database_url, pool_size=1)
    try:
        async with create_session_factory(engine)() as db:
            journals = JournalService(db, settings)
            journal, created = await journals.bootstrap(slug=settings.journal_slug, name=args.journal_name)
            print(f"Journal '{journal.name}' ({journal.slug}): {'created' if created else 'already exists'}")
            if args.admin_email:
                identity = IdentityService(db, settings)
                admin = await identity.get_by_email(args.admin_email)
                if admin is None:
                    password = os.environ.get("JPS_ADMIN_PASSWORD") or getpass.getpass(
                        "Administrator password: "
                    )
                    if len(password) < 10:
                        sys.exit("The password must be at least 10 characters long.")
                    admin = await identity.create_user(
                        email=args.admin_email,
                        password=password,
                        given_name=args.admin_given_name,
                        family_name=args.admin_family_name,
                        email_verified=True,
                    )
                    print(f"Administrator {admin.email}: created")
                roles = await journals.roles_of(journal.id, admin.id)
                await journals.set_roles(journal, admin, roles | {Role.ADMIN}, actor=None)
                print(f"Administrator {admin.email}: has the admin role")
            await db.commit()
    finally:
        await engine.dispose()


async def seed_demo(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.environment == "production":
        sys.exit("Refusing to create demo accounts in production.")
    _configure(settings)
    engine = create_engine(settings.database_url, pool_size=1)
    try:
        async with create_session_factory(engine)() as db:
            journals = JournalService(db, settings)
            identity = IdentityService(db, settings)
            journal, _ = await journals.bootstrap(
                slug=settings.journal_slug, name="Demo Journal of Applied Science"
            )
            for email, given, family, roles in DEMO_USERS:
                user = await identity.get_by_email(email)
                if user is None:
                    user = await identity.create_user(
                        email=email,
                        password=DEMO_PASSWORD,
                        given_name=given,
                        family_name=family,
                        affiliation="Demo University",
                        email_verified=True,
                    )
                await journals.set_roles(journal, user, roles, actor=None)
            existing = {s.abbreviation for s in await journals.list_sections(journal, include_inactive=True)}
            admin = await identity.get_by_email(DEMO_USERS[0][0])
            if admin is None:
                raise RuntimeError("The demo administrator was not created")
            for section in DEMO_SECTIONS:
                if section.abbreviation not in existing:
                    await journals.create_section(journal, section, actor=admin)
            await db.commit()
        print(f"Demo data ready. Accounts ({DEMO_PASSWORD}):")
        for email, _, _, roles in DEMO_USERS:
            print(f"  {email:24} {', '.join(roles)}")
    finally:
        await engine.dispose()


def openapi(args: argparse.Namespace) -> None:
    from app.main import create_app

    schema = create_app(Settings(api_docs_enabled=True, log_json=False)).openapi()
    output = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    if args.output == "-":
        sys.stdout.write(output)
    else:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"OpenAPI schema written to {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    boot = commands.add_parser("bootstrap", help="Create the journal and the first administrator")
    boot.add_argument("--journal-name", required=True)
    boot.add_argument("--admin-email")
    boot.add_argument("--admin-given-name", default="Administrator")
    boot.add_argument("--admin-family-name", default="")
    boot.set_defaults(handler=lambda a: asyncio.run(bootstrap(a)))

    demo = commands.add_parser("seed-demo", help="Create demo accounts and sections (not in production)")
    demo.set_defaults(handler=lambda a: asyncio.run(seed_demo(a)))

    spec = commands.add_parser("openapi", help="Write the OpenAPI schema to a file")
    spec.add_argument("--output", default="-")
    spec.set_defaults(handler=openapi)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
