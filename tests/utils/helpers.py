"""
Test utilities and helper functions.

Provides common utilities for testing:
- Mock data generators
- Helper assertions
- Common test patterns
"""

from typing import List, Dict, Any
import random
from faker import Faker

fake = Faker()


def generate_mock_embedding(dimensions: int = 768) -> List[float]:
    """
    Generate a mock embedding vector.
    
    Args:
        dimensions: Number of dimensions (default: 768)
    
    Returns:
        List of floats representing embedding
    """
    return [random.random() for _ in range(dimensions)]


def generate_mock_chunks(count: int = 5, min_length: int = 50, max_length: int = 200) -> List[str]:
    """
    Generate mock text chunks.
    
    Args:
        count: Number of chunks to generate
        min_length: Minimum chunk length
        max_length: Maximum chunk length
    
    Returns:
        List of text chunks
    """
    chunks = []
    for _ in range(count):
        length = random.randint(min_length, max_length)
        chunks.append(fake.text(max_nb_chars=length))
    return chunks


def generate_mock_search_results(count: int = 5) -> List[tuple]:
"""
Generate mock search results.
    
Args:
    count: Number of results
    
Returns:
    List of (chunk_text, filename, chunk_index, similarity, metadata) tuples
"""
results = []
for i in range(count):
    results.append((
        fake.text(max_nb_chars=200),
        f"document_{i}.pdf",
        i,
        random.uniform(0.7, 0.99),
        {'page_number': i + 1, 'section_title': f'Section {i+1}'}  # Phase 1.1: metadata
    ))
return results


def assert_json_response(response, expected_status: int = 200):
    """
    Assert response is JSON with expected status.
    
    Args:
        response: Flask response object
        expected_status: Expected HTTP status code
    
    Raises:
        AssertionError: If response doesn't match expectations
    """
    assert response.status_code == expected_status, f"Expected {expected_status}, got {response.status_code}"
    assert response.content_type == 'application/json', f"Expected JSON, got {response.content_type}"
    assert response.get_json() is not None, "Response has no JSON body"


def assert_error_response(response, error_type: str = None):
    """
    Assert response is a valid error response.
    
    Args:
        response: Flask response object
        error_type: Expected error type (optional)
    """
    assert response.status_code >= 400, f"Expected error status, got {response.status_code}"
    data = response.get_json()
    assert data is not None, "Error response has no JSON body"
    assert 'error' in data or 'message' in data, "Error response missing error/message field"
    
    if error_type:
        assert data.get('error') == error_type, f"Expected error type {error_type}, got {data.get('error')}"


def generate_mock_search_results(count: int = 5) -> List[tuple]:
    """
    Generate mock search results.
    
    Args:
        count: Number of results
    
    Returns:
        List of (chunk_text, filename, chunk_index, similarity) tuples
    """
    results = []
    for i in range(count):
        results.append((
            fake.paragraph(),
            f"document_{i}.pdf",
            i,
            random.uniform(0.7, 1.0)
        ))
    return results


def generate_mock_document_metadata() -> Dict[str, Any]:
    """
    Generate mock document metadata.
    
    Returns:
        Dictionary with document metadata
    """
    return {
        'id': random.randint(1, 1000),
        'filename': fake.file_name(extension='pdf'),
        'chunk_count': random.randint(5, 50),
        'created_at': fake.date_time(),
        'metadata': {
            'pages': random.randint(1, 100),
            'author': fake.name(),
            'size': random.randint(1000, 5000000)
        }
    }


def assert_valid_embedding(embedding: List[float], dimensions: int = 768) -> None:
    """
    Assert that an embedding vector is valid.
    
    Args:
        embedding: Embedding vector to validate
        dimensions: Expected number of dimensions
    
    Raises:
        AssertionError: If embedding is invalid
    """
    assert isinstance(embedding, list), "Embedding must be a list"
    assert len(embedding) == dimensions, f"Embedding must have {dimensions} dimensions"
    assert all(isinstance(x, (int, float)) for x in embedding), "All elements must be numeric"


def assert_sanitized_filename(filename: str) -> None:
    """
    Assert that a filename is properly sanitized.
    
    Args:
        filename: Filename to validate
    
    Raises:
        AssertionError: If filename is not sanitized
    """
    assert ".." not in filename, "Filename contains path traversal"
    assert "/" not in filename, "Filename contains forward slash"
    assert "\\" not in filename, "Filename contains backslash"
    assert all(c not in filename for c in ['<', '>', ':', '"', '|', '?', '*']), "Filename contains special characters"


def create_mock_response(status_code: int = 200, json_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Create a mock HTTP response.
    
    Args:
        status_code: HTTP status code
        json_data: JSON response data
    
    Returns:
        Mock response dictionary
    """
    return {
        'status_code': status_code,
        'json': json_data or {},
        'text': str(json_data) if json_data else ''
    }
