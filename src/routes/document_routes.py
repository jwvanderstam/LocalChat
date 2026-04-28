
"""
Document Routes Blueprint
========================

Document management API endpoints for LocalChat application.
Handles upload, list, search, and testing operations.

"""

import json
import os
import queue
import threading
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flask import Blueprint, Response, jsonify, request
from flask import current_app as _current_app
from flask.typing import ResponseReturnValue

if TYPE_CHECKING:
    from ..types import LocalChatApp
    current_app: LocalChatApp
else:
    current_app = _current_app

from .. import config
from ..security import limiter
from ..utils.file_validation import validate_file_content
from ..utils.logging_config import get_logger
from ..utils.sanitization import sanitize_filename, validate_path

bp = Blueprint('documents', __name__)
logger = get_logger(__name__)


def _save_uploaded_files(files) -> list:
    """Filter by supported extension, validate content, save to the upload folder, return saved paths."""
    from .. import config
    saved = []
    for file in files:
        if not file.filename:
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in config.SUPPORTED_EXTENSIONS:
            continue
        safe_name = sanitize_filename(file.filename)
        file_path = os.path.join(config.UPLOAD_FOLDER, safe_name)
        if not validate_path(file_path, config.UPLOAD_FOLDER):
            logger.warning(f"Rejected upload: resolved path escapes upload folder: {safe_name!r}")
            continue
        file.save(file_path)
        ok, err = validate_file_content(file_path, ext)
        if not ok:
            os.remove(file_path)
            logger.warning(f"Rejected upload '{safe_name}': {err}")
            continue
        saved.append(file_path)
    return saved


def _update_document_count(app) -> int:
    """Fetch and cache the latest document count, falling back to the cached value."""
    from .. import config
    try:
        doc_count = app.db.get_document_count()
        config.app_state.set_document_count(doc_count)
        return doc_count
    except Exception as count_err:
        logger.warning(f"Could not update document count: {count_err}")
        return config.app_state.get_document_count()


def _stream_file_ingest(app, file_path: str) -> Generator[str, None, None]:
    """Ingest a single file and yield SSE progress events."""
    yield f"data: {json.dumps({'message': f'Processing {os.path.basename(file_path)}...'})}\n\n"

    progress_queue: queue.Queue = queue.Queue()
    result_container: dict = {}

    def _run_ingest(path=file_path, pq=progress_queue, rc=result_container):
        from .. import config as _cfg
        workspace_id = _cfg.app_state.get_active_workspace_id()
        try:
            s, m, d = app.doc_processor.ingest_document(
                path,
                lambda msg: pq.put(('progress', msg)),
                workspace_id=workspace_id,
            )
            rc.update({'success': s, 'message': m, 'doc_id': d})
        except Exception as exc:
            rc.update({'success': False, 'message': str(exc), 'doc_id': None})
        finally:
            pq.put(('done', None))

    thread = threading.Thread(target=_run_ingest, daemon=True)
    thread.start()

    while True:
        try:
            event_type, event_data = progress_queue.get(timeout=5)
            if event_type == 'done':
                break
            yield f"data: {json.dumps({'message': event_data})}\n\n"
        except queue.Empty:
            yield ": keep-alive\n\n"

    thread.join()

    success = result_container.get('success', False)
    message = result_container.get('message', 'Unknown error')
    yield f"data: {json.dumps({'result': {'filename': os.path.basename(file_path), 'success': success, 'message': message}})}\n\n"

    try:
        os.remove(file_path)
    except OSError as e:
        logger.debug("Failed to remove temp file %s: %s", file_path, e)


@bp.route('/upload', methods=['POST'])
@limiter.limit(config.RATELIMIT_UPLOAD)
def api_upload_documents() -> ResponseReturnValue:
    """
    Upload and ingest documents.

    Upload one or more documents for RAG processing and indexing.
    ---
    tags:
      - Documents
    summary: Upload documents
    description: |
      Upload documents for RAG processing. Supported formats:
      - PDF (with table extraction)
      - DOCX (Microsoft Word)
      - TXT (plain text)
      - MD (Markdown)

      **Maximum file size**: Configured via MAX_CONTENT_LENGTH (default 16 MB)

      **Processing steps**:
      1. File validation and storage
      2. Text extraction (with table detection for PDFs)
      3. Intelligent chunking
      4. Embedding generation
      5. Vector database storage

      Returns progress via Server-Sent Events (SSE).
    consumes:
      - multipart/form-data
    produces:
      - text/event-stream
    parameters:
      - name: files
        in: formData
        type: file
        required: true
        description: One or more document files to upload
    responses:
      200:
        description: Upload progress stream
        schema:
          type: object
          properties:
            message:
              type: string
              description: Progress message
            result:
              type: object
              properties:
                filename:
                  type: string
                success:
                  type: boolean
                message:
                  type: string
            done:
              type: boolean
              description: Upload completion flag
            total_documents:
              type: integer
              description: Total documents in system after upload
        examples:
          text/event-stream: |
            data: {"message": "Processing document.pdf..."}

            data: {"result": {"filename": "document.pdf", "success": true, "message": "Ingested successfully"}}

            data: {"done": true, "total_documents": 42}
      400:
        description: Bad request (no files, invalid format)
        schema:
          $ref: '#/definitions/Error'
      413:
        description: File too large (exceeds MAX_CONTENT_LENGTH limit)
        schema:
          $ref: '#/definitions/Error'
    """
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': 'No files provided'}), 400

    files = request.files.getlist('files')

    if not files or files[0].filename == '':
        return jsonify({'success': False, 'message': 'No files selected'}), 400

    file_paths = _save_uploaded_files(files)

    if not file_paths:
        return jsonify({'success': False, 'message': 'No supported files found'}), 400

    # Get references to app objects before entering generator
    app = current_app._get_current_object()  # type: ignore[attr-defined]

    # Stream ingestion progress
    def generate() -> Generator[str, None, None]:
        try:
            for file_path in file_paths:
                yield from _stream_file_ingest(app, file_path)
            doc_count = _update_document_count(app)
            yield f"data: {json.dumps({'done': True, 'total_documents': doc_count})}\n\n"
        except GeneratorExit:
            pass
        except Exception as e:
            logger.error("Upload stream error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'error': 'Upload failed', 'done': True})}\n\n"
        finally:
            for fp in file_paths:
                try:
                    os.remove(fp)
                except OSError:
                    pass  # already deleted or unremovable

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@bp.route('/list', methods=['GET'])
def api_list_documents() -> ResponseReturnValue:
    """
    List all documents.

    Retrieve a list of all documents in the system with metadata.
    ---
    tags:
      - Documents
    summary: List all documents
    description: |
      Returns all documents with metadata including:
      - Document ID
      - Filename
      - File type
      - Upload timestamp
      - Chunk count
      - Processing status
    responses:
      200:
        description: Document list retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            documents:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: string
                    description: Document UUID
                  filename:
                    type: string
                  file_type:
                    type: string
                  uploaded_at:
                    type: string
                    format: date-time
                  chunk_count:
                    type: integer
        examples:
          application/json:
            success: true
            documents:
              - id: "abc-123-def"
                filename: "report.pdf"
                file_type: "pdf"
                uploaded_at: "2025-01-15T10:30:00Z"
                chunk_count: 25
      500:
        description: Server error retrieving documents
        schema:
          $ref: '#/definitions/Error'
    """
    from ..db import DatabaseUnavailableError
    try:
        workspace_id = config.app_state.get_active_workspace_id()
        documents = current_app.db.get_all_documents(workspace_id=workspace_id)
        return jsonify({
            'success': True,
            'documents': documents
        })
    except DatabaseUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve documents'
        }), 500


@bp.route('/test', methods=['POST'])
def api_test_retrieval() -> ResponseReturnValue:
    """
    Test RAG retrieval with detailed diagnostic information.

    Request Body:
        - query (str): Search query
        - use_hybrid_search (bool, optional): Enable/disable BM25

    Returns:
        JSON response with retrieval results and diagnostics
    """
    try:
        data = request.get_json()

        data = data or {}
        query = data.get('query', '').strip()
        if not query:
            return jsonify({'success': False, 'message': 'Query required'}), 400
        if len(query) > 1000:
            return jsonify({'success': False, 'message': 'Query too long'}), 400

        use_hybrid = data.get('use_hybrid_search', True)

        try:
            from ..utils.sanitization import sanitize_query
            query = sanitize_query(query)
        except ImportError:
            pass
        logger.info("Testing retrieval")
        # Test both modes
        results_hybrid = current_app.doc_processor.retrieve_context(query, use_hybrid_search=True)
        results_semantic = current_app.doc_processor.retrieve_context(query, use_hybrid_search=False)

        # Format response
        response = {
            'success': True,
            'query': query,
            'hybrid_search': use_hybrid,
            'results': {
                'hybrid': _format_test_results(results_hybrid, 'Hybrid (Semantic + BM25)'),
                'semantic_only': _format_test_results(results_semantic, 'Semantic Only')
            },
            'diagnostic': {
                'hybrid_count': len(results_hybrid),
                'semantic_count': len(results_semantic),
                'recommendation': _get_search_recommendation(results_hybrid, results_semantic)
            }
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error in test_retrieval: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Failed to test retrieval'
        }), 500


@bp.route('/stats', methods=['GET'])
def api_document_stats() -> ResponseReturnValue:
    """
    Get document statistics including chunk analysis.

    Retrieve comprehensive statistics about documents and chunks.
    ---
    tags:
      - Documents
    summary: Get document statistics
    description: |
      Returns detailed statistics including:
      - Total document count
      - Total chunk count
      - Average chunks per document
      - Chunk size distribution
      - Processing statistics
    responses:
      200:
        description: Statistics retrieved successfully
        schema:
          $ref: '#/definitions/DocumentStats'
        examples:
          application/json:
            success: true
            document_count: 42
            chunk_count: 1250
            chunk_statistics:
              avg_chunks_per_doc: 29.8
              min_chunk_size: 156
              max_chunk_size: 1024
              avg_chunk_size: 768
      500:
        description: Server error retrieving statistics
        schema:
          $ref: '#/definitions/Error'
    """
    from ..db import DatabaseUnavailableError
    try:
        doc_count = current_app.db.get_document_count()
        chunk_count = current_app.db.get_chunk_count()
        chunk_stats = current_app.db.get_chunk_statistics()

        return jsonify({
            'success': True,
            'document_count': doc_count,
            'chunk_count': chunk_count,
            'chunk_statistics': chunk_stats,
            'max_upload_size': current_app.config.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024)
        })
    except DatabaseUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Error getting document stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve statistics'
        }), 500


@bp.route('/search-text', methods=['POST'])
def api_search_text() -> ResponseReturnValue:
    """
    Search chunks by text content (for debugging).

    Request Body:
        - search_text (str): Text to search for
        - limit (int, optional): Max results

    Returns:
        JSON response with matching chunks
    """
    from ..db import DatabaseUnavailableError
    try:
        data = request.get_json() or {}
        search_text = data.get('search_text', '').strip()
        limit = data.get('limit', 10)

        if not search_text:
            return jsonify({
                'success': False,
                'message': 'search_text required'
            }), 400

        from ..utils.logging_config import sanitize_log_value as _slv
        logger.info("Searching chunks for text: %s", _slv(search_text))
        results = current_app.db.search_chunks_by_text(search_text, limit)

        return jsonify({
            'success': True,
            'search_text': search_text,
            'count': len(results),
            'results': results
        })

    except DatabaseUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Error searching text: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Search failed'
        }), 500


@bp.route('/chunks/<int:chunk_id>/context', methods=['GET'])
def api_get_chunk_context(chunk_id: int) -> ResponseReturnValue:
    """
    Return a chunk and its surrounding neighbours for source attribution.

    Query params:
        window (int, optional): Chunks before/after to include (default 1, max 5)

    Returns:
        JSON with the target chunk plus adjacent chunks ordered by chunk_index.
    """
    from ..db import DatabaseUnavailableError
    try:
        window = min(int(request.args.get('window', 1)), 5)
    except (TypeError, ValueError):
        window = 1

    try:
        chunk = current_app.db.get_chunk_by_id(chunk_id)
        if chunk is None:
            return jsonify({'success': False, 'message': 'Chunk not found'}), 404

        adjacent = current_app.db.get_adjacent_chunks(
            chunk['document_id'], chunk['chunk_index'], window_size=window
        )
        return jsonify({
            'success': True,
            'chunk_id': chunk_id,
            'document_id': chunk['document_id'],
            'chunk_index': chunk['chunk_index'],
            'window': window,
            'chunks': [
                {'chunk_text': text, 'chunk_index': idx}
                for text, idx in adjacent
            ],
        })
    except DatabaseUnavailableError:
        raise
    except Exception:
        logger.error("Error fetching chunk context for %s", str(chunk_id).replace('\r', '').replace('\n', ' '), exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to fetch chunk context'}), 500


@bp.route('/clear', methods=['DELETE'])
def api_clear_documents() -> ResponseReturnValue:
    """
    Clear all documents and chunks from the database.

    Warning: This operation cannot be undone!

    Returns:
        JSON response with success status
    """
    from .. import config
    from ..db import DatabaseUnavailableError

    try:
        logger.warning("Clearing all documents from database")
        current_app.db.delete_all_documents()

        # Update document count
        config.app_state.set_document_count(0)

        logger.info("All documents cleared successfully")
        return jsonify({
            'success': True,
            'message': 'All documents and chunks have been deleted'
        })
    except DatabaseUnavailableError:
        raise  # propagate to the global 503 error handler
    except Exception as e:
        logger.error(f"Error clearing documents: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Failed to clear documents'
        }), 500


# Helper functions

def _format_test_results(results, mode_name: str) -> dict[str, Any]:
    """Format results for test API response."""
    if not results:
        return {'mode': mode_name, 'count': 0, 'chunks': []}

    formatted = []
    for chunk_text, filename, chunk_index, similarity, metadata, *_ in results:
        chunk_data = {
            'filename': filename,
            'chunk_index': chunk_index,
            'similarity': round(similarity, 4),
            'preview': chunk_text[:200] + '...' if len(chunk_text) > 200 else chunk_text,
            'length': len(chunk_text)
        }

        # Add optional per-chunk metadata
        if metadata.get('page_number'):
            chunk_data['page_number'] = metadata['page_number']
        if metadata.get('section_title'):
            chunk_data['section_title'] = metadata['section_title']

        formatted.append(chunk_data)

    return {
        'mode': mode_name,
        'count': len(formatted),
        'chunks': formatted
    }


def _get_search_recommendation(hybrid_results, semantic_results) -> str:
    """Provide recommendation based on test results."""
    if len(hybrid_results) == 0 and len(semantic_results) == 0:
        return "No results found. Try: 1) Lower MIN_SIMILARITY_THRESHOLD, 2) Upload more relevant documents, 3) Rephrase query"
    elif len(hybrid_results) < len(semantic_results):
        return "Semantic-only search found more results. Your query may have no keyword matches - this is normal for conceptual questions."
    elif len(hybrid_results) > len(semantic_results):
        return "Hybrid search found more results. BM25 keyword matching is helping improve retrieval."
    else:
        return "Both modes returned same number of results. Query works well with either mode."

