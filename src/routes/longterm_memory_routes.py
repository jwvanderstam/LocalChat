"""
Long-Term Memory Routes
=======================

Endpoints for managing and triggering the long-term memory store.

Registered at: /api/memory/
"""

from flask import Blueprint, jsonify, request
from flask import current_app as _current_app
from flask.typing import ResponseReturnValue

from .. import config
from ..utils.logging_config import get_logger

bp = Blueprint('longterm_memory', __name__)
logger = get_logger(__name__)

_ERR_INTERNAL = 'Internal server error'


@bp.route('/', methods=['GET'])
def list_memories() -> ResponseReturnValue:
    """Return all stored memories (paginated)."""
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
        offset = max(int(request.args.get('offset', 0)), 0)
        memories = _current_app.db.get_all_memories(limit=limit, offset=offset)
        return jsonify({'success': True, 'memories': memories, 'count': len(memories)})
    except Exception:
        logger.error("[Memory] list_memories error", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/extract', methods=['POST'])
def extract_memories() -> ResponseReturnValue:
    """
    Trigger memory extraction from unprocessed conversations.

    Optional JSON body: { "limit": 10 }
    """
    try:
        body = request.get_json(silent=True) or {}
        limit = min(int(body.get('limit', 10)), 50)

        if not _current_app.startup_status.get('database', False):
            return jsonify({'success': False, 'message': 'Database not available'}), 503

        active_model = config.app_state.get_active_model()
        if not active_model:
            return jsonify({'success': False, 'message': 'No active model'}), 400

        from ..memory.extractor import MemoryExtractor
        extractor = MemoryExtractor()

        conversations = _current_app.db.get_unextracted_conversations(limit=limit)
        total_new = 0
        processed = 0

        for conv in conversations:
            try:
                messages = _current_app.db.get_conversation_messages(conv['id'])
                # get_conversation_messages returns a list of (role, content, ...) or dicts
                # normalise to list[dict[str,str]]
                msg_list = []
                for m in messages:
                    if isinstance(m, dict):
                        msg_list.append({'role': m.get('role', ''), 'content': m.get('content', '')})
                    elif isinstance(m, (list, tuple)) and len(m) >= 2:
                        msg_list.append({'role': m[0], 'content': m[1]})

                new = extractor.extract(
                    conversation_id=conv['id'],
                    messages=msg_list,
                    model=active_model,
                    ollama_client=_current_app.ollama_client,
                    db=_current_app.db,
                )
                total_new += new
                processed += 1
            except Exception:
                logger.warning("[Memory] Extraction failed for conv %s", conv['id'], exc_info=True)

        return jsonify({
            'success': True,
            'conversations_processed': processed,
            'new_memories': total_new,
        })
    except Exception:
        logger.error("[Memory] extract_memories error", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/<memory_id>', methods=['DELETE'])
def delete_memory(memory_id: str) -> ResponseReturnValue:
    """Delete a single memory by UUID."""
    try:
        _current_app.db.delete_memory(memory_id)
        return jsonify({'success': True})
    except Exception:
        logger.error("[Memory] delete_memory error", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.route('/', methods=['DELETE'])
def delete_all_memories() -> ResponseReturnValue:
    """Delete all stored memories."""
    try:
        count = _current_app.db.delete_all_memories()
        return jsonify({'success': True, 'deleted': count})
    except Exception:
        logger.error("[Memory] delete_all_memories error", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500
