"""API routes — status, chat (SSE), plugins."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config, exceptions
from ..rag.retrieval import RetrievalResult
from ..utils.logging_config import get_logger
from ..utils.workspace import get_workspace_id

try:
    from pydantic import ValidationError as PydanticValidationError
except ImportError:
    class _FallbackValidationError(ValueError):  # type: ignore[misc]
        pass
    PydanticValidationError = _FallbackValidationError  # type: ignore[assignment,misc]

router = APIRouter()
logger = get_logger(__name__)

_ERR_INVALID_JSON = "Request body must be valid JSON"

# TTL caches — module-level to survive across requests
_status_doc_count_cache: dict[str | None, tuple[int, float]] = {}
_STATUS_CACHE_TTL: float = 5.0
_status_cache_lock = threading.Lock()
_ollama_status_cache: list = [False, 0.0]
_OLLAMA_STATUS_TTL: float = 10.0
_ollama_status_lock = threading.Lock()

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
    lower = message.lower()
    return any(phrase in lower for phrase in _WEB_INTENT_PHRASES)


def _parse_chat_request(data: dict) -> dict:
    from ..models import ChatRequest
    from ..utils.sanitization import sanitize_query
    req = ChatRequest(**data)
    message = sanitize_query(req.message)
    enhance = (req.enhance or _has_web_search_intent(message)) and config.WEB_SEARCH_ENABLED
    if enhance and not req.enhance:
        logger.info("[ENHANCED] Auto-enabled web search from message intent")
    return {
        "message": message,
        "use_rag": req.use_rag,
        "enhance": enhance,
        "chat_history": req.history,
        "conversation_id": req.conversation_id,
        "images": req.images or [],
        "temperature": req.temperature,
        "model_override": req.model_override or None,
        "additional_workspace_ids": req.additional_workspace_ids or [],
        "active_source_ids": req.active_source_ids or [],
    }


def _try_mcp_rag(
    message: str, filename_filter: list | None, chunks_retrieved_ref: list[int]
) -> tuple[str, list[dict]] | None:
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
            chunks_retrieved_ref[0] += len(sources)
            if not context:
                logger.warning("[RAG/MCP] No chunks retrieved from local-docs server")
            return context, sources
    except Exception as mcp_err:
        logger.warning("[RAG/MCP] local-docs call failed, falling back to direct: %s", mcp_err)
    return None


def _get_rag_context(
    message: str,
    doc_processor: Any,
    chunks_retrieved_ref: list[int],
    filename_filter: list | None = None,
    workspace_id: str | None = None,
    additional_workspace_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> tuple[str, list[dict]]:
    if config.MCP_ENABLED:
        mcp_result = _try_mcp_rag(message, filename_filter, chunks_retrieved_ref)
        if mcp_result is not None:
            return mcp_result

    results = doc_processor.retrieve_context(
        message, filename_filter=filename_filter or [], workspace_id=workspace_id,
        additional_workspace_ids=additional_workspace_ids,
        source_ids=source_ids or [],
    )
    logger.info("[RAG] Retrieved %d chunks from database", len(results))
    chunks_retrieved_ref[0] += len(results)
    if not results:
        logger.warning("[RAG] No chunks retrieved from documents")
        return "", []

    sources = [
        {
            "filename": r.filename,
            "chunk_index": r.chunk_index,
            "page_number": r.metadata.get("page_number"),
            "section_title": r.metadata.get("section_title"),
            "chunk_id": r.chunk_id,
        }
        for r in results
    ]
    return doc_processor.format_context_for_llm(results, max_length=config.MAX_CONTEXT_LENGTH), sources


def _get_web_context(message: str) -> str:
    if config.MCP_ENABLED:
        try:
            from ..mcp_client import mcp_registry
            result = mcp_registry.web_search.call_tool("search", {"query": message})
            if isinstance(result, dict):
                context = result.get("context", "")
                if context:
                    return context
                logger.warning("[ENHANCED/MCP] Web search server returned no results")
                return ""
        except Exception as mcp_err:
            logger.warning("[ENHANCED/MCP] web-search call failed, falling back: %s", mcp_err)

    from ..rag.web_search import WebSearchProvider
    searcher = WebSearchProvider()
    web_results = searcher.search(message)
    if not web_results:
        logger.warning("[ENHANCED] Web search returned no results")
        return ""
    logger.info("[ENHANCED] Got %d web result(s)", len(web_results))
    return searcher.format_web_context(web_results, max_length=4000)


def _insert_system_prompt(messages: list, prompt: str) -> None:
    if not messages or messages[0].get("role") != "system":
        messages.insert(0, {"role": "system", "content": prompt})


def _build_context_sections(local_context: str, web_context: str) -> str:
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
) -> tuple[list, str]:
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


def _get_doc_count_cached(db: Any, workspace_id: str | None) -> tuple[int, bool]:
    with _status_cache_lock:
        now = time.monotonic()
        cached = _status_doc_count_cache.get(workspace_id)
        if cached is None or now - cached[1] > _STATUS_CACHE_TTL:
            try:
                count = db.get_document_count(workspace_id=workspace_id)
                _status_doc_count_cache[workspace_id] = (count, now)
                return count, True
            except Exception as exc:
                logger.warning("Could not get document count: %s", exc)
                return 0, False
        return cached[0], True


def _check_ollama_live(app_state: Any) -> bool:
    with _ollama_status_lock:
        now = time.monotonic()
        if now - _ollama_status_cache[1] < _OLLAMA_STATUS_TTL:
            return _ollama_status_cache[0]
        try:
            available, _ = app_state.ollama_client.check_connection()
        except Exception:
            available = False
        _ollama_status_cache[:] = [available, now]
        app_state.startup_status["ollama"] = available
        app_state.startup_status["ready"] = available and app_state.startup_status.get("database", False)
        return available


def _collect_cache_stats(app_state: Any) -> dict:
    stats: dict = {}
    if hasattr(app_state, "embedding_cache") and app_state.embedding_cache:
        stats["embedding"] = app_state.embedding_cache.get_stats().to_dict()
    if hasattr(app_state, "query_cache") and app_state.query_cache:
        stats["query"] = app_state.query_cache.get_stats().to_dict()
    return stats


def _get_filename_filter(fields: dict, db: Any) -> list[str]:
    conversation_id = fields.get("conversation_id")
    if not conversation_id:
        return []
    try:
        return db.get_conversation_document_filter(conversation_id)
    except Exception as filter_err:
        logger.warning("[RAG] Could not read document filter: %s", filter_err)
        return []


def _retrieve_via_aggregator(
    fields: dict, plan: Any, chunks_retrieved_ref: list[int]
) -> tuple[str, str, list[dict]] | None:
    tools: list[str] = []
    if fields["use_rag"]:
        tools.append("local_docs")
    if fields["enhance"]:
        tools.append("web_search")
    if not tools:
        return None
    try:
        from ..agent.aggregator import AggregatorAgent
        agent_result = AggregatorAgent().run(
            fields["message"],
            plan=plan,
            filename_filter=[],
            tools=tools,
            top_k=config.TOP_K_RESULTS,
            max_retries=config.AGENT_MAX_RETRIES,
        )
        chunks_retrieved_ref[0] += len(agent_result.sources)
        if agent_result.partial:
            logger.warning("[Agent] Partial results: %s", agent_result.warnings)
        return (
            agent_result.contexts_by_tool.get("local_docs", ""),
            agent_result.contexts_by_tool.get("web_search", ""),
            agent_result.sources,
        ), agent_result  # type: ignore[return-value]
    except Exception as agent_err:
        logger.warning("[Agent] Failed, falling back to direct retrieval: %s", agent_err)
        return None


def _retrieve_contexts(
    fields: dict,
    doc_processor: Any,
    db: Any,
    chunks_retrieved_ref: list[int],
    plan: Any = None,
    workspace_id: str | None = None,
    additional_workspace_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> tuple[str, str, list[dict], Any]:
    """Return (local_ctx, web_ctx, sources, agent_result)."""
    if config.AGGREGATOR_AGENT_ENABLED:
        agg = _retrieve_via_aggregator(fields, plan, chunks_retrieved_ref)
        if agg is not None:
            (local_ctx, web_ctx, sources), agent_result = agg
            return local_ctx, web_ctx, sources, agent_result

    local_context = ""
    web_context = ""
    sources: list[dict] = []

    if fields["use_rag"]:
        try:
            filename_filter = _get_filename_filter(fields, db)
            if plan is not None and plan.is_multi_hop:
                local_context, sources = _get_rag_context_multi_hop(
                    plan.sub_questions, doc_processor, filename_filter,
                    workspace_id=workspace_id, chunks_retrieved_ref=chunks_retrieved_ref,
                )
            else:
                local_context, sources = _get_rag_context(
                    fields["message"], doc_processor, chunks_retrieved_ref,
                    filename_filter=filename_filter, workspace_id=workspace_id,
                    additional_workspace_ids=additional_workspace_ids,
                    source_ids=source_ids,
                )
        except Exception as exc:
            raise exceptions.SearchError(
                f"Failed to retrieve context: {exc}", details={"error": str(exc)}
            ) from exc

    if fields["enhance"]:
        try:
            web_context = _get_web_context(fields["message"])
        except Exception as web_err:
            logger.warning("[ENHANCED] Web search failed, continuing without: %s", web_err)

    return local_context, web_context, sources, None


def _get_rag_context_multi_hop(
    sub_questions: list[str],
    doc_processor: Any,
    filename_filter: list[str],
    workspace_id: str | None = None,
    chunks_retrieved_ref: list[int] | None = None,
) -> tuple[str, list[dict]]:
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
                logger.warning("[Planner] Sub-question retrieval failed: %s", exc)

    seen: dict[int, RetrievalResult] = {}
    for r in all_results:
        if r.chunk_id not in seen or r.similarity > seen[r.chunk_id].similarity:
            seen[r.chunk_id] = r

    merged = sorted(seen.values(), key=lambda r: r.similarity, reverse=True)[:config.TOP_K_RESULTS]

    if not merged:
        return "", []

    if chunks_retrieved_ref is not None:
        chunks_retrieved_ref[0] += len(merged)

    local_context = doc_processor.format_context_for_llm(merged, max_length=config.MAX_CONTEXT_LENGTH)
    sources = [
        {
            "filename": r.filename,
            "chunk_index": r.chunk_index,
            "page_number": r.metadata.get("page_number"),
            "section_title": r.metadata.get("section_title"),
            "chunk_id": r.chunk_id,
            "combined_score": r.metadata.get("combined_score"),
        }
        for r in merged
    ]
    return local_context, sources


def _build_user_message(message: str, images: list) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "user", "content": message}
    if images:
        msg["images"] = images
    return msg


def _persist_user_message(
    app_state: Any, conversation_id: str | None, message: str,
    plan: Any = None, agent_result: Any = None, workspace_id: str | None = None,
) -> tuple[str | None, int | None]:
    if not app_state.startup_status.get("database", False):
        return conversation_id, None
    try:
        plan_json: dict | None = plan.to_dict() if plan is not None else None
        if agent_result is not None:
            plan_json = plan_json or {}
            plan_json["tool_trace"] = agent_result.to_trace_dict()
            if agent_result.warnings:
                plan_json["agent_warnings"] = agent_result.warnings
            if agent_result.partial:
                plan_json["partial_results"] = True

        if not conversation_id:
            title = message[:60] + ("..." if len(message) > 60 else "")
            conversation_id, message_id = app_state.db.create_conversation_with_message(
                title, "user", message, workspace_id=workspace_id, plan_json=plan_json
            )
        else:
            message_id = app_state.db.save_message(conversation_id, "user", message, plan_json=plan_json)
        return conversation_id, message_id
    except Exception as mem_err:
        logger.warning("[MEMORY] Could not persist user message: %s", mem_err)
        return None, None


def _persist_assistant_message(app_state: Any, conversation_id: str | None, text: str) -> int | None:
    if not conversation_id:
        return None
    try:
        return app_state.db.save_message(conversation_id, "assistant", text)
    except Exception as mem_err:
        logger.warning("[MEMORY] Could not persist assistant message: %s", mem_err)
        return None


def _get_tool_executor(app_state: Any) -> Any:
    if not config.TOOL_CALLING_ENABLED:
        return None
    try:
        from ..tools import ToolExecutor, tool_registry
        if len(tool_registry) > 0:
            return ToolExecutor(app_state.ollama_client, tool_registry)
    except ImportError:
        pass
    return None


def _any_local_only_sources(sources: list[dict] | None, app_state: Any) -> bool:
    if not sources or not app_state.startup_status.get("database", False):
        return False
    filenames = list({s["filename"] for s in sources if s.get("filename")})
    if not filenames:
        return False
    try:
        return app_state.db.any_local_only_sources(filenames)
    except Exception as exc:
        logger.warning("[CloudFallback] local_only check failed: %s", exc)
        return True


def _build_done_payload(
    conversation_id: str | None,
    asst_message_id: int | None,
    sources: list[dict] | None,
    cloud_client: Any,
    model_used: str,
    agent_result: Any,
    routed_model: str | None,
    routed_rationale: str | None,
) -> dict:
    payload: dict = {"done": True}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if asst_message_id is not None:
        payload["message_id"] = asst_message_id
    if sources:
        payload["sources"] = sources
        payload["source_chunk_ids"] = [s["chunk_id"] for s in sources if s.get("chunk_id")]
        scores = [s["combined_score"] for s in sources if s.get("combined_score") is not None]
        if scores:
            payload["answer_confidence"] = round(min(1.0, max(0.0, sum(scores) / len(scores))), 4)
    if cloud_client is not None:
        payload["model_used"] = model_used
    if agent_result is not None:
        payload["tool_trace"] = agent_result.to_trace_dict()
        if agent_result.partial:
            payload["partial_results"] = True
    if routed_model:
        payload["routed_model"] = routed_model
        payload["routed_rationale"] = routed_rationale
    return payload


def _update_chunk_stats(app_state: Any, sources: list[dict]) -> None:
    if not sources or not app_state.startup_status.get("database", False):
        return
    chunk_ids = [s["chunk_id"] for s in sources if s.get("chunk_id")]
    if chunk_ids:
        try:
            app_state.db.increment_chunk_retrieved(chunk_ids)
        except Exception as exc:
            logger.debug("[Feedback] chunk_stats update failed: %s", exc)


async def _stream_chunks_with_fallback(
    local_stream: Any, cloud_client: Any, sources: list[dict] | None, app_state: Any, messages: list, temperature: float
) -> AsyncGenerator[tuple[str, str], None]:
    from ..llm_client import is_refusal

    if cloud_client is None:
        async for chunk in local_stream:
            yield chunk, "local"
        return

    buffered_chunks: list[str] = []
    async for chunk in local_stream:
        buffered_chunks.append(chunk)
    buffered = "".join(buffered_chunks)

    if is_refusal(buffered) and not _any_local_only_sources(sources, app_state):
        logger.info("[CloudFallback] Local refusal detected — routing to cloud")
        for chunk in cloud_client.generate_chat_response(
            config.CLOUD_MODEL, messages, stream=True, temperature=temperature
        ):
            yield chunk, "cloud"
    else:
        for chunk in buffered_chunks:
            yield chunk, "local"


async def _retrieve_plan_and_memory(
    fields: dict, active_model: str, ollama_client: Any, db: Any
) -> tuple[Any, str]:
    plan = None
    query_words = len(fields["message"].split())
    if config.QUERY_PLANNER_ENABLED and fields["use_rag"] and query_words >= 7:
        try:
            from ..rag.planner import QueryPlanner
            plan = await QueryPlanner().plan(fields["message"], active_model, ollama_client)
        except Exception as plan_err:
            logger.warning("[Planner] Unexpected error (skipped): %s", plan_err)

    memory_context = ""
    if config.LONG_TERM_MEMORY_ENABLED:
        try:
            from ..memory.retriever import MemoryRetriever
            memories = MemoryRetriever().retrieve(fields["message"], ollama_client, db)
            memory_context = MemoryRetriever.format_for_prompt(memories)
        except Exception as mem_err:
            logger.debug("[Memory] Retrieval skipped: %s", mem_err)

    return plan, memory_context


def _apply_model_routing(
    fields: dict, active_model: str, sources: list[dict], plan: Any
) -> tuple[str, str | None]:
    if fields.get("model_override"):
        logger.info("[Router] User override → %s", str(fields["model_override"]).replace("\r", "").replace("\n", " "))
        return fields["model_override"], "user override"
    if config.MODEL_ROUTER_ENABLED:
        try:
            from ..agent.router import ModelRouter
            doc_types = [s.get("doc_type") for s in sources if s.get("doc_type")]
            return ModelRouter().select(fields["message"], plan=plan, doc_types=doc_types, active_model=active_model)
        except Exception as router_err:
            logger.warning("[Router] Selection failed, using active model: %s", router_err)
    return active_model, None


@router.get("/status")
def api_status(request: Request) -> Any:
    app_state = request.app.state
    db_available = app_state.startup_status.get("database", False)
    workspace_id = get_workspace_id(request)
    doc_count = 0
    if db_available:
        doc_count, db_available = _get_doc_count_cached(app_state.db, workspace_id)

    ollama_available = _check_ollama_live(app_state)

    response: dict = {
        "ollama": ollama_available,
        "database": db_available,
        "ready": ollama_available and db_available,
        "active_model": config.app_state.get_active_model(),
        "document_count": doc_count,
        "features": {
            "model_router": config.MODEL_ROUTER_ENABLED,
            "aggregator_agent": config.AGGREGATOR_AGENT_ENABLED,
            "mcp": config.MCP_ENABLED,
            "graph_rag": config.GRAPH_RAG_ENABLED,
            "long_term_memory": config.LONG_TERM_MEMORY_ENABLED,
        },
    }

    cache_stats = _collect_cache_stats(app_state)
    if cache_stats:
        response["cache"] = cache_stats

    if config.MCP_ENABLED:
        try:
            from ..mcp_client import mcp_registry
            response["mcp_servers"] = mcp_registry.health_summary()
        except Exception as mcp_err:
            logger.warning("[MCP] health_summary failed: %s", mcp_err)
            response["mcp_servers"] = {"error": str(mcp_err)}

    if config.MODEL_ROUTER_ENABLED:
        try:
            from ..agent.models import model_registry
            response["model_routing"] = model_registry.summary()
        except Exception:
            pass

    return response


async def _generate_sse(
    plan: Any,
    tool_executor: Any,
    active_model: str,
    app_state: Any,
    messages: list,
    fields: dict,
    sources: list[dict] | None,
    cloud_client: Any,
    conversation_id: str | None,
    agent_result: Any,
    routed_rationale: str | None,
) -> AsyncGenerator[str, None]:
    full_response: list[str] = []
    model_used = "local"
    try:
        if plan is not None:
            yield f"data: {json.dumps({'plan': plan.to_dict()})}\n\n"

        local_stream = (
            tool_executor.execute(active_model, messages, stream=True)
            if tool_executor is not None
            else app_state.ollama_client.generate_chat_response(
                active_model, messages, stream=True, temperature=fields["temperature"]
            )
        )

        async for chunk, chunk_model in _stream_chunks_with_fallback(
            local_stream, cloud_client, sources, app_state, messages, fields["temperature"]
        ):
            full_response.append(chunk)
            model_used = chunk_model
            yield f"data: {json.dumps({'content': chunk})}\n\n"

        asst_message_id = _persist_assistant_message(app_state, conversation_id, "".join(full_response))
        _update_chunk_stats(app_state, sources or [])
        done_payload = _build_done_payload(
            conversation_id, asst_message_id, sources, cloud_client, model_used,
            agent_result, active_model if routed_rationale else None, routed_rationale,
        )
        yield f"data: {json.dumps(done_payload)}\n\n"

    except exceptions.LocalChatException as exc:
        yield f"data: {json.dumps({'error': 'GenerationError', 'message': exc.message, 'done': True})}\n\n"
    except Exception:
        logger.exception("[CHAT API] Unexpected error generating response")
        yield f"data: {json.dumps({'error': 'GenerationError', 'message': 'Failed to generate response', 'done': True})}\n\n"
    finally:
        pass  # ensures cleanup runs on client disconnect


@router.post("/chat")
async def api_chat(request: Request) -> Any:
    try:
        body = await request.body()
        if not body:
            return JSONResponse({"error": "BadRequest", "success": False, "message": _ERR_INVALID_JSON}, status_code=400)
        import json as _json
        try:
            data = _json.loads(body)
        except _json.JSONDecodeError:
            return JSONResponse({"error": "BadRequest", "success": False, "message": _ERR_INVALID_JSON}, status_code=400)

        if not isinstance(data, dict):
            return JSONResponse({"error": "BadRequest", "success": False, "message": _ERR_INVALID_JSON}, status_code=400)

        try:
            fields = _parse_chat_request(data)
        except ImportError:
            logger.exception("Failed to import required modules")
            return JSONResponse({"success": False, "message": "Server configuration error"}, status_code=500)

        active_model = config.app_state.get_active_model()
        if not active_model:
            return JSONResponse({"error": "NoModelConfigured", "message": "No active model set. Please select a model first."}, status_code=400)

        logger.info(
            "[CHAT API] Request - RAG Mode: %s, Enhanced: %s, Query: %s...",
            fields["use_rag"], fields["enhance"],
            str(fields["message"])[:50].replace("\r", "").replace("\n", " "),
        )

        app_state = request.app.state
        plan, memory_context = await _retrieve_plan_and_memory(
            fields, active_model, app_state.ollama_client, app_state.db
        )

        workspace_id = get_workspace_id(request)
        messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in fields["chat_history"]]

        chunks_retrieved_ref = [0]
        local_ctx, web_ctx, sources, agent_result = _retrieve_contexts(
            fields, app_state.doc_processor, app_state.db, chunks_retrieved_ref,
            plan=plan, workspace_id=workspace_id,
            additional_workspace_ids=fields.get("additional_workspace_ids") or None,
            source_ids=fields.get("active_source_ids") or None,
        )

        active_model, routed_rationale = _apply_model_routing(fields, active_model, sources, plan)
        messages, final_message = _build_context_prompt(
            fields["message"], local_ctx, web_ctx, messages, fields["use_rag"], fields["enhance"],
            memory_context=memory_context,
        )
        messages.append(_build_user_message(final_message, fields["images"]))

        conversation_id, _msg_id = _persist_user_message(
            app_state, fields["conversation_id"], fields["message"],
            plan=plan, agent_result=agent_result, workspace_id=workspace_id,
        )

        tool_executor = None if (local_ctx or web_ctx) else _get_tool_executor(app_state)
        cloud_client = getattr(app_state, "cloud_client", None)

        return StreamingResponse(
            _generate_sse(
                plan, tool_executor, active_model, app_state, messages, fields,
                sources, cloud_client, conversation_id, agent_result, routed_rationale,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except PydanticValidationError as exc:
        return JSONResponse({"error": "ValidationError", "success": False, "message": "Invalid request", "details": exc.errors()}, status_code=422)
    except exceptions.LocalChatException as exc:
        return JSONResponse({"success": False, "message": exc.message}, status_code=500)
    except Exception:
        logger.exception("[CHAT API] Unexpected error")
        return JSONResponse({"success": False, "message": "An unexpected error occurred during chat"}, status_code=500)


@router.get("/plugins")
def list_plugins(request: Request) -> Any:
    try:
        from ..tools import plugin_loader, tool_registry
        plugins = plugin_loader.list_plugins()
        builtin_tools = [
            {"name": s.name, "description": s.description}
            for s in tool_registry.get_by_source("builtin")
        ]
        return {
            "success": True,
            "plugins": plugins,
            "plugin_count": len(plugins),
            "builtin_tools": builtin_tools,
            "builtin_tool_count": len(builtin_tools),
            "total_tools": len(tool_registry),
        }
    except Exception:
        logger.exception("[PLUGINS] list_plugins error")
        return JSONResponse({"success": False, "message": "Internal server error"}, status_code=500)


@router.post("/plugins/reload")
def reload_plugins(request: Request) -> Any:
    try:
        from ..tools import plugin_loader
        if not config.PLUGINS_ENABLED:
            return JSONResponse({"success": False, "message": "Plugin system is disabled"}, status_code=400)
        count = plugin_loader.reload_all()
        return {"success": True, "reloaded": count, "plugins": plugin_loader.list_plugins()}
    except Exception:
        logger.exception("[PLUGINS] reload error")
        return JSONResponse({"success": False, "message": "Internal server error"}, status_code=500)
