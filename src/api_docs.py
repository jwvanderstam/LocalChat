# -*- coding: utf-8 -*-

"""
OpenAPI Documentation Configuration
===================================

Configures Swagger UI and OpenAPI specification for LocalChat API.
Provides interactive API documentation at /api/docs

Author: LocalChat Team
Created: 2025-01-15
"""

from flasgger import Swagger
from flask import Flask

# OpenAPI configuration
SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/api/docs/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/docs/",
    "title": "LocalChat API",
    "version": "0.3.0",
    "description": "Professional RAG (Retrieval-Augmented Generation) API",
    "termsOfService": None,
    "hide_top_bar": False,
}

# OpenAPI template
SWAGGER_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "LocalChat RAG API",
        "description": """
# LocalChat RAG Application API

Professional Retrieval-Augmented Generation (RAG) application for document-based question answering.

## Features

- ?? **Document Management**: Upload and manage PDF, DOCX, TXT, Markdown files
- ?? **Vector Search**: Fast similarity search using pgvector
- ?? **Chat Interface**: Conversational AI with RAG context
- ?? **Model Management**: Manage and switch between Ollama models
- ?? **Analytics**: Document and chunk statistics

## Authentication

Currently, the API supports both authenticated and unauthenticated modes:
- **Month 1 Mode**: Basic validation (no auth required)
- **Month 2 Mode**: Pydantic validation with optional JWT auth

## Rate Limiting

- Default: 100 requests per minute per IP
- Chat endpoint: 20 requests per minute
- Model operations: 10 requests per minute

## Base URL

Development: `http://localhost:5000`

## Response Format

All API responses follow this structure:

```json
{
  "success": true,
  "data": {...},
  "message": "Success message"
}
```

Error responses:

```json
{
  "error": "ErrorType",
  "message": "User-friendly error message",
  "details": {...}
}
```

## Supported File Types

- PDF (with table extraction)
- DOCX (Microsoft Word)
- TXT (Plain text)
- MD (Markdown)

Maximum file size: 16 MB
        """,
        "version": "0.3.0",
        "contact": {
            "name": "LocalChat Team",
            "url": "https://github.com/jwvanderstam/LocalChat",
        },
        "license": {
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
    },
    "host": "localhost:5000",
    "basePath": "/",
    "schemes": ["http"],
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "JWT token (optional). Format: Bearer <token>",
        }
    },
    "tags": [
        {
            "name": "System",
            "description": "System status and health checks",
        },
        {
            "name": "Documents",
            "description": "Document management operations",
        },
        {
            "name": "Models",
            "description": "LLM model management",
        },
        {
            "name": "Chat",
            "description": "Chat and RAG operations",
        },
    ],
    "definitions": {
        "Error": {
            "type": "object",
            "properties": {
                "error": {
                    "type": "string",
                    "description": "Error type",
                },
                "message": {
                    "type": "string",
                    "description": "User-friendly error message",
                },
                "details": {
                    "type": "object",
                    "description": "Additional error details",
                },
            },
        },
        "StatusResponse": {
            "type": "object",
            "properties": {
                "ollama": {
                    "type": "boolean",
                    "description": "Ollama service status",
                },
                "database": {
                    "type": "boolean",
                    "description": "Database service status",
                },
                "ready": {
                    "type": "boolean",
                    "description": "Overall system readiness",
                },
                "active_model": {
                    "type": "string",
                    "description": "Currently active LLM model",
                },
                "document_count": {
                    "type": "integer",
                    "description": "Total documents in system",
                },
            },
        },
        "ChatRequest": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {
                    "type": "string",
                    "description": "User's chat message",
                    "minLength": 1,
                    "maxLength": 5000,
                },
                "use_rag": {
                    "type": "boolean",
                    "description": "Whether to use RAG mode",
                    "default": True,
                },
                "history": {
                    "type": "array",
                    "description": "Chat history",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "enum": ["user", "assistant", "system"],
                            },
                            "content": {
                                "type": "string",
                            },
                        },
                    },
                },
            },
        },
        "DocumentStats": {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                },
                "document_count": {
                    "type": "integer",
                },
                "chunk_count": {
                    "type": "integer",
                },
                "chunk_statistics": {
                    "type": "object",
                },
            },
        },
        "Model": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Model name",
                },
                "size": {
                    "type": "integer",
                    "description": "Model size in bytes",
                },
                "modified_at": {
                    "type": "string",
                    "format": "date-time",
                },
            },
        },
    },
}


def init_swagger(app: Flask) -> Swagger:
    """
    Initialize Swagger/OpenAPI documentation.
    
    Configures Flasgger with custom configuration and template.
    Provides interactive API documentation at /api/docs
    
    Args:
        app: Flask application instance
    
    Returns:
        Configured Swagger instance
    
    Example:
        >>> from src.app_factory import create_app
        >>> from src.api_docs import init_swagger
        >>> 
        >>> app = create_app()
        >>> swagger = init_swagger(app)
        >>> # Visit http://localhost:5000/api/docs/
    """
    swagger = Swagger(
        app,
        config=SWAGGER_CONFIG,
        template=SWAGGER_TEMPLATE,
    )
    
    return swagger


# Example endpoint documentation (for reference)
EXAMPLE_ENDPOINT_SPEC = """
Example endpoint documentation:
---
tags:
  - Documents
summary: Upload and ingest documents
description: |
  Upload one or more documents for RAG processing.
  Supported formats: PDF, DOCX, TXT, MD
  
  Maximum file size: 16 MB
consumes:
  - multipart/form-data
parameters:
  - name: files
    in: formData
    type: file
    required: true
    description: Document files to upload
responses:
  200:
    description: Upload progress (Server-Sent Events stream)
    schema:
      type: object
      properties:
        message:
          type: string
          description: Progress message
        result:
          type: object
          description: Upload result for each file
        done:
          type: boolean
          description: Upload complete flag
  400:
    description: Bad request (no files, invalid format)
    schema:
      $ref: '#/definitions/Error'
  413:
    description: File too large
    schema:
      $ref: '#/definitions/Error'
"""
