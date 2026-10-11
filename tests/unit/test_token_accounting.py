"""OBS-1a — every model call is counted by tokens, labelled by model and path only.

The Ollama half runs the real client against `tests/utils/fake_ollama.py` in-process
(`httpx.ASGITransport`, no socket), so the counts come from the same final `done`
object a real Ollama sends. The stub reports one token per word: the system and user
messages below are 3 + 3 = 6 prompt words, and the reply
"Based on the provided context, what is pgvector" is 8 words.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src import monitoring
from src.llm_client import LiteLLMClient
from src.ollama_client import OllamaClient
from tests.utils.fake_ollama import create_app

pytestmark = pytest.mark.unit

MODEL = "llama3.2:latest"
MESSAGES = [
    {"role": "system", "content": "You are helpful"},
    {"role": "user", "content": "what is pgvector"},
]
LOCAL = f'model="{MODEL}",path="local"'


@pytest.fixture
def metrics(monkeypatch):
    collector = monitoring.MetricsCollector()
    monkeypatch.setattr(monitoring, "_metrics", collector)
    return collector


@pytest.fixture
def ollama():
    client = OllamaClient(base_url="http://fake-ollama")
    client._async_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()))
    return client


async def _stream(client: OllamaClient) -> str:
    return "".join([c async for c in client.generate_chat_response(MODEL, MESSAGES, stream=True)])


async def test_two_streamed_chats_add_exactly_the_tokens_ollama_reported(ollama, metrics):
    await _stream(ollama)
    await _stream(ollama)

    counters = metrics.get_metrics()["counters"]
    assert (
        counters[f"llm_calls_total{{{LOCAL}}}"],
        counters[f"llm_prompt_tokens_total{{{LOCAL}}}"],
        counters[f"llm_completion_tokens_total{{{LOCAL}}}"],
    ) == (2, 12, 16)


async def test_non_streamed_and_tool_completions_are_counted_too(ollama, metrics):
    [_ async for _ in ollama.generate_chat_response(MODEL, MESSAGES, stream=False)]
    await ollama.generate_chat_completion(MODEL, MESSAGES)

    counters = metrics.get_metrics()["counters"]
    assert (counters[f"llm_prompt_tokens_total{{{LOCAL}}}"],
            counters[f"llm_completion_tokens_total{{{LOCAL}}}"]) == (12, 16)


async def test_the_local_path_records_no_cost(ollama, metrics):
    await _stream(ollama)

    assert not any(k.startswith("llm_cost_usd_total") for k in metrics.get_metrics()["counters"])


async def test_token_counters_carry_only_the_model_and_path_labels(ollama, metrics):
    await _stream(ollama)

    llm_keys = {k for k in metrics.get_metrics()["counters"] if k.startswith("llm_")}
    assert llm_keys == {
        f"llm_calls_total{{{LOCAL}}}",
        f"llm_prompt_tokens_total{{{LOCAL}}}",
        f"llm_completion_tokens_total{{{LOCAL}}}",
    }


async def test_prometheus_export_carries_the_token_totals(ollama, metrics):
    await _stream(ollama)

    lines = monitoring.export_prometheus_metrics().splitlines()
    assert "# TYPE llm_prompt_tokens_total counter" in lines
    assert f"llm_prompt_tokens_total{{{LOCAL}}} 6" in lines
    assert f"llm_completion_tokens_total{{{LOCAL}}} 8" in lines


# ── cloud path ────────────────────────────────────────────────────────────────

CLOUD_MODEL = "gpt-4o-mini"
CLOUD = f'model="{CLOUD_MODEL}",path="cloud"'


def _chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
                           usage=None)


def _canned_stream(prompt: int, completion: int) -> list[SimpleNamespace]:
    # What litellm yields with include_usage: content chunks, then one with usage only.
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    return [_chunk("Hello"), _chunk(" world"), SimpleNamespace(choices=[], usage=usage)]


def _cloud_client(fake_litellm: MagicMock) -> LiteLLMClient:
    with patch.dict("sys.modules", {"litellm": fake_litellm}):
        return LiteLLMClient("openai", None, CLOUD_MODEL)


def test_two_cloud_streams_add_their_reported_tokens_and_priced_cost(metrics):
    fake = MagicMock()
    fake.completion.side_effect = [_canned_stream(120, 30), _canned_stream(80, 20)]
    fake.cost_per_token.side_effect = [(0.0012, 0.0045), (0.0008, 0.0030)]
    client = _cloud_client(fake)

    assert "".join(client.generate_chat_response(CLOUD_MODEL, MESSAGES)) == "Hello world"
    list(client.generate_chat_response(CLOUD_MODEL, MESSAGES))

    counters = metrics.get_metrics()["counters"]
    assert (
        counters[f"llm_calls_total{{{CLOUD}}}"],
        counters[f"llm_prompt_tokens_total{{{CLOUD}}}"],
        counters[f"llm_completion_tokens_total{{{CLOUD}}}"],
        round(counters[f"llm_cost_usd_total{{{CLOUD}}}"], 6),
    ) == (2, 200, 50, 0.0095)


def test_a_cloud_stream_asks_litellm_for_usage(metrics):
    fake = MagicMock()
    fake.completion.return_value = _canned_stream(1, 1)
    fake.cost_per_token.return_value = (0.0, 0.0)

    list(_cloud_client(fake).generate_chat_response(CLOUD_MODEL, MESSAGES))

    assert fake.completion.call_args.kwargs["stream_options"] == {"include_usage": True}


def test_a_model_litellm_cannot_price_still_counts_its_tokens(metrics):
    fake = MagicMock()
    fake.completion.return_value = _canned_stream(120, 30)
    fake.cost_per_token.side_effect = Exception("model not mapped")

    list(_cloud_client(fake).generate_chat_response(CLOUD_MODEL, MESSAGES))

    counters = metrics.get_metrics()["counters"]
    assert counters[f"llm_prompt_tokens_total{{{CLOUD}}}"] == 120
    assert f"llm_cost_usd_total{{{CLOUD}}}" not in counters


def test_a_cloud_response_without_usage_records_nothing(metrics):
    fake = MagicMock()
    fake.completion.return_value = [_chunk("Hello")]

    list(_cloud_client(fake).generate_chat_response(CLOUD_MODEL, MESSAGES))

    assert not any(k.startswith("llm_") for k in metrics.get_metrics()["counters"])


def test_a_non_streamed_cloud_completion_is_counted(metrics):
    fake = MagicMock()
    response = MagicMock()
    response.usage = SimpleNamespace(prompt_tokens=50, completion_tokens=10)
    fake.completion.return_value = response
    fake.cost_per_token.return_value = (0.0005, 0.0010)

    _cloud_client(fake).generate_chat_completion(CLOUD_MODEL, MESSAGES)

    counters = metrics.get_metrics()["counters"]
    assert (counters[f"llm_prompt_tokens_total{{{CLOUD}}}"],
            counters[f"llm_completion_tokens_total{{{CLOUD}}}"],
            round(counters[f"llm_cost_usd_total{{{CLOUD}}}"], 6)) == (50, 10, 0.0015)
