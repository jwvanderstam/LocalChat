"""
Unit tests for ConfluenceConnector (src/connectors/confluence_connector.py).

Confluence config (URL/email/API token) comes from ``src.config`` env vars
rather than the connector's own config dict, so tests patch
``src.connectors.confluence_connector.app_config`` attributes directly.
HTTP calls go through ``requests.get``, mocked at the module boundary.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.base import DocumentSource, EventType
from src.connectors.confluence_connector import ConfluenceConnector


@pytest.fixture(autouse=True)
def _confluence_env(monkeypatch):
    monkeypatch.setattr("src.connectors.confluence_connector.app_config.CONFLUENCE_URL", "https://x.atlassian.net")
    monkeypatch.setattr("src.connectors.confluence_connector.app_config.CONFLUENCE_EMAIL", "me@example.com")
    monkeypatch.setattr("src.connectors.confluence_connector.app_config.CONFLUENCE_API_TOKEN", "tok")


def _resp(json_data=None, raises=False):
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    if raises:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError("500 error")
    return resp


@pytest.mark.unit
class TestConfluenceConnectorConfig:

    def test_connector_type(self):
        assert ConfluenceConnector({}).connector_type == "confluence"

    def test_display_name_all_spaces(self):
        assert "all spaces" in ConfluenceConnector({}).display_name

    def test_display_name_specific_space(self):
        assert "ENG" in ConfluenceConnector({"space_key": "ENG"}).display_name

    def test_validate_config_valid_when_env_set(self):
        assert ConfluenceConnector({}).validate_config() == []

    def test_validate_config_missing_env_vars(self, monkeypatch):
        monkeypatch.setattr("src.connectors.confluence_connector.app_config.CONFLUENCE_URL", "")
        monkeypatch.setattr("src.connectors.confluence_connector.app_config.CONFLUENCE_EMAIL", "")
        monkeypatch.setattr("src.connectors.confluence_connector.app_config.CONFLUENCE_API_TOKEN", "")
        errors = ConfluenceConnector({}).validate_config()
        assert len(errors) == 3


@pytest.mark.unit
class TestConfluenceConnectorListSources:

    def test_list_sources_returns_pages(self):
        c = ConfluenceConnector({})
        page = _resp({"results": [
            {"id": "1", "title": "Home", "space": {"key": "ENG"}, "version": {"when": "2024-01-01T00:00:00Z"}},
        ]})
        with patch("src.connectors.confluence_connector.requests.get", return_value=page):
            sources = c.list_sources()
        assert len(sources) == 1
        assert sources[0].source_id == "1"
        assert sources[0].filename == "ENG_Home.txt"

    def test_list_sources_paginates(self):
        c = ConfluenceConnector({})
        # First page full (50 results) forces a second request; second page short-circuits.
        page1 = _resp({"results": [
            {"id": str(i), "title": f"Page{i}", "space": {"key": "ENG"}, "version": {}}
            for i in range(50)
        ]})
        page2 = _resp({"results": [
            {"id": "50", "title": "Last", "space": {"key": "ENG"}, "version": {}},
        ]})
        with patch("src.connectors.confluence_connector.requests.get", side_effect=[page1, page2]) as mock_get:
            sources = c.list_sources()
        assert len(sources) == 51
        assert mock_get.call_count == 2

    def test_list_sources_empty_returns_empty_list(self):
        c = ConfluenceConnector({})
        with patch("src.connectors.confluence_connector.requests.get", return_value=_resp({"results": []})):
            assert c.list_sources() == []

    def test_list_sources_swallows_api_error(self):
        c = ConfluenceConnector({})
        with patch("src.connectors.confluence_connector.requests.get", return_value=_resp(raises=True)):
            assert c.list_sources() == []

    def test_list_sources_restricts_to_space_key(self):
        c = ConfluenceConnector({"space_key": "ENG"})
        with patch("src.connectors.confluence_connector.requests.get", return_value=_resp({"results": []})) as mock_get:
            c.list_sources()
        assert mock_get.call_args.kwargs["params"]["spaceKey"] == "ENG"


@pytest.mark.unit
class TestConfluenceConnectorPoll:

    def test_first_poll_reports_all_pages_as_added(self):
        c = ConfluenceConnector({})
        page = _resp({"results": [
            {"id": "1", "title": "Home", "space": {"key": "ENG"}, "version": {}},
        ]})
        with patch("src.connectors.confluence_connector.requests.get", return_value=page):
            events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.ADDED
        assert c._last_poll_at is not None

    def test_subsequent_poll_uses_cql_and_reports_modified(self):
        c = ConfluenceConnector({})
        c._last_poll_at = datetime(2024, 1, 1, tzinfo=UTC)
        page = _resp({"results": [
            {"id": "2", "title": "Updated", "space": {"key": "ENG"}, "version": {}},
        ]})
        with patch("src.connectors.confluence_connector.requests.get", return_value=page) as mock_get:
            events = c.poll()
        assert events[0].event_type == EventType.MODIFIED
        cql = mock_get.call_args.kwargs["params"]["cql"]
        assert "lastModified >" in cql

    def test_poll_no_changes_returns_empty(self):
        c = ConfluenceConnector({})
        c._last_poll_at = datetime(2024, 1, 1, tzinfo=UTC)
        with patch("src.connectors.confluence_connector.requests.get", return_value=_resp({"results": []})):
            assert c.poll() == []

    def test_poll_swallows_api_error(self):
        c = ConfluenceConnector({})
        with patch("src.connectors.confluence_connector.requests.get", return_value=_resp(raises=True)):
            assert c.poll() == []


@pytest.mark.unit
class TestConfluenceConnectorFetch:

    def test_fetch_converts_html_to_text(self):
        c = ConfluenceConnector({})
        page = _resp({"body": {"storage": {"value": "<p>Hello world</p>"}}})
        with patch("src.connectors.confluence_connector.requests.get", return_value=page):
            data = c.fetch(DocumentSource(source_id="1", filename="Home.txt"))
        assert b"Hello world" in data

    def test_fetch_raises_on_api_error(self):
        c = ConfluenceConnector({})
        with patch("src.connectors.confluence_connector.requests.get", return_value=_resp(raises=True)):
            import requests
            with pytest.raises(requests.HTTPError):
                c.fetch(DocumentSource(source_id="1", filename="Home.txt"))
