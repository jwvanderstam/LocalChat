# -*- coding: utf-8 -*-

"""
API Routes Blueprint
===================

Core API endpoints for LocalChat application.
Handles status checks, chat (RAG and direct LLM), and core API functionality.

Author: LocalChat Team
Created: 2025-01-15
Last Updated: 2025-01-27
"""

from flask import Blueprint, jsonify, request, Response
from flask import current_app as _current_app
from typing import Dict, Any, Generator, TYPE_CHECKING
import json

if TYPE_CHECKING:
    from ..types import LocalChatApp
    current_app: LocalChatApp
else:
    current_app = _current_app

from .. import config
from .. import exceptions
from ..utils.logging_config import get_logger

try:
    from pydantic import ValidationError as PydanticValidationError
except ImportError:
    class _FallbackValidationError(ValueError):
        """Fallback exception when Pydantic is not available"""
        pass
    PydanticValidationError = _FallbackValidationError

bp = Blueprint('api', __name__)
logger = get_logger(__name__)


@bp.route('/status')
def api_status():
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
    active_model = config.app_state.get_active_model()

    # Get document count with error handling for closed pool
    doc_count = 0
    db_available = current_app.startup_status.get('database', False)

    if db_available:
        try:
            doc_count = current_app.db.get_document_count()
        except Exception as e:
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
    try:
        data = request.get_json()
        if not data or not isinstance(data, dict):
            return jsonify({'success': False, 'message': 'Request body must be valid JSON'}), 400

        # Import validation modules
        try:
            from ..models import ChatRequest
            from ..utils.sanitization import sanitize_query

            # Pydantic validation + sanitization
            request_data = ChatRequest(**data)
            message = sanitize_query(request_data.message)
            use_rag = request_data.use_rag
            enhance = request_data.enhance and config.WEB_SEARCH_ENABLED
            chat_history = request_data.history
            conversation_id = request_data.conversation_id
            images = request_data.images or []

        except ImportError as e:
            logger.error(f"Failed to import required modules: {e}")
            return jsonify({'success': False, 'message': 'Server configuration error'}), 500
        
        logger.info(f"[CHAT API] Request - RAG Mode: {use_rag}, Enhanced: {enhance}, Query: {message[:50]}...")
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
        
        # System prompts
        RAG_SYSTEM_PROMPT = """You are a helpful assistant that answers questions based strictly on the provided context passages.

Rules:
1. Answer directly and concisely using only information from the provided context.
2. If the answer is not in the context, say: "I don't have that information in the provided documents."
3. Do not describe the document structure or list section names — synthesize the content into a clear, direct answer.
4. Do not reference internal identifiers like chunk numbers or section indices.
5. Only use bullet points or tables when the content genuinely benefits from that structure.
6. You may mention the source document name when it adds useful context."""

        ENHANCED_SYSTEM_PROMPT = """You are a helpful assistant that answers questions using both uploaded documents and live web search results.

Rules:
1. Synthesize information from both local documents and web sources into a single clear answer.
2. Prefer local document content when it directly answers the question.
3. Use web sources to fill gaps, provide current information, or verify facts.
4. When citing web sources, mention the URL or site name briefly.
5. Do not list section names or describe document structure — give a direct answer.
6. Only use bullet points or tables when the content genuinely benefits from that structure."""

        # If RAG mode, retrieve context
        local_context_block = ""
        web_context_block = ""

        if use_rag:
            logger.debug("[RAG] Retrieving context from documents...")
            try:
                results = current_app.doc_processor.retrieve_context(message)
                logger.info(f"[RAG] Retrieved {len(results)} chunks from database")

                if results:
                    local_context_block = current_app.doc_processor.format_context_for_llm(
                        results, max_length=6000
                    )
                    for idx, (_, filename, chunk_index, similarity, metadata) in enumerate(results, 1):
                        log_parts = [f"[RAG] Result {idx}: {filename} chunk {chunk_index}: similarity {similarity:.3f}"]
                        if metadata.get('page_number'):
                            log_parts.append(f"page {metadata['page_number']}")
                        if metadata.get('section_title'):
                            log_parts.append(f"section: {metadata['section_title'][:30]}")
                        logger.debug(" ".join(log_parts))
                else:
                    logger.warning("[RAG] No chunks retrieved from documents")

            except Exception as e:
                error_msg = f"Failed to retrieve context: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise exceptions.SearchError(error_msg, details={"error": str(e)})

        if enhance:
            logger.info("[ENHANCED] Running web search...")
            try:
                from ..rag.web_search import WebSearchProvider
                searcher = WebSearchProvider()
                web_results = searcher.search(original_message)
                if web_results:
                    web_context_block = searcher.format_web_context(web_results, max_length=4000)
                    logger.info(f"[ENHANCED] Got {len(web_results)} web result(s)")
                else:
                    logger.warning("[ENHANCED] Web search returned no results")
            except Exception as web_err:
                logger.warning(f"[ENHANCED] Web search failed, continuing without: {web_err}")

        # Build combined prompt
        has_local = bool(local_context_block)
        has_web = bool(web_context_block)

        if has_local or has_web:
            system_prompt = ENHANCED_SYSTEM_PROMPT if enhance else RAG_SYSTEM_PROMPT
            if not messages or messages[0].get('role') != 'system':
                messages.insert(0, {'role': 'system', 'content': system_prompt})

            context_sections: list = []
            if has_local:
                context_sections.append("=== Local Document Context ===\n" + local_context_block)
            if has_web:
                context_sections.append("=== Web Search Results ===\n" + web_context_block)

            combined_context = "\n\n".join(context_sections)
            message = f"""{combined_context}\n\n---\n\nQuestion: {original_message}\n\nAnswer the question directly using the information above. Synthesize the relevant content into a clear response."""
            logger.info(f"[CHAT API] Context ready — local: {has_local}, web: {has_web}")
        elif use_rag:
            if not messages or messages[0].get('role') != 'system':
                messages.insert(0, {
                    'role': 'system',
                    'content': "You are a helpful AI assistant. No relevant documents or web results were found."
                })
        else:
            logger.debug("[CHAT API] Direct LLM mode - no RAG")

        user_message: Dict[str, Any] = {'role': 'user', 'content': message}
        if images:
            user_message['images'] = images
            logger.info(f"[CHAT API] Attaching {len(images)} image(s) to request")
        messages.append(user_message)

        # Persistent memory: create or reuse a conversation, then save the user message
        if current_app.startup_status.get('database', False):
            try:
                if not conversation_id:
                    title = original_message[:60] + ('...' if len(original_message) > 60 else '')
                    conversation_id = current_app.db.create_conversation(title)
                    logger.debug(f"[MEMORY] Created conversation: {conversation_id}")
                current_app.db.save_message(conversation_id, 'user', original_message)
                logger.debug(f"[MEMORY] Saved user message to conversation {conversation_id}")
            except Exception as mem_err:
                logger.warning(f"[MEMORY] Could not persist user message: {mem_err}")
                conversation_id = None

        # Capture app object before entering generator
        app = current_app._get_current_object()  # type: ignore[attr-defined]

        # Initialize tool executor when tool calling is enabled
        _tool_executor = None
        if config.TOOL_CALLING_ENABLED:
            try:
                from ..tools import tool_registry, ToolExecutor

                if len(tool_registry) > 0:
                    _tool_executor = ToolExecutor(app.ollama_client, tool_registry)
                    logger.debug(
                        f"[CHAT API] Tool calling enabled with {len(tool_registry)} tool(s): "
                        f"{', '.join(tool_registry.names)}"
                    )
            except ImportError:
                logger.debug("[CHAT API] Tools module not available, skipping")

        # Stream response
        def generate() -> Generator[str, None, None]:
            full_response: list = []
            try:
                logger.debug("[CHAT API] Starting response stream...")

                if _tool_executor is not None:
                    response_stream = _tool_executor.execute(
                        active_model, messages, stream=True
                    )
                else:
                    response_stream = app.ollama_client.generate_chat_response(
                        active_model, messages, stream=True
                    )

                for chunk in response_stream:
                    full_response.append(chunk)
                    yield f"data: {json.dumps({'content': chunk})}\n\n"

                # Save assistant response to persistent memory
                if conversation_id:
                    try:
                        app.db.save_message(conversation_id, 'assistant', ''.join(full_response))
                        logger.debug(f"[MEMORY] Saved assistant message to conversation {conversation_id}")
                    except Exception as mem_err:
                        logger.warning(f"[MEMORY] Could not persist assistant message: {mem_err}")

                done_payload: dict = {'done': True}
                if conversation_id:
                    done_payload['conversation_id'] = conversation_id
                yield f"data: {json.dumps(done_payload)}\n\n"
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
