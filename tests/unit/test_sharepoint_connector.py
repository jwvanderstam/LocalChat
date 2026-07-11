"""
Unit tests for SharePointConnector (src/connectors/sharepoint_connector.py).

The Graph API is reached via ``requests.get``, so all HTTP calls are mocked
at the module boundary (``src.connectors.sharepoint_connector.requests.get``).
``_access_token`` and ``_resolve_drive_id`` are stubbed directly since they
depend on OAuth token storage that is out of scope for these tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.connectors.base import DocumentSource, EventType
from src.connectors.sharepoint_connector import SharePointConnector


def _make(**overrides) -> SharePointConnector:
    cfg = {"site_url": "https://contoso.sharepoint.com/sites/x", "user_id": "u1", **overrides}
    c = SharePointConnector(cfg)
    c._access_token = MagicMock(return_value="tok")
    c._resolve_drive_id = MagicMock(return_value="drive1")
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
class TestSharePointConnectorConfig:

    def test_connector_type(self):
        assert _make().connector_type == "sharepoint"

    def test_display_name_contains_site_url(self):
        assert "contoso.sharepoint.com" in _make().display_name

    def test_validate_config_missing_site_url(self):
        c = SharePointConnector({"user_id": "u1"})
        errors = c.validate_config()
        assert any("site_url" in e for e in errors)

    def test_validate_config_missing_user_id(self):
        c = SharePointConnector({"site_url": "https://x"})
        errors = c.validate_config()
        assert any("user_id" in e for e in errors)

    def test_validate_config_valid(self):
        c = SharePointConnector({"site_url": "https://x", "user_id": "u1"})
        assert c.validate_config() == []


@pytest.mark.unit
class TestSharePointConnectorListSources:

    def test_list_sources_returns_watched_files(self):
        c = _make()
        root_page = _resp({"value": [
            {"id": "f1", "name": "report.pdf", "size": 10, "lastModifiedDateTime": "2024-01-01T00:00:00Z"},
            {"id": "f2", "name": "archive.exe"},
            {"id": "folder1", "name": "sub", "folder": {}},
        ]})
        sub_page = _resp({"value": []})
        with patch("src.connectors.sharepoint_connector.requests.get",
                   side_effect=[root_page, sub_page]) as mock_get:
            sources = c.list_sources()
        assert len(sources) == 1
        assert sources[0].filename == "report.pdf"
        assert sources[0].source_id == "f1"
        assert mock_get.call_count == 2

    def test_list_sources_recurses_into_folders(self):
        c = _make()
        root_page = _resp({"value": [{"id": "folder1", "name": "sub", "folder": {}}]})
        sub_page = _resp({"value": [{"id": "f1", "name": "nested.pdf"}]})
        with patch("src.connectors.sharepoint_connector.requests.get", side_effect=[root_page, sub_page]):
            sources = c.list_sources()
        assert [s.filename for s in sources] == ["nested.pdf"]

    def test_list_sources_follows_next_link(self):
        c = _make()
        page1 = _resp({"value": [{"id": "f1", "name": "a.pdf"}], "@odata.nextLink": "https://next"})
        page2 = _resp({"value": [{"id": "f2", "name": "b.pdf"}]})
        with patch("src.connectors.sharepoint_connector.requests.get", side_effect=[page1, page2]):
            sources = c.list_sources()
        assert {s.filename for s in sources} == {"a.pdf", "b.pdf"}

    def test_list_sources_empty_returns_empty_list(self):
        c = _make()
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=_resp({"value": []})):
            assert c.list_sources() == []

    def test_list_sources_swallows_api_error(self):
        c = _make()
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=_resp(raises=True)):
            assert c.list_sources() == []


@pytest.mark.unit
class TestSharePointConnectorPoll:

    def test_poll_first_call_reports_added_and_stores_delta_token(self):
        c = _make()
        page = _resp({
            "value": [{"id": "f1", "name": "a.pdf"}],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/drive1/root/delta?token=TOK1",
        })
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=page):
            events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.ADDED
        assert c._delta_token == "TOK1"

    def test_poll_subsequent_call_reports_modified(self):
        c = _make()
        c._delta_token = "TOK1"
        page = _resp({
            "value": [{"id": "f1", "name": "a.pdf"}],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/drives/drive1/root/delta?token=TOK2",
        })
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=page) as mock_get:
            events = c.poll()
        assert events[0].event_type == EventType.MODIFIED
        called_url = mock_get.call_args_list[0].args[0]
        assert "token=TOK1" in called_url

    def test_poll_reports_deleted_items(self):
        c = _make()
        page = _resp({
            "value": [{"id": "f1", "name": "a.pdf", "deleted": {"state": "deleted"}}],
            "@odata.deltaLink": "https://x?token=TOK3",
        })
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=page):
            events = c.poll()
        assert events[0].event_type == EventType.DELETED

    def test_poll_ignores_folders_and_unwatched_extensions(self):
        c = _make()
        page = _resp({
            "value": [
                {"id": "d1", "name": "sub", "folder": {}},
                {"id": "f1", "name": "archive.exe"},
            ],
            "@odata.deltaLink": "https://x?token=TOK4",
        })
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=page):
            events = c.poll()
        assert events == []

    def test_poll_no_changes_returns_empty(self):
        c = _make()
        page = _resp({"value": [], "@odata.deltaLink": "https://x?token=TOK5"})
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=page):
            assert c.poll() == []

    def test_poll_swallows_api_error(self):
        c = _make()
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=_resp(raises=True)):
            assert c.poll() == []


@pytest.mark.unit
class TestSharePointConnectorFetch:

    def test_fetch_returns_content_bytes(self):
        c = _make()
        source = DocumentSource(source_id="f1", filename="a.pdf", metadata={"drive_id": "drive1"})
        resp = _resp(content=b"file data")
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=resp) as mock_get:
            data = c.fetch(source)
        assert data == b"file data"
        assert "drives/drive1/items/f1/content" in mock_get.call_args.args[0]

    def test_fetch_raises_on_api_error(self):
        c = _make()
        source = DocumentSource(source_id="f1", filename="a.pdf", metadata={"drive_id": "drive1"})
        with patch("src.connectors.sharepoint_connector.requests.get", return_value=_resp(raises=True)):
            import requests
            with pytest.raises(requests.HTTPError):
                c.fetch(source)
