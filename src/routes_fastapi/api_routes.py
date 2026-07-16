"""API routes — status, chat (SSE), plugins."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config, exceptions
from ..services import chat
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


def _collect_cache_stats(app_state: Any) -> dict:
    stats: dict = {}
    if hasattr(app_state, "embedding_cache") and app_state.embedding_cache:
        stats["embedding"] = app_state.embedding_cache.get_stats().to_dict()
    if hasattr(app_state, "query_cache") and app_state.query_cache:
        stats["query"] = app_state.query_cache.get_stats().to_dict()
    return stats


def _build_user_message(message: str, images: list) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "user", "content": message}
    if images:
        msg["images"] = images
    return msg


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

        async for chunk, chunk_model in chat.stream_chunks_with_fallback(
            local_stream, cloud_client, sources, app_state, messages, fields["temperature"]
        ):
            full_response.append(chunk)
            model_used = chunk_model
            yield f"data: {json.dumps({'content': chunk})}\n\n"

        asst_message_id = chat.persist_assistant_message(app_state, conversation_id, "".join(full_response))
        chat.update_chunk_stats(app_state, sources or [])
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


@router.get("/status")
def api_status(request: Request) -> Any:
    app_state = request.app.state
    db_available = app_state.startup_status.get("database", False)
    workspace_id = get_workspace_id(request)
    doc_count = 0
    if db_available:
        doc_count, db_available = chat.get_doc_count_cached(app_state.db, workspace_id)

    ollama_available = chat.check_ollama_live(app_state)

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
            response["mcp_servers"] = {"error": "unavailable"}

    if config.MODEL_ROUTER_ENABLED:
        try:
            from ..agent.models import model_registry
            response["model_routing"] = model_registry.summary()
        except Exception:
            pass

    return response


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
            fields = chat.parse_chat_request(data)
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
        plan, memory_context = await chat.retrieve_plan_and_memory(
            fields, active_model, app_state.ollama_client, app_state.db
        )

        workspace_id = get_workspace_id(request)
        messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in fields["chat_history"]]

        chunks_retrieved_ref = [0]
        local_ctx, web_ctx, sources, agent_result = chat.retrieve_contexts(
            fields, app_state.doc_processor, app_state.db, chunks_retrieved_ref,
            plan=plan, workspace_id=workspace_id,
            additional_workspace_ids=fields.get("additional_workspace_ids") or None,
            source_ids=fields.get("active_source_ids") or None,
        )

        active_model, routed_rationale = chat.apply_model_routing(fields, active_model, sources, plan)
        messages, final_message = _build_context_prompt(
            fields["message"], local_ctx, web_ctx, messages, fields["use_rag"], fields["enhance"],
            memory_context=memory_context,
        )
        messages.append(_build_user_message(final_message, fields["images"]))

        conversation_id, _msg_id = chat.persist_user_message(
            app_state, fields["conversation_id"], fields["message"],
            plan=plan, agent_result=agent_result, workspace_id=workspace_id,
        )

        tool_executor = None if (local_ctx or web_ctx) else chat.get_tool_executor(app_state)
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
