
"""
API Routes Blueprint
===================

Core API endpoints for LocalChat application.
Handles status checks, chat (RAG and direct LLM), and core API functionality.

Author: LocalChat Team
Created: 2025-01-15
Last Updated: 2025-01-27
"""

import json
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Generator

from flask import Blueprint, Response, g, jsonify, request
from flask import current_app as _current_app

if TYPE_CHECKING:
    from ..types import LocalChatApp
    current_app: LocalChatApp
else:
    current_app = _current_app

from .. import config, exceptions
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

# TTL cache for document count — /status is polled ~every second by the UI;
# avoid a DB round-trip on every poll by caching for 5 s.
_status_doc_count_cache: list = [0, 0.0]  # [count, last_refresh_monotonic]
_STATUS_CACHE_TTL: float = 5.0
_status_cache_lock = threading.Lock()

# ── System prompts (module-level to avoid re-creation per request) ──────────
_RAG_SYSTEM_PROMPT = """You are a helpful assistant that answers questions based strictly on the provided context passages.

Rules:
1. Answer directly and concisely using only information from the provided context.
2. If the answer is not in the context, say: "I don't have that information in the provided documents."
3. Do not describe the document structure or list section names - synthesize the content into a clear, direct answer.
4. Do not reference internal identifiers like chunk numbers or section indices.
5. Only use bullet points or tables when the content genuinely benefits from that structure.
6. You may mention the source document name when it adds useful context."""

_ENHANCED_SYSTEM_PROMPT = """You are a helpful assistant that answers questions using both uploaded documents and live web search results.

Rules:
1. Synthesize information from both local documents and web sources into a single clear answer.
2. Prefer local document content when it directly answers the question.
3. Use web sources to fill gaps, provide current information, or verify facts.
4. When citing web sources, mention the URL or site name briefly.
5. Do not list section names or describe document structure - give a direct answer.
6. Only use bullet points or tables when the content genuinely benefits from that structure."""


def _parse_chat_request(data: dict) -> dict:
    """Validate and sanitise chat request data. Returns cleaned field dict."""
    from ..models import ChatRequest
    from ..utils.sanitization import sanitize_query
    req = ChatRequest(**data)
    return {
        'message': sanitize_query(req.message),
        'use_rag': req.use_rag,
        'enhance': req.enhance and config.WEB_SEARCH_ENABLED,
        'chat_history': req.history,
        'conversation_id': req.conversation_id,
        'images': req.images or [],
        'temperature': req.temperature,
    }


def _get_rag_context(message: str, doc_processor, filename_filter: list | None = None) -> tuple[str, list[dict]]:
    """Retrieve and format RAG context. Returns (formatted context block, source list)."""
    results = doc_processor.retrieve_context(message, filename_filter=filename_filter or [])
    logger.info(f"[RAG] Retrieved {len(results)} chunks from database")
    g.chunks_retrieved = getattr(g, "chunks_retrieved", 0) + len(results)
    if not results:
        logger.warning("[RAG] No chunks retrieved from documents")
        return "", []
    for idx, (_, filename, chunk_index, similarity, metadata, *_) in enumerate(results, 1):
        parts = [f"[RAG] Result {idx}: {filename} chunk {chunk_index}: similarity {similarity:.3f}"]
        if metadata.get('page_number'):
            parts.append(f"page {metadata['page_number']}")
        if metadata.get('section_title'):
            parts.append(f"section: {metadata['section_title'][:30]}")
        logger.debug(" ".join(parts))
    sources = [
        {
            "filename": filename,
            "chunk_index": chunk_index,
            "page_number": metadata.get("page_number"),
            "section_title": metadata.get("section_title"),
            "chunk_id": chunk_id,
        }
        for _, filename, chunk_index, _, metadata, chunk_id in results
    ]
    return doc_processor.format_context_for_llm(results, max_length=6000), sources


def _get_web_context(message: str) -> str:
    """Run web search and return formatted context block."""
    from ..rag.web_search import WebSearchProvider
    searcher = WebSearchProvider()
    web_results = searcher.search(message)
    if not web_results:
        logger.warning("[ENHANCED] Web search returned no results")
        return ""
    logger.info(f"[ENHANCED] Got {len(web_results)} web result(s)")
    return searcher.format_web_context(web_results, max_length=4000)


def _insert_system_prompt(messages: list, prompt: str) -> None:
    """Prepend a system message if one is not already present."""
    if not messages or messages[0].get('role') != 'system':
        messages.insert(0, {'role': 'system', 'content': prompt})


def _build_context_sections(local_context: str, web_context: str) -> str:
    """Build the combined context block from local and web sources."""
    sections = []
    if local_context:
        sections.append("=== Local Document Context ===\n" + local_context)
    if web_context:
        sections.append("=== Web Search Results ===\n" + web_context)
    return "\n\n".join(sections)


def _build_context_prompt(
    original_message: str,
    local_context: str,
    web_context: str,
    messages: list,
    use_rag: bool,
    enhance: bool,
) -> tuple:
    """Inject context into messages list and return (updated_messages, final_message)."""
    has_local = bool(local_context)
    has_web = bool(web_context)

    if has_local or has_web:
        _insert_system_prompt(messages, _ENHANCED_SYSTEM_PROMPT if enhance else _RAG_SYSTEM_PROMPT)
        combined = _build_context_sections(local_context, web_context)
        final_message = (
            f"{combined}\n\n---\n\nQuestion: {original_message}\n\n"
            "Answer the question directly using the information above. "
            "Synthesize the relevant content into a clear response."
        )
        logger.info(f"[CHAT API] Context ready - local: {has_local}, web: {has_web}")
    elif use_rag:
        _insert_system_prompt(
            messages, "You are a helpful AI assistant. No relevant documents or web results were found."
        )
        final_message = original_message
    else:
        final_message = original_message

    return messages, final_message


@bp.route('/status', methods=['GET'])
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
        with _status_cache_lock:
            now = time.monotonic()
            if now - _status_doc_count_cache[1] > _STATUS_CACHE_TTL:
                try:
                    _status_doc_count_cache[:] = [current_app.db.get_document_count(), now]
                except Exception as e:
                    logger.warning(f"Could not get document count: {e}")
                    db_available = False
            doc_count = _status_doc_count_cache[0]

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


def _retrieve_contexts(fields: dict, doc_processor) -> tuple:
    """Retrieve local RAG context and web search context based on request flags."""
    local_context = ""
    web_context = ""
    sources: list[dict] = []

    if fields['use_rag']:
        try:
            filename_filter: list[str] = []
            conversation_id = fields.get('conversation_id')
            if conversation_id:
                try:
                    filename_filter = current_app.db.get_conversation_document_filter(conversation_id)
                except Exception as filter_err:
                    logger.warning(f"[RAG] Could not read document filter: {filter_err}")
            local_context, sources = _get_rag_context(
                fields['message'], doc_processor, filename_filter=filename_filter
            )
        except Exception as e:
            raise exceptions.SearchError(
                f"Failed to retrieve context: {e}", details={"error": str(e)}
            )

    if fields['enhance']:
        try:
            web_context = _get_web_context(fields['message'])
        except Exception as web_err:
            logger.warning(f"[ENHANCED] Web search failed, continuing without: {web_err}")

    return local_context, web_context, sources


def _build_user_message(message: str, images: list) -> dict[str, Any]:
    """Construct the user message dict, optionally attaching images."""
    msg: dict[str, Any] = {'role': 'user', 'content': message}
    if images:
        msg['images'] = images
        logger.info(f"[CHAT API] Attaching {len(images)} image(s) to request")
    return msg


def _persist_user_message(app, conversation_id, message: str):
    """Save the user message to the database if available. Returns conversation_id."""
    if not app.startup_status.get('database', False):
        return conversation_id
    try:
        if not conversation_id:
            title = message[:60] + ('...' if len(message) > 60 else '')
            conversation_id = app.db.create_conversation(title)
        app.db.save_message(conversation_id, 'user', message)
    except Exception as mem_err:
        logger.warning(f"[MEMORY] Could not persist user message: {mem_err}")
        conversation_id = None
    return conversation_id


def _persist_assistant_message(app, conversation_id, text: str) -> None:
    """Save the assistant response to the database."""
    if not conversation_id:
        return
    try:
        app.db.save_message(conversation_id, 'assistant', text)
    except Exception as mem_err:
        logger.warning(f"[MEMORY] Could not persist assistant message: {mem_err}")


def _get_tool_executor(app):
    """Create a ToolExecutor if tool calling is enabled and tools are registered."""
    if not config.TOOL_CALLING_ENABLED:
        return None
    try:
        from ..tools import ToolExecutor, tool_registry
        if len(tool_registry) > 0:
            return ToolExecutor(app.ollama_client, tool_registry)
    except ImportError:
        pass
    return None


def _stream_chat_response(app, active_model, messages, conversation_id, tool_executor, temperature=0.7, sources=None):
    """Build and return an SSE Response that streams the chat completion."""
    def generate() -> Generator[str, None, None]:
        full_response: list = []
        try:
            stream = (
                tool_executor.execute(active_model, messages, stream=True)
                if tool_executor is not None
                else app.ollama_client.generate_chat_response(active_model, messages, stream=True, temperature=temperature)
            )
            for chunk in stream:
                full_response.append(chunk)
                yield f"data: {json.dumps({'content': chunk})}\n\n"

            _persist_assistant_message(app, conversation_id, ''.join(full_response))

            done_payload: dict = {'done': True}
            if conversation_id:
                done_payload['conversation_id'] = conversation_id
            if sources:
                done_payload['sources'] = sources
            yield f"data: {json.dumps(done_payload)}\n\n"
        except exceptions.LocalChatException as e:
            # Expected application error (e.g. model not found) — already logged
            # at WARNING level by the exception constructor; no traceback needed.
            msg = e.message
            yield f"data: {json.dumps({'error': 'GenerationError', 'message': msg, 'done': True})}\n\n"
        except Exception as e:
            logger.error(f"[CHAT API] Unexpected error generating response: {e}", exc_info=True)
            msg = "Failed to generate response"
            yield f"data: {json.dumps({'error': 'GenerationError', 'message': msg, 'done': True})}\n\n"

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


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
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({'error': 'BadRequest', 'success': False, 'message': 'Request body must be valid JSON'}), 400

        try:
            fields = _parse_chat_request(data)
        except ImportError as e:
            logger.error(f"Failed to import required modules: {e}")
            return jsonify({'success': False, 'message': 'Server configuration error'}), 500

        active_model = config.app_state.get_active_model()
        if not active_model:
            return jsonify({'error': 'NoModelConfigured', 'message': 'No active model set. Please select a model first.'}), 400

        g.model = active_model
        logger.info(f"[CHAT API] Request - RAG Mode: {fields['use_rag']}, Enhanced: {fields['enhance']}, Query: {fields['message'][:50]}...")

        messages = [{'role': m.get('role', 'user'), 'content': m.get('content', '')} for m in fields['chat_history']]
        local_ctx, web_ctx, sources = _retrieve_contexts(fields, current_app.doc_processor)
        messages, final_message = _build_context_prompt(
            fields['message'], local_ctx, web_ctx, messages, fields['use_rag'], fields['enhance']
        )
        messages.append(_build_user_message(final_message, fields['images']))

        app = current_app._get_current_object()  # type: ignore[attr-defined]
        conversation_id = _persist_user_message(app, fields['conversation_id'], fields['message'])
        # Don't use tool calling when context is already embedded — the model
        # would try to call retrieval tools it doesn't need, causing confusion.
        tool_executor = None if (local_ctx or web_ctx) else _get_tool_executor(app)

        return _stream_chat_response(app, active_model, messages, conversation_id, tool_executor, fields['temperature'], sources=sources)

    except (PydanticValidationError, exceptions.LocalChatException):
        raise
    except Exception as e:
        logger.error(f"[CHAT API] Unexpected error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An unexpected error occurred during chat'}), 500


# ---------------------------------------------------------------------------
# Plugin system endpoints
# ---------------------------------------------------------------------------

@bp.route('/api/plugins', methods=['GET'])
def list_plugins():
    """List all loaded tool plugins and the tools each one registered."""
    try:
        from ..tools import plugin_loader, tool_registry

        plugins = plugin_loader.list_plugins()
        builtin_tools = [
            {"name": s.name, "description": s.description}
            for s in tool_registry.get_by_source("builtin")
        ]

        return jsonify({
            "success": True,
            "plugins": plugins,
            "plugin_count": len(plugins),
            "builtin_tools": builtin_tools,
            "builtin_tool_count": len(builtin_tools),
            "total_tools": len(tool_registry),
        })
    except Exception as exc:
        logger.error(f"[PLUGINS] list_plugins error: {exc}", exc_info=True)
        return jsonify({"success": False, "message": str(exc)}), 500


@bp.route('/api/plugins/reload', methods=['POST'])
def reload_plugins():
    """Reload all plugins from disk without restarting the server."""
    try:
        from .. import config
        from ..tools import plugin_loader

        if not config.PLUGINS_ENABLED:
            return jsonify({"success": False, "message": "Plugin system is disabled"}), 400

        count = plugin_loader.reload_all()
        return jsonify({
            "success": True,
            "reloaded": count,
            "plugins": plugin_loader.list_plugins(),
        })
    except Exception as exc:
        logger.error(f"[PLUGINS] reload error: {exc}", exc_info=True)
        return jsonify({"success": False, "message": str(exc)}), 500
