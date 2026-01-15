"""
Configuration Module
===================

Manages configuration settings and application state for the LocalChat RAG application.
Handles environment variables, database settings, RAG parameters, and persistent state.

Classes:
    AppState: Manages persistent application state (active model, document count)

Constants:
    Database configuration (PG_HOST, PG_PORT, etc.)
    RAG configuration (CHUNK_SIZE, TOP_K_RESULTS, etc.)
    Application settings (SECRET_KEY, UPLOAD_FOLDER, etc.)

Example:
    >>> from config import app_state, CHUNK_SIZE
    >>> app_state.set_active_model("llama3.2")
    >>> print(f"Chunk size: {CHUNK_SIZE}")

Author: LocalChat Team
Last Updated: 2026-01-04 (Fixed type safety)
"""

import os
import json
import secrets
from typing import Dict, Any, Optional, List
from datetime import datetime
from dotenv import load_dotenv
from .utils.logging_config import get_logger

# Load environment variables from .env file
load_dotenv()

# Setup logger
logger = get_logger(__name__)

# ============================================================================
# SECURITY CONFIGURATION - WEEK 1
# ============================================================================

# Secret keys - MUST be set in production!
_SECRET_KEY_RAW: Optional[str] = os.environ.get('SECRET_KEY')
if not _SECRET_KEY_RAW or _SECRET_KEY_RAW == 'change-this-to-a-random-secret-key-in-production':
    if os.environ.get('APP_ENV') == 'production':
        raise ValueError("SECRET_KEY must be set in production!")
    SECRET_KEY: str = secrets.token_hex(32)
    logger.warning("Using generated SECRET_KEY - set SECRET_KEY in .env for production")
else:
    SECRET_KEY: str = _SECRET_KEY_RAW

_JWT_SECRET_KEY_RAW: Optional[str] = os.environ.get('JWT_SECRET_KEY')
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

# CORS settings
CORS_ENABLED: bool = os.environ.get('CORS_ENABLED', 'False').lower() == 'true'
CORS_ORIGINS: List[str] = os.environ.get('CORS_ORIGINS', '*').split(',')

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

PG_HOST: str = str(os.environ.get('PG_HOST', 'localhost'))
PG_PORT: int = int(os.environ.get('PG_PORT', '5432'))
PG_USER: str = str(os.environ.get('PG_USER', 'postgres'))

_PG_PASSWORD_RAW: Optional[str] = os.environ.get('PG_PASSWORD')
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

# ============================================================================
# RAG CONFIGURATION - OPTIMIZED FOR HIGH QUALITY RESPONSES
# ============================================================================

# Chunking - MAXIMUM QUALITY (prevents word breaks)
CHUNK_SIZE: int = 1200             # Increased from 1024 - larger chunks
CHUNK_OVERLAP: int = 300           # Increased from 200 - 25% overlap prevents broken words
CHUNK_SEPARATORS: List[str] = [
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

# Retrieval Configuration - MAXIMUM QUALITY (HIGH RESOURCE)
TOP_K_RESULTS: int = 60                      # Increased from 40 - more candidates
MIN_SIMILARITY_THRESHOLD: float = 0.20       # Lower threshold - better recall
RERANK_RESULTS: bool = True                  # Always re-rank for precision
RERANK_TOP_K: int = 15                       # INCREASED from 12 - maximum context!

# Hybrid Search Configuration
HYBRID_SEARCH_ENABLED: bool = True           # Enable semantic + BM25 hybrid search
SEMANTIC_WEIGHT: float = 0.70                # Semantic similarity weight in hybrid
BM25_ENABLED: bool = True                    # Enable BM25 keyword matching

# Query Enhancement
QUERY_EXPANSION_ENABLED: bool = True         # Expand queries with synonyms
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

# Diversity filtering
ENABLE_DIVERSITY_FILTER: bool = True         # Remove near-duplicate chunks
DIVERSITY_THRESHOLD: float = 0.85            # Jaccard similarity threshold

# Context quality enhancement
EMPHASIZE_HIGH_SIMILARITY: bool = True       # Mark highest similarity chunks
INCLUDE_CONFIDENCE_SCORES: bool = True       # Show confidence in context

# Embedding Cache Configuration
EMBEDDING_CACHE_SIZE: int = 500              # Max cached embeddings
EMBEDDING_CACHE_ENABLED: bool = True         # Enable query embedding caching

# Processing Configuration
MAX_WORKERS: int = 8                         # Parallel processing threads
BATCH_SIZE: int = 64                         # Embeddings batch size (increased from 32)
BATCH_MAX_WORKERS: int = 8                   # Batch processor workers

# Database Performance
DB_SEARCH_EF: int = 100                      # HNSW ef_search parameter
DB_INDEX_TYPE: str = 'hnsw'                  # Use HNSW index

# L3 Database Cache Configuration (NEW - Phase 4)
L3_CACHE_ENABLED: bool = True                # Enable DB cache
L3_CACHE_TTL: int = 86400                   # 24 hours default
L3_CACHE_TABLE: str = "query_cache"          # Cache table name

# Performance Monitoring (NEW - Phase 4)
ENABLE_PERF_METRICS: bool = True             # Enable metrics collection
SLOW_QUERY_THRESHOLD: float = 1.0            # Log queries > 1s

# ============================================================================
# LLM CONFIGURATION - MAXIMUM QUALITY
# ============================================================================

DEFAULT_TEMPERATURE: float = 0.0   # ZERO temperature for maximum factuality
MAX_CONTEXT_LENGTH: int = 50000    # MAXIMUM context for most comprehensive answers

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

# Supported file types
SUPPORTED_EXTENSIONS: List[str] = ['.pdf', '.txt', '.docx', '.md']

# Flask settings
UPLOAD_FOLDER: str = 'uploads'
MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024  # 16MB max upload size

# State persistence file
STATE_FILE: str = 'app_state.json'


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
        self.state: Dict[str, Any] = self._load_state()
        logger.info("Application state initialized")
    
    def _load_state(self) -> Dict[str, Any]:
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
                with open(self.state_file, 'r') as f:
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
    
    def get_active_model(self) -> Optional[str]:
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

logger.info("Configuration module loaded")
logger.debug(f"Database: {PG_HOST}:{PG_PORT}/{PG_DB}")
logger.debug(f"Chunk size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}")
logger.debug(f"Top-K results: {TOP_K_RESULTS}, Min similarity: {MIN_SIMILARITY_THRESHOLD}")
