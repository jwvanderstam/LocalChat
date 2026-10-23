"""Self-service account changes: a signed-in user changing their own password.

The route identifies the caller; this decides whether the change is allowed. Keeping
the decision here, not in the handler, is the layering QP-4 moves every route to.
"""

from __future__ import annotations

import uuid
from typing import Any

from ..db.users import hash_user_password
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class PasswordChangeError(Exception):
    """The change was refused. Carries the response to send."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def change_own_password(db: Any, user_id: str, current_password: str, new_password: str) -> None:
    """Replace *user_id*'s password after proving they know the current one."""
    user = db.get_user_by_id(user_id) if _is_uuid(user_id) else None
    if user is None:
        # The env-var bootstrap admin signs in as "admin", with no user row, so it has
        # no stored password to change. Its way out is to create a real administrator.
        raise PasswordChangeError(
            409, "This account has no stored password. Sign in as a database user to change it."
        )
    # 400, not 401: the session is valid, only this answer is wrong. A 401 would make
    # the frontend treat a typo as an expired session and send the user to the login page.
    if not db.verify_user_password(user["username"], current_password):
        raise PasswordChangeError(400, "Current password is incorrect")
    if not db.update_user(user_id, hashed_password=hash_user_password(new_password)):
        raise PasswordChangeError(409, "The account changed while updating; try again")
    logger.info("[Auth] User %s changed their own password", user_id)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
