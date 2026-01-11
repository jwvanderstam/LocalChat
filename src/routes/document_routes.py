# -*- coding: utf-8 -*-

"""
Document Routes Blueprint
========================

Document management API endpoints for LocalChat application.
Handles upload, list, search, and testing operations.

Author: LocalChat Team
Created: 2025-01-15
"""

from flask import Blueprint, jsonify, request, Response, current_app
from typing import Generator, Dict, Any
from pathlib import Path
import os
import json

from ..utils.logging_config import get_logger

bp = Blueprint('documents', __name__)
logger = get_logger(__name__)


@bp.route('/upload', methods=['POST'])
def api_upload_documents():
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
      
      **Maximum file size**: 16 MB
      
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
        description: File too large (exceeds 16 MB limit)
        schema:
          $ref: '#/definitions/Error'
    """
    from .. import config
    
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    
    if not files or files[0].filename == '':
        return jsonify({'success': False, 'message': 'No files selected'}), 400
    
    # Save files temporarily
    file_paths = []
    for file in files:
        if file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext in config.SUPPORTED_EXTENSIONS:
                file_path = os.path.join(config.UPLOAD_FOLDER, file.filename)
                file.save(file_path)
                file_paths.append(file_path)
    
    if not file_paths:
        return jsonify({'success': False, 'message': 'No supported files found'}), 400
    
    # Stream ingestion progress
    def generate() -> Generator[str, None, None]:
        results = []
        for file_path in file_paths:
            yield f"data: {json.dumps({'message': f'Processing {os.path.basename(file_path)}...'})}\n\n"
            
            success, message, doc_id = current_app.doc_processor.ingest_document(
                file_path,
                lambda m: None
            )
            
            results.append({
                'filename': os.path.basename(file_path),
                'success': success,
                'message': message
            })
            
            yield f"data: {json.dumps({'result': results[-1]})}\n\n"
            
            # Clean up temporary file
            try:
                os.remove(file_path)
            except:
                pass
        
        # Update document count
        doc_count = current_app.db.get_document_count()
        config.app_state.set_document_count(doc_count)
        
        yield f"data: {json.dumps({'done': True, 'total_documents': doc_count})}\n\n"
    
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@bp.route('/list')
def api_list_documents():
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
    try:
        documents = current_app.db.get_all_documents()
        return jsonify({
            'success': True,
            'documents': documents
        })
    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bp.route('/test', methods=['POST'])
def api_test_retrieval():
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
        
        # Try Month 2 validation
        try:
            from ..models import RetrievalRequest
            from ..utils.sanitization import sanitize_query
            
            request_data = RetrievalRequest(**data)
            query = sanitize_query(request_data.query)
            use_hybrid = data.get('use_hybrid_search', True)
            
        except ImportError:
            # Month 1 validation
            query = data.get('query', 'What is this about?').strip()
            use_hybrid = data.get('use_hybrid_search', True)
            
            if not query:
                return jsonify({'success': False, 'message': 'Query required'}), 400
            if len(query) > 1000:
                return jsonify({'success': False, 'message': 'Query too long'}), 400
        
        logger.info(f"Testing retrieval: {query[:50]}... (hybrid={use_hybrid})")
        
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


@bp.route('/stats')
def api_document_stats():
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
    try:
        doc_count = current_app.db.get_document_count()
        chunk_count = current_app.db.get_chunk_count()
        chunk_stats = current_app.db.get_chunk_statistics()
        
        return jsonify({
            'success': True,
            'document_count': doc_count,
            'chunk_count': chunk_count,
            'chunk_statistics': chunk_stats
        })
    except Exception as e:
        logger.error(f"Error getting document stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bp.route('/search-text', methods=['POST'])
def api_search_text():
    """
    Search chunks by text content (for debugging).
    
    Request Body:
        - search_text (str): Text to search for
        - limit (int, optional): Max results
    
    Returns:
        JSON response with matching chunks
    """
    try:
        data = request.get_json()
        search_text = data.get('search_text', '').strip()
        limit = data.get('limit', 10)
        
        if not search_text:
            return jsonify({
                'success': False,
                'message': 'search_text required'
            }), 400
        
        logger.info(f"Searching chunks for text: {search_text}")
        results = current_app.db.search_chunks_by_text(search_text, limit)
        
        return jsonify({
            'success': True,
            'search_text': search_text,
            'count': len(results),
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error searching text: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bp.route('/clear', methods=['DELETE'])
def api_clear_documents():
    """
    Clear all documents and chunks from the database.
    
    Warning: This operation cannot be undone!
    
    Returns:
        JSON response with success status
    """
    from .. import config
    
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
    except Exception as e:
        logger.error(f"Error clearing documents: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# Helper functions

def _format_test_results(results, mode_name: str) -> Dict[str, Any]:
    """Format results for test API response."""
    if not results:
        return {'mode': mode_name, 'count': 0, 'chunks': []}
    
    formatted = []
    for chunk_text, filename, chunk_index, similarity in results:
        formatted.append({
            'filename': filename,
            'chunk_index': chunk_index,
            'similarity': round(similarity, 4),
            'preview': chunk_text[:200] + '...' if len(chunk_text) > 200 else chunk_text,
            'length': len(chunk_text)
        })
    
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
