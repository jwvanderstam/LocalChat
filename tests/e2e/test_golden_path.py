"""TQ-4 — the golden path, through a real browser.

Sign in, upload a document, ask about it, and get an answer that cites the file
just uploaded. This is the entire frontend test strategy, deliberately: the
vanilla-JS frontend is not worth a component-test investment at this scope, and
one proof that the path a user actually walks still works catches the
regressions that matter.

It is an end-to-end test in the strict sense — the only thing faked is the model
process (`tests/utils/fake_ollama.py`). Auth, templates, the SSE upload stream,
ingest, pgvector retrieval and the SSE chat stream are all real, and each has
broken this path at least once without a Python test noticing.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

try:
    from playwright.sync_api import Page, expect
except ImportError:
    if os.environ.get("CI"):
        # Never skip in CI. `pytest.importorskip` is how the suite this file
        # replaced stayed broken for months: the tests reported "skipped" and the
        # job reported green. `pytest-playwright` is in requirements.txt, so a
        # missing import here means CI is misconfigured, and that must be loud.
        raise
    pytest.skip(
        "playwright not installed — run: pip install -r requirements.txt && playwright install chromium",
        allow_module_level=True,
    )

from tests.e2e.conftest import ADMIN_PASSWORD, ADMIN_USERNAME  # noqa: E402

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.db]

#: The codename is what makes the retrieval assertion deterministic. Every run
#: uploads the same prose, so against a database holding an earlier run's copy the
#: top hit was whichever identical chunk pgvector happened to return — a real
#: failure seen while breaking this test on purpose. A word unique to this run
#: leaves the ranking no such choice.
DOCUMENT = """\
Vector search in LocalChat, build {codename}

LocalChat stores embeddings in PostgreSQL using the pgvector extension, and ranks
candidates by cosine similarity against an HNSW index. Build {codename} keeps that
behaviour unchanged.
"""

#: Shares none of the document's words. Without it the citation assertion would
#: also pass for a retriever that attaches every document to every answer.
UNRELATED_QUESTION = "What is marsupial husbandry in temperate climates?"


class Document(NamedTuple):
    path: Path
    codename: str


@pytest.fixture
def document(tmp_path: Path, page: Page) -> Iterator[Document]:
    """A uniquely named file, retired again afterwards.

    Unique because 0013 allows one live document per (filename, workspace);
    retired because a run that left its document behind would compete with the
    next run's for the top rank.
    """
    codename = uuid.uuid4().hex[:8]
    path = tmp_path / f"vector-search-{codename}.txt"
    path.write_text(DOCUMENT.format(codename=codename), encoding="utf-8")

    yield Document(path, codename)

    _retire(page, path.name)


def _retire(page: Page, filename: str) -> None:
    """Soft-delete the document, using the session the browser already holds."""
    listing = page.request.get("/api/documents/list")
    if not listing.ok:
        return  # the test failed before signing in; there is nothing to retire
    for doc in listing.json().get("documents", []):
        if doc.get("filename") == filename:
            page.request.delete(f"/api/documents/{doc['id']}")


def _sign_in(page: Page) -> None:
    page.goto("/login")
    page.locator("#username").fill(ADMIN_USERNAME)
    page.locator("#password").fill(ADMIN_PASSWORD)
    page.locator("#login-submit").click()
    expect(page).to_have_url(re.compile(r"/$"))


def _ask(page: Page, question: str) -> None:
    page.locator("#chat-input").fill(question)
    page.locator("#send-btn").click()


def test_visiting_the_app_without_a_session_lands_on_the_login_page(page: Page) -> None:
    """The guard on everything below: if the app let anyone in, signing in would
    prove nothing and the golden path would pass without authenticating."""
    page.goto("/")
    expect(page).to_have_url(re.compile(r"/login"), timeout=15_000)


def test_sign_in_upload_ask_and_the_answer_cites_the_document(page: Page,
                                                              document: Document) -> None:
    _sign_in(page)

    page.goto("/documents")
    page.locator("#file-input").set_input_files(str(document.path))
    page.locator("#upload-btn").click()

    upload_result = page.locator("#upload-results .alert-success")
    expect(upload_result).to_contain_text(document.path.name, timeout=90_000)
    expect(page.locator("#documents-list")).to_contain_text(document.path.name, timeout=30_000)

    page.goto("/")
    _ask(page, f"How does build {document.codename} rank candidates by cosine similarity?")

    answer = page.locator(".assistant-message").first
    sources = answer.locator(".sources-panel")
    expect(sources).to_be_visible(timeout=90_000)
    # Asserted on the sources panel rather than on the answer text: the stub echoes
    # the prompt it was given, and the prompt carries the retrieved context — so the
    # filename appears in the reply whether or not a citation was ever rendered.
    expect(sources).to_contain_text(document.path.name)

    # Both of these are here because the node harness cannot reach them: its DOM
    # is a stub whose createElement returns a proxy with a no-op appendChild, so
    # nothing that asserts on a *built* tree can run there.
    #
    # The empty state used to survive the first message — renderChatHistory()
    # painted it and returned, and nothing took it down again, so "Start a
    # conversation..." sat above the transcript for the rest of the session. It
    # escaped this test and the harness both, and was found by looking at a
    # screenshot, which is the argument for pinning it here.
    expect(page.locator("#chat-empty-state")).to_have_count(0)

    # Citations are numbered footnotes, not a collapsed "N sources" disclosure.
    expect(sources.locator(".sources-panel-marker").first).to_have_text("1")

    _ask(page, UNRELATED_QUESTION)
    unrelated_answer = page.locator(".assistant-message").nth(1)
    # `.message-time` is filled in on the stream's `done` event, and the sources
    # panel is appended in that same handler — so waiting for it is what stops the
    # assertion below from passing merely because the answer had not arrived yet.
    expect(unrelated_answer.locator(".message-time")).not_to_be_empty(timeout=90_000)
    assert unrelated_answer.locator(".sources-panel").count() == 0, (
        "a question the document says nothing about was answered with a citation to it"
    )
