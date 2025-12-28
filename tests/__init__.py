"""
LocalChat Test Suite
====================

Comprehensive test suite for the LocalChat RAG application.

Test Structure:
    - Unit tests: tests/test_*.py
    - Integration tests: tests/integration/test_*.py
    - Test fixtures: tests/conftest.py
    - Test utilities: tests/utils/

Usage:
    # Run all tests
    pytest

    # Run with coverage
    pytest --cov

    # Run specific test file
    pytest tests/test_sanitization.py

    # Run specific test
    pytest tests/test_sanitization.py::test_sanitize_filename

    # Run only unit tests
    pytest -m unit

    # Run only integration tests
    pytest -m integration
"""

__version__ = "1.0.0"
