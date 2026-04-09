"""
Workspace Routes
================

CRUD and switch endpoints for workspace/persona management.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint('workspaces', __name__)


# ---------------------------------------------------------------------------
# List / Create
# ---------------------------------------------------------------------------

@bp.route('/api/workspaces', methods=['GET'])
def list_workspaces():
    """Return all workspaces with document and conversation counts."""
    try:
        workspaces = current_app.db.list_workspaces()
        active_id = config.app_state.get_active_workspace_id()
        for ws in workspaces:
            ws['active'] = ws['id'] == active_id
        return jsonify({'success': True, 'workspaces': workspaces})
    except Exception as e:
        logger.error(f"[Workspaces] list error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/workspaces', methods=['POST'])
def create_workspace():
    """Create a new workspace."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'name is required'}), 400
    try:
        workspace_id = current_app.db.create_workspace(
            name=name,
            description=data.get('description', ''),
            system_prompt=data.get('system_prompt', ''),
            model_class=data.get('model_class'),
        )
        workspace = current_app.db.get_workspace(workspace_id)
        return jsonify({'success': True, 'workspace': workspace}), 201
    except Exception as e:
        logger.error(f"[Workspaces] create error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# Get / Update / Delete
# ---------------------------------------------------------------------------

@bp.route('/api/workspaces/<workspace_id>', methods=['GET'])
def get_workspace(workspace_id: str):
    """Return a single workspace by ID."""
    try:
        workspace = current_app.db.get_workspace(workspace_id)
        if workspace is None:
            return jsonify({'success': False, 'message': 'Workspace not found'}), 404
        workspace['active'] = workspace_id == config.app_state.get_active_workspace_id()
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] get error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/workspaces/<workspace_id>', methods=['PUT'])
def update_workspace(workspace_id: str):
    """Update workspace fields (name, description, system_prompt, model_class)."""
    data = request.get_json(silent=True) or {}
    allowed = {'name', 'description', 'system_prompt', 'model_class'}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({'success': False, 'message': 'No valid fields provided'}), 400
    try:
        updated = current_app.db.update_workspace(workspace_id, **fields)
        if not updated:
            return jsonify({'success': False, 'message': 'Workspace not found'}), 404
        workspace = current_app.db.get_workspace(workspace_id)
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] update error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/workspaces/<workspace_id>', methods=['DELETE'])
def delete_workspace(workspace_id: str):
    """Delete a workspace. Clears the active workspace if it was the deleted one."""
    try:
        deleted = current_app.db.delete_workspace(workspace_id)
        if not deleted:
            return jsonify({'success': False, 'message': 'Workspace not found'}), 404
        if config.app_state.get_active_workspace_id() == workspace_id:
            # Fall back to the default workspace (or None = all docs)
            default_id = current_app.db.get_default_workspace_id()
            if default_id:
                config.app_state.set_active_workspace_id(default_id)
            else:
                config.app_state.state['active_workspace_id'] = None
                config.app_state._save_state()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"[Workspaces] delete error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# Switch / Active
# ---------------------------------------------------------------------------

@bp.route('/api/workspaces/active', methods=['GET'])
def get_active_workspace():
    """Return the currently active workspace (or null if none set)."""
    active_id = config.app_state.get_active_workspace_id()
    if not active_id:
        return jsonify({'success': True, 'workspace': None})
    try:
        workspace = current_app.db.get_workspace(active_id)
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] get active error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/workspaces/switch', methods=['POST'])
def switch_workspace():
    """Switch the active workspace.  POST body: {workspace_id: <uuid>}."""
    data = request.get_json(silent=True) or {}
    workspace_id = (data.get('workspace_id') or '').strip()
    if not workspace_id:
        return jsonify({'success': False, 'message': 'workspace_id is required'}), 400
    try:
        workspace = current_app.db.get_workspace(workspace_id)
        if workspace is None:
            return jsonify({'success': False, 'message': 'Workspace not found'}), 404
        config.app_state.set_active_workspace_id(workspace_id)
        logger.info(f"[Workspaces] Switched to workspace: {workspace['name']} ({workspace_id})")
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] switch error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500
