"""
File Content Validation
=======================

Validates that uploaded files match their declared extension using magic-byte
inspection. Prevents content-type spoofing (e.g. an HTML file renamed to .pdf).

Only the minimum required bytes are read — no full file load.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Magic-byte signatures keyed by extension.
# Each value is a tuple of (offset, expected_bytes).
_MAGIC: dict[str, tuple[int, bytes]] = {
    ".pdf":  (0, b"%PDF"),
    ".png":  (0, b"\x89PNG"),
    ".jpg":  (0, b"\xff\xd8\xff"),
    ".jpeg": (0, b"\xff\xd8\xff"),
    ".gif":  (0, b"GIF8"),
    ".webp": (8, b"WEBP"),
}

# Number of header bytes needed per extension.
_READ_SIZE: dict[str, int] = {
    ".pdf":  4,
    ".png":  4,
    ".jpg":  3,
    ".jpeg": 3,
    ".gif":  4,
    ".webp": 12,
    ".docx": 4,
    ".txt":  512,
    ".md":   512,
}

_DEFAULT_READ = 16


def validate_file_content(file_path: str, extension: str) -> tuple[bool, str]:
    """
    Validate that the file's content matches its declared extension.

    Reads only the minimum number of header bytes required for each format.
    Text files (.txt, .md) are validated by attempting a UTF-8 decode.

    Args:
        file_path:  Absolute path to the saved file.
        extension:  Lowercase extension including the leading dot (e.g. '.pdf').

    Returns:
        (True, "")                on success
        (False, error_message)    on mismatch or read failure
    """
    path = Path(file_path)

    if not path.exists():
        return False, f"File not found: {file_path}"

    if path.stat().st_size == 0:
        return False, "File is empty (0 bytes)"

    ext = extension.lower()
    read_size = _READ_SIZE.get(ext, _DEFAULT_READ)

    try:
        with open(file_path, "rb") as fh:
            header = fh.read(read_size)
    except OSError as exc:
        return False, f"Could not read file: {exc}"

    # --- DOCX (ZIP container) ---
    if ext == ".docx":
        if not header.startswith(b"PK\x03\x04"):
            return False, "DOCX file does not have a valid ZIP/DOCX signature"
        if not _docx_contains_word_dir(file_path):
            return False, "File has ZIP signature but is not a valid DOCX (missing word/ entry)"
        return True, ""

    # --- Plain text / Markdown ---
    if ext in (".txt", ".md"):
        try:
            header.decode("utf-8")
            return True, ""
        except UnicodeDecodeError:
            return False, f"{ext.upper().lstrip('.')} file contains invalid UTF-8 / binary content"

    # --- Magic-byte formats ---
    if ext in _MAGIC:
        offset, expected = _MAGIC[ext]
        actual = header[offset: offset + len(expected)]
        if actual != expected:
            fmt = ext.upper().lstrip(".")
            return False, (
                f"{fmt} file has invalid signature "
                f"(expected {expected.hex()}, got {actual.hex() or 'empty'})"
            )
        return True, ""

    # Unknown extension — let the document loader handle it.
    return True, ""


def _docx_contains_word_dir(file_path: str) -> bool:
    """Return True if the ZIP archive contains at least one 'word/' entry."""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return any(name.startswith("word/") for name in zf.namelist())
    except zipfile.BadZipFile:
        return False
