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

_EXT_DOCX = ".docx"
_EXT_PPTX = ".pptx"
_EXT_XLSX = ".xlsx"

# Number of header bytes needed per extension.
_READ_SIZE: dict[str, int] = {
    ".pdf":  4,
    ".png":  4,
    ".jpg":  3,
    ".jpeg": 3,
    ".gif":  4,
    ".webp": 12,
    _EXT_DOCX: 4,
    _EXT_PPTX: 4,
    _EXT_XLSX: 4,
    ".txt":  512,
    ".md":   512,
}

_DEFAULT_READ = 16

def validate_file_content(file_path: str, extension: str) -> tuple[bool, str]:
    """Validate that the file's content matches its declared extension."""
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

    if ext in (_EXT_DOCX, _EXT_PPTX, _EXT_XLSX):
        return _validate_zip_office(header, file_path, ext)
    if ext in (".txt", ".md"):
        return _validate_text(header, ext)
    if ext in _MAGIC:
        return _validate_magic(header, ext)
    return True, ""


def _validate_zip_office(header: bytes, file_path: str, ext: str) -> tuple[bool, str]:
    fmt = ext.upper().lstrip(".")
    if not header.startswith(b"PK\x03\x04"):
        return False, f"{fmt} file does not have a valid ZIP/{fmt} signature"
    checker_map = {
        _EXT_DOCX: ("word/", _docx_contains_word_dir),
        _EXT_PPTX: ("ppt/",  _pptx_contains_ppt_dir),
        _EXT_XLSX: ("xl/",   _xlsx_contains_xl_dir),
    }
    dir_prefix, checker = checker_map[ext]
    if not checker(file_path):
        return False, f"File has ZIP signature but is not a valid {fmt} (missing {dir_prefix} entry)"
    return True, ""


def _validate_text(header: bytes, ext: str) -> tuple[bool, str]:
    try:
        header.decode("utf-8")
        return True, ""
    except UnicodeDecodeError:
        return False, f"{ext.upper().lstrip('.')} file contains invalid UTF-8 / binary content"


def _validate_magic(header: bytes, ext: str) -> tuple[bool, str]:
    offset, expected = _MAGIC[ext]
    actual = header[offset: offset + len(expected)]
    if actual != expected:
        fmt = ext.upper().lstrip(".")
        return False, (
            f"{fmt} file has invalid signature "
            f"(expected {expected.hex()}, got {actual.hex() or 'empty'})"
        )
    return True, ""


def _docx_contains_word_dir(file_path: str) -> bool:
    """Return True if the ZIP archive contains at least one 'word/' entry."""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return any(name.startswith("word/") for name in zf.namelist())
    except zipfile.BadZipFile:
        return False


def _pptx_contains_ppt_dir(file_path: str) -> bool:
    """Return True if the ZIP archive contains at least one 'ppt/' entry."""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return any(name.startswith("ppt/") for name in zf.namelist())
    except zipfile.BadZipFile:
        return False


def _xlsx_contains_xl_dir(file_path: str) -> bool:
    """Return True if the ZIP archive contains at least one 'xl/' entry."""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return any(name.startswith("xl/") for name in zf.namelist())
    except zipfile.BadZipFile:
        return False
