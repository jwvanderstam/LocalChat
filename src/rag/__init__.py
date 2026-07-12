"""
RAG (Retrieval-Augmented Generation) Package
=============================================

Handles document ingestion, chunking, embedding generation, and context retrieval
for the LocalChat RAG application.

Re-exports all public symbols for backward compatibility with ``from src.rag import ...``.
"""

from .. import config
from ..db import db
from ..monitoring import counted, get_metrics, timed
from ..ollama_client import ollama_client
from ..utils.logging_config import get_logger
from .cache import EmbeddingCache
from .loaders import DOCX_AVAILABLE, PDF_AVAILABLE, Document
from .loaders import _pypdf as pypdf
from .processor import DocumentProcessor, doc_processor
from .scoring import BM25Scorer

# src/monitoring.py only depends on stdlib + Starlette (always installed), so this
# import never actually fails — the flag is kept for the small number of call sites
# and tests that check it, but is no longer conditional.
MONITORING_AVAILABLE = True

logger = get_logger(__name__)

__all__ = [
    'doc_processor',
    'DocumentProcessor',
    'BM25Scorer',
    'EmbeddingCache',
    'PDF_AVAILABLE',
    'DOCX_AVAILABLE',
    'pypdf',
    'Document',
    'MONITORING_AVAILABLE',
    'logger',
    'config',
]
