"""Tests for the UI-only XiaoAI Navidrome configuration flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.xiaoai_navidrome.const import DOMAIN
from custom_components.xiaoai_navidrome.model import NavidromeAuthError
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

CONNECTION = {
    "navidrome_url": "https://navidrome.invalid/music/",
    "username": "synthetic-user",
    "password": "synthetic-password",
    "verify_ssl": True,
}
PLAYBACK = {
    "media_player": "media_player.synthetic_speaker",
    "track_phrase": "播放家庭音乐",
    "playlist_phrase": "播放家庭歌单",
    "max_bit_rate": 128,
    "share_ttl_hours": 6,
    "queue_max_tracks": 500,
    "playlist_gap_seconds": 2,
    "index_refresh_minutes": 30,
    "embedding_enabled": False,
    "embedding_provider": "ollama",
    "embedding_model": "synthetic-embedding-model",
}


async def test_user_flow_configures_connection_and_playback(hass: HomeAssistant) -> None:
    """One UI flow creates a complete entry without YAML or secrets files."""
    with patch(
        "custom_components.xiaoai_navidrome.config_flow._validate_connection",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "playback"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], PLAYBACK)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "XiaoAI Navidrome"
    assert result["data"]["navidrome_url"] == "https://navidrome.invalid/music"
    assert result["options"]["media_player"] == "media_player.synthetic_speaker"
    assert "media_player" not in result["data"]
    assert "home_assistant_token" not in result["data"]


async def test_user_flow_reports_invalid_credentials(hass: HomeAssistant) -> None:
    """Authentication failures remain on the connection step."""
    with patch(
        "custom_components.xiaoai_navidrome.config_flow._validate_connection",
        new=AsyncMock(side_effect=NavidromeAuthError("rejected")),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_can_clear_optional_values_and_api_key(hass: HomeAssistant) -> None:
    """Blank optional selectors override old values instead of falling back to data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            **CONNECTION,
            "navidrome_url": "https://navidrome.invalid/music",
        },
        options={
            **PLAYBACK,
            "conversation_sensor": "sensor.synthetic_conversation",
            "embedding_url": "http://embedding.invalid:11434",
            "embedding_api_key": "synthetic-secret",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    submitted = {
        **PLAYBACK,
        "clear_embedding_api_key": True,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], submitted)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "conversation_sensor" not in result["data"]
    assert "embedding_url" not in result["data"]
    assert "embedding_api_key" not in result["data"]
    assert "clear_embedding_api_key" not in result["data"]


async def test_reconfigure_can_remove_public_share_url(hass: HomeAssistant) -> None:
    """Replacing connection data removes a previously configured public ShareURL."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            **CONNECTION,
            "navidrome_url": "https://navidrome.invalid/music",
            "share_url": "https://media.invalid/music",
        },
        options=PLAYBACK,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.xiaoai_navidrome.config_flow._validate_connection",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **CONNECTION,
                "navidrome_url": "https://navidrome.invalid/music",
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert "share_url" not in entry.data


async def test_user_flow_reports_malformed_url_without_crashing(
    hass: HomeAssistant,
) -> None:
    """Invalid ports and IPv6 syntax remain ordinary form validation errors."""
    for url in ("https://navidrome.invalid:bad", "https://[::1/music"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CONNECTION, "navidrome_url": url},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_url"}
