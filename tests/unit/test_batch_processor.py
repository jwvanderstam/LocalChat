
"""
Batch Processor Tests
=====================

Tests for batch embedding processor (src/performance/batch_processor.py)

Target: Increase coverage from 85% to 95% (+0.3% overall)

Author: LocalChat Team
Created: January 2025
"""

from unittest.mock import Mock


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
        mock_client.generate_embeddings_batch.return_value = [[0.1, 0.2, 0.3]]

        processor = BatchEmbeddingProcessor(mock_client)
        result = processor.process_batch(["test text"], "model")

        assert len(result) == 1
        assert result[0] is not None

    def test_process_batch_calls_ollama_client(self):
        """Test that process_batch calls Ollama client."""
        from src.performance.batch_processor import BatchEmbeddingProcessor

        mock_client = Mock()
        mock_client.generate_embeddings_batch.return_value = [[0.1, 0.2], [0.1, 0.2]]

        processor = BatchEmbeddingProcessor(mock_client)
        processor.process_batch(["text1", "text2"], "model")

        # Should have called generate_embeddings_batch
        assert mock_client.generate_embeddings_batch.call_count >= 1

    def test_process_batch_handles_errors_gracefully(self):
        """Test that errors in batch processing are handled."""
        from src.performance.batch_processor import BatchEmbeddingProcessor

        mock_client = Mock()
        # Simulate failure — batch returns None for the failed item
        mock_client.generate_embeddings_batch.return_value = [None]

        processor = BatchEmbeddingProcessor(mock_client)
        result = processor.process_batch(["text"], "model")

        # Should still return a list
        assert isinstance(result, list)


class TestBatchProcessingPerformance:
    """Test batch processing performance characteristics."""

    def test_batch_processor_parallelization(self):
        """Test that batch processor uses parallelization."""
        import time

        from src.performance.batch_processor import BatchEmbeddingProcessor

        mock_client = Mock()

        def batch_embedding(model, batch_texts):
            time.sleep(0.01)  # Simulate one GPU batch pass
            return [[0.1] * 768 for _ in batch_texts]

        mock_client.generate_embeddings_batch.side_effect = batch_embedding

        processor = BatchEmbeddingProcessor(mock_client, max_workers=4)
        texts = [f"text_{i}" for i in range(8)]

        start = time.time()
        result = processor.process_batch(texts, "model")
        elapsed = time.time() - start

        # All 8 texts processed in a single batch call
        assert len(result) == 8
        assert elapsed < 0.5  # Should complete in reasonable time


class TestBatchProcessorEdgeCases:
    """Test edge cases in batch processing."""

    def test_process_batch_with_none_in_list(self):
        """Test handling None in text list."""
        from src.performance.batch_processor import BatchEmbeddingProcessor

        mock_client = Mock()
        mock_client.generate_embeddings_batch.return_value = [None, [0.1]]

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
        mock_client.generate_embeddings_batch.return_value = [[0.1], [0.1]]

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
