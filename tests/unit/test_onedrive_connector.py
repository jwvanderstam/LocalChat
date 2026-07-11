"""
Unit tests for OneDriveConnector (src/connectors/onedrive_connector.py).

Same shape as the SharePoint connector tests: Graph API calls go through
``requests.get`` which is mocked at the module boundary, and
``_access_token`` is stubbed to avoid needing real OAuth token storage.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.connectors.base import DocumentSource, EventType
from src.connectors.onedrive_connector import OneDriveConnector


def _make(**overrides) -> OneDriveConnector:
    cfg = {"user_id": "u1", **overrides}
    c = OneDriveConnector(cfg)
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
class TestOneDriveConnectorConfig:

    def test_connector_type(self):
        assert _make().connector_type == "onedrive"

    def test_display_name_defaults_to_root(self):
        assert _make().display_name == "OneDrive: root"

    def test_display_name_uses_folder_path(self):
        assert _make(folder_path="Docs").display_name == "OneDrive: Docs"

    def test_validate_config_missing_user_id(self):
        errors = OneDriveConnector({}).validate_config()
        assert any("user_id" in e for e in errors)

    def test_validate_config_valid(self):
        assert OneDriveConnector({"user_id": "u1"}).validate_config() == []


@pytest.mark.unit
class TestOneDriveConnectorListSources:

    def test_list_sources_returns_watched_files(self):
        c = _make()
        page = _resp({"value": [
            {"id": "f1", "name": "report.pdf", "size": 10},
            {"id": "f2", "name": "archive.exe"},
        ]})
        with patch("src.connectors.onedrive_connector.requests.get", return_value=page):
            sources = c.list_sources()
        assert [s.filename for s in sources] == ["report.pdf"]

    def test_list_sources_recurses_into_folders(self):
        c = _make()
        root_page = _resp({"value": [{"id": "d1", "name": "sub", "folder": {}}]})
        sub_page = _resp({"value": [{"id": "f1", "name": "nested.pdf"}]})
        with patch("src.connectors.onedrive_connector.requests.get", side_effect=[root_page, sub_page]):
            sources = c.list_sources()
        assert [s.filename for s in sources] == ["nested.pdf"]

    def test_list_sources_non_recursive_skips_folders(self):
        c = _make(recursive=False)
        root_page = _resp({"value": [
            {"id": "d1", "name": "sub", "folder": {}},
            {"id": "f1", "name": "top.pdf"},
        ]})
        with patch("src.connectors.onedrive_connector.requests.get", return_value=root_page) as mock_get:
            sources = c.list_sources()
        assert [s.filename for s in sources] == ["top.pdf"]
        mock_get.assert_called_once()

    def test_list_sources_empty_returns_empty_list(self):
        c = _make()
        with patch("src.connectors.onedrive_connector.requests.get", return_value=_resp({"value": []})):
            assert c.list_sources() == []

    def test_list_sources_swallows_api_error(self):
        c = _make()
        with patch("src.connectors.onedrive_connector.requests.get", return_value=_resp(raises=True)):
            assert c.list_sources() == []

    def test_resolve_root_item_uses_folder_path(self):
        c = _make(folder_path="Docs/Reports")
        resp = _resp({"id": "resolved-id"})
        with patch("src.connectors.onedrive_connector.requests.get", return_value=resp) as mock_get:
            item_id = c._resolve_root_item("tok")
        assert item_id == "resolved-id"
        assert "root:/Docs/Reports" in mock_get.call_args.args[0]


@pytest.mark.unit
class TestOneDriveConnectorPoll:

    def test_poll_first_call_reports_added_and_stores_delta_token(self):
        c = _make()
        page = _resp({
            "value": [{"id": "f1", "name": "a.pdf"}],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/drive/root/delta?token=TOK1",
        })
        with patch("src.connectors.onedrive_connector.requests.get", return_value=page):
            events = c.poll()
        assert events[0].event_type == EventType.ADDED
        assert c._delta_token == "TOK1"

    def test_poll_subsequent_call_reports_modified(self):
        c = _make()
        c._delta_token = "TOK1"
        page = _resp({
            "value": [{"id": "f1", "name": "a.pdf"}],
            "@odata.deltaLink": "https://x?token=TOK2",
        })
        with patch("src.connectors.onedrive_connector.requests.get", return_value=page) as mock_get:
            events = c.poll()
        assert events[0].event_type == EventType.MODIFIED
        assert "token=TOK1" in mock_get.call_args_list[0].args[0]

    def test_poll_reports_deleted_items(self):
        c = _make()
        page = _resp({
            "value": [{"id": "f1", "name": "a.pdf", "deleted": {"state": "deleted"}}],
            "@odata.deltaLink": "https://x?token=TOK3",
        })
        with patch("src.connectors.onedrive_connector.requests.get", return_value=page):
            events = c.poll()
        assert events[0].event_type == EventType.DELETED

    def test_poll_follows_next_link_before_delta_link(self):
        c = _make()
        page1 = _resp({"value": [{"id": "f1", "name": "a.pdf"}], "@odata.nextLink": "https://next"})
        page2 = _resp({"value": [{"id": "f2", "name": "b.pdf"}], "@odata.deltaLink": "https://x?token=TOK4"})
        with patch("src.connectors.onedrive_connector.requests.get", side_effect=[page1, page2]):
            events = c.poll()
        assert len(events) == 2

    def test_poll_no_changes_returns_empty(self):
        c = _make()
        page = _resp({"value": [], "@odata.deltaLink": "https://x?token=TOK5"})
        with patch("src.connectors.onedrive_connector.requests.get", return_value=page):
            assert c.poll() == []

    def test_poll_swallows_api_error(self):
        c = _make()
        with patch("src.connectors.onedrive_connector.requests.get", return_value=_resp(raises=True)):
            assert c.poll() == []


@pytest.mark.unit
class TestOneDriveConnectorFetch:

    def test_fetch_returns_content_bytes(self):
        c = _make()
        source = DocumentSource(source_id="f1", filename="a.pdf")
        resp = _resp(content=b"file data")
        with patch("src.connectors.onedrive_connector.requests.get", return_value=resp) as mock_get:
            data = c.fetch(source)
        assert data == b"file data"
        assert "items/f1/content" in mock_get.call_args.args[0]

    def test_fetch_raises_on_api_error(self):
        c = _make()
        source = DocumentSource(source_id="f1", filename="a.pdf")
        with patch("src.connectors.onedrive_connector.requests.get", return_value=_resp(raises=True)):
            import requests
            with pytest.raises(requests.HTTPError):
                c.fetch(source)
