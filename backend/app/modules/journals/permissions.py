"""Roles within a journal and the capabilities they grant."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    EDITOR_IN_CHIEF = "editor_in_chief"
    SECTION_EDITOR = "section_editor"
    REVIEWER = "reviewer"
    AUTHOR = "author"
    COPYEDITOR = "copyeditor"
    LAYOUT_EDITOR = "layout_editor"
    PROOFREADER = "proofreader"
    FINANCE_MANAGER = "finance_manager"


class Capability(StrEnum):
    JOURNAL_SETTINGS_EDIT = "journal.settings.edit"
    SECTIONS_MANAGE = "sections.manage"
    USERS_VIEW = "users.view"
    USERS_MANAGE = "users.manage"
    AUDIT_VIEW = "audit.view"
    SUBMISSIONS_CREATE = "submissions.create"
    # Every submitted manuscript in the journal. Section editors see their sections' manuscripts instead.
    SUBMISSIONS_VIEW_ALL = "submissions.view_all"


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.ADMIN: frozenset(Capability),
    Role.EDITOR_IN_CHIEF: frozenset({Capability.USERS_VIEW, Capability.SUBMISSIONS_VIEW_ALL}),
    Role.SECTION_EDITOR: frozenset(),
    Role.REVIEWER: frozenset(),
    Role.AUTHOR: frozenset({Capability.SUBMISSIONS_CREATE}),
    Role.COPYEDITOR: frozenset(),
    Role.LAYOUT_EDITOR: frozenset(),
    Role.PROOFREADER: frozenset(),
    Role.FINANCE_MANAGER: frozenset(),
}

ROLE_LABELS: dict[Role, str] = {
    Role.ADMIN: "Administrator",
    Role.EDITOR_IN_CHIEF: "Editor-in-chief",
    Role.SECTION_EDITOR: "Section editor",
    Role.REVIEWER: "Reviewer",
    Role.AUTHOR: "Author",
    Role.COPYEDITOR: "Copyeditor",
    Role.LAYOUT_EDITOR: "Layout editor",
    Role.PROOFREADER: "Proofreader",
    Role.FINANCE_MANAGER: "Finance manager",
}

# Roles whose holders may be assigned as editors of a section.
SECTION_EDITOR_ROLES = frozenset({Role.EDITOR_IN_CHIEF, Role.SECTION_EDITOR})


def capabilities_for(roles: Iterable[Role]) -> frozenset[Capability]:
    result: set[Capability] = set()
    for role in roles:
        result |= ROLE_CAPABILITIES[role]
    return frozenset(result)
