"""Behavior tests for the Home Assistant-native playback queue."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.xiaoai_navidrome.model import NavidromeProtocolError, Track
from custom_components.xiaoai_navidrome.queue import (
    PlaybackQueue,
    QueueClosedError,
    QueueConflictError,
    QueuePlayerError,
)
from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.core import HomeAssistant, ServiceCall

PLAYER = "media_player.synthetic_speaker"


class FakeNavidrome:
    """Return deterministic direct stream URLs and track deleted shares."""

    def __init__(self) -> None:
        self.created: list[list[str]] = []
        self.deleted: list[str] = []

    async def async_create_stream_urls(
        self, tracks: list[str], *, max_bit_rate: int, ttl: timedelta
    ) -> tuple[str, list[str]]:
        assert max_bit_rate == 128
        assert ttl == timedelta(hours=1)
        self.created.append(list(tracks))
        return f"share-{len(self.created)}", [
            f"https://media.invalid/share/s/{item}" for item in tracks
        ]

    async def async_delete_share(self, share_id: str) -> None:
        self.deleted.append(share_id)


@pytest.fixture
async def queue(hass: HomeAssistant) -> PlaybackQueue:
    """Create a queue with a compatible synthetic media player."""
    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set(PLAYER, "idle", {"supported_features": features})
    calls: list[tuple[str, dict[str, Any]]] = []

    async def capture(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("media_player", "play_media", capture)
    hass.services.async_register("media_player", "media_pause", capture)
    manager = PlaybackQueue(
        hass,
        "synthetic-entry",
        FakeNavidrome(),  # type: ignore[arg-type]
        media_player=PLAYER,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    manager.test_calls = calls  # type: ignore[attr-defined]
    await manager.async_load()
    yield manager
    await manager.async_close()


async def test_replace_next_previous_and_cached_share(queue: PlaybackQueue) -> None:
    """Playback controls retain one ordered share while queue contents are unchanged."""
    tracks = [
        Track("track-a", "Synthetic Alpha", duration=300),
        Track("track-b", "Synthetic Beta", duration=300),
    ]
    first = await queue.async_replace(tracks)
    assert first["state"] == "playing"
    assert first["current_index"] == 0
    assert queue.navidrome.created == [["track-a", "track-b"]]  # type: ignore[attr-defined]

    second = await queue.async_next(expected_revision=first["revision"])
    assert second["current_index"] == 1
    assert len(queue.navidrome.created) == 1  # type: ignore[attr-defined]

    previous = await queue.async_previous(expected_revision=second["revision"])
    assert previous["current_index"] == 0
    assert len(queue.navidrome.created) == 1  # type: ignore[attr-defined]


async def test_sequence_mode_wraps_after_the_last_track(queue: PlaybackQueue) -> None:
    """The default sequential mode continuously loops the queue."""
    first = await queue.async_replace(
        [Track("track-a", duration=300), Track("track-b", duration=300)]
    )
    assert first["repeat"] == "all"
    assert first["shuffle"] is False
    second = await queue.async_next(expected_revision=first["revision"])
    wrapped = await queue.async_next(expected_revision=second["revision"])
    assert wrapped["current_index"] == 0
    assert wrapped["state"] == "playing"


async def test_native_resume_volume_mute_and_seek(
    hass: HomeAssistant, queue: PlaybackQueue
) -> None:
    """Supported player controls call the corresponding Home Assistant services."""
    features = int(
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    async def capture(call: ServiceCall) -> None:
        queue.test_calls.append((call.service, dict(call.data)))  # type: ignore[attr-defined]

    for service in ("media_play", "media_seek", "volume_set", "volume_mute"):
        hass.services.async_register("media_player", service, capture)

    playing = await queue.async_replace([Track("track-a", duration=300)])
    hass.states.async_set(
        PLAYER,
        "paused",
        {
            "supported_features": features,
            "media_duration": 300,
            "media_position": 42,
            "volume_level": 0.35,
            "is_volume_muted": False,
        },
    )
    assert await queue.async_handle_player_state(PLAYER, "playing", "paused", datetime.now(UTC))
    resumed = await queue.async_play(expected_revision=queue.revision)
    assert resumed["state"] == "playing"
    assert len(queue.navidrome.created) == 1  # type: ignore[attr-defined]
    assert queue.test_calls[-1] == ("media_play", {"entity_id": PLAYER})  # type: ignore[attr-defined]

    volume = await queue.async_set_volume(0.6, expected_revision=resumed["revision"])
    assert volume["player"]["supports_volume_set"] is True
    assert queue.test_calls[-1] == (  # type: ignore[attr-defined]
        "volume_set",
        {"entity_id": PLAYER, "volume_level": 0.6},
    )
    muted = await queue.async_set_muted(True, expected_revision=volume["revision"])
    assert muted["player"]["supports_volume_mute"] is True
    assert queue.test_calls[-1] == (  # type: ignore[attr-defined]
        "volume_mute",
        {"entity_id": PLAYER, "is_volume_muted": True},
    )
    sought = await queue.async_seek(120, expected_revision=muted["revision"])
    assert sought["position"] == 120
    assert sought["player"]["position"] == 120
    assert queue.test_calls[-1] == (  # type: ignore[attr-defined]
        "media_seek",
        {"entity_id": PLAYER, "seek_position": 120.0},
    )
    assert playing["revision"] < queue.revision
    assert await queue.async_handle_player_state(PLAYER, "playing", "paused", datetime.now(UTC))
    assert queue.state == "stopped"


async def test_player_controls_reject_unsupported_capabilities(queue: PlaybackQueue) -> None:
    """The queue never bypasses a media player's advertised capabilities."""
    await queue.async_replace([Track("track-a", duration=300)])
    with pytest.raises(QueuePlayerError, match="volume control"):
        await queue.async_set_volume(0.5)
    with pytest.raises(QueuePlayerError, match="mute control"):
        await queue.async_set_muted(True)
    with pytest.raises(QueuePlayerError, match="seeking"):
        await queue.async_seek(30)


async def test_playback_error_hides_dynamic_share_identifier(queue: PlaybackQueue) -> None:
    """A failed M3U request cannot expose its capability identifier."""
    private_id = "synthetic-private-share-capability"
    queue.navidrome.async_create_stream_urls = AsyncMock(  # type: ignore[method-assign]
        side_effect=NavidromeProtocolError(f"GET share/{private_id}/m3u returned HTTP 500")
    )

    with pytest.raises(QueuePlayerError) as raised:
        await queue.async_replace([Track("synthetic-track", duration=30)])

    assert private_id not in str(raised.value)
    assert private_id not in queue.status()["last_error"]
    assert queue.status()["last_error"] == "Navidrome returned an invalid playback response"


async def test_external_pause_cancels_automatic_advance(queue: PlaybackQueue) -> None:
    """A Home Assistant state event stops the internal timer without polling."""
    status = await queue.async_replace(
        [Track("short-a", duration=1), Track("short-b", duration=30)]
    )
    handled = await queue.async_handle_player_state(
        PLAYER,
        "playing",
        "paused",
        datetime.now(UTC),
    )
    assert handled
    assert queue.status()["state"] == "stopped"
    await asyncio.sleep(1.2)
    assert queue.status()["current_index"] == 0
    assert queue.status()["state"] == "stopped"
    assert status["revision"] < queue.status()["revision"]


async def test_queue_option_change_retains_automatic_advance(
    queue: PlaybackQueue,
) -> None:
    """A new revision for repeat or shuffle must not invalidate the active timer."""
    playing = await queue.async_replace(
        [Track("short-a", duration=1), Track("long-b", duration=30)]
    )
    await queue.async_set_options(repeat="all", expected_revision=playing["revision"])
    await asyncio.sleep(1.2)
    assert queue.status()["current_index"] == 1
    assert queue.status()["state"] == "playing"


async def test_switching_player_stops_the_old_output(
    hass: HomeAssistant,
    queue: PlaybackQueue,
) -> None:
    """Changing an active output cannot leave the previous speaker playing."""
    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set("media_player.second", "idle", {"supported_features": features})
    playing = await queue.async_replace([Track("synthetic", duration=30)])
    result = await queue.async_set_media_player(
        "media_player.second",
        expected_revision=playing["revision"],
    )
    assert result["state"] == "stopped"
    assert result["media_player"] == "media_player.second"
    assert queue.test_calls[-1] == (
        "media_pause",
        {"entity_id": PLAYER},
    )


async def test_stop_prevents_stale_revision_mutation(queue: PlaybackQueue) -> None:
    """Revision CAS rejects a stale panel command after stop."""
    playing = await queue.async_replace([Track("track-a", duration=300)])
    stopped = await queue.async_stop(expected_revision=playing["revision"])
    assert stopped["state"] == "stopped"
    calls_after_stop = len(queue.test_calls)
    repeated = await queue.async_stop(expected_revision=stopped["revision"])
    assert repeated["revision"] == stopped["revision"]
    assert len(queue.test_calls) == calls_after_stop
    with pytest.raises(QueueConflictError):
        await queue.async_play(expected_revision=playing["revision"])


async def test_close_is_terminal_during_inflight_play(hass: HomeAssistant) -> None:
    """Config Entry unload wins over a play transaction blocked in Home Assistant."""
    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set(PLAYER, "idle", {"supported_features": features})
    play_started = asyncio.Event()
    allow_play_return = asyncio.Event()
    pause_calls: list[str] = []

    async def play_media(_call: ServiceCall) -> None:
        play_started.set()
        await allow_play_return.wait()

    async def pause(call: ServiceCall) -> None:
        pause_calls.append(call.data["entity_id"])

    hass.services.async_register("media_player", "play_media", play_media)
    hass.services.async_register("media_player", "media_pause", pause)
    navidrome = FakeNavidrome()
    manager = PlaybackQueue(
        hass,
        "close-race-entry",
        navidrome,  # type: ignore[arg-type]
        media_player=PLAYER,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await manager.async_load()

    play_task = asyncio.create_task(manager.async_replace([Track("track-a", duration=300)]))
    await play_started.wait()
    close_task = asyncio.create_task(manager.async_close())
    await asyncio.sleep(0)
    allow_play_return.set()
    with pytest.raises(QueuePlayerError):
        await play_task
    await close_task

    assert manager.status()["state"] == "stopped"
    assert pause_calls == [PLAYER]
    assert manager._share_id == ""
    assert navidrome.deleted == ["share-1"]
    with pytest.raises(QueueClosedError):
        await manager.async_play()


async def test_stale_timer_cannot_cross_player_switch(hass: HomeAssistant) -> None:
    """A timer waiting for the lock cannot replay after a newer stopped revision."""
    old_player = "media_player.race_old"
    new_player = "media_player.race_new"
    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set(old_player, "idle", {"supported_features": features})
    hass.states.async_set(new_player, "idle", {"supported_features": features})
    pause_started = asyncio.Event()
    allow_pause_return = asyncio.Event()
    play_calls: list[dict[str, Any]] = []

    async def play_media(call: ServiceCall) -> None:
        play_calls.append(dict(call.data))

    async def pause(call: ServiceCall) -> None:
        if call.data["entity_id"] == old_player:
            pause_started.set()
            await allow_pause_return.wait()

    hass.services.async_register("media_player", "play_media", play_media)
    hass.services.async_register("media_player", "media_pause", pause)
    manager = PlaybackQueue(
        hass,
        "timer-race-entry",
        FakeNavidrome(),  # type: ignore[arg-type]
        media_player=old_player,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await manager.async_load()
    await manager.async_replace([Track("track-a", duration=300), Track("track-b", duration=300)])
    revision = manager.revision

    switch_task = asyncio.create_task(manager.async_set_media_player(new_player))
    await pause_started.wait()
    timer_task = asyncio.create_task(manager._async_timer(0, revision))
    await asyncio.sleep(0)
    allow_pause_return.set()
    await switch_task
    await timer_task

    assert manager.status()["media_player"] == new_player
    assert manager.status()["state"] == "stopped"
    assert manager.status()["current_index"] == 0
    assert len(play_calls) == 1
    await manager.async_close()


async def test_buffering_then_paused_stops_queue(queue: PlaybackQueue) -> None:
    """An intermediate buffering state cannot hide an explicit external pause."""
    await queue.async_replace([Track("track-a", duration=300)])
    assert not await queue.async_handle_player_state(
        PLAYER,
        "playing",
        "buffering",
        datetime.now(UTC),
    )
    assert await queue.async_handle_player_state(
        PLAYER,
        "buffering",
        "paused",
        datetime.now(UTC),
    )
    assert queue.status()["state"] == "stopped"


async def test_failed_share_deletion_is_persisted_and_retried(hass: HomeAssistant) -> None:
    """A transient Navidrome failure cannot discard the only revocation identifier."""

    class FlakyNavidrome(FakeNavidrome):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def async_delete_share(self, share_id: str) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("synthetic outage")
            self.deleted.append(share_id)

    navidrome = FlakyNavidrome()
    manager = PlaybackQueue(
        hass,
        "share-cleanup-entry",
        navidrome,  # type: ignore[arg-type]
        media_player="",
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await manager.async_load()
    await manager._async_delete_share("share-pending")
    stored = await manager._store.async_load()
    assert stored["pending_share_deletions"] == ["share-pending"]
    manager._cancel_share_cleanup()
    await asyncio.sleep(0)

    with patch(
        "custom_components.xiaoai_navidrome.queue.asyncio.sleep",
        new=AsyncMock(),
    ):
        await manager._async_retry_share_cleanup()
    stored = await manager._store.async_load()
    assert stored["pending_share_deletions"] == []
    assert navidrome.deleted == ["share-pending"]
    await manager.async_close()


async def test_replace_with_player_override_stops_previous_output(
    hass: HomeAssistant,
) -> None:
    """A service-level target override cannot leave two speakers playing."""
    second = "media_player.synthetic_second"
    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set(PLAYER, "idle", {"supported_features": features})
    hass.states.async_set(second, "idle", {"supported_features": features})
    calls: list[tuple[str, str]] = []

    async def capture(call: ServiceCall) -> None:
        calls.append((call.service, call.data["entity_id"]))

    hass.services.async_register("media_player", "play_media", capture)
    hass.services.async_register("media_player", "media_pause", capture)
    manager = PlaybackQueue(
        hass,
        "override-entry",
        FakeNavidrome(),  # type: ignore[arg-type]
        media_player=PLAYER,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await manager.async_load()
    await manager.async_replace([Track("track-a", duration=60)])
    await manager.async_replace([Track("track-b", duration=60)], media_player=second)
    assert calls == [
        ("play_media", PLAYER),
        ("media_pause", PLAYER),
        ("play_media", second),
    ]
    await manager.async_close()


async def test_pause_during_loading_stops_after_play_transaction(
    hass: HomeAssistant,
) -> None:
    """A buffering-to-paused event is retained while play_media owns the queue lock."""
    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set(PLAYER, "idle", {"supported_features": features})
    state_tasks: list[asyncio.Task[bool]] = []

    async def play(_call: ServiceCall) -> None:
        changed_at = datetime.now(UTC)
        state_tasks.append(
            asyncio.create_task(
                manager.async_handle_player_state(
                    PLAYER,
                    "buffering",
                    "paused",
                    changed_at,
                )
            )
        )
        await asyncio.sleep(0)

    async def pause(_call: ServiceCall) -> None:
        return None

    hass.services.async_register("media_player", "play_media", play)
    hass.services.async_register("media_player", "media_pause", pause)
    manager = PlaybackQueue(
        hass,
        "loading-pause-entry",
        FakeNavidrome(),  # type: ignore[arg-type]
        media_player=PLAYER,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await manager.async_load()
    await manager.async_replace([Track("track-a", duration=60)])
    assert state_tasks
    assert await state_tasks[0]
    assert manager.status()["state"] == "stopped"
    await manager.async_close()


async def test_changed_configured_player_overrides_stored_panel_selection(
    hass: HomeAssistant,
) -> None:
    """An Options Flow player change wins over an older queue Store selection."""
    second = "media_player.synthetic_second"
    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set(PLAYER, "idle", {"supported_features": features})
    hass.states.async_set(second, "idle", {"supported_features": features})
    first = PlaybackQueue(
        hass,
        "player-option-entry",
        FakeNavidrome(),  # type: ignore[arg-type]
        media_player=PLAYER,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await first.async_load()
    await first.async_close()
    second_queue = PlaybackQueue(
        hass,
        "player-option-entry",
        FakeNavidrome(),  # type: ignore[arg-type]
        media_player=second,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await second_queue.async_load()
    assert second_queue.media_player == second
    await second_queue.async_close()


async def test_active_share_is_revoked_after_restart(hass: HomeAssistant) -> None:
    """A crash-restored active share becomes a persisted revocation candidate."""
    manager = PlaybackQueue(
        hass,
        "active-share-entry",
        FakeNavidrome(),  # type: ignore[arg-type]
        media_player="",
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await manager.async_load()
    manager._share_id = "share-active"
    await manager._async_persist()

    restored_nav = FakeNavidrome()
    restored = PlaybackQueue(
        hass,
        "active-share-entry",
        restored_nav,  # type: ignore[arg-type]
        media_player="",
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await restored.async_load()
    restored._cancel_share_cleanup()
    await asyncio.sleep(0)
    with patch(
        "custom_components.xiaoai_navidrome.queue.asyncio.sleep",
        new=AsyncMock(),
    ):
        await restored._async_retry_share_cleanup()
    assert restored_nav.deleted == ["share-active"]
    await restored.async_close()


async def test_share_handoff_persists_old_revocation_before_delete(
    hass: HomeAssistant,
) -> None:
    """A crash after activating a new share still leaves the old ID recoverable."""

    class BlockingDeleteNavidrome(FakeNavidrome):
        def __init__(self) -> None:
            super().__init__()
            self.delete_started = asyncio.Event()
            self.allow_delete = asyncio.Event()

        async def async_delete_share(self, share_id: str) -> None:
            if share_id == "share-1":
                self.delete_started.set()
                await self.allow_delete.wait()
            await super().async_delete_share(share_id)

    features = int(MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.PAUSE)
    hass.states.async_set(PLAYER, "idle", {"supported_features": features})

    async def capture(_call: ServiceCall) -> None:
        return None

    hass.services.async_register("media_player", "play_media", capture)
    hass.services.async_register("media_player", "media_pause", capture)
    navidrome = BlockingDeleteNavidrome()
    manager = PlaybackQueue(
        hass,
        "share-handoff-entry",
        navidrome,  # type: ignore[arg-type]
        media_player=PLAYER,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    await manager.async_load()
    await manager.async_replace([Track("track-a", duration=60)])
    replace_task = asyncio.create_task(manager.async_replace([Track("track-b", duration=60)]))
    await navidrome.delete_started.wait()
    stored = await manager._store.async_load()
    assert stored["active_share_id"] == "share-2"
    assert stored["pending_share_deletions"] == ["share-1"]
    navidrome.allow_delete.set()
    await replace_task
    await manager.async_close()
