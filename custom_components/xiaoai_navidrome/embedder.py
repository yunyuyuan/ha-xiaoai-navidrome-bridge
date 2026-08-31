"""HTTP embedding providers used by the optional local semantic matcher."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

import aiohttp

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_BATCH_SIZE = 64
MAX_VECTOR_DIMENSIONS = 8192
DEFAULT_TIMEOUT_SECONDS = 15.0
QUERY_INSTRUCTION = (
    "Instruct: Match a spoken music request to the correct music-library track. "
    "Prefer exact title and artist identity across languages, scripts and transliterations.\n"
    "Query: "
)


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider response is unsafe or unusable."""


class HTTPEmbedder:
    """Embed documents and queries through Ollama or OpenAI-compatible HTTP APIs.

    The caller owns an injected ``aiohttp.ClientSession``.  An API key is never
    placed in URLs or request JSON; OpenAI requests use it only in the standard
    ``Authorization`` header.
    """

    def __init__(
        self,
        base_url: str,
        provider: str,
        model: str,
        api_key: str = "",
        *,
        session: Any | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Configure one provider endpoint and optional externally managed session."""
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {"ollama", "openai"}:
            raise ValueError("provider must be 'ollama' or 'openai'")
        if not model.strip():
            raise ValueError("embedding model is required")
        try:
            parsed = urlsplit(base_url)
            hostname = parsed.hostname
            _port = parsed.port
        except ValueError as err:
            raise ValueError("base_url must be an absolute HTTP(S) URL") from err
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.provider = normalized_provider
        self.model = model.strip()
        self.api_key = api_key
        self.session = session
        self.timeout = float(timeout)

    @property
    def model_id(self) -> str:
        """Return a stable provider-qualified model identifier for persistence."""
        return f"{self.provider}:{self.model}"

    async def embed_documents(self, values: Sequence[str]) -> list[list[float]]:
        """Embed a non-empty document batch and preserve input ordering exactly."""
        return await self._embed([str(value) for value in values])

    async def embed_query(self, value: str) -> list[float]:
        """Embed a query with the music retrieval instruction prefix."""
        vectors = await self._embed([QUERY_INSTRUCTION + str(value)])
        if len(vectors) != 1:
            raise EmbeddingError(
                f"embedding provider returned {len(vectors)} vectors for one query"
            )
        return vectors[0]

    async def _embed(self, values: list[str]) -> list[list[float]]:
        """Submit one provider batch, bound the response size, and validate vectors."""
        if not values:
            return []
        if len(values) > MAX_BATCH_SIZE:
            raise EmbeddingError(f"embedding batch exceeds {MAX_BATCH_SIZE} inputs")
        body = {"model": self.model, "input": values}
        endpoint = "/v1/embeddings" if self.provider == "openai" else "/api/embed"
        headers = {"Content-Type": "application/json"}
        if self.provider == "openai" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            payload, status = await self._post_json(endpoint, body, headers)
        except EmbeddingError:
            raise
        except TimeoutError as exc:
            raise EmbeddingError("embedding request timed out") from exc
        except Exception as exc:
            raise EmbeddingError(f"embedding request failed: {exc}") from exc
        if not HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
            detail = _error_detail(payload)
            raise EmbeddingError(f"embedding provider HTTP {status}: {detail}")
        return await asyncio.to_thread(self._parse_and_normalize, payload, len(values))

    def _parse_and_normalize(self, payload: Any, expected_count: int) -> list[list[float]]:
        """Validate a decoded provider payload away from Home Assistant's event loop."""
        vectors = self._parse_response(payload, expected_count)
        return _validate_and_normalize(vectors, expected_count)

    async def _post_json(
        self, endpoint: str, body: Mapping[str, Any], headers: Mapping[str, str]
    ) -> tuple[Any, int]:
        """POST JSON using the injected aiohttp session or a short-lived session."""
        url = self.base_url + endpoint
        if self.session is not None:
            return await self._request_with_session(self.session, url, body, headers)
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await self._request_with_session(session, url, body, headers)

    async def _request_with_session(
        self, session: Any, url: str, body: Mapping[str, Any], headers: Mapping[str, str]
    ) -> tuple[Any, int]:
        """Use aiohttp's response context manager and enforce a 64 MiB read cap."""
        request = session.post(
            url,
            json=dict(body),
            headers=dict(headers),
            timeout=self.timeout,
            allow_redirects=False,
        )
        async with request as response:
            raw = await _read_limited(response.content)
            try:
                decoded = await asyncio.to_thread(json.loads, raw)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise EmbeddingError("embedding provider returned invalid JSON") from exc
            return decoded, int(response.status)

    def _parse_response(self, payload: Any, expected_count: int) -> list[list[Any]]:
        """Parse provider-specific schema and validate OpenAI indices before vectors."""
        if not isinstance(payload, Mapping):
            raise EmbeddingError("embedding provider response must be a JSON object")
        provider_error = _error_detail(payload)
        if self.provider == "ollama":
            if payload.get("error"):
                raise EmbeddingError(f"embedding provider: {provider_error}")
            ollama_vectors = payload.get("embeddings")
            if not isinstance(ollama_vectors, list) or len(ollama_vectors) != expected_count:
                raise EmbeddingError("Ollama response has no embeddings array")
            for index, vector in enumerate(ollama_vectors):
                _validate_vector_container(vector, index)
            return ollama_vectors

        error = payload.get("error")
        if error:
            raise EmbeddingError(f"embedding provider: {provider_error}")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != expected_count:
            count = len(data) if isinstance(data, list) else 0
            raise EmbeddingError(
                f"embedding provider returned {count} vectors for {expected_count} inputs"
            )
        openai_vectors: list[list[Any] | None] = [None] * expected_count
        for item in data:
            if not isinstance(item, Mapping):
                raise EmbeddingError("OpenAI embedding item must be an object")
            position = item.get("index")
            vector = item.get("embedding")
            if (
                not isinstance(position, int)
                or position < 0
                or position >= expected_count
                or openai_vectors[position] is not None
            ):
                raise EmbeddingError(
                    f"embedding provider returned invalid or duplicate index {position!r}"
                )
            if not isinstance(vector, list):
                raise EmbeddingError(
                    f"embedding provider returned a non-array vector at index {position}"
                )
            _validate_vector_container(vector, position)
            openai_vectors[position] = vector
        if any(vector is None for vector in openai_vectors):
            raise EmbeddingError("embedding provider omitted a vector index")
        return [vector for vector in openai_vectors if vector is not None]


async def _read_limited(content: Any) -> bytes:
    """Read an aiohttp response content stream while rejecting oversized data."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in content.iter_chunked(64 * 1024):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise EmbeddingError("embedding response exceeds 8 MiB")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_and_normalize(vectors: Sequence[Any], expected_count: int) -> list[list[float]]:
    """Check batch count/dimensions and return L2-normalized finite vectors."""
    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"embedding provider returned {len(vectors)} vectors for {expected_count} inputs"
        )
    normalized: list[list[float]] = []
    dimension: int | None = None
    for index, vector in enumerate(vectors):
        _validate_vector_container(vector, index)
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise EmbeddingError(
                f"embedding provider returned a non-numeric vector at index {index}"
            ) from exc
        if any(not math.isfinite(value) for value in values):
            raise EmbeddingError(
                f"embedding provider returned a non-finite vector at index {index}"
            )
        if dimension is None:
            dimension = len(values)
        elif len(values) != dimension:
            raise EmbeddingError("embedding provider returned inconsistent vector dimensions")
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            raise EmbeddingError(f"embedding provider returned a zero vector at index {index}")
        normalized.append([value / norm for value in values])
    return normalized


def _validate_vector_container(vector: Any, index: int) -> None:
    """Reject malformed or implausibly wide vectors before any numeric copies."""
    if not isinstance(vector, list) or not vector:
        raise EmbeddingError(f"embedding provider returned an empty vector at index {index}")
    if len(vector) > MAX_VECTOR_DIMENSIONS:
        raise EmbeddingError(
            f"embedding vector at index {index} exceeds {MAX_VECTOR_DIMENSIONS} dimensions"
        )


def _error_detail(payload: Any) -> str:
    """Extract a bounded provider error message without exposing request secrets."""
    if not isinstance(payload, Mapping):
        return "unexpected response"
    error = payload.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if message:
            return str(message)[:1024]
    if isinstance(error, str):
        return error[:1024]
    message = payload.get("message")
    return str(message)[:1024] if message else "request failed"
