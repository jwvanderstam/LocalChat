"""
Google Drive Connector
======================

Watches a Google Drive for changes using the Drive API v3 changes feed.

Config keys:
    user_id    (required)  UUID of the LocalChat user whose OAuth token is used
    folder_id  (optional)  Drive folder ID to watch (default: entire My Drive)
    recursive  (optional, default true)
    extensions (optional)  List of extensions to watch (default: all supported)

Requires: Google OAuth token stored for the configured user_id.
See GET /api/oauth/google/authorize to connect.
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

_DRIVE_BASE = "https://www.googleapis.com/drive/v3"

# Google Workspace MIME types and the plain-text export format to request
_EXPORT_MIME: dict[str, str] = {
    'application/vnd.google-apps.document':     'text/plain',
    'application/vnd.google-apps.spreadsheet':  'text/csv',
    'application/vnd.google-apps.presentation': 'text/plain',
}

# Synthetic extensions appended when a Google Workspace file has no extension
_WORKSPACE_EXT: dict[str, str] = {
    'application/vnd.google-apps.document':     '.txt',
    'application/vnd.google-apps.spreadsheet':  '.csv',
    'application/vnd.google-apps.presentation': '.txt',
}


class GoogleDriveConnector(BaseConnector):
    """Watches a Google Drive folder via the Drive API v3 changes feed."""

    @property
    def connector_type(self) -> str:
        return "google_drive"

    @property
    def display_name(self) -> str:
        folder_id = self.config.get('folder_id', '')
        label = ('folder ' + folder_id[:8] + '…') if folder_id else 'My Drive'
        return f"Google Drive: {label}"

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
            return self._list_files(self._access_token())
        except Exception:
            logger.exception("[GoogleDrive] list_sources failed")
            return []

    def poll(self) -> list[DocumentEvent]:
        try:
            return self._changes_poll(self._access_token())
        except Exception:
            logger.exception("[GoogleDrive] poll failed")
            return []

    def fetch(self, source: DocumentSource) -> bytes:
        token = self._access_token()
        mime_type = source.metadata.get('mime_type', '')
        export_mime = _EXPORT_MIME.get(mime_type)
        if export_mime:
            resp = requests.get(
                f"{_DRIVE_BASE}/files/{source.source_id}/export",
                params={'mimeType': export_mime},
                headers=self._auth_headers(token),
                timeout=60,
            )
        else:
            resp = requests.get(
                f"{_DRIVE_BASE}/files/{source.source_id}",
                params={'alt': 'media'},
                headers=self._auth_headers(token),
                timeout=60,
            )
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _access_token(self) -> str:
        from .google_auth import get_valid_google_access_token
        db = getattr(self, '_db', None)
        if db is None:
            from ..db import db as _db
            db = _db
        return get_valid_google_access_token(self.config['user_id'], db)

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {'Authorization': f'Bearer {token}'}

    def _watched_extensions(self) -> set[str]:
        exts = self.config.get('extensions') or []
        if exts:
            return {e.lower() if e.startswith('.') else f'.{e.lower()}' for e in exts}
        return set(app_config.SUPPORTED_EXTENSIONS)

    def _is_watched(self, name: str, mime_type: str) -> bool:
        if mime_type in _EXPORT_MIME:
            return True
        return Path(name).suffix.lower() in self._watched_extensions()

    def _list_files(self, token: str) -> list[DocumentSource]:
        """Enumerate files in the configured folder (or all of My Drive)."""
        sources: list[DocumentSource] = []
        folder_id = self.config.get('folder_id', '')
        query = f"'{folder_id}' in parents and trashed=false" if folder_id else "trashed=false"
        params: dict[str, Any] = {
            'q': query,
            'fields': 'nextPageToken,files(id,name,mimeType,modifiedTime,size,webViewLink)',
            'pageSize': 100,
        }
        while True:
            resp = requests.get(f"{_DRIVE_BASE}/files", params=params,
                                headers=self._auth_headers(token), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get('files', []):
                if self._is_watched(item.get('name', ''), item.get('mimeType', '')):
                    sources.append(self._item_to_source(item))
            next_token = data.get('nextPageToken')
            if not next_token:
                break
            params['pageToken'] = next_token
        return sources

    def _get_start_page_token(self, token: str) -> str:
        resp = requests.get(f"{_DRIVE_BASE}/changes/startPageToken",
                            headers=self._auth_headers(token), timeout=15)
        resp.raise_for_status()
        return resp.json()['startPageToken']

    def _changes_poll(self, token: str) -> list[DocumentEvent]:
        """Poll the Drive changes feed from the stored page token."""
        page_token = getattr(self, '_changes_page_token', None)
        if not page_token:
            page_token = self._get_start_page_token(token)

        events: list[DocumentEvent] = []
        params: dict[str, Any] = {
            'pageToken': page_token,
            'fields': (
                'nextPageToken,newStartPageToken,'
                'changes(type,removed,file(id,name,mimeType,modifiedTime,size,webViewLink))'
            ),
            'pageSize': 100,
        }
        while True:
            resp = requests.get(f"{_DRIVE_BASE}/changes", params=params,
                                headers=self._auth_headers(token), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for change in data.get('changes', []):
                event = self._change_to_event(change)
                if event is not None:
                    events.append(event)
            if 'newStartPageToken' in data:
                self._changes_page_token = data['newStartPageToken']
                break
            next_token = data.get('nextPageToken')
            if not next_token:
                break
            params['pageToken'] = next_token

        if events:
            logger.info(f"[GoogleDrive] {len(events)} event(s)")
        return events

    def _change_to_event(self, change: dict[str, Any]) -> DocumentEvent | None:
        if change.get('type') != 'file':
            return None
        file_info = change.get('file') or {}
        name = file_info.get('name', '')
        mime_type = file_info.get('mimeType', '')
        if not self._is_watched(name, mime_type):
            return None
        source = self._item_to_source(file_info)
        if change.get('removed'):
            return DocumentEvent(EventType.DELETED, source)
        return DocumentEvent(EventType.MODIFIED, source)

    def _item_to_source(self, item: dict[str, Any]) -> DocumentSource:
        last_modified = None
        if mt := item.get('modifiedTime'):
            try:
                last_modified = datetime.fromisoformat(mt.replace('Z', '+00:00'))
            except Exception:
                pass

        mime_type = item.get('mimeType', '')
        name = item.get('name', '')
        # Append a synthetic extension so the ingest pipeline recognises the file type
        if mime_type in _WORKSPACE_EXT and not Path(name).suffix:
            name = name + _WORKSPACE_EXT[mime_type]

        return DocumentSource(
            source_id=item['id'],
            filename=name,
            last_modified=last_modified,
            size_bytes=int(item.get('size') or 0),
            metadata={'mime_type': mime_type, 'web_url': item.get('webViewLink', '')},
        )
