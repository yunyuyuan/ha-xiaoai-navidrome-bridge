"""Tests for authenticated XiaoAI Navidrome HTTP views."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web
from custom_components.xiaoai_navidrome.const import DOMAIN
from custom_components.xiaoai_navidrome.http import (
    XiaoAINavidromeCoverView,
    requested_cover_size,
)


def test_requested_cover_size_accepts_panel_thumbnail_sizes() -> None:
    """The proxy accepts only the density-aware sizes emitted by the panel."""
    assert requested_cover_size(None) == 64
    for size in (64, 96, 128, 160, 192, 256, 320, 384):
        assert requested_cover_size(str(size)) == size


@pytest.mark.parametrize("value", ["0", "65", "97", "600", "2048", "invalid"])
def test_requested_cover_size_rejects_arbitrary_resizes(value: str) -> None:
    """Callers cannot turn the authenticated proxy into an unbounded resizer."""
    with pytest.raises(web.HTTPBadRequest) as error:
        requested_cover_size(value)
    assert error.value.text == "Invalid cover size"


@pytest.mark.asyncio
async def test_cover_view_forwards_selected_size() -> None:
    """The authenticated view requests the selected thumbnail from Navidrome."""
    calls: list[tuple[str, int]] = []

    class FakeNavidrome:
        """Record the bounded cover request without network access."""

        async def async_cover_art(self, cover_id: str, size: int) -> tuple[bytes, str]:
            calls.append((cover_id, size))
            return b"\xff\xd8\xffsynthetic", "image/jpeg"

    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "entries": {
                    "entry-one": SimpleNamespace(navidrome=FakeNavidrome()),
                }
            }
        }
    )

    class FakeRequest(dict[str, object]):
        """Provide the request attributes used by the HA view and decorator."""

        def __init__(self) -> None:
            """Initialize authenticated request data and query parameters."""
            super().__init__(hass_user=SimpleNamespace(is_admin=True))
            self.app = {"hass": hass}
            self.query = {"size": "256"}

    request = FakeRequest()
    response = await XiaoAINavidromeCoverView().get(
        request,  # type: ignore[arg-type] -- deliberately minimal request fake.
        "entry-one",
        "cover-one",
    )
    assert calls == [("cover-one", 256)]
    assert response.content_type == "image/jpeg"
    assert response.headers["Cache-Control"] == "private, max-age=86400"
