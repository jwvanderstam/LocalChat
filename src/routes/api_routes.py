
"""
API Routes Blueprint
===================

Core API endpoints for LocalChat application.
Handles status checks, chat (RAG and direct LLM), and core API functionality.

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


_WEB_INTENT_PHRASES = (
    "check internet", "search internet", "search the internet",
    "search online", "search the web", "look online", "look it up online",
    "check online", "check the web", "find online", "find on internet",
    "search web", "google it", "browse the web", "current news",
    "latest news", "recent news", "what's happening", "what is happening",
    "up to date", "most recent", "most current", "most actual",
    "zoek internet", "zoek het op", "check internet",
)


def _has_web_search_intent(message: str) -> bool:
    """Return True if the message contains natural-language web search intent."""
    lower = message.lower()
    return any(phrase in lower for phrase in _WEB_INTENT_PHRASES)


def _parse_chat_request(data: dict) -> dict:
    """Validate and sanitise chat request data. Returns cleaned field dict."""
    from ..models import ChatRequest
    from ..utils.sanitization import sanitize_query
    req = ChatRequest(**data)
    message = sanitize_query(req.message)
    # Auto-enable web search when message clearly signals intent,
    # even if the toggle wasn't flipped manually.
    enhance = (req.enhance or _has_web_search_intent(message)) and config.WEB_SEARCH_ENABLED
    if enhance and not req.enhance:
        logger.info("[ENHANCED] Auto-enabled web search from message intent")
    return {
        'message': message,
        'use_rag': req.use_rag,
        'enhance': enhance,
        'chat_history': req.history,
        'conversation_id': req.conversation_id,
        'images': req.images or [],
        'temperature': req.temperature,
        'model_override': req.model_override or None,
    }


def _try_mcp_rag(message: str, filename_filter: list | None) -> tuple[str, list[dict]] | None:
    """Attempt retrieval via the local-docs MCP server.

    Returns (context, sources) on success, or None if MCP is unavailable or fails.
    """
    try:
        from ..mcp_client import mcp_registry
        result = mcp_registry.local_docs.call_tool("search", {
            "query": message,
            "filters": {"filenames": filename_filter or []},
            "top_k": config.TOP_K_RESULTS,
        })
        if isinstance(result, dict) and "context" in result:
            context = result["context"]
            sources = result.get("sources") or []
            chunk_count = len(sources)
            logger.info(f"[RAG/MCP] Retrieved {chunk_count} chunks via local-docs server")
            g.chunks_retrieved = getattr(g, "chunks_retrieved", 0) + chunk_count
            if not context:
                logger.warning("[RAG/MCP] No chunks retrieved from local-docs server")
            return context, sources
    except Exception as mcp_err:
        logger.warning(f"[RAG/MCP] local-docs call failed, falling back to direct: {mcp_err}")
    return None


def _get_rag_context(
    message: str,
    doc_processor,
    filename_filter: list | None = None,
    workspace_id: str | None = None,
) -> tuple[str, list[dict]]:
    """Retrieve and format RAG context. Returns (formatted context block, source list).

    When MCP_ENABLED is True, delegates to the local-docs MCP server.
    Falls back to direct retrieval if the MCP server is unreachable.
    """
    if config.MCP_ENABLED:
        mcp_result = _try_mcp_rag(message, filename_filter)
        if mcp_result is not None:
            return mcp_result

    # Direct retrieval path (default when MCP disabled, or MCP fallback)
    results = doc_processor.retrieve_context(
        message, filename_filter=filename_filter or [], workspace_id=workspace_id
    )
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
    return doc_processor.format_context_for_llm(results, max_length=config.MAX_CONTEXT_LENGTH), sources


def _get_web_context(message: str) -> str:
    """Run web search and return formatted context block.

    When MCP_ENABLED is True, delegates to the web-search MCP server.
    Falls back to direct search if the MCP server is unreachable.
    """
    if config.MCP_ENABLED:
        try:
            from ..mcp_client import mcp_registry
            result = mcp_registry.web_search.call_tool("search", {"query": message})
            if isinstance(result, dict):
                context = result.get("context", "")
                count = result.get("result_count", 0)
                if context:
                    logger.info(f"[ENHANCED/MCP] Got {count} web result(s) via web-search server")
                    return context
                logger.warning("[ENHANCED/MCP] Web search server returned no results")
                return ""
        except Exception as mcp_err:
            logger.warning(f"[ENHANCED/MCP] web-search call failed, falling back to direct: {mcp_err}")

    # Direct search path
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
    memory_context: str = "",
) -> tuple:
    """Inject context into messages list and return (updated_messages, final_message)."""
    has_local = bool(local_context)
    has_web = bool(web_context)

    if has_local or has_web:
        system = _ENHANCED_SYSTEM_PROMPT if enhance else _RAG_SYSTEM_PROMPT
        if memory_context:
            system = memory_context + "\n\n" + system
        _insert_system_prompt(messages, system)
        combined = _build_context_sections(local_context, web_context)
        final_message = (
            f"{combined}\n\n---\n\nQuestion: {original_message}\n\n"
            "Answer the question directly using the information above. "
            "Synthesize the relevant content into a clear response."
        )
        logger.info(f"[CHAT API] Context ready - local: {has_local}, web: {has_web}, memory: {bool(memory_context)}")
    elif use_rag:
        system = "You are a helpful AI assistant. No relevant documents or web results were found."
        if memory_context:
            system = memory_context + "\n\n" + system
        _insert_system_prompt(messages, system)
        final_message = original_message
    else:
        if memory_context:
            _insert_system_prompt(messages, memory_context)
        final_message = original_message

    return messages, final_message


def _get_doc_count_cached(db) -> tuple[int, bool]:
    """Return (doc_count, db_still_available) using a short TTL cache."""
    with _status_cache_lock:
        now = time.monotonic()
        if now - _status_doc_count_cache[1] > _STATUS_CACHE_TTL:
            try:
                _status_doc_count_cache[:] = [db.get_document_count(), now]
            except Exception as e:
                logger.warning(f"Could not get document count: {e}")
                return 0, False
        return _status_doc_count_cache[0], True


def _collect_cache_stats() -> dict:
    """Return a cache-statistics dict (may be empty) from app caches."""
    stats: dict = {}
    if hasattr(current_app, 'embedding_cache') and current_app.embedding_cache:
        stats['embedding'] = current_app.embedding_cache.get_stats().to_dict()
    if hasattr(current_app, 'query_cache') and current_app.query_cache:
        stats['query'] = current_app.query_cache.get_stats().to_dict()
    return stats


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
    db_available = current_app.startup_status.get('database', False)
    doc_count = 0
    if db_available:
        doc_count, db_available = _get_doc_count_cached(current_app.db)

    response = {
        'ollama': current_app.startup_status['ollama'],
        'database': db_available,
        'ready': current_app.startup_status['ready'] and db_available,
        'active_model': config.app_state.get_active_model(),
        'document_count': doc_count,
        'features': {
            'model_router': config.MODEL_ROUTER_ENABLED,
            'aggregator_agent': config.AGGREGATOR_AGENT_ENABLED,
            'mcp': config.MCP_ENABLED,
            'graph_rag': config.GRAPH_RAG_ENABLED,
            'long_term_memory': config.LONG_TERM_MEMORY_ENABLED,
        },
    }

    cache_stats = _collect_cache_stats()
    if cache_stats:
        response['cache'] = cache_stats

    if config.MCP_ENABLED:
        try:
            from ..mcp_client import mcp_registry
            response['mcp_servers'] = mcp_registry.health_summary()
        except Exception as mcp_err:
            logger.warning(f"[MCP] health_summary failed: {mcp_err}")
            response['mcp_servers'] = {'error': str(mcp_err)}

    if config.MODEL_ROUTER_ENABLED:
        try:
            from ..agent.models import model_registry
            response['model_routing'] = model_registry.summary()
        except Exception:
            pass

    return jsonify(response)


def _get_filename_filter(fields: dict) -> list[str]:
    """Return the active document filter for this conversation (or empty list)."""
    conversation_id = fields.get('conversation_id')
    if not conversation_id:
        return []
    try:
        return current_app.db.get_conversation_document_filter(conversation_id)
    except Exception as filter_err:
        logger.warning(f"[RAG] Could not read document filter: {filter_err}")
        return []


def _retrieve_contexts(fields: dict, doc_processor, plan=None, workspace_id: str | None = None) -> tuple:
    """Retrieve local RAG context and web search context based on request flags.

    When AGGREGATOR_AGENT_ENABLED is true, dispatches all tools through
    AggregatorAgent (parallel, with retry) and stores the result in g.agent_result.

    Falls back to direct retrieval on any agent-level error.
    When *plan* is provided and is multi-hop (direct path), runs parallel
    retrievals for each sub-question.
    """
    if config.AGGREGATOR_AGENT_ENABLED:
        result = _retrieve_via_aggregator(fields, plan)
        if result is not None:
            return result

    return _retrieve_direct(fields, doc_processor, plan, workspace_id=workspace_id)


def _retrieve_via_aggregator(fields: dict, plan) -> tuple | None:
    """Run the AggregatorAgent and return (local_ctx, web_ctx, sources).

    Returns None when no tools are needed or the agent fails (caller falls back
    to direct retrieval).
    """
    tools: list[str] = []
    if fields['use_rag']:
        tools.append("local_docs")
    if fields['enhance']:
        tools.append("web_search")
    if not tools:
        return None
    try:
        from ..agent.aggregator import AggregatorAgent
        filename_filter = _get_filename_filter(fields)
        agent_result = AggregatorAgent().run(
            fields['message'],
            plan=plan,
            filename_filter=filename_filter,
            tools=tools,
            top_k=config.TOP_K_RESULTS,
            max_retries=config.AGENT_MAX_RETRIES,
        )
        g.chunks_retrieved = getattr(g, "chunks_retrieved", 0) + len(agent_result.sources)
        g.agent_result = agent_result
        if agent_result.partial:
            logger.warning(f"[Agent] Partial results: {agent_result.warnings}")
        return (
            agent_result.contexts_by_tool.get("local_docs", ""),
            agent_result.contexts_by_tool.get("web_search", ""),
            agent_result.sources,
        )
    except Exception as agent_err:
        logger.warning(f"[Agent] Failed, falling back to direct retrieval: {agent_err}")
        return None


def _retrieve_direct(fields: dict, doc_processor, plan, workspace_id: str | None = None) -> tuple:
    """Direct retrieval path (default, or aggregator fallback)."""
    local_context = ""
    web_context = ""
    sources: list[dict] = []

    if fields['use_rag']:
        try:
            filename_filter = _get_filename_filter(fields)
            if plan is not None and plan.is_multi_hop:
                local_context, sources = _get_rag_context_multi_hop(
                    plan.sub_questions, doc_processor, filename_filter, workspace_id=workspace_id
                )
            else:
                local_context, sources = _get_rag_context(
                    fields['message'], doc_processor,
                    filename_filter=filename_filter, workspace_id=workspace_id
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


def _get_rag_context_multi_hop(
    sub_questions: list[str],
    doc_processor,
    filename_filter: list[str],
    workspace_id: str | None = None,
) -> tuple[str, list[dict]]:
    """Parallel retrieval per sub-question, merged and deduplicated by chunk_id."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_results: list = []
    with ThreadPoolExecutor(max_workers=min(len(sub_questions), 4)) as executor:
        futures = {
            executor.submit(
                doc_processor.retrieve_context, q,
                filename_filter=filename_filter, workspace_id=workspace_id
            ): q
            for q in sub_questions
        }
        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception as exc:
                logger.warning(f"[Planner] Sub-question retrieval failed: {exc}")

    # Deduplicate by chunk_id, keep highest similarity score per chunk
    seen: dict[int, tuple] = {}
    for r in all_results:
        chunk_id = r[5]
        if chunk_id not in seen or r[3] > seen[chunk_id][3]:
            seen[chunk_id] = r

    merged = sorted(seen.values(), key=lambda r: r[3], reverse=True)
    merged = merged[:config.TOP_K_RESULTS]

    if not merged:
        return "", []

    g.chunks_retrieved = getattr(g, "chunks_retrieved", 0) + len(merged)
    local_context = doc_processor.format_context_for_llm(merged, max_length=config.MAX_CONTEXT_LENGTH)
    sources = [
        {
            "filename": r[1],
            "chunk_index": r[2],
            "page_number": r[4].get("page_number"),
            "section_title": r[4].get("section_title"),
            "chunk_id": r[5],
        }
        for r in merged
    ]
    return local_context, sources


def _build_user_message(message: str, images: list) -> dict[str, Any]:
    """Construct the user message dict, optionally attaching images."""
    msg: dict[str, Any] = {'role': 'user', 'content': message}
    if images:
        msg['images'] = images
        logger.info(f"[CHAT API] Attaching {len(images)} image(s) to request")
    return msg


def _persist_user_message(
    app, conversation_id, message: str,
    plan=None, agent_result=None, workspace_id: str | None = None,
):
    """Save the user message (+ optional plan + agent tool trace) to the database.

    Returns (conversation_id, message_id).  message_id is None when DB is
    unavailable or the insert failed.
    """
    if not app.startup_status.get('database', False):
        return conversation_id, None
    try:
        if not conversation_id:
            title = message[:60] + ('...' if len(message) > 60 else '')
            conversation_id = app.db.create_conversation(title, workspace_id=workspace_id)
        plan_json: dict | None = plan.to_dict() if plan is not None else None
        if agent_result is not None:
            plan_json = plan_json or {}
            plan_json['tool_trace'] = agent_result.to_trace_dict()
            if agent_result.warnings:
                plan_json['agent_warnings'] = agent_result.warnings
            if agent_result.partial:
                plan_json['partial_results'] = True
        message_id: int | None = app.db.save_message(
            conversation_id, 'user', message, plan_json=plan_json
        )
        return conversation_id, message_id
    except Exception as mem_err:
        logger.warning(f"[MEMORY] Could not persist user message: {mem_err}")
        return None, None


def _persist_assistant_message(app, conversation_id, text: str) -> int | None:
    """Save the assistant response to the database.  Returns the message_id or None."""
    if not conversation_id:
        return None
    try:
        return app.db.save_message(conversation_id, 'assistant', text)
    except Exception as mem_err:
        logger.warning(f"[MEMORY] Could not persist assistant message: {mem_err}")
        return None


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


def _any_local_only_sources(sources: list[dict] | None, app) -> bool:
    """Return True if any source doc has local_only=TRUE in the DB."""
    if not sources or not app.startup_status.get('database', False):
        return False
    filenames = list({s['filename'] for s in sources if s.get('filename')})
    if not filenames:
        return False
    try:
        return app.db.any_local_only_sources(filenames)
    except Exception as e:
        logger.warning(f"[CloudFallback] local_only check failed: {e}")
        return True  # Conservative fallback


def _build_done_payload(
    conversation_id, asst_message_id, sources, cloud_client, model_used,
    agent_result, routed_model, routed_rationale,
) -> dict:
    """Assemble the SSE ``done`` payload dict."""
    payload: dict = {'done': True}
    if conversation_id:
        payload['conversation_id'] = conversation_id
    if asst_message_id is not None:
        payload['message_id'] = asst_message_id
    if sources:
        payload['sources'] = sources
        payload['source_chunk_ids'] = [s['chunk_id'] for s in sources if s.get('chunk_id')]
    if cloud_client is not None:
        payload['model_used'] = model_used
    if agent_result is not None:
        payload['tool_trace'] = agent_result.to_trace_dict()
        if agent_result.partial:
            payload['partial_results'] = True
    if routed_model:
        payload['routed_model'] = routed_model
        payload['routed_rationale'] = routed_rationale
    return payload


def _update_chunk_stats(app, sources: list[dict]) -> None:
    """Increment retrieved-count for every source chunk (fire-and-forget)."""
    if not sources or not app.startup_status.get('database', False):
        return
    chunk_ids = [s['chunk_id'] for s in sources if s.get('chunk_id')]
    if chunk_ids:
        try:
            app.db.increment_chunk_retrieved(chunk_ids)
        except Exception as cs_err:
            logger.debug(f"[Feedback] chunk_stats update failed: {cs_err}")


def _stream_chunks_with_fallback(
    local_stream, cloud_client, sources, app, messages, temperature,
) -> Generator[tuple[str, str], None, None]:
    """Yield (text_chunk, model_used) pairs, falling back to cloud on refusal."""
    from ..llm_client import is_refusal

    if cloud_client is None:
        for chunk in local_stream:
            yield chunk, 'local'
        return

    # Cloud fallback: buffer the local response first, then decide
    buffered_chunks: list[str] = []
    for chunk in local_stream:
        buffered_chunks.append(chunk)
    buffered = ''.join(buffered_chunks)

    if is_refusal(buffered) and not _any_local_only_sources(sources, app):
        logger.info("[CloudFallback] Local refusal detected — routing to cloud")
        for chunk in cloud_client.generate_chat_response(
            config.CLOUD_MODEL, messages, stream=True, temperature=temperature
        ):
            yield chunk, 'cloud'
    else:
        yield buffered, 'local'


def _generate_chat_events(
    app, active_model, messages, conversation_id, tool_executor, temperature,
    sources, plan, agent_result, routed_model, routed_rationale, cloud_client,
) -> Generator[str, None, None]:
    """Core SSE generator — lifted out of _stream_chat_response to reduce nesting."""
    full_response: list[str] = []
    model_used = 'local'
    try:
        if plan is not None:
            yield f"data: {json.dumps({'plan': plan.to_dict()})}\n\n"

        local_stream = (
            tool_executor.execute(active_model, messages, stream=True)
            if tool_executor is not None
            else app.ollama_client.generate_chat_response(
                active_model, messages, stream=True, temperature=temperature
            )
        )

        for chunk, chunk_model in _stream_chunks_with_fallback(
            local_stream, cloud_client, sources, app, messages, temperature
        ):
            full_response.append(chunk)
            model_used = chunk_model
            yield f"data: {json.dumps({'content': chunk})}\n\n"

        asst_message_id = _persist_assistant_message(app, conversation_id, ''.join(full_response))
        _update_chunk_stats(app, sources or [])
        yield f"data: {json.dumps(_build_done_payload(conversation_id, asst_message_id, sources, cloud_client, model_used, agent_result, routed_model, routed_rationale))}\n\n"

    except exceptions.LocalChatException as e:
        yield f"data: {json.dumps({'error': 'GenerationError', 'message': e.message, 'done': True})}\n\n"
    except Exception as e:
        logger.error(f"[CHAT API] Unexpected error generating response: {e}", exc_info=True)
        yield f"data: {json.dumps({'error': 'GenerationError', 'message': 'Failed to generate response', 'done': True})}\n\n"


def _stream_chat_response(app, active_model, messages, conversation_id, tool_executor, temperature=0.7, sources=None, plan=None, agent_result=None, routed_model=None, routed_rationale=None):
    """Build and return an SSE Response that streams the chat completion."""
    cloud_client = getattr(app, 'cloud_client', None)
    response = Response(
        _generate_chat_events(
            app, active_model, messages, conversation_id, tool_executor, temperature,
            sources, plan, agent_result, routed_model, routed_rationale, cloud_client,
        ),
        mimetype='text/event-stream',
    )
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


def _retrieve_plan_and_memory(
    fields: dict, active_model: str, ollama_client, db,
) -> tuple:
    """Return (plan, memory_context) — either may be None/'' on error or when disabled."""
    plan = None
    if config.QUERY_PLANNER_ENABLED and fields['use_rag']:
        try:
            from ..rag.planner import QueryPlanner
            plan = QueryPlanner().plan(fields['message'], active_model, ollama_client)
        except Exception as plan_err:
            logger.warning(f"[Planner] Unexpected error (skipped): {plan_err}")

    memory_context = ""
    if config.LONG_TERM_MEMORY_ENABLED:
        try:
            from ..memory.retriever import MemoryRetriever
            memories = MemoryRetriever().retrieve(fields['message'], ollama_client, db)
            memory_context = MemoryRetriever.format_for_prompt(memories)
        except Exception as mem_err:
            logger.debug(f"[Memory] Retrieval skipped: {mem_err}")

    return plan, memory_context


def _apply_model_routing(
    fields: dict,
    active_model: str,
    sources: list[dict],
    plan,
) -> tuple[str, str | None]:
    """Return (model_name, rationale) after applying override or auto-routing."""
    if fields.get('model_override'):
        logger.info(f"[Router] User override → {fields['model_override']!r}")
        return fields['model_override'], "user override"
    if config.MODEL_ROUTER_ENABLED:
        try:
            from ..agent.router import ModelRouter
            doc_types = [s.get("doc_type") for s in sources if s.get("doc_type")]
            return ModelRouter().select(
                fields['message'],
                plan=plan,
                doc_types=doc_types,
                active_model=active_model,
            )
        except Exception as router_err:
            logger.warning(f"[Router] Selection failed, using active model: {router_err}")
    return active_model, None


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

        # ── Query planning + long-term memory (optional, non-blocking) ──────
        plan, memory_context = _retrieve_plan_and_memory(
            fields, active_model, current_app.ollama_client, current_app.db
        )

        workspace_id = config.app_state.get_active_workspace_id()

        messages = [{'role': m.get('role', 'user'), 'content': m.get('content', '')} for m in fields['chat_history']]
        local_ctx, web_ctx, sources = _retrieve_contexts(
            fields, current_app.doc_processor, plan=plan, workspace_id=workspace_id
        )
        # Capture agent result if the aggregator ran (stored in g by _retrieve_contexts)
        agent_result = getattr(g, 'agent_result', None)

        # ── Model routing (optional, < 1 ms) ─────────────────────────────
        active_model, routed_rationale = _apply_model_routing(
            fields, active_model, sources, plan
        )
        g.model = active_model

        messages, final_message = _build_context_prompt(
            fields['message'], local_ctx, web_ctx, messages, fields['use_rag'], fields['enhance'],
            memory_context=memory_context,
        )
        messages.append(_build_user_message(final_message, fields['images']))

        app = current_app._get_current_object()  # type: ignore[attr-defined]
        conversation_id, _msg_id = _persist_user_message(
            app, fields['conversation_id'], fields['message'],
            plan=plan, agent_result=agent_result, workspace_id=workspace_id,
        )
        # Don't use tool calling when context is already embedded — the model
        # would try to call retrieval tools it doesn't need, causing confusion.
        tool_executor = None if (local_ctx or web_ctx) else _get_tool_executor(app)

        return _stream_chat_response(
            app, active_model, messages, conversation_id, tool_executor,
            fields['temperature'], sources=sources, plan=plan, agent_result=agent_result,
            routed_model=active_model if routed_rationale else None,
            routed_rationale=routed_rationale,
        )

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
