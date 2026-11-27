"""Remove the names hidden in a document's metadata before reviewers or authors see it.

Word processors record who wrote a file, who last saved it, and who made each tracked change and
comment. In blind review these names must not reach the other side. This module rewrites the
metadata of the common formats; the visible text is never touched (authors are asked to remove
their names from it themselves).

``strip`` returns the new bytes and whether metadata could be removed. For formats it does not
understand (.doc, LaTeX, images...) it returns the file unchanged and ``False``, so editors can be
warned to check the file by hand.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Callable

logger = logging.getLogger(__name__)

ANONYMOUS = "Anonymous"
# Larger archives are left alone rather than unpacked in memory.
MAX_UNPACKED_BYTES = 300 * 1024 * 1024

# --------------------------------------------------------------------------- Office Open XML (.docx, .xlsx)

_OOXML_CORE = re.compile(
    rb"(<(dc:creator|cp:lastModifiedBy|dc:contributor|cp:contentStatus)[^>]*>)(.*?)(</\2>)", re.S
)
_OOXML_APP = re.compile(rb"(<(Company|Manager)[^>]*>)(.*?)(</\2>)", re.S)
# Authors of tracked changes and comments: w:author="Jane Doe" w:initials="JD"
_OOXML_ATTRS = re.compile(rb'\b(w:author|w:initials|author|w15:userId|w15:providerId)="[^"]*"')
_OOXML_PERSON = re.compile(rb'(<w15:person\b[^>]*\bw15:author=)"[^"]*"')


def _ooxml_part(name: str, data: bytes) -> bytes:
    if name == "docProps/core.xml":
        return _OOXML_CORE.sub(lambda m: m.group(1) + m.group(4), data)
    if name == "docProps/app.xml":
        return _OOXML_APP.sub(lambda m: m.group(1) + m.group(4), data)
    if name.endswith(".xml") and (name.startswith(("word/", "xl/", "ppt/"))):
        data = _OOXML_PERSON.sub(rb'\1"' + ANONYMOUS.encode() + b'"', data)
        return _OOXML_ATTRS.sub(
            lambda m: (
                m.group(1) + b'="' + (b"A" if m.group(1).endswith(b"initials") else ANONYMOUS.encode()) + b'"'
            ),
            data,
        )
    return data


# --------------------------------------------------------------------------- OpenDocument (.odt, .ods)

_ODF_META = re.compile(rb"(<(meta:initial-creator|dc:creator|meta:printed-by)[^>]*>)(.*?)(</\2>)", re.S)
# Tracked changes and annotations carry <dc:creator>Name</dc:creator> in content.xml.
_ODF_CREATOR = re.compile(rb"(<dc:creator[^>]*>)(.*?)(</dc:creator>)", re.S)


def _odf_part(name: str, data: bytes) -> bytes:
    if name == "meta.xml":
        return _ODF_META.sub(lambda m: m.group(1) + m.group(4), data)
    if name in ("content.xml", "styles.xml"):
        return _ODF_CREATOR.sub(lambda m: m.group(1) + ANONYMOUS.encode() + m.group(3), data)
    return data


def _rewrite_zip(data: bytes, rewrite: Callable[[str, bytes], bytes]) -> bytes | None:
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    with source:
        entries = source.infolist()
        if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
            return None
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for entry in entries:
                content = source.read(entry)
                if not entry.is_dir():
                    content = rewrite(entry.filename, content)
                # Keep each entry's name, order, date and compression (ODF needs "mimetype" first, stored).
                target.writestr(entry, content, compress_type=entry.compress_type)
        return output.getvalue()


# --------------------------------------------------------------------------- PDF


def _strip_pdf(data: bytes) -> bytes | None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, TextStringObject

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return None
    writer = PdfWriter(clone_from=reader)
    # The document information dictionary (Author, Creator...) and the XMP metadata stream.
    writer.metadata = None
    if "/Metadata" in writer.root_object:
        del writer.root_object["/Metadata"]
    # Comments and other annotations name their author in /T.
    for page in writer.pages:
        for reference in page.get("/Annots", []) or []:
            annotation = reference.get_object()
            if "/T" in annotation:
                annotation[NameObject("/T")] = TextStringObject(ANONYMOUS)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


# --------------------------------------------------------------------------- RTF

_RTF_INFO = b"{\\info"


def _skip_group(data: bytes, start: int) -> int:
    """Index just after the group that opens at ``start`` (``data[start] == '{'``)."""
    depth = 0
    index = start
    while index < len(data):
        char = data[index : index + 1]
        if char == b"\\":
            index += 2  # escaped character, e.g. \{ or \\
            continue
        if char == b"{":
            depth += 1
        elif char == b"}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(data)


def _strip_rtf(data: bytes) -> bytes | None:
    if not data.startswith(b"{\\rtf"):
        return None
    result = data
    for marker in (_RTF_INFO, b"{\\*\\revtbl", b"{\\revtbl"):
        while (start := result.find(marker)) != -1:
            result = result[:start] + result[_skip_group(result, start) :]
    return result


# --------------------------------------------------------------------------- entry point

_STRIPPERS: dict[str, Callable[[bytes], bytes | None]] = {
    ".docx": lambda data: _rewrite_zip(data, _ooxml_part),
    ".xlsx": lambda data: _rewrite_zip(data, _ooxml_part),
    ".odt": lambda data: _rewrite_zip(data, _odf_part),
    ".ods": lambda data: _rewrite_zip(data, _odf_part),
    ".pdf": _strip_pdf,
    ".rtf": _strip_rtf,
}


def can_strip(extension: str) -> bool:
    return extension in _STRIPPERS


def strip(data: bytes, extension: str) -> tuple[bytes, bool]:
    stripper = _STRIPPERS.get(extension)
    if stripper is None:
        return data, False
    try:
        result = stripper(data)
    except Exception:
        # A damaged or unusual file: hand it over unchanged and let the editor check it.
        logger.warning("Could not remove metadata", extra={"extension": extension}, exc_info=True)
        return data, False
    if result is None:
        return data, False
    return result, True
