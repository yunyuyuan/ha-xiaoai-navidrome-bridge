"""Authenticated WebSocket API for the native panel."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, WS_PREFIX
from .queue import QueueError

if TYPE_CHECKING:
    from .runtime import XiaoAINavidromeRuntime

_IDENTIFIER = vol.All(cv.string, vol.Length(min=1, max=512))
_PAGE = {
    vol.Optional("q", default=""): vol.All(cv.string, vol.Length(max=300)),
    vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("limit", default=40): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
}


def _schema(command: str, extra: dict[Any, Any] | None = None) -> dict[Any, Any]:
    return {
        vol.Required("type"): f"{WS_PREFIX}/{command}",
        vol.Required("entry_id"): cv.string,
        **(extra or {}),
    }


def _runtime(hass: HomeAssistant, msg: dict[str, Any]) -> XiaoAINavidromeRuntime:
    runtime = hass.data.get(DOMAIN, {}).get("entries", {}).get(msg["entry_id"])
    if runtime is None:
        raise HomeAssistantError("XiaoAI Navidrome entry is not loaded")
    return cast("XiaoAINavidromeRuntime", runtime)


async def _queue_result(awaitable: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await awaitable
    except QueueError as err:
        raise HomeAssistantError(str(err)) from err


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("config"))
@websocket_api.async_response
async def websocket_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return panel configuration and index status."""
    connection.send_result(msg["id"], _runtime(hass, msg).panel_config())


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("tracks", _PAGE))
@websocket_api.async_response
async def websocket_tracks(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Browse indexed tracks."""
    connection.send_result(
        msg["id"],
        await _runtime(hass, msg).async_browse_tracks(msg["q"], msg["offset"], msg["limit"]),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("playlists", _PAGE))
@websocket_api.async_response
async def websocket_playlists(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Browse Navidrome playlists."""
    connection.send_result(
        msg["id"],
        await _runtime(hass, msg).async_browse_playlists(msg["q"], msg["offset"], msg["limit"]),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    _schema(
        "playlist_tracks",
        {
            vol.Required("playlist_id"): _IDENTIFIER,
            vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional("limit", default=40): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
        },
    )
)
@websocket_api.async_response
async def websocket_playlist_tracks(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Browse tracks in one playlist."""
    connection.send_result(
        msg["id"],
        await _runtime(hass, msg).async_playlist_tracks(
            msg["playlist_id"], msg["offset"], msg["limit"]
        ),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("track", {vol.Required("track_id"): _IDENTIFIER}))
@websocket_api.async_response
async def websocket_track(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return full track details."""
    connection.send_result(
        msg["id"], (await _runtime(hass, msg).navidrome.async_track(msg["track_id"])).to_dict()
    )


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("media_players"))
@websocket_api.async_response
async def websocket_media_players(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return compatible Home Assistant media players."""
    connection.send_result(msg["id"], _runtime(hass, msg).media_players())


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("queue"))
@websocket_api.async_response
async def websocket_queue(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the current queue snapshot."""
    connection.send_result(msg["id"], _runtime(hass, msg).queue.status())


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("subscribe_queue"))
@callback
def websocket_subscribe_queue(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Subscribe the panel to queue updates instead of polling."""
    runtime = _runtime(hass, msg)

    @callback
    def forward(queue: dict[str, Any]) -> None:
        connection.send_event(msg["id"], queue)

    connection.subscriptions[msg["id"]] = runtime.queue.add_listener(forward)
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    _schema(
        "queue_add",
        {
            vol.Required("track_ids"): vol.All([_IDENTIFIER], vol.Length(min=1, max=5000)),
            vol.Required("position"): vol.In({"replace", "next", "last"}),
            vol.Optional("expected_revision"): vol.Coerce(int),
        },
    )
)
@websocket_api.async_response
async def websocket_queue_add(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add tracks to the queue."""
    runtime = _runtime(hass, msg)
    result = await runtime.async_add_track_ids(
        msg["track_ids"],
        msg["position"],
        expected_revision=msg.get("expected_revision"),
        context=connection.context(msg),
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    _schema(
        "queue_playlist",
        {
            vol.Required("playlist_id"): _IDENTIFIER,
            vol.Required("position"): vol.In({"replace", "next", "last"}),
            vol.Optional("start_track_id", default=""): vol.All(cv.string, vol.Length(max=512)),
            vol.Optional("expected_revision"): vol.Coerce(int),
        },
    )
)
@websocket_api.async_response
async def websocket_queue_playlist(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Load a playlist into the queue."""
    result = await _runtime(hass, msg).async_add_playlist(
        msg["playlist_id"],
        msg["position"],
        start_track_id=msg["start_track_id"],
        expected_revision=msg.get("expected_revision"),
        context=connection.context(msg),
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    _schema(
        "queue_control",
        {
            vol.Required("action"): vol.In({"play", "stop", "previous", "next", "clear", "jump"}),
            vol.Optional("index"): vol.Coerce(int),
            vol.Optional("expected_revision"): vol.Coerce(int),
        },
    )
)
@websocket_api.async_response
async def websocket_queue_control(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Run a transport action."""
    queue = _runtime(hass, msg).queue
    expected = msg.get("expected_revision")
    context = connection.context(msg)
    action = msg["action"]
    if action == "play":
        result = await _queue_result(queue.async_play(expected_revision=expected, context=context))
    elif action == "stop":
        result = await _queue_result(queue.async_stop(expected_revision=expected, context=context))
    elif action == "previous":
        result = await _queue_result(
            queue.async_previous(expected_revision=expected, context=context)
        )
    elif action == "next":
        result = await _queue_result(queue.async_next(expected_revision=expected, context=context))
    elif action == "clear":
        result = await _queue_result(queue.async_clear(expected_revision=expected, context=context))
    else:
        if "index" not in msg:
            raise HomeAssistantError("Queue jump requires an index")
        result = await _queue_result(
            queue.async_jump(msg["index"], expected_revision=expected, context=context)
        )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    _schema(
        "queue_options",
        {
            vol.Optional("shuffle"): cv.boolean,
            vol.Optional("repeat"): vol.In({"all", "one"}),
            vol.Optional("expected_revision"): vol.Coerce(int),
        },
    )
)
@websocket_api.async_response
async def websocket_queue_options(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update queue modes."""
    result = await _queue_result(
        _runtime(hass, msg).queue.async_set_options(
            shuffle=msg.get("shuffle"),
            repeat=msg.get("repeat"),
            expected_revision=msg.get("expected_revision"),
        )
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    _schema(
        "queue_player",
        {
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("expected_revision"): vol.Coerce(int),
        },
    )
)
@websocket_api.async_response
async def websocket_queue_player(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Select the queue output player."""
    result = await _queue_result(
        _runtime(hass, msg).queue.async_set_media_player(
            msg["entity_id"], expected_revision=msg.get("expected_revision")
        )
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    _schema(
        "player_control",
        {
            vol.Required("action"): vol.In({"volume_set", "volume_mute", "seek"}),
            vol.Optional("volume_level"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
            vol.Optional("is_volume_muted"): cv.boolean,
            vol.Optional("position"): vol.All(vol.Coerce(float), vol.Range(min=0, max=604800)),
            vol.Optional("expected_revision"): vol.Coerce(int),
        },
    )
)
@websocket_api.async_response
async def websocket_player_control(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Control supported properties of the selected Home Assistant player."""
    queue = _runtime(hass, msg).queue
    expected = msg.get("expected_revision")
    context = connection.context(msg)
    action = msg["action"]
    if action == "volume_set":
        if "volume_level" not in msg:
            raise HomeAssistantError("Volume control requires volume_level")
        result = await _queue_result(
            queue.async_set_volume(msg["volume_level"], expected_revision=expected, context=context)
        )
    elif action == "volume_mute":
        if "is_volume_muted" not in msg:
            raise HomeAssistantError("Mute control requires is_volume_muted")
        result = await _queue_result(
            queue.async_set_muted(
                msg["is_volume_muted"], expected_revision=expected, context=context
            )
        )
    else:
        if "position" not in msg:
            raise HomeAssistantError("Seek control requires position")
        result = await _queue_result(
            queue.async_seek(msg["position"], expected_revision=expected, context=context)
        )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(_schema("sync_library"))
@websocket_api.async_response
async def websocket_sync_library(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Trigger an immediate index synchronization."""
    connection.send_result(msg["id"], await _runtime(hass, msg).async_sync_library())


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register panel commands exactly once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("websocket_registered"):
        return
    for command in (
        websocket_config,
        websocket_tracks,
        websocket_playlists,
        websocket_playlist_tracks,
        websocket_track,
        websocket_media_players,
        websocket_queue,
        websocket_subscribe_queue,
        websocket_queue_add,
        websocket_queue_playlist,
        websocket_queue_control,
        websocket_queue_options,
        websocket_queue_player,
        websocket_player_control,
        websocket_sync_library,
    ):
        websocket_api.async_register_command(hass, command)
    domain_data["websocket_registered"] = True
