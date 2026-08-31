"""Neutral synthetic tests for HTTP embedding provider validation."""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from typing import Any

import pytest
from custom_components.xiaoai_navidrome.embedder import (
    MAX_RESPONSE_BYTES,
    MAX_VECTOR_DIMENSIONS,
    QUERY_INSTRUCTION,
    EmbeddingError,
    HTTPEmbedder,
)


class FakeContent:
    """Async response stream for an injected fake aiohttp session."""

    def __init__(self, raw: bytes) -> None:
        """Store a deterministic response body."""
        self.raw = raw

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        """Yield the body in chunks of the caller-selected size."""
        for start in range(0, len(self.raw), size):
            yield self.raw[start : start + size]


class FakeResponse:
    """Minimal async aiohttp response context manager."""

    def __init__(self, status: int, body: object) -> None:
        """Create a JSON response with the requested status."""
        self.status = status
        self.content = FakeContent(json.dumps(body).encode())

    async def __aenter__(self) -> FakeResponse:
        """Enter the response context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the response context without suppression."""


class FakeSession:
    """Capture one request and return a configured fake response."""

    def __init__(self, status: int, body: object) -> None:
        """Configure the provider response and empty capture fields."""
        self.status = status
        self.body = body
        self.url = ""
        self.json: dict[str, Any] = {}
        self.headers: dict[str, str] = {}
        self.timeout: float | None = None
        self.allow_redirects = True

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        """Capture the HTTP request exactly as the provider client sends it."""
        self.url = url
        self.json = kwargs["json"]
        self.headers = kwargs["headers"]
        self.timeout = kwargs["timeout"]
        self.allow_redirects = kwargs["allow_redirects"]
        return FakeResponse(self.status, self.body)


@pytest.mark.asyncio
async def test_ollama_batch_endpoint_l2_normalization_and_injected_session() -> None:
    """Ollama uses /api/embed and returns a strictly normalized batch."""
    session = FakeSession(200, {"embeddings": [[3, 4], [0, 2]]})
    embedder = HTTPEmbedder("http://unit.invalid/", "ollama", "synthetic-model", session=session)
    vectors = await embedder.embed_documents(["first", "second"])
    assert session.url == "http://unit.invalid/api/embed"
    assert session.json == {"model": "synthetic-model", "input": ["first", "second"]}
    assert "Authorization" not in session.headers
    assert session.allow_redirects is False
    assert vectors == [[0.6, 0.8], [0.0, 1.0]]
    assert embedder.model_id == "ollama:synthetic-model"


@pytest.mark.asyncio
async def test_openai_query_uses_instruction_and_authorization_header_only() -> None:
    """OpenAI queries carry the retrieval instruction and keep the key out of JSON/URL."""
    session = FakeSession(200, {"data": [{"index": 0, "embedding": [1, 1]}]})
    embedder = HTTPEmbedder(
        "https://unit.invalid/base",
        "openai",
        "synthetic-model",
        "key-123",
        session=session,
        timeout=3.5,
    )
    vector = await embedder.embed_query("neutral request")
    assert session.url == "https://unit.invalid/base/v1/embeddings"
    assert session.headers["Authorization"] == "Bearer key-123"
    assert session.json["model"] == "synthetic-model"
    assert session.json["input"] == [QUERY_INSTRUCTION + "neutral request"]
    assert "key-123" not in session.url
    assert "key-123" not in json.dumps(session.json)
    assert math.isclose(sum(value * value for value in vector), 1.0)
    assert session.timeout == 3.5


@pytest.mark.asyncio
async def test_provider_rejects_inconsistent_or_invalid_indexed_batches() -> None:
    """Malformed OpenAI indices and dimensions surface as EmbeddingError."""
    duplicate = FakeSession(
        200,
        {"data": [{"index": 0, "embedding": [1, 0]}, {"index": 0, "embedding": [0, 1]}]},
    )
    embedder = HTTPEmbedder("http://unit.invalid", "openai", "synthetic", session=duplicate)
    with pytest.raises(EmbeddingError, match="duplicate"):
        await embedder.embed_documents(["a", "b"])

    inconsistent = FakeSession(200, {"embeddings": [[1, 0], [1, 0, 0]]})
    ollama = HTTPEmbedder("http://unit.invalid", "ollama", "synthetic", session=inconsistent)
    with pytest.raises(EmbeddingError, match="inconsistent"):
        await ollama.embed_documents(["a", "b"])


@pytest.mark.asyncio
async def test_response_limit_is_exposed_as_embedding_error() -> None:
    """A response larger than the hard 8 MiB limit is rejected before parsing."""

    class OversizedContent:
        """Yield one byte beyond the fixed response limit."""

        async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
            """Yield a deliberately oversized binary payload."""
            del size
            yield b"x" * (MAX_RESPONSE_BYTES + 1)

    class OversizedResponse(FakeResponse):
        """Fake response whose body cannot fit within the allowed safety bound."""

        def __init__(self) -> None:
            """Set a successful response status with oversized stream content."""
            self.status = 200
            self.content = OversizedContent()

    class OversizedSession(FakeSession):
        """Return the oversized response through the regular session seam."""

        def post(self, url: str, **kwargs: Any) -> OversizedResponse:
            """Capture the call and return a stream beyond the size ceiling."""
            super().post(url, **kwargs)
            return OversizedResponse()

    embedder = HTTPEmbedder(
        "http://unit.invalid", "ollama", "synthetic", session=OversizedSession(200, {})
    )
    with pytest.raises(EmbeddingError, match="8 MiB"):
        await embedder.embed_documents(["a"])


def test_embedding_url_rejects_userinfo_query_and_fragment() -> None:
    """Provider URLs cannot smuggle credentials or ambiguous endpoint suffixes."""
    for url in (
        "https://user:pass@unit.invalid",
        "https://unit.invalid?target=other",
        "https://unit.invalid/#fragment",
        "https://unit.invalid:bad",
    ):
        with pytest.raises(ValueError, match="absolute HTTP"):
            HTTPEmbedder(url, "ollama", "synthetic-model")


@pytest.mark.asyncio
async def test_implausibly_wide_vector_is_rejected() -> None:
    """A small JSON body cannot expand into millions of Python float objects."""
    session = FakeSession(200, {"embeddings": [[0] * (MAX_VECTOR_DIMENSIONS + 1)]})
    embedder = HTTPEmbedder("http://unit.invalid", "ollama", "synthetic", session=session)
    with pytest.raises(EmbeddingError, match="exceeds"):
        await embedder.embed_query("neutral request")
