"""Neutral synthetic behavior tests for the local multilingual matcher."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from custom_components.xiaoai_navidrome import matcher
from custom_components.xiaoai_navidrome.matcher import LibraryIndex, Normalizer


class SemanticStub:
    """A deterministic two-dimensional embedder for matcher tests."""

    model_id = "stub:two"

    async def embed_documents(self, values: list[str]) -> list[list[float]]:
        """Place the first synthetic document on x and the second on y."""
        assert len(values) == 2
        return [[1.0, 0.0], [0.0, 1.0]]

    async def embed_query(self, value: str) -> list[float]:
        """Return a synthetic cross-language query close to the first document."""
        assert value == "synthetic-language-request"
        return [3.0, 0.0]


class FailingStub(SemanticStub):
    """Embedder that fails only while producing the query vector."""

    async def embed_query(self, value: str) -> list[float]:
        """Model an unavailable embedding service during a search."""
        raise RuntimeError("unavailable")


def test_normalizer_defers_dictionary_loading_until_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime construction performs no dictionary-backed converter file I/O."""
    calls: list[str] = []

    class Converter:
        def __init__(self, mode: str) -> None:
            calls.append(f"opencc:{mode}")

        @staticmethod
        def convert(value: str) -> str:
            return value

    class Kakasi:
        def __init__(self) -> None:
            calls.append("pykakasi")

        @staticmethod
        def convert(_value: str) -> list[dict[str, str]]:
            return []

    monkeypatch.setattr(matcher, "opencc", SimpleNamespace(OpenCC=Converter))
    monkeypatch.setattr(matcher, "pykakasi", SimpleNamespace(kakasi=Kakasi))

    normalizer = Normalizer()
    assert calls == []
    normalizer.variants("Synthetic")
    assert calls == ["opencc:s2t", "opencc:t2s", "pykakasi"]
    normalizer.variants("Again")
    assert calls == ["opencc:s2t", "opencc:t2s", "pykakasi"]


@pytest.mark.asyncio
async def test_normalizer_handles_scripts_and_excludes_pinyin_initials() -> None:
    """Simplified/traditional, full pinyin, kana, and romaji remain identity keys."""
    normalizer = Normalizer()
    chinese = normalizer.variants("春风")
    assert "春风" in chinese
    assert "春風" in chinese
    assert "chunfeng" in chinese
    assert "cf" not in chinese

    japanese = normalizer.variants("サンプル")
    assert "サンプル" in japanese
    assert "さんぷる" in japanese
    assert "sanpuru" in japanese
    assert normalizer.key("  Ａlpha—BETA! ") == "alphabeta"


@pytest.mark.asyncio
async def test_lexical_scores_and_surface_only_substring_evidence() -> None:
    """Lexical score ordering works without transliteration-based contains evidence."""
    index = LibraryIndex(aliases={"one": ["special trigger"]})
    await index.async_build(
        [
            {"id": "one", "title": "春风", "artist": "蓝组", "album": "Unit"},
            {"id": "two", "title": "Bright Signal", "artist": "North", "album": "Unit"},
        ]
    )

    exact = await index.search("春风 蓝组")
    assert exact["candidates"][0]["id"] == "one"
    assert exact["confidence"] == 0.99
    assert exact["automatic"]
    assert "title_artist_exact" in exact["candidates"][0]["evidence"]

    alias = await index.search("special trigger")
    assert alias["confidence"] == 1.0
    assert alias["candidates"][0]["id"] == "one"

    contained = await index.search("请播放春风蓝组")
    assert contained["confidence"] >= 0.98
    assert "title_artist_contained" in contained["candidates"][0]["evidence"]

    pinyin = await index.search("chunfeng")
    assert pinyin["candidates"][0]["id"] == "one"
    assert "title_exact" in pinyin["candidates"][0]["evidence"]
    assert "title_contained" not in pinyin["candidates"][0]["evidence"]

    fuzzy = await index.search("bright signl")
    assert fuzzy["candidates"][0]["id"] == "two"
    assert fuzzy["candidates"][0]["lexical_score"] > 0.7
    assert "title_fuzzy" in fuzzy["candidates"][0]["evidence"]


@pytest.mark.asyncio
async def test_build_uses_executor_and_browse_and_playlist_rank_are_stable() -> None:
    """CPU indexing dispatches through the supplied callback and browse is lexical only."""
    calls: list[str] = []

    async def executor(function: object, *args: object) -> object:
        calls.append(getattr(function, "__name__", "unknown"))
        return function(*args)  # type: ignore[operator]

    index = LibraryIndex(executor=executor)
    await index.async_build(
        [
            {"id": "b", "title": "Beta Tone", "artist": "Delta"},
            {"id": "a", "title": "Alpha Tone", "artist": "Gamma"},
        ]
    )
    assert "_build_entries" in calls
    assert [track["id"] for track in index.browse()[0]] == ["a", "b"]
    assert index.browse("alpha", 0, 1)[1] == 1
    ranked = index.rank_playlists("alpha pack", [{"id": "p", "name": "Alpha Pack"}])
    assert ranked[0]["score"] == 1.0


@pytest.mark.asyncio
async def test_embedding_supports_automatic_cross_language_and_failure_fallback() -> None:
    """A semantic-only query can autoplay, while provider failure leaves lexical ranking."""
    tracks = [
        {"id": "semantic", "title": "Orchid Grid", "artist": "A"},
        {"id": "other", "title": "Harbor Loop", "artist": "B"},
    ]
    semantic_index = LibraryIndex(embedder=SemanticStub())
    await semantic_index.async_build(tracks)
    semantic = await semantic_index.search("synthetic-language-request")
    assert semantic["candidates"][0]["id"] == "semantic"
    assert semantic["automatic"]
    assert semantic["reason"] == "confident_semantic_match"
    assert semantic["semantic_confidence"] == 1.0
    assert "embedding" in semantic["candidates"][0]["evidence"]

    fallback_index = LibraryIndex(embedder=FailingStub())
    await fallback_index.async_build(tracks)
    fallback = await fallback_index.search("orchid grid")
    assert fallback["candidates"][0]["id"] == "semantic"
    assert fallback["candidates"][0]["lexical_score"] == 0.94
    assert fallback["candidates"][0]["semantic_score"] == 0.0
    assert fallback_index.embedding_error == (
        "Embedding provider is unavailable or returned invalid vectors"
    )
    assert "orchid" not in fallback_index.embedding_error.lower()


@pytest.mark.asyncio
async def test_storage_round_trip_and_drops_model_mismatched_vectors() -> None:
    """Schema one preserves metadata/vectors only when the model identity agrees."""
    index = LibraryIndex(embedder=SemanticStub())
    await index.async_build(
        [
            {"id": "semantic", "title": "Orchid Grid", "artist": "A"},
            {"id": "other", "title": "Harbor Loop", "artist": "B"},
        ]
    )
    stored = index.to_storage()
    assert stored["schema"] == 1
    assert stored["model"] == "stub:two"
    assert all(entry["vector"] for entry in stored["tracks"])

    restored = LibraryIndex.from_storage(
        stored,
        embedder=SemanticStub(),
        autoplay_min_score=0.91,
        autoplay_min_margin=0.19,
        embedding_weight=0.25,
        semantic_autoplay_min_score=0.7,
        semantic_autoplay_min_margin=0.11,
    )
    assert restored.to_storage()["tracks"] == stored["tracks"]
    assert restored.autoplay_min_score == 0.91
    assert restored.autoplay_min_margin == 0.19
    assert restored.embedding_weight == 0.25

    class OtherModel(SemanticStub):
        model_id = "stub:other"

    mismatch = LibraryIndex.from_storage(stored, embedder=OtherModel())
    assert all(not entry["vector"] for entry in mismatch.to_storage()["tracks"])
    assert math.isclose((await mismatch.search("orchid grid"))["confidence"], 0.94)


@pytest.mark.asyncio
async def test_incremental_build_reuses_unchanged_document_vectors() -> None:
    """Only new or changed metadata is sent to the embedding provider."""

    class CountingEmbedder:
        model_id = "stub:incremental"

        def __init__(self) -> None:
            self.batches: list[list[str]] = []

        async def embed_documents(self, values: list[str]) -> list[list[float]]:
            self.batches.append(list(values))
            return [[1.0, float(index + 1)] for index, _ in enumerate(values)]

        async def embed_query(self, value: str) -> list[float]:
            return [1.0, 1.0]

    embedder = CountingEmbedder()
    original = LibraryIndex(embedder=embedder)
    await original.async_build(
        [
            {"id": "one", "title": "Synthetic One", "artist": "A"},
            {"id": "two", "title": "Synthetic Two", "artist": "B"},
        ]
    )
    refreshed = LibraryIndex(embedder=embedder)
    await refreshed.async_build(
        [
            {"id": "one", "title": "Synthetic One", "artist": "A"},
            {"id": "two", "title": "Synthetic Two", "artist": "B"},
            {"id": "three", "title": "Synthetic Three", "artist": "C"},
        ],
        reuse=original,
    )

    assert [len(batch) for batch in embedder.batches] == [2, 1]
    assert all(entry["vector"] for entry in refreshed.to_storage()["tracks"])


@pytest.mark.asyncio
async def test_embedding_documents_are_batched_without_partial_index() -> None:
    """Large libraries use bounded provider batches and retain every valid vector."""

    class BatchEmbedder:
        model_id = "stub:batch"

        def __init__(self) -> None:
            self.sizes: list[int] = []

        async def embed_documents(self, values: list[str]) -> list[list[float]]:
            self.sizes.append(len(values))
            return [[1.0, 1.0] for _ in values]

        async def embed_query(self, _value: str) -> list[float]:
            return [1.0, 1.0]

    embedder = BatchEmbedder()
    index = LibraryIndex(embedder=embedder)
    await index.async_build(
        [
            {"id": f"synthetic-{number}", "title": f"Synthetic Track {number}"}
            for number in range(130)
        ]
    )
    assert embedder.sizes == [64, 64, 2]
    assert index.embedded_count == 130
    assert not index.embedding_error
