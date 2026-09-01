"""Register the native Home Assistant sidebar panel."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_PANEL_TITLE,
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
    VERSION,
)

_FRONTEND_DIR = Path(__file__).parent / "frontend"


def normalize_panel_title(value: object) -> str:
    """Return a compact sidebar title without control or directional characters."""
    if value is None:
        return DEFAULT_PANEL_TITLE
    clean = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in str(value)
    )
    return " ".join(clean.split())[:40] or DEFAULT_PANEL_TITLE


async def async_register_panel(hass: HomeAssistant, entry_id: str, title: object) -> None:
    """Serve and register the XiaoAI Navidrome panel."""
    sidebar_title = normalize_panel_title(title)
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    PANEL_STATIC_URL,
                    str(_FRONTEND_DIR),
                    cache_headers=True,
                )
            ]
        )
        domain_data["static_registered"] = True
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=sidebar_title,
        sidebar_icon="mdi:music-circle",
        module_url=f"{PANEL_STATIC_URL}/panel.js?v={VERSION}",
        config={"entry_id": entry_id, "title": sidebar_title},
        require_admin=True,
        handle_safe_area=True,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel while keeping immutable static paths registered."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
