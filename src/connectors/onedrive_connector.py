"""
OneDrive Connector
==================

Watches a OneDrive personal drive for changes using the Microsoft Graph API
delta query mechanism.

Config keys:
    user_id     (required)  UUID of the LocalChat user whose OAuth token is used
    folder_path (optional)  Folder path within OneDrive (default: root)
    recursive   (optional, default true)
    extensions  (optional)  List of extensions to watch

Requires: Microsoft OAuth token stored for the configured user_id.
See GET /api/oauth/microsoft/authorize to connect.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .. import config as app_config
from ..utils.logging_config import get_logger
from .base import BaseConnector, DocumentEvent, DocumentSource, EventType

logger = get_logger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OneDriveConnector(BaseConnector):
    """Watches a personal OneDrive via Graph API delta queries."""

    @property
    def connector_type(self) -> str:
        return "onedrive"

    @property
    def display_name(self) -> str:
        folder = self.config.get('folder_path', 'root')
        return f"OneDrive: {folder}"

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.config.get('user_id', '').strip():
            errors.append("'user_id' is required (LocalChat user UUID for OAuth token)")
        return errors

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def list_sources(self) -> list[DocumentSource]:
        try:
            token = self._access_token()
            root_item = self._resolve_root_item(token)
            return self._list_recursive(token, root_item)
        except Exception as exc:
            logger.error(f"[OneDrive] list_sources failed: {exc}")
            return []

    def poll(self) -> list[DocumentEvent]:
        try:
            token = self._access_token()
            return self._delta_poll(token)
        except Exception as exc:
            logger.error(f"[OneDrive] poll failed: {exc}")
            return []

    def fetch(self, source: DocumentSource) -> bytes:
        token = self._access_token()
        url = f"{_GRAPH_BASE}/me/drive/items/{source.source_id}/content"
        resp = requests.get(url, headers=self._auth_headers(token), timeout=60, allow_redirects=True)
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _access_token(self) -> str:
        from .microsoft_auth import get_valid_access_token
        db = getattr(self, '_db', None)
        if db is None:
            from ..db import db as _db
            db = _db
        return get_valid_access_token(self.config['user_id'], db)

    def _auth_headers(self, token: str) -> dict:
        return {'Authorization': f'Bearer {token}'}

    def _resolve_root_item(self, token: str) -> str:
        """Return the item ID for the configured folder_path."""
        folder_path = self.config.get('folder_path', '').strip('/')
        if not folder_path:
            return 'root'
        resp = requests.get(
            f"{_GRAPH_BASE}/me/drive/root:/{folder_path}",
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

    def _list_recursive(self, token: str, item_id: str) -> list[DocumentSource]:
        sources: list[DocumentSource] = []
        url = f"{_GRAPH_BASE}/me/drive/items/{item_id}/children"
        while url:
            resp = requests.get(url, headers=self._auth_headers(token), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get('value', []):
                if 'folder' in item:
                    if self.config.get('recursive', True):
                        sources.extend(self._list_recursive(token, item['id']))
                elif self._is_watched(item.get('name', '')):
                    sources.append(self._item_to_source(item))
            url = data.get('@odata.nextLink')
        return sources

    def _delta_poll(self, token: str) -> list[DocumentEvent]:
        delta_token = getattr(self, '_delta_token', None)
        folder_path = self.config.get('folder_path', '').strip('/')
        if delta_token:
            url = f"{_GRAPH_BASE}/me/drive/root/delta?token={delta_token}"
        elif folder_path:
            url = f"{_GRAPH_BASE}/me/drive/root:/{folder_path}:/delta"
        else:
            url = f"{_GRAPH_BASE}/me/drive/root/delta"

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
                    events.append(DocumentEvent(EventType.ADDED, self._item_to_source(item)))
                else:
                    events.append(DocumentEvent(EventType.MODIFIED, self._item_to_source(item)))
            url = data.get('@odata.nextLink')
            if '@odata.deltaLink' in data:
                self._delta_token = data['@odata.deltaLink'].split('token=')[-1]
                break

        if events:
            logger.info(f"[OneDrive] {len(events)} event(s)")
        return events

    def _item_to_source(self, item: dict[str, Any]) -> DocumentSource:
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
            metadata={'web_url': item.get('webUrl', '')},
        )
