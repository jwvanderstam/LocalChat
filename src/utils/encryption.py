"""
Field-level Fernet encryption for sensitive text columns.

The key is read from ``ENCRYPTION_KEY`` (or ``TOKEN_ENCRYPTION_KEY`` as a
fallback so existing deployments are not broken).  When no key is configured,
content is stored in plain text and a warning is emitted — acceptable for
local/dev deployments but not for production.
"""

from __future__ import annotations

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

_WARNED_NO_KEY = False


def _get_fernet():
    """Return a Fernet instance or None if no key is configured."""
    from .. import config

    key = config.ENCRYPTION_KEY
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        logger.warning(f"[Encryption] Invalid ENCRYPTION_KEY: {exc}")
        return None


def encrypt(text: str | None) -> str | None:
    """Encrypt *text* and return the ciphertext string, or plain text when no key."""
    if not text:
        return text
    fernet = _get_fernet()
    if fernet:
        return fernet.encrypt(text.encode()).decode()
    global _WARNED_NO_KEY
    if not _WARNED_NO_KEY:
        logger.warning("[Encryption] ENCRYPTION_KEY not set — storing content in plain text")
        _WARNED_NO_KEY = True
    return text


def decrypt(text: str | None) -> str | None:
    """Decrypt *text* and return the plaintext string.

    Falls back to returning *text* unchanged when no key is configured or when
    the value was stored before encryption was enabled.
    """
    if not text:
        return text
    fernet = _get_fernet()
    if fernet:
        try:
            return fernet.decrypt(text.encode()).decode()
        except Exception:
            # Value may have been stored before encryption was enabled.
            return text
    return text
