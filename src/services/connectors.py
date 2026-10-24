"""Connectors and the OAuth accounts they spend: the use cases behind two route modules.

QP-4's sixth aggregate, and where CONN-1's authorisation model lives (ROADMAP CONN-1,
decided 2026-10-24). The route's ``deny()`` admits a workspace owner; the rules here are
what that guard cannot express:

* a connector spends only its creator's OAuth token, so ``user_id`` is refused in its
  config (BUG-4);
* a type whose config names something outside the workspace, a server path, is a global
  admin's decision, at creation and at every config change (audit C4);
* a config is validated by its own connector class before it is stored.

The admin check needs the request, so the route passes it in as ``require_admin``; it is
called at the point the route used to call it, so the order of refusals is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..utils.logging_config import get_logger
from ..utils.scope import Scope
from .errors import ServiceError

if TYPE_CHECKING:
    from ..connectors.base import BaseConnector
    from ..connectors.registry import ConnectorRegistry
    from ..db import Database

logger = get_logger(__name__)

# A connector spends its owner's OAuth token. Accepting the owner from client
# config would let any workspace owner name someone else's account (BUG-4), so
# the field is refused outright rather than silently overwritten.
_OWNER_IN_CONFIG = (
    "'user_id' may not be set in config; a connector uses the account of the user who created it"
)

# Connector types whose configuration names something outside the workspace — a
# server-side path — and so is a global decision, not a workspace owner's. Any
# user may create a workspace and become its owner, which is what made
# `local_folder` a way to read any file the server process can reach (audit C4).
ADMIN_ONLY_TYPES = frozenset({"local_folder"})

_PROVIDERS = ("google_drive", "microsoft", "onedrive")


class ConnectorsService:
    """Creating, changing, retiring and inspecting connectors over one database and registry."""

    def __init__(self, db: Database, registry: ConnectorRegistry) -> None:
        self._db = db
        self._registry = registry

    def available(self, user_id: str | None) -> list[dict[str, Any]]:
        """The providers *user_id* has authorised. Advisory: a failed probe is left out."""
        available = []
        for provider in _PROVIDERS:
            try:
                token = (
                    self._db.oauth_tokens.get(user_id or "", provider)
                    if user_id and self._db.is_connected
                    else None
                )
                if token:
                    available.append({"type": provider, "authorized": True})
            except Exception:  # noqa: BLE001 — availability is advisory; the list is returned with whatever could be determined
                logger.debug("Could not probe connector availability", exc_info=True)
        return available

    def types(self) -> list[str]:
        types: list[str] = self._registry.available_types()
        return types

    def list_all(self, scope: Scope) -> list[dict[str, Any]]:
        return self._db.connectors.list_all(scope=scope)

    def get(self, connector_id: str, scope: Scope) -> dict[str, Any] | None:
        return self._db.connectors.get(connector_id, scope=scope)

    def create(
        self,
        connector_type: str,
        display_name: str,
        config: dict[str, Any],
        sync_interval: int,
        workspace_id: str | None,
        *,
        require_admin: Callable[[], None],
        creator: Callable[[], str],
    ) -> dict[str, Any] | None:
        """Create, register and return the connector, or raise ``ServiceError``.

        *creator* returns the caller, who becomes ``created_by`` and the only account
        whose token the connector may spend.
        """
        if not connector_type:
            raise ServiceError(400, "connector_type is required")
        if connector_type not in self._registry.available_types():
            raise ServiceError(400, f"Unknown connector_type. Available: {self._registry.available_types()}")
        _refuse_owner_in(config)
        if connector_type in ADMIN_ONLY_TYPES:
            require_admin()
        created_by = creator()
        instance = self._validate(connector_type, config)
        if workspace_id is None:
            # A global admin passes the guard without naming a workspace. Refused here,
            # before the insert: a connector with no workspace was written and registered,
            # then its read-back refused the missing scope and the caller got a 500.
            raise ServiceError(400, "Select a workspace for the connector")
        if not display_name:
            display_name = instance.display_name
        connector_id = self._db.connectors.create(
            connector_type=connector_type,
            display_name=display_name,
            config=config,
            workspace_id=workspace_id,
            sync_interval=sync_interval,
            created_by=created_by,
        )
        self._registry.add(connector_id, connector_type, config,
                           workspace_id=workspace_id, owner_user_id=created_by)
        return self._db.connectors.get(connector_id, scope=workspace_id)

    def update(
        self,
        connector_id: str,
        fields: dict[str, Any],
        scope: Scope,
        *,
        require_admin: Callable[[], None],
    ) -> dict[str, Any] | None:
        """Apply *fields* and return the connector; None when *scope* has no such connector."""
        _refuse_owner_in(fields.get("config") or {})
        if "config" in fields:
            # A config change is a fresh configuration decision, so it faces the same
            # two checks creation does. Without this, an owner could repoint a
            # local_folder connector an admin had created — the whole of C4, through
            # the other door, since nothing here validated or re-authorised.
            existing = self._db.connectors.get(connector_id, scope=scope)
            if existing is None:
                return None
            connector_type = existing["connector_type"]
            if connector_type in ADMIN_ONLY_TYPES:
                require_admin()
            self._validate(connector_type, fields["config"])
        if not self._db.connectors.update(connector_id, scope=scope, **fields):
            return None
        if "config" in fields or "enabled" in fields:
            row = self._db.connectors.get(connector_id, scope=scope)
            if row and row.get("enabled"):
                self._registry.add(
                    connector_id, row["connector_type"], row["config"],
                    workspace_id=row.get("workspace_id"),
                    owner_user_id=row.get("created_by"),
                )
            else:
                self._registry.remove(connector_id)
        return self._db.connectors.get(connector_id, scope=scope)

    def retire(self, connector_id: str, actor: str | None, scope: Scope) -> bool:
        retired = self._db.connectors.retire(connector_id, deleted_by=_actor(actor), scope=scope)
        if retired:
            self._registry.remove(connector_id)
        return retired

    def purge(self, connector_id: str) -> bool:
        return self._db.connectors.purge(connector_id)

    def sync_history(self, connector_id: str, limit: int) -> list[dict[str, Any]]:
        return self._db.connectors.sync_history(connector_id, limit=limit)

    def _validate(self, connector_type: str, config: dict[str, Any]) -> BaseConnector:
        """The connector *config* builds, or a refusal unless its own class accepts it."""
        cls = self._registry.get_class(connector_type)
        if cls is None:
            raise ServiceError(400, f"Unknown connector_type. Available: {self._registry.available_types()}")
        try:
            instance = cls(config)
        except Exception as exc:  # noqa: BLE001 — instantiates a connector config class to validate it; construction can fail any number of ways
            logger.warning("Connector config instantiation failed: %s", exc)
            raise ServiceError(400, "Invalid connector configuration") from exc
        errors = instance.validate_config()
        if errors:
            raise ServiceError(400, "; ".join(errors))
        return instance


class OAuthAccountsService:
    """A user's connected OAuth accounts: store, inspect and remove their tokens."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def store(
        self,
        user_id: str,
        provider: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime,
        scopes: list[str],
    ) -> None:
        self._db.oauth_tokens.upsert(
            user_id=user_id,
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=scopes,
        )

    def status(self, user_id: str, provider: str) -> dict[str, Any]:
        token = self._db.oauth_tokens.get(user_id, provider)
        if not token:
            return {"connected": False}
        return {
            "connected": True,
            "expires_at": token.get("expires_at"),
            "expired": self._db.oauth_tokens.is_expired(user_id, provider),
            "scopes": token.get("scopes", []),
        }

    def disconnect(self, user_id: str, provider: str) -> bool:
        return self._db.oauth_tokens.delete(user_id, provider)


def _refuse_owner_in(config: dict[str, Any]) -> None:
    if "user_id" in config:
        raise ServiceError(400, _OWNER_IN_CONFIG)


def _actor(user_id: str | None) -> str | None:
    """The user to record, or None for no caller and for the RBAC bypass's "anonymous"."""
    return user_id if user_id and user_id != "anonymous" else None
