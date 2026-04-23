"""
Connector Routes
================

REST API for managing live-sync connectors and receiving webhook events.

Endpoints:
    GET  /api/connectors                         list all connectors
    POST /api/connectors                         create a connector
    GET  /api/connectors/<id>                    get one connector
    PUT  /api/connectors/<id>                    update connector
    DELETE /api/connectors/<id>                  delete connector
    POST /api/connectors/<id>/sync               trigger an immediate sync
    GET  /api/connectors/<id>/history            sync log history
    POST /api/connectors/<id>/webhook            receive a push event
    GET  /api/connectors/types                   list available connector types
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from .. import config
from ..connectors.registry import connector_registry
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint('connectors', __name__)

_ERR_INTERNAL = 'Internal server error'


# ---------------------------------------------------------------------------
# Types
_NOT_FOUND = 'Connector not found'

# ---------------------------------------------------------------------------

@bp.route('/api/connectors/types', methods=['GET'])
def list_connector_types():
    """
    List available connector types.
    ---
    tags:
      - Connectors
    summary: List connector types
    responses:
      200:
        description: List of supported connector type strings
    """
    return jsonify({'success': True, 'types': connector_registry.available_types()})


# ---------------------------------------------------------------------------
# List / Create
# ---------------------------------------------------------------------------

@bp.route('/api/connectors', methods=['GET'])
def list_connectors():
    """
    List connectors.
    ---
    tags:
      - Connectors
    summary: List connectors for the active workspace
    responses:
      200:
        description: List of connector objects
    """
    workspace_id = config.app_state.get_active_workspace_id()
    try:
        connectors = current_app.db.list_connectors(workspace_id=workspace_id)
        return jsonify({'success': True, 'connectors': connectors})
    except Exception as e:
        logger.error(f"[Connectors] list error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/connectors', methods=['POST'])
def create_connector():
    """
    Create a connector.
    ---
    tags:
      - Connectors
    summary: Create and register a new connector
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [connector_type]
          properties:
            connector_type: {type: string, enum: [local_folder, s3, webhook]}
            display_name:   {type: string}
            config:         {type: object}
            sync_interval:  {type: integer, description: Seconds between polls (default 900)}
    responses:
      201:
        description: Connector created
      400:
        description: Invalid connector_type or config validation error
    """
    data = request.get_json(silent=True) or {}
    connector_type = (data.get('connector_type') or '').strip()
    display_name = (data.get('display_name') or '').strip()
    connector_config = data.get('config') or {}
    sync_interval = int(data.get('sync_interval') or 900)

    if not connector_type:
        return jsonify({'success': False, 'message': 'connector_type is required'}), 400
    if connector_type not in connector_registry.available_types():
        return jsonify({
            'success': False,
            'message': f"Unknown connector_type. Available: {connector_registry.available_types()}",
        }), 400

    workspace_id = config.app_state.get_active_workspace_id()

    # Validate config before persisting
    cls = connector_registry.get_class(connector_type)
    try:
        tmp_instance = cls(connector_config)
    except Exception as exc:
        logger.warning("Connector config instantiation failed: %s", exc)
        return jsonify({'success': False, 'message': 'Invalid connector configuration'}), 400
    errors = tmp_instance.validate_config()
    if errors:
        return jsonify({'success': False, 'message': '; '.join(errors)}), 400

    if not display_name:
        display_name = tmp_instance.display_name

    try:
        connector_id = current_app.db.create_connector(
            connector_type=connector_type,
            display_name=display_name,
            config=connector_config,
            workspace_id=workspace_id,
            sync_interval=sync_interval,
        )
        connector_registry.add(
            connector_id, connector_type, connector_config, workspace_id=workspace_id
        )
        connector = current_app.db.get_connector(connector_id)
        return jsonify({'success': True, 'connector': connector}), 201
    except Exception as e:
        logger.error(f"[Connectors] create error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


# ---------------------------------------------------------------------------
# Get / Update / Delete
# ---------------------------------------------------------------------------

@bp.route('/api/connectors/<connector_id>', methods=['GET'])
def get_connector(connector_id: str):
    try:
        connector = current_app.db.get_connector(connector_id)
        if connector is None:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        return jsonify({'success': True, 'connector': connector})
    except Exception as e:
        logger.error(f"[Connectors] get error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/connectors/<connector_id>', methods=['PUT'])
def update_connector(connector_id: str):
    """Update connector fields (display_name, config, enabled, sync_interval)."""
    data = request.get_json(silent=True) or {}
    allowed = {'display_name', 'config', 'enabled', 'sync_interval'}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({'success': False, 'message': 'No valid fields provided'}), 400
    try:
        updated = current_app.db.update_connector(connector_id, **fields)
        if not updated:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        # Reload the live instance if config changed
        if 'config' in fields or 'enabled' in fields:
            row = current_app.db.get_connector(connector_id)
            if row and row.get('enabled'):
                connector_registry.add(
                    connector_id, row['connector_type'], row['config'],
                    workspace_id=row.get('workspace_id'),
                )
            else:
                connector_registry.remove(connector_id)
        connector = current_app.db.get_connector(connector_id)
        return jsonify({'success': True, 'connector': connector})
    except Exception as e:
        logger.error(f"[Connectors] update error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/api/connectors/<connector_id>', methods=['DELETE'])
def delete_connector(connector_id: str):
    try:
        deleted = current_app.db.delete_connector(connector_id)
        if not deleted:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        connector_registry.remove(connector_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"[Connectors] delete error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


# ---------------------------------------------------------------------------
# Sync trigger
# ---------------------------------------------------------------------------

@bp.route('/api/connectors/<connector_id>/sync', methods=['POST'])
def trigger_sync(connector_id: str):
    """Trigger an immediate sync for one connector (runs in background thread)."""
    import threading

    connector_instance = connector_registry.get(connector_id)
    if connector_instance is None:
        return jsonify({'success': False, 'message': 'Connector not found or not loaded'}), 404

    sync_worker = getattr(current_app, 'sync_worker', None)
    if sync_worker is None:
        return jsonify({'success': False, 'message': 'Sync worker not running'}), 503

    def _run():
        sync_worker._sync_one(connector_instance)

    threading.Thread(target=_run, daemon=True, name=f"manual-sync-{connector_id[:8]}").start()
    return jsonify({'success': True, 'message': 'Sync triggered'})


# ---------------------------------------------------------------------------
# Sync history
# ---------------------------------------------------------------------------

@bp.route('/api/connectors/<connector_id>/history', methods=['GET'])
def sync_history(connector_id: str):
    limit = min(int(request.args.get('limit', 20)), 100)
    try:
        history = current_app.db.get_connector_sync_history(connector_id, limit=limit)
        return jsonify({'success': True, 'history': history})
    except Exception as e:
        logger.error(f"[Connectors] history error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------

@bp.route('/api/connectors/<connector_id>/webhook', methods=['POST'])
def receive_webhook(connector_id: str):
    """
    Receive a webhook push event.
    ---
    tags:
      - Connectors
    summary: Receive document push event
    parameters:
      - in: path
        name: connector_id
        type: string
        required: true
      - in: header
        name: X-LocalChat-Secret
        type: string
        description: Shared secret (required when connector.config.secret is set)
      - in: body
        name: body
        schema:
          type: object
          required: [event_type, source_id]
          properties:
            event_type:   {type: string, enum: [added, modified, deleted]}
            source_id:    {type: string}
            filename:     {type: string}
            fetch_url:    {type: string, description: Required for added/modified}
            content_type: {type: string}
            metadata:     {type: object}
    responses:
      200:
        description: Event queued
      400:
        description: Payload validation error
      403:
        description: Bad secret
      404:
        description: Connector not found
      503:
        description: Connector not active
    """
    # Validate shared secret if configured
    connector = current_app.db.get_connector(connector_id)
    if connector is None:
        return jsonify({'success': False, 'message': _NOT_FOUND}), 404
    if connector.get('connector_type') != 'webhook':
        return jsonify({'success': False, 'message': 'Not a webhook connector'}), 400

    secret = connector.get('config', {}).get('secret')
    if secret:
        provided = request.headers.get('X-LocalChat-Secret', '')
        if provided != secret:
            logger.warning("[Webhook] Bad secret for connector")
            return jsonify({'success': False, 'message': 'Forbidden'}), 403

    instance = connector_registry.get(connector_id)
    if instance is None:
        return jsonify({'success': False, 'message': 'Connector not active'}), 503

    payload = request.get_json(silent=True) or {}
    errors = instance.push_event(payload)
    if errors:
        return jsonify({'success': False, 'message': '; '.join(errors)}), 400

    return jsonify({'success': True, 'message': 'Event queued'})
