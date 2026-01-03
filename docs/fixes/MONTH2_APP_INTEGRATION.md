# Month 2 Error Handlers and Validation - Add to app.py

## Add these imports at the top of app.py (after existing imports):

```python
# Month 2 additions - Error handling and validation
from pydantic import ValidationError as PydanticValidationError
from datetime import datetime
import exceptions
from models import (
    ChatRequest, ModelRequest, RetrievalRequest,
    ModelPullRequest, ModelDeleteRequest, ErrorResponse
)
from utils.sanitization import (
    sanitize_filename, sanitize_query, sanitize_model_name
)
```

## Add these error handlers after the Flask app setup (after line 68):

```python
# ============================================================================
# ERROR HANDLERS - Month 2
# ============================================================================

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
        details={
            "max_size": f"{config.MAX_CONTENT_LENGTH / (1024*1024):.0f}MB"
        }
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
    Handle Pydantic validation errors.
    
    Args:
        error: Pydantic validation error
    
    Returns:
        JSON error response with validation details
    """
    logger.warning(f"Validation error: {error}")
    error_response = ErrorResponse(
        error="ValidationError",
        message="Request validation failed",
        details={"errors": error.errors()}
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


# ============================================================================
# VALIDATED API ENDPOINTS - Month 2
# ============================================================================

## Replace the existing /api/chat endpoint with this validated version:

@app.route('/api/chat', methods=['POST'])
def api_chat() -> Response:
    """
    Chat endpoint with RAG or direct LLM (with validation).
    
    Validates input using Pydantic models before processing.
    """
    try:
        # Validate request data
        request_data = ChatRequest(**request.get_json())
        
        # Sanitize inputs
        message = sanitize_query(request_data.message)
        use_rag = request_data.use_rag
        chat_history = request_data.history
        
        logger.info(f"Chat request: {message[:50]}... (RAG: {use_rag})")
        logger.debug(f"History length: {len(chat_history)}")
        
        active_model = config.app_state.get_active_model()
        if not active_model:
            raise exceptions.InvalidModelError("No active model set")
        
        logger.debug(f"Using model: {active_model}")
        
        # Prepare messages
        messages = []
        
        # Add chat history
        for msg in chat_history:
            messages.append({
                'role': msg.get('role', 'user'),
                'content': msg.get('content', '')
            })
        
        # If RAG mode, retrieve context
        if use_rag:
            logger.debug("Retrieving context from RAG...")
            try:
                results = doc_processor.retrieve_context(message)
                logger.info(f"Retrieved {len(results)} chunks")
                
                if results:
                    context = "Relevant context from documents:\n\n"
                    for chunk_text, filename, chunk_index, similarity in results:
                        context += f"[{filename}, chunk {chunk_index}, similarity: {similarity:.3f}]\n{chunk_text}\n\n"
                        logger.debug(f"Chunk: {filename} #{chunk_index} (sim: {similarity:.3f})")
                    
                    # Add context to the message
                    message = f"{context}\nUser question: {message}"
                    logger.debug(f"Context added (total length: {len(message)})")
                else:
                    logger.warning("No context retrieved - check if documents are indexed")
            except Exception as e:
                raise exceptions.SearchError("Failed to retrieve context", details={"error": str(e)})
        else:
            logger.debug("Direct LLM mode - no RAG")
        
        messages.append({'role': 'user', 'content': message})
        
        # Stream response
        def generate() -> Generator[str, None, None]:
            try:
                for chunk in ollama_client.generate_chat_response(active_model, messages, stream=True):
                    yield f"data: {json.dumps({'content': chunk})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                logger.error(f"Error generating response: {e}", exc_info=True)
                error_msg = json.dumps({
                    'error': 'GenerationError',
                    'message': 'Failed to generate response'
                })
                yield f"data: {error_msg}\n\n"
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
        
    except PydanticValidationError as e:
        raise  # Let error handler deal with it
    except exceptions.LocalChatException as e:
        raise  # Let error handler deal with it
    except Exception as e:
        logger.error(f"Unexpected error in chat: {e}", exc_info=True)
        raise exceptions.LocalChatException(
            "An unexpected error occurred during chat",
            details={"error": str(e)}
        )


## Replace the existing /api/models/active endpoint:

@app.route('/api/models/active', methods=['GET', 'POST'])
def api_active_model() -> Response:
    """Get or set the active model (with validation)."""
    try:
        if request.method == 'POST':
            # Validate request
            request_data = ModelRequest(**request.get_json())
            
            # Sanitize model name
            model_name = sanitize_model_name(request_data.model)
            
            # Verify model exists
            success, models = ollama_client.list_models()
            if not success:
                raise exceptions.OllamaConnectionError("Failed to list models")
            
            model_names = [m['name'] for m in models]
            if model_name not in model_names:
                raise exceptions.InvalidModelError(
                    f"Model '{model_name}' not found",
                    details={'requested': model_name, 'available': model_names[:10]}
                )
            
            config.app_state.set_active_model(model_name)
            logger.info(f"Active model changed to: {model_name}")
            return jsonify({'success': True, 'model': model_name})
        
        else:  # GET
            active_model = config.app_state.get_active_model()
            return jsonify({'model': active_model})
            
    except PydanticValidationError as e:
        raise
    except exceptions.LocalChatException as e:
        raise
    except Exception as e:
        logger.error(f"Error in active_model endpoint: {e}", exc_info=True)
        raise exceptions.LocalChatException(
            "Failed to get/set active model",
            details={"error": str(e)}
        )


## Replace /api/models/pull:

@app.route('/api/models/pull', methods=['POST'])
def api_pull_model() -> Response:
    """Pull a new model (with validation)."""
    try:
        # Validate request
        request_data = ModelPullRequest(**request.get_json())
        
        # Sanitize model name
        model_name = sanitize_model_name(request_data.model)
        
        logger.info(f"Pulling model: {model_name}")
        
        def generate() -> Generator[str, None, None]:
            try:
                for progress in ollama_client.pull_model(model_name):
                    yield f"data: {json.dumps(progress)}\n\n"
            except Exception as e:
                logger.error(f"Error pulling model: {e}", exc_info=True)
                error_msg = json.dumps({
                    'error': str(e)
                })
                yield f"data: {error_msg}\n\n"
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
        
    except PydanticValidationError as e:
        raise
    except Exception as e:
        logger.error(f"Error in pull_model endpoint: {e}", exc_info=True)
        raise exceptions.LocalChatException(
            "Failed to pull model",
            details={"error": str(e), "model": request.get_json().get('model')}
        )


## Replace /api/models/delete:

@app.route('/api/models/delete', methods=['DELETE'])
def api_delete_model() -> Response:
    """Delete a model (with validation)."""
    try:
        # Validate request
        request_data = ModelDeleteRequest(**request.get_json())
        
        # Sanitize model name
        model_name = sanitize_model_name(request_data.model)
        
        logger.info(f"Deleting model: {model_name}")
        
        success, message = ollama_client.delete_model(model_name)
        
        if not success:
            raise exceptions.InvalidModelError(
                f"Failed to delete model: {message}",
                details={"model": model_name}
            )
        
        return jsonify({'success': True, 'message': message})
        
    except PydanticValidationError as e:
        raise
    except exceptions.LocalChatException as e:
        raise
    except Exception as e:
        logger.error(f"Error deleting model: {e}", exc_info=True)
        raise exceptions.LocalChatException(
            "Failed to delete model",
            details={"error": str(e)}
        )


## Replace /api/documents/test:

@app.route('/api/documents/test', methods=['POST'])
def api_test_retrieval() -> Response:
    """Test RAG retrieval (with validation)."""
    try:
        # Validate request
        request_data = RetrievalRequest(**request.get_json())
        
        # Sanitize query
        query = sanitize_query(request_data.query)
        
        logger.info(f"Testing retrieval: {query[:50]}...")
        
        success, results = doc_processor.test_retrieval(query)
        
        return jsonify({
            'success': success,
            'results': results
        })
        
    except PydanticValidationError as e:
        raise
    except Exception as e:
        logger.error(f"Error in test_retrieval: {e}", exc_info=True)
        raise exceptions.SearchError(
            "Failed to test retrieval",
            details={"error": str(e)}
        )
```

## Save this file as: MONTH2_APP_INTEGRATION.md
