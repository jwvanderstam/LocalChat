"""
Integration tests for LocalChat

Tests complete workflows across multiple components.
"""

import pytest
from unittest.mock import Mock, patch
import tempfile
import os
from tests.utils.mocks import MockDatabase, MockOllamaClient
from tests.utils.helpers import generate_mock_embedding


# ============================================================================
# DOCUMENT INGESTION INTEGRATION TESTS
# ============================================================================

@pytest.mark.integration
class TestDocumentIngestionIntegration:
    """Integration tests for document ingestion workflow."""
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_complete_document_ingestion_pipeline(self, mock_ollama, mock_db):
        """Should handle complete document ingestion pipeline."""
        # Setup mocks
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        mock_db.document_exists = db.document_exists
        mock_db.insert_document = db.insert_document
        mock_db.insert_chunks_batch = db.insert_chunks_batch
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        # Create test document
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("This is a test document with enough content to create multiple chunks. " * 20)
            test_file = f.name
        
        try:
            from src.rag import DocumentProcessor
            processor = DocumentProcessor()
            
            # Ingest document
            success, message, doc_id = processor.ingest_document(test_file)
            
            assert success is True
            assert doc_id is not None
            assert db.get_document_count() == 1
            assert db.get_chunk_count() > 0
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_duplicate_document_prevention(self, mock_ollama, mock_db):
        """Should prevent duplicate document ingestion."""
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        mock_db.document_exists = db.document_exists
        mock_db.insert_document = db.insert_document
        mock_db.insert_chunks_batch = db.insert_chunks_batch
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        # Create test document
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content")
            test_file = f.name
        
        try:
            from src.rag import DocumentProcessor
            processor = DocumentProcessor()
            
            # First ingestion
            success1, _, doc_id1 = processor.ingest_document(test_file)
            assert success1 is True
            
            # Second ingestion (should detect duplicate)
            success2, message2, doc_id2 = processor.ingest_document(test_file)
            assert success2 is True
            assert "already exists" in message2
            assert doc_id1 == doc_id2
            
            # Only one document should exist
            assert db.get_document_count() == 1
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)


# ============================================================================
# RAG RETRIEVAL INTEGRATION TESTS
# ============================================================================

@pytest.mark.integration
class TestRAGRetrievalIntegration:
    """Integration tests for RAG retrieval workflow."""
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_complete_rag_retrieval_pipeline(self, mock_ollama, mock_db):
        """Should handle complete RAG retrieval pipeline."""
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        # Setup database with sample data
        doc_id = db.insert_document("test.pdf", "content")
        chunks_data = [
            (doc_id, "chunk about machine learning", 0, generate_mock_embedding()),
            (doc_id, "chunk about neural networks", 1, generate_mock_embedding()),
            (doc_id, "chunk about data science", 2, generate_mock_embedding()),
        ]
        db.insert_chunks_batch(chunks_data)
        
        # Setup mocks
        mock_db.search_similar_chunks = db.search_similar_chunks
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()
        
        # Retrieve context
        results = processor.retrieve_context("machine learning", top_k=5)
        
        assert isinstance(results, list)
        assert len(results) > 0
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_retrieval_with_multiple_documents(self, mock_ollama, mock_db):
        """Should retrieve from multiple documents."""
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        # Insert multiple documents
        doc_id1 = db.insert_document("doc1.pdf", "content1")
        doc_id2 = db.insert_document("doc2.pdf", "content2")
        
        chunks_data = [
            (doc_id1, "Python programming basics", 0, generate_mock_embedding()),
            (doc_id1, "Advanced Python features", 1, generate_mock_embedding()),
            (doc_id2, "JavaScript fundamentals", 0, generate_mock_embedding()),
            (doc_id2, "React framework guide", 1, generate_mock_embedding()),
        ]
        db.insert_chunks_batch(chunks_data)
        
        mock_db.search_similar_chunks = db.search_similar_chunks
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()
        
        results = processor.retrieve_context("programming", top_k=10)
        
        assert isinstance(results, list)
        # Should potentially return chunks from both documents
        assert len(results) > 0


# ============================================================================
# END-TO-END WORKFLOW TESTS
# ============================================================================

@pytest.mark.integration
class TestEndToEndWorkflow:
    """End-to-end workflow tests."""
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_ingest_and_query_workflow(self, mock_ollama, mock_db):
        """Should handle complete ingest + query workflow."""
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        # Setup mocks
        mock_db.document_exists = db.document_exists
        mock_db.insert_document = db.insert_document
        mock_db.insert_chunks_batch = db.insert_chunks_batch
        mock_db.search_similar_chunks = db.search_similar_chunks
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        # Create test document
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Artificial intelligence and machine learning are transforming technology. " * 10)
            test_file = f.name
        
        try:
            from src.rag import DocumentProcessor
            processor = DocumentProcessor()
            
            # Step 1: Ingest document
            success, _, doc_id = processor.ingest_document(test_file)
            assert success is True
            assert db.get_document_count() == 1
            
            # Step 2: Query the document
            results = processor.retrieve_context("artificial intelligence", top_k=3)
            assert isinstance(results, list)
            
            # Step 3: Verify results contain relevant content
            if results:
                # Results should have the expected structure
                for result in results:
                    assert len(result) == 4
                    chunk_text, filename, chunk_idx, similarity = result
                    assert isinstance(chunk_text, str)
                    assert isinstance(filename, str)
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_multiple_documents_and_queries(self, mock_ollama, mock_db):
        """Should handle multiple documents and queries."""
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        # Setup mocks
        mock_db.document_exists = db.document_exists
        mock_db.insert_document = db.insert_document
        mock_db.insert_chunks_batch = db.insert_chunks_batch
        mock_db.search_similar_chunks = db.search_similar_chunks
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        file_paths = []
        try:
            from src.rag import DocumentProcessor
            processor = DocumentProcessor()
            
            # Ingest multiple documents
            for i in range(3):
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(f"Document {i} with unique content about topic {i}. " * 10)
                    file_paths.append(f.name)
                    
                    success, _, _ = processor.ingest_document(f.name)
                    assert success is True
            
            # Verify all documents ingested
            assert db.get_document_count() == 3
            
            # Multiple queries
            queries = ["topic 0", "topic 1", "topic 2"]
            for query in queries:
                results = processor.retrieve_context(query, top_k=5)
                assert isinstance(results, list)
        
        finally:
            for path in file_paths:
                if os.path.exists(path):
                    os.unlink(path)


# ============================================================================
# ERROR HANDLING INTEGRATION TESTS
# ============================================================================

@pytest.mark.integration
class TestErrorHandlingIntegration:
    """Integration tests for error handling."""
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_handles_missing_ollama_model(self, mock_ollama, mock_db):
        """Should handle missing Ollama model gracefully."""
        db = MockDatabase()
        
        # Setup mocks
        mock_db.document_exists = db.document_exists
        mock_ollama.get_embedding_model.return_value = None
        
        # Create test document
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content")
            test_file = f.name
        
        try:
            from src.rag import DocumentProcessor
            processor = DocumentProcessor()
            
            success, message, doc_id = processor.ingest_document(test_file)
            
            # Should fail gracefully
            assert success is False
            assert "model" in message.lower() or "embedding" in message.lower()
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_handles_database_errors(self, mock_ollama, mock_db):
        """Should handle database errors gracefully."""
        ollama = MockOllamaClient()
        
        # Setup mocks to raise error
        mock_db.document_exists.side_effect = Exception("Database error")
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        
        # Create test document
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content")
            test_file = f.name
        
        try:
            from src.rag import DocumentProcessor
            processor = DocumentProcessor()
            
            success, message, doc_id = processor.ingest_document(test_file)
            
            # Should fail gracefully
            assert success is False
            assert isinstance(message, str)
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)


# ============================================================================
# PERFORMANCE INTEGRATION TESTS
# ============================================================================

@pytest.mark.integration
@pytest.mark.slow
class TestPerformanceIntegration:
    """Performance-related integration tests."""
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_handles_large_document(self, mock_ollama, mock_db):
        """Should handle large documents efficiently."""
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        # Setup mocks
        mock_db.document_exists = db.document_exists
        mock_db.insert_document = db.insert_document
        mock_db.insert_chunks_batch = db.insert_chunks_batch
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        # Create large document (10KB)
        large_content = "This is a test sentence. " * 500
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(large_content)
            test_file = f.name
        
        try:
            from src.rag import DocumentProcessor
            processor = DocumentProcessor()
            
            success, _, _ = processor.ingest_document(test_file)
            
            assert success is True
            assert db.get_chunk_count() > 5  # Should create multiple chunks
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)
    
    @patch('rag.db')
    @patch('rag.ollama_client')
    def test_handles_many_queries(self, mock_ollama, mock_db):
        """Should handle many queries efficiently."""
        db = MockDatabase()
        ollama = MockOllamaClient()
        
        # Setup with sample data
        doc_id = db.insert_document("test.pdf", "content")
        chunks_data = [
            (doc_id, f"chunk {i}", i, generate_mock_embedding())
            for i in range(10)
        ]
        db.insert_chunks_batch(chunks_data)
        
        mock_db.search_similar_chunks = db.search_similar_chunks
        mock_ollama.get_embedding_model = ollama.get_embedding_model
        mock_ollama.generate_embedding = ollama.generate_embedding
        
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()
        
        # Run many queries
        for i in range(20):
            results = processor.retrieve_context(f"query {i}", top_k=3)
            assert isinstance(results, list)
