"""
LocalChat Application Package
=============================

A RAG (Retrieval-Augmented Generation) application for document-based Q&A.

Modules:
    - app: Flask web application and API routes
    - config: Configuration management
    - db: PostgreSQL database with pgvector support
    - ollama_client: Ollama API client for LLM inference
    - rag: Document processing and retrieval engine
    - security: Authentication and security middleware (optional)
    - exceptions: Custom exception classes (optional)
    - models: Pydantic data models (optional)

Author: LocalChat Team
Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "LocalChat Team"

# ============================================================================
# WARNING SUPPRESSIONS
# ============================================================================

import warnings
import os

# Suppress PyPDF2 deprecation warning
# Note: PyPDF2 is deprecated in favor of pypdf, but still functional
# Migration scheduled for next maintenance cycle
warnings.filterwarnings('ignore', message='PyPDF2 is deprecated')
warnings.filterwarnings('ignore', category=DeprecationWarning, module='PyPDF2')

# Suppress security middleware warning in development
# Security features are optional and application handles missing dependencies gracefully
if os.environ.get('FLASK_ENV') == 'development' or os.environ.get('APP_ENV') == 'development':
    # Only suppress in development - in production, we want to see security warnings
    pass  # Handled gracefully in app.py already

# Package namespace initialization
# Relative imports will resolve correctly with this file present
