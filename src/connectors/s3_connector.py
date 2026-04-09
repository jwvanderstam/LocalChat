"""
S3 Connector (stub)
===================

Polls an S3-compatible bucket (AWS S3, MinIO, Cloudflare R2, etc.) for
new, modified, and deleted objects using ``ListObjectsV2`` with
``LastModified`` comparisons.

Requires ``boto3`` (``pip install boto3``).  The connector gracefully
degrades to an import error at *instantiation* time (not import time)
so the rest of the application starts normally without boto3.

Config keys:
    bucket          (required) Bucket name.
    prefix          (optional) Key prefix to restrict the watch scope.
    endpoint_url    (optional) Custom endpoint for S3-compatible stores.
    region          (optional) AWS region, default 'us-east-1'.
    access_key_id   (optional) Falls back to env / IAM role if omitted.
    secret_access_key (optional) Same fallback.
    extensions      (optional) List of extensions to watch.
"""

from __future__ import annotations

import os
from typing import Any

from ..utils.logging_config import get_logger
from .base import BaseConnector, DocumentEvent, DocumentSource, EventType

logger = get_logger(__name__)


class S3Connector(BaseConnector):
    """S3 / S3-compatible bucket connector."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        try:
            import boto3  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "S3Connector requires boto3: pip install boto3"
            ) from exc
        self._client = None
        self._snapshot: dict[str, str] = {}  # key → etag

    @property
    def connector_type(self) -> str:
        return "s3"

    @property
    def display_name(self) -> str:
        bucket = self.config.get("bucket", "")
        prefix = self.config.get("prefix", "")
        label = f"s3://{bucket}"
        if prefix:
            label += f"/{prefix.strip('/')}"
        return label

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.config.get("bucket", "").strip():
            errors.append("'bucket' is required")
        return errors

    def _get_client(self):
        if self._client is None:
            import boto3
            kwargs: dict[str, Any] = {
                "region_name": self.config.get("region", "us-east-1"),
            }
            if self.config.get("endpoint_url"):
                kwargs["endpoint_url"] = self.config["endpoint_url"]
            if self.config.get("access_key_id"):
                kwargs["aws_access_key_id"] = self.config["access_key_id"]
            if self.config.get("secret_access_key"):
                kwargs["aws_secret_access_key"] = self.config["secret_access_key"]
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _watched_extensions(self) -> set[str]:
        from .. import config as app_config
        exts = self.config.get("extensions") or []
        if exts:
            return {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
        return set(app_config.SUPPORTED_EXTENSIONS)

    def _is_watched(self, key: str) -> bool:
        ext = os.path.splitext(key)[1].lower()
        return ext in self._watched_extensions()

    def _list_objects(self) -> dict[str, str]:
        """Return {key: etag} for all watched objects in the bucket."""
        client = self._get_client()
        bucket = self.config["bucket"]
        prefix = self.config.get("prefix", "")
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if prefix:
            kwargs["Prefix"] = prefix
        result: dict[str, str] = {}
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if self._is_watched(key):
                    result[key] = obj["ETag"].strip('"')
        return result

    def list_sources(self) -> list[DocumentSource]:
        from datetime import timezone
        client = self._get_client()
        bucket = self.config["bucket"]
        prefix = self.config.get("prefix", "")
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if prefix:
            kwargs["Prefix"] = prefix
        sources: list[DocumentSource] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not self._is_watched(key):
                    continue
                sources.append(DocumentSource(
                    source_id=key,
                    filename=os.path.basename(key),
                    last_modified=obj.get("LastModified"),
                    size_bytes=obj.get("Size", 0),
                    metadata={"bucket": bucket, "key": key},
                ))
        return sources

    def poll(self) -> list[DocumentEvent]:
        current = self._list_objects()
        previous = self._snapshot
        self._snapshot = current
        events: list[DocumentEvent] = []

        for key, etag in current.items():
            source = DocumentSource(
                source_id=key,
                filename=os.path.basename(key),
                metadata={"bucket": self.config["bucket"], "key": key},
            )
            if key not in previous:
                events.append(DocumentEvent(EventType.ADDED, source))
            elif etag != previous[key]:
                events.append(DocumentEvent(EventType.MODIFIED, source))

        for key in previous:
            if key not in current:
                events.append(DocumentEvent(
                    EventType.DELETED,
                    DocumentSource(source_id=key, filename=os.path.basename(key)),
                ))

        if events:
            logger.info(f"[S3] {len(events)} event(s) from {self.display_name}")
        return events

    def fetch(self, source: DocumentSource) -> bytes:
        client = self._get_client()
        resp = client.get_object(Bucket=self.config["bucket"], Key=source.source_id)
        return resp["Body"].read()
