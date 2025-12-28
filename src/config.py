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
Last Updated: 2024-12-27
"""

import os
import json
from typing import Dict, Any, Optional
from datetime import datetime
from .utils.logging_config import get_logger

# Setup logger
logger = get_logger(__name__)

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

PG_HOST: str = os.environ.get('PG_HOST', 'localhost')
PG_PORT: int = int(os.environ.get('PG_PORT', '5432'))
PG_USER: str = os.environ.get('PG_USER', 'postgres')
PG_PASSWORD: str = os.environ.get('PG_PASSWORD', 'Mutsmuts10')
PG_DB: str = os.environ.get('PG_DB', 'rag_db')

# Connection Pool Settings
DB_POOL_MIN_CONN: int = 2
DB_POOL_MAX_CONN: int = 10

# ============================================================================
# OLLAMA CONFIGURATION
# ============================================================================

OLLAMA_BASE_URL: str = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')

# ============================================================================
# RAG CONFIGURATION - OPTIMIZED FOR BETTER PERFORMANCE
# ============================================================================

# Chunking - Optimal for most use cases
CHUNK_SIZE: int = 768              # Characters per chunk (increased for better context)
CHUNK_OVERLAP: int = 128           # Overlap between chunks (16.7% overlap)
CHUNK_SEPARATORS: list = ['\n\n\n', '\n\n', '\n', '. ', '! ', '? ', '; ', ', ', ' ', '']  # Hierarchical splitting

# Retrieval Configuration - More aggressive retrieval with filtering
TOP_K_RESULTS: int = 15            # Retrieve top 15 chunks (increased from 10)
MIN_SIMILARITY_THRESHOLD: float = 0.25  # Filter out low-quality matches (lowered from 0.3)
RERANK_RESULTS: bool = True        # Re-rank results by relevance
RERANK_TOP_K: int = 10             # After re-ranking, return top 10

# Advanced RAG features
USE_CONTEXTUAL_CHUNKS: bool = True   # Include adjacent chunks for context
CONTEXT_WINDOW_SIZE: int = 1         # Include 1 chunk before/after each result

# Re-ranking weights
SIMILARITY_WEIGHT: float = 0.5       # Vector similarity weight
KEYWORD_WEIGHT: float = 0.2          # Exact keyword match weight  
BM25_WEIGHT: float = 0.2             # BM25 relevance score weight
POSITION_WEIGHT: float = 0.1         # Early chunk position weight

# Processing Configuration
MAX_WORKERS: int = 4               # Parallel workers for document processing

# ============================================================================
# LLM CONFIGURATION
# ============================================================================

DEFAULT_TEMPERATURE: float = 0.0   # ZERO temperature for maximum factuality (no creativity/hallucinations)
MAX_CONTEXT_LENGTH: int = 4096     # Maximum context window for LLM

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

# Supported file types
SUPPORTED_EXTENSIONS: list = ['.pdf', '.txt', '.docx', '.md']

# Flask settings
SECRET_KEY: str = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
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
