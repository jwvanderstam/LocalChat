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
from .cache import EmbeddingCache
from .cache import embedding_cache as _embedding_cache
from .loaders import DOCX_AVAILABLE, PDF_AVAILABLE, Document
from .loaders import _pypdf as pypdf
from .processor import DocumentProcessor, doc_processor
from .scoring import BM25Scorer

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import counted, get_metrics, timed
    MONITORING_AVAILABLE = True
except ImportError:
    def timed(_metric_name: str):  # noqa: E306
        return lambda func: func
    def counted(_metric_name: str, _labels=None):  # noqa: E306
        return lambda func: func
    def get_metrics():  # noqa: E306
        raise RuntimeError("Monitoring not available")
    MONITORING_AVAILABLE = False

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
    'db',
    'ollama_client',
]
