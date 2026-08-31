"""Authenticated HTTP views for XiaoAI Navidrome."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.core import HomeAssistant

from .const import COVER_API_URL, DOMAIN
from .navidrome import NavidromeAuthError, NavidromeError

MAX_COVER_ID_LENGTH = 512
COVER_ART_SIZES = frozenset({64, 96, 128, 160, 192, 256, 320, 384})
DEFAULT_COVER_ART_SIZE = 64


def requested_cover_size(value: str | None) -> int:
    """Return one bounded thumbnail size accepted by the panel."""
    if value is None:
        return DEFAULT_COVER_ART_SIZE
    try:
        size = int(value)
    except (TypeError, ValueError) as err:
        raise web.HTTPBadRequest(text="Invalid cover size") from err
    if size not in COVER_ART_SIZES:
        raise web.HTTPBadRequest(text="Invalid cover size")
    return size


class XiaoAINavidromeCoverView(HomeAssistantView):
    """Proxy cover art without exposing Navidrome credentials to the browser."""

    name = "api:xiaoai_navidrome:cover"
    url = f"{COVER_API_URL}/{{entry_id}}/{{cover_id}}"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request, entry_id: str, cover_id: str) -> web.Response:
        """Return one cover image."""
        hass: HomeAssistant = request.app["hass"]
        runtime = hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id)
        if runtime is None:
            raise web.HTTPNotFound(text="Integration entry not found")
        if not cover_id or len(cover_id) > MAX_COVER_ID_LENGTH or "/" in cover_id:
            raise web.HTTPBadRequest(text="Invalid cover identifier")
        size = requested_cover_size(request.query.get("size"))
        try:
            content, content_type = await runtime.navidrome.async_cover_art(cover_id, size)
        except NavidromeAuthError as err:
            raise web.HTTPUnauthorized(text="Navidrome authentication failed") from err
        except NavidromeError as err:
            raise web.HTTPBadGateway(text="Unable to load Navidrome cover") from err
        return web.Response(
            body=content,
            content_type=content_type or "image/jpeg",
            headers={
                "Cache-Control": "private, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
        )


def async_register_http_views(hass: HomeAssistant) -> None:
    """Register HTTP views once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("http_registered"):
        return
    hass.http.register_view(XiaoAINavidromeCoverView)
    domain_data["http_registered"] = True
