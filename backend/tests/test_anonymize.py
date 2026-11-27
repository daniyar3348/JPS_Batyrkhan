"""Names hidden in documents' metadata are removed before the other side of a blind review sees them."""

from __future__ import annotations

import io
import zipfile

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from app.modules.files.anonymize import strip

NAME = b"Jane Doe"


def make_zip(parts: dict[str, bytes], *, first: tuple[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if first is not None:
            archive.writestr(zipfile.ZipInfo(first[0]), first[1], compress_type=zipfile.ZIP_STORED)
        for name, content in parts.items():
            archive.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def unpacked(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_docx_metadata_tracked_changes_and_comments() -> None:
    docx = make_zip(
        {
            "[Content_Types].xml": b"<Types/>",
            "docProps/core.xml": (
                b"<cp:coreProperties><dc:title>Soil carbon</dc:title><dc:creator>Jane Doe</dc:creator>"
                b"<cp:lastModifiedBy>Jane Doe</cp:lastModifiedBy></cp:coreProperties>"
            ),
            "docProps/app.xml": b"<Properties><Company>Jane Doe Lab</Company></Properties>",
            "word/document.xml": (
                b'<w:document><w:body><w:ins w:id="1" w:author="Jane Doe" w:date="2026-01-01">'
                b"<w:r><w:t>Soil carbon text</w:t></w:r></w:ins></w:body></w:document>"
            ),
            "word/comments.xml": b'<w:comments><w:comment w:author="Jane Doe" w:initials="JD"/></w:comments>',
            "word/people.xml": b'<w15:people><w15:person w15:author="Jane Doe"/></w15:people>',
        }
    )
    result, removed = strip(docx, ".docx")
    assert removed
    parts = unpacked(result)
    assert all(NAME not in content for content in parts.values())
    assert b"Soil carbon text" in parts["word/document.xml"]  # the text itself is untouched
    assert b"<dc:title>Soil carbon</dc:title>" in parts["docProps/core.xml"]
    assert b'w:author="Anonymous"' in parts["word/comments.xml"]


def test_odt_keeps_mimetype_first_and_removes_creators() -> None:
    odt = make_zip(
        {
            "meta.xml": b"<office:meta><meta:initial-creator>Jane Doe</meta:initial-creator>"
            b"<dc:creator>Jane Doe</dc:creator></office:meta>",
            "content.xml": b"<office:text><text:changed-region><office:change-info>"
            b"<dc:creator>Jane Doe</dc:creator></office:change-info></text:changed-region></office:text>",
        },
        first=("mimetype", b"application/vnd.oasis.opendocument.text"),
    )
    result, removed = strip(odt, ".odt")
    assert removed
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        first = archive.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert all(NAME not in content for content in unpacked(result).values())


def test_pdf_information_xmp_and_comment_authors() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    writer.add_metadata({"/Author": "Jane Doe", "/Title": "Soil carbon"})
    note = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Text"),
            NameObject("/T"): TextStringObject("Jane Doe"),
            NameObject("/Contents"): TextStringObject("Check this figure"),
        }
    )
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(note)])
    buffer = io.BytesIO()
    writer.write(buffer)
    assert NAME in buffer.getvalue()

    result, removed = strip(buffer.getvalue(), ".pdf")
    assert removed
    assert NAME not in result
    reader = PdfReader(io.BytesIO(result))
    assert reader.metadata is None
    annotations = reader.pages[0]["/Annots"]
    assert isinstance(annotations, ArrayObject) and len(annotations) == 1
    note_after = annotations[0].get_object()
    assert note_after["/Contents"] == "Check this figure" and note_after["/T"] == "Anonymous"


def test_rtf_info_and_revision_authors() -> None:
    rtf = (
        rb"{\rtf1\ansi{\info{\author Jane Doe}{\operator Jane Doe}}"
        rb"{\*\revtbl {Unknown;}{Jane Doe;}}Soil carbon \{text\}}"
    )
    result, removed = strip(rtf, ".rtf")
    assert removed
    assert NAME not in result
    assert result.endswith(rb"Soil carbon \{text\}}")


def test_unknown_or_damaged_files_are_returned_unchanged() -> None:
    assert strip(b"\\documentclass{article}", ".tex") == (b"\\documentclass{article}", False)
    assert strip(b"not a zip", ".docx") == (b"not a zip", False)
    assert strip(b"%PDF-1.7 broken", ".pdf") == (b"%PDF-1.7 broken", False)
