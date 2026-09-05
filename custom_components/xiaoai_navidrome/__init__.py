"""XiaoAI Navidrome Home Assistant custom integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_PANEL_ENABLED,
    CONF_PANEL_LANGUAGE,
    CONF_PANEL_TITLE,
    DEFAULT_PANEL_ENABLED,
    DEFAULT_PANEL_LANGUAGE,
    DEFAULT_PANEL_TITLE,
    DOMAIN,
)
from .http import async_register_http_views
from .model import NavidromeAuthError, NavidromeConnectionError, NavidromeError
from .panel import async_register_panel, async_unregister_panel
from .runtime import XiaoAINavidromeRuntime
from .services import async_setup_services
from .websocket_api import async_register_websocket_commands

XiaoAINavidromeConfigEntry = ConfigEntry[XiaoAINavidromeRuntime]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SELECT]


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register integration-wide APIs and service actions."""
    hass.data.setdefault(DOMAIN, {}).setdefault("entries", {})
    await async_setup_services(hass)
    async_register_websocket_commands(hass)
    async_register_http_views(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: XiaoAINavidromeConfigEntry) -> bool:
    """Set up one XiaoAI Navidrome config entry."""
    hass.data.setdefault(DOMAIN, {}).setdefault("entries", {})
    runtime = XiaoAINavidromeRuntime(hass, entry)
    try:
        await runtime.async_setup()
    except NavidromeAuthError as err:
        raise ConfigEntryAuthFailed("Navidrome rejected the configured credentials") from err
    except NavidromeConnectionError as err:
        raise ConfigEntryNotReady("Unable to connect to Navidrome") from err
    except NavidromeError as err:
        raise ConfigEntryNotReady("Navidrome returned an invalid response") from err

    entry.runtime_data = runtime
    hass.data[DOMAIN]["entries"][entry.entry_id] = runtime
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if entry.options.get(CONF_PANEL_ENABLED, DEFAULT_PANEL_ENABLED):
            await async_register_panel(
                hass,
                entry.entry_id,
                entry.options.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE),
                entry.options.get(CONF_PANEL_LANGUAGE, DEFAULT_PANEL_LANGUAGE),
            )
    except Exception:
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
        await runtime.async_close()
        async_unregister_panel(hass)
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: XiaoAINavidromeConfigEntry) -> bool:
    """Unload a config entry and cancel its background work."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime = hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    if runtime is not None:
        await runtime.async_close()
    if not hass.data[DOMAIN]["entries"]:
        async_unregister_panel(hass)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: XiaoAINavidromeConfigEntry) -> None:
    """Reload after connection or options changes."""
    await hass.config_entries.async_reload(entry.entry_id)
