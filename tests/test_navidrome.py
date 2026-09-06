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

from custom_components.xiaoai_navidrome.model import (
    LyricLine,
    Lyrics,
    NavidromeProtocolError,
    Track,
)
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


def test_structured_lyrics_use_exact_track_id_and_prefer_synced_lines() -> None:
    """Lyrics capability discovery is cached and synchronized main lyrics win."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/rest/getOpenSubsonicExtensions.view"):
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "openSubsonicExtensions": [
                            {"name": "songLyrics", "versions": ["1", 2]},
                        ],
                    }
                }
            )
        assert path.endswith("/rest/getLyricsBySongId.view")
        assert request["params"]["id"] == "track-lyrics"
        assert "enhanced" not in request["params"]
        return _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "lyricsList": {
                        "structuredLyrics": [
                            {
                                "lang": "eng",
                                "synced": False,
                                "line": [{"value": "Static line"}],
                            },
                            {
                                "kind": "translation",
                                "lang": "eng",
                                "synced": True,
                                "line": [{"start": 500, "value": "Ignored translation"}],
                            },
                            {
                                "kind": "main",
                                "lang": "xxx",
                                "offset": "125",
                                "synced": "true",
                                "line": [
                                    {"start": "2000", "value": "Second line"},
                                    {"start": 1500, "value": "Middle\u061c line\u200f"},
                                    {"start": 1000, "value": " First\u0000 line\u202e "},
                                    {"start": -1, "value": "Invalid timing"},
                                ],
                            },
                        ]
                    },
                }
            }
        )

    client, session = _client(responder)
    lyrics = asyncio.run(client.async_lyrics("track-lyrics"))
    repeated = asyncio.run(client.async_lyrics("track-lyrics"))

    assert lyrics == Lyrics(
        track_id="track-lyrics",
        state="ready",
        synced=True,
        offset_ms=125,
        language="und",
        lines=(
            LyricLine("First  line", 1000),
            LyricLine("Middle  line", 1500),
            LyricLine("Second line", 2000),
        ),
    )
    assert repeated == lyrics
    assert [urlsplit(request["url"]).path for request in session.requests].count(
        "/library/rest/getOpenSubsonicExtensions.view"
    ) == 1


def test_lyrics_return_supported_empty_and_unsupported_states() -> None:
    """A legal empty response differs from a server without songLyrics support."""

    def empty_responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        payload: Mapping[str, Any]
        if path.endswith("/rest/getOpenSubsonicExtensions.view"):
            payload = {
                "subsonic-response": {
                    "status": "ok",
                    "openSubsonicExtensions": [{"name": "songLyrics", "versions": [1]}],
                }
            }
        else:
            payload = {"subsonic-response": {"status": "ok", "lyricsList": {}}}
        return _json_response(payload)

    empty_client, empty_session = _client(empty_responder)
    assert asyncio.run(empty_client.async_lyrics("track-empty")).to_dict() == {
        "track_id": "track-empty",
        "state": "empty",
        "synced": False,
        "offset_ms": 0,
        "language": "und",
        "lines": [],
    }
    assert len(empty_session.requests) == 2

    unsupported_client, unsupported_session = _client(
        lambda **_: _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "openSubsonicExtensions": [{"name": "other", "versions": [1]}],
                }
            }
        )
    )
    assert asyncio.run(unsupported_client.async_lyrics("track-unsupported")).state == "unsupported"
    assert len(unsupported_session.requests) == 1


def test_lyrics_reject_malformed_structures_without_caching_unsupported() -> None:
    """Malformed required containers remain retryable protocol errors."""
    malformed_extensions_client, malformed_extensions_session = _client(
        lambda **_: _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "openSubsonicExtensions": {"name": "songLyrics", "versions": [1]},
                }
            }
        )
    )
    for _ in range(2):
        with pytest.raises(NavidromeProtocolError, match="invalid extension list"):
            asyncio.run(malformed_extensions_client.async_lyrics("track-malformed"))
    assert len(malformed_extensions_session.requests) == 2

    invalid_versions_client, _ = _client(
        lambda **_: _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "openSubsonicExtensions": [{"name": "songLyrics", "versions": "invalid"}],
                }
            }
        )
    )
    with pytest.raises(NavidromeProtocolError, match="invalid songLyrics versions"):
        asyncio.run(invalid_versions_client.async_lyrics("track-malformed"))

    def malformed_lyrics_responder(**request: Any) -> _Response:
        if urlsplit(request["url"]).path.endswith("/rest/getOpenSubsonicExtensions.view"):
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "openSubsonicExtensions": [{"name": "songLyrics", "versions": [1]}],
                    }
                }
            )
        return _json_response({"subsonic-response": {"status": "ok", "lyricsList": "invalid"}})

    malformed_lyrics_client, _ = _client(malformed_lyrics_responder)
    with pytest.raises(NavidromeProtocolError, match="does not contain lyricsList"):
        asyncio.run(malformed_lyrics_client.async_lyrics("track-malformed"))

    def malformed_structured_responder(**request: Any) -> _Response:
        if urlsplit(request["url"]).path.endswith("/rest/getOpenSubsonicExtensions.view"):
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "openSubsonicExtensions": [{"name": "songLyrics", "versions": [1]}],
                    }
                }
            )
        return _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "lyricsList": {"structuredLyrics": "invalid"},
                }
            }
        )

    malformed_structured_client, _ = _client(malformed_structured_responder)
    with pytest.raises(NavidromeProtocolError, match="invalid structured lyrics"):
        asyncio.run(malformed_structured_client.async_lyrics("track-malformed"))


def test_concurrent_lyrics_requests_share_capability_discovery() -> None:
    """Concurrent reads perform one extension discovery and independent lyric requests."""

    def responder(**request: Any) -> _Response:
        if urlsplit(request["url"]).path.endswith("/rest/getOpenSubsonicExtensions.view"):
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "openSubsonicExtensions": [{"name": "songLyrics", "versions": [1]}],
                    }
                }
            )
        return _json_response({"subsonic-response": {"status": "ok", "lyricsList": {}}})

    client, session = _client(responder)

    async def fetch_both() -> tuple[Lyrics, Lyrics]:
        first, second = await asyncio.gather(
            client.async_lyrics("track-one"),
            client.async_lyrics("track-two"),
        )
        return first, second

    first, second = asyncio.run(fetch_both())
    assert (first.track_id, second.track_id) == ("track-one", "track-two")
    paths = [urlsplit(request["url"]).path for request in session.requests]
    assert paths.count("/library/rest/getOpenSubsonicExtensions.view") == 1
    assert paths.count("/library/rest/getLyricsBySongId.view") == 2


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ([{"value": "x" * 1024}] * 513, "text exceeds"),
        ([{"value": "x"}] * 5001, "too many lines"),
    ],
)
def test_lyrics_reject_total_text_and_line_count_limits(
    lines: list[dict[str, str]], message: str
) -> None:
    """Structured lyrics remain bounded even when every individual line is small."""

    def responder(**request: Any) -> _Response:
        if urlsplit(request["url"]).path.endswith("/rest/getOpenSubsonicExtensions.view"):
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "openSubsonicExtensions": [{"name": "songLyrics", "versions": [1]}],
                    }
                }
            )
        return _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "lyricsList": {"structuredLyrics": {"synced": False, "line": lines}},
                }
            }
        )

    client, _ = _client(responder)
    with pytest.raises(NavidromeProtocolError, match=message):
        asyncio.run(client.async_lyrics("track-bounded"))


def test_lyrics_use_dedicated_response_body_limit() -> None:
    """Lyrics endpoints cannot consume the general-purpose JSON response allowance."""

    def responder(**request: Any) -> _Response:
        if urlsplit(request["url"]).path.endswith("/rest/getOpenSubsonicExtensions.view"):
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "openSubsonicExtensions": [{"name": "songLyrics", "versions": [1]}],
                    }
                }
            )
        return _Response(200, b"x" * (1024 * 1024 + 1))

    client, _ = _client(responder)
    with pytest.raises(NavidromeProtocolError, match="1048576 byte limit"):
        asyncio.run(client.async_lyrics("track-large-response"))


def test_lyrics_reject_excessive_text_and_stay_out_of_track_storage() -> None:
    """Untrusted lyrics are bounded and never alter the persistent Track shape."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/rest/getOpenSubsonicExtensions.view"):
            return _json_response(
                {
                    "subsonic-response": {
                        "status": "ok",
                        "openSubsonicExtensions": [{"name": "songLyrics", "versions": [1]}],
                    }
                }
            )
        return _json_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "lyricsList": {
                        "structuredLyrics": {
                            "synced": False,
                            "line": {"value": "x" * 4097},
                        }
                    },
                }
            }
        )

    client, _ = _client(responder)
    with pytest.raises(NavidromeProtocolError, match="excessively long line"):
        asyncio.run(client.async_lyrics("track-large"))
    assert "lyrics" not in Track("track-storage").to_dict()


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


def test_private_m3u_origin_is_rewritten_to_public_share_origin() -> None:
    """The API origin supplies a trusted path that is rewritten for the speaker."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        if path.endswith("/api/share/"):
            return _json_response({"id": "share-synthetic"})
        return _Response(
            200,
            b"http://127.0.0.1:4533/share/s/signed-track.mp3\n",
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


def test_m3u_public_origin_is_replaced_by_configured_speaker_origin() -> None:
    """A valid share path from another proxy is emitted through the configured proxy."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        if path.endswith("/api/share/"):
            return _json_response({"id": "share-synthetic"})
        return _Response(
            200,
            b"https://internal-proxy.synthetic/share/s/signed-track.mp3\n",
        )

    client, _ = _client(
        responder,
        base_url="https://internal-proxy.synthetic",
        share_url="https://speaker-proxy.synthetic",
    )
    urls = asyncio.run(client.create_share(["track-one"], timedelta(minutes=5), 128))
    assert urls == ["https://speaker-proxy.synthetic/share/s/signed-track.mp3"]


def test_private_api_infers_one_public_origin_from_m3u() -> None:
    """A private API URL accepts one consistent public origin returned by Navidrome."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        if path.endswith("/api/share/"):
            return _json_response({"id": "share-synthetic"})
        return _Response(
            200,
            b"https://media.synthetic.invalid/music/share/s/one.mp3\n"
            b"https://media.synthetic.invalid/music/share/s/two.mp3\n",
        )

    client, session = _client(responder, base_url="http://127.0.0.1:4533")
    urls = asyncio.run(client.create_share(["track-one", "track-two"], timedelta(minutes=5), 128))
    assert urls == [
        "https://media.synthetic.invalid/music/share/s/one.mp3",
        "https://media.synthetic.invalid/music/share/s/two.mp3",
    ]
    assert all(request["url"].startswith("http://127.0.0.1:4533/") for request in session.requests)


@pytest.mark.parametrize(
    "entry",
    [
        "/library/share/s/share-synthetic/file.mp3?leak=1",
        "/library/share/s/%2e%2e/api/share/file.mp3",
        "/library/share/s/a/../file.mp3",
        "/library/share/s/a/%2e%2e/file.mp3",
        "/library/share/s/%252e%252e/%252e%252e/private.mp3",
        "/library/share/s/a%5c..%5c..%5cprivate.mp3",
        "/library/share/s/a%00b/file.mp3",
        "/library/sha\tre/s/share-synthetic/file.mp3",
        "https://[::1/library/share/s/file.mp3",
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

    client, _ = _client(responder, share_url="https://synthetic.invalid/library")
    with pytest.raises(NavidromeProtocolError):
        asyncio.run(client.create_share(["track-one"], timedelta(minutes=5), 128))


@pytest.mark.parametrize(
    "entry",
    [
        "https://synthetic.invalid/library/sha\tre/s/signed-track.mp3",
        "https://synthetic.invalid/library/sha\x00re/s/signed-track.mp3",
    ],
)
def test_raw_control_characters_are_rejected_before_url_parsing(entry: str) -> None:
    """URL parsing cannot erase raw control characters before validation."""

    client, _ = _client(lambda **_: _json_response({}))
    with pytest.raises(NavidromeProtocolError) as raised:
        client._rewrite_share_url(entry)

    assert raised.value.reason == "share_m3u_url"


def test_inferred_share_origin_must_be_consistent() -> None:
    """Automatic public-origin discovery cannot mix hosts within one M3U."""

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        if path.endswith("/api/share/"):
            return _json_response({"id": "share-synthetic"})
        return _Response(
            200,
            b"https://media-one.synthetic/music/share/s/one.mp3\n"
            b"https://media-two.synthetic/music/share/s/two.mp3\n",
        )

    client, _ = _client(responder, base_url="http://127.0.0.1:4533")
    with pytest.raises(NavidromeProtocolError, match="outside the Navidrome origin"):
        asyncio.run(client.create_share(["track-one", "track-two"], timedelta(minutes=5), 128))


def test_m3u_http_error_does_not_expose_share_identifier() -> None:
    """The client error source itself cannot expose a temporary share identifier."""
    private_id = "synthetic-private-share-capability"

    def responder(**request: Any) -> _Response:
        path = urlsplit(request["url"]).path
        if path.endswith("/auth/login"):
            return _json_response({"token": "synthetic-token"})
        if path.endswith("/api/share/"):
            return _json_response({"id": private_id})
        return _Response(500, b"synthetic failure")

    client, _ = _client(responder, base_url="http://127.0.0.1:4533")
    with pytest.raises(NavidromeProtocolError) as raised:
        asyncio.run(client.create_share(["track-one"], timedelta(minutes=5), 128))

    assert private_id not in str(raised.value)
    assert str(raised.value) == "Navidrome GET request returned HTTP 500"


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


def test_cover_art_requests_selected_thumbnail_size() -> None:
    """Cover retrieval delegates density-aware scaling to Navidrome."""

    def responder(**request: Any) -> _Response:
        assert request["url"].endswith("/library/rest/getCoverArt.view")
        assert request["params"]["id"] == "synthetic-cover"
        assert request["params"]["size"] == "320"
        return _Response(200, b"\xff\xd8\xffsynthetic")

    client, _ = _client(responder)
    content, content_type = asyncio.run(client.async_cover_art("synthetic-cover", 320))
    assert content == b"\xff\xd8\xffsynthetic"
    assert content_type == "image/jpeg"


def test_share_origin_normalizes_default_https_port() -> None:
    """Explicit :443 and an omitted HTTPS port represent the same origin."""

    client, _ = _client(lambda **_: _json_response({}))
    assert (
        client._rewrite_share_url("https://synthetic.invalid:443/library/share/s/signed-track.mp3")
        == "https://synthetic.invalid/library/share/s/signed-track.mp3"
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
