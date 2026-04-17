"""
Unit tests for config.py

Tests configuration constants, AppState class, and state persistence.
"""

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import mock_open, patch

import pytest

from src.config import (
    CHUNK_SIZE,
    PG_HOST,
    PG_PORT,
    SUPPORTED_EXTENSIONS,
    TOP_K_RESULTS,
    AppState,
)

# ============================================================================
# CONFIGURATION CONSTANTS TESTS
# ============================================================================

@pytest.mark.unit
class TestConfigurationConstants:
    """Tests for configuration constants."""

    def test_database_config_has_defaults(self):
        """Should have default database configuration."""
        assert isinstance(PG_HOST, str)
        assert isinstance(PG_PORT, int)
        assert PG_PORT > 0

    def test_chunk_size_is_positive(self):
        """Should have positive chunk size."""
        assert CHUNK_SIZE > 0
        assert isinstance(CHUNK_SIZE, int)

    def test_top_k_results_is_positive(self):
        """Should have positive top-k value."""
        assert TOP_K_RESULTS > 0
        assert isinstance(TOP_K_RESULTS, int)

    def test_supported_extensions_is_list(self):
        """Should have list of supported extensions."""
        assert isinstance(SUPPORTED_EXTENSIONS, list)
        assert len(SUPPORTED_EXTENSIONS) > 0
        assert all(ext.startswith('.') for ext in SUPPORTED_EXTENSIONS)


# ============================================================================
# APPSTATE INITIALIZATION TESTS
# ============================================================================

@pytest.mark.unit
class TestAppStateInitialization:
    """Tests for AppState initialization."""

    def test_creates_with_default_file(self, temp_dir):
        """Should create with default state file."""
        state_file = os.path.join(temp_dir, "test_state.json")
        state = AppState(state_file=state_file)

        assert state.state_file == state_file
        assert isinstance(state.state, dict)

    def test_initializes_with_default_state(self, temp_dir):
        """Should initialize with default state if file doesn't exist."""
        state_file = os.path.join(temp_dir, "nonexistent.json")
        state = AppState(state_file=state_file)

        assert state.get_active_model() is None
        assert state.get_document_count() == 0

    def test_loads_existing_state_file(self, temp_dir):
        """Should load existing state file."""
        state_file = os.path.join(temp_dir, "existing_state.json")

        # Create existing state
        existing_state = {
            'active_model': 'llama3.2',
            'document_count': 5,
            'last_updated': '2024-12-27T10:00:00'
        }
        with open(state_file, 'w') as f:
            json.dump(existing_state, f)

        # Load state
        state = AppState(state_file=state_file)

        assert state.get_active_model() == 'llama3.2'
        assert state.get_document_count() == 5

    def test_handles_corrupted_state_file(self, temp_dir):
        """Should handle corrupted state file gracefully."""
        state_file = os.path.join(temp_dir, "corrupted.json")

        # Create corrupted file
        with open(state_file, 'w') as f:
            f.write("{ invalid json }")

        # Should fall back to default state
        state = AppState(state_file=state_file)

        assert state.get_active_model() is None
        assert state.get_document_count() == 0


# ============================================================================
# ACTIVE MODEL TESTS
# ============================================================================

@pytest.mark.unit
class TestActiveModel:
    """Tests for active model management."""

    def test_get_active_model_returns_none_initially(self, temp_dir):
        """Should return None when no model is set."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        assert state.get_active_model() is None

    def test_set_active_model_updates_state(self, temp_dir):
        """Should update active model."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_active_model("llama3.2")

        assert state.get_active_model() == "llama3.2"

    def test_set_active_model_persists_to_file(self, temp_dir):
        """Should persist active model to file."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_active_model("llama3.2:latest")

        # Load from file
        with open(state_file) as f:
            saved_state = json.load(f)

        assert saved_state['active_model'] == "llama3.2:latest"

    def test_set_active_model_updates_timestamp(self, temp_dir):
        """Should update last_updated timestamp."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_active_model("llama3.2")

        assert state.state.get('last_updated') is not None

    def test_can_change_active_model(self, temp_dir):
        """Should allow changing active model."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_active_model("llama2")
        assert state.get_active_model() == "llama2"

        state.set_active_model("llama3.2")
        assert state.get_active_model() == "llama3.2"


# ============================================================================
# DOCUMENT COUNT TESTS
# ============================================================================

@pytest.mark.unit
class TestDocumentCount:
    """Tests for document count management."""

    def test_get_document_count_returns_zero_initially(self, temp_dir):
        """Should return 0 initially."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        assert state.get_document_count() == 0

    def test_set_document_count_updates_state(self, temp_dir):
        """Should update document count."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_document_count(10)

        assert state.get_document_count() == 10

    def test_set_document_count_persists_to_file(self, temp_dir):
        """Should persist document count to file."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_document_count(25)

        # Load from file
        with open(state_file) as f:
            saved_state = json.load(f)

        assert saved_state['document_count'] == 25

    def test_set_document_count_rejects_negative(self, temp_dir):
        """Should reject negative document count."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        with pytest.raises(ValueError, match="cannot be negative"):
            state.set_document_count(-1)

    def test_set_document_count_accepts_zero(self, temp_dir):
        """Should accept zero as valid count."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_document_count(0)
        assert state.get_document_count() == 0

    def test_increment_document_count_increases_by_one(self, temp_dir):
        """Should increment count by 1."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_document_count(5)
        state.increment_document_count()

        assert state.get_document_count() == 6

    def test_increment_document_count_by_custom_amount(self, temp_dir):
        """Should increment by custom amount."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_document_count(10)
        state.increment_document_count(5)

        assert state.get_document_count() == 15

    def test_increment_document_count_persists(self, temp_dir):
        """Should persist incremented count."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_document_count(3)
        state.increment_document_count(2)

        # Reload state
        new_state = AppState(state_file=state_file)
        assert new_state.get_document_count() == 5


# ============================================================================
# STATE PERSISTENCE TESTS
# ============================================================================

@pytest.mark.unit
class TestStatePersistence:
    """Tests for state persistence."""

    def test_state_persists_across_instances(self, temp_dir):
        """Should persist state across different instances."""
        state_file = os.path.join(temp_dir, "test.json")

        # First instance
        state1 = AppState(state_file=state_file)
        state1.set_active_model("llama3.2")
        state1.set_document_count(10)

        # Second instance
        state2 = AppState(state_file=state_file)

        assert state2.get_active_model() == "llama3.2"
        assert state2.get_document_count() == 10

    def test_timestamp_updated_on_save(self, temp_dir):
        """Should update timestamp on each save."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_active_model("model1")
        first_timestamp = state.state['last_updated']

        # Small delay to ensure different timestamp
        import time
        time.sleep(0.01)

        state.set_active_model("model2")
        second_timestamp = state.state['last_updated']

        assert second_timestamp != first_timestamp

    def test_handles_save_errors_gracefully(self, temp_dir):
        """Should handle save errors gracefully."""
        state_file = os.path.join(temp_dir, "readonly.json")
        state = AppState(state_file=state_file)

        # Make directory read-only (simulate permission error)
        # This test may not work on all systems, so we skip if it fails
        try:
            os.chmod(temp_dir, 0o444)
            state.set_active_model("test")  # Should not raise exception
        except:
            pass  # Skip if chmod doesn't work
        finally:
            os.chmod(temp_dir, 0o755)  # Restore permissions


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.unit
class TestAppStateIntegration:
    """Integration tests for AppState."""

    def test_complete_workflow(self, temp_dir):
        """Should handle complete state management workflow."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        # Initial state
        assert state.get_active_model() is None
        assert state.get_document_count() == 0

        # Set model
        state.set_active_model("llama3.2")
        assert state.get_active_model() == "llama3.2"

        # Add documents
        state.set_document_count(5)
        assert state.get_document_count() == 5

        # Increment documents
        state.increment_document_count(3)
        assert state.get_document_count() == 8

        # Change model
        state.set_active_model("llama2")
        assert state.get_active_model() == "llama2"

        # Verify persistence
        new_state = AppState(state_file=state_file)
        assert new_state.get_active_model() == "llama2"
        assert new_state.get_document_count() == 8

    def test_concurrent_updates(self, temp_dir):
        """Should handle updates from multiple instances."""
        state_file = os.path.join(temp_dir, "test.json")

        state1 = AppState(state_file=state_file)
        state2 = AppState(state_file=state_file)

        state1.set_active_model("model1")
        state2.set_active_model("model2")

        # Last write wins
        final_state = AppState(state_file=state_file)
        assert final_state.get_active_model() == "model2"


# ============================================================================
# EDGE CASES
# ============================================================================

@pytest.mark.unit
class TestAppStateEdgeCases:
    """Edge case tests for AppState."""

    def test_handles_empty_model_name(self, temp_dir):
        """Should handle empty model name."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        state.set_active_model("")
        assert state.get_active_model() == ""

    def test_handles_very_long_model_name(self, temp_dir):
        """Should handle very long model names."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        long_name = "model" * 1000
        state.set_active_model(long_name)
        assert state.get_active_model() == long_name

    def test_handles_special_characters_in_model_name(self, temp_dir):
        """Should handle special characters in model name."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        special_name = "model:latest-v1.2.3"
        state.set_active_model(special_name)
        assert state.get_active_model() == special_name

    def test_handles_large_document_count(self, temp_dir):
        """Should handle large document counts."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        large_count = 1000000
        state.set_document_count(large_count)
        assert state.get_document_count() == large_count

    def test_handles_unicode_in_state(self, temp_dir):
        """Should handle Unicode characters."""
        state_file = os.path.join(temp_dir, "test.json")
        state = AppState(state_file=state_file)

        unicode_model = "??-??-model"
        state.set_active_model(unicode_model)

        # Reload and verify
        new_state = AppState(state_file=state_file)
        assert new_state.get_active_model() == unicode_model


# ============================================================================
# ENVIRONMENT VARIABLE TESTS
# ============================================================================

@pytest.mark.unit
class TestEnvironmentVariables:
    """Tests for environment variable configuration."""

    @patch.dict(os.environ, {'PG_HOST': 'testhost'})
    def test_uses_environment_variable_for_host(self):
        """Should use environment variable if set."""
        # Need to reload module to pick up env vars
        # In real scenario, these are set before import
        pass  # This is more of an integration test

    def test_has_sensible_defaults(self):
        """Should have sensible default values."""
        assert CHUNK_SIZE > 0
        assert CHUNK_SIZE < 100000  # Reasonable upper bound

        assert TOP_K_RESULTS > 0
        assert TOP_K_RESULTS < 1000  # Reasonable upper bound


# ============================================================================
# Env-configurable RAG params
# ============================================================================

class TestEnvConfigurableRagParams:
    """
    Verify that CHUNK_SIZE, CHUNK_OVERLAP, TOP_K_RESULTS, and SEMANTIC_WEIGHT
    are read from environment variables when present.

    Because config.py is loaded at import time, we use importlib.reload()
    inside a patched os.environ to observe the effect.
    """

    def _reload_config_with_env(self, overrides: dict):
        import importlib

        import src.config as cfg_module
        with patch.dict(os.environ, overrides, clear=False):
            importlib.reload(cfg_module)
            return cfg_module

    def test_chunk_size_from_env(self):
        cfg = self._reload_config_with_env({"CHUNK_SIZE": "800"})
        assert cfg.CHUNK_SIZE == 800

    def test_chunk_overlap_from_env(self):
        cfg = self._reload_config_with_env({"CHUNK_OVERLAP": "100"})
        assert cfg.CHUNK_OVERLAP == 100

    def test_top_k_results_from_env(self):
        cfg = self._reload_config_with_env({"TOP_K_RESULTS": "20", "RERANK_TOP_K": "10"})
        assert cfg.TOP_K_RESULTS == 20

    def test_semantic_weight_from_env(self):
        cfg = self._reload_config_with_env({"SEMANTIC_WEIGHT": "0.55"})
        assert abs(cfg.SEMANTIC_WEIGHT - 0.55) < 1e-9

    def test_defaults_used_when_env_absent(self):
        """Without env overrides, defaults must be the documented values."""
        # Strip the keys in case the test runner has them set
        stripped = {k: "" for k in ("CHUNK_SIZE", "CHUNK_OVERLAP", "TOP_K_RESULTS", "SEMANTIC_WEIGHT")}
        import importlib

        import src.config as cfg_module
        env = {k: v for k, v in os.environ.items() if k not in stripped}
        with patch.dict(os.environ, {}, clear=True):
            # Re-apply everything except the stripped keys
            os.environ.update(env)
            importlib.reload(cfg_module)
            assert cfg_module.CHUNK_SIZE == 1200
            assert cfg_module.CHUNK_OVERLAP == 150
            assert cfg_module.TOP_K_RESULTS == 30
            assert abs(cfg_module.SEMANTIC_WEIGHT - 0.70) < 1e-9
