"""A stand-in for Ollama, so the ingest → ask → cite path can run in CI.

The integration suite mocked retrieval and the model at the boundary, which meant the
one path the product exists for — put a document in, ask about it, get an answer that
cites it — was never executed end to end. It needs an embedding service and a chat
model, and CI has no GPU.

**The embeddings are deliberately not random.** A hash-to-noise vector would let this
harness "work" while making every retrieval assertion arbitrary: the expected chunk
would rank first by luck, and the test would pass whatever the retrieval code did.
Instead each text is embedded as an L2-normalised bag of its words, so cosine
similarity tracks word overlap. A query about pgvector then genuinely ranks the
pgvector chunk above the others, and the ordering is a property of the retrieval code
rather than of the stub.

Deterministic across processes: `zlib.crc32`, not `hash()`, which Python randomises
per interpreter.
"""

from __future__ import annotations

import json
import math
import re
import threading
import zlib
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

EMBEDDING_DIMS = 768

#: What a chat completion answers with. Fixed, because the assertion that matters is
#: which sources came back, not what the model said about them.
CANNED_REPLY = "Based on the provided context, "

_WORD_RE = re.compile(r"[a-z0-9]+")


def embed(text: str, dims: int = EMBEDDING_DIMS) -> list[float]:
    """An L2-normalised bag-of-words vector. Same text in, same vector out."""
    vector = [0.0] * dims
    for word in _WORD_RE.findall(text.lower()):
        vector[zlib.crc32(word.encode()) % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        # An empty or punctuation-only string. A zero vector makes pgvector's cosine
        # distance undefined, so return a fixed unit vector instead.
        vector[0] = 1.0
        return vector
    return [v / norm for v in vector]


def create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/tags")
    def tags() -> dict[str, Any]:
        return {"models": [
            {"name": "llama3.2:latest", "size": 2_000_000_000, "digest": "fake"},
            {"name": "nomic-embed-text:latest", "size": 274_000_000, "digest": "fake"},
        ]}

    @app.get("/api/ps")
    def running() -> dict[str, Any]:
        return {"models": []}

    @app.post("/api/embed")
    async def embed_new(request: Request) -> dict[str, Any]:
        body = await request.json()
        inputs = body.get("input", body.get("prompt", ""))
        texts = inputs if isinstance(inputs, list) else [inputs]
        return {"embeddings": [embed(t) for t in texts], "model": body.get("model", "")}

    @app.post("/api/embeddings")
    async def embed_legacy(request: Request) -> dict[str, Any]:
        body = await request.json()
        return {"embedding": embed(body.get("prompt", ""))}

    @app.post("/api/chat")
    async def chat(request: Request) -> Any:
        body = await request.json()
        model = body.get("model", "llama3.2:latest")
        reply = CANNED_REPLY + _first_user_message(body)

        if not body.get("stream", True):
            return {"message": {"role": "assistant", "content": reply}, "done": True}

        def _stream():
            # Ollama streams newline-delimited JSON, one object per chunk.
            for token in reply.split(" "):
                yield json.dumps({
                    "model": model,
                    "message": {"role": "assistant", "content": token + " "},
                    "done": False,
                }) + "\n"
            yield json.dumps({"model": model, "message": {"role": "assistant", "content": ""},
                              "done": True, "done_reason": "stop"}) + "\n"

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    return app


def _first_user_message(body: dict[str, Any]) -> str:
    for message in reversed(body.get("messages") or []):
        if message.get("role") == "user":
            return str(message.get("content", ""))[:200]
    return ""


class FakeOllama:
    """Runs the stub on a background thread; `base_url` is what the client should use."""

    def __init__(self, port: int = 0) -> None:
        self._config = uvicorn.Config(create_app(), host="127.0.0.1", port=port,
                                      log_level="warning")
        self._server = uvicorn.Server(self._config)
        self._thread: threading.Thread | None = None

    def start(self, timeout: float = 10.0) -> str:
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = threading.Event()
        waited = 0.0
        while not self._server.started and waited < timeout:
            deadline.wait(0.05)
            waited += 0.05
        if not self._server.started:
            raise RuntimeError("fake Ollama did not start")
        port = self._server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
