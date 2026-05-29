"""
Annotation Routes
=================

CRUD endpoints for chunk annotations.

Endpoints:
    POST   /api/annotations                    create annotation on a chunk
    GET    /api/chunks/<chunk_id>/annotations  list annotations for a chunk
    DELETE /api/annotations/<id>               delete an annotation
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from ..security import get_current_user_id
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint('annotations', __name__)

_ERR_INTERNAL = 'Internal server error'


@bp.post('/annotations')
def create_annotation() -> ResponseReturnValue:
    """
    Create an annotation on a document chunk.
    ---
    tags: [Annotations]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [chunk_id, text]
          properties:
            chunk_id:        {type: integer}
            text:            {type: string}
            conversation_id: {type: string}
    responses:
      201: {description: Annotation created}
      400: {description: Missing required fields}
    """
    data = request.get_json(silent=True) or {}
    chunk_id = data.get('chunk_id')
    text = (data.get('text') or '').strip()
    conversation_id = data.get('conversation_id') or None

    if not chunk_id or not isinstance(chunk_id, int):
        return jsonify({'success': False, 'message': 'chunk_id (integer) is required'}), 400
    if not text:
        return jsonify({'success': False, 'message': 'text is required'}), 400

    user_id = get_current_user_id()
    try:
        annotation_id = current_app.db.add_annotation(
            chunk_id=chunk_id,
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return jsonify({'success': True, 'id': annotation_id}), 201
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        logger.error(f"[Annotations] create error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.get('/chunks/<int:chunk_id>/annotations')
def list_chunk_annotations(chunk_id: int) -> ResponseReturnValue:
    """
    List all annotations for a document chunk.
    ---
    tags: [Annotations]
    parameters:
      - {in: path, name: chunk_id, type: integer, required: true}
    responses:
      200: {description: List of annotations}
    """
    try:
        annotations = current_app.db.get_annotations_for_chunk(chunk_id)
        return jsonify({'success': True, 'annotations': annotations})
    except Exception as e:
        logger.error(f"[Annotations] list error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500


@bp.delete('/annotations/<annotation_id>')
def delete_annotation(annotation_id: str) -> ResponseReturnValue:
    """
    Delete an annotation (owner or admin only).
    ---
    tags: [Annotations]
    parameters:
      - {in: path, name: annotation_id, type: string, required: true}
    responses:
      200: {description: Deleted}
      404: {description: Not found}
    """
    user_id = get_current_user_id()
    try:
        deleted = current_app.db.delete_annotation(annotation_id, user_id=user_id)
        if not deleted:
            return jsonify({'success': False, 'message': 'Annotation not found'}), 404
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"[Annotations] delete error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _ERR_INTERNAL}), 500
