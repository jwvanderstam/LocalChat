"""
Mock objects for testing.

Provides pre-configured mock objects for common dependencies.
"""

from unittest.mock import Mock, MagicMock
from typing import List, Dict, Any, Optional
import random


class MockDatabase:
    """Mock database for testing."""
    
    def __init__(self):
        self.is_connected = True
        self.documents = {}
        self.chunks = {}
        self._doc_id_counter = 1
        self._chunk_id_counter = 1
    
    def document_exists(self, filename: str) -> tuple:
        """Check if document exists."""
        for doc_id, doc_info in self.documents.items():
            if doc_info['filename'] == filename:
                return True, doc_info
        return False, None
    
    def insert_document(self, filename: str, content: str, metadata: Optional[Dict] = None) -> int:
        """Insert a document."""
        doc_id = self._doc_id_counter
        self._doc_id_counter += 1
        
        self.documents[doc_id] = {
            'id': doc_id,
            'filename': filename,
            'content': content,
            'metadata': metadata or {},
            'chunk_count': 0
        }
        return doc_id
    
    def insert_chunks_batch(self, chunks_data: List[tuple]) -> None:
        """Insert chunks in batch."""
        for doc_id, chunk_text, chunk_index, embedding in chunks_data:
            chunk_id = self._chunk_id_counter
            self._chunk_id_counter += 1
            
            self.chunks[chunk_id] = {
                'id': chunk_id,
                'document_id': doc_id,
                'chunk_text': chunk_text,
                'chunk_index': chunk_index,
                'embedding': embedding
            }
            
            if doc_id in self.documents:
                self.documents[doc_id]['chunk_count'] += 1
    
    def search_similar_chunks(self, query_embedding: List[float], top_k: int = 5, 
                            file_type_filter: Optional[str] = None) -> List[tuple]:
        """Search for similar chunks."""
        results = []
        for chunk in list(self.chunks.values())[:top_k]:
            doc = self.documents.get(chunk['document_id'], {})
            results.append((
                chunk['chunk_text'],
                doc.get('filename', 'unknown'),
                chunk['chunk_index'],
                random.uniform(0.7, 1.0),
                chunk.get('metadata', {})  # Phase 1.1: Include metadata
            ))
        return results
    
    def get_document_count(self) -> int:
        """Get document count."""
        return len(self.documents)
    
    def get_chunk_count(self) -> int:
        """Get chunk count."""
        return len(self.chunks)
    
    def get_all_documents(self) -> List[Dict]:
        """Get all documents."""
        return list(self.documents.values())
    
    def delete_all_documents(self) -> None:
        """Delete all documents."""
        self.documents.clear()
        self.chunks.clear()
    
    def get_connection(self):
        """Get a mock connection."""
        return MagicMock()
    
    def close(self) -> None:
        """Close connections."""
        self.is_connected = False


class MockOllamaClient:
    """Mock Ollama client for testing."""
    
    def __init__(self):
        self.models = [
            {'name': 'llama3.2', 'size': 4500000000},
            {'name': 'nomic-embed-text', 'size': 274000000}
        ]
        self.embedding_model = 'nomic-embed-text'
    
    def check_connection(self) -> tuple:
        """Check connection."""
        return True, "Connected to Ollama"
    
    def list_models(self) -> tuple:
        """List available models."""
        return True, self.models
    
    def get_first_available_model(self) -> Optional[str]:
        """Get first available model."""
        return self.models[0]['name'] if self.models else None
    
    def get_embedding_model(self, preferred_model: Optional[str] = None) -> Optional[str]:
        """Get embedding model."""
        return preferred_model or self.embedding_model
    
    def generate_embedding(self, model: str, text: str) -> tuple:
        """Generate embedding."""
        embedding = [random.random() for _ in range(768)]
        return True, embedding
    
    def generate_chat_response(self, model: str, messages: List[Dict], 
                              stream: bool = True):
        """Generate chat response."""
        response_chunks = ["Hello", " from", " mock", " Ollama", "!"]
        for chunk in response_chunks:
            yield chunk
    
    def test_model(self, model_name: str) -> tuple:
        """Test model."""
        return True, "Model is working"
    
    def pull_model(self, model_name: str):
        """Pull a model."""
        for i in range(5):
            yield {'status': 'downloading', 'progress': i * 20}
        yield {'status': 'complete', 'progress': 100}
    
    def delete_model(self, model_name: str) -> tuple:
        """Delete a model."""
        return True, f"Model {model_name} deleted"


def create_mock_config():
    """Create a mock config module."""
    config = Mock()
    config.CHUNK_SIZE = 500
    config.CHUNK_OVERLAP = 50
    config.TOP_K_RESULTS = 5
    config.MIN_SIMILARITY_THRESHOLD = 0.7
    config.EMBEDDING_MODEL = 'nomic-embed-text'
    config.MAX_WORKERS = 4
    config.RERANK_RESULTS = True
    config.SIMILARITY_WEIGHT = 0.5
    config.KEYWORD_WEIGHT = 0.2
    config.BM25_WEIGHT = 0.2
    config.POSITION_WEIGHT = 0.1
    return config
