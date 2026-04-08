"""
LLM Client Abstraction
======================

Provides a ModelClient Protocol and a LiteLLM-backed implementation for
cloud model fallback (Feature 1.3).

litellm is imported lazily inside LiteLLMClient.__init__ so the application
starts normally when the package is not installed and CLOUD_FALLBACK_ENABLED
is false (the default).
"""

from __future__ import annotations

import re
from typing import Generator, Protocol, runtime_checkable

from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)

# ── Refusal detection ─────────────────────────────────────────────────────────
# Compiled once at import time.  Only applied to responses shorter than 500
# characters to avoid false positives on long answers that happen to contain
# a matched phrase.
_REFUSAL_MAX_LEN = 500
_REFUSAL_RE = re.compile(
    "|".join(config.CLOUD_REFUSAL_PATTERNS),
    re.IGNORECASE,
)


def is_refusal(text: str) -> bool:
    """Return True when *text* looks like a local-model refusal."""
    if len(text) >= _REFUSAL_MAX_LEN:
        return False
    return bool(_REFUSAL_RE.search(text))


# ── Protocol ──────────────────────────────────────────────────────────────────

@runtime_checkable
class ModelClient(Protocol):
    def generate_chat_response(
        self,
        model: str,
        messages: list[dict],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]: ...

    def generate_chat_completion(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict: ...


# ── LiteLLM implementation ────────────────────────────────────────────────────

class LiteLLMClient:
    """
    ModelClient implementation backed by litellm.

    Supports any provider litellm supports (OpenAI, Anthropic, Cohere, …).
    Pass ``provider`` as the litellm provider prefix (e.g. ``"openai"``),
    ``api_key`` if not already in the environment, and ``model`` as the
    litellm model string (e.g. ``"gpt-4o"`` or ``"anthropic/claude-3-5-haiku"``).
    """

    def __init__(self, provider: str, api_key: str | None, model: str) -> None:
        try:
            import litellm as _litellm
            self._litellm = _litellm
        except ImportError as exc:
            raise ImportError(
                "litellm is required for cloud fallback — "
                "run: pip install 'litellm>=1.67.0'"
            ) from exc

        self._provider = provider
        self._model = model

        if api_key:
            import os
            # litellm reads provider API keys from env vars (e.g. OPENAI_API_KEY).
            key_var = f"{provider.upper()}_API_KEY"
            os.environ.setdefault(key_var, api_key)

        logger.info(f"[CloudFallback] LiteLLMClient ready — provider={provider}, model={model}")

    def generate_chat_response(
        self,
        model: str,
        messages: list[dict],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        """Yield text chunks from a litellm streaming (or non-streaming) completion."""
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            response = self._litellm.completion(**kwargs)
            if stream:
                for chunk in response:
                    content = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                    if content:
                        yield content
            else:
                yield (response.choices[0].message.content or "") if response.choices else ""
        except Exception as e:
            logger.error(f"[CloudFallback] litellm error: {e}", exc_info=True)
            raise

    def generate_chat_completion(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        """Non-streaming completion (for tool-call use cases)."""
        kwargs: dict = {"model": model, "messages": messages, "stream": False}
        if tools:
            kwargs["tools"] = tools
        response = self._litellm.completion(**kwargs)
        return response.model_dump()
