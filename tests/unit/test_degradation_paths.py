"""P2-4b — the exception paths that change behaviour, driven rather than assumed.

Two groups, and they are testing different things:

* The four handlers P2-4b **narrowed** from `except Exception`. A narrow is a
  behaviour change: the named errors are still absorbed, and anything else now
  escapes. Both halves are asserted, because only the second one is new.
* The handlers that were failing **silently** and gained a log. The assertion is
  on what the caller gets when the optional part fails — never on the log call,
  which would restate the code. One of these (the settings page) is the case
  that would have caught a real bug in this PR: the `stats = {}` assignment was
  destroyed by the script that added the logging, and no test noticed.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

import pytest

pytestmark = pytest.mark.unit


class TestTimestampParsingIsNarrowedNotBlind:
    """`_item_to_source` absorbs an unparseable timestamp and nothing else."""

    @staticmethod
    def _onedrive():
        from src.connectors.onedrive_connector import OneDriveConnector
        return OneDriveConnector.__new__(OneDriveConnector)

    @staticmethod
    def _google():
        from src.connectors.google_drive_connector import GoogleDriveConnector
        return GoogleDriveConnector.__new__(GoogleDriveConnector)

    def test_a_malformed_timestamp_leaves_last_modified_unset(self):
        source = self._onedrive()._item_to_source(
            {"id": "item-1", "name": "q3.docx", "lastModifiedDateTime": "not-a-date"}
        )
        assert source.last_modified is None
        assert source.filename == "q3.docx"

    def test_a_well_formed_timestamp_is_still_parsed(self):
        """The negative space: without this, a handler that swallowed everything
        would pass the test above just as well."""
        source = self._onedrive()._item_to_source(
            {"id": "item-1", "name": "q3.docx", "lastModifiedDateTime": "2026-09-21T10:30:00Z"}
        )
        assert source.last_modified == datetime(2026, 9, 21, 10, 30, tzinfo=UTC)

    def test_google_drive_reads_its_own_field_name(self):
        source = self._google()._item_to_source(
            {"id": "g-1", "name": "notes.txt", "modifiedTime": "2026-09-21T10:30:00Z"}
        )
        assert source.last_modified == datetime(2026, 9, 21, 10, 30, tzinfo=UTC)

    def test_an_unexpected_error_now_escapes(self):
        """The point of the narrow, and the only assertion here that distinguishes
        it from the blind handler it replaced. The error has to be raised from
        *inside* the try block to mean anything — a `KeyError` from `item['id']`
        below it would propagate either way and prove nothing."""

        class _HostileTimestamp:
            def replace(self, *_args):
                raise RuntimeError("not a parsing failure")

        with pytest.raises(RuntimeError, match="not a parsing failure"):
            self._onedrive()._item_to_source(
                {"id": "item-1", "lastModifiedDateTime": _HostileTimestamp()}
            )


class TestExpiredTokenFailsSafe:
    def test_an_unparseable_expiry_counts_as_expired(self):
        from src.db.oauth_tokens import OAuthTokensMixin

        mixin = OAuthTokensMixin.__new__(OAuthTokensMixin)
        mixin.get_oauth_token = Mock(return_value={"expires_at": "whenever"})

        assert mixin.is_token_expired("user-1", "microsoft") is True

    def test_a_future_expiry_is_not_expired(self):
        from src.db.oauth_tokens import OAuthTokensMixin

        mixin = OAuthTokensMixin.__new__(OAuthTokensMixin)
        mixin.get_oauth_token = Mock(return_value={"expires_at": "2099-01-01T00:00:00+00:00"})

        assert mixin.is_token_expired("user-1", "microsoft") is False


class TestAPageStillRendersWhenItsStatsDoNot:
    """The regression guard for the bug this PR introduced and then fixed."""

    def test_settings_falls_back_to_empty_stats(self, monkeypatch):
        from src.routes_fastapi import settings_routes, web_routes

        def _boom(_state):
            raise RuntimeError("stats backend down")

        monkeypatch.setattr(settings_routes, "gather_admin_stats", _boom)

        captured = {}

        class _Templates:
            def TemplateResponse(self, *args, **kwargs):
                captured.update(kwargs.get("context") or (args[2] if len(args) > 2 else {}))
                return "rendered"

        monkeypatch.setattr(web_routes, "_templates", lambda _request: _Templates())

        request = MagicMock()
        request.app.state.docs_service.get_fragment.return_value = None

        assert web_routes.settings(request) == "rendered"
        assert captured.get("stats") == {}


class TestVisionSuggestionFallsBackWhenVramCannotBeRead:
    def test_a_failing_probe_yields_the_cpu_safe_model(self):
        from src.ollama_client import OllamaClient

        client = OllamaClient.__new__(OllamaClient)
        client.get_gpu_info = Mock(side_effect=RuntimeError("nvidia-smi exploded"))

        model, rationale = client.suggest_vision_model()

        assert model == "moondream:1.8b"
        assert "CPU" in rationale
