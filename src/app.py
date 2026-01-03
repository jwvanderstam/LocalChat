"""
Flask Application Module
========================

Main application entry point for LocalChat RAG application.
Provides web interface and REST API for document management, chat, and model operations.

Routes:
    Web Pages: /, /chat, /documents, /models, /overview
    API: /api/status, /api/chat, /api/documents/*, /api/models/*

Example:
    >>> python app.py
    # Starts web server on http://localhost:5000

Author: LocalChat Team
Last Updated: 2024-12-27 (Month 2 - Error Handling & Validation)
"""

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import os
import json
from pathlib import Path
import atexit
import signal
import sys
from typing import Dict, Any, Generator
from datetime import datetime

# Core modules
from . import config
from .db import db
from .ollama_client import ollama_client
from .rag import doc_processor
from .utils.logging_config import setup_logging, get_logger

# Month 2 additions - Error handling and validation (optional for Python 3.14 compatibility)
MONTH2_ENABLED = False
try:
    from pydantic import ValidationError as PydanticValidationError
    from src import exceptions
    from src.models import (
        ChatRequest, ModelRequest, RetrievalRequest,
        ModelPullRequest, ModelDeleteRequest, ErrorResponse
    )
    from src.utils.sanitization import (
        sanitize_filename, sanitize_query, sanitize_model_name
    )
    MONTH2_ENABLED = True
    logger_temp = get_logger(__name__)
    logger_temp.info("✅ Month 2 features enabled (Pydantic validation)")
except ImportError as e:
    # Month 2 features not available (likely Python 3.14 with no pydantic wheels)
    # Application will work with basic validation only
    logger_temp = get_logger(__name__)
    logger_temp.warning(f"⚠️  Month 2 features disabled: {e}")
    logger_temp.warning("⚠️  Application will run with basic validation (Month 1 only)")
    logger_temp.info("To enable Month 2 features, install: pip install pydantic==2.9.2")

# ============================================================================
# LOGGING INITIALIZATION
# ============================================================================

# Initialize logging system at startup
setup_logging(log_level="INFO", log_file="logs/app.log")
logger = get_logger(__name__)

logger.info("=" * 50)
if MONTH2_ENABLED:
    logger.info("LocalChat Application Starting (Month 2 - Validated)")
else:
    logger.info("LocalChat Application Starting (Month 1 - Basic Validation)")
logger.info("=" * 50)

# ============================================================================
# FLASK APPLICATION SETUP
# ============================================================================

# Get the root directory (parent of src/)
ROOT_DIR = Path(__file__).parent.parent

app = Flask(__name__, 
    template_folder=str(ROOT_DIR / 'templates'),
    static_folder=str(ROOT_DIR / 'static'))
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
logger.debug(f"Upload folder: {config.UPLOAD_FOLDER}")

# Make the WSGI interface available at the top level so wfastcgi can get it.
wsgi_app = app.wsgi_app

# Global state
startup_status: Dict[str, bool] = {
    'ollama': False,
    'database': False,
    'ready': False
}


def startup_checks() -> None:
    """
    Perform startup checks for Ollama and database.
    
    Verifies that required services (Ollama, PostgreSQL) are available
    and initializes the application state.
    """
    logger.info("=" * 50)
    logger.info("Starting LocalChat Application")
    logger.info("=" * 50)
    
    # Check Ollama
    logger.info("1. Checking Ollama...")
    ollama_success, ollama_message = ollama_client.check_connection()
    startup_status['ollama'] = ollama_success
    
    if ollama_success:
        logger.info(f"✓ {ollama_message}")
    else:
        logger.error(f"✗ {ollama_message}")
    
    if ollama_success:
        # Load first available model if no active model set
        if not config.app_state.get_active_model():
            first_model = ollama_client.get_first_available_model()
            if first_model:
                config.app_state.set_active_model(first_model)
                logger.info(f"✓ Active model set to: {first_model}")
    
    # Check Database
    logger.info("2. Checking PostgreSQL with pgvector...")
    db_success, db_message = db.initialize()
    startup_status['database'] = db_success
    
    if db_success:
        logger.info(f"✓ {db_message}")
        doc_count = db.get_document_count()
        config.app_state.set_document_count(doc_count)
        logger.info(f"✓ Documents in database: {doc_count}")
    else:
        logger.error(f"✗ {db_message}")
    
    # Overall status
    startup_status['ready'] = startup_status['ollama'] and startup_status['database']
    
    logger.info("3. Starting web server...")
    if startup_status['ready']:
        logger.info("✓ All services ready!")
        logger.info("✓ Server starting on http://localhost:5000")
    else:
        logger.warning("⚠ Some services are not available")
        logger.warning("⚠ Server starting with limited functionality")
    
    logger.info("=" * 50)


def cleanup() -> None:
    """
    Cleanup function to close database connections.
    
    Called automatically on application shutdown to ensure
    all connections are properly closed.
    """
    if db.is_connected:
        logger.info("Closing database connections...")
        db.close()
        logger.info("Cleanup complete")


# Register cleanup handlers
atexit.register(cleanup)

def signal_handler(sig: int, frame: Any) -> None:
    """
    Handle interrupt signals gracefully.
    
    Args:
        sig: Signal number
        frame: Current stack frame
    """
    logger.info("\nReceived interrupt signal, shutting down...")
    cleanup()
    logger.info("Goodbye!")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ============================================================================
# ERROR HANDLERS - Month 2 (Optional)
# ============================================================================

if MONTH2_ENABLED:
    @app.errorhandler(400)
    def bad_request_handler(error) -> Response:
        """
        Handle 400 Bad Request errors.
        
        Args:
            error: Error details
        
        Returns:
            JSON error response
        """
        logger.warning(f"Bad request: {error}")
        error_response = ErrorResponse(
            error="BadRequest",
            message="The request was invalid or cannot be served",
            details={"description": str(error)}
        )
        return jsonify(error_response.model_dump()), 400


    @app.errorhandler(404)
    def not_found_handler(error) -> Response:
        """
        Handle 404 Not Found errors.
        
        Args:
            error: Error details
        
        Returns:
            JSON error response
        """
        logger.warning(f"Resource not found: {error}")
        error_response = ErrorResponse(
            error="NotFound",
            message="The requested resource was not found",
            details={"path": request.path}
        )
        return jsonify(error_response.model_dump()), 404


    @app.errorhandler(405)
    def method_not_allowed_handler(error) -> Response:
        """
        Handle 405 Method Not Allowed errors.
        
        Args:
            error: Error details
        
        Returns:
            JSON error response
        """
        logger.warning(f"Method not allowed: {request.method} {request.path}")
        error_response = ErrorResponse(
            error="MethodNotAllowed",
            message=f"Method {request.method} not allowed for this endpoint",
            details={"method": request.method, "path": request.path}
        )
        return jsonify(error_response.model_dump()), 405


    @app.errorhandler(413)
    def request_entity_too_large_handler(error) -> Response:
        """
        Handle 413 Request Entity Too Large errors.
        
        Args:
            error: Error details
        
        Returns:
            JSON error response
        """
        logger.warning(f"File too large: {error}")
        error_response = ErrorResponse(
            error="FileTooLarge",
            message="The uploaded file is too large",
            details={"max_size": f"{config.MAX_CONTENT_LENGTH / (1024*1024):.0f}MB"}
        )
        return jsonify(error_response.model_dump()), 413


    @app.errorhandler(500)
    def internal_server_error_handler(error) -> Response:
        """
        Handle 500 Internal Server Error.
        
        Args:
            error: Error details
        
        Returns:
            JSON error response
        """
        logger.error(f"Internal server error: {error}", exc_info=True)
        error_response = ErrorResponse(
            error="InternalServerError",
            message="An unexpected error occurred on the server",
            details={"type": type(error).__name__}
        )
        return jsonify(error_response.model_dump()), 500


    @app.errorhandler(PydanticValidationError)
    def validation_error_handler(error: PydanticValidationError) -> Response:
        """
        Handle Pydantic validation errors with user-friendly messages.
        
        Args:
            error: Pydantic validation error
        
        Returns:
            JSON error response with user-friendly validation details
        """
        # Extract error details
        errors = error.errors()
        
        # Create user-friendly message
        if len(errors) == 1:
            err = errors[0]
            field = err.get('loc', ['field'])[-1]  # Get last field name
            error_type = err.get('type', 'validation_error')
            
            # Create specific user-friendly messages
            if error_type == 'string_too_long':
                max_length = err.get('ctx', {}).get('max_length', 5000)
                input_length = len(str(err.get('input', '')))
                user_message = (
                    f"Your {field} is too long ({input_length:,} characters). "
                    f"Please shorten it to {max_length:,} characters or less."
                )
            elif error_type == 'string_too_short':
                min_length = err.get('ctx', {}).get('min_length', 1)
                user_message = f"Your {field} must be at least {min_length} character(s) long."
            elif error_type == 'value_error':
                user_message = f"Invalid {field}: {err.get('msg', 'Please check your input')}"
            elif error_type == 'missing':
                user_message = f"Required field '{field}' is missing."
            else:
                user_message = f"Invalid {field}: {err.get('msg', 'Please check your input')}"
                
            logger.warning(f"Validation error: {user_message}")
        else:
            # Multiple errors
            user_message = "Multiple validation errors occurred:\n"
            for idx, err in enumerate(errors[:3], 1):  # Show max 3 errors
                field = err.get('loc', ['field'])[-1]
                user_message += f"{idx}. {field}: {err.get('msg', 'Invalid value')}\n"
            if len(errors) > 3:
                user_message += f"... and {len(errors) - 3} more error(s)."
            logger.warning(f"Multiple validation errors: {len(errors)} total")
        
        # Create response with both user-friendly and technical details
        error_response = ErrorResponse(
            error="ValidationError",
            message=user_message,
            details={
                "errors": errors,
                "help": "Please check your input and try again. If you're copying from another source, try shortening your message or breaking it into smaller parts."
            }
        )
        return jsonify(error_response.model_dump()), 400


    @app.errorhandler(exceptions.LocalChatException)
    def localchat_exception_handler(error: exceptions.LocalChatException) -> Response:
        """
        Handle custom LocalChat exceptions.
        
        Args:
            error: LocalChat custom exception
        
        Returns:
            JSON error response
        """
        status_code = exceptions.get_status_code(error)
        logger.error(f"{error.__class__.__name__}: {error.message}", extra=error.details)
        
        error_response = ErrorResponse(
            error=error.__class__.__name__,
            message=error.message,
            details=error.details
        )
        return jsonify(error_response.model_dump()), status_code
    
    logger.info("✅ Month 2 error handlers registered")
else:
    logger.info("ℹ️  Using basic error handlers (Month 1 mode)")
# ============================================================================
# WEB ROUTES
# ============================================================================

@app.route('/favicon.ico')
def favicon() -> Response:
    """
    Serve favicon or return 204 No Content if not found.
    
    Prevents 404 errors in browser console.
    
    Returns:
        Favicon file or 204 status code
    """
    favicon_path = Path(ROOT_DIR) / 'static' / 'favicon.ico'
    if favicon_path.exists():
        return app.send_static_file('favicon.ico')
    return '', 204


@app.route('/')
def index() -> str:
    """
    Redirect to chat page.
    
    Returns:
        Rendered chat template
    """
    return render_template('chat.html')


@app.route('/chat')
def chat() -> str:
    """
    Render chat page.
    
    Returns:
        Rendered chat template
    """
    return render_template('chat.html')


@app.route('/documents')
def documents() -> str:
    """
    Render document management page.
    
    Returns:
        Rendered documents template
    """
    return render_template('documents.html')


@app.route('/models')
def models() -> str:
    """
    Render model management page.
    
    Returns:
        Rendered models template
    """
    return render_template('models.html')


@app.route('/overview')
def overview() -> str:
    """
    Render overview page.
    
    Returns:
        Rendered overview template
    """
    return render_template('overview.html')


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/status')
def api_status() -> Response:
    """
    Get system status.
    
    Returns:
        JSON response with service status information
    
    Example:
        >>> GET /api/status
        {
            "ollama": true,
            "database": true,
            "ready": true,
            "active_model": "llama3.2",
            "document_count": 5
        }
    """
    active_model = config.app_state.get_active_model()
    doc_count = db.get_document_count() if startup_status['database'] else 0
    
    return jsonify({
        'ollama': startup_status['ollama'],
        'database': startup_status['database'],
        'ready': startup_status['ready'],
        'active_model': active_model,
        'document_count': doc_count
    })


@app.route('/api/models')
def api_list_models() -> Response:
    """
    List all available Ollama models.
    
    Returns:
        JSON response with model list
    
    Example:
        >>> GET /api/models
        {
            "success": true,
            "models": [
                {"name": "llama3.2", "size": 4500000000, ...},
                ...
            ]
        }
    """
    success, models = ollama_client.list_models()
    return jsonify({
        'success': success,
        'models': models
    })


@app.route('/api/models/active', methods=['GET', 'POST'])
def api_active_model() -> Response:
    """
    Get or set the active model.
    
    Month 2: Uses ModelRequest validation
    Month 1: Uses basic validation
    
    Returns:
        JSON response with active model info
    """
    try:
        if request.method == 'POST':
            data = request.get_json()
            
            # Month 2: Pydantic validation + sanitization
            if MONTH2_ENABLED:
                request_data = ModelRequest(**data)
                model_name = sanitize_model_name(request_data.model)
            # Month 1: Basic validation
            else:
                model_name = data.get('model', '').strip()
                
                if not model_name:
                    logger.warning("Model name not provided in request")
                    return jsonify({'success': False, 'message': 'Model name required'}), 400
            
            logger.info(f"Setting active model to: {model_name}")
            
            # Verify model exists
            success, models = ollama_client.list_models()
            if not success:
                error_msg = "Failed to list models"
                logger.error(error_msg)
                if MONTH2_ENABLED:
                    raise exceptions.OllamaConnectionError(error_msg)
                else:
                    return jsonify({'success': False, 'message': error_msg}), 503
            
            model_names = [m['name'] for m in models]
            if model_name not in model_names:
                error_msg = f"Model '{model_name}' not found"
                logger.warning(error_msg)
                if MONTH2_ENABLED:
                    raise exceptions.InvalidModelError(error_msg, details={'requested': model_name, 'available': model_names[:10]})
                else:
                    return jsonify({'success': False, 'message': error_msg}), 404
            
            config.app_state.set_active_model(model_name)
            logger.info(f"Active model changed to: {model_name}")
            return jsonify({'success': True, 'model': model_name})
        
        else:  # GET
            active_model = config.app_state.get_active_model()
            return jsonify({'model': active_model})
            
    except Exception as e:
        if MONTH2_ENABLED and isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):
            raise
        else:
            logger.error(f"Error in active_model endpoint: {e}", exc_info=True)
            return jsonify({'success': False, 'message': 'Failed to get/set active model'}), 500


@app.route('/api/models/pull', methods=['POST'])
def api_pull_model() -> Response:
    """
    Pull a new model.
    
    Month 2: Uses ModelPullRequest validation
    Month 1: Uses basic validation
    """
    try:
        data = request.get_json()
        
        # Month 2: Pydantic validation + sanitization
        if MONTH2_ENABLED:
            request_data = ModelPullRequest(**data)
            model_name = sanitize_model_name(request_data.model)
        # Month 1: Basic validation
        else:
            model_name = data.get('model', '').strip()
            
            if not model_name:
                return jsonify({'success': False, 'message': 'Model name required'}), 400
        
        logger.info(f"Pulling model: {model_name}")
        
        def generate() -> Generator[str, None, None]:
            try:
                for progress in ollama_client.pull_model(model_name):
                    yield f"data: {json.dumps(progress)}\n\n"
            except Exception as e:
                logger.error(f"Error pulling model: {e}", exc_info=True)
                error_msg = json.dumps({'error': str(e)})
                yield f"data: {error_msg}\n\n"
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
        
    except Exception as e:
        if MONTH2_ENABLED and isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):
            raise
        else:
            logger.error(f"Error in pull_model endpoint: {e}", exc_info=True)
            return jsonify({'success': False, 'message': 'Failed to pull model'}), 500


@app.route('/api/models/delete', methods=['DELETE'])
def api_delete_model() -> Response:
    """
    Delete a model.
    
    Month 2: Uses ModelDeleteRequest validation
    Month 1: Uses basic validation
    """
    try:
        data = request.get_json()
        
        # Month 2: Pydantic validation + sanitization
        if MONTH2_ENABLED:
            request_data = ModelDeleteRequest(**data)
            model_name = sanitize_model_name(request_data.model)
        # Month 1: Basic validation
        else:
            model_name = data.get('model', '').strip()
            
            if not model_name:
                return jsonify({'success': False, 'message': 'Model name required'}), 400
        
        logger.info(f"Deleting model: {model_name}")
        
        success, message = ollama_client.delete_model(model_name)
        
        if not success:
            error_msg = f"Failed to delete model: {message}"
            logger.error(error_msg)
            if MONTH2_ENABLED:
                raise exceptions.InvalidModelError(error_msg, details={"model": model_name})
            else:
                return jsonify({'success': False, 'message': error_msg}), 500
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        if MONTH2_ENABLED and isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):
            raise
        else:
            logger.error(f"Error deleting model: {e}", exc_info=True)
            return jsonify({'success': False, 'message': 'Failed to delete model'}), 500


@app.route('/api/models/test', methods=['POST'])
def api_test_model() -> Response:
    """
    Test a model.
    
    Month 2: Uses ModelRequest validation
    Month 1: Uses basic validation
    """
    try:
        data = request.get_json()
        
        # Month 2: Pydantic validation + sanitization
        if MONTH2_ENABLED:
            request_data = ModelRequest(**data)
            model_name = sanitize_model_name(request_data.model)
        # Month 1: Basic validation
        else:
            model_name = data.get('model', '').strip()
            
            if not model_name:
                return jsonify({'success': False, 'message': 'Model name required'}), 400
        
        logger.info(f"Testing model: {model_name}")
        
        success, result = ollama_client.test_model(model_name)
        
        return jsonify({'success': success, 'result': result})
        
    except Exception as e:
        if MONTH2_ENABLED and isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):
            raise
        else:
            logger.error(f"Error testing model: {e}", exc_info=True)
            return jsonify({'success': False, 'message': 'Failed to test model'}), 500


# RAG System Prompt - Forces model to use ONLY provided context
RAG_SYSTEM_PROMPT = """You are a precise AI assistant that answers questions based STRICTLY on the provided document context.

MANDATORY RULES:
1. ONLY use information explicitly stated in the provided context
2. If the answer is NOT in the context, respond EXACTLY: "I don't have that information in the provided documents."
3. NEVER use external knowledge, assumptions, or inferences
4. ALWAYS cite the source document when answering: [Source: filename]
5. Be concise and factual - quote directly from context when appropriate
6. If the context is unclear or ambiguous, say so
7. Do NOT elaborate beyond what the context states

You are a document search assistant, not a general knowledge AI. Your credibility depends on accuracy, not helpfulness."""

@app.route('/api/chat', methods=['POST'])
def api_chat() -> Response:
    """
    Chat endpoint with RAG or direct LLM.
    
    Month 2: Uses Pydantic validation
    Month 1: Uses basic validation
    
    Request Body:
        - message (str): User's message
        - use_rag (bool): Whether to use RAG mode (default: true)
        - history (list): Chat history
    
    Returns:
        Server-Sent Events stream with chat response
    """
    try:
        data = request.get_json()
        
        # Month 2: Pydantic validation + sanitization
        if MONTH2_ENABLED:
            request_data = ChatRequest(**data)
            message = sanitize_query(request_data.message)
            use_rag = request_data.use_rag
            chat_history = request_data.history
        # Month 1: Basic validation
        else:
            message = data.get('message', '').strip()
            use_rag = data.get('use_rag', True)
            chat_history = data.get('history', [])
            
            # Basic validation
            if not message:
                logger.warning("Empty message in chat request")
                return jsonify({'success': False, 'message': 'Message required'}), 400
            if len(message) > 5000:
                logger.warning("Message too long in chat request")
                return jsonify({'success': False, 'message': 'Message too long (max 5000 chars)'}), 400
        
        logger.info(f"[CHAT API] Request - RAG Mode: {use_rag}, Query: {message[:50]}...")
        logger.debug(f"[CHAT API] History length: {len(chat_history)}")
        
        active_model = config.app_state.get_active_model()
        if not active_model:
            error_msg = "No active model set"
            logger.error(error_msg)
            if MONTH2_ENABLED:
                raise exceptions.InvalidModelError(error_msg)
            else:
                return jsonify({'success': False, 'message': error_msg}), 400
        
        logger.debug(f"[CHAT API] Using model: {active_model}")
        
        # Prepare messages
        messages = []
        
        # Add chat history
        for msg in chat_history:
            messages.append({
                'role': msg.get('role', 'user'),
                'content': msg.get('content', '')
            })
        
        # Store original message for later
        original_message = message
        
        # If RAG mode, retrieve context
        if use_rag:
            logger.debug("[RAG] Retrieving context from documents...")
            try:
                results = doc_processor.retrieve_context(message)
                logger.info(f"[RAG] Database search returned {len(results)} chunks")
                
                if results:
                    # Build structured context with clear source attribution
                    context_parts = []
                    for idx, (chunk_text, filename, chunk_index, similarity) in enumerate(results, 1):
                        logger.debug(f"[RAG]   ✓ {filename} chunk {chunk_index}: similarity {similarity:.3f}")
                        context_parts.append(
                            f"Document {idx}: {filename} (chunk {chunk_index}, relevance: {similarity:.2f})\n"
                            f"Content: {chunk_text}\n"
                        )
                    
                    full_context = "\n---\n\n".join(context_parts)
                    
                    # Add RAG system prompt as first message
                    if not messages or messages[0].get('role') != 'system':
                        messages.insert(0, {
                            'role': 'system',
                            'content': RAG_SYSTEM_PROMPT
                        })
                        logger.debug("[RAG] Added strict RAG system prompt")
                    
                    # Format user message with context and clear instructions
                    user_prompt = f"""Here is the context from your documents:

{full_context}

---

Question: {original_message}

Remember: Answer ONLY based on the context above. If the information is not in the context, say "I don't have that information in the provided documents." Do not use external knowledge."""
                    
                    message = user_prompt
                    logger.info(f"[CHAT API] Context added - {len(results)} chunks, {len(message)} chars total")
                else:
                    logger.warning("[RAG] No chunks retrieved - check if documents are indexed")
                    # Add system message indicating no context available
                    if not messages or messages[0].get('role') != 'system':
                        messages.insert(0, {
                            'role': 'system',
                            'content': "You are a helpful AI assistant. The user asked about documents, but no relevant documents were found. Politely let them know that no documents contain information about their query."
                        })
                        logger.debug("[RAG] Added 'no context' system prompt")
            except Exception as e:
                error_msg = f"Failed to retrieve context: {str(e)}"
                logger.error(error_msg, exc_info=True)
                if MONTH2_ENABLED:
                    raise exceptions.SearchError(error_msg, details={"error": str(e)})
                # In Month 1 mode, continue without context
                logger.warning("[RAG] Continuing without context due to error")
        else:
            logger.debug("[CHAT API] Direct LLM mode - no RAG")
        
        messages.append({'role': 'user', 'content': message})
        logger.debug(f"[CHAT API] Total messages in conversation: {len(messages)}")
        
        # Stream response
        def generate() -> Generator[str, None, None]:
            try:
                logger.debug("[CHAT API] Starting response stream...")
                for chunk in ollama_client.generate_chat_response(active_model, messages, stream=True):
                    yield f"data: {json.dumps({'content': chunk})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                logger.debug("[CHAT API] Response stream completed")
            except Exception as e:
                logger.error(f"[CHAT API] Error generating response: {e}", exc_info=True)
                error_msg = json.dumps({
                    'error': 'GenerationError',
                    'message': 'Failed to generate response'
                })
                yield f"data: {error_msg}\n\n"
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
        
    except Exception as e:
        if MONTH2_ENABLED and isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):
            raise  # Let error handler deal with it
        else:
            logger.error(f"[CHAT API] Unexpected error: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'message': 'An unexpected error occurred during chat'
            }), 500


@app.route('/api/documents/upload', methods=['POST'])
def api_upload_documents() -> Response:
    """Upload and ingest documents."""
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    
    if not files or files[0].filename == '':
        return jsonify({'success': False, 'message': 'No files selected'}), 400
    
    # Save files temporarily
    file_paths = []
    for file in files:
        if file.filename:
            # Check extension
            ext = Path(file.filename).suffix.lower()
            if ext in config.SUPPORTED_EXTENSIONS:
                file_path = os.path.join(config.UPLOAD_FOLDER, file.filename)
                file.save(file_path)
                file_paths.append(file_path)
    
    if not file_paths:
        return jsonify({'success': False, 'message': 'No supported files found'}), 400
    
    # Stream ingestion progress
    def generate() -> Generator[str, None, None]:
        def progress_callback(message):
            yield f"data: {json.dumps({'message': message})}\n\n"
        
        results = []
        for file_path in file_paths:
            for msg in progress_callback(f"Processing {os.path.basename(file_path)}..."):
                yield msg
            
            success, message, doc_id = doc_processor.ingest_document(
                file_path,
                lambda m: None  # We'll handle progress differently
            )
            
            results.append({
                'filename': os.path.basename(file_path),
                'success': success,
                'message': message
            })
            
            yield f"data: {json.dumps({'result': results[-1]})}\n\n"
            
            # Clean up temporary file
            try:
                os.remove(file_path)
            except:
                pass
        
        # Update document count
        doc_count = db.get_document_count()
        config.app_state.set_document_count(doc_count)
        
        yield f"data: {json.dumps({'done': True, 'total_documents': doc_count})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/api/documents/list')
def api_list_documents() -> Response:
    """
    List all documents.
    
    Returns:
        JSON response with document list
    
    Example:
        >>> GET /api/documents/list
        {
            "success": true,
            "documents": [
                {"id": "abc123", "title": "My Document", ...},
                ...
            ]
        }
    """
    try:
        documents = db.get_all_documents()
        return jsonify({
            'success': True,
            'documents': documents
        })
    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/documents/test', methods=['POST'])
def api_test_retrieval() -> Response:
    """
    Test RAG retrieval.
    
    Month 2: Uses RetrievalRequest validation
    Month 1: Uses basic validation
    
    Request Body:
        - query (str): Search query
        - top_k (int, optional): Number of results
        - min_similarity (float, optional): Min similarity threshold
        - file_type_filter (str, optional): File type filter
    
    Returns:
        JSON response with retrieval results
    """
    try:
        data = request.get_json()
        
        # Month 2: Pydantic validation + sanitization
        if MONTH2_ENABLED:
            request_data = RetrievalRequest(**data)
            query = sanitize_query(request_data.query)
        # Month 1: Basic validation
        else:
            query = data.get('query', 'What is this about?').strip()
            
            # Basic validation
            if not query:
                logger.warning("Empty query in test retrieval request")
                return jsonify({'success': False, 'message': 'Query required'}), 400
            if len(query) > 1000:
                logger.warning("Query too long in test retrieval request")
                return jsonify({'success': False, 'message': 'Query too long (max 1000 chars)'}), 400
        
        logger.info(f"Testing retrieval: {query[:50]}...")
        
        success, results = doc_processor.test_retrieval(query)
        
        return jsonify({
            'success': success,
            'results': results
        })
        
    except Exception as e:
        if MONTH2_ENABLED and isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):
            raise  # Let error handler deal with it
        else:
            logger.error(f"Error in test_retrieval: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'message': 'Failed to test retrieval'
            }), 500


@app.route('/api/documents/stats')
def api_document_stats() -> Response:
    """
    Get document statistics.
    
    Returns:
        JSON response with document and chunk counts
    
    Example:
        >>> GET /api/documents/stats
        {
            "success": true,
            "document_count": 10,
            "chunk_count": 25
        }
    """
    try:
        doc_count = db.get_document_count()
        chunk_count = db.get_chunk_count()
        
        return jsonify({
            'success': True,
            'document_count': doc_count,
            'chunk_count': chunk_count
        })
    except Exception as e:
        logger.error(f"Error getting document stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/documents/clear', methods=['DELETE'])
def api_clear_documents() -> Response:
    """
    Clear all documents and chunks from the database.
    
    Warning: This operation cannot be undone!
    
    Returns:
        JSON response with success status
    
    Example:
        >>> DELETE /api/documents/clear
        {"success": true, "message": "All documents and chunks have been deleted"}
    """
    try:
        logger.warning("Clearing all documents from database")
        db.delete_all_documents()
        
        # Update document count in app state
        config.app_state.set_document_count(0)
        
        logger.info("All documents cleared successfully")
        return jsonify({
            'success': True,
            'message': 'All documents and chunks have been deleted'
        })
    except Exception as e:
        logger.error(f"Error clearing documents: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


if __name__ == '__main__':
    # Perform startup checks
    startup_checks()
    
    # Start server
    HOST = os.environ.get('SERVER_HOST', 'localhost')
    try:
        PORT = int(os.environ.get('SERVER_PORT', '5000'))
    except ValueError:
        PORT = 5000
    
    logger.info(f"Starting Flask server on {HOST}:{PORT}")
    
    # Run the app - cleanup handlers will take care of shutdown
    app.run(HOST, PORT, debug=True, use_reloader=False)  # Disable reloader to avoid double cleanup

