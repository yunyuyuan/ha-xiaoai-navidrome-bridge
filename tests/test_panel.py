"""Tests for the native Home Assistant sidebar panel."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from custom_components.xiaoai_navidrome import async_setup_entry
from custom_components.xiaoai_navidrome.const import DOMAIN
from custom_components.xiaoai_navidrome.panel import async_register_panel, normalize_panel_title
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


def test_panel_title_removes_controls_and_uses_a_bounded_default() -> None:
    """Sidebar titles cannot carry controls, direction overrides, or unbounded text."""
    assert normalize_panel_title("  Synthetic\u202e   Music\x00  ") == "Synthetic Music"
    assert normalize_panel_title("\u202e\x00") == "小爱音乐"
    assert normalize_panel_title(None) == "小爱音乐"
    assert len(normalize_panel_title("x" * 80)) == 40


async def test_panel_registration_uses_the_configured_title() -> None:
    """One sanitized title names both the sidebar item and the panel header."""
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
    )
    with (
        patch("custom_components.xiaoai_navidrome.panel.frontend.async_remove_panel") as remove,
        patch(
            "custom_components.xiaoai_navidrome.panel.panel_custom.async_register_panel",
            new=AsyncMock(),
        ) as register,
    ):
        await async_register_panel(hass, "entry-one", "  Synthetic\u202e  Music  ")  # type: ignore[arg-type]

    hass.http.async_register_static_paths.assert_awaited_once()
    remove.assert_called_once()
    register.assert_awaited_once()
    kwargs = register.await_args.kwargs
    assert kwargs["sidebar_title"] == "Synthetic Music"
    assert kwargs["config"] == {"entry_id": "entry-one", "title": "Synthetic Music"}


async def test_hidden_panel_does_not_block_runtime_setup(hass: HomeAssistant) -> None:
    """Hiding the sidebar leaves the integration runtime available."""
    hass.data.setdefault(DOMAIN, {}).setdefault("entries", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "navidrome_url": "https://navidrome.invalid",
            "username": "synthetic-user",
            "password": "synthetic-password",
            "verify_ssl": True,
        },
        options={
            "media_player": "media_player.synthetic",
            "panel_enabled": False,
            "panel_title": "Synthetic Music",
        },
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
            new=AsyncMock(),
        ) as register,
    ):
        assert await async_setup_entry(hass, entry)

    runtime.async_setup.assert_awaited_once()
    register.assert_not_awaited()
    assert hass.data[DOMAIN]["entries"][entry.entry_id] is runtime


async def test_visible_panel_uses_the_configured_title(hass: HomeAssistant) -> None:
    """Runtime setup forwards the configured sidebar title to panel registration."""
    hass.data.setdefault(DOMAIN, {}).setdefault("entries", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "navidrome_url": "https://navidrome.invalid",
            "username": "synthetic-user",
            "password": "synthetic-password",
            "verify_ssl": True,
        },
        options={
            "media_player": "media_player.synthetic",
            "panel_enabled": True,
            "panel_title": "Synthetic Music",
        },
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
            new=AsyncMock(),
        ) as register,
    ):
        assert await async_setup_entry(hass, entry)

    register.assert_awaited_once_with(hass, entry.entry_id, "Synthetic Music")
