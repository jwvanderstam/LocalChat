# -*- coding: utf-8 -*-

"""
Memory Routes Blueprint
=======================

API endpoints for persistent conversation memory management.

Endpoints:
    GET    /api/conversations           - List all conversations
    POST   /api/conversations           - Create a new conversation
    GET    /api/conversations/<id>      - Get conversation with messages
    PATCH  /api/conversations/<id>      - Rename a conversation
    DELETE /api/conversations/<id>      - Delete a conversation

Author: LocalChat Team
Created: 2025-01-27
"""

from flask import Blueprint, jsonify, request
from flask import current_app as _current_app
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..types import LocalChatApp
    current_app: LocalChatApp
else:
    current_app = _current_app

from ..utils.logging_config import get_logger

bp = Blueprint('memory', __name__)
logger = get_logger(__name__)

_CONVERSATION_NOT_FOUND = 'Conversation not found'


@bp.route('/conversations', methods=['GET'])
def list_conversations():
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
    conversations = current_app.db.list_conversations()
    return jsonify({'conversations': conversations})


@bp.route('/conversations', methods=['POST'])
def create_conversation():
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
def get_conversation(conversation_id: str):
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


@bp.route('/conversations/<conversation_id>', methods=['PATCH'])
def update_conversation(conversation_id: str):
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
def delete_all_conversations():
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
def delete_conversation(conversation_id: str):
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
