"""R-5b (QP-9 review) — every use of ``ALL_WORKSPACES`` carries a reason.

``ALL_WORKSPACES`` is the one scope row-level security does not narrow, and both High
findings of the QP-9 review were paths that passed it where a workspace user could reach
them. This walks every directory whose code imports ``src`` — ``src/``, ``mcp_servers/``
and ``plugins/`` — and fails on a function that passes it without an entry below, and on
an entry whose function no longer does. A reason must hold for every caller who can reach
the function, not only for the one that prompted it.

A comparison (``scope is ALL_WORKSPACES``) is a branch on the scope, not a use of it, and
is not counted. ``scope.ALL_WORKSPACES`` is counted like the bare name, and importing it
under another name fails outright, since the walk could not follow it.

The entries pin the function, not who calls it: a new route reaching an admin-only
function is caught by its guard's tests and the permission matrix, not here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
#: plugins/ is absent in the core-without-plugins job, and walking nothing is right there.
_WALKED = ("src", "mcp_servers", "plugins")

_NO_WORKSPACE_YET = (
    "the row names its own workspace; ALL_WORKSPACES only when it has none, a row no "
    "scoped transaction admits"
)
_ADMIN_PURGE = "reached only from an admin-only purge route"
_MCP_LIST = (
    "an MCP tool behind the MCP_AUTH_TOKEN bearer, installation-wide by design; the "
    "application never calls it"
)
_SYNC_WORKER = "called only by the SyncWorker, with the id of a connector it loaded itself"

#: ``module:function`` -> why an installation-wide scope is right for every caller.
REASONS: dict[str, str] = {
    # Boot and background work: no request, so no caller to scope by.
    "src/app_bootstrap.py:_init_database_service": "boot-time log of the installation's document total",
    "src/connectors/registry.py:ConnectorRegistry.load_from_db":
        "boot loads every enabled connector; each then syncs into its own workspace",
    "src/connectors/worker.py:SyncWorker._reingest_loop":
        "the worker re-ingests stale documents of every workspace, each into its own",
    "src/db/connectors.py:ConnectorsRepository.interval": _SYNC_WORKER,
    "src/db/connectors.py:ConnectorsRepository.set_sync_status": _SYNC_WORKER,
    "src/db/documents.py:DocumentsRepository.mark_ingested":
        "SyncWorker bookkeeping, by the id of the document it has just re-ingested",
    "src/db/feedback.py:FeedbackRepository.export_pairs":
        "training data for the reranker, which is installation-wide; reached from the "
        "weekly job and the admin-only retrain",
    # A row that names its own workspace.
    "src/db/connectors.py:ConnectorsRepository.create": _NO_WORKSPACE_YET,
    "src/db/conversations.py:ConversationsRepository.create": _NO_WORKSPACE_YET,
    "src/db/conversations.py:ConversationsRepository.create_with_message": _NO_WORKSPACE_YET,
    "src/db/memories.py:MemoriesRepository.insert": _NO_WORKSPACE_YET,
    "src/rag/processor.py:DocumentProcessor.ingest_document": _NO_WORKSPACE_YET,
    "src/db/documents.py:DocumentsRepository.exists":
        "with no workspace it matches only documents without one (IS NOT DISTINCT FROM)",
    "src/memory/extractor.py:MemoryExtractor._try_persist_memory_item":
        "a memory with no workspace dedupes against all; the answer is a yes or no",
    "src/db/workspaces.py:WorkspacesRepository.create":
        "a new workspace has no scope yet; its creator becomes owner in the same transaction",
    # Ids the caller already obtained, or proved, in its own scope.
    "src/db/feedback.py:FeedbackRepository.insert":
        "the conversation, message and chunk ids were looked up in the caller's scope first "
        "(R-8); correct_doc_ids is stored unchecked, and nothing reads it",
    "src/db/memories.py:MemoriesRepository.record_use": "the ids a scoped memory search just returned",
    "src/db/memories.py:MemoriesRepository.mark_extracted":
        "the id of a conversation the extraction batch read in its own scope",
    "src/db/workspace_keys.py:WorkspaceKeysRepository._touch": "the id `resolve` has just matched",
    "src/db/contributions.py:ContributionsRepository.archive":
        "withdraws only rows whose source_project_id is the workspace the route's "
        "ws:owner guard admitted; those rows have no workspace_id, being global",
    # Authentication and authorisation: they establish the scope, so none exists yet.
    "src/db/workspace_keys.py:WorkspaceKeysRepository.resolve":
        "finding a key's workspace is the point; the hash comparison is constant-time",
    "src/db/workspaces.py:WorkspaceMembersRepository.role": "the authorisation check itself",
    "src/db/workspaces.py:WorkspaceMembersRepository.for_user":
        "a caller's own memberships, read by the guard and the workspace switcher; any "
        "user's only through the admin-only user management",
    "src/security_fastapi.py:check_workspace_access":
        "an admin, by the database's role, who names no workspace acts installation-wide",
    "src/routes_fastapi/connector_routes.py:receive_webhook":
        "a public receiver; the connector id plus its mandatory secret is the credential",
    # Membership changes, after the route authorised the workspace.
    "src/db/workspaces.py:WorkspaceMembersRepository.add":
        "the route admitted a global admin or the workspace's owner first",
    "src/db/workspaces.py:WorkspaceMembersRepository.remove":
        "the route admitted a global admin or the workspace's owner first",
    # Global-admin only.
    "src/db/connectors.py:ConnectorsRepository.purge": _ADMIN_PURGE,
    "src/db/conversations.py:ConversationsRepository.purge": _ADMIN_PURGE,
    "src/db/documents.py:DocumentsRepository.purge": _ADMIN_PURGE,
    "src/db/users.py:UsersRepository.purge": _ADMIN_PURGE,
    "src/db/workspaces.py:WorkspacesRepository.purge": _ADMIN_PURGE,
    "src/db/documents.py:DocumentsRepository.purge_all":
        "admin-only, and touches only documents already retired",
    "src/db/users.py:UsersRepository.list_all": "the admin-only user list",
    "src/db/workspaces.py:WorkspacesRepository.list_all":
        "every workspace, shown only to a global admin by the database's role",
    "src/db/feedback.py:FeedbackRepository.stats": "GET /api/feedback/stats, admin-only",
    "src/db/feedback.py:FeedbackRepository.trend": "GET /api/feedback/stats, admin-only",
    "src/db/feedback.py:FeedbackRepository.stale_chunks": "GET /api/feedback/stats, admin-only",
    "src/db/contributions.py:ContributionsRepository.contribute":
        "the global tier belongs to no workspace; contributing needs a global admin (GKB-2)",
    "src/db/contributions.py:ContributionsRepository.list_all":
        "GET /api/gkb/documents, admin-only",
    "src/services/admin_stats.py:_collect_document_stats":
        "admin statistics, gathered only for a caller the database says is an admin (R-6)",
    # Errs toward the safe answer.
    "src/db/documents.py:DocumentsRepository.any_local_only_sources":
        "a yes or no that can only block the cloud fallback, never allow it; a namesake in "
        "another workspace can block it, one bit that errs safe",
    "mcp_servers/cloud_connectors/server.py:list_sources": _MCP_LIST,
    "mcp_servers/local_docs/server.py:list_sources": _MCP_LIST,
}


def _modules() -> list[tuple[str, ast.Module]]:
    found = []
    for top in _WALKED:
        for path in sorted((_ROOT / top).rglob("*.py")):
            module = path.relative_to(_ROOT).as_posix()
            if module != "src/utils/scope.py":
                found.append((module, ast.parse(path.read_text(encoding="utf-8"))))
    return found


def _is_the_scope(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "ALL_WORKSPACES") or (
        isinstance(node, ast.Attribute) and node.attr == "ALL_WORKSPACES")


def _uses() -> set[str]:
    """``module:function`` for every function that passes ALL_WORKSPACES as a value."""
    found: set[str] = set()
    for module, tree in _modules():
        compared = {
            id(node)
            for cmp in ast.walk(tree) if isinstance(cmp, ast.Compare)
            and all(isinstance(op, (ast.Is, ast.IsNot)) for op in cmp.ops)
            for node in [cmp.left, *cmp.comparators]
        }

        def visit(node: ast.AST, qualname: list[str], module: str = module, compared: set[int] = compared) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(child, [*qualname, child.name])
                    continue
                if _is_the_scope(child) and id(child) not in compared:
                    found.add(f"{module}:{'.'.join(qualname) or '<module>'}")
                visit(child, qualname)

        visit(tree, [])
    return found


def test_every_use_of_all_workspaces_has_a_reason():
    assert sorted(_uses() - REASONS.keys()) == []


def test_no_reason_outlives_its_use():
    """A function that stopped passing ALL_WORKSPACES takes its entry with it."""
    assert sorted(REASONS.keys() - _uses()) == []


def test_it_is_never_imported_under_another_name():
    """`import ALL_WORKSPACES as X` would hide every use of X from the walk above."""
    renamed = [
        module
        for module, tree in _modules()
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names if alias.name == "ALL_WORKSPACES" and alias.asname
    ]
    assert renamed == []


def test_a_comparison_is_not_counted_as_a_use():
    """`scope is ALL_WORKSPACES` in get_connection is a branch, and has no entry."""
    assert "src/db/connection.py:DatabaseConnection.get_connection" not in _uses()
