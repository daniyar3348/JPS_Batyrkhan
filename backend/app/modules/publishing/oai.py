"""OAI-PMH 2.0 (https://www.openarchives.org/OAI/openarchivesprotocol.html) over the published articles.

Harvesters (BASE, OpenAIRE, Google Scholar's crawlers, national indexes) read Dublin Core records
(``oai_dc``). Sets: the journal, and each of its sections. Records are never deleted (``deletedRecord``
is "no"): a published article stays published.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import get_db, get_settings
from app.core.errors import ValidationFailed
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.journals.deps import get_current_journal
from app.modules.journals.models import Journal, Section
from app.modules.journals.publishing_settings import PublishingSettings, publishing_settings
from app.modules.publishing.crossref import full_text_url
from app.modules.publishing.models import PublishedArticle

oai_router = APIRouter(tags=["oai"])

OAI = "http://www.openarchives.org/OAI/2.0/"
OAI_DC = "http://www.openarchives.org/OAI/2.0/oai_dc/"
DC = "http://purl.org/dc/elements/1.1/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
PAGE_SIZE = 100
FORMATS = {"oai_dc": ("http://www.openarchives.org/OAI/2.0/oai_dc.xsd", OAI_DC)}
VERBS = {
    "Identify": (set(), set()),
    "ListMetadataFormats": (set(), {"identifier"}),
    "ListSets": (set(), {"resumptionToken"}),
    "GetRecord": ({"identifier", "metadataPrefix"}, set()),
    "ListIdentifiers": ({"metadataPrefix"}, {"from", "until", "set", "resumptionToken"}),
    "ListRecords": ({"metadataPrefix"}, {"from", "until", "set", "resumptionToken"}),
}
_SET_UNSAFE = re.compile(r"[^A-Za-z0-9\-_.!~*'()]")


class OaiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Repository:
    journal: Journal
    settings: PublishingSettings
    identifier: str  # the repository's part of record identifiers, e.g. journal.example.org
    base_url: str
    sets: dict[str, int | None]  # setSpec -> section id (None: the whole journal)
    set_names: dict[str, str]

    def record_id(self, article: PublishedArticle) -> str:
        return f"oai:{self.identifier}:article/{article.submission_id}"

    def set_specs(self, article: PublishedArticle) -> list[str]:
        return [
            spec for spec, section in self.sets.items() if section is None or section == article.section_id
        ]


def _el(parent: ET.Element, tag: str, text: str | None = None, ns: str = OAI, **attrs: str) -> ET.Element:
    # The protocol's own elements are written in the default namespace, declared on the root.
    element = ET.SubElement(parent, tag if ns == OAI else f"{{{ns}}}{tag}", attrs)
    if text is not None:
        element.text = text
    return element


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_date(value: str, *, end: bool) -> tuple[datetime, str]:
    """A from/until argument, at day or second granularity."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
            # "until" a day includes the whole day.
            return (datetime.combine(day.date(), time.max, UTC) if end else day), "day"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC), "second"
    except ValueError:
        pass
    raise OaiError("badArgument", f"“{value}” is not a date in YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ.")


def _arguments(pairs: dict[str, list[str]]) -> dict[str, str]:
    repeated = [name for name, values in pairs.items() if len(values) > 1]
    if repeated:
        raise OaiError("badArgument", f"Repeated argument: {', '.join(repeated)}.")
    return {name: values[0] for name, values in pairs.items()}


async def _repository(db: AsyncSession, journal: Journal, settings: Settings, base_url: str) -> Repository:
    publishing = publishing_settings(journal)
    host = urlparse(publishing.site_url or settings.workspace_url).hostname or journal.slug
    sections = (
        await db.scalars(select(Section).where(Section.journal_id == journal.id).order_by(Section.sort_order))
    ).all()
    journal_set = _SET_UNSAFE.sub("-", journal.slug)
    sets: dict[str, int | None] = {journal_set: None}
    names = {journal_set: journal.name}
    for section in sections:
        spec = f"{journal_set}:{_SET_UNSAFE.sub('-', section.abbreviation)}"
        sets[spec] = section.id
        names[spec] = section.title
    return Repository(journal, publishing, host, base_url, sets, names)


def _dublin_core(parent: ET.Element, repo: Repository, article: PublishedArticle) -> None:
    data: dict[str, Any] = article.data
    dc = ET.SubElement(
        parent,
        f"{{{OAI_DC}}}dc",
        {f"{{{XSI}}}schemaLocation": f"{OAI_DC} http://www.openarchives.org/OAI/2.0/oai_dc.xsd"},
    )

    def add(tag: str, value: str | None) -> None:
        if value:
            _el(dc, tag, value, ns=DC)

    journal = repo.journal
    add("title", f"{data['title']}: {data['subtitle']}" if data.get("subtitle") else data["title"])
    for author in data["authors"]:
        family, given = author["family_name"], author["given_name"]
        add("creator", f"{family}, {given}" if family else given)
    for keyword in data["keywords"]:
        add("subject", keyword)
    add("description", data["abstract"])
    add("publisher", journal.publisher or journal.name)
    add("date", data["dates"]["published"][:10])
    add("type", "info:eu-repo/semantics/article")
    add("type", "info:eu-repo/semantics/publishedVersion")
    add("type", "Peer-reviewed Article")
    for galley in data["galleys"]:
        add("format", galley["content_type"])
    add("identifier", data.get("url"))
    add("identifier", data.get("doi_url"))
    issue = data.get("issue")
    source = journal.name
    if issue:
        source = f"{source}; {issue['label']}"
    if data.get("pages"):
        source = f"{source}; {data['pages']}"
    add("source", source)
    for issn in (journal.issn_online, journal.issn_print):
        add("source", issn)
    add("language", "eng")
    if repo.settings.site_url:
        for galley in data["galleys"]:
            add("relation", full_text_url(repo.settings, data, galley))
    if data.get("copyright_holder"):
        add(
            "rights",
            f"Copyright (c) {data.get('copyright_year') or ''} {data['copyright_holder']}".replace("  ", " "),
        )
    add("rights", data.get("license_url"))


def _header(parent: ET.Element, repo: Repository, article: PublishedArticle) -> None:
    header = _el(parent, "header")
    _el(header, "identifier", repo.record_id(article))
    _el(header, "datestamp", _stamp(article.updated_at))
    for spec in repo.set_specs(article):
        _el(header, "setSpec", spec)


async def _find(db: AsyncSession, repo: Repository, identifier: str) -> PublishedArticle:
    prefix = f"oai:{repo.identifier}:article/"
    if identifier.startswith(prefix) and identifier[len(prefix) :].isdigit():
        article = await db.scalar(
            select(PublishedArticle).where(
                PublishedArticle.journal_id == repo.journal.id,
                PublishedArticle.submission_id == int(identifier[len(prefix) :]),
            )
        )
        if article is not None:
            return article
    raise OaiError("idDoesNotExist", f"No record has the identifier “{identifier}”.")


async def _list(
    db: AsyncSession, repo: Repository, root: ET.Element, verb: str, args: dict[str, str]
) -> None:
    token = args.get("resumptionToken")
    if token is not None:
        if set(args) - {"verb"} != {"resumptionToken"}:
            raise OaiError("badArgument", "resumptionToken cannot be combined with other arguments.")
        try:
            prefix, start, end, set_spec, after_stamp, after_id, done = decode_cursor(token, size=7)
        except ValidationFailed as error:
            raise OaiError("badResumptionToken", "The resumption token is invalid or has expired.") from error
        args = {"metadataPrefix": prefix}
        if start:
            args["from"] = start
        if end:
            args["until"] = end
        if set_spec:
            args["set"] = set_spec
    else:
        after_stamp, after_id, done = None, None, 0
    prefix = args["metadataPrefix"]
    if prefix not in FORMATS:
        raise OaiError("cannotDisseminateFormat", f"The format “{prefix}” is not available; use oai_dc.")
    conditions = [PublishedArticle.journal_id == repo.journal.id]
    granularity = None
    if "from" in args:
        start_at, granularity = _parse_date(args["from"], end=False)
        conditions.append(PublishedArticle.updated_at >= start_at)
    if "until" in args:
        end_at, until_granularity = _parse_date(args["until"], end=True)
        if granularity and until_granularity != granularity:
            raise OaiError("badArgument", "from and until must have the same granularity.")
        if "from" in args and end_at < start_at:
            raise OaiError("badArgument", "from is later than until.")
        conditions.append(PublishedArticle.updated_at <= end_at)
    if "set" in args:
        if args["set"] not in repo.sets:
            raise OaiError("badArgument", f"There is no set “{args['set']}”.")
        section_id = repo.sets[args["set"]]
        if section_id is not None:
            conditions.append(PublishedArticle.section_id == section_id)
    total = await db.scalar(select(func.count()).select_from(PublishedArticle).where(and_(*conditions))) or 0
    page = select(PublishedArticle).where(*conditions)
    if after_stamp is not None:
        stamp = datetime.fromisoformat(str(after_stamp))
        page = page.where(
            or_(
                PublishedArticle.updated_at > stamp,
                and_(PublishedArticle.updated_at == stamp, PublishedArticle.id > int(str(after_id))),
            )
        )
    rows = (
        await db.scalars(page.order_by(PublishedArticle.updated_at, PublishedArticle.id).limit(PAGE_SIZE + 1))
    ).all()
    if not rows:
        raise OaiError("noRecordsMatch", "No records match the request.")
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    container = _el(root, verb)
    for article in rows:
        if verb == "ListIdentifiers":
            _header(container, repo, article)
        else:
            record = _el(container, "record")
            _header(record, repo, article)
            _dublin_core(_el(record, "metadata"), repo, article)
    if more or token is not None:
        last = rows[-1]
        next_token = (
            encode_cursor(
                [
                    prefix,
                    args.get("from", ""),
                    args.get("until", ""),
                    args.get("set", ""),
                    last.updated_at.isoformat(),
                    last.id,
                    int(done) + len(rows),
                ]
            )
            if more
            else ""
        )
        _el(
            container,
            "resumptionToken",
            next_token,
            completeListSize=str(total),
            cursor=str(int(done)),
        )


async def _respond(
    db: AsyncSession, repo: Repository, args: dict[str, str], *, error: OaiError | None = None
) -> ET.Element:
    root = ET.Element(
        "OAI-PMH",
        {"xmlns": OAI, f"{{{XSI}}}schemaLocation": f"{OAI} http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd"},
    )
    _el(root, "responseDate", _stamp(utcnow()))
    request = _el(root, "request", repo.base_url)
    try:
        if error is not None:
            raise error
        verb = args.get("verb")
        if verb not in VERBS:
            raise OaiError("badVerb", "The verb is missing or not one of the six OAI-PMH verbs.")
        required, optional = VERBS[verb]
        given = set(args) - {"verb"}
        exclusive = "resumptionToken" in given
        missing = set() if exclusive else required - given
        unknown = given - required - optional
        if missing or unknown:
            raise OaiError(
                "badArgument",
                f"Missing: {', '.join(sorted(missing)) or '-'}; not allowed: "
                f"{', '.join(sorted(unknown)) or '-'}.",
            )
        for name, value in args.items():
            request.set(name, value)
        if verb == "Identify":
            await _identify(db, repo, root)
        elif verb == "ListMetadataFormats":
            if "identifier" in args:
                await _find(db, repo, args["identifier"])
            formats = _el(root, "ListMetadataFormats")
            for name, (schema, namespace) in FORMATS.items():
                item = _el(formats, "metadataFormat")
                _el(item, "metadataPrefix", name)
                _el(item, "schema", schema)
                _el(item, "metadataNamespace", namespace)
        elif verb == "ListSets":
            if "resumptionToken" in args:
                raise OaiError("badResumptionToken", "The list of sets is complete in one response.")
            sets = _el(root, "ListSets")
            for spec, name in repo.set_names.items():
                item = _el(sets, "set")
                _el(item, "setSpec", spec)
                _el(item, "setName", name)
        elif verb == "GetRecord":
            if args["metadataPrefix"] not in FORMATS:
                raise OaiError("cannotDisseminateFormat", "Only oai_dc is available.")
            article = await _find(db, repo, args["identifier"])
            record = _el(_el(root, "GetRecord"), "record")
            _header(record, repo, article)
            _dublin_core(_el(record, "metadata"), repo, article)
        else:
            await _list(db, repo, root, verb, args)
    except OaiError as problem:
        if problem.code in ("badVerb", "badArgument"):
            request.attrib.clear()  # the protocol: no attributes when the request itself is wrong
        for child in list(root)[2:]:
            root.remove(child)
        _el(root, "error", problem.message, code=problem.code)
    return root


async def _identify(db: AsyncSession, repo: Repository, root: ET.Element) -> None:
    journal = repo.journal
    earliest = await db.scalar(
        select(func.min(PublishedArticle.updated_at)).where(PublishedArticle.journal_id == journal.id)
    )
    identify = _el(root, "Identify")
    _el(identify, "repositoryName", journal.name)
    _el(identify, "baseURL", repo.base_url)
    _el(identify, "protocolVersion", "2.0")
    _el(identify, "adminEmail", journal.contact_email or "admin@" + repo.identifier)
    _el(identify, "earliestDatestamp", _stamp(earliest or datetime(2000, 1, 1, tzinfo=UTC)))
    _el(identify, "deletedRecord", "no")
    _el(identify, "granularity", "YYYY-MM-DDThh:mm:ssZ")
    description = _el(identify, "description")
    ns = "http://www.openarchives.org/OAI/2.0/oai-identifier"
    identifier = ET.SubElement(
        description,
        f"{{{ns}}}oai-identifier",
        {f"{{{XSI}}}schemaLocation": f"{ns} http://www.openarchives.org/OAI/2.0/oai-identifier.xsd"},
    )
    _el(identifier, "scheme", "oai", ns=ns)
    _el(identifier, "repositoryIdentifier", repo.identifier, ns=ns)
    _el(identifier, "delimiter", ":", ns=ns)
    _el(identifier, "sampleIdentifier", f"oai:{repo.identifier}:article/1", ns=ns)


ET.register_namespace("oai_dc", OAI_DC)
ET.register_namespace("dc", DC)
ET.register_namespace("xsi", XSI)
ET.register_namespace("oai-identifier", "http://www.openarchives.org/OAI/2.0/oai-identifier")


async def _handle(
    request: Request, pairs: dict[str, list[str]], db: AsyncSession, journal: Journal, settings: Settings
) -> Response:
    base_url = str(request.url.replace(query=""))
    repo = await _repository(db, journal, settings, base_url)
    try:
        root = await _respond(db, repo, _arguments(pairs))
    except OaiError as error:  # repeated arguments
        root = await _respond(db, repo, {}, error=error)
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(
        content=body,
        media_type="text/xml; charset=utf-8",
        headers={"Cache-Control": f"public, max-age={settings.public_cache_seconds}"},
    )


@oai_router.get("/oai", response_class=Response)
async def oai_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    journal: Journal = Depends(get_current_journal),
    settings: Settings = Depends(get_settings),
) -> Response:
    """OAI-PMH 2.0 repository: Dublin Core records of the published articles."""
    return await _handle(request, parse_qs(request.url.query, keep_blank_values=True), db, journal, settings)


@oai_router.post("/oai", response_class=Response)
async def oai_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
    journal: Journal = Depends(get_current_journal),
    settings: Settings = Depends(get_settings),
) -> Response:
    """The same, with the arguments in an application/x-www-form-urlencoded body."""
    body = (await request.body()).decode("utf-8", errors="replace")
    return await _handle(request, parse_qs(body, keep_blank_values=True), db, journal, settings)
