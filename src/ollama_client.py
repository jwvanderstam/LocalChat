"""
Ollama Client Module
===================

Client for interacting with the Ollama API for LLM inference, embeddings,
model management, and GPU hardware detection.

Classes:
    OllamaClient: Main client for Ollama API operations

GPU Support:
    GPU layer offload is controlled by ``OLLAMA_NUM_GPU`` (default ``-1``,
    meaning all transformer layers are placed on GPU).  The value is forwarded
    in ``options.num_gpu`` on every ``/api/chat`` and ``/api/embed`` request so
    Ollama distributes work across all detected GPUs automatically.

GPU Detection:
    ``get_gpu_info()`` delegates to :class:`~src.gpu_monitor.GpuMonitor`,
    which auto-detects NVIDIA/AMD GPUs and TTL-caches results (30 s).

TTL Caching:
    ``get_running_models()`` caches ``/api/ps`` responses for 5 s.  Stale
    cached data is returned on network errors rather than an empty list.

Embedding Endpoint:
    Uses the newer ``/api/embed`` endpoint (Ollama ≥ 0.1.32) with automatic
    fallback to the legacy ``/api/embeddings`` endpoint on HTTP 404.  The
    resolved embedding model name is cached after the first ``list_models()``
    call to avoid repeated API round-trips.

Example:
    >>> from ollama_client import ollama_client
    >>> success, message = ollama_client.check_connection()
    >>> if success:
    ...     embedding = ollama_client.generate_embedding("nomic-embed-text", "Hello")
    ...     gpus = ollama_client.get_gpu_info()

"""

import json
import threading
import time
from typing import Any, Dict, Generator, List, NoReturn, Optional, Tuple

import requests

from . import config
from .gpu_monitor import GpuMonitor
from .utils.logging_config import get_logger

# Setup logger
logger = get_logger(__name__)


class OllamaClient:
    """
    Client for interacting with Ollama API.

    Handles communication with the Ollama server for chat completions,
    embedding generation, model management, and GPU hardware detection.
    All HTTP requests reuse a single ``requests.Session`` for connection
    pooling.

    Attributes:
        base_url (str): Base URL for Ollama API.
        is_available (bool): Whether Ollama server is accessible.
        available_models (List[str]): List of available model names.

    TTL cache attributes (internal):
        _running_models_cache: Cached ``/api/ps`` result; refreshed every
            ``_RUNNING_MODELS_TTL`` seconds (default 5 s).
        _gpu_info_cache: Cached GPU hardware stats; refreshed every
            ``_GPU_INFO_TTL`` seconds (default 30 s).

    Example:
        >>> client = OllamaClient("http://localhost:11434")
        >>> success, msg = client.check_connection()
        >>> if success:
        ...     gpus = client.get_gpu_info()
        ...     models = client.get_running_models()
    """

    # How long (seconds) to serve cached results before re-querying.
    _RUNNING_MODELS_TTL: float = 5.0   # loaded models can change at any time
    _LIST_MODELS_TTL: float = 60.0     # installed models list; rarely changes

    def __init__(self, base_url: str | None = None) -> None:
        """
        Initialize Ollama client.

        Args:
            base_url: Base URL for Ollama API (default from config)
        """
        self.base_url: str = base_url or config.OLLAMA_BASE_URL
        self.is_available: bool = False
        self.available_models: list[str] = []
        self._session = requests.Session()  # reuse TCP connections across calls
        self._embedding_model_cache: str | None = None  # resolved once, reused
        # TTL caches — avoids /api/ps on every admin page load
        self._running_models_cache: list[dict[str, Any]] | None = None
        self._running_models_cache_time: float = 0.0
        self._list_models_cache: list[dict[str, Any]] | None = None
        self._list_models_cache_time: float = 0.0
        self._gpu_monitor = GpuMonitor()
        logger.info(f"OllamaClient initialized with base_url: {self.base_url}")

    def check_connection(self) -> tuple[bool, str]:
        """
        Check if Ollama is running and accessible.

        Tests connectivity to the Ollama server and retrieves available models.

        Returns:
            Tuple of (success: bool, message: str)
            - success: True if connection successful
            - message: Status message or error description

        Example:
            >>> success, msg = ollama_client.check_connection()
            >>> print(msg)
            'Ollama is running with 4 models'
        """
        try:
            logger.debug(f"Checking connection to {self.base_url}")
            response = self._session.get(f"{self.base_url}/api/tags", timeout=5)

            if response.status_code == 200:
                self.is_available = True
                data = response.json()
                self.available_models = [model['name'] for model in data.get('models', [])]
                message = f"Ollama is running with {len(self.available_models)} models"
                logger.info(message)
                self._start_background_refresh()
                return True, message
            else:
                self.is_available = False
                message = f"Ollama returned status code {response.status_code}"
                logger.warning(message)
                return False, message

        except requests.exceptions.RequestException as e:
            self.is_available = False
            message = f"Cannot connect to Ollama: {str(e)}"
            logger.error(message, exc_info=True)
            return False, message

    def list_models(self) -> tuple[bool, list[dict[str, Any]]]:
        """
        List all available models.

        Queries Ollama for installed models and their metadata.

        Returns:
            Tuple of (success: bool, models: List[Dict])
            - success: True if request successful
            - models: List of model dictionaries with name, size, etc.

        Example:
            >>> success, models = ollama_client.list_models()
            >>> for model in models:
            ...     print(model['name'], model['size'])
        """
        now = time.monotonic()
        if (
            self._list_models_cache is not None
            and (now - self._list_models_cache_time) < self._LIST_MODELS_TTL
        ):
            return True, self._list_models_cache
        try:
            logger.debug("Fetching model list")
            response = self._session.get(f"{self.base_url}/api/tags", timeout=5)

            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get('models', []):
                    models.append({
                        'name': model['name'],
                        'size': model.get('size', 0),
                        'modified_at': model.get('modified_at', ''),
                        'digest': model.get('digest', '')
                    })
                logger.debug(f"Found {len(models)} models")
                self._list_models_cache = models
                self._list_models_cache_time = now
                return True, models
            else:
                logger.warning(f"Failed to list models: {response.status_code}")
                return False, self._list_models_cache if self._list_models_cache is not None else []

        except Exception as e:
            logger.error(f"Error listing models: {e}", exc_info=True)
            return False, self._list_models_cache if self._list_models_cache is not None else []

    def get_first_available_model(self, preferred: str | None = None) -> str | None:
        """
        Get the best available chat model name.

        If *preferred* is given and an installed model whose name starts with
        that string exists, it is returned first.  Otherwise falls back to the
        first model in the list (Ollama orders by modification time).

        Embedding-only models (nomic-embed-text, mxbai-embed, etc.) are skipped.

        Args:
            preferred: Preferred model name prefix (e.g. "llama3.1").

        Returns:
            Name of selected model, or None if no models available.
        """
        success, models = self.list_models()
        if not success or not models:
            logger.warning("No models available")
            return None

        embed_families = ('nomic-embed', 'mxbai-embed', 'all-minilm', 'embed')
        chat_models = [
            m for m in models
            if not any(m['name'].lower().startswith(f) for f in embed_families)
        ]
        if not chat_models:
            chat_models = models  # fall back if everything looks like an embed model

        if preferred:
            for m in chat_models:
                if m['name'].startswith(preferred):
                    logger.debug(f"Preferred model matched: {m['name']}")
                    return m['name']
            logger.debug(f"Preferred model {preferred!r} not found; using first available")

        model_name = chat_models[0]['name']
        logger.debug(f"First available model: {model_name}")
        return model_name

    def pull_model(self, model_name: str) -> Generator[dict[str, Any], None, None]:
        """
        Pull a model from Ollama registry.

        Downloads a model from the Ollama registry with streaming progress updates.

        Args:
            model_name: Name of model to pull (e.g., "llama3.2")

        Yields:
            Progress updates as dictionaries with status/completion info

        Example:
            >>> for progress in ollama_client.pull_model("llama3.2"):
            ...     print(progress.get('status'))
        """
        try:
            logger.info(f"Pulling model: {model_name}")
            response = self._session.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                stream=True,
                timeout=300
            )

            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        yield json.loads(line)
                logger.info(f"Successfully pulled model: {model_name}")
                self._list_models_cache = None  # invalidate after pull
            else:
                error_msg = f"Failed to pull model: {response.status_code}"
                logger.error(error_msg)
                yield {"error": error_msg}

        except Exception as e:
            error_msg = f"Error pulling model: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield {"error": error_msg}

    def delete_model(self, model_name: str) -> tuple[bool, str]:
        """
        Delete a model from Ollama.

        Args:
            model_name: Name of model to delete

        Returns:
            Tuple of (success: bool, message: str)

        Example:
            >>> success, msg = ollama_client.delete_model("old-model")
            >>> print(msg)
        """
        try:
            logger.info(f"Deleting model: {model_name}")
            response = self._session.delete(
                f"{self.base_url}/api/delete",
                json={"name": model_name},
                timeout=30
            )

            success = response.status_code == 200
            message = "Model deleted successfully" if success else "Failed to delete model"

            if success:
                logger.info(f"Deleted model: {model_name}")
                self._list_models_cache = None  # invalidate after delete
            else:
                logger.warning(f"Failed to delete model: {model_name}")

            return success, message

        except Exception as e:
            logger.error(f"Error deleting model: {e}", exc_info=True)
            return False, str(e)

    def get_vision_model(self) -> str | None:
        """
        Get a vision-capable model for image processing.

        Searches installed models for known multimodal/vision model families.
        Falls back to the first available model if none are identified.

        Returns:
            Name of a vision model, or None if no models are available

        Example:
            >>> model = ollama_client.get_vision_model()
            >>> if model:
            ...     print(f"Vision model: {model}")
        """
        vision_families = ['llava', 'moondream', 'bakllava', 'minicpm-v', 'cogvlm']
        success, models = self.list_models()
        if not success or not models:
            logger.warning("No models available for vision")
            return None

        model_names = [m['name'] for m in models]

        # Prefer an explicitly vision-capable model
        for family in vision_families:
            for name in model_names:
                if family in name.lower():
                    logger.info(f"Using vision model: {name}")
                    return name

        # Fall back to the active / first model (may still support vision)
        fallback = model_names[0]
        logger.warning(f"No dedicated vision model found, falling back to: {fallback}")
        return fallback

    def describe_image(
        self,
        model: str,
        image_b64: str,
        prompt: str | None = None
    ) -> tuple[bool, str]:
        """
        Generate a text description of an image using a vision model.

        Args:
            model: Vision-capable model name
            image_b64: Base64-encoded image data
            prompt: Custom description prompt (default: from config)

        Returns:
            Tuple of (success: bool, description_or_error: str)

        Example:
            >>> import base64
            >>> with open("image.png", "rb") as f:
            ...     b64 = base64.b64encode(f.read()).decode()
            >>> success, desc = ollama_client.describe_image("llava", b64)
        """
        if prompt is None:
            prompt = config.VISION_DESCRIBE_PROMPT

        try:
            logger.info(f"Describing image with model: {model}")
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": prompt, "images": [image_b64]}
            ]
            description = ""
            for chunk in self.generate_chat_response(model, messages, stream=False):
                description += chunk

            logger.info(f"Image described: {len(description)} characters")
            return True, description.strip()

        except Exception as e:
            logger.error(f"Error describing image: {e}", exc_info=True)
            return False, str(e)

    def _iter_stream_chunks(self, response) -> Generator[str, None, None]:
        """Yield content chunks from a streaming Ollama /api/chat response."""
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                if 'message' in data:
                    content = data['message'].get('content', '')
                    if content:
                        yield content
                if data.get('done', False):
                    break

    def _raise_for_ollama_error(self, response, model: str) -> NoReturn:
        """
        Parse a non-200 Ollama response and raise an appropriate exception.

        A 404 is interpreted as "model not found" and raises
        ``InvalidModelError`` with an actionable user message.  All other
        non-200 codes raise a generic ``RuntimeError``.

        Args:
            response: The ``requests.Response`` object (status_code != 200).
            model: Model name that was requested (used in the error message).

        Raises:
            InvalidModelError: Model not found in Ollama (HTTP 404).
            RuntimeError: Any other non-200 Ollama API error.
        """
        from .exceptions import InvalidModelError

        if response.status_code == 404:
            try:
                ollama_detail = response.json().get("error", "")
            except Exception:
                ollama_detail = response.text[:200]

            raise InvalidModelError(
                f"Model '{model}' is not available. "
                "Go to Model Management to pull or select an installed model.",
                details={"model": model, "ollama_error": ollama_detail},
            )

        body = response.text[:200] if response.text else ""
        logger.error(f"Ollama API error {response.status_code}: {body}")
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}")

    def _build_chat_options(
        self, temperature: float = 0.7, max_tokens: int | None = None
    ) -> dict[str, Any]:
        """Build the options dict for /api/chat requests."""
        options: dict[str, Any] = {
            "num_gpu": config.OLLAMA_NUM_GPU,
            "num_ctx": config.MAX_CONTEXT_LENGTH,
            "temperature": temperature,
        }
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        return options

    def generate_chat_response(
        self,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        """
        Generate a chat response from the model.

        Args:
            model: Name of model to use.
            messages: List of message dicts with ``role`` and ``content``.
            stream: Whether to stream response (default: ``True``).
            max_tokens: Optional token limit passed to Ollama.

        Yields:
            Response text chunks.

        Raises:
            InvalidModelError: If the requested model is not installed.
            RuntimeError: For any other non-200 Ollama API response.

        Example:
            >>> messages = [{"role": "user", "content": "Hello"}]
            >>> for chunk in ollama_client.generate_chat_response("llama3.2", messages):
            ...     print(chunk, end='')
        """
        logger.debug(f"Generating chat response with model: {model}")
        options = self._build_chat_options(temperature, max_tokens)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "keep_alive": -1,
            "options": options,
        }

        try:
            response = self._session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=stream,
                timeout=120,
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"Ollama did not respond within 120 s (model: {model}). "
                "The model may still be loading — try again shortly."
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc

        if response.status_code == 200:
            if stream:
                yield from self._iter_stream_chunks(response)
            else:
                data = response.json()
                yield data.get('message', {}).get('content', '')
            logger.debug("Chat response generated successfully")
        else:
            self._raise_for_ollama_error(response, model)

    def _build_tool_payload(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build the request payload for non-streaming /api/chat completions."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_gpu": config.OLLAMA_NUM_GPU,
                "num_ctx": config.MAX_CONTEXT_LENGTH,
            },
        }
        if tools:
            payload["tools"] = tools
        return payload

    def generate_chat_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Non-streaming chat completion that returns the full response.

        Used by the tool-calling executor to inspect ``tool_calls`` before
        deciding whether to stream the final answer.

        Args:
            model: Name of model to use.
            messages: Conversation messages.
            tools: Optional list of tool schemas in Ollama format.

        Returns:
            Full Ollama response dictionary (contains ``message`` with
            ``content`` and/or ``tool_calls``).

        Raises:
            InvalidModelError: If the requested model is not installed.
            RuntimeError: For any other non-200 Ollama API response.

        Example:
            >>> resp = ollama_client.generate_chat_completion("llama3.2", messages)
            >>> if resp["message"].get("tool_calls"):
            ...     print("Model wants to call tools")
        """
        payload = self._build_tool_payload(model, messages, tools)

        logger.debug(f"Chat completion (non-stream) with model: {model}")
        try:
            response = self._session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"Ollama did not respond within 120 s (model: {model}). "
                "The model may still be loading — try again shortly."
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc

        if response.status_code == 200:
            data = response.json()
            tool_calls = data.get("message", {}).get("tool_calls")
            if tool_calls:
                logger.info(f"Model returned {len(tool_calls)} tool call(s)")
            return data

        self._raise_for_ollama_error(response, model)

    def _embed_new_api(self, model: str, text: str) -> tuple[bool, list[float], bool]:
        """
        Try the newer ``/api/embed`` endpoint (Ollama ≥ 0.1.32).

        Returns:
            (success, embedding, should_fallback) — should_fallback is True only
            when the server returned 404 (endpoint not available on this build).
        """
        response = self._session.post(
            f"{self.base_url}/api/embed",
            json={
                "model": model,
                "input": text,
                "keep_alive": -1,
                "options": {"num_gpu": config.OLLAMA_NUM_GPU},
            },
            timeout=config.OLLAMA_EMBED_TIMEOUT,
        )
        if response.status_code == 200:
            embeddings = response.json().get("embeddings", [])
            if embeddings:
                logger.debug(f"Generated embedding with {len(embeddings[0])} dimensions")
                return True, embeddings[0], False
        if response.status_code == 404:
            return False, [], True  # caller should try legacy endpoint
        logger.warning(f"Failed to generate embedding: {response.status_code}")
        return False, [], False

    def _embed_legacy_api(self, model: str, text: str) -> tuple[bool, list[float]]:
        """
        Fallback to the legacy ``/api/embeddings`` endpoint (older Ollama builds).

        Returns:
            (success, embedding)
        """
        logger.debug("Falling back to legacy /api/embeddings endpoint")
        response = self._session.post(
            f"{self.base_url}/api/embeddings",
            json={
                "model": model,
                "prompt": text,
                "keep_alive": -1,
                "options": {"num_gpu": config.OLLAMA_NUM_GPU},
            },
            timeout=config.OLLAMA_EMBED_TIMEOUT,
        )
        if response.status_code == 200:
            embedding = response.json().get("embedding", [])
            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
            return True, embedding
        logger.warning(f"Failed to generate embedding (legacy): {response.status_code}")
        return False, []

    def generate_embedding(
        self,
        model: str,
        text: str
    ) -> tuple[bool, list[float]]:
        """
        Generate embedding vector for text.

        Tries the newer ``/api/embed`` endpoint first (more efficient, supports
        batching and truncation).  Falls back to the legacy ``/api/embeddings``
        endpoint if the server returns 404 (older Ollama build).

        Args:
            model: Name of embedding model (e.g., "nomic-embed-text")
            text: Input text to embed

        Returns:
            Tuple of (success: bool, embedding: List[float])
        """
        try:
            logger.debug(f"Generating embedding with model: {model}")
            success, embedding, should_fallback = self._embed_new_api(model, text)
            if success:
                return True, embedding
            if should_fallback:
                return self._embed_legacy_api(model, text)
            return False, []
        except Exception as e:
            logger.error(f"Error generating embedding: {e}", exc_info=True)
            return False, []

    def generate_embeddings_batch(
        self,
        model: str,
        texts: list[str],
    ) -> list[list[float] | None]:
        """
        Generate embeddings for multiple texts in a single API call.

        Sends all texts as a batch via the ``/api/embed`` endpoint so Ollama
        processes them in one GPU forward pass — far faster than one
        ``generate_embedding`` call per text.

        Falls back to individual ``generate_embedding`` calls if the batch
        request fails.

        Args:
            model: Embedding model name (e.g., "nomic-embed-text")
            texts: List of input texts to embed

        Returns:
            List of embeddings aligned with ``texts``; ``None`` for any that
            failed.
        """
        if not texts:
            return []
        try:
            logger.debug(f"Batch-embedding {len(texts)} texts with model: {model}")
            response = self._session.post(
                f"{self.base_url}/api/embed",
                json={
                    "model": model,
                    "input": texts,
                    "keep_alive": -1,
                    "options": {"num_gpu": config.OLLAMA_NUM_GPU},
                },
                timeout=config.OLLAMA_EMBED_TIMEOUT,
            )
            if response.status_code == 200:
                embeddings = response.json().get("embeddings", [])
                if len(embeddings) == len(texts):
                    logger.debug(f"Batch embed returned {len(embeddings)} embeddings")
                    return embeddings
                logger.warning(
                    f"Batch embed returned {len(embeddings)} results for {len(texts)} texts; padding"
                )
                result: list[list[float] | None] = list(embeddings)
                result += [None] * (len(texts) - len(embeddings))
                return result
            logger.warning(
                f"Batch embed failed: HTTP {response.status_code}; falling back to per-text"
            )
        except Exception as exc:
            logger.warning(f"Batch embedding error: {exc}; falling back to per-text")

        # Per-text fallback
        fallback_results = []
        for text in texts:
            success, embedding = self.generate_embedding(model, text)
            fallback_results.append(embedding if success else None)
        return fallback_results

    def get_running_models(self) -> list[dict[str, Any]]:
        """
        Return models currently loaded in Ollama (from ``/api/ps``).

        Results are cached for ``_RUNNING_MODELS_TTL`` seconds so that
        repeated admin dashboard refreshes do not hammer the Ollama HTTP API.

        Each entry contains ``name``, ``size`` (bytes), ``size_vram`` (bytes)
        and ``processor`` so callers can display GPU/CPU offload percentages.

        Returns:
            List of model info dicts, or empty list if unavailable.
        """
        now = time.monotonic()
        if (
            self._running_models_cache is not None
            and (now - self._running_models_cache_time) < self._RUNNING_MODELS_TTL
        ):
            return self._running_models_cache
        try:
            response = self._session.get(f"{self.base_url}/api/ps", timeout=5)
            if response.status_code == 200:
                result = response.json().get("models", [])
                self._running_models_cache = result
                self._running_models_cache_time = now
                return result
        except Exception as e:
            logger.debug("Could not fetch running models from /api/ps: %s", e)
        # Return stale data rather than an empty list when the query fails
        return self._running_models_cache if self._running_models_cache is not None else []

    def get_gpu_info(self) -> list[dict[str, Any]]:
        """
        Detect all available GPUs and return per-GPU hardware stats.

        Delegates to :class:`~src.gpu_monitor.GpuMonitor`, which TTL-caches
        results (30 s) and tries NVIDIA first, then AMD.

        Each entry contains:
            ``id``, ``name``, ``vendor``, ``vram_total_mb``, ``vram_used_mb``,
            ``vram_free_mb``, ``utilization_percent``, ``temperature_c``.

        Returns:
            List of GPU info dicts (one per physical GPU), or empty list.
        """
        return self._gpu_monitor.get_gpu_info()

    def _find_model_in_list(self, model_names: list, preferred: list) -> str | None:
        """Return first model from preferred list found (by substring) in model_names."""
        for embed_model in preferred:
            for model_name in model_names:
                if embed_model in model_name:
                    return model_name
        return model_names[0] if model_names else None

    def _log_embedding_model_selection(
        self, found: str | None, model_names: list[str], embedding_models: list[str]
    ) -> None:
        """Log which embedding model was selected and whether it is a fallback."""
        if not found:
            return
        is_fallback = found == model_names[0] and not any(e in found for e in embedding_models)
        if is_fallback:
            logger.warning(f"No dedicated embedding model found, using: {found}")
        else:
            logger.info(f"Using embedding model: {found}")

    def _resolve_model(
        self,
        preferred: str | None,
        fallback_families: list[str],
    ) -> tuple[str | None, list[str]]:
        """Find an installed model; returns (model_name, all_model_names)."""
        success, models = self.list_models()
        if not success or not models:
            return None, []
        model_names = [m['name'] for m in models]
        if preferred and preferred in model_names:
            return preferred, model_names
        return self._find_model_in_list(model_names, fallback_families), model_names

    def get_embedding_model(self, preferred_model: str | None = None) -> str | None:
        """
        Get the best available embedding model.

        Tries preferred model first, then falls back to common embedding models.

        Args:
            preferred_model: Preferred model name (optional)

        Returns:
            Name of best available embedding model, or None if none available

        Example:
            >>> model = ollama_client.get_embedding_model("nomic-embed-text")
            >>> print(f"Using embedding model: {model}")
        """
        if not preferred_model:
            preferred_model = config.OLLAMA_EMBEDDING_MODEL or None
        if not preferred_model and self._embedding_model_cache is not None:
            return self._embedding_model_cache

        logger.debug(f"Finding best embedding model (preferred: {preferred_model})")
        embedding_families = [
            'nomic-embed-text', 'mxbai-embed-large', 'all-minilm', 'llama2', 'mistral'
        ]
        found, model_names = self._resolve_model(preferred_model, embedding_families)
        if not found:
            logger.error("No embedding model available")
            return None

        self._log_embedding_model_selection(found, model_names, embedding_families)
        self._embedding_model_cache = found
        return found

    def _start_background_refresh(self) -> None:
        """Start a daemon thread that proactively refreshes slow TTL caches.

        Refreshes ``get_gpu_info()`` every ~25 s (TTL = 30 s) and
        ``get_running_models()`` every 4 s (TTL = 5 s) so the admin
        dashboard never stalls on a cold cache miss.

        Safe to call multiple times — only one thread is ever started.
        """
        if getattr(self, '_background_refresh_started', False):
            return
        self._background_refresh_started = True

        def _refresh_loop() -> None:
            gpu_tick = 0
            while True:
                time.sleep(4.0)
                try:
                    self.get_running_models()
                except Exception:
                    pass
                gpu_tick += 1
                if gpu_tick >= 6:  # ~24 s — refresh before 30 s TTL expires
                    gpu_tick = 0
                    try:
                        self.get_gpu_info()
                    except Exception:
                        pass

        t = threading.Thread(target=_refresh_loop, name="ollama-cache-refresh", daemon=True)
        t.start()
        logger.debug("Background cache refresh thread started")

    def test_model(self, model_name: str) -> tuple[bool, str]:
        """
        Test a model with a simple prompt.

        Args:
            model_name: Name of model to test

        Returns:
            Tuple of (success: bool, response: str)

        Example:
            >>> success, response = ollama_client.test_model("llama3.2")
            >>> if success:
            ...     print(f"Model works: {response}")
        """
        try:
            logger.info(f"Testing model: {model_name}")
            messages = [{"role": "user", "content": "Say 'Hello, I am working!' and nothing else."}]
            response_text = ""

            for chunk in self.generate_chat_response(model_name, messages, stream=True):
                response_text += chunk

            if response_text.startswith("Error:"):
                logger.warning(f"Model test returned error: {model_name}")
                return False, response_text
            logger.info(f"Model test successful: {model_name}")
            return True, response_text.strip()

        except Exception as e:
            logger.error(f"Model test failed: {e}", exc_info=True)
            return False, str(e)


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Global Ollama client instance
ollama_client = OllamaClient()

logger.info("Ollama client module loaded")
