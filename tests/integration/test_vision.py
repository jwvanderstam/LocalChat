"""Tests for the vision feature: OllamaClient.describe_image and image chat."""

import base64
from unittest.mock import patch

import pytest


class TestDescribeImage:
    """Unit tests for OllamaClient.describe_image."""

    def _make_client(self):
        from src.ollama_client import OllamaClient

        return OllamaClient()

    def test_assembles_chunks_into_description(self):
        client = self._make_client()
        with patch.object(
            client,
            "generate_chat_response",
            return_value=iter(["A ", "red ", "apple."]),
        ):
            success, desc = client.describe_image("llava:7b", "base64data==")
        assert success is True
        assert desc == "A red apple."

    def test_uses_custom_prompt_when_provided(self):
        client = self._make_client()
        captured: dict = {}

        def fake_stream(model, messages, **kwargs):
            captured["messages"] = messages
            return iter(["ok"])

        with patch.object(client, "generate_chat_response", side_effect=fake_stream):
            client.describe_image("llava:7b", "b64==", prompt="Describe the colours.")

        assert captured["messages"][0]["content"] == "Describe the colours."

    def test_returns_false_on_exception(self):
        client = self._make_client()
        with patch.object(
            client,
            "generate_chat_response",
            side_effect=RuntimeError("connection refused"),
        ):
            success, msg = client.describe_image("llava:7b", "b64data==")
        assert success is False
        assert "connection refused" in msg

    def test_strips_trailing_whitespace_from_description(self):
        client = self._make_client()
        with patch.object(
            client,
            "generate_chat_response",
            return_value=iter(["  A cat.  ", "  \n"]),
        ):
            _, desc = client.describe_image("llava:7b", "b64==")
        assert desc == "A cat."


class TestGetVisionModel:
    """Unit tests for OllamaClient.get_vision_model."""

    def _make_client(self):
        from src.ollama_client import OllamaClient

        return OllamaClient()

    def test_returns_none_when_list_models_fails(self):
        client = self._make_client()
        with patch.object(client, "list_models", return_value=(False, [])):
            assert client.get_vision_model() is None

    def test_returns_none_when_model_list_empty(self):
        client = self._make_client()
        with patch.object(client, "list_models", return_value=(True, [])):
            assert client.get_vision_model() is None

    def test_returns_llava_model_when_available(self):
        client = self._make_client()
        with patch.object(
            client,
            "list_models",
            return_value=(True, [{"name": "llava:7b"}, {"name": "llama3.2"}]),
        ):
            assert client.get_vision_model() == "llava:7b"

    def test_falls_back_to_first_model_when_no_vision_model_found(self):
        client = self._make_client()
        with patch.object(
            client,
            "list_models",
            return_value=(True, [{"name": "llama3.2"}, {"name": "mistral"}]),
        ):
            model = client.get_vision_model()
        assert model == "llama3.2"


class TestLoadImageFile:
    """Unit tests for DocumentLoaderMixin.load_image_file."""

    def test_returns_false_when_no_vision_model_available(self, tmp_path):
        from src.rag.loaders import DocumentLoaderMixin

        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        loader = DocumentLoaderMixin()
        with patch("src.rag.loaders.ollama_client.get_vision_model", return_value=None):
            success, msg = loader.load_image_file(str(img_path))

        assert success is False
        assert "No vision model" in msg

    def test_returns_description_on_success(self, tmp_path):
        from src.rag.loaders import DocumentLoaderMixin

        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)

        loader = DocumentLoaderMixin()
        with patch("src.rag.loaders.ollama_client.get_vision_model", return_value="llava:7b"):
            with patch(
                "src.rag.loaders.ollama_client.describe_image",
                return_value=(True, "A beautiful landscape photo."),
            ):
                success, content = loader.load_image_file(str(img_path))

        assert success is True
        assert "photo.jpg" in content
        assert "A beautiful landscape photo." in content

    def test_returns_false_when_describe_fails(self, tmp_path):
        from src.rag.loaders import DocumentLoaderMixin

        img_path = tmp_path / "broken.jpg"
        img_path.write_bytes(b"\xff\xd8" + b"\x00" * 20)

        loader = DocumentLoaderMixin()
        with patch("src.rag.loaders.ollama_client.get_vision_model", return_value="llava:7b"):
            with patch(
                "src.rag.loaders.ollama_client.describe_image",
                return_value=(False, "Model not responding"),
            ):
                success, msg = loader.load_image_file(str(img_path))

        assert success is False
        assert "Model not responding" in msg


@pytest.mark.integration
class TestChatWithImages:
    """Integration tests for the /api/chat endpoint with image attachments."""

    def setup_method(self):
        from src import config

        self._original_model = config.app_state.get_active_model()
        self._original_tool_calling = config.TOOL_CALLING_ENABLED
        # Disable tool calling so the route uses generate_chat_response directly
        config.TOOL_CALLING_ENABLED = False

    def teardown_method(self):
        from src import config

        config.app_state.set_active_model(self._original_model)
        config.TOOL_CALLING_ENABLED = self._original_tool_calling

    def test_chat_with_image_streams_sse_response(self, app, client):
        from src import config

        config.app_state.set_active_model("llava:7b")
        app.startup_status["ollama"] = True

        with patch.object(
            app.ollama_client,
            "generate_chat_response",
            return_value=iter(["I can see a cat."]),
        ):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "What is in this image?",
                    "images": [base64.b64encode(b"fake_image_bytes").decode()],
                    "use_rag": False,
                },
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        assert "I can see a cat." in resp.data.decode()

    def test_images_field_is_passed_to_llm(self, app, client):
        from src import config

        config.app_state.set_active_model("llava:7b")
        app.startup_status["ollama"] = True
        captured: dict = {}

        def capture(model, messages, **kwargs):
            captured["messages"] = messages
            return iter(["ok"])

        fake_b64 = base64.b64encode(b"pixel_data").decode()

        with patch.object(app.ollama_client, "generate_chat_response", side_effect=capture):
            client.post(
                "/api/chat",
                json={"message": "Describe it", "images": [fake_b64], "use_rag": False},
            )

        # The user message must carry the images list
        user_msgs = [m for m in captured.get("messages", []) if m.get("role") == "user"]
        assert any("images" in m for m in user_msgs)
