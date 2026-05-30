"""
Confluence Connector
====================

Ingests pages from Confluence Cloud using the REST API v1 with API token auth.
Polls for changes via CQL ``lastModified`` queries on subsequent syncs.

Config keys:
    space_key  (optional)  Confluence space key to restrict ingestion (default: all spaces)

Requires env vars: CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN.
"""
from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from typing import Any

import requests

from .. import config as app_config
from ..utils.logging_config import get_logger
from .base import BaseConnector, DocumentEvent, DocumentSource, EventType

logger = get_logger(__name__)


def _html_to_text(html: str) -> str:
    """Convert Confluence storage-format HTML to plain text."""
    try:
        import html2text as _h2t
        h = _h2t.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.body_width = 0
        return h.handle(html)
    except ImportError:
        return re.sub(r'<[^>]+>', ' ', html)


def _safe_filename(title: str, space_key: str) -> str:
    prefix = f"{space_key}_" if space_key else ""
    safe = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in title)
    return f"{prefix}{safe}.txt"


class ConfluenceConnector(BaseConnector):
    """Syncs pages from Confluence Cloud via REST API with Basic/API-token auth."""

    @property
    def connector_type(self) -> str:
        return "confluence"

    @property
    def display_name(self) -> str:
        space = self.config.get('space_key', '')
        base = app_config.CONFLUENCE_URL or 'Confluence'
        return f"Confluence: {space or 'all spaces'} @ {base}"

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not app_config.CONFLUENCE_URL:
            errors.append("CONFLUENCE_URL environment variable is not set")
        if not app_config.CONFLUENCE_EMAIL:
            errors.append("CONFLUENCE_EMAIL environment variable is not set")
        if not app_config.CONFLUENCE_API_TOKEN:
            errors.append("CONFLUENCE_API_TOKEN environment variable is not set")
        return errors

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def list_sources(self) -> list[DocumentSource]:
        try:
            return self._list_pages()
        except Exception:
            logger.exception("[Confluence] list_sources failed")
            return []

    def poll(self) -> list[DocumentEvent]:
        try:
            return self._poll_changes()
        except Exception:
            logger.exception("[Confluence] poll failed")
            return []

    def fetch(self, source: DocumentSource) -> bytes:
        url = f"{self._base_url()}/content/{source.source_id}"
        resp = requests.get(url, headers=self._auth_headers(),
                            params={'expand': 'body.storage'}, timeout=30)
        resp.raise_for_status()
        html = resp.json().get('body', {}).get('storage', {}).get('value', '')
        return _html_to_text(html).encode('utf-8')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_url(self) -> str:
        return (app_config.CONFLUENCE_URL or '').rstrip('/') + '/wiki/rest/api'

    def _auth_headers(self) -> dict[str, str]:
        creds = f"{app_config.CONFLUENCE_EMAIL}:{app_config.CONFLUENCE_API_TOKEN}"
        encoded = base64.b64encode(creds.encode()).decode()
        return {'Authorization': f'Basic {encoded}', 'Accept': 'application/json'}

    def _list_pages(self) -> list[DocumentSource]:
        """Enumerate all pages in the configured space (or all spaces)."""
        sources: list[DocumentSource] = []
        space_key = self.config.get('space_key', '')
        params: dict[str, Any] = {
            'type': 'page',
            'expand': 'version,space',
            'limit': 50,
            'start': 0,
        }
        if space_key:
            params['spaceKey'] = space_key

        while True:
            resp = requests.get(f"{self._base_url()}/content",
                                params=params, headers=self._auth_headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for page in data.get('results', []):
                sources.append(self._page_to_source(page))
            if len(data.get('results', [])) < params['limit']:
                break
            params['start'] += params['limit']
        return sources

    def _poll_changes(self) -> list[DocumentEvent]:
        """Return pages modified since the last poll timestamp."""
        last_poll: datetime | None = getattr(self, '_last_poll_at', None)
        now = datetime.now(UTC)
        events: list[DocumentEvent] = []

        if last_poll is None:
            for source in self._list_pages():
                events.append(DocumentEvent(EventType.ADDED, source))
        else:
            ts = last_poll.strftime('%Y-%m-%d %H:%M')
            space_key = self.config.get('space_key', '')
            cql = f'lastModified > "{ts}" AND type = "page"'
            if space_key:
                cql += f' AND space = "{space_key}"'
            params: dict[str, Any] = {
                'cql': cql,
                'expand': 'version,space',
                'limit': 50,
                'start': 0,
            }
            while True:
                resp = requests.get(f"{self._base_url()}/content/search",
                                    params=params, headers=self._auth_headers(), timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for page in data.get('results', []):
                    events.append(DocumentEvent(EventType.MODIFIED, self._page_to_source(page)))
                if len(data.get('results', [])) < params['limit']:
                    break
                params['start'] += params['limit']

        self._last_poll_at = now
        if events:
            logger.info(f"[Confluence] {len(events)} event(s)")
        return events

    def _page_to_source(self, page: dict[str, Any]) -> DocumentSource:
        title = page.get('title', 'Untitled')
        space_key = page.get('space', {}).get('key', '')
        filename = _safe_filename(title, space_key)

        last_modified = None
        when = page.get('version', {}).get('when')
        if when:
            try:
                last_modified = datetime.fromisoformat(when.replace('Z', '+00:00'))
            except Exception:
                pass

        base = (app_config.CONFLUENCE_URL or '').rstrip('/')
        web_url = base + '/wiki' + page.get('_links', {}).get('webui', '')
        return DocumentSource(
            source_id=page['id'],
            filename=filename,
            last_modified=last_modified,
            metadata={'web_url': web_url, 'space_key': space_key, 'title': title},
        )
