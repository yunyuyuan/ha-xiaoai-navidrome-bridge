"""Synthetic unit tests for the asynchronous Navidrome client."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import timedelta
from hashlib import md5
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("aiohttp")

from custom_components.xiaoai_navidrome.model import NavidromeProtocolError, Track
from custom_components.xiaoai_navidrome.navidrome import NavidromeClient


class _Content:
    """Minimal asynchronous response content used without network I/O."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, amount: int = -1) -> bytes:
        """Return the requested bounded byte sequence."""
        return self._body if amount < 0 else self._body[:amount]

    async def iter_chunked(self, amount: int) -> AsyncIterator[bytes]:
        """Yield every byte in deterministic chunks until EOF."""
        for offset in range(0, len(self._body), amount):
            yield self._body[offset : offset + amount]


class _Response:
    """Minimal aiohttp response context manager for deterministic tests."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.content_length = len(body)
        self.content = _Content(body)

    async def __aenter__(self) -> _Response:
        """Enter the response context."""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """Leave the response context."""


class _Session:
    """An injected session that dispatches synthetic responses by test callback."""

    def __init__(self, responder: Callable[..., _Response]) -> None:
        self._responder = responder
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        """Record and return one synthetic aiohttp request context manager."""
        request = {"method": method, "url": url, **kwargs}
        self.requests.append(request)
        return self._responder(**request)


def _json_response(payload: Mapping[str, Any], status: int = 200) -> _Response:
    """Construct a JSON synthetic response."""
    return _Response(status, json.dumps(payload).encode())


def _client(
    responder: Callable[..., _Response],
    *,
    base_url: str = "https://synthetic.invalid/library",
    share_url: str | None = None,
) -> tuple[NavidromeClient, _Session]:
    """Create a client using a synthetic reverse-proxy base path."""
    session = _Session(responder)
    return (
        NavidromeClient(
            base_url,
            "synthetic_user",
            "synthetic_password",
            session,  # type: ignore[arg-type] -- deliberately minimal injected fake.
            share_url=share_url,
        ),
        session,
    )


def test_subsonic_token_parameters() -> None:
    """Subsonic authentication includes the specified token-and-salt fields."""
    client, _ = _client(lambda **_: _json_response({}))
    params = client._subsonic_auth_params()
    assert params["u"] == "synthetic_user"
    assert params["v"] == "1.16.1"
    assert params["c"] == "xiaoai-navidrome"
    assert params["f"] == "json"
    assert (
        params["t"]
        == md5(f"synthetic_password{params['s']}".encode(), usedforsecurity=False).hexdigest()
    )


def test_nullable_field_parsing_and_paging() -> None:
    """Singleton/list payloads and string numbers parse safely across pages."""

    def responder(**request: Any) -> _Response:
        params = request["params"]
        assert request["url"].endswith("/library/rest/search3.view")
        assert params["query"] == ""
        if params["songOffset"] == "0":
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "searchResult3": {
                            "song": [
                                {
                                    "id": "track-one",
                                    "title": None,
                                    "duration": "203",
                                    "year": "2025",
                                    "track": "7",
                                    "discNumber": "2",
                                    "bitRate": "320",
                                    "size": "4096",
                                },
                                {"id": "track-two", "duration": "not-a-number"},
                            ]
                        },
                    }
                }
            )
        return _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "searchResult3": {"song": {"id": "track-three", "duration": 1.0}},
                }
            }
        )

    client, session = _client(responder)
    tracks = asyncio.run(client.all_tracks(2))
    assert [track.id for track in tracks] == ["track-one", "track-two", "track-three"]
    assert tracks[0].to_dict()["duration"] == 203
    assert tracks[0].year == 2025
    assert tracks[0].track_number == 7
    assert tracks[0].disc_number == 2
    assert tracks[0].size == 4096
    assert tracks[1].duration == 0
    assert len(session.requests) == 2


def test_native_login_create_and_m3u() -> None:
    """A native share logs in, posts the required payload, and preserves M3U order."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            assert request["json"] == {
                "username": "synthetic_user",
                "password": "synthetic_password",
            }
            return _json_response({"data": {"token": "synthetic-token"}})
        if path.endswith("/api/share/"):
            payload = request["json"]
            assert payload["description"] == "Home Assistant playback"
            assert payload["resourceType"] == "media_file"
            assert payload["resourceIds"] == "track-one,track-two"
            assert payload["format"] == "mp3"
            assert payload["maxBitRate"] == 192
            assert payload["expiresAt"].endswith("Z")
            assert request["headers"]["X-ND-Authorization"] == "Bearer synthetic-token"
            assert request["headers"]["X-ND-Client-Unique-Id"]
            return _json_response(
                {"id": "share-synthetic", "url": "/library/share/s/share-synthetic"}
            )
        assert path.endswith("/share/share-synthetic/m3u")
        return _Response(
            200,
            b"#EXTM3U\n/library/share/s/share-synthetic/one.mp3\nshare/s/share-synthetic/two.mp3\n",
        )

    client, _ = _client(responder)
    urls = asyncio.run(
        client.create_share([Track("track-one"), "track-two"], timedelta(minutes=5), 192)
    )
    assert urls == [
        "https://synthetic.invalid/library/share/s/share-synthetic/one.mp3",
        "https://synthetic.invalid/library/share/s/share-synthetic/two.mp3",
    ]


def test_separate_public_share_origin_is_accepted() -> None:
    """An explicit ShareURL permits private API access and a public speaker origin."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        if path.endswith("/api/share/"):
            return _json_response({"id": "share-synthetic"})
        return _Response(
            200,
            b"https://media.synthetic.invalid/music/share/s/signed-track.mp3\n",
        )

    client, session = _client(
        responder,
        base_url="http://127.0.0.1:4533",
        share_url="https://media.synthetic.invalid/music",
    )
    urls = asyncio.run(client.create_share(["track-one"], timedelta(minutes=5), 128))
    assert urls == ["https://media.synthetic.invalid/music/share/s/signed-track.mp3"]
    assert session.requests[1]["url"] == "http://127.0.0.1:4533/api/share/"
    assert session.requests[-1]["url"] == "http://127.0.0.1:4533/share/share-synthetic/m3u"


@pytest.mark.parametrize(
    "entry",
    [
        "https://outside.synthetic/share/s/share-synthetic/file.mp3",
        "/library/share/s/share-synthetic/file.mp3?leak=1",
        "/library/share/s/%2e%2e/api/share/file.mp3",
        "https://user@synthetic.invalid/library/share/s/share-synthetic/file.mp3",
    ],
)
def test_hostile_m3u_urls_are_rejected(entry: str) -> None:
    """M3U URLs cannot cross origin, carry credentials/query, or escape the share path."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        if path.endswith("/api/share/"):
            return _json_response({"data": {"id": "share-synthetic"}})
        return _Response(200, f"#EXTM3U\n{entry}\n".encode())

    client, _ = _client(responder)
    with pytest.raises(NavidromeProtocolError):
        asyncio.run(client.create_share(["track-one"], timedelta(minutes=5), 128))


def test_native_401_relogs_in_once() -> None:
    """One expired native token triggers one fresh login and a successful retry."""
    logins = 0
    shares = 0

    def responder(**request: Any) -> _Response:
        nonlocal logins, shares
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            logins += 1
            return _json_response({"token": f"synthetic-token-{logins}"})
        if path.endswith("/api/share/"):
            shares += 1
            if shares == 1:
                return _json_response({"error": "expired"}, status=401)
            assert request["headers"]["X-ND-Authorization"] == "Bearer synthetic-token-2"
            return _json_response({"id": "share-synthetic"})
        return _Response(200, b"/library/share/s/share-synthetic/file.mp3\n")

    client, _ = _client(responder)
    urls = asyncio.run(client.create_share(["track-one"], timedelta(minutes=5), 128))
    assert logins == 2
    assert shares == 2
    assert urls == ["https://synthetic.invalid/library/share/s/share-synthetic/file.mp3"]


def test_cover_art_rejects_unknown_content() -> None:
    """A successful HTML response cannot be relabeled and served as an image."""

    client, _ = _client(lambda **_: _Response(200, b"<html>synthetic error</html>"))
    with pytest.raises(NavidromeProtocolError, match="unsupported image format"):
        asyncio.run(client.async_cover_art("synthetic-cover"))


def test_share_origin_normalizes_default_https_port() -> None:
    """Explicit :443 and an omitted HTTPS port represent the same origin."""

    client, _ = _client(lambda **_: _json_response({}))
    assert (
        client._validate_share_url("https://synthetic.invalid:443/library/share/s/signed-track.mp3")
        == "https://synthetic.invalid:443/library/share/s/signed-track.mp3"
    )


def test_native_login_never_follows_redirects() -> None:
    """A hostile redirect cannot receive the password or native authorization headers."""

    client, session = _client(lambda **_: _Response(307, b"redirect"))
    with pytest.raises(NavidromeProtocolError, match="HTTP 307"):
        asyncio.run(client.async_login())
    assert len(session.requests) == 1
    assert session.requests[0]["allow_redirects"] is False


def test_delete_share_accepts_not_found() -> None:
    """A 404 proves the public capability is already revoked."""

    def responder(**request: Any) -> _Response:
        if request["url"].endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        assert request["method"] == "DELETE"
        assert request["url"].endswith("/api/share/share-missing/")
        return _Response(404, b"not found")

    client, _ = _client(responder)
    asyncio.run(client.async_delete_share("share-missing"))


def test_ping_reads_all_chunked_response_parts() -> None:
    """A legal chunked JSON response is consumed through EOF, not truncated."""
    raw = json.dumps({"subsonic-response": {"status": "ok"}}).encode()

    class ChunkedContent:
        async def iter_chunked(self, _amount: int) -> AsyncIterator[bytes]:
            midpoint = len(raw) // 2
            yield raw[:midpoint]
            await asyncio.sleep(0)
            yield raw[midpoint:]

    class ChunkedResponse(_Response):
        def __init__(self) -> None:
            self.status = 200
            self.content_length = None
            self.content = ChunkedContent()

    client, _ = _client(lambda **_: ChunkedResponse())
    asyncio.run(client.async_ping())
