"""Persistent playback queue managed inside Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import math
import random
from collections.abc import Callable, Coroutine, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.media_player.const import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_DURATION,
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_POSITION_UPDATED_AT,
    ATTR_MEDIA_SEEK_POSITION,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    MediaPlayerEntityFeature,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import EVENT_QUEUE_UPDATED, STORAGE_KEY_PREFIX, STORAGE_VERSION
from .model import (
    NavidromeAuthError,
    NavidromeConnectionError,
    NavidromeError,
    Track,
)
from .navidrome import NavidromeClient

_LOGGER = logging.getLogger(__name__)
SHARE_CLEANUP_INITIAL_DELAY = 60
SHARE_CLEANUP_MAX_DELAY = 3600

QueueListener = Callable[[dict[str, Any]], None]
TaskCreator = Callable[[Coroutine[Any, Any, Any], str], asyncio.Task[Any]]


class QueueError(Exception):
    """Base playback queue error."""


class QueueEmptyError(QueueError):
    """Raised when an operation needs a non-empty queue."""


class QueueFullError(QueueError):
    """Raised when an operation exceeds the configured queue limit."""


class QueuePlayerError(QueueError):
    """Raised when a compatible output is unavailable."""


class QueueConflictError(QueueError):
    """Raised when optimistic concurrency detects a stale client."""


class QueueClosedError(QueueError):
    """Raised when a mutation races with Config Entry unload."""


def _safe_playback_error(err: Exception) -> str:
    """Return a useful playback error without upstream paths or user data."""
    if isinstance(err, NavidromeAuthError):
        return "Navidrome authentication failed"
    if isinstance(err, NavidromeConnectionError):
        return "Unable to connect to Navidrome"
    if isinstance(err, NavidromeError):
        return "Navidrome returned an invalid playback response"
    if isinstance(err, QueueClosedError):
        return "The playback queue is unloading"
    if isinstance(err, HomeAssistantError):
        return "Home Assistant media player control failed"
    return "Playback operation failed"


class PlaybackQueue:
    """Own playback state, timers, shares, persistence and HA service calls."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        navidrome: NavidromeClient,
        *,
        media_player: str,
        max_tracks: int,
        max_bit_rate: int,
        share_ttl: timedelta,
        gap_seconds: int,
        create_background_task: TaskCreator | None = None,
    ) -> None:
        """Initialize the queue."""
        self.hass = hass
        self.entry_id = entry_id
        self.navidrome = navidrome
        self.max_tracks = max_tracks
        self.max_bit_rate = max_bit_rate
        self.share_ttl = share_ttl
        self.gap_seconds = gap_seconds
        self._create_background_task = create_background_task or hass.async_create_background_task
        self.items: list[Track] = []
        self.current_index = -1
        self.state = "stopped"
        self.shuffle = False
        self.repeat = "all"
        self.started_at: datetime | None = None
        self.ends_at: datetime | None = None
        self.last_error = ""
        self.revision = 0
        self._configured_media_player = media_player
        self.media_player = media_player
        self._active_output_player = ""
        self._loading_started_at: datetime | None = None
        self._operation_lock = asyncio.Lock()
        self._timer_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._share_cleanup_task: asyncio.Task[None] | None = None
        self._share_id = ""
        self._share_expires_at: datetime | None = None
        self._stream_ids: list[str] = []
        self._stream_urls: list[str] = []
        self._pending_share_deletions: set[str] = set()
        self._share_cleanup_delay = SHARE_CLEANUP_INITIAL_DELAY
        self._listeners: set[QueueListener] = set()
        self._closing = False
        self._closed = False
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{entry_id}.queue",
            private=True,
            atomic_writes=True,
        )

    async def async_load(self) -> None:
        """Load a previous queue, always stopped after a Home Assistant restart."""
        stored = await self._store.async_load()
        if not stored:
            await self._async_persist()
            return
        self.items = [Track.from_dict(item) for item in stored.get("items", [])]
        self.current_index = int(stored.get("current_index", -1))
        if not self.items:
            self.current_index = -1
        elif not 0 <= self.current_index < len(self.items):
            self.current_index = 0
        self.shuffle = bool(stored.get("shuffle", False))
        repeat = str(stored.get("repeat", "all"))
        self.repeat = repeat if repeat in {"all", "one"} else "all"
        stored_configured_player = str(stored.get("configured_media_player", ""))
        if stored_configured_player == self._configured_media_player:
            self.media_player = str(stored.get("media_player") or self.media_player)
        pending = stored.get("pending_share_deletions", [])
        if isinstance(pending, list):
            self._pending_share_deletions = {
                share_id for share_id in pending[:1000] if isinstance(share_id, str) and share_id
            }
        active_share = stored.get("active_share_id")
        if isinstance(active_share, str) and active_share:
            self._pending_share_deletions.add(active_share)
        self.revision = max(0, int(stored.get("revision", 0))) + 1
        self.state = "stopped"
        self.started_at = None
        self.ends_at = None
        self._loading_started_at = None
        self._active_output_player = ""
        self.last_error = ""
        await self._async_persist()
        self._schedule_share_cleanup()

    async def async_close(self) -> None:
        """Cancel background work and delete the temporary share."""
        self._closing = True
        async with self._operation_lock:
            if self._closed:
                return
            output_player = self._active_output_player
            self._cancel_timer()
            self._cancel_idle_confirmation()
            self._cancel_share_cleanup()
            if output_player:
                with suppress(Exception):
                    await self._async_stop_player(output_player, None)
            self._active_output_player = ""
            await self._async_delete_share(self._share_id)
            self._share_id = ""
            self._share_expires_at = None
            self._stream_ids = []
            self._stream_urls = []
            self.state = "stopped"
            self.started_at = None
            self.ends_at = None
            self._loading_started_at = None
            self._closed = True
            await self._async_persist()

    def add_listener(self, listener: QueueListener) -> Callable[[], None]:
        """Register a callback invoked after queue state changes."""
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    def status(self) -> dict[str, Any]:
        """Return a JSON-safe queue snapshot."""
        current = (
            self.items[self.current_index] if 0 <= self.current_index < len(self.items) else None
        )
        player = self.player_status()
        return {
            "enabled": True,
            "state": self.state,
            "items": [item.to_dict() for item in self.items],
            "current_index": self.current_index,
            "current": current.to_dict() if current else None,
            "shuffle": self.shuffle,
            "repeat": self.repeat,
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "ends_at": self.ends_at.isoformat() if self.ends_at else "",
            "last_error": self.last_error,
            "revision": self.revision,
            "media_player": self.media_player,
            "position": player["position"],
            "duration": player["duration"],
            "player": player,
        }

    def player_status(self, entity_id: str | None = None) -> dict[str, Any]:
        """Return non-sensitive state and capabilities for one media player."""
        target = entity_id or self.media_player
        state = self.hass.states.get(target) if target else None
        features = int(state.attributes.get("supported_features", 0)) if state else 0
        current = (
            self.items[self.current_index] if 0 <= self.current_index < len(self.items) else None
        )
        if target != self.media_player:
            current = None
        reported_duration = (
            self._positive_number(state.attributes.get(ATTR_MEDIA_DURATION) if state else None)
            if current
            else 0.0
        )
        duration = reported_duration or float(current.duration if current else 0)
        position = self._player_position(state) if current else 0.0
        if duration > 0:
            position = min(position, duration)
        volume = self._optional_number(
            state.attributes.get(ATTR_MEDIA_VOLUME_LEVEL) if state else None
        )
        return {
            "entity_id": target,
            "state": state.state if state else "unavailable",
            "supported_features": features,
            "supports_play": bool(features & MediaPlayerEntityFeature.PLAY),
            "supports_pause": bool(features & MediaPlayerEntityFeature.PAUSE),
            "supports_stop": bool(features & MediaPlayerEntityFeature.STOP),
            "supports_seek": bool(features & MediaPlayerEntityFeature.SEEK),
            "supports_volume_set": bool(features & MediaPlayerEntityFeature.VOLUME_SET),
            "supports_volume_mute": bool(features & MediaPlayerEntityFeature.VOLUME_MUTE),
            "volume_level": min(1.0, max(0.0, volume)) if volume is not None else None,
            "is_volume_muted": bool(state.attributes.get(ATTR_MEDIA_VOLUME_MUTED, False))
            if state
            else False,
            "position": max(0.0, position),
            "duration": max(0.0, duration),
        }

    async def async_replace(
        self,
        tracks: Sequence[Track],
        *,
        media_player: str | None = None,
        expected_revision: int | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Replace the queue and start its first item."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            self._validate_track_count(len(tracks))
            target_player = media_player or self.media_player
            if media_player:
                self._validate_player(media_player)
            if self._active_output_player and self._active_output_player != target_player:
                try:
                    await self._async_stop_player(self._active_output_player, context)
                except Exception as err:
                    raise QueuePlayerError(_safe_playback_error(err)) from err
                self._active_output_player = ""
            self.media_player = target_player
            self._require_player()
            self._cancel_timer()
            self._cancel_idle_confirmation()
            self.items = list(tracks)
            self._invalidate_stream_cache()
            if self.shuffle:
                random.SystemRandom().shuffle(self.items)
            self.current_index = 0
            self._set_loading()
            self.last_error = ""
            self._changed()
            await self._async_persist()
            return await self._async_play_current(context=context)

    async def async_add(
        self,
        tracks: Sequence[Track],
        position: str,
        *,
        expected_revision: int | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Insert tracks at the next or last position."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            if not tracks:
                raise QueueEmptyError("No tracks were supplied")
            self._validate_track_count(len(self.items) + len(tracks))
            if not self.items:
                self.items = list(tracks)
                self._invalidate_stream_cache()
                if self.shuffle:
                    random.SystemRandom().shuffle(self.items)
                self.current_index = 0
                self._set_loading()
                self._changed()
                await self._async_persist()
                return await self._async_play_current(context=context)
            insert_at = self.current_index + 1 if position == "next" else len(self.items)
            self.items[insert_at:insert_at] = tracks
            self._invalidate_stream_cache()
            if self.shuffle:
                self._shuffle_upcoming()
            self._changed()
            await self._async_persist()
            self._reschedule_timer_for_current()
            return self.status()

    async def async_play(
        self, *, expected_revision: int | None = None, context: Context | None = None
    ) -> dict[str, Any]:
        """Play the current queue item."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            if not self.items:
                raise QueueEmptyError("The playback queue is empty")
            self._require_player()
            if not 0 <= self.current_index < len(self.items):
                self.current_index = 0
            self._cancel_timer()
            player_state = self.hass.states.get(self.media_player)
            features = (
                int(player_state.attributes.get("supported_features", 0)) if player_state else 0
            )
            if (
                player_state is not None
                and player_state.state == "paused"
                and features & MediaPlayerEntityFeature.PLAY
            ):
                await self._async_player_service(
                    "media_play", {ATTR_ENTITY_ID: self.media_player}, context
                )
                now = datetime.now(UTC)
                position = self._player_position(player_state)
                duration = max(1, self.items[self.current_index].duration)
                self._active_output_player = self.media_player
                self.state = "playing"
                self.started_at = now - timedelta(seconds=min(position, duration))
                self.ends_at = now + timedelta(
                    seconds=max(1, duration - position) + self.gap_seconds
                )
                self._loading_started_at = now
                self.last_error = ""
                self._changed()
                await self._async_persist()
                self._schedule_timer(
                    max(1, math.ceil((self.ends_at - now).total_seconds())), self.revision
                )
                return self.status()
            self._set_loading()
            self.last_error = ""
            self._changed()
            await self._async_persist()
            return await self._async_play_current(context=context)

    async def async_stop(
        self, *, expected_revision: int | None = None, context: Context | None = None
    ) -> dict[str, Any]:
        """Stop the local timer before pausing or stopping the media player."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            if self.state not in {"playing", "loading"} and not self._active_output_player:
                return self.status()
            output_player = self._active_output_player or self.media_player
            self._set_stopped()
            self._changed()
            await self._async_persist()
            if output_player:
                try:
                    await self._async_stop_player(output_player, context)
                except Exception as err:
                    self.last_error = _safe_playback_error(err)
                    self._changed()
                    await self._async_persist()
                    raise QueuePlayerError(self.last_error) from err
                self._active_output_player = ""
            return self.status()

    async def async_clear(
        self, *, expected_revision: int | None = None, context: Context | None = None
    ) -> dict[str, Any]:
        """Stop playback and remove all queue items."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            player = self._active_output_player or self.media_player
            was_active = bool(self._active_output_player) or self.state in {"playing", "loading"}
            if was_active:
                self._set_stopped()
                self._changed()
                await self._async_persist()
                if player:
                    try:
                        await self._async_stop_player(player, context)
                    except Exception as err:
                        self.last_error = _safe_playback_error(err)
                        self._changed()
                        await self._async_persist()
                        raise QueuePlayerError(self.last_error) from err
                    self._active_output_player = ""
            self.items = []
            self.current_index = -1
            self.last_error = ""
            self._changed()
            await self._async_persist()
            await self._async_delete_share(self._share_id)
            self._share_id = ""
            self._share_expires_at = None
            self._stream_ids = []
            self._stream_urls = []
            return self.status()

    async def async_next(
        self,
        *,
        automatic: bool = False,
        expected_revision: int | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Advance to the next item."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            return await self._async_advance(1, automatic=automatic, context=context)

    async def async_previous(
        self, *, expected_revision: int | None = None, context: Context | None = None
    ) -> dict[str, Any]:
        """Move to the previous item."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            return await self._async_advance(-1, automatic=False, context=context)

    async def async_jump(
        self,
        index: int,
        *,
        expected_revision: int | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Play a queue item without changing the queue order."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            if not 0 <= index < len(self.items):
                raise QueueError("Queue index is out of range")
            self._require_player()
            self._cancel_timer()
            self.current_index = index
            self._set_loading()
            self.last_error = ""
            self._changed()
            await self._async_persist()
            return await self._async_play_current(context=context)

    async def async_set_options(
        self,
        *,
        shuffle: bool | None = None,
        repeat: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Update shuffle and repeat settings."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            if repeat is not None and repeat not in {"all", "one"}:
                raise QueueError("Repeat must be all or one")
            if shuffle is not None and shuffle != self.shuffle:
                self.shuffle = shuffle
                if shuffle:
                    self._shuffle_upcoming()
                    self._invalidate_stream_cache()
            if repeat is not None:
                self.repeat = repeat
            self._changed()
            await self._async_persist()
            self._reschedule_timer_for_current()
            return self.status()

    async def async_set_volume(
        self,
        volume_level: float,
        *,
        expected_revision: int | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Set the selected player's volume through Home Assistant."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            self._require_player()
            if not 0 <= volume_level <= 1:
                raise QueuePlayerError("Volume must be between 0 and 1")
            if not self.player_status()["supports_volume_set"]:
                raise QueuePlayerError("The selected media player does not support volume control")
            await self._async_player_service(
                "volume_set",
                {
                    ATTR_ENTITY_ID: self.media_player,
                    ATTR_MEDIA_VOLUME_LEVEL: volume_level,
                },
                context,
            )
            self._notify()
            return self.status()

    async def async_set_muted(
        self,
        is_muted: bool,
        *,
        expected_revision: int | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Mute or unmute the selected player through Home Assistant."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            self._require_player()
            if not self.player_status()["supports_volume_mute"]:
                raise QueuePlayerError("The selected media player does not support mute control")
            await self._async_player_service(
                "volume_mute",
                {
                    ATTR_ENTITY_ID: self.media_player,
                    ATTR_MEDIA_VOLUME_MUTED: is_muted,
                },
                context,
            )
            self._notify()
            return self.status()

    async def async_seek(
        self,
        position: float,
        *,
        expected_revision: int | None = None,
        context: Context | None = None,
    ) -> dict[str, Any]:
        """Seek the current track and keep automatic advancement aligned."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            self._require_player()
            if not 0 <= self.current_index < len(self.items):
                raise QueueEmptyError("The playback queue has no current item")
            if not self.player_status()["supports_seek"]:
                raise QueuePlayerError("The selected media player does not support seeking")
            duration = max(1, self.items[self.current_index].duration)
            target = min(max(0.0, position), float(duration))
            await self._async_player_service(
                "media_seek",
                {ATTR_ENTITY_ID: self.media_player, ATTR_MEDIA_SEEK_POSITION: target},
                context,
            )
            if self.state == "playing":
                now = datetime.now(UTC)
                self.started_at = now - timedelta(seconds=target)
                self.ends_at = now + timedelta(seconds=max(1, duration - target) + self.gap_seconds)
                self._changed()
                await self._async_persist()
                self._schedule_timer(
                    max(1, math.ceil((self.ends_at - now).total_seconds())), self.revision
                )
            else:
                self._notify()
            status = self.status()
            status["position"] = target
            status["player"]["position"] = target
            return status

    async def async_set_media_player(
        self, entity_id: str, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        """Persist the selected media player."""
        async with self._operation_lock:
            self._ensure_open()
            self._check_revision(expected_revision)
            self._validate_player(entity_id)
            if entity_id != self.media_player:
                old_player = self._active_output_player
                if old_player:
                    try:
                        await self._async_stop_player(old_player, None)
                    except Exception as err:
                        raise QueuePlayerError(_safe_playback_error(err)) from err
                    self._active_output_player = ""
                self._set_stopped()
                self.media_player = entity_id
                self._changed()
                await self._async_persist()
            return self.status()

    async def async_handle_player_state(
        self,
        entity_id: str,
        _old_state: str | None,
        new_state: str | None,
        changed_at: datetime,
    ) -> bool:
        """Synchronize external pause/stop state changes without polling."""
        if self._closing or self._closed or entity_id != self.media_player:
            return False
        if new_state in {"paused", "off", "standby", "unavailable"}:
            async with self._operation_lock:
                if (
                    self._closing
                    or self._closed
                    or self.state not in {"loading", "playing"}
                    or entity_id != self.media_player
                    or self._loading_started_at is None
                    or changed_at < self._loading_started_at
                ):
                    self._notify()
                    return False
                self._set_stopped()
                self._active_output_player = ""
                self._changed()
                await self._async_persist()
                return True
        if (
            new_state != "idle"
            or self.state != "playing"
            or self.started_at is None
            or changed_at < self.started_at
        ):
            self._notify()
            return False
        if self.ends_at is not None and self.ends_at - changed_at <= timedelta(seconds=30):
            self._notify()
            return False
        self._schedule_idle_confirmation(entity_id, self.revision)
        self._notify()
        return False

    async def _async_advance(
        self, direction: int, *, automatic: bool, context: Context | None
    ) -> dict[str, Any]:
        if not self.items:
            raise QueueEmptyError("The playback queue is empty")
        self._require_player()
        self._cancel_timer()
        next_index = self.current_index
        if not (automatic and self.repeat == "one"):
            next_index += direction
        if next_index >= len(self.items):
            if self.shuffle:
                previous_id = self.items[self.current_index].id
                random.SystemRandom().shuffle(self.items)
                self._invalidate_stream_cache()
                if len(self.items) > 1 and self.items[0].id == previous_id:
                    self.items[0], self.items[1] = self.items[1], self.items[0]
            next_index = 0
        if next_index < 0:
            next_index = len(self.items) - 1
        self.current_index = next_index
        self._set_loading()
        self.last_error = ""
        self._changed()
        await self._async_persist()
        return await self._async_play_current(context=context)

    async def _async_play_current(self, *, context: Context | None) -> dict[str, Any]:
        if not 0 <= self.current_index < len(self.items):
            raise QueueEmptyError("The playback queue has no current item")
        player = self.media_player
        self._require_player()
        old_share = self._share_id
        new_share = ""
        try:
            stream_ids, share_id, urls, new_share = await self._async_prepare_stream_urls()
            self._ensure_open()
            url = urls[self.current_index]
            self._active_output_player = player
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                "play_media",
                {
                    ATTR_ENTITY_ID: player,
                    ATTR_MEDIA_CONTENT_ID: url,
                    ATTR_MEDIA_CONTENT_TYPE: "audio/mpeg",
                },
                blocking=True,
                context=context,
            )
            self._ensure_open()
        except Exception as err:
            if new_share:
                await self._async_delete_share(new_share)
            self.state = "error"
            self.started_at = None
            self.ends_at = None
            self._loading_started_at = None
            self.last_error = _safe_playback_error(err)
            self._changed()
            await self._async_persist()
            raise QueuePlayerError(self.last_error) from err
        now = datetime.now(UTC)
        if new_share:
            self._share_id = share_id
            self._pending_share_deletions.discard(new_share)
            if old_share and old_share != share_id:
                self._pending_share_deletions.add(old_share)
            self._share_expires_at = now + self.share_ttl
            self._stream_ids = stream_ids
            self._stream_urls = urls
        duration = max(1, self.items[self.current_index].duration)
        self.state = "playing"
        self.started_at = now
        self.ends_at = now + timedelta(seconds=duration + self.gap_seconds)
        self.last_error = ""
        self._changed()
        await self._async_persist()
        self._schedule_timer(duration + self.gap_seconds, self.revision)
        if new_share and old_share and old_share != share_id:
            await self._async_delete_share(old_share)
        return self.status()

    async def _async_prepare_stream_urls(self) -> tuple[list[str], str, list[str], str]:
        """Reuse safe stream URLs or create and crash-protect a new share."""
        stream_ids = [track.id for track in self.items]
        reusable = (
            stream_ids == self._stream_ids
            and len(self._stream_urls) == len(stream_ids)
            and self._share_expires_at is not None
            and self._share_expires_at - datetime.now(UTC) > timedelta(minutes=5)
        )
        if reusable:
            return stream_ids, self._share_id, self._stream_urls, ""
        share_id, urls = await self.navidrome.async_create_stream_urls(
            stream_ids,
            max_bit_rate=self.max_bit_rate,
            ttl=self.share_ttl,
        )
        self._pending_share_deletions.add(share_id)
        await self._async_persist()
        return stream_ids, share_id, urls, share_id

    async def _async_stop_player(self, entity_id: str, context: Context | None) -> None:
        state = self.hass.states.get(entity_id)
        features = int(state.attributes.get("supported_features", 0)) if state else 0
        if features & MediaPlayerEntityFeature.PAUSE:
            service = "media_pause"
        elif features & MediaPlayerEntityFeature.STOP:
            service = "media_stop"
        else:
            raise QueuePlayerError("The selected media player supports neither pause nor stop")
        await self._async_player_service(service, {ATTR_ENTITY_ID: entity_id}, context)

    async def _async_player_service(
        self, service: str, data: dict[str, Any], context: Context | None
    ) -> None:
        """Call a media player service and expose only a fixed safe error."""
        try:
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                service,
                data,
                blocking=True,
                context=context,
            )
        except Exception as err:
            raise QueuePlayerError(_safe_playback_error(err)) from err

    def _schedule_timer(self, delay: int, revision: int) -> None:
        self._cancel_timer()
        self._timer_task = self._create_background_task(
            self._async_timer(delay, revision),
            f"{self.entry_id} XiaoAI Navidrome queue timer",
        )

    def _reschedule_timer_for_current(self) -> None:
        """Retain automatic advancement after a non-transport queue mutation."""
        if self.state != "playing" or self.ends_at is None:
            return
        remaining = max(1, math.ceil((self.ends_at - datetime.now(UTC)).total_seconds()))
        self._schedule_timer(remaining, self.revision)

    async def _async_timer(self, delay: int, revision: int) -> None:
        try:
            await asyncio.sleep(delay)
            if self.revision != revision or self.state != "playing":
                return
            await self.async_next(automatic=True, expected_revision=revision)
        except asyncio.CancelledError:
            raise
        except QueueConflictError, QueueClosedError:
            return
        except Exception:
            _LOGGER.exception("Unable to advance the XiaoAI Navidrome queue")

    def _schedule_idle_confirmation(self, entity_id: str, revision: int) -> None:
        self._cancel_idle_confirmation()
        self._idle_task = self._create_background_task(
            self._async_confirm_idle(entity_id, revision),
            f"{self.entry_id} XiaoAI Navidrome idle confirmation",
        )

    async def _async_confirm_idle(self, entity_id: str, revision: int) -> None:
        try:
            await asyncio.sleep(5)
            state = self.hass.states.get(entity_id)
            if state is None or state.state != "idle":
                return
            async with self._operation_lock:
                if (
                    self._closing
                    or self._closed
                    or self.revision != revision
                    or self.state != "playing"
                ):
                    return
                self._set_stopped()
                self._active_output_player = ""
                self._changed()
                await self._async_persist()
        except asyncio.CancelledError:
            raise

    def _set_loading(self) -> None:
        self._cancel_idle_confirmation()
        self.state = "loading"
        self.started_at = None
        self.ends_at = None
        self._loading_started_at = datetime.now(UTC)

    def _set_stopped(self) -> None:
        self._cancel_timer()
        self._cancel_idle_confirmation()
        self.state = "stopped"
        self.started_at = None
        self.ends_at = None
        self._loading_started_at = None

    def _cancel_timer(self) -> None:
        task = self._timer_task
        self._timer_task = None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def _cancel_idle_confirmation(self) -> None:
        task = self._idle_task
        self._idle_task = None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def _shuffle_upcoming(self) -> None:
        start = max(0, self.current_index + 1)
        upcoming = self.items[start:]
        random.SystemRandom().shuffle(upcoming)
        self.items[start:] = upcoming

    def _invalidate_stream_cache(self) -> None:
        """Force the next playback operation to create URLs for the new queue order."""
        self._stream_ids = []
        self._stream_urls = []
        self._share_expires_at = None

    def _check_revision(self, expected: int | None) -> None:
        if expected is not None and expected != self.revision:
            raise QueueConflictError("The queue changed; refresh it and retry")

    def _ensure_open(self) -> None:
        if self._closing or self._closed:
            raise QueueClosedError("The playback queue is unloading")

    def _validate_track_count(self, count: int) -> None:
        if count <= 0:
            raise QueueEmptyError("The playback queue is empty")
        if count > self.max_tracks:
            raise QueueFullError(f"The queue limit is {self.max_tracks} tracks")

    def _validate_player(self, entity_id: str) -> None:
        if not entity_id.startswith("media_player.") or self.hass.states.get(entity_id) is None:
            raise QueuePlayerError("Select an existing media_player entity")

    def _require_player(self) -> None:
        if not self.media_player:
            raise QueuePlayerError("Select a media player before playback")
        self._validate_player(self.media_player)

    @staticmethod
    def _optional_number(value: Any) -> float | None:
        """Return a finite float without accepting booleans."""
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except TypeError, ValueError:
            return None
        return number if math.isfinite(number) else None

    @classmethod
    def _positive_number(cls, value: Any) -> float:
        """Return a positive finite number or zero."""
        number = cls._optional_number(value)
        return number if number is not None and number > 0 else 0.0

    def _player_position(self, state: State | None) -> float:
        """Estimate current position from Home Assistant memory without polling."""
        position = self._optional_number(
            state.attributes.get(ATTR_MEDIA_POSITION) if state else None
        )
        if position is not None:
            if state is not None and state.state == "playing":
                updated_at = state.attributes.get(ATTR_MEDIA_POSITION_UPDATED_AT)
                if isinstance(updated_at, datetime):
                    position += max(
                        0.0, (datetime.now(UTC) - updated_at.astimezone(UTC)).total_seconds()
                    )
            return max(0.0, position)
        if self.state == "playing" and self.started_at is not None:
            return max(0.0, (datetime.now(UTC) - self.started_at).total_seconds())
        return 0.0

    def _notify(self) -> None:
        """Publish a snapshot without mutating the persistent queue revision."""
        status = self.status()
        self.hass.bus.async_fire(EVENT_QUEUE_UPDATED, {"entry_id": self.entry_id, "queue": status})
        for listener in tuple(self._listeners):
            listener(status)

    def _changed(self) -> None:
        self.revision += 1
        self._notify()

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {
                "items": [item.to_dict() for item in self.items],
                "current_index": self.current_index,
                "shuffle": self.shuffle,
                "repeat": self.repeat,
                "revision": self.revision,
                "media_player": self.media_player,
                "configured_media_player": self._configured_media_player,
                "active_share_id": self._share_id,
                "pending_share_deletions": sorted(self._pending_share_deletions),
            }
        )

    async def _async_delete_share(self, share_id: str) -> None:
        if not share_id:
            return
        self._pending_share_deletions.add(share_id)
        await self._async_persist()
        try:
            await self.navidrome.async_delete_share(share_id)
        except Exception:
            _LOGGER.debug("Unable to delete an expired Navidrome share")
            self._schedule_share_cleanup()
            return
        self._pending_share_deletions.discard(share_id)
        await self._async_persist()

    def _schedule_share_cleanup(self) -> None:
        if (
            not self._pending_share_deletions
            or self._closing
            or self._closed
            or (self._share_cleanup_task and not self._share_cleanup_task.done())
        ):
            return
        self._share_cleanup_task = self._create_background_task(
            self._async_retry_share_cleanup(),
            f"{self.entry_id} XiaoAI Navidrome share cleanup",
        )

    async def _async_retry_share_cleanup(self) -> None:
        try:
            await asyncio.sleep(self._share_cleanup_delay)
            async with self._operation_lock:
                if self._closing or self._closed:
                    return
                pending = tuple(self._pending_share_deletions)
                for share_id in pending:
                    try:
                        await self.navidrome.async_delete_share(share_id)
                    except Exception:
                        continue
                    self._pending_share_deletions.discard(share_id)
                await self._async_persist()
                if self._pending_share_deletions:
                    self._share_cleanup_delay = min(
                        self._share_cleanup_delay * 2,
                        SHARE_CLEANUP_MAX_DELAY,
                    )
                else:
                    self._share_cleanup_delay = SHARE_CLEANUP_INITIAL_DELAY
        except asyncio.CancelledError:
            raise
        finally:
            self._share_cleanup_task = None
            self._schedule_share_cleanup()

    def _cancel_share_cleanup(self) -> None:
        task = self._share_cleanup_task
        self._share_cleanup_task = None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
