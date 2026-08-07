"""Ollama tags: an untagged pull becomes `name:latest`, and nothing matched it.

Pulling `llama3.2` from the model page installed `llama3.2:latest`. Activating it
then answered `404 Model 'llama3.2' not found` — while that same name was what the
page displayed as the active model, so the active model appeared not to exist.

Two halves to the fix: the pull menu now sends explicit tags, and resolution accepts
either form so existing stored values keep working.
"""

from __future__ import annotations

import pytest

from src.routes_fastapi.model_routes import _resolve_model_name

INSTALLED = ["llama3.2:latest", "mistral:latest", "nomic-embed-text:latest", "phi3:3.8b"]


@pytest.mark.unit
class TestResolvesEitherForm:
    def test_exact_match_wins(self):
        assert _resolve_model_name("llama3.2:latest", INSTALLED) == "llama3.2:latest"

    def test_untagged_resolves_to_latest(self):
        """The reported bug: the pull menu sent this and it 404'd."""
        assert _resolve_model_name("llama3.2", INSTALLED) == "llama3.2:latest"

    def test_latest_resolves_to_untagged_when_that_is_what_is_installed(self):
        """The mirror case, so an older stored value still activates."""
        assert _resolve_model_name("legacy:latest", ["legacy"]) == "legacy"

    def test_returns_the_installed_name_not_the_requested_one(self):
        """The caller stores the result, so it must be the name Ollama uses."""
        assert _resolve_model_name("mistral", INSTALLED) == "mistral:latest"


@pytest.mark.unit
class TestStillRefusesWhatIsNotThere:
    def test_unknown_model_is_unresolved(self):
        assert _resolve_model_name("does-not-exist", INSTALLED) is None

    def test_untagged_does_not_match_a_different_tag(self):
        """`phi3` must not silently activate `phi3:3.8b` — only `:latest` is implied.

        Guessing a tag would let a request for one model quietly run another.
        """
        assert _resolve_model_name("phi3", INSTALLED) is None

    def test_an_explicit_tag_is_never_redirected(self):
        assert _resolve_model_name("llama3.2:1b", INSTALLED) is None

    def test_empty_list_resolves_nothing(self):
        assert _resolve_model_name("llama3.2", []) is None


@pytest.mark.unit
def test_pull_menu_offers_only_tagged_names():
    """The menu is what created the mismatch; an untagged entry recreates it."""
    import re
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "templates" / "models.html").read_text(
        encoding="utf-8"
    )
    values = re.findall(r'<option value="([^"]+)"', html)
    untagged = [v for v in values if v and v != "custom" and ":" not in v]
    assert not untagged, f"pull options without an explicit tag: {untagged}"
