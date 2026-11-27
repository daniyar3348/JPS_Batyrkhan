"""Starting texts for the site's pages: what indexes such as DOAJ and Scopus expect a journal to publish.

A new journal gets them as unpublished drafts to fill in; the demo data publishes them as they are.
"""

from __future__ import annotations

from app.modules.content.models import Page
from app.modules.content.service import ContentService
from app.modules.journals.models import Journal

STARTER_PAGES: list[tuple[str, str, str]] = [
    (
        "aims-and-scope",
        "Aims and scope",
        "The journal publishes original research, reviews and short communications in its field.\n\n"
        "## Topics\n\n- First topic\n- Second topic\n\n"
        "## Audience\n\nResearchers, practitioners and students.\n",
    ),
    (
        "author-guidelines",
        "Author guidelines",
        "## Before you submit\n\n"
        "- The manuscript has not been published and is not under consideration elsewhere.\n"
        "- All authors have agreed to the submission.\n\n"
        "## Preparing the manuscript\n\n"
        "Write in English. Structure research articles as Introduction, Methods, Results and Discussion. "
        "Include an abstract of up to 250 words and three to six keywords.\n\n"
        "## References\n\nUse APA style and give DOIs where they exist.\n",
    ),
    (
        "peer-review",
        "Peer review",
        "Every research article is reviewed by at least two independent experts in **double-blind** review: "
        "reviewers and authors do not know each other's names.\n\n"
        "The editors check each submission first and may decline it without review if it is outside the "
        "journal's scope. The usual time to a first decision is eight weeks.\n",
    ),
    (
        "publication-ethics",
        "Publication ethics",
        "The journal follows the guidance of the Committee on Publication Ethics (COPE).\n\n"
        "## Plagiarism\n\nSubmissions are checked for similarity with published work.\n\n"
        "## Conflicts of interest\n\nAuthors, reviewers and editors declare any conflict of interest.\n\n"
        "## Corrections and retractions\n\nCorrections are published as new versions of the article; "
        "earlier versions stay available.\n",
    ),
    (
        "open-access",
        "Open access and licensing",
        "All articles are free to read immediately on publication.\n\n"
        "Articles are published under the Creative Commons Attribution 4.0 licence (CC BY 4.0). "
        "Authors keep the copyright.\n\n"
        "The journal's metadata is open: it is registered with Crossref and available through OAI-PMH.\n",
    ),
]


async def add_starter_pages(service: ContentService, journal: Journal, *, published: bool) -> int:
    """Create the starter pages that do not exist yet; return how many were added."""
    existing = {page.slug for page in await service.pages(journal)}
    added = 0
    for position, (slug, title, body) in enumerate(STARTER_PAGES):
        if slug in existing:
            continue
        service.db.add(
            Page(
                journal_id=journal.id,
                slug=slug,
                title=title,
                body=body,
                position=position,
                in_menu=True,
                is_published=published,
            )
        )
        added += 1
    await service.db.flush()
    return added
