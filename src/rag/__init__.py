"""
RAG (Retrieval-Augmented Generation) Package
=============================================

Handles document ingestion, chunking, embedding generation, and context retrieval
for the LocalChat RAG application.

Re-exports all public symbols for backward compatibility with ``from src.rag import ...``.
"""

from .. import config
from ..db import db
from ..ollama_client import ollama_client
from ..utils.logging_config import get_logger

from .scoring import BM25Scorer
from .cache import EmbeddingCache, embedding_cache as _embedding_cache
from .loaders import PDF_AVAILABLE, DOCX_AVAILABLE, PyPDF2, Document
from .processor import DocumentProcessor, doc_processor

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import timed, counted, get_metrics
    MONITORING_AVAILABLE = True
except ImportError:
    def timed(metric_name):  # noqa: E306
        return lambda func: func
    def counted(metric_name, labels=None):  # noqa: E306
        return lambda func: func
    MONITORING_AVAILABLE = False

logger = get_logger(__name__)

__all__ = [
    'doc_processor',
    'DocumentProcessor',
    'BM25Scorer',
    'EmbeddingCache',
    'PDF_AVAILABLE',
    'DOCX_AVAILABLE',
    'PyPDF2',
    'Document',
    'MONITORING_AVAILABLE',
    'logger',
    'config',
    'db',
    'ollama_client',
]
