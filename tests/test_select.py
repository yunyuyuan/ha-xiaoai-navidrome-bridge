"""Tests for the native playlist launcher select entity."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from custom_components.xiaoai_navidrome.const import DOMAIN
from custom_components.xiaoai_navidrome.model import Playlist
from custom_components.xiaoai_navidrome.runtime import XiaoAINavidromeRuntime
from custom_components.xiaoai_navidrome.select import (
    XiaoAINavidromePlaylistSelect,
    _playlist_options,
)
from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized
from pytest_homeassistant_custom_component.common import MockConfigEntry


def test_playlist_options_are_sorted_unique_and_hide_ids() -> None:
    """Duplicate names remain selectable without exposing backend IDs."""
    options, playlist_ids = _playlist_options(
        [
            Playlist("playlist-b", "Synthetic Mix"),
            Playlist("playlist-c", ""),
            Playlist("playlist-a", "Synthetic Mix"),
            Playlist("playlist-d", "\u202eVisible\u0000 Label"),
            Playlist("playlist-e", "L" * 120),
        ]
    )

    assert options == [
        "play_playlist",
        "L" * 96,
        "Synthetic Mix",
        "Synthetic Mix (2)",
        "Unnamed playlist",
        "Visible Label",
    ]
    assert playlist_ids == {
        "L" * 96: "playlist-e",
        "Synthetic Mix": "playlist-a",
        "Synthetic Mix (2)": "playlist-b",
        "Unnamed playlist": "playlist-c",
        "Visible Label": "playlist-d",
    }
    assert all("playlist-" not in option for option in options)


@pytest.mark.parametrize("name", ["play_playlist", "Play playlist", "播放歌单"])
def test_playlist_name_does_not_collide_with_idle_prompt(name: str) -> None:
    """A playlist matching either translated prompt remains independently selectable."""
    options, playlist_ids = _playlist_options([Playlist("playlist-one", name)])

    assert options == ["play_playlist", f"{name} (2)"]
    assert playlist_ids == {f"{name} (2)": "playlist-one"}


async def test_runtime_notifies_playlist_entities_only_when_choices_change() -> None:
    """Panel refreshes update native select options without a polling loop."""
    runtime = object.__new__(XiaoAINavidromeRuntime)
    runtime._playlists_cache = (0.0, [])
    runtime._playlists_lock = asyncio.Lock()
    runtime._playlist_listeners = set()
    runtime.navidrome = SimpleNamespace(
        async_playlists=AsyncMock(
            side_effect=[
                [Playlist("playlist-one", "Synthetic One")],
                [Playlist("playlist-one", "Synthetic One")],
                [Playlist("playlist-two", "Synthetic Two")],
            ]
        )
    )
    notifications = 0

    def notified() -> None:
        nonlocal notifications
        notifications += 1

    remove = runtime.add_playlist_listener(notified)
    await runtime._async_playlists(fresh=True)
    await runtime._async_playlists(fresh=True)
    assert notifications == 1
    remove()
    await runtime._async_playlists(fresh=True)
    assert notifications == 1


async def test_concurrent_playlist_refreshes_share_the_newest_result() -> None:
    """Concurrent fresh reads cannot overwrite the cache out of order."""
    runtime = object.__new__(XiaoAINavidromeRuntime)
    runtime._playlists_cache = (0.0, [])
    runtime._playlists_lock = asyncio.Lock()
    runtime._playlist_listeners = set()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def load_playlists() -> list[Playlist]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return [Playlist("playlist-one", "Synthetic One")]

    runtime.navidrome = SimpleNamespace(async_playlists=load_playlists)
    first = asyncio.create_task(runtime._async_playlists(fresh=True))
    await started.wait()
    second = asyncio.create_task(runtime._async_playlists(fresh=True))
    release.set()

    first_result, second_result = await asyncio.gather(first, second)
    assert calls == 1
    assert first_result == second_result


async def test_playlist_select_plays_exact_choice_and_requires_admin(
    hass: HomeAssistant,
) -> None:
    """The native selector launches an exact playlist and keeps admin boundaries."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="synthetic-entry")
    runtime = SimpleNamespace(
        async_playlists=AsyncMock(return_value=[Playlist("playlist-one", "Synthetic Playlist")]),
        add_playlist_listener=lambda _listener: lambda: None,
        async_add_playlist=AsyncMock(return_value={"state": "playing"}),
        queue=SimpleNamespace(revision=7),
    )
    entity = XiaoAINavidromePlaylistSelect(runtime, entry)  # type: ignore[arg-type]
    entity.hass = hass
    entity.entity_id = "select.synthetic_playlist"
    entity.async_write_ha_state = Mock()
    await entity._async_refresh_options()

    admin = await hass.auth.async_create_user("synthetic-admin", group_ids=[GROUP_ID_ADMIN])
    entity.async_set_context(Context(user_id=admin.id))
    await entity.async_select_option("Synthetic Playlist")

    runtime.async_add_playlist.assert_awaited_once_with(
        "playlist-one",
        "replace",
        expected_revision=7,
        context=entity._context,
    )
    assert entity.current_option == "play_playlist"
    entity.async_write_ha_state.assert_called_once()

    regular = await hass.auth.async_create_user("synthetic-regular")
    entity.async_set_context(Context(user_id=regular.id))
    with pytest.raises(Unauthorized):
        await entity.async_select_option("Synthetic Playlist")
    assert runtime.async_add_playlist.await_count == 1
