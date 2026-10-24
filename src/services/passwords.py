"""Password hashing and checking — Werkzeug's PBKDF2-SHA256, salt stored in the hash.

Its own module, importing nothing from the application above the repository, because
``security_fastapi`` checks credentials with it and ``services.users`` imports
``security_fastapi``: anywhere else would be an import cycle.
"""

from __future__ import annotations

import functools
import secrets
from typing import TYPE_CHECKING, Any

from werkzeug.security import check_password_hash, generate_password_hash

if TYPE_CHECKING:
    from ..db.users import UsersRepository


def hash_user_password(password: str) -> str:
    """Return a Werkzeug PBKDF2-SHA256 hash string for ``password``."""
    hashed: str = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)
    return hashed


@functools.cache
def _dummy_hash() -> str:
    return hash_user_password(secrets.token_urlsafe(32))


def verify_user_password(users: UsersRepository, username: str, password: str) -> dict[str, Any] | None:
    """Return the user, hash removed, if the credentials are valid; else None."""
    user = users.get_by_username(username)
    stored_hash = user.pop('hashed_password', None) if user else None
    usable = bool(user and user.get('is_active') and stored_hash)
    # Always pay for one hash: answering an unknown or inactive user without one
    # made the response time say which usernames exist (audit S3).
    matches = check_password_hash(stored_hash if usable and stored_hash else _dummy_hash(), password)
    return user if usable and matches else None
