"""
Pytest configuration and fixtures for LocalChat tests.

This file contains shared fixtures, mock objects, and test utilities
that can be used across all test files.
"""

import pytest
import os
import tempfile
from typing import Generator, Dict, Any
from unittest.mock import Mock, MagicMock
from faker import Faker

# Initialize Faker for generating test data
fake = Faker()


# ============================================================================
# CONFIGURATION FIXTURES
# ============================================================================

@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """
    Provide a temporary directory for tests.
    
    Yields:
        str: Path to temporary directory
        
    Example:
        def test_file_creation(temp_dir):
            file_path = os.path.join(temp_dir, "test.txt")
            with open(file_path, 'w') as f:
                f.write("test")
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """
    Provide sample configuration for tests.
    
    Returns:
        Dict: Sample configuration dictionary
    """
    return {
        'chunk_size': 500,
        'chunk_overlap': 50,
        'top_k': 5,
        'min_similarity': 0.7,
        'embedding_model': 'nomic-embed-text',
    }


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest.fixture
def mock_db():
    """
    Provide a mock database instance.
    
    Returns:
        Mock: Mock database object with common methods
    """
    db = Mock()
    db.is_connected = True
    db.document_exists = Mock(return_value=(False, None))
    db.insert_document = Mock(return_value=1)
    db.insert_chunks_batch = Mock()
    db.search_similar_chunks = Mock(return_value=[])
    db.get_document_count = Mock(return_value=0)
    db.get_chunk_count = Mock(return_value=0)
    db.get_all_documents = Mock(return_value=[])
    return db


@pytest.fixture
def sample_embedding() -> list:
    """
    Provide a sample embedding vector.
    
    Returns:
        list: 768-dimensional embedding vector
    """
    return [fake.random.random() for _ in range(768)]


@pytest.fixture
def sample_document_info() -> Dict[str, Any]:
    """
    Provide sample document information.
    
    Returns:
        Dict: Document information dictionary
    """
    return {
        'id': 1,
        'filename': 'sample.pdf',
        'chunk_count': 10,
        'created_at': fake.date_time(),
        'metadata': {'pages': 5}
    }


# ============================================================================
# OLLAMA FIXTURES
# ============================================================================

@pytest.fixture
def mock_ollama_client():
    """
    Provide a mock Ollama client.
    
    Returns:
        Mock: Mock Ollama client with common methods
    """
    client = Mock()
    client.check_connection = Mock(return_value=(True, "Connected"))
    client.list_models = Mock(return_value=(True, [
        {'name': 'llama3.2', 'size': 4500000000},
        {'name': 'nomic-embed-text', 'size': 274000000}
    ]))
    client.get_first_available_model = Mock(return_value='llama3.2')
    client.get_embedding_model = Mock(return_value='nomic-embed-text')
    client.generate_embedding = Mock(return_value=(True, [0.1] * 768))
    client.generate_chat_response = Mock(return_value=iter(["Hello", " world", "!"]))
    client.test_model = Mock(return_value=(True, "OK"))
    return client


# ============================================================================
# TEXT AND DOCUMENT FIXTURES
# ============================================================================

@pytest.fixture
def sample_text() -> str:
    """
    Provide sample text for testing.
    
    Returns:
        str: Sample text content
    """
    return """
    This is a sample document for testing purposes.
    It contains multiple paragraphs and sentences.
    
    The document should be long enough to test chunking.
    We need at least a few hundred characters to make
    meaningful tests for the RAG system.
    
    This paragraph discusses testing strategies and
    the importance of having good test coverage.
    """


@pytest.fixture
def long_text() -> str:
    """
    Provide long text for chunking tests.
    
    Returns:
        str: Long text content (>1000 characters)
    """
    paragraphs = [fake.paragraph(nb_sentences=10) for _ in range(5)]
    return "\n\n".join(paragraphs)


@pytest.fixture
def sample_pdf_path(temp_dir) -> str:
    """
    Create a sample text file (simulating PDF for simple tests).
    
    Args:
        temp_dir: Temporary directory fixture
        
    Returns:
        str: Path to sample file
    """
    file_path = os.path.join(temp_dir, "sample.pdf")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("Sample PDF content for testing.")
    return file_path


@pytest.fixture
def sample_txt_path(temp_dir) -> str:
    """
    Create a sample text file.
    
    Args:
        temp_dir: Temporary directory fixture
        
    Returns:
        str: Path to sample text file
    """
    file_path = os.path.join(temp_dir, "sample.txt")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("Sample text content for testing.\n" * 10)
    return file_path


# ============================================================================
# VALIDATION FIXTURES
# ============================================================================

@pytest.fixture
def valid_chat_request() -> Dict[str, Any]:
    """
    Provide a valid chat request.
    
    Returns:
        Dict: Valid chat request data
    """
    return {
        'message': 'What is this document about?',
        'use_rag': True,
        'history': []
    }


@pytest.fixture
def invalid_chat_request_empty() -> Dict[str, Any]:
    """
    Provide an invalid chat request (empty message).
    
    Returns:
        Dict: Invalid chat request data
    """
    return {
        'message': '',
        'use_rag': True,
        'history': []
    }


@pytest.fixture
def invalid_chat_request_long() -> Dict[str, Any]:
    """
    Provide an invalid chat request (message too long).
    
    Returns:
        Dict: Invalid chat request data
    """
    return {
        'message': 'a' * 6000,  # Exceeds 5000 char limit
        'use_rag': True,
        'history': []
    }


# ============================================================================
# APP FIXTURES
# ============================================================================

@pytest.fixture
def mock_flask_app():
    """
    Provide a mock Flask app for testing.
    
    Returns:
        Mock: Mock Flask application
    """
    app = Mock()
    app.config = {}
    return app


# ============================================================================
# TEST DATA GENERATORS
# ============================================================================

def generate_chunks(count: int = 5) -> list:
    """
    Generate sample text chunks.
    
    Args:
        count: Number of chunks to generate
        
    Returns:
        list: List of text chunks
    """
    return [fake.paragraph(nb_sentences=5) for _ in range(count)]


def generate_search_results(count: int = 5) -> list:
    """
    Generate sample search results.
    
    Args:
        count: Number of results to generate
        
    Returns:
        list: List of (chunk_text, filename, chunk_index, similarity) tuples
    """
    results = []
    for i in range(count):
        results.append((
            fake.paragraph(),
            f"document_{i}.pdf",
            i,
            fake.random.random()
        ))
    return results


# ============================================================================
# MARKER HELPERS
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "db: Database tests")
    config.addinivalue_line("markers", "ollama: Ollama tests")
