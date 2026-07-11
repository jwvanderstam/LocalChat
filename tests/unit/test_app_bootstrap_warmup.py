"""
App Bootstrap Warm-up Tests
===========================

Tests for the startup warm-up helpers in src/app_bootstrap.py that amortise
first-request latency (embedding model CUDA kernel compile, reranker model load).
"""

from unittest.mock import MagicMock, patch


class TestWarmupReranker:
    """Test _warmup_reranker (src/app_bootstrap.py)."""

    def test_skips_when_reranker_disabled(self):
        from src.app_bootstrap import _warmup_reranker

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = False
            with patch("src.rag.reranker.get_reranker") as mock_get_reranker:
                _warmup_reranker()
                mock_get_reranker.assert_not_called()

    def test_loads_reranker_when_enabled(self):
        from src.app_bootstrap import _warmup_reranker

        mock_reranker = MagicMock()
        mock_reranker.is_available.return_value = True

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch("src.rag.reranker.get_reranker", return_value=mock_reranker) as mock_get_reranker:
                _warmup_reranker()
                mock_get_reranker.assert_called_once()

    def test_does_not_raise_when_reranker_load_fails(self):
        from src.app_bootstrap import _warmup_reranker

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch("src.rag.reranker.get_reranker", side_effect=RuntimeError("boom")):
                _warmup_reranker()  # must not raise — warm-up failures are non-fatal
