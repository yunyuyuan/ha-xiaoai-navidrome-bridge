"""Diagnostics support for XiaoAI Navidrome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CONVERSATION_SENSOR,
    CONF_EMBEDDING_API_KEY,
    CONF_EMBEDDING_URL,
    CONF_MEDIA_PLAYER,
    CONF_NAVIDROME_URL,
    CONF_PASSWORD,
    CONF_PLAYLIST_PHRASE,
    CONF_SHARE_URL,
    CONF_TRACK_PHRASE,
    DOMAIN,
)

_REDACT = {
    CONF_PASSWORD,
    CONF_EMBEDDING_API_KEY,
    CONF_NAVIDROME_URL,
    CONF_SHARE_URL,
    CONF_EMBEDDING_URL,
    CONF_MEDIA_PLAYER,
    CONF_CONVERSATION_SENSOR,
    CONF_TRACK_PHRASE,
    CONF_PLAYLIST_PHRASE,
    "username",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """Return diagnostics without credentials, queries or personal media metadata."""
    runtime = hass.data[DOMAIN]["entries"][entry.entry_id]
    queue = runtime.queue.status()
    index = runtime.index_status()
    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "options": dict(entry.options)},
            _REDACT,
        ),
        "index": {
            "enabled": index["enabled"],
            "ready": index["ready"],
            "track_count": index["track_count"],
            "embedded_count": index["embedded_count"],
            "last_sync": index["last_sync"],
            "syncing": index["syncing"],
            "has_error": bool(index["last_error"]),
        },
        "queue": {
            "state": queue["state"],
            "item_count": len(queue["items"]),
            "current_index": queue["current_index"],
            "shuffle": queue["shuffle"],
            "repeat": queue["repeat"],
            "has_media_player": bool(queue["media_player"]),
            "revision": queue["revision"],
            "has_error": bool(queue["last_error"]),
        },
    }
