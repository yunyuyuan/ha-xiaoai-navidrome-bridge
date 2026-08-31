"""Runtime orchestration for the XiaoAI Navidrome integration."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.const import ATTR_FRIENDLY_NAME, EVENT_STATE_CHANGED
from homeassistant.core import Context, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTOPLAY_MIN_MARGIN,
    CONF_AUTOPLAY_MIN_SCORE,
    CONF_CONVERSATION_SENSOR,
    CONF_EMBEDDING_API_KEY,
    CONF_EMBEDDING_ENABLED,
    CONF_EMBEDDING_MODEL,
    CONF_EMBEDDING_PROVIDER,
    CONF_EMBEDDING_URL,
    CONF_EMBEDDING_WEIGHT,
    CONF_INDEX_REFRESH_MINUTES,
    CONF_MAX_BIT_RATE,
    CONF_MEDIA_PLAYER,
    CONF_NAVIDROME_URL,
    CONF_PASSWORD,
    CONF_PLAYLIST_GAP_SECONDS,
    CONF_PLAYLIST_PHRASE,
    CONF_QUEUE_MAX_TRACKS,
    CONF_SEMANTIC_AUTOPLAY_MIN_MARGIN,
    CONF_SEMANTIC_AUTOPLAY_MIN_SCORE,
    CONF_SHARE_TTL_HOURS,
    CONF_SHARE_URL,
    CONF_TRACK_PHRASE,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_AUTOPLAY_MIN_MARGIN,
    DEFAULT_AUTOPLAY_MIN_SCORE,
    DEFAULT_EMBEDDING_ENABLED,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDING_WEIGHT,
    DEFAULT_INDEX_REFRESH_MINUTES,
    DEFAULT_MAX_BIT_RATE,
    DEFAULT_PLAYLIST_GAP_SECONDS,
    DEFAULT_PLAYLIST_PHRASE,
    DEFAULT_QUEUE_MAX_TRACKS,
    DEFAULT_SEMANTIC_AUTOPLAY_MIN_MARGIN,
    DEFAULT_SEMANTIC_AUTOPLAY_MIN_SCORE,
    DEFAULT_SHARE_TTL_HOURS,
    DEFAULT_TRACK_PHRASE,
    DEFAULT_VERIFY_SSL,
    INDEX_STORAGE_VERSION,
    STORAGE_KEY_PREFIX,
    VERSION,
)
from .embedder import HTTPEmbedder
from .matcher import LibraryIndex
from .model import (
    NavidromeAuthError,
    NavidromeConnectionError,
    NavidromeError,
    Playlist,
    Track,
)
from .navidrome import NavidromeClient
from .queue import PlaybackQueue, QueueError
from .voice import VoiceCommand, parse_voice_command

_LOGGER = logging.getLogger(__name__)
PLAYLIST_CACHE_SECONDS = 30
PLAYLIST_MIN_SCORE = 0.15
VOICE_DEBOUNCE_SECONDS = 5
VOICE_EVENT_TTL_SECONDS = 120


class MatchError(HomeAssistantError):
    """Raised when a spoken request has no unambiguous match."""


def _voice_error_category(err: Exception) -> str:
    """Classify a voice failure without exposing exception text."""
    current: BaseException | None = err
    while current is not None:
        if isinstance(current, MatchError):
            return "matching"
        if isinstance(current, NavidromeAuthError):
            return "authentication"
        if isinstance(current, NavidromeConnectionError):
            return "connection"
        if isinstance(current, NavidromeError):
            return "protocol"
        if isinstance(current, QueueError):
            return "playback"
        current = current.__cause__
    return "home_assistant"


class XiaoAINavidromeRuntime:
    """Coordinate Navidrome, matching, queue persistence and HA events."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        """Create a runtime from one config entry."""
        self.hass = hass
        self.entry = entry
        self.options = dict(entry.options)
        self.navidrome = NavidromeClient(
            session=async_get_clientsession(hass),
            base_url=entry.data[CONF_NAVIDROME_URL],
            share_url=entry.data.get(CONF_SHARE_URL),
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        )
        self._embedding_configuration_error = ""
        self.embedder = self._create_embedder()
        self.index = self._new_index()
        self.queue = PlaybackQueue(
            hass,
            entry.entry_id,
            self.navidrome,
            media_player=str(self.options.get(CONF_MEDIA_PLAYER, "")),
            max_tracks=int(self.options.get(CONF_QUEUE_MAX_TRACKS, DEFAULT_QUEUE_MAX_TRACKS)),
            max_bit_rate=int(self.options.get(CONF_MAX_BIT_RATE, DEFAULT_MAX_BIT_RATE)),
            share_ttl=timedelta(
                hours=int(self.options.get(CONF_SHARE_TTL_HOURS, DEFAULT_SHARE_TTL_HOURS))
            ),
            gap_seconds=int(
                self.options.get(CONF_PLAYLIST_GAP_SECONDS, DEFAULT_PLAYLIST_GAP_SECONDS)
            ),
            create_background_task=partial(entry.async_create_background_task, hass),
        )
        self._index_store: Store[dict[str, Any]] = Store(
            hass,
            INDEX_STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{entry.entry_id}.index",
            private=True,
            atomic_writes=True,
            serialize_in_event_loop=False,
        )
        self._sync_lock = asyncio.Lock()
        self._syncing = False
        self._last_sync = ""
        self._last_error = self._embedding_configuration_error
        self._sync_task: asyncio.Task[None] | None = None
        self._sync_callers: set[asyncio.Task[Any]] = set()
        self._closing = False
        self._closed = False
        self._playlists_cache: tuple[float, list[Playlist]] = (0.0, [])
        self._last_voice_signature = ""
        self._last_voice_at = 0.0
        self._processed_voice_events: dict[str, float] = {}

    def _index_options(self) -> dict[str, Any]:
        """Return one canonical set of matcher options for build and restore."""
        return {
            "embedder": self.embedder,
            "executor": self.hass.async_add_executor_job,
            "autoplay_min_score": float(
                self.options.get(CONF_AUTOPLAY_MIN_SCORE, DEFAULT_AUTOPLAY_MIN_SCORE)
            ),
            "autoplay_min_margin": float(
                self.options.get(CONF_AUTOPLAY_MIN_MARGIN, DEFAULT_AUTOPLAY_MIN_MARGIN)
            ),
            "embedding_weight": float(
                self.options.get(CONF_EMBEDDING_WEIGHT, DEFAULT_EMBEDDING_WEIGHT)
            ),
            "semantic_autoplay_min_score": float(
                self.options.get(
                    CONF_SEMANTIC_AUTOPLAY_MIN_SCORE,
                    DEFAULT_SEMANTIC_AUTOPLAY_MIN_SCORE,
                )
            ),
            "semantic_autoplay_min_margin": float(
                self.options.get(
                    CONF_SEMANTIC_AUTOPLAY_MIN_MARGIN,
                    DEFAULT_SEMANTIC_AUTOPLAY_MIN_MARGIN,
                )
            ),
        }

    def _new_index(self) -> LibraryIndex:
        """Create an empty index using the active Config Entry options."""
        return LibraryIndex(**self._index_options())

    def _create_embedder(self) -> HTTPEmbedder | None:
        """Create an optional HTTP embedder from options."""
        if not self.options.get(CONF_EMBEDDING_ENABLED, DEFAULT_EMBEDDING_ENABLED):
            return None
        url = str(self.options.get(CONF_EMBEDDING_URL, "")).strip()
        if not url:
            self._embedding_configuration_error = (
                "Embedding is enabled but no provider URL is configured"
            )
            _LOGGER.warning("Semantic matching is enabled but no embedding URL is configured")
            return None
        try:
            return HTTPEmbedder(
                url,
                str(self.options.get(CONF_EMBEDDING_PROVIDER, DEFAULT_EMBEDDING_PROVIDER)),
                str(self.options.get(CONF_EMBEDDING_MODEL, DEFAULT_EMBEDDING_MODEL)),
                str(self.options.get(CONF_EMBEDDING_API_KEY, "")),
                session=async_get_clientsession(self.hass),
                timeout=90,
            )
        except ValueError as err:
            self._embedding_configuration_error = "Embedding configuration is invalid"
            _LOGGER.warning("Invalid embedding configuration: %s", err)
            return None

    async def async_setup(self) -> None:
        """Load persistent state, register event listeners and start safe sync work."""
        await self.navidrome.async_ping()
        await self._async_restore_index()
        await self.queue.async_load()

        conversation_sensor = self.options.get(CONF_CONVERSATION_SENSOR)
        if conversation_sensor:
            self.entry.async_on_unload(
                async_track_state_change_event(
                    self.hass,
                    [conversation_sensor],
                    self._async_conversation_changed,
                )
            )
        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_player_changed)
        )
        refresh = timedelta(
            minutes=int(self.options.get(CONF_INDEX_REFRESH_MINUTES, DEFAULT_INDEX_REFRESH_MINUTES))
        )
        self.entry.async_on_unload(
            async_track_time_interval(self.hass, self._async_periodic_sync, refresh)
        )
        self._sync_task = self.entry.async_create_background_task(
            self.hass,
            self._async_background_sync(),
            f"{self.entry.entry_id} XiaoAI Navidrome initial index sync",
        )

    async def async_close(self) -> None:
        """Cancel owned work and stop the queue on config-entry unload."""
        self._closing = True
        task = self._sync_task
        self._sync_task = None
        sync_tasks = set(self._sync_callers)
        if task is not None:
            sync_tasks.add(task)
        current = asyncio.current_task()
        sync_tasks.discard(current)
        for sync_task in sync_tasks:
            if not sync_task.done():
                sync_task.cancel()
        if sync_tasks:
            await asyncio.gather(*sync_tasks, return_exceptions=True)
        await self.queue.async_close()
        self._closed = True

    async def _async_restore_index(self) -> None:
        """Restore the serialized index without blocking Home Assistant's event loop."""
        stored = await self._index_store.async_load()
        if not stored:
            return
        try:
            self.index = await self.hass.async_add_executor_job(
                partial(
                    LibraryIndex.from_storage,
                    stored,
                    **self._index_options(),
                )
            )
            self._last_sync = str(stored.get("last_sync", ""))
            self._last_error = self.index.embedding_error or self._embedding_configuration_error
        except (TypeError, ValueError) as err:
            _LOGGER.warning("Ignoring an invalid XiaoAI Navidrome index: %s", err)

    async def _async_background_sync(self) -> None:
        """Refresh the index while preserving restored data on failure."""
        try:
            await self.async_sync_library()
        except Exception:
            _LOGGER.exception("Unable to synchronize the XiaoAI Navidrome library")

    async def _async_periodic_sync(self, _now: datetime) -> None:
        """Run the configured periodic library synchronization."""
        if self._closing or self._closed or (self._sync_task and not self._sync_task.done()):
            return
        self._sync_task = self.entry.async_create_background_task(
            self.hass,
            self._async_background_sync(),
            f"{self.entry.entry_id} XiaoAI Navidrome periodic index sync",
        )

    async def async_sync_library(self) -> dict[str, Any]:
        """Build and persist a complete multilingual library index."""
        if self._closing or self._closed:
            raise HomeAssistantError("XiaoAI Navidrome is unloading")
        caller = asyncio.current_task()
        if caller is not None:
            self._sync_callers.add(caller)
        try:
            return await self._async_sync_library_locked()
        finally:
            if caller is not None:
                self._sync_callers.discard(caller)

    async def _async_sync_library_locked(self) -> dict[str, Any]:
        """Build and persist an index while participating in runtime shutdown."""
        if self._sync_lock.locked():
            return self.index_status()
        async with self._sync_lock:
            if self._closing or self._closed:
                raise HomeAssistantError("XiaoAI Navidrome is unloading")
            self._syncing = True
            self._last_error = ""
            try:
                tracks = await self.navidrome.async_all_tracks(500)
                fresh = self._new_index()
                await fresh.async_build(tracks, reuse=self.index)
                if self._closing or self._closed:
                    raise HomeAssistantError("XiaoAI Navidrome is unloading")
                synchronized = datetime.now(UTC).isoformat()
                payload = await self.hass.async_add_executor_job(fresh.to_storage)
                payload["last_sync"] = synchronized
                await self._async_save_index(payload)
                self.index = fresh
                self._last_sync = synchronized
                self._last_error = fresh.embedding_error or self._embedding_configuration_error
            except Exception as err:
                self._last_error = str(err)
                raise
            finally:
                self._syncing = False
        return self.index_status()

    async def _async_save_index(self, payload: dict[str, Any]) -> None:
        """Finish an executor-backed atomic Store write before honoring cancellation."""
        save_task = asyncio.create_task(
            self._index_store.async_save(payload),
            name=f"{self.entry.entry_id} XiaoAI Navidrome index Store write",
        )
        try:
            await asyncio.shield(save_task)
        except asyncio.CancelledError:
            try:
                await save_task
            except Exception:
                _LOGGER.exception("Unable to finish XiaoAI Navidrome index Store write")
            raise

    def index_status(self) -> dict[str, Any]:
        """Return the panel-safe index status."""
        return {
            "enabled": True,
            "ready": bool(self.index.track_count),
            "track_count": self.index.track_count,
            "embedded_count": self.index.embedded_count,
            "last_sync": self._last_sync,
            "last_error": self.index.embedding_error or self._last_error,
            "syncing": self._syncing,
        }

    def panel_config(self) -> dict[str, Any]:
        """Return non-secret panel configuration."""
        return {
            "version": VERSION,
            "entry_id": self.entry.entry_id,
            "index": self.index_status(),
            "voice_enabled": bool(self.options.get(CONF_CONVERSATION_SENSOR)),
            "direct_share_streams": True,
        }

    async def async_browse_tracks(self, query: str, offset: int, limit: int) -> dict[str, Any]:
        """Browse the local index."""
        items, total = await self.hass.async_add_executor_job(
            self.index.browse, query, offset, limit
        )
        return {"items": items, "total": total, "index": self.index_status()}

    async def _async_playlists(self, *, fresh: bool = False) -> list[Playlist]:
        """Return a short-lived playlist cache."""
        cached_at, playlists = self._playlists_cache
        if not fresh and playlists and time.monotonic() - cached_at < PLAYLIST_CACHE_SECONDS:
            return playlists
        playlists = await self.navidrome.async_playlists()
        self._playlists_cache = (time.monotonic(), playlists)
        return playlists

    async def async_browse_playlists(self, query: str, offset: int, limit: int) -> dict[str, Any]:
        """Browse and lexically rank playlists."""
        playlists = await self._async_playlists(fresh=True)
        if query:
            items = await self.hass.async_add_executor_job(
                self.index.rank_playlists, query, playlists
            )
            items = [item for item in items if float(item.get("score", 0)) >= PLAYLIST_MIN_SCORE]
        else:
            items = [playlist.to_dict() for playlist in playlists]
            items.sort(key=lambda item: str(item.get("name", "")).casefold())
        total = len(items)
        return {"items": items[offset : offset + limit], "total": total}

    async def async_playlist_tracks(
        self, playlist_id: str, offset: int, limit: int
    ) -> dict[str, Any]:
        """Browse a playlist while preserving Navidrome order."""
        tracks = await self.navidrome.async_playlist_tracks(playlist_id)
        return {
            "items": [track.to_dict() for track in tracks[offset : offset + limit]],
            "total": len(tracks),
        }

    def media_players(self) -> dict[str, Any]:
        """List media players that can play URLs and can be stopped safely."""
        items: list[dict[str, Any]] = []
        required_play = int(MediaPlayerEntityFeature.PLAY_MEDIA)
        supported_stop = int(MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.STOP)
        for state in self.hass.states.async_all("media_player"):
            features = int(state.attributes.get("supported_features", 0))
            if features & required_play == 0 or features & supported_stop == 0:
                continue
            player = self.queue.player_status(state.entity_id)
            items.append(
                {
                    **player,
                    "name": state.attributes.get(ATTR_FRIENDLY_NAME, state.entity_id),
                    "supports_play_media": True,
                }
            )
        items.sort(key=lambda item: str(item["name"]).casefold())
        return {"items": items, "selected": self.queue.media_player}

    async def async_add_track_ids(
        self,
        track_ids: list[str],
        position: str,
        *,
        expected_revision: int | None,
        context: Context | None,
    ) -> dict[str, Any]:
        """Resolve track IDs and mutate the playback queue."""
        if len(track_ids) > self.queue.max_tracks:
            raise HomeAssistantError(f"The queue limit is {self.queue.max_tracks} tracks")
        known = {
            str(item.get("id")): Track.from_dict(item)
            for item in self.index.tracks
            if item.get("id")
        }
        tracks = [
            known.get(track_id) or await self.navidrome.async_track(track_id)
            for track_id in track_ids
        ]
        try:
            if position == "replace":
                return await self.queue.async_replace(
                    tracks,
                    expected_revision=expected_revision,
                    context=context,
                )
            return await self.queue.async_add(
                tracks,
                position,
                expected_revision=expected_revision,
                context=context,
            )
        except QueueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_add_playlist(
        self,
        playlist_id: str,
        position: str,
        *,
        start_track_id: str = "",
        expected_revision: int | None,
        context: Context | None,
    ) -> dict[str, Any]:
        """Add a full playlist, optionally rotating the clicked item to the front."""
        tracks = await self.navidrome.async_playlist_tracks(playlist_id)
        if start_track_id:
            start = next(
                (index for index, item in enumerate(tracks) if item.id == start_track_id),
                -1,
            )
            if start >= 0:
                tracks = tracks[start:] + tracks[:start]
        try:
            if position == "replace":
                return await self.queue.async_replace(
                    tracks,
                    expected_revision=expected_revision,
                    context=context,
                )
            return await self.queue.async_add(
                tracks,
                position,
                expected_revision=expected_revision,
                context=context,
            )
        except QueueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_play_query(
        self,
        query: str,
        *,
        media_player: str | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Resolve one track query and replace the queue."""
        track, match = await self._async_match_track(query)
        try:
            queue = await self.queue.async_replace(
                [track], media_player=media_player, context=context
            )
        except QueueError as err:
            raise HomeAssistantError(str(err)) from err
        return {"queue": queue, "match": match}

    async def async_play_playlist_query(
        self,
        query: str,
        *,
        media_player: str | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Resolve one playlist query and replace the queue."""
        playlists = await self._async_playlists(fresh=True)
        ranked = await self.hass.async_add_executor_job(self.index.rank_playlists, query, playlists)
        if not ranked:
            raise MatchError("No matching playlist was found")
        top = float(ranked[0].get("score", 0))
        margin = top if len(ranked) == 1 else top - float(ranked[1].get("score", 0))
        if top < self.index.autoplay_min_score or (
            margin < self.index.autoplay_min_margin and top < 1
        ):
            raise MatchError("The playlist match is ambiguous")
        tracks = await self.navidrome.async_playlist_tracks(str(ranked[0]["id"]))
        try:
            queue = await self.queue.async_replace(
                tracks, media_player=media_player, context=context
            )
        except QueueError as err:
            raise HomeAssistantError(str(err)) from err
        return {
            "queue": queue,
            "match": {
                "playlist": ranked[0],
                "confidence": round(top, 3),
                "margin": round(margin, 3),
            },
        }

    async def _async_match_track(self, query: str) -> tuple[Track, dict[str, Any]]:
        """Use the local index, with a bounded Navidrome fallback before first sync."""
        if self.index.tracks:
            match = await self.index.search(query)
        else:
            tracks = await self.navidrome.async_search_tracks(query, 20)
            match = await self.hass.async_add_executor_job(
                self.index.rank_tracks, query, tracks, 20
            )
        candidates = match.get("candidates", [])
        if not candidates:
            raise MatchError("No matching track was found")
        if not match.get("automatic"):
            raise MatchError("The track match is ambiguous")
        return Track.from_dict(candidates[0]), match

    @callback
    def _async_conversation_changed(self, event: Event[Any]) -> None:
        """Schedule processing for a fresh conversation sensor state."""
        if self._closing or self._closed:
            return
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        event_identity = self._conversation_event_identity(new_state)
        if event_identity is None:
            return
        command = parse_voice_command(
            new_state.state,
            track_phrase=str(self.options.get(CONF_TRACK_PHRASE, DEFAULT_TRACK_PHRASE)),
            playlist_phrase=str(self.options.get(CONF_PLAYLIST_PHRASE, DEFAULT_PLAYLIST_PHRASE)),
        )
        if command is None:
            return
        signature = f"{command.action}\0{command.query}"
        now = time.monotonic()
        self._processed_voice_events = {
            key: seen_at
            for key, seen_at in self._processed_voice_events.items()
            if now - seen_at < VOICE_EVENT_TTL_SECONDS
        }
        if event_identity:
            if event_identity in self._processed_voice_events:
                return
            self._processed_voice_events[event_identity] = now
        else:
            if (
                signature == self._last_voice_signature
                and now - self._last_voice_at < VOICE_DEBOUNCE_SECONDS
            ):
                return
            self._last_voice_signature = signature
            self._last_voice_at = now
        self.entry.async_create_background_task(
            self.hass,
            self._async_execute_voice(command),
            f"{self.entry.entry_id} XiaoAI Navidrome voice command",
        )

    @staticmethod
    def _conversation_event_identity(state: State) -> str | None:
        """Return a stable event identity, or None when the timestamp is stale."""
        timestamp = state.attributes.get("timestamp")
        if timestamp:
            parsed = dt_util.parse_datetime(str(timestamp))
            if parsed and datetime.now(UTC) - dt_util.as_utc(parsed) > timedelta(seconds=60):
                return None
            if parsed:
                return f"timestamp:{dt_util.as_utc(parsed).isoformat()}"
        for key in ("conversation_id", "sequence"):
            value = state.attributes.get(key)
            if value is not None and str(value).strip():
                return f"{key}:{value!s}"
        return ""

    async def _async_execute_voice(self, command: VoiceCommand) -> None:
        """Execute one parsed command without any YAML automation."""
        try:
            if command.action == "play":
                await self.async_play_query(command.query)
            elif command.action == "play_playlist":
                await self.async_play_playlist_query(command.query)
            elif command.action == "previous":
                await self.queue.async_previous()
            elif command.action == "next":
                await self.queue.async_next()
            elif command.action == "stop":
                await self.queue.async_stop()
        except (MatchError, NavidromeError, QueueError, HomeAssistantError) as err:
            _LOGGER.warning(
                "Unable to handle XiaoAI Navidrome voice command (%s error)",
                _voice_error_category(err),
            )

    @callback
    def _async_player_changed(self, event: Event[Any]) -> None:
        """React to the selected media player's state changes without callbacks or polling."""
        if self._closing or self._closed:
            return
        entity_id = event.data.get("entity_id")
        if entity_id != self.queue.media_player:
            return
        old_state: State | None = event.data.get("old_state")
        new_state: State | None = event.data.get("new_state")
        if old_state is None or new_state is None:
            return
        self.entry.async_create_background_task(
            self.hass,
            self.queue.async_handle_player_state(
                entity_id,
                old_state.state,
                new_state.state,
                new_state.last_changed,
            ),
            f"{self.entry.entry_id} XiaoAI Navidrome player state sync",
        )
