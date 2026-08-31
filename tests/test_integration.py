"""End-to-end Home Assistant runtime tests with synthetic Navidrome data."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.xiaoai_navidrome import async_setup_entry
from custom_components.xiaoai_navidrome.const import DOMAIN
from custom_components.xiaoai_navidrome.diagnostics import async_get_config_entry_diagnostics
from custom_components.xiaoai_navidrome.model import NavidromeProtocolError, Track
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

        hass.states.async_set(
            SENSOR,
            "播放家庭音乐Synthetic Beta",
            {"synthetic_sequence": 2},
        )
        await hass.async_block_till_done()
        assert create_stream.call_count == 2

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
