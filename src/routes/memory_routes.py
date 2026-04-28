
"""
Memory Routes Blueprint
=======================

API endpoints for persistent conversation memory management.

Endpoints:
    GET    /api/conversations                    - List all conversations
    POST   /api/conversations                    - Create a new conversation
    GET    /api/conversations/<id>               - Get conversation with messages
    GET    /api/conversations/<id>/export        - Export conversation (JSON or Markdown)
    GET    /api/conversations/<id>/documents     - Get document filter for a conversation
    PUT    /api/conversations/<id>/documents     - Set document filter for a conversation
    PATCH  /api/conversations/<id>               - Rename a conversation
    DELETE /api/conversations/<id>               - Delete a conversation

"""

import json
from typing import TYPE_CHECKING

from flask import Blueprint, Response, jsonify, request
from flask import current_app as _current_app
from flask.typing import ResponseReturnValue

if TYPE_CHECKING:
    from ..types import LocalChatApp
    current_app: LocalChatApp
else:
    current_app = _current_app

from .. import config
from ..utils.logging_config import get_logger

bp = Blueprint('memory', __name__)
logger = get_logger(__name__)

_CONVERSATION_NOT_FOUND = 'Conversation not found'


@bp.route('/conversations', methods=['GET'])
def list_conversations() -> ResponseReturnValue:
    """
    List all conversations.
    ---
    tags:
      - Memory
    summary: List conversations
    responses:
      200:
        description: List of conversations
      503:
        description: Database unavailable
    """
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        offset = max(int(request.args.get('offset', 0)), 0)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'limit and offset must be integers'}), 400
    workspace_id = config.app_state.get_active_workspace_id()
    conversations = current_app.db.list_conversations(limit=limit, offset=offset, workspace_id=workspace_id)
    return jsonify({'conversations': conversations, 'limit': limit, 'offset': offset})


@bp.route('/conversations', methods=['POST'])
def create_conversation() -> ResponseReturnValue:
    """
    Create a new conversation.
    ---
    tags:
      - Memory
    summary: Create conversation
    parameters:
      - name: body
        in: body
        schema:
          type: object
          properties:
            title:
              type: string
    responses:
      201:
        description: Conversation created
      503:
        description: Database unavailable
    """
    data = request.get_json() or {}
    title = str(data.get('title', 'New Conversation'))[:255].strip() or 'New Conversation'
    conversation_id = current_app.db.create_conversation(title)
    return jsonify({'id': conversation_id, 'title': title}), 201


@bp.route('/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id: str) -> ResponseReturnValue:
    """
    Get a conversation with all its messages.
    ---
    tags:
      - Memory
    summary: Get conversation
    parameters:
      - name: conversation_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Conversation messages
      404:
        description: Conversation not found
      503:
        description: Database unavailable
    """
    messages = current_app.db.get_conversation_messages(conversation_id)
    if messages is None:
        return jsonify({'error': _CONVERSATION_NOT_FOUND}), 404
    return jsonify({'id': conversation_id, 'messages': messages})


@bp.route('/conversations/<conversation_id>/export', methods=['GET'])
def export_conversation(conversation_id: str) -> ResponseReturnValue:
    """
    Export a conversation as JSON or Markdown.
    ---
    tags:
      - Memory
    summary: Export conversation
    parameters:
      - name: conversation_id
        in: path
        type: string
        required: true
      - name: format
        in: query
        type: string
        enum: [json, markdown]
        default: json
    responses:
      200:
        description: Conversation exported
      400:
        description: Invalid format parameter
      404:
        description: Conversation not found
      503:
        description: Database unavailable
    """
    fmt = request.args.get('format', 'json').lower()
    if fmt not in ('json', 'markdown'):
        return jsonify({'error': 'Invalid format. Use json or markdown.'}), 400

    messages = current_app.db.get_conversation_messages(conversation_id)
    if messages is None:
        return jsonify({'error': _CONVERSATION_NOT_FOUND}), 404

    if fmt == 'json':
        payload = {'id': conversation_id, 'messages': messages}
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename="conversation-{conversation_id}.json"'},
        )

    # Markdown export
    lines = [f'# Conversation {conversation_id}', '']
    for msg in messages:
        role_label = 'You' if msg['role'] == 'user' else 'Assistant'
        ts = msg.get('timestamp') or ''
        lines.append(f'### {role_label}{" — " + ts if ts else ""}')
        lines.append('')
        lines.append(msg['content'])
        lines.append('')
    return Response(
        '\n'.join(lines),
        mimetype='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="conversation-{conversation_id}.md"'},
    )


@bp.route('/conversations/<conversation_id>/documents', methods=['GET'])
def get_conversation_documents(conversation_id: str) -> ResponseReturnValue:
    """
    Get the document filter for a conversation.
    ---
    tags:
      - Memory
    summary: Get conversation document filter
    parameters:
      - name: conversation_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Document filter list
      404:
        description: Conversation not found
      503:
        description: Database unavailable
    """
    filenames = current_app.db.get_conversation_document_filter(conversation_id)
    if filenames is None:
        return jsonify({'error': _CONVERSATION_NOT_FOUND}), 404
    return jsonify({'conversation_id': conversation_id, 'document_filter': filenames})


@bp.route('/conversations/<conversation_id>/documents', methods=['PUT'])
def set_conversation_documents(conversation_id: str) -> ResponseReturnValue:
    """
    Set (or clear) the document filter for a conversation.
    ---
    tags:
      - Memory
    summary: Set conversation document filter
    parameters:
      - name: conversation_id
        in: path
        type: string
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            filenames:
              type: array
              items:
                type: string
              description: List of filenames to restrict retrieval to.
                Pass an empty array to clear the filter.
    responses:
      200:
        description: Document filter updated
      400:
        description: Invalid request body
      404:
        description: Conversation not found
      503:
        description: Database unavailable
    """
    data = request.get_json() or {}
    filenames = data.get('filenames')
    if not isinstance(filenames, list):
        return jsonify({'error': '"filenames" must be an array of strings'}), 400
    if not all(isinstance(f, str) for f in filenames):
        return jsonify({'error': '"filenames" must be an array of strings'}), 400

    updated = current_app.db.set_conversation_document_filter(conversation_id, filenames)
    if not updated:
        return jsonify({'error': _CONVERSATION_NOT_FOUND}), 404
    return jsonify({'conversation_id': conversation_id, 'document_filter': filenames})


@bp.route('/conversations/<conversation_id>', methods=['PATCH'])
def update_conversation(conversation_id: str) -> ResponseReturnValue:
    """
    Rename a conversation.
    ---
    tags:
      - Memory
    summary: Rename conversation
    parameters:
      - name: conversation_id
        in: path
        type: string
        required: true
      - name: body
        in: body
        schema:
          type: object
          required: [title]
          properties:
            title:
              type: string
    responses:
      200:
        description: Conversation renamed
      400:
        description: Title required
      404:
        description: Conversation not found
      503:
        description: Database unavailable
    """
    data = request.get_json() or {}
    title = str(data.get('title', '')).strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400

    updated = current_app.db.update_conversation_title(conversation_id, title)
    if not updated:
        return jsonify({'error': _CONVERSATION_NOT_FOUND}), 404
    return jsonify({'id': conversation_id, 'title': title})


@bp.route('/conversations', methods=['DELETE'])
def delete_all_conversations() -> ResponseReturnValue:
    """
    Delete all conversations and their messages.
    ---
    tags:
      - Memory
    summary: Delete all conversations
    responses:
      200:
        description: All conversations deleted
      503:
        description: Database unavailable
    """
    deleted = current_app.db.delete_all_conversations()
    return jsonify({'success': True, 'deleted': deleted})


@bp.route('/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id: str) -> ResponseReturnValue:
    """
    Delete a conversation and all its messages.
    ---
    tags:
      - Memory
    summary: Delete conversation
    parameters:
      - name: conversation_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Conversation deleted
      404:
        description: Conversation not found
      503:
        description: Database unavailable
    """
    deleted = current_app.db.delete_conversation(conversation_id)
    if not deleted:
        return jsonify({'error': _CONVERSATION_NOT_FOUND}), 404
    return jsonify({'success': True})
