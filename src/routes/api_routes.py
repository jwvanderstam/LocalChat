# -*- coding: utf-8 -*-

"""
API Routes Blueprint
===================

Core API endpoints for LocalChat application.
Handles status checks and core API functionality.

Author: LocalChat Team
Created: 2025-01-15
"""

from flask import Blueprint, jsonify, current_app
from typing import Dict, Any

bp = Blueprint('api', __name__)


@bp.route('/status')
def api_status() -> Dict[str, Any]:
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
    from .. import config
    
    active_model = config.app_state.get_active_model()
    doc_count = (
        current_app.db.get_document_count() 
        if current_app.startup_status['database'] 
        else 0
    )
    
    return jsonify({
        'ollama': current_app.startup_status['ollama'],
        'database': current_app.startup_status['database'],
        'ready': current_app.startup_status['ready'],
        'active_model': active_model,
        'document_count': doc_count
    })


@bp.route('/chat', methods=['POST'])
def api_chat():
    """
    Chat endpoint with RAG or direct LLM.
    
    Handles chat requests with optional RAG context retrieval.
    Supports streaming responses via Server-Sent Events.
    
    Request Body:
        - message (str): User's message
        - use_rag (bool): Whether to use RAG mode (default: true)
        - history (list): Chat history
    
    Returns:
        Server-Sent Events stream with chat response
    """
    from flask import request, Response
    from typing import Generator
    import json
    from .. import config
    from ..utils.logging_config import get_logger
    
    logger = get_logger(__name__)
    
    try:
        data = request.get_json()
        
        # Import validation modules conditionally
        try:
            from pydantic import ValidationError as PydanticValidationError
            from ..models import ChatRequest
            from ..utils.sanitization import sanitize_query
            from .. import exceptions
            
            # Pydantic validation + sanitization
            request_data = ChatRequest(**data)
            message = sanitize_query(request_data.message)
            use_rag = request_data.use_rag
            chat_history = request_data.history
            month2_enabled = True
            
        except ImportError:
            # Basic validation (Month 1 mode)
            message = data.get('message', '').strip()
            use_rag = data.get('use_rag', True)
            chat_history = data.get('history', [])
            month2_enabled = False
            
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
            if month2_enabled:
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
        
        # Store original message
        original_message = message
        
        # RAG System Prompt
        RAG_SYSTEM_PROMPT = """You are an ULTRA-PRECISE document analysis AI that provides COMPREHENSIVE and DETAILED answers using ONLY the provided context.

ABSOLUTE RULES - NO EXCEPTIONS:
1. ?? ONLY use information EXPLICITLY stated in the provided context
2. ?? If the answer is NOT in the context, respond EXACTLY: "I don't have that information in the provided documents."
3. ?? NEVER use external knowledge, prior training, assumptions, or inferences
4. ?? ALWAYS cite the source: [Source: filename]
5. ?? For numbers/data: Quote EXACT values from context

RESPONSE QUALITY:
- Be COMPREHENSIVE and DETAILED
- Use proper formatting (paragraphs, bullets, tables)
- Combine information from multiple sources
- Provide CONTEXT around facts

REMEMBER: Your value is in providing COMPLETE, ACCURATE information from the documents."""
        
        # If RAG mode, retrieve context
        if use_rag:
            logger.debug("[RAG] Retrieving context from documents...")
            try:
                results = current_app.doc_processor.retrieve_context(message)
                logger.info(f"[RAG] Retrieved {len(results)} chunks from database")
                
                if results:
                    # Format context
                    formatted_context = current_app.doc_processor.format_context_for_llm(
                        results, max_length=6000
                    )
                    
                    # Log results
                    for idx, (_, filename, chunk_index, similarity) in enumerate(results, 1):
                        logger.debug(f"[RAG]   ? Result {idx}: {filename} chunk {chunk_index}: similarity {similarity:.3f}")
                    
                    # Add RAG system prompt
                    if not messages or messages[0].get('role') != 'system':
                        messages.insert(0, {
                            'role': 'system',
                            'content': RAG_SYSTEM_PROMPT
                        })
                    
                    # Format user message with context
                    user_prompt = f"""{formatted_context}

---

Question: {original_message}

Remember: Answer ONLY based on the context above."""
                    
                    message = user_prompt
                    logger.info(f"[CHAT API] Context formatted - {len(results)} chunks")
                else:
                    logger.warning("[RAG] No chunks retrieved")
                    if not messages or messages[0].get('role') != 'system':
                        messages.insert(0, {
                            'role': 'system',
                            'content': "You are a helpful AI assistant. No relevant documents were found."
                        })
                        
            except Exception as e:
                error_msg = f"Failed to retrieve context: {str(e)}"
                logger.error(error_msg, exc_info=True)
                if month2_enabled:
                    raise exceptions.SearchError(error_msg, details={"error": str(e)})
                logger.warning("[RAG] Continuing without context")
        else:
            logger.debug("[CHAT API] Direct LLM mode - no RAG")
        
        messages.append({'role': 'user', 'content': message})
        
        # Stream response
        def generate() -> Generator[str, None, None]:
            try:
                logger.debug("[CHAT API] Starting response stream...")
                for chunk in current_app.ollama_client.generate_chat_response(
                    active_model, messages, stream=True
                ):
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
        
        response = Response(generate(), mimetype='text/event-stream')
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Accel-Buffering'] = 'no'
        return response
        
    except Exception as e:
        try:
            if month2_enabled and isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):
                raise
        except:
            pass
        
        logger.error(f"[CHAT API] Unexpected error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'An unexpected error occurred during chat'
        }), 500
