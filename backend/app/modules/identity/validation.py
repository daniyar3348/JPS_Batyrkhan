"""Validation of identifiers used in user profiles."""

from __future__ import annotations

import re

_ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
_ORCID_PREFIXES = ("https://orcid.org/", "http://orcid.org/", "orcid.org/")


def normalize_orcid(value: str) -> str:
    """Accept an ORCID iD with or without the https://orcid.org/ prefix and verify its ISO 7064 checksum."""
    candidate = value.strip()
    for prefix in _ORCID_PREFIXES:
        if candidate.lower().startswith(prefix):
            candidate = candidate[len(prefix) :]
            break
    candidate = candidate.upper()
    if not _ORCID.match(candidate):
        raise ValueError("ORCID iD must look like 0000-0002-1825-0097")
    digits = candidate.replace("-", "")
    total = 0
    for char in digits[:-1]:
        total = (total + int(char)) * 2
    check = (12 - total % 11) % 11
    if digits[-1] != ("X" if check == 10 else str(check)):
        raise ValueError("This ORCID iD has an invalid check digit")
    return candidate


def normalize_interests(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        term = " ".join(value.split())
        if term and term.lower() not in seen:
            seen[term.lower()] = term
    if len(seen) > 30:
        raise ValueError("List at most 30 interests")
    if any(len(term) > 100 for term in seen.values()):
        raise ValueError("Each interest must be 100 characters or fewer")
    return list(seen.values())
