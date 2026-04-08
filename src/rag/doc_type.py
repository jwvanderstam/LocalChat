"""
Document Type Classification and Chunker Registry
==================================================

Provides DocType enum, DocTypeClassifier for extension-to-type mapping,
and ChunkerRegistry which maps each DocType to the correct load+chunk
callable and a version string stored in the DB for cache invalidation.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .processor import DocumentProcessor


class DocType(str, Enum):
    PDF          = "PDF"
    DOCX         = "DOCX"
    TXT          = "TXT"
    MD           = "MD"
    PPTX         = "PPTX"
    CODE_PYTHON  = "CODE_PYTHON"
    CODE_JS      = "CODE_JS"
    CODE_TS      = "CODE_TS"
    EMAIL        = "EMAIL"
    IMAGE        = "IMAGE"
    UNKNOWN      = "UNKNOWN"


class DocTypeClassifier:
    _EXT_MAP: dict[str, DocType] = {
        '.pdf':  DocType.PDF,
        '.docx': DocType.DOCX,
        '.txt':  DocType.TXT,
        '.md':   DocType.MD,
        '.pptx': DocType.PPTX,
        '.py':   DocType.CODE_PYTHON,
        '.js':   DocType.CODE_JS,
        '.ts':   DocType.CODE_TS,
        '.eml':  DocType.EMAIL,
        '.png':  DocType.IMAGE,
        '.jpg':  DocType.IMAGE,
        '.jpeg': DocType.IMAGE,
        '.gif':  DocType.IMAGE,
        '.webp': DocType.IMAGE,
    }

    @classmethod
    def classify(cls, ext: str) -> DocType:
        """Return the DocType for a file extension (lower-case, including dot)."""
        return cls._EXT_MAP.get(ext.lower(), DocType.UNKNOWN)


# Callable type: (processor, file_path, filename, progress_callback)
#   -> (success, error_msg, chunks_with_metadata | None, raw_content | None)
_ChunkerFn = Callable[
    ["DocumentProcessor", str, str, Callable[[str], None] | None],
    tuple[bool, str, list[dict[str, Any]] | None, str | None],
]


def _chunker_pdf(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    if progress_cb:
        progress_cb(f"Loading {filename}...")
    success, pages_or_error = proc._load_pdf_with_pages(file_path)
    if not success:
        return False, f"Failed to load {filename}: {pages_or_error}", None, None
    if progress_cb:
        progress_cb(f"Chunking {filename}...")
    chunks = proc.chunk_pages_with_metadata(pages_or_error)
    if not chunks:
        return False, f"No chunks generated from {filename}", None, None
    return True, "", chunks, None


def _chunker_docx(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    return _chunker_plain_text(proc, file_path, filename, progress_cb)


def _chunker_plain_text(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    if progress_cb:
        progress_cb(f"Loading {filename}...")
    success, content = proc.load_document(file_path)
    if not success:
        return False, f"Failed to load {filename}: {content}", None, None
    if not content or len(content.strip()) < 10:
        return False, f"Document {filename} has insufficient content ({len(content)} chars)", None, None
    if progress_cb:
        progress_cb(f"Chunking {filename}...")
    chunk_texts = proc.chunk_text(content)
    if not chunk_texts:
        return False, f"No chunks generated from {filename}", None, None
    chunks = [
        {'text': c, 'page_number': None, 'section_title': None, 'chunk_index': i}
        for i, c in enumerate(chunk_texts)
    ]
    return True, "", chunks, content


def _chunker_pptx(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    if progress_cb:
        progress_cb(f"Loading {filename}...")
    success, slides_or_error = proc.load_pptx_file(file_path)
    if not success:
        return False, f"Failed to load {filename}: {slides_or_error}", None, None
    if progress_cb:
        progress_cb(f"Chunking {filename}...")
    chunks = proc.chunk_slides(slides_or_error)
    if not chunks:
        return False, f"No chunks generated from {filename}", None, None
    return True, "", chunks, None


def _chunker_code_python(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    if progress_cb:
        progress_cb(f"Loading {filename}...")
    success, content = proc.load_text_file(file_path)
    if not success:
        return False, f"Failed to load {filename}: {content}", None, None
    if progress_cb:
        progress_cb(f"Chunking {filename}...")
    chunks = proc.chunk_code_python(content)
    if not chunks:
        return False, f"No chunks generated from {filename}", None, None
    return True, "", chunks, content


def _chunker_code_js_ts(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    if progress_cb:
        progress_cb(f"Loading {filename}...")
    success, content = proc.load_text_file(file_path)
    if not success:
        return False, f"Failed to load {filename}: {content}", None, None
    if progress_cb:
        progress_cb(f"Chunking {filename}...")
    chunks = proc.chunk_code_js_ts(content)
    if not chunks:
        return False, f"No chunks generated from {filename}", None, None
    return True, "", chunks, content


def _chunker_email(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    if progress_cb:
        progress_cb(f"Loading {filename}...")
    success, content = proc.load_eml_file(file_path)
    if not success:
        return False, f"Failed to load {filename}: {content}", None, None
    if progress_cb:
        progress_cb(f"Chunking {filename}...")
    chunks = proc.chunk_email(content)
    if not chunks:
        return False, f"No chunks generated from {filename}", None, None
    return True, "", chunks, content


def _chunker_image(
    proc: "DocumentProcessor",
    file_path: str,
    filename: str,
    progress_cb: Callable[[str], None] | None,
) -> tuple[bool, str, list[dict[str, Any]] | None, str | None]:
    return _chunker_plain_text(proc, file_path, filename, progress_cb)


class ChunkerRegistry:
    """Maps DocType → (chunker_fn, chunker_version)."""

    _REGISTRY: dict[DocType, tuple[_ChunkerFn, str]] = {
        DocType.PDF:         (_chunker_pdf,          "pdf-v1"),
        DocType.DOCX:        (_chunker_docx,         "docx-v1"),
        DocType.TXT:         (_chunker_plain_text,   "text-v1"),
        DocType.MD:          (_chunker_plain_text,   "text-v1"),
        DocType.PPTX:        (_chunker_pptx,         "pptx-v1"),
        DocType.CODE_PYTHON: (_chunker_code_python,  "code-py-v1"),
        DocType.CODE_JS:     (_chunker_code_js_ts,   "code-js-v1"),
        DocType.CODE_TS:     (_chunker_code_js_ts,   "code-ts-v1"),
        DocType.EMAIL:       (_chunker_email,        "email-v1"),
        DocType.IMAGE:       (_chunker_image,        "image-v1"),
        DocType.UNKNOWN:     (_chunker_plain_text,   "text-v1"),
    }

    @classmethod
    def get_chunker(cls, doc_type: DocType) -> tuple[_ChunkerFn, str]:
        """Return (chunker_fn, chunker_version) for the given DocType."""
        return cls._REGISTRY.get(doc_type, cls._REGISTRY[DocType.UNKNOWN])
