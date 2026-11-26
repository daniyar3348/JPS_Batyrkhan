from __future__ import annotations

import re

_ISSN = re.compile(r"^(\d{4})-?(\d{3}[\dX])$")


def normalize_issn(value: str) -> str:
    """Return the ISSN as NNNN-NNNC after verifying its mod-11 check digit."""
    match = _ISSN.match(value.strip().upper())
    if not match:
        raise ValueError("ISSN must look like 0317-8471")
    digits = match.group(1) + match.group(2)
    total = sum(int(digit) * weight for digit, weight in zip(digits[:7], range(8, 1, -1), strict=True))
    check = (11 - total % 11) % 11
    if digits[7] != ("X" if check == 10 else str(check)):
        raise ValueError("This ISSN has an invalid check digit")
    return f"{digits[:4]}-{digits[4:]}"
