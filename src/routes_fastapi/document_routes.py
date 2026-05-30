"""Document routes — upload (SSE), list, delete, stats, retrieval test."""

from __future__ import annotations

import json
import os
import queue
import threading
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile as _StarletteUploadFile

from .. import config
from ..db.connection import DatabaseUnavailableError
from ..utils.file_validation import validate_file_content
from ..utils.logging_config import get_logger
from ..utils.logging_config import sanitize_log_value as _slv
from ..utils.sanitization import sanitize_filename, validate_path
from ..utils.workspace import get_workspace_id

logger = get_logger(__name__)
router = APIRouter()


def _save_upload_file(file: UploadFile) -> str | None:
    """Validate and save a single UploadFile; return path on success or None."""
    if not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in config.SUPPORTED_EXTENSIONS:
        return None
    safe_name = sanitize_filename(file.filename)
    file_path = os.path.join(config.UPLOAD_FOLDER, safe_name)
    if not validate_path(file_path, config.UPLOAD_FOLDER):
        logger.warning("Rejected upload: resolved path escapes upload folder: %r", safe_name)
        return None
    content = file.file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    ok, err = validate_file_content(file_path, ext)
    if not ok:
        os.remove(file_path)
        logger.warning("Rejected upload '%s': %s", safe_name, err)
        return None
    return file_path


def _update_document_count(app_state: Any, workspace_id: str | None = None) -> int:
    try:
        doc_count = app_state.db.get_document_count(workspace_id=workspace_id)
        config.app_state.set_document_count(doc_count)
        return doc_count
    except Exception as count_err:
        logger.warning("Could not update document count: %s", count_err)
        return config.app_state.get_document_count()


def _stream_file_ingest(app_state: Any, file_path: str, workspace_id: str | None) -> list[str]:
    """Ingest a single file synchronously, collecting SSE events into a list."""
    from ..rag.loaders import VISION_MODEL_MISSING_ERROR

    events: list[str] = [
        f"data: {json.dumps({'message': f'Processing {os.path.basename(file_path)}...'})}\n\n"
    ]
    progress_queue: queue.Queue = queue.Queue()
    result_container: dict = {}

    def _run_ingest() -> None:
        try:
            s, m, d = app_state.doc_processor.ingest_document(
                file_path,
                lambda msg: progress_queue.put(("progress", msg)),
                workspace_id=workspace_id,
            )
            result_container.update({"success": s, "message": m, "doc_id": d})
        except Exception as exc:
            result_container.update({"success": False, "message": str(exc), "doc_id": None})
        finally:
            progress_queue.put(("done", None))

    thread = threading.Thread(target=_run_ingest, daemon=True)
    thread.start()

    while True:
        try:
            event_type, event_data = progress_queue.get(timeout=5)
            if event_type == "done":
                break
            events.append(f"data: {json.dumps({'message': event_data})}\n\n")
        except queue.Empty:
            events.append(": keep-alive\n\n")

    thread.join()

    success = result_container.get("success", False)
    message = result_container.get("message", "Unknown error")
    result_payload: dict = {"filename": os.path.basename(file_path), "success": success, "message": message}

    if not success:
        from ..rag.loaders import VISION_MODEL_MISSING_ERROR as _VMME
        if _VMME in message:
            try:
                model, reason = app_state.ollama_client.suggest_vision_model()
                result_payload["suggest_pull"] = {"model": model, "reason": reason}
            except Exception as exc:
                logger.debug("Could not determine vision model suggestion: %s", exc)

    events.append(f"data: {json.dumps({'result': result_payload})}\n\n")

    try:
        os.remove(file_path)
    except OSError as e:
        logger.debug("Failed to remove temp file %s: %s", file_path, e)

    return events


@router.post("/upload")
async def api_upload_documents(request: Request) -> Any:
    form = await request.form()
    uploaded_files = form.getlist("files")
    if not uploaded_files:
        return JSONResponse({"success": False, "message": "No files provided"}, status_code=400)

    file_paths: list[str] = []
    for file in uploaded_files:
        if isinstance(file, _StarletteUploadFile):
            path = _save_upload_file(file)
            if path:
                file_paths.append(path)

    if not file_paths:
        return JSONResponse({"success": False, "message": "No supported files found"}, status_code=400)

    app_state = request.app.state
    workspace_id = get_workspace_id(request)

    async def _generate() -> AsyncGenerator[str, None]:
        try:
            for file_path in file_paths:
                events = _stream_file_ingest(app_state, file_path, workspace_id)
                for event in events:
                    yield event
            doc_count = _update_document_count(app_state, workspace_id)
            yield f"data: {json.dumps({'done': True, 'total_documents': doc_count})}\n\n"
        except Exception as exc:
            logger.error("Upload stream error: %s", exc, exc_info=True)
            yield f"data: {json.dumps({'error': 'Upload failed', 'done': True})}\n\n"
        finally:
            for fp in file_paths:
                try:
                    os.remove(fp)
                except OSError:
                    pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/list")
def api_list_documents(request: Request) -> Any:
    try:
        documents = request.app.state.db.get_all_documents(workspace_id=get_workspace_id(request))
        return {"success": True, "documents": documents}
    except DatabaseUnavailableError as exc:
        logger.error("DB unavailable listing documents: %s", exc)
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)
    except Exception as exc:
        logger.error("Error listing documents: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": "Failed to retrieve documents"}, status_code=500)


@router.get("/stats")
def api_document_stats(request: Request) -> Any:
    workspace_id = get_workspace_id(request)
    try:
        db = request.app.state.db
        return {
            "success": True,
            "document_count": db.get_document_count(workspace_id=workspace_id),
            "chunk_count": db.get_chunk_count(workspace_id=workspace_id),
            "chunk_statistics": db.get_chunk_statistics(),
            "max_upload_size": config.MAX_CONTENT_LENGTH,
        }
    except DatabaseUnavailableError as exc:
        logger.error("DB unavailable getting stats: %s", exc)
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)
    except Exception as exc:
        logger.error("Error getting document stats: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": "Failed to retrieve statistics"}, status_code=500)


@router.post("/test")
async def api_test_retrieval(request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    query = data.get("query", "").strip()
    if not query:
        return JSONResponse({"success": False, "message": "Query required"}, status_code=400)
    if len(query) > 1000:
        return JSONResponse({"success": False, "message": "Query too long"}, status_code=400)

    try:
        from ..utils.sanitization import sanitize_query
        query = sanitize_query(query)
    except ImportError:
        pass

    try:
        doc_processor = request.app.state.doc_processor
        results_hybrid = doc_processor.retrieve_context(query, use_hybrid_search=True)
        results_semantic = doc_processor.retrieve_context(query, use_hybrid_search=False)
        return {
            "success": True,
            "query": query,
            "results": {
                "hybrid": _format_test_results(results_hybrid, "Hybrid (Semantic + BM25)"),
                "semantic_only": _format_test_results(results_semantic, "Semantic Only"),
            },
            "diagnostic": {
                "hybrid_count": len(results_hybrid),
                "semantic_count": len(results_semantic),
                "recommendation": _get_search_recommendation(results_hybrid, results_semantic),
            },
        }
    except Exception as exc:
        logger.error("Error in test_retrieval: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": "Failed to test retrieval"}, status_code=500)


@router.post("/search-text")
async def api_search_text(request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    search_text = data.get("search_text", "").strip()
    limit = data.get("limit", 10)
    if not search_text:
        return JSONResponse({"success": False, "message": "search_text required"}, status_code=400)
    try:
        results = request.app.state.db.search_chunks_by_text(search_text, limit)
        return {"success": True, "search_text": search_text, "count": len(results), "results": results}
    except Exception as exc:
        logger.error("Error searching text: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": "Search failed"}, status_code=500)


@router.get("/chunks/{chunk_id}/context")
def api_get_chunk_context(chunk_id: int, request: Request, window: int = 1) -> Any:
    window = min(window, 5)
    try:
        db = request.app.state.db
        chunk = db.get_chunk_by_id(chunk_id)
        if chunk is None:
            return JSONResponse({"success": False, "message": "Chunk not found"}, status_code=404)
        adjacent = db.get_adjacent_chunks(chunk["document_id"], chunk["chunk_index"], window_size=window)
        return {
            "success": True,
            "chunk_id": chunk_id,
            "document_id": chunk["document_id"],
            "chunk_index": chunk["chunk_index"],
            "window": window,
            "chunks": [{"chunk_text": text, "chunk_index": idx} for text, idx in adjacent],
        }
    except Exception:
        logger.error("Error fetching chunk context for %s", str(chunk_id), exc_info=True)
        return JSONResponse({"success": False, "message": "Failed to fetch chunk context"}, status_code=500)


@router.delete("/clear")
def api_clear_documents(request: Request) -> Any:
    try:
        logger.warning("Clearing all documents from database")
        request.app.state.db.delete_all_documents()
        config.app_state.set_document_count(0)
        return {"success": True, "message": "All documents and chunks have been deleted"}
    except DatabaseUnavailableError as exc:
        logger.error("DB unavailable clearing documents: %s", exc)
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)
    except Exception as exc:
        logger.error("Error clearing documents: %s", exc, exc_info=True)
        return JSONResponse({"success": False, "message": "Failed to clear documents"}, status_code=500)


@router.delete("/{doc_id}")
def api_delete_document(doc_id: int, request: Request) -> Any:
    try:
        request.app.state.db.delete_document(doc_id)
        _update_document_count(request.app.state)
        return {"success": True}
    except DatabaseUnavailableError as exc:
        logger.error("DB unavailable deleting document %s: %s", _slv(str(doc_id)), exc)
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)
    except Exception as exc:
        logger.error("Error deleting document %s: %s", _slv(str(doc_id)), exc, exc_info=True)
        return JSONResponse({"success": False, "message": "Failed to delete document"}, status_code=500)


def _format_test_results(results: list, mode_name: str) -> dict[str, Any]:
    if not results:
        return {"mode": mode_name, "count": 0, "chunks": []}
    formatted = []
    for chunk_text, filename, chunk_index, similarity, metadata, *_ in results:
        chunk_data: dict[str, Any] = {
            "filename": filename,
            "chunk_index": chunk_index,
            "similarity": round(similarity, 4),
            "preview": chunk_text[:200] + "..." if len(chunk_text) > 200 else chunk_text,
            "length": len(chunk_text),
        }
        if metadata.get("page_number"):
            chunk_data["page_number"] = metadata["page_number"]
        if metadata.get("section_title"):
            chunk_data["section_title"] = metadata["section_title"]
        formatted.append(chunk_data)
    return {"mode": mode_name, "count": len(formatted), "chunks": formatted}


def _get_search_recommendation(hybrid_results: list, semantic_results: list) -> str:
    if not hybrid_results and not semantic_results:
        return "No results found. Try: 1) Lower MIN_SIMILARITY_THRESHOLD, 2) Upload more relevant documents, 3) Rephrase query"
    if len(hybrid_results) < len(semantic_results):
        return "Semantic-only search found more results. Your query may have no keyword matches - this is normal for conceptual questions."
    if len(hybrid_results) > len(semantic_results):
        return "Hybrid search found more results. BM25 keyword matching is helping improve retrieval."
    return "Both modes returned same number of results. Query works well with either mode."
