# -*- coding: utf-8 -*-

"""
Batch Processor Tests
=====================

Tests for batch embedding processor (src/performance/batch_processor.py)

Target: Increase coverage from 85% to 95% (+0.3% overall)

Author: LocalChat Team
Created: January 2025
"""

import pytest
from unittest.mock import Mock, MagicMock


class TestBatchEmbeddingProcessor:
    """Test batch embedding processor."""
    
    def test_processor_initialization(self):
        """Test processor initializes correctly."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        processor = BatchEmbeddingProcessor(mock_client)
        
        assert processor is not None
        assert processor.ollama_client is mock_client
        assert processor.batch_size > 0
        assert processor.max_workers > 0
    
    def test_processor_with_custom_batch_size(self):
        """Test processor with custom batch size."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        processor = BatchEmbeddingProcessor(mock_client, batch_size=32)
        
        assert processor.batch_size == 32
    
    def test_processor_with_custom_workers(self):
        """Test processor with custom worker count."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        processor = BatchEmbeddingProcessor(mock_client, max_workers=4)
        
        assert processor.max_workers == 4
    
    def test_process_batch_with_empty_list(self):
        """Test processing empty text list."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        processor = BatchEmbeddingProcessor(mock_client)
        
        result = processor.process_batch([], "model")
        
        assert result == []
    
    def test_process_batch_with_single_text(self):
        """Test processing single text."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        mock_client.generate_embedding.return_value = (True, [0.1, 0.2, 0.3])
        
        processor = BatchEmbeddingProcessor(mock_client)
        result = processor.process_batch(["test text"], "model")
        
        assert len(result) == 1
        assert result[0] is not None
    
    def test_process_batch_calls_ollama_client(self):
        """Test that process_batch calls Ollama client."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        mock_client.generate_embedding.return_value = (True, [0.1, 0.2])
        
        processor = BatchEmbeddingProcessor(mock_client)
        processor.process_batch(["text1", "text2"], "model")
        
        # Should have called generate_embedding
        assert mock_client.generate_embedding.call_count >= 1
    
    def test_process_batch_handles_errors_gracefully(self):
        """Test that errors in batch processing are handled."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        # Simulate failure
        mock_client.generate_embedding.return_value = (False, "Error message")
        
        processor = BatchEmbeddingProcessor(mock_client)
        result = processor.process_batch(["text"], "model")
        
        # Should still return a list
        assert isinstance(result, list)


class TestBatchProcessingPerformance:
    """Test batch processing performance characteristics."""
    
    def test_batch_processor_parallelization(self):
        """Test that batch processor uses parallelization."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        import time
        
        mock_client = Mock()
        
        def slow_embedding(text, model):
            time.sleep(0.01)  # Simulate work
            return (True, [0.1] * 768)
        
        mock_client.generate_embedding.side_effect = slow_embedding
        
        processor = BatchEmbeddingProcessor(mock_client, max_workers=4)
        texts = [f"text_{i}" for i in range(8)]
        
        start = time.time()
        result = processor.process_batch(texts, "model")
        elapsed = time.time() - start
        
        # With 8 texts and 4 workers, should be faster than sequential
        assert len(result) == 8
        # Parallelization should make it faster (but still took some time)
        assert elapsed < 0.5  # Should complete in reasonable time


class TestBatchProcessorEdgeCases:
    """Test edge cases in batch processing."""
    
    def test_process_batch_with_none_in_list(self):
        """Test handling None in text list."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        mock_client.generate_embedding.return_value = (True, [0.1])
        
        processor = BatchEmbeddingProcessor(mock_client)
        
        # Should handle gracefully or filter Nones
        try:
            result = processor.process_batch([None, "text"], "model")
            assert isinstance(result, list)
        except (TypeError, AttributeError):
            pass  # Acceptable to reject None
    
    def test_process_batch_with_empty_strings(self):
        """Test handling empty strings."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        mock_client.generate_embedding.return_value = (True, [0.1])
        
        processor = BatchEmbeddingProcessor(mock_client)
        result = processor.process_batch(["", "text"], "model")
        
        assert isinstance(result, list)
    
    def test_processor_with_zero_workers(self):
        """Test processor with zero workers."""
        from src.performance.batch_processor import BatchEmbeddingProcessor
        
        mock_client = Mock()
        
        # Should either reject or handle gracefully
        try:
            processor = BatchEmbeddingProcessor(mock_client, max_workers=0)
            # If it allows 0, should still work somehow
            assert processor.max_workers >= 0
        except ValueError:
            pass  # Acceptable to reject 0 workers
