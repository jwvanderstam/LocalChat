"""
Unit tests for S3Connector (src/connectors/s3_connector.py).

boto3 is an optional dependency and is not installed in the test
environment, so the "requires boto3" ImportError branch is exercised
directly. For the happy-path tests a fake ``boto3`` module is injected
into ``sys.modules`` so the connector can be constructed, then the
underlying client is replaced with a MagicMock (bypassing ``_get_client``)
so paginate()/get_object() behaviour can be controlled per test.
"""
from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.connectors.base import EventType


@pytest.fixture
def s3_connector_cls(monkeypatch):
    """S3Connector with a fake boto3 module injected for the test's duration."""
    monkeypatch.setitem(sys.modules, "boto3", MagicMock())
    from src.connectors.s3_connector import S3Connector
    return S3Connector


def _with_client(connector, pages):
    """Attach a mock boto3 client whose paginator yields the given pages."""
    mock_client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = pages
    mock_client.get_paginator.return_value = paginator
    connector._client = mock_client
    return mock_client


@pytest.mark.unit
class TestS3ConnectorConfig:

    def test_raises_import_error_without_boto3(self):
        # boto3 is genuinely absent from this environment, so this exercises
        # the real graceful-degradation branch without any mocking.
        from src.connectors.s3_connector import S3Connector
        with pytest.raises(ImportError, match="boto3"):
            S3Connector({"bucket": "b"})

    def test_connector_type(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        assert c.connector_type == "s3"

    def test_display_name_with_prefix(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b", "prefix": "docs/"})
        assert c.display_name == "s3://b/docs"

    def test_display_name_without_prefix(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        assert c.display_name == "s3://b"

    def test_validate_config_missing_bucket(self, s3_connector_cls):
        errors = s3_connector_cls({}).validate_config()
        assert any("bucket" in e for e in errors)

    def test_validate_config_valid(self, s3_connector_cls):
        assert s3_connector_cls({"bucket": "b"}).validate_config() == []


@pytest.mark.unit
class TestS3ConnectorListSources:

    def test_list_sources_returns_watched_files_with_pagination(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b", "prefix": "docs"})
        pages = [
            {"Contents": [
                {"Key": "docs/a.txt", "ETag": '"e1"', "LastModified": datetime(2024, 1, 1), "Size": 10},
                {"Key": "docs/b.bin", "ETag": '"e2"', "LastModified": datetime(2024, 1, 1), "Size": 5},
            ]},
            {"Contents": [
                {"Key": "docs/c.pdf", "ETag": '"e3"', "LastModified": datetime(2024, 1, 2), "Size": 20},
            ]},
        ]
        _with_client(c, pages)
        sources = c.list_sources()
        filenames = {s.filename for s in sources}
        assert filenames == {"a.txt", "c.pdf"}  # .bin is not a supported extension

    def test_list_sources_empty_bucket(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        _with_client(c, [{"Contents": []}])
        assert c.list_sources() == []

    def test_list_sources_propagates_api_error(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        mock_client = _with_client(c, [])
        mock_client.get_paginator.return_value.paginate.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            c.list_sources()


@pytest.mark.unit
class TestS3ConnectorPoll:

    def test_poll_first_call_reports_added(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        _with_client(c, [{"Contents": [
            {"Key": "a.txt", "ETag": '"e1"', "LastModified": datetime(2024, 1, 1), "Size": 1},
        ]}])
        events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.ADDED
        assert events[0].source.filename == "a.txt"

    def test_poll_no_changes_returns_empty(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        page = [{"Contents": [
            {"Key": "a.txt", "ETag": '"e1"', "LastModified": datetime(2024, 1, 1), "Size": 1},
        ]}]
        _with_client(c, page)
        c.poll()  # establish snapshot
        _with_client(c, page)
        assert c.poll() == []

    def test_poll_detects_modified_etag(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        _with_client(c, [{"Contents": [
            {"Key": "a.txt", "ETag": '"e1"', "LastModified": datetime(2024, 1, 1), "Size": 1},
        ]}])
        c.poll()
        _with_client(c, [{"Contents": [
            {"Key": "a.txt", "ETag": '"e2-changed"', "LastModified": datetime(2024, 1, 2), "Size": 2},
        ]}])
        events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.MODIFIED

    def test_poll_detects_deleted_key(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        _with_client(c, [{"Contents": [
            {"Key": "a.txt", "ETag": '"e1"', "LastModified": datetime(2024, 1, 1), "Size": 1},
        ]}])
        c.poll()
        _with_client(c, [{"Contents": []}])
        events = c.poll()
        assert len(events) == 1
        assert events[0].event_type == EventType.DELETED
        assert events[0].source.filename == "a.txt"


@pytest.mark.unit
class TestS3ConnectorFetch:

    def test_fetch_returns_object_bytes(self, s3_connector_cls):
        c = s3_connector_cls({"bucket": "b"})
        mock_client = _with_client(c, [])
        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"file bytes"))}
        from src.connectors.base import DocumentSource
        source = DocumentSource(source_id="docs/a.txt", filename="a.txt")
        assert c.fetch(source) == b"file bytes"
        mock_client.get_object.assert_called_once_with(Bucket="b", Key="docs/a.txt")
