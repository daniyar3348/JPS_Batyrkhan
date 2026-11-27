"""Registering DOIs with Crossref: the deposit XML (schema 5.3.1) and the HTTPS deposit interface.

Deposits are queued by Crossref and processed later, so registering is two steps:
1. POST the XML to ``/servlet/deposit`` (operation ``doMDUpload``); Crossref answers that it received it;
2. later, GET ``/servlet/submissionDownload?type=result`` for the batch: a ``doi_batch_diagnostic``
   document says whether each DOI was registered.

The XML is built from the published-article snapshot, so it describes exactly what readers see.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Literal

import httpx
from defusedxml import ElementTree as SafeET

from app.core.config import Settings
from app.modules.journals.models import Journal
from app.modules.journals.publishing_settings import PublishingSettings

SCHEMA_VERSION = "5.3.1"
NS = f"http://www.crossref.org/schema/{SCHEMA_VERSION}"
JATS = "http://www.ncbi.nlm.nih.gov/JATS1"
AI = "http://www.crossref.org/AccessIndicators.xsd"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = f"{NS} https://www.crossref.org/schemas/crossref{SCHEMA_VERSION}.xsd"

ET.register_namespace("jats", JATS)
ET.register_namespace("ai", AI)
ET.register_namespace("xsi", XSI)


class NotReady(Exception):
    """The deposit cannot be built: the message says what is missing."""


def deposit_problems(journal: Journal, settings: PublishingSettings) -> list[str]:
    """What must be set up before any DOI can be registered."""
    problems = []
    if not settings.doi.ready:
        problems.append("DOIs are not enabled, or the DOI prefix is missing.")
    if not settings.site_url:
        problems.append("The address of the journal's site is not set: Crossref links each DOI to it.")
    if not (journal.issn_online or journal.issn_print):
        problems.append("The journal has no ISSN: Crossref needs one for journal articles.")
    if not (settings.doi.depositor_name and settings.doi.depositor_email):
        problems.append("The depositor's name and e-mail (who Crossref writes to) are not set.")
    return problems


def _add(parent: ET.Element, tag: str, text: str | None = None, ns: str = NS, **attrs: str) -> ET.Element:
    # Crossref's own elements are written in the default namespace, declared on the root.
    element = ET.SubElement(parent, tag if ns == NS else f"{{{ns}}}{tag}", attrs)
    if text is not None:
        element.text = text
    return element


def _date(parent: ET.Element, tag: str, value: datetime) -> None:
    element = _add(parent, tag, media_type="online")
    # The schema's order is month, day, year.
    _add(element, "month", f"{value.month:02d}")
    _add(element, "day", f"{value.day:02d}")
    _add(element, "year", str(value.year))


def _pages(parent: ET.Element, pages: str) -> None:
    parts = re.split("\\s*[-\u2013]\\s*", pages.strip(), maxsplit=1)
    first, last = parts[0], parts[1] if len(parts) > 1 else ""
    if not first:
        return
    element = _add(parent, "pages")
    _add(element, "first_page", first[:32])
    if last:
        _add(element, "last_page", last[:32])


def _orcid(value: str) -> str:
    return value if value.startswith("http") else f"https://orcid.org/{value}"


def build_deposit(
    *,
    journal: Journal,
    settings: PublishingSettings,
    article: dict[str, Any],
    batch_id: str,
    timestamp: int,
) -> bytes:
    """The deposit for one article. ``timestamp`` must grow with every deposit of the same DOI."""
    problems = deposit_problems(journal, settings)
    if not article.get("doi"):
        problems.append("The article has no DOI.")
    if problems:
        raise NotReady(" ".join(problems))

    root = ET.Element(
        "doi_batch",
        {"xmlns": NS, "version": SCHEMA_VERSION, f"{{{XSI}}}schemaLocation": SCHEMA_LOCATION},
    )
    head = _add(root, "head")
    _add(head, "doi_batch_id", batch_id)
    _add(head, "timestamp", str(timestamp))
    depositor = _add(head, "depositor")
    _add(depositor, "depositor_name", settings.doi.depositor_name)
    _add(depositor, "email_address", settings.doi.depositor_email)
    _add(head, "registrant", journal.publisher or journal.name)

    body = _add(root, "body")
    journal_el = _add(body, "journal")
    metadata = _add(journal_el, "journal_metadata", language="en")
    _add(metadata, "full_title", journal.name)
    if journal.abbreviation:
        _add(metadata, "abbrev_title", journal.abbreviation)
    if journal.issn_online:
        _add(metadata, "issn", journal.issn_online, media_type="electronic")
    if journal.issn_print:
        _add(metadata, "issn", journal.issn_print, media_type="print")

    published = datetime.fromisoformat(article["dates"]["published"])
    issue = article.get("issue")
    if issue:
        issue_el = _add(journal_el, "journal_issue")
        _date(
            issue_el,
            "publication_date",
            datetime.fromisoformat(issue["published_at"] or article["dates"]["published"]),
        )
        if issue.get("volume") is not None:
            _add(_add(issue_el, "journal_volume"), "volume", str(issue["volume"]))
        if issue.get("number"):
            _add(issue_el, "issue", issue["number"])

    item = _add(journal_el, "journal_article", publication_type="full_text", language="en")
    titles = _add(item, "titles")
    _add(titles, "title", article["title"])
    if article.get("subtitle"):
        _add(titles, "subtitle", article["subtitle"])

    authors = article["authors"]
    if authors:
        contributors = _add(item, "contributors")
        for index, author in enumerate(authors):
            person = _add(
                contributors,
                "person_name",
                sequence="first" if index == 0 else "additional",
                contributor_role="author",
            )
            # The surname is required; people with a single name have it recorded as the given name.
            if author["family_name"]:
                _add(person, "given_name", author["given_name"])
                _add(person, "surname", author["family_name"])
            else:
                _add(person, "surname", author["given_name"])
            if author.get("affiliation"):
                institution = _add(_add(person, "affiliations"), "institution")
                _add(institution, "institution_name", author["affiliation"])
            if author.get("orcid"):
                _add(person, "ORCID", _orcid(author["orcid"]), authenticated="false")

    if article.get("abstract"):
        abstract = _add(item, "abstract", ns=JATS)
        for paragraph in re.split(r"\n\s*\n", article["abstract"].strip()):
            _add(abstract, "p", paragraph.strip(), ns=JATS)

    _date(item, "publication_date", published)
    if article.get("pages"):
        _pages(item, article["pages"])

    if article.get("license_url"):
        program = _add(item, "program", ns=AI, name="AccessIndicators")
        _add(program, "free_to_read", ns=AI)
        _add(program, "license_ref", article["license_url"], ns=AI, applies_to="vor")

    doi_data = _add(item, "doi_data")
    _add(doi_data, "doi", article["doi"])
    _add(doi_data, "resource", settings.article_url(article["slug"]))
    galleys = [g for g in article.get("galleys", []) if g.get("content_type")]
    if galleys:
        # Full-text links: for text and data mining, and for Similarity Check's crawler.
        mining = _add(doi_data, "collection", property="text-mining")
        for galley in galleys:
            _add(
                _add(mining, "item"),
                "resource",
                full_text_url(settings, article, galley),
                mime_type=galley["content_type"],
            )
        pdf = next((g for g in galleys if g["content_type"] == "application/pdf"), None)
        if pdf is not None:
            crawler = _add(doi_data, "collection", property="crawler-based")
            _add(
                _add(crawler, "item", crawler="iParadigms"), "resource", full_text_url(settings, article, pdf)
            )

    references = article.get("references") or []
    if references:
        citations = _add(item, "citation_list")
        for index, reference in enumerate(references, start=1):
            citation = _add(citations, "citation", key=f"ref{index}")
            _add(citation, "unstructured_citation", reference)

    return bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def full_text_url(settings: PublishingSettings, article: dict[str, Any], galley: dict[str, Any]) -> str:
    """Readers download galleys from the journal's site, which passes the request to the public API."""
    return f"{settings.article_url(article['slug'])}/download/{galley['id']}"


# ---------------------------------------------------------------------- the deposit interface


class CrossrefError(Exception):
    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent  # wrong account or refused deposit: trying again will not help


@dataclass(frozen=True)
class Result:
    state: Literal["pending", "registered", "failed"]
    message: str
    raw: str


def _text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()[:500]


class CrossrefClient:
    URLS: ClassVar[dict[str, str]] = {
        "test": "https://test.crossref.org",
        "production": "https://doi.crossref.org",
    }
    # Tests replace the network with httpx.MockTransport.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    def __init__(self, settings: Settings) -> None:
        if settings.crossref_mode not in self.URLS:
            raise ValueError("Crossref is not configured for real deposits")
        if not settings.crossref_username or settings.crossref_password is None:
            raise CrossrefError(
                "The Crossref account is not configured on the server (JPS_CROSSREF_USERNAME and "
                "JPS_CROSSREF_PASSWORD).",
                permanent=True,
            )
        self.base_url = self.URLS[settings.crossref_mode]
        self.username = settings.crossref_username
        self.password = settings.crossref_password.get_secret_value()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=60.0, transport=self.transport)

    async def deposit(self, xml: bytes, *, file_name: str) -> str:
        async with self._client() as client:
            try:
                response = await client.post(
                    "/servlet/deposit",
                    data={
                        "operation": "doMDUpload",
                        "login_id": self.username,
                        "login_passwd": self.password,
                    },
                    files={"fname": (file_name, xml, "application/xml")},
                )
            except httpx.HTTPError as error:
                raise CrossrefError(f"Crossref could not be reached: {error}", permanent=False) from error
        text = response.text
        if response.status_code in (401, 403):
            raise CrossrefError("Crossref did not accept the account's login or password.", permanent=True)
        if response.status_code >= 500 or response.status_code == 429:
            raise CrossrefError(f"Crossref is unavailable (HTTP {response.status_code}).", permanent=False)
        if response.status_code != 200 or "SUCCESS" not in text.upper():
            raise CrossrefError(f"Crossref refused the deposit: {_text_of(text)}", permanent=True)
        return text

    async def result(self, batch_id: str) -> Result:
        async with self._client() as client:
            try:
                response = await client.get(
                    "/servlet/submissionDownload",
                    params={
                        "usr": self.username,
                        "pwd": self.password,
                        "doi_batch_id": batch_id,
                        "type": "result",
                    },
                )
            except httpx.HTTPError as error:
                raise CrossrefError(f"Crossref could not be reached: {error}", permanent=False) from error
        if response.status_code in (401, 403):
            raise CrossrefError("Crossref did not accept the account's login or password.", permanent=True)
        if response.status_code != 200:
            raise CrossrefError(f"Crossref is unavailable (HTTP {response.status_code}).", permanent=False)
        return parse_result(response.text)


def parse_result(document: str) -> Result:
    """Read a ``doi_batch_diagnostic``: the batch's state, and each record's outcome."""
    try:
        root = SafeET.fromstring(document.encode())
    except SafeET.ParseError:
        return Result("pending", "Crossref has not reported on the deposit yet.", document[:2000])

    # The diagnostic may or may not carry a namespace; compare local names.
    def local(element: Any) -> str:
        return str(element.tag).rsplit("}", 1)[-1]

    if local(root) != "doi_batch_diagnostic":
        return Result("pending", "Crossref has not reported on the deposit yet.", document[:2000])
    batch_status = root.get("status", "")
    if batch_status != "completed":
        return Result(
            "pending", f"Crossref is processing the deposit ({batch_status or 'queued'}).", document
        )
    records = [child for child in root if local(child) == "record_diagnostic"]
    if not records:
        return Result("failed", "Crossref processed the deposit but reported no records.", document)
    messages = []
    failed = False
    for record in records:
        status = record.get("status", "")
        message = next((child.text or "" for child in record if local(child) == "msg"), "").strip()
        if status == "Failure":
            failed = True
        if message:
            messages.append(f"{status}: {message}" if status else message)
    return Result("failed" if failed else "registered", "; ".join(messages)[:2000], document)
