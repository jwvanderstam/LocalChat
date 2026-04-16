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

Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "LocalChat Team"

import os

# Package namespace initialization
# Relative imports will resolve correctly with this file present
