"""
Configuration Module
===================

Manages configuration settings and application state for the LocalChat RAG application.
Handles environment variables, database settings, RAG parameters, Ollama GPU settings,
observability options, and persistent state.

Classes:
    AppState: Manages persistent application state (active model, document count)

Constants:
    Database configuration (PG_HOST, PG_PORT, DB_POOL_MIN_CONN, DB_POOL_MAX_CONN)
    Ollama configuration (OLLAMA_BASE_URL, OLLAMA_NUM_GPU)
    RAG configuration (CHUNK_SIZE, TOP_K_RESULTS, HYBRID_SEARCH_ENABLED, etc.)
    Application settings (SECRET_KEY, UPLOAD_FOLDER, APP_VERSION, etc.)
    Observability (METRICS_TOKEN, ENABLE_PERF_METRICS, SLOW_QUERY_THRESHOLD)
    Demo mode (DEMO_MODE — disables JWT authentication; never use in production)

Example:
    >>> from config import app_state, CHUNK_SIZE, OLLAMA_NUM_GPU
    >>> app_state.set_active_model("llama3.2")
    >>> print(f"Chunk size: {CHUNK_SIZE}, GPU layers: {OLLAMA_NUM_GPU}")

Author: LocalChat Team
Last Updated: 2026-03-19
"""

import json
import os
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from .utils.logging_config import get_logger

# Load environment variables from .env file
load_dotenv()

# Setup logger
logger = get_logger(__name__)

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

# Secret keys - MUST be set in production!
_SECRET_KEY_RAW: str | None = os.environ.get('SECRET_KEY')
if not _SECRET_KEY_RAW or _SECRET_KEY_RAW == 'change-this-to-a-random-secret-key-in-production':
    if os.environ.get('APP_ENV') == 'production':
        raise ValueError("SECRET_KEY must be set in production!")
    SECRET_KEY: str = secrets.token_hex(32)
    logger.warning("Using generated SECRET_KEY - set SECRET_KEY in .env for production")
else:
    SECRET_KEY: str = _SECRET_KEY_RAW

_JWT_SECRET_KEY_RAW: str | None = os.environ.get('JWT_SECRET_KEY')
if not _JWT_SECRET_KEY_RAW or _JWT_SECRET_KEY_RAW == 'change-this-to-a-random-jwt-secret-in-production':
    if os.environ.get('APP_ENV') == 'production':
        raise ValueError("JWT_SECRET_KEY must be set in production!")
    JWT_SECRET_KEY: str = secrets.token_hex(32)
    logger.warning("Using generated JWT_SECRET_KEY - set JWT_SECRET_KEY in .env for production")
else:
    JWT_SECRET_KEY: str = _JWT_SECRET_KEY_RAW

JWT_ACCESS_TOKEN_EXPIRES: int = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', '3600'))

# Rate limiting settings
RATELIMIT_ENABLED: bool = os.environ.get('RATELIMIT_ENABLED', 'True').lower() == 'true'
RATELIMIT_CHAT: str = str(os.environ.get('RATELIMIT_CHAT', '10 per minute'))
RATELIMIT_UPLOAD: str = str(os.environ.get('RATELIMIT_UPLOAD', '5 per hour'))
RATELIMIT_MODELS: str = str(os.environ.get('RATELIMIT_MODELS', '20 per minute'))
RATELIMIT_GENERAL: str = str(os.environ.get('RATELIMIT_GENERAL', '60 per minute'))

# Redis settings (shared by cache layer and rate limiting storage)
REDIS_ENABLED: bool = os.environ.get('REDIS_ENABLED', 'False').lower() == 'true'
REDIS_HOST: str = str(os.environ.get('REDIS_HOST', 'localhost'))
REDIS_PORT: int = int(os.environ.get('REDIS_PORT', '6379'))
REDIS_PASSWORD: str | None = os.environ.get('REDIS_PASSWORD') or None

# Rate limiting storage URI.
# Uses Redis DB 1 (DB 0 is reserved for application caches) when Redis is
# enabled.  Falls back to in-process memory when Redis is not configured.
if REDIS_ENABLED:
    _redis_auth = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
    RATELIMIT_STORAGE_URI: str = f"redis://{_redis_auth}{REDIS_HOST}:{REDIS_PORT}/1"
else:
    RATELIMIT_STORAGE_URI: str = "memory://"

# CORS settings
CORS_ENABLED: bool = os.environ.get('CORS_ENABLED', 'False').lower() == 'true'
CORS_ORIGINS: list[str] = [o.strip() for o in os.environ.get('CORS_ORIGINS', 'localhost,127.0.0.1').split(',')]

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

PG_HOST: str = str(os.environ.get('PG_HOST', 'localhost'))
try:
    PG_PORT: int = int(os.environ.get('PG_PORT', '5432'))
except ValueError:
    logger.warning("Invalid PG_PORT value, defaulting to 5432")
    PG_PORT: int = 5432
PG_USER: str = str(os.environ.get('PG_USER', 'postgres'))

_PG_PASSWORD_RAW: str | None = os.environ.get('PG_PASSWORD')
if not _PG_PASSWORD_RAW:
    raise ValueError("PG_PASSWORD must be set in .env file!")
PG_PASSWORD: str = _PG_PASSWORD_RAW

PG_DB: str = str(os.environ.get('PG_DB', 'rag_db'))

# Connection Pool Settings
DB_POOL_MIN_CONN: int = int(os.environ.get('DB_POOL_MIN_CONN', '2'))
DB_POOL_MAX_CONN: int = int(os.environ.get('DB_POOL_MAX_CONN', '10'))

# ============================================================================
# OLLAMA CONFIGURATION
# ============================================================================

OLLAMA_BASE_URL: str = str(os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434'))
# Number of model layers to offload to GPU(s).
# -1 = all layers on GPU (recommended when GPU VRAM is sufficient).
#  0 = CPU only.  Set via OLLAMA_NUM_GPU env var.
OLLAMA_NUM_GPU: int = int(os.environ.get('OLLAMA_NUM_GPU', '-1'))
# Context window size (tokens) sent to Ollama as num_ctx.
# KV-cache VRAM ≈ num_ctx × 0.125 MB for a 7B model.
#   8192  → ~0.5 GB  (safe for any 12 GB GPU + any quantization)
#  32768  → ~4.0 GB  (requires Q4 model ≤5 GB to avoid CPU offload on 12 GB GPU)
# Override via OLLAMA_NUM_CTX env var to match your GPU + model combination.
OLLAMA_NUM_CTX: int = int(os.environ.get('OLLAMA_NUM_CTX', '8192'))

# ============================================================================
# RAG CONFIGURATION - OPTIMIZED FOR HIGH QUALITY RESPONSES
# ============================================================================

# Chunking - OPTIMIZED (prevents repetition)
CHUNK_SIZE: int = int(os.environ.get("CHUNK_SIZE", "1200"))       # Large chunks for context
CHUNK_OVERLAP: int = int(os.environ.get("CHUNK_OVERLAP", "150"))  # 12.5% overlap - industry standard (was 300/25%)
CHUNK_SEPARATORS: list[str] = [
    '\n\n\n',      # Major section breaks
    '\n\n',        # Paragraph breaks (primary)
    '\n',          # Line breaks
    '. ',          # Sentences
    '! ',          # Sentences
    '? ',          # Sentences
    '; ',          # Clauses
    ': ',          # Lists/definitions
    ', ',          # Phrases
    ' ',           # Words
    ''             # Character-level (last resort)
]

# Table-specific settings - Keep tables intact
TABLE_CHUNK_SIZE: int = 3000       # Even larger to keep more tables intact
KEEP_TABLES_INTACT: bool = True    # Always try to keep tables together
MIN_TABLE_ROWS: int = 3            # Min rows to consider as table

# Retrieval Configuration - OPTIMIZED FOR SYNTHESIS
TOP_K_RESULTS: int = int(os.environ.get("TOP_K_RESULTS", "20"))  # Retrieve focused candidates (reduced from 30)
MIN_SIMILARITY_THRESHOLD: float = 0.30       # Slightly higher for quality (was 0.25)
RERANK_RESULTS: bool = True                  # Always re-rank for precision
RERANK_TOP_K: int = 4                        # Return 4 best chunks - better for synthesis (was 6)

# Hybrid Search Configuration
HYBRID_SEARCH_ENABLED: bool = True           # Enable semantic + BM25 hybrid search
SEMANTIC_WEIGHT: float = float(os.environ.get("SEMANTIC_WEIGHT", "0.70"))  # Semantic similarity weight in hybrid
BM25_ENABLED: bool = True                    # Enable BM25 keyword matching

# Query Enhancement
QUERY_EXPANSION_ENABLED: bool = False        # Expand queries with synonyms (opt-in; English business-domain only)
MAX_QUERY_EXPANSIONS: int = 2                # Add up to 2 related terms
QUERY_MIN_LENGTH: int = 10                   # Minimum chars for meaningful query

# Advanced RAG features - MAXIMUM QUALITY
USE_CONTEXTUAL_CHUNKS: bool = True           # Include adjacent chunks
CONTEXT_WINDOW_SIZE: int = 2                 # 2 chunks before/after (increased from 1)
USE_RECIPROCAL_RANK_FUSION: bool = True      # Combine multiple ranking signals

# Re-ranking weights - BALANCED FOR QUALITY
SIMILARITY_WEIGHT: float = 0.50              # Semantic similarity
KEYWORD_WEIGHT: float = 0.20                 # Exact term matches (increased)
BM25_WEIGHT: float = 0.20                    # BM25 score
POSITION_WEIGHT: float = 0.05                # Early chunks bonus
LENGTH_WEIGHT: float = 0.05                  # Chunk length preference

# Diversity filtering - STRENGTHENED to catch overlapping chunks
ENABLE_DIVERSITY_FILTER: bool = True         # Remove near-duplicate chunks
DIVERSITY_THRESHOLD: float = 0.50            # Jaccard similarity threshold (was 0.85 - too weak)

# Context quality enhancement
EMPHASIZE_HIGH_SIMILARITY: bool = True       # Mark highest similarity chunks
INCLUDE_CONFIDENCE_SCORES: bool = True       # Show confidence in context

# Embedding Cache Configuration
EMBEDDING_CACHE_SIZE: int = 500              # Max cached embeddings
EMBEDDING_CACHE_ENABLED: bool = True         # Enable query embedding caching

# Processing Configuration
MAX_WORKERS: int = 8                         # Parallel processing threads
BATCH_SIZE: int = 512                        # Embeddings batch size
BATCH_MAX_WORKERS: int = 8                   # Batch processor workers

# Database Performance
# ef_search is computed dynamically in documents.py as max(top_k * 2, 40)
# to balance recall and query latency based on the configured TOP_K_RESULTS.
DB_INDEX_TYPE: str = 'hnsw'                  # Use HNSW index

# L3 Database Cache Configuration (NEW - Phase 4)
L3_CACHE_ENABLED: bool = True                # Enable DB cache
L3_CACHE_TTL: int = 86400                   # 24 hours default
L3_CACHE_TABLE: str = "query_cache"          # Cache table name

# Performance Monitoring (NEW - Phase 4)
ENABLE_PERF_METRICS: bool = True             # Enable metrics collection
SLOW_QUERY_THRESHOLD: float = 1.0            # Log queries > 1s

# ============================================================================
# WEB SEARCH CONFIGURATION (RAG Enhanced Mode)
# ============================================================================

WEB_SEARCH_ENABLED: bool = os.environ.get('WEB_SEARCH_ENABLED', 'True').lower() == 'true'
WEB_SEARCH_MAX_RESULTS: int = int(os.environ.get('WEB_SEARCH_MAX_RESULTS', '5'))
WEB_SEARCH_TIMEOUT: int = int(os.environ.get('WEB_SEARCH_TIMEOUT', '10'))
WEB_SEARCH_FETCH_PAGES: bool = os.environ.get('WEB_SEARCH_FETCH_PAGES', 'False').lower() == 'true'
WEB_SEARCH_MAX_PAGE_CHARS: int = int(os.environ.get('WEB_SEARCH_MAX_PAGE_CHARS', '2000'))

# ============================================================================
# TOOL CALLING CONFIGURATION
# ============================================================================

TOOL_CALLING_ENABLED: bool = os.environ.get('TOOL_CALLING_ENABLED', 'True').lower() == 'true'
TOOL_MAX_ROUNDS: int = int(os.environ.get('TOOL_MAX_ROUNDS', '5'))

# ============================================================================
# CLOUD MODEL FALLBACK CONFIGURATION (Feature 1.3)
# ============================================================================

# Set CLOUD_FALLBACK_ENABLED=true to enable cloud fallback when the local
# model refuses to answer (e.g. "I don't know" responses).
# Requires litellm: pip install 'litellm>=1.67.0'
CLOUD_FALLBACK_ENABLED: bool = os.environ.get('CLOUD_FALLBACK_ENABLED', 'false').lower() == 'true'
CLOUD_PROVIDER: str = os.environ.get('CLOUD_PROVIDER', '')   # e.g. "openai", "anthropic"
CLOUD_API_KEY: str | None = os.environ.get('CLOUD_API_KEY') or None
CLOUD_MODEL: str = os.environ.get('CLOUD_MODEL', '')         # e.g. "gpt-4o", "claude-3-5-haiku"

# Phrases that indicate a local refusal (case-insensitive regex alternation).
# Only checked on responses shorter than 500 chars to avoid false positives.
CLOUD_REFUSAL_PATTERNS: list[str] = [
    r"I don't know",
    r"I cannot",
    r"I'm not sure",
    r"I don't have information",
    r"I don't have access",
    r"I'm unable to",
    r"no information",
    r"not mentioned in",
    r"not provided in",
]

# ============================================================================
# PLUGIN SYSTEM CONFIGURATION
# ============================================================================

# Set PLUGINS_ENABLED=false to skip plugin loading entirely at startup.
PLUGINS_ENABLED: bool = os.environ.get('PLUGINS_ENABLED', 'True').lower() == 'true'
# Directory (relative to repo root) that is scanned for .py plugin files.
PLUGINS_DIR: str = os.environ.get('PLUGINS_DIR', 'plugins')

# ============================================================================
# LLM CONFIGURATION - MAXIMUM QUALITY
# ============================================================================

DEFAULT_TEMPERATURE: float = 0.0   # ZERO temperature for maximum factuality
MAX_CONTEXT_LENGTH: int = OLLAMA_NUM_CTX  # Mirrors OLLAMA_NUM_CTX; override via env var

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

# Application version (override with APP_VERSION env var for CI-stamped builds)
APP_VERSION: str = os.environ.get('APP_VERSION', '0.5.0')

# Supported file types
SUPPORTED_IMAGE_EXTENSIONS: list[str] = ['.png', '.jpg', '.jpeg', '.gif', '.webp']
SUPPORTED_EXTENSIONS: list[str] = (
    ['.pdf', '.txt', '.docx', '.md', '.pptx', '.py', '.js', '.ts', '.eml']
    + SUPPORTED_IMAGE_EXTENSIONS
)

# Vision / multimodal configuration
VISION_DESCRIBE_PROMPT: str = (
    "Describe this image in detail. Include all visible text, charts, tables, diagrams, "
    "key objects, and any relevant context. Be comprehensive so the description can be "
    "used to answer questions about the image."
)

# Flask settings
UPLOAD_FOLDER: str = 'uploads'
MAX_CONTENT_LENGTH: int = int(os.environ.get('MAX_CONTENT_LENGTH', str(16 * 1024 * 1024)))  # Default: 16MB

# Logging
LOG_FILE: str = os.environ.get('LOG_FILE', 'logs/app.log')
# Set LOG_FORMAT=json to emit JSON lines (recommended for production log aggregators)
LOG_FORMAT: str = os.environ.get('LOG_FORMAT', 'text')

# State persistence file
STATE_FILE: str = 'app_state.json'

# ============================================================================
# DEMO MODE
# ============================================================================
# DEMO_MODE=true is intended ONLY for single-user local evaluation.
# It disables JWT authentication and suppresses web search.
# NEVER enable demo mode in a network-accessible or multi-user deployment.

DEMO_MODE: bool = os.environ.get('DEMO_MODE', 'false').lower() == 'true'
if DEMO_MODE:
    logger.warning(
        "DEMO_MODE is ON — authentication is disabled. "
        "Do not expose this instance to untrusted networks."
    )

# ============================================================================
# METRICS / OBSERVABILITY
# ============================================================================
# Optional static bearer token that Prometheus (or an operator) must supply
# when scraping /api/metrics.  Leave empty to allow unauthenticated access
# (acceptable when the endpoint is behind a firewall or a private network).
METRICS_TOKEN: str = os.environ.get('METRICS_TOKEN', '')
if not METRICS_TOKEN:
    logger.warning(
        "METRICS_TOKEN is not set — /api/metrics is accessible without authentication. "
        "Set METRICS_TOKEN in .env to restrict access."
    )


class AppState:
    """
    Manages persistent application state.

    Handles runtime configuration such as active model and document count,
    persisting state to a JSON file for recovery after restarts.

    Attributes:
        state_file (str): Path to state persistence file
        state (Dict[str, Any]): Current application state

    Example:
        >>> state = AppState()
        >>> state.set_active_model("llama3.2")
        >>> model = state.get_active_model()
        >>> print(model)
        llama3.2
    """

    def __init__(self, state_file: str = STATE_FILE) -> None:
        """
        Initialize application state manager.

        Args:
            state_file: Path to state persistence file
        """
        self.state_file: str = state_file
        self.state: dict[str, Any] = self._load_state()
        logger.info("Application state initialized")

    def _load_state(self) -> dict[str, Any]:
        """
        Load state from JSON file.

        Returns:
            Dictionary containing application state, or default state if file
            doesn't exist or cannot be read.

        Note:
            If loading fails, returns default state and logs the error.
        """
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                    logger.debug(f"Loaded state from {self.state_file}")
                    return state
            except Exception as e:
                logger.error(f"Error loading state: {e}", exc_info=True)

        # Return default state
        default_state = {
            'active_model': None,
            'document_count': 0,
            'last_updated': None
        }
        logger.debug("Using default application state")
        return default_state

    def _save_state(self) -> None:
        """
        Save state to JSON file.

        Updates the last_updated timestamp and persists state to disk.
        Logs errors if save fails but doesn't raise exceptions.
        """
        try:
            self.state['last_updated'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.debug(f"Saved state to {self.state_file}")
        except Exception as e:
            logger.error(f"Error saving state: {e}", exc_info=True)

    def get_active_model(self) -> str | None:
        """
        Get the currently active model name.

        Returns:
            Name of active model, or None if no model is set

        Example:
            >>> model = app_state.get_active_model()
            >>> if model:
            ...     print(f"Using model: {model}")
        """
        return self.state.get('active_model')

    def set_active_model(self, model_name: str) -> None:
        """
        Set the active model name.

        Args:
            model_name: Name of the model to set as active

        Example:
            >>> app_state.set_active_model("llama3.2:latest")
        """
        self.state['active_model'] = model_name
        self._save_state()
        logger.info(f"Active model set to: {model_name}")

    def get_document_count(self) -> int:
        """
        Get the current document count.

        Returns:
            Number of documents in the system
        """
        return self.state.get('document_count', 0)

    def set_document_count(self, count: int) -> None:
        """
        Set the document count.

        Args:
            count: New document count

        Raises:
            ValueError: If count is negative

        Example:
            >>> app_state.set_document_count(10)
        """
        if count < 0:
            logger.error(f"Invalid document count: {count}")
            raise ValueError("Document count cannot be negative")

        self.state['document_count'] = count
        self._save_state()
        logger.debug(f"Document count set to: {count}")

    def increment_document_count(self, increment: int = 1) -> None:
        """
        Increment the document count.

        Args:
            increment: Amount to increment by (default: 1)

        Example:
            >>> app_state.increment_document_count(5)
        """
        current = self.state.get('document_count', 0)
        self.state['document_count'] = current + increment
        self._save_state()
        logger.debug(f"Document count incremented by {increment} to {self.state['document_count']}")


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

# Create global app state instance
app_state = AppState()


def validate_config() -> None:
    """
    Validate configuration values for logical consistency.

    Raises:
        ValueError: If any configuration value is invalid.
    """
    if CHUNK_OVERLAP >= CHUNK_SIZE:
        raise ValueError(
            f"CHUNK_OVERLAP ({CHUNK_OVERLAP}) must be less than CHUNK_SIZE ({CHUNK_SIZE})"
        )
    if RERANK_TOP_K > TOP_K_RESULTS:
        raise ValueError(
            f"RERANK_TOP_K ({RERANK_TOP_K}) cannot exceed TOP_K_RESULTS ({TOP_K_RESULTS})"
        )
    if OLLAMA_NUM_GPU < -1:
        raise ValueError(
            f"OLLAMA_NUM_GPU ({OLLAMA_NUM_GPU}) must be >= -1 (-1 means all layers on GPU)"
        )
    if DB_POOL_MIN_CONN > DB_POOL_MAX_CONN:
        raise ValueError(
            f"DB_POOL_MIN_CONN ({DB_POOL_MIN_CONN}) cannot exceed DB_POOL_MAX_CONN ({DB_POOL_MAX_CONN})"
        )
    logger.debug("Configuration validation passed")


validate_config()

logger.info("Configuration module loaded")
logger.debug(f"Database: {PG_HOST}:{PG_PORT}/{PG_DB}")
logger.debug(f"Chunk size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}")
logger.debug(f"Top-K results: {TOP_K_RESULTS}, Min similarity: {MIN_SIMILARITY_THRESHOLD}")

