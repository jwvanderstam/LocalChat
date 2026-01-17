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
    
    Provides health check and status information for all services.
    ---
    tags:
      - System
    summary: Get system status
    description: |
      Returns the current status of all system components:
      - Ollama LLM service
      - PostgreSQL database with pgvector
      - Overall system readiness
      - Active model and document count
      - Cache statistics (if enabled)
    responses:
      200:
        description: System status retrieved successfully
        schema:
          $ref: '#/definitions/StatusResponse'
        examples:
          application/json:
            ollama: true
            database: true
            ready: true
            active_model: "llama3.2"
            document_count: 42
            cache:
              embedding:
                hits: 150
                misses: 50
                hit_rate: "75.00%"
              query:
                hits: 80
                misses: 20
                hit_rate: "80.00%"
    """
    from .. import config
    
    active_model = config.app_state.get_active_model()
    
    # Get document count with error handling for closed pool
    doc_count = 0
    db_available = current_app.startup_status.get('database', False)
    
    if db_available:
        try:
            doc_count = current_app.db.get_document_count()
        except Exception as e:
            # Handle closed pool during shutdown or other DB issues
            logger = get_logger(__name__)
            logger.warning(f"Could not get document count: {e}")
            db_available = False
    
    # Get cache stats if available
    cache_stats = {}
    if hasattr(current_app, 'embedding_cache') and current_app.embedding_cache:
        cache_stats['embedding'] = current_app.embedding_cache.get_stats().to_dict()
    
    if hasattr(current_app, 'query_cache') and current_app.query_cache:
        cache_stats['query'] = current_app.query_cache.get_stats().to_dict()
    
    response = {
        'ollama': current_app.startup_status['ollama'],
        'database': db_available,  # Use checked availability
        'ready': current_app.startup_status['ready'] and db_available,  # Ready only if DB is available
        'active_model': active_model,
        'document_count': doc_count
    }
    
    if cache_stats:
        response['cache'] = cache_stats
    
    return jsonify(response)


@bp.route('/chat', methods=['POST'])
def api_chat():
    """
    Chat endpoint with RAG or direct LLM.
    
    Send a chat message and receive AI response with optional RAG context retrieval.
    ---
    tags:
      - Chat
    summary: Send chat message
    description: |
      Chat with the AI assistant. Supports two modes:
      
      **RAG Mode (use_rag=true)**:
      - Retrieves relevant context from uploaded documents
      - Provides accurate, document-based answers
      - Cites sources in responses
      
      **Direct LLM Mode (use_rag=false)**:
      - Direct conversation with the AI model
      - No document context
      - General knowledge responses
      
      Responses are streamed using Server-Sent Events (SSE).
    consumes:
      - application/json
    produces:
      - text/event-stream
    parameters:
      - name: body
        in: body
        required: true
        schema:
          $ref: '#/definitions/ChatRequest'
    responses:
      200:
        description: Chat response stream (Server-Sent Events)
        schema:
          type: object
          properties:
            content:
              type: string
              description: Response chunk content
            done:
              type: boolean
              description: Stream completion flag
        examples:
          text/event-stream: |
            data: {"content": "Based on the documents..."}
            
            data: {"content": " the answer is..."}
            
            data: {"done": true}
      400:
        description: Bad request (invalid message, too long, etc.)
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error during chat processing
        schema:
          $ref: '#/definitions/Error'
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
            
        except ImportError as e:
            logger.error(f"Failed to import required modules: {e}")
            return jsonify({'success': False, 'message': 'Server configuration error'}), 500
        
        logger.info(f"[CHAT API] Request - RAG Mode: {use_rag}, Query: {message[:50]}...")
        logger.debug(f"[CHAT API] History length: {len(chat_history)}")
        
        active_model = config.app_state.get_active_model()
        if not active_model:
            error_msg = "No active model set"
            logger.error(error_msg)
            raise exceptions.InvalidModelError(error_msg)
        
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
        
        # RAG System Prompt - Enhanced for Phase 1.1 with subtle citations
        RAG_SYSTEM_PROMPT = """You are an ULTRA-PRECISE document analysis AI that provides COMPREHENSIVE and DETAILED answers using ONLY the provided context.

ABSOLUTE RULES - NO EXCEPTIONS:
1. ONLY use information EXPLICITLY stated in the provided context
2. If the answer is NOT in the context, respond EXACTLY: "I don't have that information in the provided documents."
3. NEVER use external knowledge, prior training, assumptions, or inferences
4. ALWAYS cite sources but keep citations SUBTLE and NON-INTRUSIVE
5. For numbers/data: Quote EXACT values from context

CITATION STYLE (Keep it subtle!):
Use INLINE parenthetical citations that don't disrupt reading flow:
- Format: (Document name, p.X) - Simple and clean
- Place at END of sentence or paragraph
- DO NOT create separate citation lines or headers
- DO NOT copy the chunk/section format from context headers

GOOD citation examples:
? "The server requires 32GB RAM (Technical Specs, p.15)."
? "Financial terms are specified in the DFA document (OVK Bijlage 05, p.23)."
? "Storage management includes volume creation and LVM configuration (Private Cloud Hosting, p.10)."

BAD citation examples (TOO INTRUSIVE):
? "Section (Chunk 31, Page 10)"
? "Source: document.pdf, page 15, section: System Requirements"
? Creating separate lines for citations

RESPONSE QUALITY:
- Be COMPREHENSIVE and DETAILED
- Use proper formatting (paragraphs, bullets, tables)
- Combine information from multiple sources
- Provide CONTEXT around facts
- Keep citations subtle - at the end of sentences in parentheses

REMEMBER: Citations should be helpful but NOT distracting. Use simple format: (Document, p.X)"""
        
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
                    for idx, (_, filename, chunk_index, similarity, metadata) in enumerate(results, 1):
                        # Enhanced logging with metadata (Phase 1.1)
                        log_parts = [f"[RAG]   ? Result {idx}: {filename} chunk {chunk_index}: similarity {similarity:.3f}"]
                        if metadata.get('page_number'):
                            log_parts.append(f"page {metadata['page_number']}")
                        if metadata.get('section_title'):
                            log_parts.append(f"section: {metadata['section_title'][:30]}")
                        logger.debug(" ".join(log_parts))
                    
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
                raise exceptions.SearchError(error_msg, details={"error": str(e)})
        else:
            logger.debug("[CHAT API] Direct LLM mode - no RAG")
        
        messages.append({'role': 'user', 'content': message})
        
        # Capture app object before entering generator
        app = current_app._get_current_object()
        
        # Stream response
        def generate() -> Generator[str, None, None]:
            try:
                logger.debug("[CHAT API] Starting response stream...")
                for chunk in app.ollama_client.generate_chat_response(
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
        
    except (PydanticValidationError, exceptions.LocalChatException):
        raise  # Let error handlers deal with it
    except Exception as e:
        logger.error(f"[CHAT API] Unexpected error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'An unexpected error occurred during chat'
        }), 500
