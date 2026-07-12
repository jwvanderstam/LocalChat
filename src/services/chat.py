"""Chat service — business logic extracted from the chat route handler."""
from __future__ import annotations

import threading
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from .. import config, exceptions
from ..rag.retrieval import RetrievalResult
from ..utils.logging_config import get_logger

if TYPE_CHECKING:
    from ..agent.result import AgentResult

logger = get_logger(__name__)

# TTL caches — module-level to survive across requests
_status_doc_count_cache: dict[str | None, tuple[int, float]] = {}
_STATUS_CACHE_TTL: float = 5.0
_status_cache_lock = threading.Lock()
_ollama_status_cache: list = [False, 0.0]  # [available, last_check_time]
_OLLAMA_STATUS_TTL: float = 10.0
_ollama_status_lock = threading.Lock()
_ollama_refresh_thread: threading.Thread | None = None
_ollama_refresh_lock = threading.Lock()

_WEB_INTENT_PHRASES = (
    "check internet", "search internet", "search the internet",
    "search online", "search the web", "look online", "look it up online",
    "check online", "check the web", "find online", "find on internet",
    "search web", "google it", "browse the web", "current news",
    "latest news", "recent news", "what's happening", "what is happening",
    "up to date", "most recent", "most current", "most actual",
    "zoek internet", "zoek het op", "check internet",
)


def has_web_search_intent(message: str) -> bool:
    lower = message.lower()
    return any(phrase in lower for phrase in _WEB_INTENT_PHRASES)


def parse_chat_request(data: dict) -> dict:
    from ..models import ChatRequest
    from ..utils.sanitization import sanitize_query
    req = ChatRequest(**data)
    message = sanitize_query(req.message)
    enhance = (req.enhance or has_web_search_intent(message)) and config.WEB_SEARCH_ENABLED
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


def try_mcp_rag(
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


def get_rag_context(
    message: str,
    doc_processor: Any,
    chunks_retrieved_ref: list[int],
    filename_filter: list | None = None,
    workspace_id: str | None = None,
    additional_workspace_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> tuple[str, list[dict]]:
    if config.MCP_ENABLED:
        mcp_result = try_mcp_rag(message, filename_filter, chunks_retrieved_ref)
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


def get_web_context(message: str) -> str:
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


def get_doc_count_cached(db: Any, workspace_id: str | None) -> tuple[int, bool]:
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


def _ollama_refresh_worker(app_state: Any) -> None:
    """Refresh Ollama liveness on a background thread; never blocks the request path."""
    while True:
        time.sleep(_OLLAMA_STATUS_TTL)
        try:
            available, _ = app_state.ollama_client.check_connection()
        except Exception:
            available = False
        with _ollama_status_lock:
            _ollama_status_cache[:] = [available, time.monotonic()]
        app_state.startup_status["ollama"] = available
        app_state.startup_status["ready"] = available and app_state.startup_status.get("database", False)


def check_ollama_live(app_state: Any) -> bool:
    global _ollama_refresh_thread
    with _ollama_status_lock:
        if not _ollama_status_cache[1]:
            # First call: seed from bootstrap result so we don't briefly report False
            _ollama_status_cache[:] = [
                app_state.startup_status.get("ollama", False),
                time.monotonic(),
            ]
    with _ollama_refresh_lock:
        if _ollama_refresh_thread is None or not _ollama_refresh_thread.is_alive():
            _ollama_refresh_thread = threading.Thread(
                target=_ollama_refresh_worker,
                args=(app_state,),
                name="ollama-liveness",
                daemon=True,
            )
            _ollama_refresh_thread.start()
    with _ollama_status_lock:
        return bool(_ollama_status_cache[0])


def get_filename_filter(fields: dict, db: Any) -> list[str]:
    conversation_id = fields.get("conversation_id")
    if not conversation_id:
        return []
    try:
        return db.get_conversation_document_filter(conversation_id)
    except Exception as filter_err:
        logger.warning("[RAG] Could not read document filter: %s", filter_err)
        return []


def retrieve_via_aggregator(
    fields: dict, plan: Any, chunks_retrieved_ref: list[int]
) -> tuple[tuple[str, str, list[dict]], AgentResult] | None:
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
        ), agent_result
    except Exception as agent_err:
        logger.warning("[Agent] Failed, falling back to direct retrieval: %s", agent_err)
        return None


def retrieve_contexts(
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
        agg = retrieve_via_aggregator(fields, plan, chunks_retrieved_ref)
        if agg is not None:
            (local_ctx, web_ctx, sources), agent_result = agg
            return local_ctx, web_ctx, sources, agent_result

    local_context = ""
    web_context = ""
    sources = []

    if fields["use_rag"]:
        try:
            filename_filter = get_filename_filter(fields, db)
            if plan is not None and plan.is_multi_hop:
                local_context, sources = get_rag_context_multi_hop(
                    plan.sub_questions, doc_processor, filename_filter,
                    workspace_id=workspace_id, chunks_retrieved_ref=chunks_retrieved_ref,
                )
            else:
                local_context, sources = get_rag_context(
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
            web_context = get_web_context(fields["message"])
        except Exception as web_err:
            logger.warning("[ENHANCED] Web search failed, continuing without: %s", web_err)

    return local_context, web_context, sources, None


def get_rag_context_multi_hop(
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


def persist_user_message(
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


def persist_assistant_message(app_state: Any, conversation_id: str | None, text: str) -> int | None:
    if not conversation_id:
        return None
    try:
        return app_state.db.save_message(conversation_id, "assistant", text)
    except Exception as mem_err:
        logger.warning("[MEMORY] Could not persist assistant message: %s", mem_err)
        return None


def get_tool_executor(app_state: Any) -> Any:
    if not config.TOOL_CALLING_ENABLED:
        return None
    try:
        from ..tools import ToolExecutor, tool_registry
        if len(tool_registry) > 0:
            return ToolExecutor(app_state.ollama_client, tool_registry)
    except ImportError:
        pass
    return None


def any_local_only_sources(sources: list[dict] | None, app_state: Any) -> bool:
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


def update_chunk_stats(app_state: Any, sources: list[dict]) -> None:
    if not sources or not app_state.startup_status.get("database", False):
        return
    chunk_ids = [s["chunk_id"] for s in sources if s.get("chunk_id")]
    if chunk_ids:
        try:
            app_state.db.increment_chunk_retrieved(chunk_ids)
        except Exception as exc:
            logger.debug("[Feedback] chunk_stats update failed: %s", exc)


async def stream_chunks_with_fallback(
    local_stream: Any,
    cloud_client: Any,
    sources: list[dict] | None,
    app_state: Any,
    messages: list,
    temperature: float,
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

    if is_refusal(buffered) and not any_local_only_sources(sources, app_state):
        logger.info("[CloudFallback] Local refusal detected — routing to cloud")
        for chunk in cloud_client.generate_chat_response(
            config.CLOUD_MODEL, messages, stream=True, temperature=temperature
        ):
            yield chunk, "cloud"
    else:
        for chunk in buffered_chunks:
            yield chunk, "local"


async def retrieve_plan_and_memory(
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


def apply_model_routing(
    fields: dict, active_model: str, sources: list[dict], plan: Any
) -> tuple[str, str | None]:
    if fields.get("model_override"):
        logger.info("[Router] User override → %s", str(fields["model_override"]).replace("\r", "").replace("\n", " "))
        return fields["model_override"], "user override"
    if config.MODEL_ROUTER_ENABLED:
        try:
            from ..agent.router import ModelRouter
            doc_types = [dt for s in sources if (dt := s.get("doc_type"))]
            return ModelRouter().select(fields["message"], plan=plan, doc_types=doc_types, active_model=active_model)
        except Exception as router_err:
            logger.warning("[Router] Selection failed, using active model: %s", router_err)
    return active_model, None
