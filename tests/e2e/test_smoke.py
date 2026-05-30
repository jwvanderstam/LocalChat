"""
Playwright smoke tests. Require a running LocalChat server on BASE_URL.

Run:
    pip install pytest-playwright
    playwright install chromium
    python app.py &            # or docker compose up -d
    pytest tests/e2e/ -v

These tests are intentionally excluded from CI (no @pytest.mark.e2e jobs in
.github/workflows/tests.yml) because they need a live server and optionally
Ollama. Run locally before major releases.
"""

import pytest

playwright_mod = pytest.importorskip("playwright", reason="playwright not installed — run: pip install pytest-playwright && playwright install chromium")
from playwright.sync_api import Page, expect  # noqa: E402

BASE_URL = "http://localhost:5000"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": BASE_URL}


@pytest.mark.e2e
def test_page_loads(page: Page):
    page.goto("/")
    expect(page).to_have_title("LocalChat")
    expect(page.locator("#chat-messages")).to_be_visible()
    expect(page.locator("#chat-form")).to_be_visible()


@pytest.mark.e2e
def test_rag_toggle_updates_badge(page: Page):
    page.goto("/")
    rag_toggle = page.locator("#rag-toggle")
    badge = page.locator("#mode-badge")

    rag_toggle.uncheck()
    expect(badge).to_have_text("Direct LLM Mode")

    rag_toggle.check()
    expect(badge).to_have_text("RAG Mode: ON")


@pytest.mark.e2e
def test_new_chat_clears_to_empty_state(page: Page):
    page.goto("/")
    page.locator("#new-chat-btn").click()
    expect(page.locator("#chat-empty-state")).to_be_visible()


@pytest.mark.e2e
def test_send_message_shows_user_bubble(page: Page):
    """User bubble appears immediately; loading indicator appears before LLM responds."""
    page.goto("/")
    page.locator("#new-chat-btn").click()
    page.locator("#chat-input").fill("Hello, world!")
    page.locator("#chat-form button[type='submit']").click()

    # User bubble is rendered synchronously before any fetch completes
    expect(page.locator(".user-message").first).to_be_visible(timeout=3_000)
    # Loading indicator follows
    expect(page.locator(".loading-message").first).to_be_visible(timeout=3_000)


@pytest.mark.e2e
def test_document_page_loads(page: Page):
    page.goto("/documents")
    # Either the upload form or the upload button must be present
    assert (
        page.locator("#upload-form").count() > 0
        or page.locator("[data-bs-target='#uploadModal'], #upload-btn").count() > 0
    ), "No upload entry point found on /documents"
