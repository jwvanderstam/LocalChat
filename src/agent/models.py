"""
Model Registry
==============

Maps logical model classes (FAST, BASE, LARGE, CODE, VISION) to concrete
Ollama model IDs and request parameters.

Model IDs are read from environment variables at import time.  An empty
model_id means "use the user-selected active model" — the registry never
overrides unless a specific model has been configured.

Environment variables (all optional):
    MODEL_FAST    — small/fast model for simple factual lookups
    MODEL_BASE    — default model (fallback for all classes)
    MODEL_LARGE   — large model for complex multi-doc synthesis
    MODEL_CODE    — code-specialist model
    MODEL_VISION  — vision/multimodal model for image-heavy docs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .. import config


class ModelClass(StrEnum):
    """Logical routing categories for query classification."""

    FAST = "fast"       # Short factual lookups — speed over depth
    BASE = "base"       # Default for unclassified queries
    LARGE = "large"     # Multi-doc synthesis, long reasoning chains
    CODE = "code"       # Code generation, review, explanation
    VISION = "vision"   # Image-heavy documents, PDFs with figures


@dataclass(frozen=True)
class ModelConfig:
    """
    Configuration for one model class.

    A model_id of "" means "defer to the currently active model".
    timeout_s is the per-request timeout in seconds passed to the Ollama
    client; set higher for large models with long generation times.
    """

    model_id: str = ""
    max_tokens: int = 4096
    timeout_s: int = 120
    description: str = ""


class ModelRegistry:
    """
    Registry of model configurations keyed by ModelClass.

    Populated from environment variables at instantiation.  An unconfigured
    class (empty model_id) transparently falls back to the active model so
    the system always has a working model regardless of configuration.
    """

    _DEFAULTS: dict[ModelClass, ModelConfig] = {
        ModelClass.FAST:   ModelConfig(description="Small fast model — simple factual lookups"),
        ModelClass.BASE:   ModelConfig(description="Default general-purpose model"),
        ModelClass.LARGE:  ModelConfig(description="Large model — complex synthesis"),
        ModelClass.CODE:   ModelConfig(description="Code-specialist model"),
        ModelClass.VISION: ModelConfig(description="Vision/multimodal model"),
    }

    def __init__(self) -> None:
        self._registry: dict[ModelClass, ModelConfig] = {}
        config_map: dict[ModelClass, str] = {
            ModelClass.FAST:   config.MODEL_FAST,
            ModelClass.BASE:   config.MODEL_BASE,
            ModelClass.LARGE:  config.MODEL_LARGE,
            ModelClass.CODE:   config.MODEL_CODE,
            ModelClass.VISION: config.MODEL_VISION,
        }
        for cls, model_id in config_map.items():
            default = self._DEFAULTS[cls]
            self._registry[cls] = ModelConfig(
                model_id=model_id,
                max_tokens=default.max_tokens,
                timeout_s=default.timeout_s,
                description=default.description,
            )

    def get(self, cls: ModelClass, fallback: str = "") -> ModelConfig:
        """
        Return the ModelConfig for *cls*.

        If the class has no configured model_id, returns a config with
        model_id set to *fallback* (typically the active model).
        """
        cfg = self._registry.get(cls, self._DEFAULTS[cls])
        if cfg.model_id:
            return cfg
        return ModelConfig(
            model_id=fallback,
            max_tokens=cfg.max_tokens,
            timeout_s=cfg.timeout_s,
            description=cfg.description,
        )

    def resolve(self, cls: ModelClass, fallback: str) -> str:
        """Return the model_id for *cls*, or *fallback* if not configured."""
        return self.get(cls, fallback).model_id

    def summary(self) -> dict[str, dict]:
        """Return a JSON-serialisable summary of configured model IDs."""
        return {
            cls.value: {
                "model_id": cfg.model_id or "(active model)",
                "configured": bool(cfg.model_id),
                "description": cfg.description,
            }
            for cls, cfg in self._registry.items()
        }


# Module-level singleton — re-reads env on every import (test-friendly).
model_registry = ModelRegistry()
