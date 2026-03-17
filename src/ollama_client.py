"""
Ollama Client Module
===================

Client for interacting with the Ollama API for LLM inference and embeddings.
Provides functions for chat completion, embedding generation, and model management.

Classes:
    OllamaClient: Main client for Ollama API operations

Example:
    >>> from ollama_client import ollama_client
    >>> success, message = ollama_client.check_connection()
    >>> if success:
    ...     embedding = ollama_client.generate_embedding("nomic-embed-text", "Hello")

Author: LocalChat Team
Last Updated: 2025-01-27
"""

import requests
import json
from typing import Tuple, List, Dict, Any, Optional, Generator
from . import config
from .utils.logging_config import get_logger

# Setup logger
logger = get_logger(__name__)


class OllamaClient:
    """
    Client for interacting with Ollama API.
    
    Handles communication with the Ollama server for chat completions,
    embedding generation, and model management operations.
    
    Attributes:
        base_url (str): Base URL for Ollama API
        is_available (bool): Whether Ollama server is accessible
        available_models (List[str]): List of available model names
    
    Example:
        >>> client = OllamaClient("http://localhost:11434")
        >>> success, msg = client.check_connection()
        >>> if success:
        ...     models = client.list_models()
    """
    
    def __init__(self, base_url: Optional[str] = None) -> None:
        """
        Initialize Ollama client.
        
        Args:
            base_url: Base URL for Ollama API (default from config)
        """
        self.base_url: str = base_url or config.OLLAMA_BASE_URL
        self.is_available: bool = False
        self.available_models: List[str] = []
        logger.info(f"OllamaClient initialized with base_url: {self.base_url}")
    
    def check_connection(self) -> Tuple[bool, str]:
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
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            
            if response.status_code == 200:
                self.is_available = True
                data = response.json()
                self.available_models = [model['name'] for model in data.get('models', [])]
                message = f"Ollama is running with {len(self.available_models)} models"
                logger.info(message)
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
    
    def list_models(self) -> Tuple[bool, List[Dict[str, Any]]]:
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
        try:
            logger.debug("Fetching model list")
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            
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
                return True, models
            else:
                logger.warning(f"Failed to list models: {response.status_code}")
                return False, []
                
        except Exception as e:
            logger.error(f"Error listing models: {e}", exc_info=True)
            return False, []
    
    def get_first_available_model(self) -> Optional[str]:
        """
        Get the first available model name.
        
        Returns:
            Name of first available model, or None if no models available
        
        Example:
            >>> model = ollama_client.get_first_available_model()
            >>> if model:
            ...     print(f"Using model: {model}")
        """
        success, models = self.list_models()
        if success and models:
            model_name = models[0]['name']
            logger.debug(f"First available model: {model_name}")
            return model_name
        logger.warning("No models available")
        return None
    
    def pull_model(self, model_name: str) -> Generator[Dict[str, Any], None, None]:
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
            response = requests.post(
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
            else:
                error_msg = f"Failed to pull model: {response.status_code}"
                logger.error(error_msg)
                yield {"error": error_msg}
                
        except Exception as e:
            error_msg = f"Error pulling model: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield {"error": error_msg}
    
    def delete_model(self, model_name: str) -> Tuple[bool, str]:
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
            response = requests.delete(
                f"{self.base_url}/api/delete",
                json={"name": model_name},
                timeout=30
            )
            
            success = response.status_code == 200
            message = "Model deleted successfully" if success else "Failed to delete model"
            
            if success:
                logger.info(f"Deleted model: {model_name}")
            else:
                logger.warning(f"Failed to delete model: {model_name}")
            
            return success, message
            
        except Exception as e:
            logger.error(f"Error deleting model: {e}", exc_info=True)
            return False, str(e)
    
    def get_vision_model(self) -> Optional[str]:
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
        prompt: Optional[str] = None
    ) -> Tuple[bool, str]:
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
            messages: List[Dict[str, Any]] = [
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
                    yield data['message'].get('content', '')
                if data.get('done', False):
                    break

    def _raise_for_ollama_error(self, response, model: str) -> None:
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

            logger.error(f"Model not found: {model!r} — {ollama_detail}")
            raise InvalidModelError(
                f"Model '{model}' is not available. "
                "Go to Model Management to pull or select an installed model.",
                details={"model": model, "ollama_error": ollama_detail},
            )

        body = response.text[:200] if response.text else ""
        logger.error(f"Ollama API error {response.status_code}: {body}")
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}")

    def generate_chat_response(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = True,
        max_tokens: Optional[int] = None
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
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["options"] = {"num_predict": max_tokens}

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            stream=stream,
            timeout=120,
        )

        if response.status_code == 200:
            if stream:
                yield from self._iter_stream_chunks(response)
            else:
                data = response.json()
                yield data.get('message', {}).get('content', '')
            logger.debug("Chat response generated successfully")
        else:
            self._raise_for_ollama_error(response, model)

    def generate_chat_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
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
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        logger.debug(f"Chat completion (non-stream) with model: {model}")
        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=120,
        )

        if response.status_code == 200:
            data = response.json()
            tool_calls = data.get("message", {}).get("tool_calls")
            if tool_calls:
                logger.info(f"Model returned {len(tool_calls)} tool call(s)")
            return data

        self._raise_for_ollama_error(response, model)

    def generate_embedding(
        self,
        model: str,
        text: str
    ) -> Tuple[bool, List[float]]:
        """
        Generate embedding vector for text.
        
        Args:
            model: Name of embedding model (e.g., "nomic-embed-text")
            text: Input text to embed
        
        Returns:
            Tuple of (success: bool, embedding: List[float])
            - success: True if embedding generated
            - embedding: Vector as list of floats, or empty list on failure
        
        Example:
            >>> success, emb = ollama_client.generate_embedding("nomic-embed-text", "test")
            >>> if success:
            ...     print(f"Embedding dimension: {len(emb)}")
        """
        try:
            logger.debug(f"Generating embedding with model: {model}")
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": model,
                    "prompt": text
                },
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                embedding = data.get('embedding', [])
                logger.debug(f"Generated embedding with {len(embedding)} dimensions")
                return True, embedding
            else:
                logger.warning(f"Failed to generate embedding: {response.status_code}")
                return False, []
                
        except Exception as e:
            logger.error(f"Error generating embedding: {e}", exc_info=True)
            return False, []
    
    def _find_model_in_list(self, model_names: list, preferred: list) -> Optional[str]:
        """Return first model from preferred list found (by substring) in model_names."""
        for embed_model in preferred:
            for model_name in model_names:
                if embed_model in model_name:
                    return model_name
        return model_names[0] if model_names else None

    def get_embedding_model(self, preferred_model: Optional[str] = None) -> Optional[str]:
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
        logger.debug(f"Finding best embedding model (preferred: {preferred_model})")
        
        if preferred_model:
            success, models = self.list_models()
            if success:
                model_names = [m['name'] for m in models]
                if preferred_model in model_names:
                    logger.info(f"Using preferred embedding model: {preferred_model}")
                    return preferred_model
        
        embedding_models = [
            'nomic-embed-text', 'mxbai-embed-large', 'all-minilm', 'llama2', 'mistral'
        ]
        success, models = self.list_models()
        if success:
            model_names = [m['name'] for m in models]
            found = self._find_model_in_list(model_names, embedding_models)
            if found:
                is_fallback = found == model_names[0] and not any(e in found for e in embedding_models)
                if is_fallback:
                    logger.warning(f"No dedicated embedding model found, using: {found}")
                else:
                    logger.info(f"Using embedding model: {found}")
            return found
        logger.error("No embedding model available")
        return None
    
    def test_model(self, model_name: str) -> Tuple[bool, str]:
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
