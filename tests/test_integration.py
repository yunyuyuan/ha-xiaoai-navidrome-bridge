"""End-to-end Home Assistant runtime tests with synthetic Navidrome data."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.xiaoai_navidrome import async_setup_entry
from custom_components.xiaoai_navidrome.const import DOMAIN
from custom_components.xiaoai_navidrome.diagnostics import async_get_config_entry_diagnostics
from custom_components.xiaoai_navidrome.model import NavidromeProtocolError, Playlist, Track
from custom_components.xiaoai_navidrome.queue import PlaybackQueue
from custom_components.xiaoai_navidrome.runtime import (
    XiaoAINavidromeRuntime,
    _voice_error_category,
)
from custom_components.xiaoai_navidrome.voice import VoiceCommand
from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

PLAYER = "media_player.synthetic_speaker"
SENSOR = "sensor.synthetic_conversation"
ENTRY_DATA = {
    "navidrome_url": "https://navidrome.invalid",
    "username": "synthetic-user",
    "password": "synthetic-password",
    "verify_ssl": True,
}
ENTRY_OPTIONS = {
    "media_player": PLAYER,
    "conversation_sensor": SENSOR,
    "track_phrase": "播放家庭音乐",
    "playlist_phrase": "播放家庭歌单",
    "max_bit_rate": 128,
    "share_ttl_hours": 6,
    "queue_max_tracks": 100,
    "playlist_gap_seconds": 2,
    "index_refresh_minutes": 30,
    "embedding_enabled": False,
    "embedding_provider": "ollama",
    "embedding_model": "synthetic-model",
    "autoplay_min_score": 0.91,
    "autoplay_min_margin": 0.19,
    "embedding_weight": 0.25,
    "semantic_autoplay_min_score": 0.7,
    "semantic_autoplay_min_margin": 0.11,
}
TRACKS = [
    Track("track-a", "Synthetic Alpha", "Example Artist", duration=300),
    Track("track-b", "Synthetic Beta", "Example Artist", duration=300),
]


@pytest.fixture
async def voice_queue(hass: HomeAssistant) -> PlaybackQueue:
    """Create an empty real queue for delayed voice mutation tests."""
    manager = PlaybackQueue(
        hass,
        "synthetic-voice-entry",
        SimpleNamespace(),  # type: ignore[arg-type]
        media_player=PLAYER,
        max_tracks=20,
        max_bit_rate=128,
        share_ttl=timedelta(hours=1),
        gap_seconds=0,
    )
    manager.test_calls = []  # type: ignore[attr-defined]
    await manager.async_load()
    yield manager
    await manager.async_close()


async def test_setup_service_voice_and_player_state_sync(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The integration runs playback and state synchronization without YAML or Bridge."""
    features = int(
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )
    hass.states.async_set(PLAYER, "idle", {"supported_features": features})
    hass.states.async_set(SENSOR, "idle")
    media_calls: list[tuple[str, dict[str, Any]]] = []

    async def capture(call: ServiceCall) -> None:
        media_calls.append((call.service, dict(call.data)))

    hass.services.async_register("media_player", "play_media", capture)
    hass.services.async_register("media_player", "media_play", capture)
    hass.services.async_register("media_player", "media_pause", capture)
    hass.services.async_register("media_player", "media_seek", capture)
    hass.services.async_register("media_player", "volume_set", capture)
    hass.services.async_register("media_player", "volume_mute", capture)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
        unique_id="synthetic-entry",
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.xiaoai_navidrome.navidrome.NavidromeClient.async_ping",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.xiaoai_navidrome.navidrome.NavidromeClient.async_all_tracks",
            new=AsyncMock(return_value=TRACKS),
        ),
        patch(
            "custom_components.xiaoai_navidrome.navidrome.NavidromeClient.async_create_stream_urls",
            new=AsyncMock(
                side_effect=[
                    (
                        "share-a",
                        ["https://navidrome.invalid/share/s/synthetic/track-a"],
                    ),
                    (
                        "share-b",
                        ["https://navidrome.invalid/share/s/synthetic/track-b"],
                    ),
                    (
                        "share-c",
                        ["https://navidrome.invalid/share/s/synthetic/track-b"],
                    ),
                ]
            ),
        ) as create_stream,
        patch(
            "custom_components.xiaoai_navidrome.navidrome.NavidromeClient.async_delete_share",
            new=AsyncMock(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        runtime = hass.data[DOMAIN]["entries"][entry.entry_id]
        if runtime._sync_task is not None:
            await runtime._sync_task
        initial_sensor_state = hass.states.get(SENSOR)
        assert initial_sensor_state is not None
        initial_identity = runtime._conversation_event_identity(initial_sensor_state)
        assert initial_identity in runtime._processed_voice_events
        assert runtime.index_status()["track_count"] == 2
        assert runtime.index.autoplay_min_score == 0.91
        assert runtime.index.autoplay_min_margin == 0.19
        assert runtime.index.embedding_weight == 0.25

        websocket = await hass_ws_client(hass)
        await websocket.send_json_auto_id({"type": f"{DOMAIN}/config", "entry_id": entry.entry_id})
        panel_config = await websocket.receive_json()
        assert panel_config["success"]
        assert panel_config["result"]["direct_share_streams"] is True

        await websocket.send_json_auto_id(
            {"type": f"{DOMAIN}/media_players", "entry_id": entry.entry_id}
        )
        players = await websocket.receive_json()
        assert players["success"]
        assert players["result"]["items"][0]["supports_seek"] is True
        assert players["result"]["items"][0]["supports_volume_set"] is True
        assert players["result"]["items"][0]["supports_volume_mute"] is True

        regular_user = await hass.auth.async_create_user("synthetic-regular-user")
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN,
                "sync_library",
                blocking=True,
                context=Context(user_id=regular_user.id),
            )

        response = await hass.services.async_call(
            DOMAIN,
            "play",
            {"query": "Synthetic Alpha"},
            blocking=True,
            return_response=True,
        )
        assert response["queue"]["state"] == "playing"
        assert media_calls[-1][0] == "play_media"
        assert media_calls[-1][1]["media_content_id"].startswith(
            "https://navidrome.invalid/share/s/"
        )

        for payload, expected_call in (
            (
                {"action": "volume_set", "volume_level": 0.4},
                ("volume_set", {"entity_id": PLAYER, "volume_level": 0.4}),
            ),
            (
                {"action": "volume_mute", "is_volume_muted": True},
                ("volume_mute", {"entity_id": PLAYER, "is_volume_muted": True}),
            ),
            (
                {"action": "seek", "position": 30},
                ("media_seek", {"entity_id": PLAYER, "seek_position": 30.0}),
            ),
        ):
            await websocket.send_json_auto_id(
                {
                    "type": f"{DOMAIN}/player_control",
                    "entry_id": entry.entry_id,
                    **payload,
                }
            )
            player_control = await websocket.receive_json()
            assert player_control["success"]
            assert media_calls[-1] == expected_call

        hass.states.async_set(SENSOR, "播放家庭音乐Synthetic Beta")
        await hass.async_block_till_done()
        assert runtime.queue.status()["current"]["id"] == "track-b"
        assert create_stream.call_count == 2
        sensor_state = hass.states.get(SENSOR)
        assert sensor_state is not None
        first_identity = runtime._conversation_event_identity(sensor_state)
        assert first_identity is not None
        assert first_identity.startswith("state_change:")
        assert first_identity in runtime._processed_voice_events

        hass.states.async_set(
            SENSOR,
            "播放家庭音乐Synthetic Beta",
            {"synthetic_sequence": 2},
        )
        await hass.async_block_till_done()
        assert create_stream.call_count == 2
        sensor_state = hass.states.get(SENSOR)
        assert sensor_state is not None
        assert runtime._conversation_event_identity(sensor_state) == first_identity
        assert list(runtime._processed_voice_events).count(first_identity) == 1

        event_time = datetime.now(UTC).isoformat()
        hass.states.async_set(
            SENSOR,
            "播放家庭音乐Synthetic Beta",
            {"timestamp": event_time},
        )
        await hass.async_block_till_done()
        assert create_stream.call_count == 3
        hass.states.async_set(
            SENSOR,
            "播放家庭音乐Synthetic Beta",
            {"timestamp": event_time, "synthetic_refresh": 1},
        )
        await hass.async_block_till_done()
        assert create_stream.call_count == 3

        hass.states.async_set(PLAYER, "playing", {"supported_features": features})
        hass.states.async_set(PLAYER, "paused", {"supported_features": features})
        await hass.async_block_till_done()
        assert runtime.queue.status()["state"] == "stopped"

        response = await hass.services.async_call(
            DOMAIN,
            "resume",
            blocking=True,
            return_response=True,
        )
        assert response["state"] == "playing"
        assert media_calls[-1][0] == "media_play"
        assert create_stream.call_count == 3

        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        serialized_diagnostics = repr(diagnostics)
        assert "navidrome.invalid" not in serialized_diagnostics
        assert PLAYER not in serialized_diagnostics
        assert "播放家庭音乐" not in serialized_diagnostics
        assert "Synthetic Alpha" not in serialized_diagnostics

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert entry.entry_id not in hass.data[DOMAIN]["entries"]


async def test_panel_registration_failure_closes_unpublished_runtime(
    hass: HomeAssistant,
) -> None:
    """A partial setup cannot leave listeners, tasks, or queue output behind."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "navidrome_url": "https://navidrome.invalid",
            "username": "synthetic-user",
            "password": "synthetic-password",
            "verify_ssl": True,
        },
        options={"media_player": PLAYER},
    )
    entry.add_to_hass(hass)
    runtime = AsyncMock()
    with (
        patch(
            "custom_components.xiaoai_navidrome.XiaoAINavidromeRuntime",
            return_value=runtime,
        ),
        patch(
            "custom_components.xiaoai_navidrome.async_register_panel",
            new=AsyncMock(side_effect=RuntimeError("synthetic panel failure")),
        ),
        patch("custom_components.xiaoai_navidrome.async_unregister_panel"),
        pytest.raises(RuntimeError, match="synthetic panel failure"),
    ):
        await async_setup_entry(hass, entry)
    runtime.async_setup.assert_awaited_once()
    runtime.async_close.assert_awaited_once()
    assert DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]["entries"]


async def test_playlist_start_occurrence_is_forwarded_to_shuffled_queue(
    hass: HomeAssistant,
) -> None:
    """A playlist click forwards the exact selected occurrence to the queue."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="synthetic-playlist-entry",
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
    )
    runtime = XiaoAINavidromeRuntime(hass, entry)
    playlist_tracks = [
        Track("track-a", title="Synthetic First", duration=300),
        Track("track-b", duration=300),
        Track("track-a", title="Synthetic Selected", duration=300),
        Track("track-c", duration=300),
    ]
    runtime.navidrome.async_playlist_tracks = AsyncMock(return_value=playlist_tracks)
    runtime.queue.async_replace = AsyncMock(
        return_value={"current": {"id": "track-a", "title": "Synthetic Selected"}}
    )

    result = await runtime.async_add_playlist(
        "playlist-one",
        "replace",
        start_track_id="track-a",
        start_index=2,
        expected_revision=7,
        context=None,
    )

    assert result["current"]["title"] == "Synthetic Selected"
    runtime.queue.async_replace.assert_awaited_once_with(
        playlist_tracks,
        first_track_index=2,
        expected_revision=7,
        context=None,
    )
    runtime.queue.async_replace.reset_mock()
    with pytest.raises(HomeAssistantError, match="playlist item has changed"):
        await runtime.async_add_playlist(
            "playlist-one",
            "replace",
            start_track_id="track-a",
            start_index=1,
            expected_revision=7,
            context=None,
        )
    runtime.queue.async_replace.assert_not_awaited()
    await runtime.async_close()


async def test_manual_sync_is_cancelled_before_runtime_reload(
    hass: HomeAssistant,
) -> None:
    """An old manual sync cannot write the shared index Store after close returns."""
    entry_id = "sync-race-entry"
    old_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
    )
    new_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
    )
    old = XiaoAINavidromeRuntime(hass, old_entry)
    new = XiaoAINavidromeRuntime(hass, new_entry)
    old.navidrome.async_all_tracks = AsyncMock(return_value=[Track("old-track", "Synthetic Old")])
    new.navidrome.async_all_tracks = AsyncMock(return_value=[Track("new-track", "Synthetic New")])
    write_started = asyncio.Event()
    allow_write = threading.Event()
    original_write = old._index_store._write_data

    def blocked_write(data: dict[str, Any]) -> None:
        hass.loop.call_soon_threadsafe(write_started.set)
        assert allow_write.wait(10)
        original_write(data)

    async def blocked_async_write(data: dict[str, Any]) -> None:
        await hass.async_add_executor_job(blocked_write, data)

    old._index_store._async_write_data = blocked_async_write  # type: ignore[method-assign]
    old_sync = asyncio.create_task(old.async_sync_library())
    write_wait = asyncio.create_task(write_started.wait())
    done, _pending = await asyncio.wait(
        {old_sync, write_wait},
        timeout=10,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if old_sync in done:
        result = await old_sync
        pytest.fail(f"sync exited before its Store executor write started: {result}")
    assert write_wait in done
    close_task = asyncio.create_task(old.async_close())
    await asyncio.sleep(0)
    assert not close_task.done()
    allow_write.set()
    await close_task
    with pytest.raises(asyncio.CancelledError):
        await old_sync

    await new.async_sync_library()
    stored = await Store(
        hass,
        1,
        f"xiaoai_navidrome.{entry_id}.index",
        private=True,
        atomic_writes=True,
        serialize_in_event_loop=False,
    ).async_load()
    assert stored is not None
    assert [item["track"]["id"] for item in stored["tracks"]] == ["new-track"]
    await new.async_close()


async def test_voice_failure_log_hides_dynamic_share_identifier() -> None:
    """Voice errors log a fixed category rather than exception text."""
    private_id = "synthetic-private-share-capability"
    root = NavidromeProtocolError(f"GET share/{private_id}/m3u returned HTTP 500")
    wrapped = HomeAssistantError("Playback operation failed")
    wrapped.__cause__ = root
    runtime = object.__new__(XiaoAINavidromeRuntime)
    runtime.async_play_query = AsyncMock(side_effect=wrapped)

    with patch("custom_components.xiaoai_navidrome.runtime._LOGGER.warning") as warning:
        await runtime._async_execute_voice(VoiceCommand("play", "synthetic query"))

    warning.assert_called_once_with(
        "Unable to handle XiaoAI Navidrome voice command (%s error)",
        "protocol",
    )
    assert private_id not in str(warning.call_args)
    assert _voice_error_category(wrapped) == "protocol"


def test_conversation_identity_rejects_stale_state_change_fallback() -> None:
    """An old sensor state without record metadata is not a fresh voice event."""
    stale = SimpleNamespace(
        attributes={},
        last_changed=datetime.now(UTC) - timedelta(minutes=2),
    )
    assert XiaoAINavidromeRuntime._conversation_event_identity(stale) is None  # type: ignore[arg-type]
    future = SimpleNamespace(
        attributes={"timestamp": (datetime.now(UTC) + timedelta(minutes=2)).isoformat()},
        last_changed=datetime.now(UTC),
    )
    assert XiaoAINavidromeRuntime._conversation_event_identity(future) is None  # type: ignore[arg-type]


def test_stable_conversation_id_is_processed_only_once() -> None:
    """A refreshed record with one stable ID cannot be replayed later."""
    scheduled: list[str] = []

    def capture_task(_hass: Any, task: Any, name: str) -> None:
        scheduled.append(name)
        task.close()

    runtime = object.__new__(XiaoAINavidromeRuntime)
    runtime._closing = False
    runtime._closed = False
    runtime.options = ENTRY_OPTIONS
    runtime.hass = SimpleNamespace()
    runtime.entry = SimpleNamespace(
        entry_id="synthetic-entry", async_create_background_task=capture_task
    )
    runtime.queue = SimpleNamespace(revision=7)
    runtime._processed_voice_events = set()
    first = SimpleNamespace(
        state="播放家庭音乐Synthetic Alpha",
        attributes={"conversation_id": "conversation-one"},
        last_changed=datetime.now(UTC),
    )
    refreshed = SimpleNamespace(
        state=first.state,
        attributes={"conversation_id": "conversation-one", "synthetic_refresh": 99},
        last_changed=first.last_changed,
    )

    runtime._async_conversation_changed(
        SimpleNamespace(data={"old_state": None, "new_state": first})
    )
    runtime._async_conversation_changed(
        SimpleNamespace(data={"old_state": first, "new_state": refreshed})
    )

    assert len(scheduled) == 1
    assert runtime._processed_voice_events == {"conversation_id:conversation-one"}


async def test_voice_play_execution_forwards_trigger_revision() -> None:
    """Track and playlist work retain the revision captured by the event callback."""
    runtime = object.__new__(XiaoAINavidromeRuntime)
    runtime.async_play_query = AsyncMock()
    runtime.async_play_playlist_query = AsyncMock()

    await runtime._async_execute_voice(VoiceCommand("play", "synthetic track"), 17)
    await runtime._async_execute_voice(VoiceCommand("play_playlist", "synthetic list"), 23)

    runtime.async_play_query.assert_awaited_once_with("synthetic track", expected_revision=17)
    runtime.async_play_playlist_query.assert_awaited_once_with(
        "synthetic list", expected_revision=23
    )


async def test_delayed_voice_track_match_cannot_overwrite_cleared_queue(
    voice_queue: PlaybackQueue,
) -> None:
    """A track match started before clear cannot replace the newer empty queue."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_match(_query: str) -> tuple[Track, dict[str, Any]]:
        started.set()
        await release.wait()
        return Track("track-delayed", "Synthetic Delayed"), {"automatic": True}

    runtime = object.__new__(XiaoAINavidromeRuntime)
    runtime.queue = voice_queue
    runtime._async_match_track = delayed_match  # type: ignore[method-assign]
    task = asyncio.create_task(runtime.async_play_query("synthetic request"))
    await started.wait()
    await voice_queue.async_clear()
    release.set()

    with pytest.raises(HomeAssistantError, match="queue changed"):
        await task
    assert voice_queue.status()["items"] == []
    assert voice_queue.test_calls == []  # type: ignore[attr-defined]


async def test_delayed_voice_playlist_match_cannot_overwrite_cleared_queue(
    voice_queue: PlaybackQueue,
) -> None:
    """A playlist match started before clear cannot replace the newer empty queue."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_playlists(*, fresh: bool) -> list[Playlist]:
        assert fresh is True
        started.set()
        await release.wait()
        return [Playlist("playlist-delayed", "Synthetic Playlist")]

    async def run_executor(target: Any, *args: Any) -> Any:
        return target(*args)

    runtime = object.__new__(XiaoAINavidromeRuntime)
    runtime.queue = voice_queue
    runtime.hass = SimpleNamespace(async_add_executor_job=run_executor)
    runtime.index = SimpleNamespace(
        rank_playlists=lambda _query, _playlists: [
            {"id": "playlist-delayed", "name": "Synthetic Playlist", "score": 1.0}
        ],
        autoplay_min_score=0.9,
        autoplay_min_margin=0.1,
    )
    runtime.navidrome = SimpleNamespace(
        async_playlist_tracks=AsyncMock(return_value=[Track("track-delayed", "Synthetic Delayed")])
    )
    runtime._async_playlists = delayed_playlists  # type: ignore[method-assign]
    task = asyncio.create_task(runtime.async_play_playlist_query("synthetic request"))
    await started.wait()
    await voice_queue.async_clear()
    release.set()

    with pytest.raises(HomeAssistantError, match="queue changed"):
        await task
    assert voice_queue.status()["items"] == []
    assert voice_queue.test_calls == []  # type: ignore[attr-defined]
