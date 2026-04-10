"""
Auth Routes — User Management
==============================

Admin-only CRUD for user accounts plus a self-service password-change endpoint.

Endpoints:
    POST   /api/users                 create user (admin)
    GET    /api/users                 list users (admin)
    GET    /api/users/<id>            get user (admin)
    PUT    /api/users/<id>            update user (admin)
    DELETE /api/users/<id>            delete user (admin)
    POST   /api/users/me/password     change own password (authenticated)
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..security import require_admin
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint('auth_users', __name__)

_NOT_FOUND = 'User not found'


def _public(user: dict) -> dict:
    """Strip the hashed_password from a user dict before returning to the client."""
    return {k: v for k, v in user.items() if k != 'hashed_password'}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@bp.post('/users')
@require_admin
def create_user():
    """
    Create a new user account (admin only).
    ---
    tags: [Users]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [username, password]
          properties:
            username: {type: string}
            password: {type: string}
            email:    {type: string}
            role:     {type: string, enum: [admin, user], default: user}
    responses:
      201: {description: User created}
      400: {description: Validation error}
      409: {description: Username already exists}
    """
    from ..db.users import hash_user_password

    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    email = (data.get('email') or '').strip() or None
    role = data.get('role', 'user')

    if not username:
        return jsonify({'success': False, 'message': 'username is required'}), 400
    if not password:
        return jsonify({'success': False, 'message': 'password is required'}), 400
    if role not in ('admin', 'user'):
        return jsonify({'success': False, 'message': "role must be 'admin' or 'user'"}), 400

    try:
        user_id = current_app.db.create_user(
            username=username,
            hashed_password=hash_user_password(password),
            email=email,
            role=role,
        )
        user = current_app.db.get_user_by_id(user_id)
        return jsonify({'success': True, 'user': _public(user)}), 201
    except Exception as exc:
        msg = str(exc)
        if 'unique' in msg.lower():
            return jsonify({'success': False, 'message': 'Username or email already exists'}), 409
        logger.error(f"[Users] create error: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': msg}), 500


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------

@bp.get('/users')
@require_admin
def list_users():
    """List all users (admin only)."""
    try:
        users = current_app.db.list_users()
        return jsonify({'success': True, 'users': [_public(u) for u in users]})
    except Exception as exc:
        logger.error(f"[Users] list error: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': str(exc)}), 500


@bp.get('/users/<user_id>')
@require_admin
def get_user(user_id: str):
    """Get a single user by ID (admin only)."""
    try:
        user = current_app.db.get_user_by_id(user_id)
        if user is None:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        return jsonify({'success': True, 'user': _public(user)})
    except Exception as exc:
        logger.error(f"[Users] get error: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': str(exc)}), 500


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@bp.put('/users/<user_id>')
@require_admin
def update_user(user_id: str):
    """
    Update user fields (admin only).
    Allowed: email, role, is_active. Use POST /api/users/me/password to change passwords.
    """
    from ..db.users import hash_user_password

    data = request.get_json(silent=True) or {}
    allowed = {'email', 'role', 'is_active'}
    fields = {k: v for k, v in data.items() if k in allowed}
    if 'password' in data:
        fields['hashed_password'] = hash_user_password(data['password'])
    if not fields:
        return jsonify({'success': False, 'message': 'No valid fields provided'}), 400
    try:
        updated = current_app.db.update_user(user_id, **fields)
        if not updated:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        user = current_app.db.get_user_by_id(user_id)
        return jsonify({'success': True, 'user': _public(user)})
    except Exception as exc:
        logger.error(f"[Users] update error: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': str(exc)}), 500


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@bp.delete('/users/<user_id>')
@require_admin
def delete_user(user_id: str):
    """Delete a user (admin only)."""
    try:
        deleted = current_app.db.delete_user(user_id)
        if not deleted:
            return jsonify({'success': False, 'message': _NOT_FOUND}), 404
        return jsonify({'success': True})
    except Exception as exc:
        logger.error(f"[Users] delete error: {exc}", exc_info=True)
        return jsonify({'success': False, 'message': str(exc)}), 500


# ---------------------------------------------------------------------------
# Self-service password change
# ---------------------------------------------------------------------------

@bp.post('/users/me/password')
def change_own_password():
    """
    Change the authenticated user's own password.
    ---
    tags: [Users]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [current_password, new_password]
          properties:
            current_password: {type: string}
            new_password:     {type: string}
    responses:
      200: {description: Password changed}
      400: {description: Missing fields}
      401: {description: Wrong current password}
    """
    from ..db.users import hash_user_password
    from ..security import get_current_user_id

    from flask_jwt_extended import verify_jwt_in_request
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    data = request.get_json(silent=True) or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    if not current_password or not new_password:
        return jsonify({'success': False, 'message': 'current_password and new_password required'}), 400

    user_id = get_current_user_id()
    user = current_app.db.get_user_by_id(user_id) if user_id else None
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    # Verify current password
    verified = current_app.db.verify_user_password(user['username'], current_password)
    if not verified:
        return jsonify({'success': False, 'message': 'Current password is incorrect'}), 401

    current_app.db.update_user(user_id, hashed_password=hash_user_password(new_password))
    return jsonify({'success': True})
