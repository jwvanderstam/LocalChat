"""
LLM Client Abstraction
======================

Provides a ModelClient Protocol and the cloud fallback's client (Feature 1.3): a
direct client for an OpenAI-compatible chat-completions endpoint. ADR-4 chose it over
litellm, whose breadth this deployment does not use and whose dependencies put the AWS
SDK in the image.
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator, Iterator
from typing import Any, Protocol, runtime_checkable

import httpx

from . import config
from .monitoring import record_llm_usage
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


# ── OpenAI-compatible implementation ──────────────────────────────────────────

class OpenAICompatibleClient:
    """ModelClient over ``POST {base_url}/chat/completions``, the OpenAI wire format.

    ``base_url`` is the API root including its version, e.g. ``https://api.openai.com/v1``.
    A cost is recorded only when both prices are set, in USD per million tokens.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        *,
        timeout: float,
        price_input_per_mtok: float | None = None,
        price_output_per_mtok: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport)
        self._prices = (
            (price_input_per_mtok, price_output_per_mtok)
            if price_input_per_mtok is not None and price_output_per_mtok is not None
            else None
        )
        logger.info(f"[CloudFallback] Client ready — endpoint={base_url}, model={model}")

    def _iter_stream_chunks(self, lines: Iterator[str], model: str) -> Generator[str, None, None]:
        """Yield non-empty content strings from a server-sent chat-completions stream."""
        usage = None
        for line in lines:
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            # With include_usage the final chunk carries usage and no choices.
            usage = chunk.get("usage") or usage
            choices = chunk.get("choices") or []
            content = (choices[0].get("delta") or {}).get("content") if choices else None
            if content:
                yield content
        self._record_usage(model, usage)

    def _record_usage(self, model: str, usage: Any) -> None:
        """Count a cloud call's tokens and, when both prices are configured, its cost."""
        usage = usage if isinstance(usage, dict) else {}
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if not isinstance(prompt, int) or not isinstance(completion, int):
            logger.warning("[CloudFallback] No token usage in the response from %s", model)
            return
        cost: float | None = None
        if self._prices is not None:
            cost = (prompt * self._prices[0] + completion * self._prices[1]) / 1_000_000
        record_llm_usage(model, "cloud", prompt, completion, cost)

    def _complete(self, body: dict) -> dict:
        response = self._http.post("chat/completions", json=body)
        response.raise_for_status()
        data: dict = response.json()
        return data

    def generate_chat_response(
        self,
        model: str,
        messages: list[dict],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        """Yield text chunks from a streaming (or non-streaming) completion."""
        body: dict = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        try:
            if stream:
                # Without this a stream reports no usage at all, and per-token billing
                # would go uncounted on exactly the path that has a bill.
                body["stream_options"] = {"include_usage": True}
                with self._http.stream("POST", "chat/completions", json=body) as response:
                    response.raise_for_status()
                    yield from self._iter_stream_chunks(response.iter_lines(), model)
            else:
                data = self._complete(body)
                self._record_usage(model, data.get("usage"))
                choices = data.get("choices") or []
                yield (choices[0]["message"].get("content") or "") if choices else ""
        except Exception:
            logger.exception("[CloudFallback] Cloud endpoint error")
            raise

    def generate_chat_completion(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        """Non-streaming completion (for tool-call use cases)."""
        body: dict = {"model": model, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        data = self._complete(body)
        self._record_usage(model, data.get("usage"))
        return data
