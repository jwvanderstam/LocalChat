"""
Unit tests for GoogleDriveConnector (src/connectors/google_drive_connector.py).

Drive API v3 calls go through ``requests.get``, mocked at the module
boundary. ``_access_token`` is stubbed directly to avoid needing real
OAuth token storage.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.connectors.base import DocumentSource, EventType
from src.connectors.google_drive_connector import GoogleDriveConnector


def _make(**overrides) -> GoogleDriveConnector:
    cfg = {"user_id": "u1", **overrides}
    c = GoogleDriveConnector(cfg)
    c._access_token = MagicMock(return_value="tok")
    return c


def _resp(json_data=None, content=b"", raises=False):
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    resp.content = content
    if raises:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError("500 error")
    return resp


@pytest.mark.unit
class TestGoogleDriveConnectorConfig:

    def test_connector_type(self):
        assert _make().connector_type == "google_drive"

    def test_display_name_defaults_to_my_drive(self):
        assert _make().display_name == "Google Drive: My Drive"

    def test_display_name_with_folder_id(self):
        assert "folder" in _make(folder_id="abcdefgh123").display_name

    def test_validate_config_missing_user_id(self):
        errors = GoogleDriveConnector({}).validate_config()
        assert any("user_id" in e for e in errors)

    def test_validate_config_valid(self):
        assert GoogleDriveConnector({"user_id": "u1"}).validate_config() == []


@pytest.mark.unit
class TestGoogleDriveConnectorListSources:

    def test_list_sources_returns_watched_files(self):
        c = _make()
        page = _resp({"files": [
            {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf"},
            {"id": "f2", "name": "photo.jpg", "mimeType": "image/jpeg"},
        ]})
        with patch("src.connectors.google_drive_connector.requests.get", return_value=page):
            sources = c.list_sources()
        assert [s.filename for s in sources] == ["report.pdf", "photo.jpg"]

    def test_list_sources_includes_google_workspace_docs_with_synthetic_extension(self):
        c = _make()
        page = _resp({"files": [
            {"id": "g1", "name": "My Doc", "mimeType": "application/vnd.google-apps.document"},
        ]})
        with patch("src.connectors.google_drive_connector.requests.get", return_value=page):
            sources = c.list_sources()
        assert sources[0].filename == "My Doc.txt"

    def test_list_sources_paginates(self):
        c = _make()
        page1 = _resp({"files": [{"id": "f1", "name": "a.pdf", "mimeType": "application/pdf"}],
                        "nextPageToken": "TOK1"})
        page2 = _resp({"files": [{"id": "f2", "name": "b.pdf", "mimeType": "application/pdf"}]})
        with patch("src.connectors.google_drive_connector.requests.get", side_effect=[page1, page2]) as mock_get:
            sources = c.list_sources()
        assert {s.filename for s in sources} == {"a.pdf", "b.pdf"}
        assert mock_get.call_count == 2

    def test_list_sources_restricts_to_folder(self):
        c = _make(folder_id="folder123")
        with patch("src.connectors.google_drive_connector.requests.get", return_value=_resp({"files": []})) as mock_get:
            c.list_sources()
        assert "folder123" in mock_get.call_args.kwargs["params"]["q"]

    def test_list_sources_empty_returns_empty_list(self):
        c = _make()
        with patch("src.connectors.google_drive_connector.requests.get", return_value=_resp({"files": []})):
            assert c.list_sources() == []

    def test_list_sources_swallows_api_error(self):
        c = _make()
        with patch("src.connectors.google_drive_connector.requests.get", return_value=_resp(raises=True)):
            assert c.list_sources() == []


@pytest.mark.unit
class TestGoogleDriveConnectorPoll:

    def test_poll_fetches_start_token_then_changes(self):
        c = _make()
        start_token_resp = _resp({"startPageToken": "START1"})
        changes_resp = _resp({
            "changes": [{"type": "file", "file": {"id": "f1", "name": "a.pdf", "mimeType": "application/pdf"}}],
            "newStartPageToken": "NEXT1",
        })
        with patch("src.connectors.google_drive_connector.requests.get",
                   side_effect=[start_token_resp, changes_resp]):
            events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.MODIFIED
        assert c._changes_page_token == "NEXT1"

    def test_poll_reuses_stored_page_token(self):
        c = _make()
        c._changes_page_token = "STORED"
        changes_resp = _resp({"changes": [], "newStartPageToken": "NEXT2"})
        with patch("src.connectors.google_drive_connector.requests.get", return_value=changes_resp) as mock_get:
            c.poll()
        assert mock_get.call_args.kwargs["params"]["pageToken"] == "STORED"

    def test_poll_reports_removed_files_as_deleted(self):
        c = _make()
        c._changes_page_token = "T"
        changes_resp = _resp({
            "changes": [{"type": "file", "removed": True,
                         "file": {"id": "f1", "name": "a.pdf", "mimeType": "application/pdf"}}],
            "newStartPageToken": "NEXT3",
        })
        with patch("src.connectors.google_drive_connector.requests.get", return_value=changes_resp):
            events = c.poll()
        assert events[0].event_type == EventType.DELETED

    def test_poll_ignores_non_file_changes_and_unwatched_extensions(self):
        c = _make()
        c._changes_page_token = "T"
        changes_resp = _resp({
            "changes": [
                {"type": "drive"},
                {"type": "file", "file": {"id": "f1", "name": "a.xyz", "mimeType": "application/octet-stream"}},
            ],
            "newStartPageToken": "NEXT4",
        })
        with patch("src.connectors.google_drive_connector.requests.get", return_value=changes_resp):
            events = c.poll()
        assert events == []

    def test_poll_follows_next_page_token_before_new_start_token(self):
        c = _make()
        c._changes_page_token = "T"
        page1 = _resp({
            "changes": [{"type": "file", "file": {"id": "f1", "name": "a.pdf", "mimeType": "application/pdf"}}],
            "nextPageToken": "PAGE2",
        })
        page2 = _resp({
            "changes": [{"type": "file", "file": {"id": "f2", "name": "b.pdf", "mimeType": "application/pdf"}}],
            "newStartPageToken": "NEXT5",
        })
        with patch("src.connectors.google_drive_connector.requests.get", side_effect=[page1, page2]):
            events = c.poll()
        assert len(events) == 2

    def test_poll_swallows_api_error(self):
        c = _make()
        with patch("src.connectors.google_drive_connector.requests.get", return_value=_resp(raises=True)):
            assert c.poll() == []


@pytest.mark.unit
class TestGoogleDriveConnectorFetch:

    def test_fetch_downloads_media_for_normal_files(self):
        c = _make()
        source = DocumentSource(source_id="f1", filename="a.pdf", metadata={"mime_type": "application/pdf"})
        resp = _resp(content=b"file data")
        with patch("src.connectors.google_drive_connector.requests.get", return_value=resp) as mock_get:
            data = c.fetch(source)
        assert data == b"file data"
        assert mock_get.call_args.kwargs["params"] == {"alt": "media"}

    def test_fetch_exports_google_workspace_documents(self):
        c = _make()
        source = DocumentSource(
            source_id="g1", filename="Doc.txt",
            metadata={"mime_type": "application/vnd.google-apps.document"},
        )
        resp = _resp(content=b"exported text")
        with patch("src.connectors.google_drive_connector.requests.get", return_value=resp) as mock_get:
            data = c.fetch(source)
        assert data == b"exported text"
        assert mock_get.call_args.kwargs["params"] == {"mimeType": "text/plain"}
        assert "export" in mock_get.call_args.args[0]

    def test_fetch_raises_on_api_error(self):
        c = _make()
        source = DocumentSource(source_id="f1", filename="a.pdf", metadata={"mime_type": "application/pdf"})
        with patch("src.connectors.google_drive_connector.requests.get", return_value=_resp(raises=True)):
            import requests
            with pytest.raises(requests.HTTPError):
                c.fetch(source)
