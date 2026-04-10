"""
SharePoint Connector
====================

Watches a SharePoint document library for changes using the Microsoft Graph
API delta query mechanism.

Config keys:
    site_url    (required)  SharePoint site URL, e.g. https://contoso.sharepoint.com/sites/mysite
    drive_id    (optional)  Specific document library drive ID (defaults to the site's default drive)
    user_id     (required)  UUID of the LocalChat user whose OAuth token is used
    recursive   (optional, default true)  Include files in sub-folders
    extensions  (optional)  List of file extensions to ingest (empty = all supported)

Requires: Microsoft OAuth token stored for the configured user_id.
See GET /api/oauth/microsoft/authorize to connect.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .. import config as app_config
from ..utils.logging_config import get_logger
from .base import BaseConnector, DocumentEvent, DocumentSource, EventType

logger = get_logger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointConnector(BaseConnector):
    """Watches a SharePoint document library via Graph API delta queries."""

    @property
    def connector_type(self) -> str:
        return "sharepoint"

    @property
    def display_name(self) -> str:
        return f"SharePoint: {self.config.get('site_url', '')}"

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.config.get('site_url', '').strip():
            errors.append("'site_url' is required")
        if not self.config.get('user_id', '').strip():
            errors.append("'user_id' is required (LocalChat user UUID for OAuth token)")
        return errors

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def list_sources(self) -> list[DocumentSource]:
        """Return all files currently in the document library."""
        try:
            token = self._access_token()
            drive_id = self._resolve_drive_id(token)
            return self._list_recursive(token, drive_id, "root")
        except Exception as exc:
            logger.error(f"[SharePoint] list_sources failed: {exc}")
            return []

    def poll(self) -> list[DocumentEvent]:
        """Return delta events since the last poll using Graph delta queries."""
        try:
            token = self._access_token()
            drive_id = self._resolve_drive_id(token)
            return self._delta_poll(token, drive_id)
        except Exception as exc:
            logger.error(f"[SharePoint] poll failed: {exc}")
            return []

    def fetch(self, source: DocumentSource) -> bytes:
        token = self._access_token()
        url = f"{_GRAPH_BASE}/drives/{source.metadata.get('drive_id')}/items/{source.source_id}/content"
        resp = requests.get(url, headers=self._auth_headers(token), timeout=60, allow_redirects=True)
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _access_token(self) -> str:
        from .microsoft_auth import get_valid_access_token
        # db is injected via BaseConnector.__init__ if provided; fallback import
        db = getattr(self, '_db', None)
        if db is None:
            from ..db import db as _db
            db = _db
        return get_valid_access_token(self.config['user_id'], db)

    def _auth_headers(self, token: str) -> dict:
        return {'Authorization': f'Bearer {token}'}

    def _resolve_drive_id(self, token: str) -> str:
        """Return configured drive_id or the site's default drive id."""
        if self.config.get('drive_id'):
            return self.config['drive_id']
        site_id = self._resolve_site_id(token)
        resp = requests.get(
            f"{_GRAPH_BASE}/sites/{site_id}/drive",
            headers=self._auth_headers(token),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['id']

    def _resolve_site_id(self, token: str) -> str:
        """Convert site_url to a Graph site ID."""
        from urllib.parse import urlparse
        parsed = urlparse(self.config['site_url'])
        hostname = parsed.netloc
        path = parsed.path.rstrip('/')
        resp = requests.get(
            f"{_GRAPH_BASE}/sites/{hostname}:{path}",
            headers=self._auth_headers(token),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['id']

    def _watched_extensions(self) -> set[str]:
        exts = self.config.get('extensions') or []
        if exts:
            return {e.lower() if e.startswith('.') else f'.{e.lower()}' for e in exts}
        return set(app_config.SUPPORTED_EXTENSIONS)

    def _is_watched(self, name: str) -> bool:
        return Path(name).suffix.lower() in self._watched_extensions()

    def _list_recursive(self, token: str, drive_id: str, item_id: str) -> list[DocumentSource]:
        sources: list[DocumentSource] = []
        url = f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}/children"
        while url:
            resp = requests.get(url, headers=self._auth_headers(token), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get('value', []):
                if 'folder' in item:
                    if self.config.get('recursive', True):
                        sources.extend(self._list_recursive(token, drive_id, item['id']))
                elif self._is_watched(item.get('name', '')):
                    sources.append(self._item_to_source(item, drive_id))
            url = data.get('@odata.nextLink')
        return sources

    def _delta_poll(self, token: str, drive_id: str) -> list[DocumentEvent]:
        delta_token = getattr(self, '_delta_token', None)
        if delta_token:
            url = f"{_GRAPH_BASE}/drives/{drive_id}/root/delta?token={delta_token}"
        else:
            url = f"{_GRAPH_BASE}/drives/{drive_id}/root/delta"

        events: list[DocumentEvent] = []
        while url:
            resp = requests.get(url, headers=self._auth_headers(token), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get('value', []):
                if 'folder' in item:
                    continue
                name = item.get('name', '')
                if not self._is_watched(name):
                    continue
                if item.get('deleted'):
                    events.append(DocumentEvent(
                        EventType.DELETED,
                        DocumentSource(source_id=item['id'], filename=name),
                    ))
                elif delta_token is None:
                    events.append(DocumentEvent(EventType.ADDED, self._item_to_source(item, drive_id)))
                else:
                    events.append(DocumentEvent(EventType.MODIFIED, self._item_to_source(item, drive_id)))
            url = data.get('@odata.nextLink')
            if '@odata.deltaLink' in data:
                new_token = data['@odata.deltaLink'].split('token=')[-1]
                self._delta_token = new_token
                break

        if events:
            logger.info(f"[SharePoint] {len(events)} event(s) from {self.config.get('site_url')}")
        return events

    def _item_to_source(self, item: dict[str, Any], drive_id: str) -> DocumentSource:
        last_modified = None
        if lm := item.get('lastModifiedDateTime'):
            try:
                last_modified = datetime.fromisoformat(lm.replace('Z', '+00:00'))
            except Exception:
                pass
        return DocumentSource(
            source_id=item['id'],
            filename=item.get('name', ''),
            last_modified=last_modified,
            size_bytes=item.get('size'),
            metadata={
                'drive_id': drive_id,
                'web_url': item.get('webUrl', ''),
                'parent_path': item.get('parentReference', {}).get('path', ''),
            },
        )
