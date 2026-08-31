"""Home Assistant service actions for XiaoAI Navidrome."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import (
    ATTR_ENTRY_ID,
    ATTR_MEDIA_PLAYER,
    ATTR_QUERY,
    DOMAIN,
    SERVICE_CLEAR_QUEUE,
    SERVICE_NEXT,
    SERVICE_PLAY,
    SERVICE_PLAY_PLAYLIST,
    SERVICE_PREVIOUS,
    SERVICE_RESUME,
    SERVICE_STOP,
    SERVICE_SYNC_LIBRARY,
)

if TYPE_CHECKING:
    from .runtime import XiaoAINavidromeRuntime

_ENTRY_SCHEMA: dict[Any, Any] = {vol.Optional(ATTR_ENTRY_ID): cv.string}
_QUERY_SCHEMA: dict[Any, Any] = {
    vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Strip, vol.Length(min=1, max=300)),
    vol.Optional(ATTR_MEDIA_PLAYER): cv.entity_id,
    **_ENTRY_SCHEMA,
}


def _runtime(hass: HomeAssistant, call: ServiceCall) -> XiaoAINavidromeRuntime:
    """Resolve the loaded integration instance targeted by a service call."""
    runtimes = cast(
        "dict[str, XiaoAINavidromeRuntime]",
        hass.data.get(DOMAIN, {}).get("entries", {}),
    )
    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        runtime = runtimes.get(entry_id)
        if runtime is None:
            raise HomeAssistantError("The selected XiaoAI Navidrome entry is not loaded")
        return runtime
    if len(runtimes) != 1:
        raise HomeAssistantError("Select a loaded XiaoAI Navidrome config entry")
    return next(iter(runtimes.values()))


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration-wide service actions exactly once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    async def handle_play(call: ServiceCall) -> ServiceResponse | None:
        runtime = _runtime(hass, call)
        result = await runtime.async_play_query(
            call.data[ATTR_QUERY],
            media_player=call.data.get(ATTR_MEDIA_PLAYER),
            context=call.context,
        )
        return result if call.return_response else None

    async def handle_playlist(call: ServiceCall) -> ServiceResponse | None:
        runtime = _runtime(hass, call)
        result = await runtime.async_play_playlist_query(
            call.data[ATTR_QUERY],
            media_player=call.data.get(ATTR_MEDIA_PLAYER),
            context=call.context,
        )
        return result if call.return_response else None

    async def handle_previous(call: ServiceCall) -> ServiceResponse | None:
        result = await _runtime(hass, call).queue.async_previous(context=call.context)
        return result if call.return_response else None

    async def handle_next(call: ServiceCall) -> ServiceResponse | None:
        result = await _runtime(hass, call).queue.async_next(context=call.context)
        return result if call.return_response else None

    async def handle_resume(call: ServiceCall) -> ServiceResponse | None:
        result = await _runtime(hass, call).queue.async_play(context=call.context)
        return result if call.return_response else None

    async def handle_stop(call: ServiceCall) -> ServiceResponse | None:
        result = await _runtime(hass, call).queue.async_stop(context=call.context)
        return result if call.return_response else None

    async def handle_clear(call: ServiceCall) -> ServiceResponse | None:
        result = await _runtime(hass, call).queue.async_clear(context=call.context)
        return result if call.return_response else None

    async def handle_sync(call: ServiceCall) -> ServiceResponse | None:
        result = await _runtime(hass, call).async_sync_library()
        return result if call.return_response else None

    handlers: dict[str, tuple[Any, dict[Any, Any]]] = {
        SERVICE_PLAY: (handle_play, _QUERY_SCHEMA),
        SERVICE_PLAY_PLAYLIST: (handle_playlist, _QUERY_SCHEMA),
        SERVICE_PREVIOUS: (handle_previous, _ENTRY_SCHEMA),
        SERVICE_NEXT: (handle_next, _ENTRY_SCHEMA),
        SERVICE_RESUME: (handle_resume, _ENTRY_SCHEMA),
        SERVICE_STOP: (handle_stop, _ENTRY_SCHEMA),
        SERVICE_CLEAR_QUEUE: (handle_clear, _ENTRY_SCHEMA),
        SERVICE_SYNC_LIBRARY: (handle_sync, _ENTRY_SCHEMA),
    }
    for name, (handler, schema) in handlers.items():
        async_register_admin_service(
            hass,
            DOMAIN,
            name,
            handler,
            schema=vol.Schema(schema),
            supports_response=SupportsResponse.OPTIONAL,
        )
    domain_data["services_registered"] = True
