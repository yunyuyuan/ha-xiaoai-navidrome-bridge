"""Local multilingual library matching for the XiaoAI Navidrome integration.

The module has no Home Assistant runtime dependency.  It deliberately keeps the
lexical index in memory and treats phonetic/transliterated forms as *identity*
evidence only: they are eligible for exact and fuzzy comparisons, never for
substring evidence.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import math
import threading
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast

try:  # Optional at import time so a broken optional runtime cannot stop HA.
    pypinyin: Any | None = importlib.import_module("pypinyin")
except Exception:  # pragma: no cover - exercised where extras are absent.
    pypinyin = None

try:  # ``opencc-python-reimplemented`` intentionally imports as ``opencc``.
    opencc: Any | None = importlib.import_module("opencc")
except Exception:  # pragma: no cover - exercised where extras are absent.
    opencc = None

try:
    pykakasi: Any | None = importlib.import_module("pykakasi")
except Exception:  # pragma: no cover - exercised where extras are absent.
    pykakasi = None

if TYPE_CHECKING:
    from .model import Playlist, Track


DEFAULT_CANDIDATE_LIMIT = 20
AUTOPLAY_MIN_SCORE = 0.72
AUTOPLAY_MIN_MARGIN = 0.08
SEMANTIC_AUTOPLAY_MIN_SCORE = 0.60
SEMANTIC_AUTOPLAY_MIN_MARGIN = 0.05
EMBEDDING_WEIGHT = 0.35
SEMANTIC_EVIDENCE_MIN_SCORE = 0.5
SEMANTIC_LEXICAL_OVERRIDE_MAX = 0.35
MIN_CANDIDATE_SCORE = 0.15
EMBEDDING_BATCH_SIZE = 64

_T = TypeVar("_T")
ExecutorCallback = Callable[..., Awaitable[Any] | Any]


class Embedder(Protocol):
    """The small async embedding interface consumed by :class:`LibraryIndex`."""

    @property
    def model_id(self) -> str:
        """Return the stable provider-and-model identifier."""

    async def embed_documents(self, values: Sequence[str]) -> list[list[float]]:
        """Embed library documents in their supplied order."""

    async def embed_query(self, value: str) -> list[float]:
        """Embed one spoken query."""


class Normalizer:
    """Create deterministic Unicode, Chinese, and Japanese search keys.

    Missing optional transliteration libraries only reduce the variants produced;
    they never prevent ordinary Unicode lexical matching from working.  Module
    globals are kept intentionally simple so tests can monkeypatch a provider.
    """

    def __init__(self) -> None:
        """Create a lazy, thread-safe converter holder without file I/O."""
        self._s2t: Any | None = None
        self._t2s: Any | None = None
        self._kakasi: Any | None = None
        self._initialized = False
        self._initialize_lock = threading.Lock()

    def _ensure_converters(self) -> None:
        """Load optional dictionary-backed converters once in the caller's thread."""
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            if opencc is not None:
                try:
                    self._s2t = opencc.OpenCC("s2t")
                    self._t2s = opencc.OpenCC("t2s")
                except Exception:
                    self._s2t = None
                    self._t2s = None
            if pykakasi is not None:
                try:
                    self._kakasi = pykakasi.kakasi()
                except Exception:
                    self._kakasi = None
            self._initialized = True

    @staticmethod
    def key(value: str) -> str:
        """Return an NFKC, case-folded key containing only letters and numbers."""
        folded = unicodedata.normalize("NFKC", str(value).strip()).casefold()
        return "".join(character for character in folded if character.isalnum())

    def surface_variants(self, value: str) -> list[str]:
        """Return original, simplified, and traditional keys for substring use."""
        self._ensure_converters()
        candidates = [str(value)]
        for converter in (self._s2t, self._t2s):
            if converter is None:
                continue
            try:
                candidates.append(str(converter.convert(str(value))))
            except Exception:
                continue
        return _unique_sorted(self.key(candidate) for candidate in candidates)

    def variants(self, value: str) -> list[str]:
        """Return surface forms plus full pinyin and Japanese reading forms.

        Pinyin is joined from complete syllables.  Initial-letter abbreviations
        are never generated, preventing short accidental phonetic matches.
        """
        original = str(value)
        variants: list[str] = list(self.surface_variants(original))
        pinyin_value = self._pinyin(original)
        if pinyin_value:
            variants.append(pinyin_value)
        variants.extend(self._japanese_variants(original))
        return _unique_sorted(variants)

    def _pinyin(self, value: str) -> str:
        """Convert Chinese readings to one complete-syllable key if available."""
        if pypinyin is None:
            return ""
        try:
            syllables = pypinyin.lazy_pinyin(value)
        except Exception:
            return ""
        if not isinstance(syllables, Sequence):
            return ""
        return self.key("".join(str(syllable) for syllable in syllables))

    def _japanese_variants(self, value: str) -> list[str]:
        """Return hiragana, katakana, and Hepburn forms supplied by pykakasi."""
        self._ensure_converters()
        if self._kakasi is None:
            return []
        try:
            pieces = self._kakasi.convert(value)
        except Exception:
            return []
        if not isinstance(pieces, Sequence):
            return []
        readings: dict[str, list[str]] = {"hira": [], "kana": [], "hepburn": []}
        for piece in pieces:
            if not isinstance(piece, Mapping):
                continue
            for name, reading in readings.items():
                candidate = piece.get(name)
                if candidate:
                    reading.append(str(candidate))
        return [self.key("".join(reading)) for reading in readings.values() if reading]


@dataclass(slots=True)
class _IndexedTrack:
    """Derived matching fields for a single serialized track record."""

    track: dict[str, Any]
    title_variants: list[str]
    artist_variants: list[str]
    album_variants: list[str]
    title_surface_variants: list[str]
    artist_surface_variants: list[str]
    alias_variants: list[str]
    combined_variants: list[str]
    document: str
    vector: list[float] = field(default_factory=list)


class LibraryIndex:
    """An in-memory local track index with optional semantic reranking.

    ``executor`` accepts Home Assistant's ``hass.async_add_executor_job`` shape
    (or any callable that accepts a function and its positional arguments).  If
    it is omitted, CPU-heavy normalization runs via :func:`asyncio.to_thread`.
    """

    def __init__(
        self,
        normalizer: Normalizer | None = None,
        *,
        embedder: Embedder | Any | None = None,
        aliases: Mapping[str, Sequence[str]] | None = None,
        executor: ExecutorCallback | None = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        embedding_weight: float = EMBEDDING_WEIGHT,
        autoplay_min_score: float = AUTOPLAY_MIN_SCORE,
        autoplay_min_margin: float = AUTOPLAY_MIN_MARGIN,
        semantic_autoplay_min_score: float = SEMANTIC_AUTOPLAY_MIN_SCORE,
        semantic_autoplay_min_margin: float = SEMANTIC_AUTOPLAY_MIN_MARGIN,
    ) -> None:
        """Create an initially empty index and validate local score settings."""
        self.normalizer = normalizer or Normalizer()
        self.embedder = embedder
        self.aliases = {
            str(key): [str(item) for item in values] for key, values in (aliases or {}).items()
        }
        self.executor = executor
        self.candidate_limit = max(1, int(candidate_limit))
        self.embedding_weight = float(embedding_weight)
        self.autoplay_min_score = float(autoplay_min_score)
        self.autoplay_min_margin = float(autoplay_min_margin)
        self.semantic_autoplay_min_score = float(semantic_autoplay_min_score)
        self.semantic_autoplay_min_margin = float(semantic_autoplay_min_margin)
        self._tracks: list[_IndexedTrack] = []
        self._model_id = _embedder_model_id(embedder)
        self.embedding_error = ""

    @property
    def tracks(self) -> tuple[dict[str, Any], ...]:
        """Return metadata snapshots without exposing derived mutable entries."""
        return tuple(dict(entry.track) for entry in self._tracks)

    @property
    def track_count(self) -> int:
        """Return the number of indexed tracks without serializing vectors."""
        return len(self._tracks)

    @property
    def embedded_count(self) -> int:
        """Return the number of tracks with semantic vectors."""
        return sum(1 for entry in self._tracks if entry.vector)

    @property
    def model_id(self) -> str:
        """Return the model identity associated with stored document vectors."""
        return self._model_id

    async def async_build(
        self,
        tracks: Sequence[Track | Mapping[str, Any]],
        embedder: Embedder | Any | None = None,
        reuse: LibraryIndex | None = None,
    ) -> None:
        """Build normalized entries and, when configured, batch-embed documents.

        Track normalization is CPU-oriented and therefore always dispatched to
        the injected executor or ``asyncio.to_thread``.  A failed embedding
        request leaves a fully usable lexical index rather than failing sync.
        """
        if embedder is not None:
            self.embedder = embedder
        self.embedding_error = ""
        self._model_id = _embedder_model_id(self.embedder)
        raw_tracks = [_track_to_dict(track) for track in tracks]
        entries = await self._run_cpu(self._build_entries, raw_tracks)

        if reuse is not None and reuse.model_id == self._model_id:
            await self._run_cpu(_reuse_entry_vectors, entries, reuse._tracks)

        pending = [entry for entry in entries if not entry.vector]
        if self.embedder is not None and pending:
            try:
                vectors: list[list[float]] = []
                for offset in range(0, len(pending), EMBEDDING_BATCH_SIZE):
                    batch = pending[offset : offset + EMBEDDING_BATCH_SIZE]
                    raw_vectors = await _embed_documents(
                        self.embedder,
                        [entry.document for entry in batch],
                    )
                    normalized_batch = await self._run_cpu(
                        _validate_and_normalize_vectors,
                        raw_vectors,
                        len(batch),
                    )
                    if vectors and normalized_batch and len(vectors[0]) != len(normalized_batch[0]):
                        raise ValueError("embedding batches have inconsistent vector dimensions")
                    vectors.extend(normalized_batch)
                for entry, vector in zip(pending, vectors, strict=True):
                    entry.vector = vector
            except Exception:
                # Semantic matching is strictly optional.  Do not retain a
                # partial batch if a provider sends malformed data or fails.
                self.embedding_error = (
                    "Embedding provider is unavailable or returned invalid vectors"
                )
                for entry in pending:
                    entry.vector = []
        self._tracks = entries

    async def search(self, query: str, limit: int | None = None) -> dict[str, Any]:
        """Rank tracks and return confidence, ambiguity, and evidence fields."""
        scored = await self._score_query(query)
        scored.sort(
            key=lambda item: (
                -item[1],
                -item[3],
                str(item[0].get("title", "")),
                str(item[0].get("id", "")),
            )
        )
        if not scored:
            return _empty_result("no_candidate")

        semantic_margin = scored[0][3]
        for item in scored[1:]:
            semantic_margin = min(semantic_margin, scored[0][3] - item[3])

        effective_limit = self.candidate_limit if limit is None or limit <= 0 else int(limit)
        candidates = [item[0] for item in scored[:effective_limit]]
        top = scored[0][1]
        margin = top if len(scored) == 1 else top - scored[1][1]
        lexical = _round_score(scored[0][2])
        semantic = _round_score(scored[0][3])
        confidence = _round_score(top)
        margin_value = _round_score(margin)
        semantic_margin_value = _round_score(semantic_margin)
        evidence = candidates[0]["evidence"]
        strong_exact = "title_artist_exact" in evidence or "track_alias_exact" in evidence
        lexical_automatic = lexical >= self.autoplay_min_score and (
            margin_value >= self.autoplay_min_margin or strong_exact
        )
        semantic_automatic = (
            semantic > 0
            and lexical < self.autoplay_min_score
            and semantic >= self.semantic_autoplay_min_score
            and semantic_margin_value >= self.semantic_autoplay_min_margin
        )
        automatic = lexical_automatic or semantic_automatic
        reason = "low_confidence"
        if semantic_automatic:
            reason = "confident_semantic_match"
        elif automatic:
            reason = "confident_match"
        elif semantic >= self.semantic_autoplay_min_score:
            reason = "ambiguous_semantic_match"
        elif confidence >= self.autoplay_min_score:
            reason = "ambiguous_match"
        return {
            "candidates": candidates,
            "confidence": confidence,
            "margin": margin_value,
            "semantic_confidence": semantic,
            "semantic_margin": semantic_margin_value,
            "automatic": automatic,
            "reason": reason,
        }

    async def _score_query(self, query: str) -> list[tuple[dict[str, Any], float, float, float]]:
        """Calculate lexical and semantic scores before sorting and confidence policy."""
        query_variants, query_surface = await self._run_cpu(self._query_variants, str(query))
        query_vector: list[float] = []
        if self.embedder is not None and self._tracks:
            try:
                query_vector = _normalise_vector(await _embed_query(self.embedder, str(query)))
                if self.embedded_count:
                    self.embedding_error = ""
            except Exception:
                # The normal lexical result is intentionally the fallback.
                self.embedding_error = (
                    "Embedding provider is unavailable or returned invalid vectors"
                )
                query_vector = []

        return await self._run_cpu(
            self._score_entries,
            query_variants,
            query_surface,
            query_vector,
        )

    def _score_entries(
        self,
        query_variants: Sequence[str],
        query_surface: Sequence[str],
        query_vector: Sequence[float],
    ) -> list[tuple[dict[str, Any], float, float, float]]:
        """Score the complete index in a worker thread."""
        scored: list[tuple[dict[str, Any], float, float, float]] = []
        for entry in self._tracks:
            lexical, evidence = _lexical_score(query_variants, query_surface, entry)
            semantic = 0.0
            if query_vector and len(query_vector) == len(entry.vector):
                semantic = max(0.0, min(1.0, _dot(query_vector, entry.vector)))
                if semantic > SEMANTIC_EVIDENCE_MIN_SCORE:
                    evidence.append("embedding")
            combined = lexical
            if semantic > 0:
                combined = max(
                    lexical,
                    lexical * (1.0 - self.embedding_weight) + semantic * self.embedding_weight,
                )
                if lexical < SEMANTIC_LEXICAL_OVERRIDE_MAX:
                    combined = max(combined, semantic)
            if combined < MIN_CANDIDATE_SCORE:
                continue
            candidate = dict(entry.track)
            candidate["score"] = _round_score(combined)
            candidate["lexical_score"] = _round_score(lexical)
            candidate["semantic_score"] = _round_score(semantic)
            candidate["evidence"] = _deduplicate(evidence)
            scored.append((candidate, combined, lexical, semantic))
        return scored

    async_search = search

    def browse(
        self, query: str = "", offset: int = 0, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a stable, paginated lexical library view without embedding calls."""
        offset = max(0, int(offset))
        limit = 50 if limit <= 0 else int(limit)
        query_variants = self.normalizer.variants(str(query))
        items: list[dict[str, Any]] = []
        for entry in self._tracks:
            if query_variants and not _browse_match(query_variants, entry):
                continue
            item = dict(entry.track)
            item["score"] = 0.0
            item["lexical_score"] = 0.0
            item["semantic_score"] = 0.0
            item["evidence"] = []
            items.append(item)
        items.sort(
            key=lambda item: (
                self.normalizer.key(f"{item.get('title', '')} {item.get('artist', '')}"),
                str(item.get("id", "")),
            )
        )
        total = len(items)
        return (items[offset : offset + limit], total) if offset < total else ([], total)

    def rank_playlists(
        self, query: str, playlists: Sequence[Playlist | Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Rank playlist names by the same exact, contained, and fuzzy variants."""
        query_variants = self.normalizer.variants(str(query))
        ranked: list[dict[str, Any]] = []
        for playlist in playlists:
            item = _track_to_dict(playlist)
            name_variants = self.normalizer.variants(str(item.get("name", "")))
            best = 0.0
            for query_variant in query_variants:
                for name_variant in name_variants:
                    score = _similarity(query_variant, name_variant)
                    if query_variant == name_variant:
                        score = 1.0
                    elif query_variant in name_variant or name_variant in query_variant:
                        score = max(score, 0.9)
                    best = max(best, score)
            item["score"] = _round_score(best)
            ranked.append(item)
        ranked.sort(
            key=lambda item: (
                -float(item["score"]),
                str(item.get("name", "")),
                str(item.get("id", "")),
            )
        )
        return ranked

    def rank_tracks(
        self,
        query: str,
        tracks: Sequence[Track | Mapping[str, Any]],
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Lexically rank a transient server result set without semantic calls."""
        query_variants, query_surface = self._query_variants(str(query))
        scored: list[tuple[dict[str, Any], float]] = []
        for raw_track in tracks:
            entry = self._make_entry(_track_to_dict(raw_track))
            score, evidence = _lexical_score(query_variants, query_surface, entry)
            candidate = dict(entry.track)
            candidate["score"] = _round_score(score)
            candidate["lexical_score"] = _round_score(score)
            candidate["semantic_score"] = 0.0
            candidate["evidence"] = _deduplicate(evidence)
            scored.append((candidate, score))
        scored.sort(
            key=lambda item: (-item[1], str(item[0].get("title", "")), str(item[0].get("id", "")))
        )
        effective_limit = self.candidate_limit if limit is None or limit <= 0 else int(limit)
        candidates = [item[0] for item in scored[:effective_limit]]
        if not scored:
            return _empty_result("navidrome_fallback")
        confidence = _round_score(scored[0][1])
        margin = confidence if len(scored) == 1 else _round_score(scored[0][1] - scored[1][1])
        strong_exact = (
            "title_artist_exact" in candidates[0]["evidence"]
            or "track_alias_exact" in candidates[0]["evidence"]
        )
        automatic = confidence >= self.autoplay_min_score and (
            margin >= self.autoplay_min_margin or strong_exact
        )
        return {
            "candidates": candidates,
            "confidence": confidence,
            "margin": margin,
            "semantic_confidence": 0.0,
            "semantic_margin": 0.0,
            "automatic": automatic,
            "reason": "confident_navidrome_fallback" if automatic else "navidrome_fallback",
        }

    def to_storage(self) -> dict[str, Any]:
        """Serialize schema-1 metadata and document vectors for HA storage."""
        return {
            "schema": 1,
            "model": self._model_id,
            "embedding_error": self.embedding_error,
            "tracks": [
                {"track": dict(entry.track), "vector": list(entry.vector)} for entry in self._tracks
            ],
        }

    @classmethod
    def from_storage(
        cls,
        storage: Mapping[str, Any],
        *,
        normalizer: Normalizer | None = None,
        embedder: Embedder | Any | None = None,
        aliases: Mapping[str, Sequence[str]] | None = None,
        executor: ExecutorCallback | None = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        embedding_weight: float = EMBEDDING_WEIGHT,
        autoplay_min_score: float = AUTOPLAY_MIN_SCORE,
        autoplay_min_margin: float = AUTOPLAY_MIN_MARGIN,
        semantic_autoplay_min_score: float = SEMANTIC_AUTOPLAY_MIN_SCORE,
        semantic_autoplay_min_margin: float = SEMANTIC_AUTOPLAY_MIN_MARGIN,
    ) -> LibraryIndex:
        """Restore schema-1 entries, dropping vectors when the model changes."""
        if storage.get("schema") != 1:
            raise ValueError("unsupported library index storage schema")
        index = cls(
            normalizer,
            embedder=embedder,
            aliases=aliases,
            executor=executor,
            candidate_limit=candidate_limit,
            embedding_weight=embedding_weight,
            autoplay_min_score=autoplay_min_score,
            autoplay_min_margin=autoplay_min_margin,
            semantic_autoplay_min_score=semantic_autoplay_min_score,
            semantic_autoplay_min_margin=semantic_autoplay_min_margin,
        )
        stored_model = storage.get("model")
        if not isinstance(stored_model, str):
            stored_model = ""
        current_model = _embedder_model_id(embedder)
        use_vectors = not (embedder is not None and stored_model and stored_model != current_model)
        raw_entries = storage.get("tracks", [])
        if not isinstance(raw_entries, Sequence) or isinstance(
            raw_entries, (str, bytes, bytearray)
        ):
            raise ValueError("invalid library index tracks")
        entries: list[_IndexedTrack] = []
        for stored in raw_entries:
            if not isinstance(stored, Mapping):
                continue
            metadata = stored.get("track")
            if not isinstance(metadata, Mapping):
                continue
            entry = index._make_entry(dict(metadata))
            vector = stored.get("vector", []) if use_vectors else []
            if _is_vector(vector):
                entry.vector = [float(value) for value in vector]
            entries.append(entry)
        if entries:
            dimensions = {len(entry.vector) for entry in entries if entry.vector}
            if len(dimensions) > 1:
                for entry in entries:
                    entry.vector = []
        index._tracks = entries
        index._model_id = current_model if embedder is not None else stored_model
        if storage.get("embedding_error") == (
            "Embedding provider is unavailable or returned invalid vectors"
        ):
            index.embedding_error = str(storage["embedding_error"])
        return index

    async def _run_cpu(self, function: Callable[..., _T], *args: Any) -> _T:
        """Run CPU work through HA's executor callback or a worker thread."""
        if self.executor is None:
            return await asyncio.to_thread(function, *args)
        result = self.executor(function, *args)
        if inspect.isawaitable(result):
            return cast("_T", await result)
        return cast("_T", result)

    def _query_variants(self, query: str) -> tuple[list[str], list[str]]:
        """Compute all identity variants and safe same-script surface variants."""
        return self.normalizer.variants(query), self.normalizer.surface_variants(query)

    def _build_entries(self, tracks: Sequence[dict[str, Any]]) -> list[_IndexedTrack]:
        """Synchronously derive all index entries; called only off the event loop."""
        return [self._make_entry(track) for track in tracks]

    def _make_entry(self, track: dict[str, Any]) -> _IndexedTrack:
        """Derive lexical variants and an embedding document from one metadata row."""
        title = str(track.get("title", ""))
        artist = str(track.get("artist", ""))
        album = str(track.get("album", ""))
        aliases = self._aliases_for(track)
        combined: list[str] = []
        for value in (f"{title} {artist}", f"{artist} {title}"):
            combined.extend(self.normalizer.variants(value))
        alias_variants: list[str] = []
        for value in aliases:
            alias_variants.extend(self.normalizer.variants(value))
        document = f"title: {title} | artist: {artist} | album: {album}"
        if aliases:
            document += " | aliases: " + "; ".join(aliases)
        return _IndexedTrack(
            track=dict(track),
            title_variants=self.normalizer.variants(title),
            artist_variants=self.normalizer.variants(artist),
            album_variants=self.normalizer.variants(album),
            title_surface_variants=self.normalizer.surface_variants(title),
            artist_surface_variants=self.normalizer.surface_variants(artist),
            alias_variants=_unique_sorted(alias_variants),
            combined_variants=_unique_sorted(combined),
            document=document,
        )

    def _aliases_for(self, track: Mapping[str, Any]) -> list[str]:
        """Collect optional configured and per-track aliases without requiring them."""
        values: list[str] = list(self.aliases.get(str(track.get("id", "")), []))
        raw_aliases = track.get("aliases", [])
        if isinstance(raw_aliases, str):
            values.append(raw_aliases)
        elif isinstance(raw_aliases, Sequence):
            values.extend(str(item) for item in raw_aliases)
        return _unique_sorted(values)


def _lexical_score(
    query_variants: Sequence[str], query_surface_variants: Sequence[str], entry: _IndexedTrack
) -> tuple[float, list[str]]:
    """Apply lexical precedence and score constants without transliteration contains."""
    best = 0.0
    evidence: list[str] = []
    for query in query_variants:
        if query in entry.combined_variants:
            best = max(best, 0.99)
            evidence.append("title_artist_exact")
        if query in entry.alias_variants:
            best = max(best, 1.0)
            evidence.append("track_alias_exact")
        if query in entry.title_variants:
            best = max(best, 0.94)
            evidence.append("title_exact")
        for candidate in entry.title_variants:
            score = _similarity(query, candidate) * 0.88
            if score > best:
                best = score
                evidence.append("title_fuzzy")
        for candidate in entry.combined_variants:
            score = _similarity(query, candidate) * 0.84
            if score > best:
                best = score
                evidence.append("combined_fuzzy")
    for query in query_surface_variants:
        artist_present = _any_contained(query, entry.artist_surface_variants)
        title_present = _any_contained(query, entry.title_surface_variants)
        if artist_present and title_present:
            best = max(best, 0.98)
            evidence.append("title_artist_contained")
        elif title_present:
            best = max(best, 0.86)
            evidence.append("title_contained")
        elif artist_present:
            best = max(best, 0.72)
            evidence.append("artist_contained")
    return min(1.0, best), evidence


def _browse_match(query_variants: Sequence[str], entry: _IndexedTrack) -> bool:
    """Test whether a normalized browse query is contained by any indexed field."""
    fields = (
        entry.title_variants,
        entry.artist_variants,
        entry.album_variants,
        entry.alias_variants,
        entry.combined_variants,
    )
    return any(
        query in candidate for query in query_variants for field in fields for candidate in field
    )


def _any_contained(query: str, values: Sequence[str]) -> bool:
    """Apply conservative substring lengths to surface-script evidence only."""
    for value in values:
        if not value:
            continue
        minimum = 2
        if _contains_han_or_kana(value) and len(value) == 1:
            minimum = 1
        elif value.isascii() and value.isalnum():
            minimum = 3
        if len(value) >= minimum and value in query:
            return True
    return False


def _contains_han_or_kana(value: str) -> bool:
    """Return whether a key includes a CJK Han, Hiragana, or Katakana code point."""
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\u3040" <= character <= "\u309f"
        or "\u30a0" <= character <= "\u30ff"
        for character in value
    )


def _similarity(left: str, right: str) -> float:
    """Return normalized pure-Python Levenshtein similarity for Unicode strings."""
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    return 1.0 - (_levenshtein(left, right) / max(len(left), len(right)))


def _levenshtein(left: str, right: str) -> int:
    """Compute Levenshtein edit distance using two Python integer rows."""
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, right_character in enumerate(right, start=1):
        current = [row]
        for column, left_character in enumerate(left, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _track_to_dict(value: Track | Playlist | Mapping[str, Any] | Any) -> dict[str, Any]:
    """Copy a model's public serialization or mapping without mutating its object."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    serializer = getattr(value, "to_dict", None)
    if callable(serializer):
        serialized = serializer()
        if isinstance(serialized, Mapping):
            return {str(key): item for key, item in serialized.items()}
    annotations = getattr(type(value), "__annotations__", {})
    if isinstance(annotations, Mapping):
        result = {str(name): getattr(value, name) for name in annotations if hasattr(value, name)}
        if result:
            return result
    raise TypeError("track and playlist values must be mappings or provide to_dict()")


def _embedder_model_id(embedder: Any | None) -> str:
    """Read an embedder model identifier while supporting a property or method."""
    if embedder is None:
        return ""
    for name in ("model_id", "model"):
        value = getattr(embedder, name, None)
        if callable(value):
            value = value()
        if isinstance(value, str) and value:
            return value
    return ""


async def _embed_documents(embedder: Any, values: Sequence[str]) -> list[list[float]]:
    """Call a document embedder without copying every vector on the event loop."""
    method = getattr(embedder, "embed_documents", None)
    if not callable(method):
        raise TypeError("embedder does not provide embed_documents")
    result = method(values)
    if inspect.isawaitable(result):
        result = await result
    return list(result)


async def _embed_query(embedder: Any, value: str) -> list[float]:
    """Call the query embedder method and materialize its vector."""
    method = getattr(embedder, "embed_query", None)
    if not callable(method):
        raise TypeError("embedder does not provide embed_query")
    result = method(value)
    if inspect.isawaitable(result):
        result = await result
    return list(result)


def _validate_and_normalize_vectors(
    vectors: Sequence[Sequence[float]], expected_count: int
) -> list[list[float]]:
    """Validate and normalize one bounded provider batch in a worker thread."""
    if len(vectors) != expected_count:
        raise ValueError(
            f"embedding batch returned {len(vectors)} vectors for {expected_count} documents"
        )
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1 or not dimensions or 0 in dimensions:
        raise ValueError("embedding batch has empty or inconsistent vector dimensions")
    return [_normalise_vector(vector) for vector in vectors]


def _reuse_entry_vectors(entries: list[_IndexedTrack], old_entries: list[_IndexedTrack]) -> None:
    """Copy reusable vectors into a fresh index away from the event loop."""
    reusable = {
        (str(entry.track.get("id", "")), entry.document): entry.vector
        for entry in old_entries
        if entry.vector
    }
    for entry in entries:
        if vector := reusable.get((str(entry.track.get("id", "")), entry.document)):
            entry.vector = list(vector)


def _is_vector(value: Any) -> bool:
    """Return whether storage holds a finite non-empty numeric vector."""
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and bool(value)
        and all(isinstance(item, (float, int)) and math.isfinite(float(item)) for item in value)
    )


def _normalise_vector(vector: Sequence[float]) -> list[float]:
    """Return a fresh L2-normalized finite vector, rejecting a zero norm."""
    result = [float(value) for value in vector]
    if not result or any(not math.isfinite(value) for value in result):
        raise ValueError("embedding vector must be finite and non-empty")
    norm = math.sqrt(sum(value * value for value in result))
    if norm == 0:
        raise ValueError("embedding vector has zero L2 norm")
    return [value / norm for value in result]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    """Return the dot product of equal-length normalized vectors."""
    return sum(a * b for a, b in zip(left, right, strict=True))


def _unique_sorted(values: Sequence[str] | Any) -> list[str]:
    """Normalize a string iterable to sorted, non-empty, unique values."""
    return sorted({str(value) for value in values if str(value)})


def _deduplicate(values: Sequence[str]) -> list[str]:
    """Return evidence in first-seen order."""
    return list(dict.fromkeys(values))


def _round_score(value: float) -> float:
    """Round score values to three decimal places."""
    return round(value + 1e-12, 3)


def _empty_result(reason: str) -> dict[str, Any]:
    """Create the stable empty-result response shape."""
    return {
        "candidates": [],
        "confidence": 0.0,
        "margin": 0.0,
        "semantic_confidence": 0.0,
        "semantic_margin": 0.0,
        "automatic": False,
        "reason": reason,
    }


# Public helpers are intentionally available for direct, deterministic tests.
levenshtein = _levenshtein
similarity = _similarity
