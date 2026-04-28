"""
Workspace Routes
================

CRUD and switch endpoints for workspace/persona management.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint('workspaces', __name__)


_NOT_FOUND = 'Workspace not found'
_ERR_INTERNAL = 'Internal server error'

# ---------------------------------------------------------------------------
# List / Create
# ---------------------------------------------------------------------------

@bp.route('/api/workspaces', methods=['GET'])
def list_workspaces() -> ResponseReturnValue:
    """
    List all workspaces.
    ---
    tags:
      - Workspaces
    summary: List workspaces
    responses:
      200:
        description: List of workspaces with document and conversation counts
    """
    try:
        workspaces = current_app.db.list_workspaces()
        active_id = config.app_state.get_active_workspace_id()
        for ws in workspaces:
            ws['active'] = ws['id'] == active_id
        return jsonify({'success': True, 'workspaces': workspaces})
    except Exception as e:
        logger.error(f"[Workspaces] list error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/workspaces', methods=['POST'])
def create_workspace() -> ResponseReturnValue:
    """
    Create a workspace.
    ---
    tags:
      - Workspaces
    summary: Create workspace
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [name]
          properties:
            name:        {type: string}
            description: {type: string}
            system_prompt: {type: string}
            model_class: {type: string}
    responses:
      201:
        description: Workspace created
      400:
        description: name is required
    """
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
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


# ---------------------------------------------------------------------------
# Get / Update / Delete
# ---------------------------------------------------------------------------

@bp.route('/api/workspaces/<workspace_id>', methods=['GET'])
def get_workspace(workspace_id: str) -> ResponseReturnValue:
    """
    Get a workspace.
    ---
    tags:
      - Workspaces
    summary: Get workspace by ID
    parameters:
      - in: path
        name: workspace_id
        type: string
        required: true
    responses:
      200:
        description: Workspace object
      404:
        description: Not found
    """
    try:
        workspace = current_app.db.get_workspace(workspace_id)
        if workspace is None:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        workspace['active'] = workspace_id == config.app_state.get_active_workspace_id()
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] get error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/workspaces/<workspace_id>', methods=['PUT'])
def update_workspace(workspace_id: str) -> ResponseReturnValue:
    """
    Update a workspace.
    ---
    tags:
      - Workspaces
    summary: Update workspace fields
    parameters:
      - in: path
        name: workspace_id
        type: string
        required: true
      - in: body
        name: body
        schema:
          type: object
          properties:
            name:          {type: string}
            description:   {type: string}
            system_prompt: {type: string}
            model_class:   {type: string}
    responses:
      200:
        description: Updated workspace
      400:
        description: No valid fields provided
      404:
        description: Not found
    """
    data = request.get_json(silent=True) or {}
    allowed = {'name', 'description', 'system_prompt', 'model_class'}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({'success': False, 'message': 'No valid fields provided'}), 400
    try:
        updated = current_app.db.update_workspace(workspace_id, **fields)
        if not updated:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        workspace = current_app.db.get_workspace(workspace_id)
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] update error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/workspaces/<workspace_id>', methods=['DELETE'])
def delete_workspace(workspace_id: str) -> ResponseReturnValue:
    """
    Delete a workspace.
    ---
    tags:
      - Workspaces
    summary: Delete workspace
    parameters:
      - in: path
        name: workspace_id
        type: string
        required: true
    responses:
      200:
        description: Deleted
      404:
        description: Not found
    """
    try:
        deleted = current_app.db.delete_workspace(workspace_id)
        if not deleted:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
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
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


# ---------------------------------------------------------------------------
# Switch / Active
# ---------------------------------------------------------------------------

@bp.route('/api/workspaces/active', methods=['GET'])
def get_active_workspace() -> ResponseReturnValue:
    """
    Get the active workspace.
    ---
    tags:
      - Workspaces
    summary: Get active workspace
    responses:
      200:
        description: Active workspace object, or null
    """
    active_id = config.app_state.get_active_workspace_id()
    if not active_id:
        return jsonify({'success': True, 'workspace': None})
    try:
        workspace = current_app.db.get_workspace(active_id)
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] get active error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

@bp.route('/api/workspaces/<workspace_id>/members', methods=['GET'])
def list_workspace_members(workspace_id: str) -> ResponseReturnValue:
    """List members of a workspace."""
    try:
        members = current_app.db.list_workspace_members(workspace_id)
        return jsonify({'success': True, 'members': members})
    except Exception as e:
        logger.error(f"[Workspaces] list members error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/workspaces/<workspace_id>/members', methods=['POST'])
def add_workspace_member(workspace_id: str) -> ResponseReturnValue:
    """
    Add or update a member's role in a workspace.
    ---
    tags: [Workspaces]
    parameters:
      - {in: path, name: workspace_id, type: string, required: true}
      - in: body
        name: body
        schema:
          type: object
          required: [user_id]
          properties:
            user_id: {type: string}
            role:    {type: string, enum: [viewer, editor, owner], default: viewer}
    responses:
      200: {description: Member added}
      400: {description: user_id required}
    """
    data = request.get_json(silent=True) or {}
    user_id = (data.get('user_id') or '').strip()
    role = data.get('role', 'viewer')
    if not user_id:
        return jsonify({'success': False, 'message': 'user_id is required'}), 400
    if role not in ('viewer', 'editor', 'owner'):
        return jsonify({'success': False, 'message': "role must be viewer, editor, or owner"}), 400
    try:
        current_app.db.add_workspace_member(workspace_id, user_id, role)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"[Workspaces] add member error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/workspaces/<workspace_id>/members/<user_id>', methods=['PUT'])
def update_workspace_member(workspace_id: str, user_id: str) -> ResponseReturnValue:
    """Change a member's role."""
    data = request.get_json(silent=True) or {}
    role = data.get('role', '')
    if role not in ('viewer', 'editor', 'owner'):
        return jsonify({'success': False, 'message': "role must be viewer, editor, or owner"}), 400
    try:
        current_app.db.add_workspace_member(workspace_id, user_id, role)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"[Workspaces] update member error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/workspaces/<workspace_id>/members/<user_id>', methods=['DELETE'])
def remove_workspace_member(workspace_id: str, user_id: str) -> ResponseReturnValue:
    """Remove a member from a workspace."""
    try:
        removed = current_app.db.remove_workspace_member(workspace_id, user_id)
        if not removed:
            return jsonify({'success': False, 'message': 'Member not found'}), 404
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"[Workspaces] remove member error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/workspaces/switch', methods=['POST'])
def switch_workspace() -> ResponseReturnValue:
    """
    Switch the active workspace.
    ---
    tags:
      - Workspaces
    summary: Switch active workspace
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [workspace_id]
          properties:
            workspace_id: {type: string}
    responses:
      200:
        description: Switched to workspace
      400:
        description: workspace_id is required
      404:
        description: Not found
    """
    data = request.get_json(silent=True) or {}
    workspace_id = (data.get('workspace_id') or '').strip()
    if not workspace_id:
        return jsonify({'success': False, 'message': 'workspace_id is required'}), 400
    try:
        workspace = current_app.db.get_workspace(workspace_id)
        if workspace is None:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        config.app_state.set_active_workspace_id(workspace_id)
        from ..utils.logging_config import sanitize_log_value as _slv
        logger.info("[Workspaces] Switched to workspace: %s (%s)", _slv(workspace['name']), _slv(workspace_id))
        return jsonify({'success': True, 'workspace': workspace})
    except Exception as e:
        logger.error(f"[Workspaces] switch error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500
