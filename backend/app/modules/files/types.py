"""Accepted file types and checks of file contents (by signature, not by the name the browser sent)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Genre(StrEnum):
    """What a file is, from the author's point of view."""

    MANUSCRIPT = "manuscript"
    TITLE_PAGE = "title_page"
    FIGURE = "figure"
    TABLE = "table"
    SUPPLEMENTARY = "supplementary"
    COVER_LETTER = "cover_letter"


@dataclass(frozen=True)
class FileType:
    content_type: str
    kind: str  # how the contents are checked: one of the keys of _CHECKS


FILE_TYPES: dict[str, FileType] = {
    ".pdf": FileType("application/pdf", "pdf"),
    ".docx": FileType("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "zip"),
    ".doc": FileType("application/msword", "ole"),
    ".odt": FileType("application/vnd.oasis.opendocument.text", "zip"),
    ".rtf": FileType("application/rtf", "rtf"),
    ".tex": FileType("application/x-tex", "text"),
    ".bib": FileType("application/x-bibtex", "text"),
    ".txt": FileType("text/plain", "text"),
    ".csv": FileType("text/csv", "text"),
    ".xlsx": FileType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "zip"),
    ".xls": FileType("application/vnd.ms-excel", "ole"),
    ".ods": FileType("application/vnd.oasis.opendocument.spreadsheet", "zip"),
    ".zip": FileType("application/zip", "zip"),
    ".png": FileType("image/png", "png"),
    ".jpg": FileType("image/jpeg", "jpeg"),
    ".jpeg": FileType("image/jpeg", "jpeg"),
    ".tif": FileType("image/tiff", "tiff"),
    ".tiff": FileType("image/tiff", "tiff"),
    ".gif": FileType("image/gif", "gif"),
    ".eps": FileType("application/postscript", "eps"),
}

_DOCUMENTS = (".pdf", ".docx", ".doc", ".odt", ".rtf")
_IMAGES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".eps")

ALLOWED_EXTENSIONS: dict[Genre, tuple[str, ...]] = {
    # .tex and .zip allow LaTeX submissions (a single file or the sources in an archive).
    Genre.MANUSCRIPT: (*_DOCUMENTS, ".tex", ".zip"),
    Genre.TITLE_PAGE: _DOCUMENTS,
    Genre.FIGURE: (*_IMAGES, ".pdf"),
    Genre.TABLE: (".docx", ".doc", ".odt", ".xlsx", ".xls", ".ods", ".csv", ".pdf"),
    Genre.SUPPLEMENTARY: tuple(FILE_TYPES),
    Genre.COVER_LETTER: (*_DOCUMENTS, ".txt"),
}

_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "zip": (b"PK\x03\x04",),
    "ole": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "rtf": (b"{\\rtf",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "tiff": (b"II*\x00", b"MM\x00*"),
    "gif": (b"GIF87a", b"GIF89a"),
    "eps": (b"%!PS", b"\xc5\xd0\xd3\xc6"),
}
_EXECUTABLES = (b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"#!")


def extension_of(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot > 0 else ""


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character may be cut at the end of the sample.
        return exc.start >= len(head) - 3
    return True


def content_problem(head: bytes, extension: str) -> str | None:
    """Why the contents do not match the extension, or None if they do."""
    if head.startswith(_EXECUTABLES):
        return "Programs and scripts cannot be uploaded."
    file_type = FILE_TYPES.get(extension)
    if file_type is None:
        return "This type of file is not accepted."
    if file_type.kind == "text":
        return None if _looks_like_text(head) else f"The file is not a plain-text {extension} file."
    if not head.startswith(_SIGNATURES[file_type.kind]):
        return f"The contents do not match the {extension} extension. Save the file again in this format."
    return None
