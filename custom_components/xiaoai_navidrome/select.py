"""Playlist launcher select entity for XiaoAI Navidrome."""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .model import NavidromeError, Playlist

if TYPE_CHECKING:
    from .runtime import XiaoAINavidromeRuntime

_IDLE_OPTION = "—"
_MAX_OPTION_LENGTH = 96


def _playlist_label(name: str) -> str:
    """Return a compact label without control or directional characters."""
    cleaned = "".join(
        " " if unicodedata.category(character).startswith("C") else character for character in name
    )
    return " ".join(cleaned.split())[:_MAX_OPTION_LENGTH] or "未命名歌单"


def _playlist_options(playlists: list[Playlist]) -> tuple[list[str], dict[str, str]]:
    """Create unique, stable labels without exposing playlist IDs."""
    options = [_IDLE_OPTION]
    playlist_ids: dict[str, str] = {}
    ordered = sorted(
        playlists,
        key=lambda item: (_playlist_label(item.name or "").casefold(), item.id),
    )
    for playlist in ordered:
        base = _playlist_label(playlist.name or "")
        label = base
        suffix = 2
        while label in playlist_ids or label == _IDLE_OPTION:
            label = f"{base} ({suffix})"
            suffix += 1
        options.append(label)
        playlist_ids[label] = playlist.id
    return options, playlist_ids


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the playlist launcher for one config entry."""
    runtime: XiaoAINavidromeRuntime = hass.data[DOMAIN]["entries"][entry.entry_id]
    async_add_entities([XiaoAINavidromePlaylistSelect(runtime, entry)])


class XiaoAINavidromePlaylistSelect(SelectEntity):
    """Launch one exact Navidrome playlist from a native HA select."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:playlist-play"
    _attr_should_poll = False
    _attr_suggested_object_id = "xiaoai_navidrome_play_playlist"
    _attr_translation_key = "play_playlist"

    def __init__(self, runtime: XiaoAINavidromeRuntime, entry: ConfigEntry) -> None:
        """Initialize the playlist launcher."""
        self._runtime = runtime
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_play_playlist"
        self._attr_options = [_IDLE_OPTION]
        self._attr_current_option = _IDLE_OPTION
        self._attr_available = False
        self._playlist_ids: dict[str, str] = {}

    async def async_added_to_hass(self) -> None:
        """Load current options and subscribe to event-driven playlist changes."""
        await super().async_added_to_hass()
        try:
            await self._async_refresh_options()
        except NavidromeError:
            self._attr_available = False
        self.async_on_remove(self._runtime.add_playlist_listener(self._playlists_changed))

    @callback
    def _playlists_changed(self) -> None:
        """Refresh after Panel or service activity discovers a changed playlist list."""
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Refresh options from the runtime's short-lived playlist cache."""
        await self._async_refresh_options()

    async def _async_refresh_options(self) -> None:
        playlists = await self._runtime.async_playlists()
        self._attr_options, self._playlist_ids = _playlist_options(playlists)
        self._attr_current_option = _IDLE_OPTION
        self._attr_available = True

    async def async_select_option(self, option: str) -> None:
        """Replace the shared queue with the selected exact playlist."""
        if option == _IDLE_OPTION:
            return
        playlist_id = self._playlist_ids.get(option)
        if playlist_id is None:
            raise HomeAssistantError("The selected playlist is no longer available")
        context = self._context or Context()
        if context.user_id:
            user = await self.hass.auth.async_get_user(context.user_id)
            if user is None or not user.is_admin:
                raise Unauthorized(
                    context=context,
                    entity_id=self.entity_id,
                    config_entry_id=self._entry_id,
                )
        await self._runtime.async_add_playlist(
            playlist_id,
            "replace",
            expected_revision=self._runtime.queue.revision,
            context=context,
        )
        self._attr_current_option = _IDLE_OPTION
        self.async_write_ha_state()


__all__ = ["XiaoAINavidromePlaylistSelect", "async_setup_entry"]
