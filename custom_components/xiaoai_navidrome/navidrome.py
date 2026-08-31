"""Asynchronous, bounded Navidrome clients for the XiaoAi integration.

The client deliberately keeps the Subsonic and native-share APIs separate: the
former uses the token-and-salt authentication required by Subsonic/OpenSubsonic,
whereas the latter uses Navidrome's native bearer token API.
"""

from __future__ import annotations

import asyncio
import json
import posixpath
import secrets
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from hashlib import md5
from typing import Any, Final
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import aiohttp

from .model import (
    NavidromeAuthError,
    NavidromeConnectionError,
    NavidromeError,
    NavidromeProtocolError,
    Playlist,
    Track,
)

_JSON_LIMIT: Final = 32 * 1024 * 1024
_IMAGE_LIMIT: Final = 8 * 1024 * 1024
_M3U_LIMIT: Final = 4 * 1024 * 1024
_SUBSONIC_VERSION: Final = "1.16.1"
_SUBSONIC_CLIENT: Final = "xiaoai-navidrome"
_AUTH_ERROR_CODES: Final = frozenset({40, 41, 44})
_HTTP_OK: Final = 200
_HTTP_REDIRECT: Final = 300
_HTTP_UNAUTHORIZED: Final = 401
_HTTP_NOT_FOUND: Final = 404


class NavidromeClient:
    """A non-blocking Navidrome client backed by an injected aiohttp session.

    Args:
        base_url: Navidrome's HTTP(S) URL.  A reverse-proxy subpath is retained.
        username: Account name used for both supported API authentication modes.
        password: Account password used for Subsonic token authentication and login.
        session: An application-owned :class:`aiohttp.ClientSession`.
        share_url: Optional public base URL expected in M3U stream entries.
        verify_ssl: When false, pass ``ssl=False`` for every HTTP request.
        request_timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        *,
        share_url: str | None = None,
        verify_ssl: bool = True,
        request_timeout: float = 15.0,
    ) -> None:
        """Initialize a client without performing network I/O."""
        self._base_url, self._base_scheme, self._base_host, self._base_port, self._base_path = (
            self._validate_base_url(base_url)
        )
        (
            self._share_url,
            self._share_scheme,
            self._share_host,
            self._share_port,
            self._share_path,
        ) = self._validate_base_url(share_url or base_url)
        self._username = username
        self._password = password
        self._session = session
        self._verify_ssl = verify_ssl
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        self._request_timeout = request_timeout
        # A stable per-client UUID-like identifier is required by Navidrome shares.
        self._client_unique_id = secrets.token_hex(16)
        self._native_token: str | None = None

    @property
    def client_unique_id(self) -> str:
        """Return the stable random client identifier sent to the native API."""
        return self._client_unique_id

    @staticmethod
    def _validate_base_url(base_url: str) -> tuple[str, str, str, int, str]:
        """Validate and canonicalize a base URL while preserving its subpath."""
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must be a non-empty HTTP(S) URL")
        parts = urlsplit(base_url.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if (
            parts.query
            or parts.fragment
            or parts.username is not None
            or parts.password is not None
        ):
            raise ValueError("base_url must not include query, fragment, or userinfo")
        try:
            host = parts.hostname
            port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        except ValueError as err:
            raise ValueError("base_url has an invalid port") from err
        if not host:
            raise ValueError("base_url must include a host")
        # A trailing slash does not distinguish an application subpath from root.
        path = parts.path.rstrip("/") or ""
        if path and not path.startswith("/"):
            raise ValueError("base_url path must be absolute")
        canonical = urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))
        return canonical, parts.scheme.lower(), host.lower(), port, path

    def _endpoint(self, suffix: str) -> str:
        """Build an endpoint beneath the configured Navidrome base path."""
        return f"{self._base_url}/{suffix.lstrip('/')}"

    def _subsonic_auth_params(self) -> dict[str, str]:
        """Generate a fresh Subsonic token-and-salt authentication parameter set."""
        salt = secrets.token_hex(8)
        token = md5(f"{self._password}{salt}".encode(), usedforsecurity=False).hexdigest()
        return {
            "u": self._username,
            "t": token,
            "s": salt,
            "v": _SUBSONIC_VERSION,
            "c": _SUBSONIC_CLIENT,
            "f": "json",
        }

    async def _read_limited(self, response: aiohttp.ClientResponse, limit: int) -> bytes:
        """Read at most ``limit`` decompressed bytes or raise a protocol error."""
        content_length = response.content_length
        if content_length is not None and content_length > limit:
            raise NavidromeProtocolError(f"response exceeds {limit} byte limit")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.content.iter_chunked(min(64 * 1024, limit + 1)):
            total += len(chunk)
            if total > limit:
                raise NavidromeProtocolError(f"response exceeds {limit} byte limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        limit: int,
        auth_http_status: bool = False,
        allow_not_found: bool = False,
    ) -> tuple[int, bytes]:
        """Issue one bounded request and translate transport errors to client errors."""
        try:
            async with asyncio.timeout(self._request_timeout):
                async with self._session.request(
                    method,
                    self._endpoint(path),
                    params=params,
                    json=json_body,
                    headers=headers,
                    ssl=self._verify_ssl,
                    allow_redirects=False,
                ) as response:
                    body = await self._read_limited(response, limit)
                    if not _HTTP_OK <= response.status < _HTTP_REDIRECT:
                        if allow_not_found and response.status == _HTTP_NOT_FOUND:
                            return response.status, body
                        if auth_http_status and response.status == _HTTP_UNAUTHORIZED:
                            raise NavidromeAuthError(
                                f"{method} {path} returned HTTP {response.status}"
                            )
                        raise NavidromeProtocolError(
                            f"{method} {path} returned HTTP {response.status}"
                        )
                    return response.status, body
        except NavidromeError:
            raise
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise NavidromeConnectionError(f"{method} {path} failed: {err}") from err

    @staticmethod
    def _json_object(body: bytes, endpoint: str) -> Mapping[str, Any]:
        """Decode a bounded JSON response and require an object at its root."""
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise NavidromeProtocolError(f"invalid JSON from {endpoint}") from err
        if not isinstance(decoded, Mapping):
            raise NavidromeProtocolError(f"JSON response from {endpoint} is not an object")
        return decoded

    async def _subsonic_request(
        self,
        endpoint: str,
        params: Mapping[str, str | int] | None = None,
    ) -> Mapping[str, Any]:
        """Call a Subsonic endpoint and validate its protocol-level status."""
        request_params = self._subsonic_auth_params()
        if params:
            request_params.update({key: str(value) for key, value in params.items()})
        _, body = await self._request_bytes(
            "GET", f"rest/{endpoint}.view", params=request_params, limit=_JSON_LIMIT
        )
        envelope = self._json_object(body, endpoint)
        root = envelope.get("subsonic-response", envelope.get("subsonicResponse"))
        if not isinstance(root, Mapping):
            raise NavidromeProtocolError(f"{endpoint} response lacks subsonic-response")
        if root.get("status") != "ok":
            error = root.get("error")
            code = self._as_int(error.get("code")) if isinstance(error, Mapping) else None
            message = self._as_text(error.get("message")) if isinstance(error, Mapping) else ""
            detail = (
                f"Subsonic error {code}" if code is not None else "unsuccessful Subsonic status"
            )
            if message:
                detail = f"{detail}: {message}"
            if code in _AUTH_ERROR_CODES:
                raise NavidromeAuthError(detail)
            raise NavidromeProtocolError(detail)
        return root

    async def ping(self) -> None:
        """Verify Subsonic connectivity and credentials."""
        await self._subsonic_request("ping")

    async def async_ping(self) -> None:
        """Verify Subsonic connectivity using Home Assistant async naming."""
        await self.ping()

    async def search_tracks(self, query: str, limit: int) -> list[Track]:
        """Search tracks with Navidrome's ``search3`` endpoint."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        root = await self._subsonic_request(
            "search3",
            {
                "query": query,
                "songCount": limit,
                "songOffset": 0,
                "albumCount": 0,
                "artistCount": 0,
            },
        )
        result = root.get("searchResult3")
        return self._tracks_from_value(result.get("song") if isinstance(result, Mapping) else None)

    async_search_tracks = search_tracks

    async def all_tracks(self, page_size: int) -> list[Track]:
        """Fetch the entire track library by paging empty ``search3`` searches."""
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        tracks: list[Track] = []
        seen_ids: set[str] = set()
        offset = 0
        while True:
            root = await self._subsonic_request(
                "search3",
                {
                    "query": "",
                    "songCount": page_size,
                    "songOffset": offset,
                    "albumCount": 0,
                    "artistCount": 0,
                },
            )
            result = root.get("searchResult3")
            page = self._tracks_from_value(
                result.get("song") if isinstance(result, Mapping) else None
            )
            for track in page:
                if track.id and track.id not in seen_ids:
                    seen_ids.add(track.id)
                    tracks.append(track)
            if len(page) < page_size:
                return tracks
            offset += page_size

    async_all_tracks = all_tracks

    async def playlists(self) -> list[Playlist]:
        """Return all saved playlists available to the configured account."""
        root = await self._subsonic_request("getPlaylists")
        container = root.get("playlists")
        return self._playlists_from_value(
            container.get("playlist") if isinstance(container, Mapping) else None
        )

    async_playlists = playlists

    async def playlist_tracks(self, playlist_id: str) -> list[Track]:
        """Return entries of a playlist in Navidrome's supplied order."""
        root = await self._subsonic_request("getPlaylist", {"id": playlist_id})
        playlist = root.get("playlist")
        return self._tracks_from_value(
            playlist.get("entry") if isinstance(playlist, Mapping) else None
        )

    async_playlist_tracks = playlist_tracks

    async def track(self, track_id: str) -> Track:
        """Return one track, raising a protocol error if Navidrome omits it."""
        root = await self._subsonic_request("getSong", {"id": track_id})
        value = root.get("song")
        tracks = self._tracks_from_value(value)
        if not tracks:
            raise NavidromeProtocolError("getSong response does not contain a valid song")
        return tracks[0]

    async_track = track

    async def cover_art(self, cover_art_id: str, size: int = 600) -> bytes:
        """Fetch bounded cover-art bytes from Subsonic's ``getCoverArt`` endpoint."""
        if size <= 0:
            raise ValueError("size must be positive")
        params = self._subsonic_auth_params()
        params.update({"id": cover_art_id, "size": str(size)})
        _, body = await self._request_bytes(
            "GET",
            "rest/getCoverArt.view",
            params=params,
            headers={"Accept": "image/*"},
            limit=_IMAGE_LIMIT,
        )
        return body

    async def async_cover_art(self, cover_art_id: str, size: int = 600) -> tuple[bytes, str]:
        """Return cover bytes and a conservative detected image media type."""
        body = await self.cover_art(cover_art_id, size)
        if body.startswith(b"\x89PNG\r\n\x1a\n"):
            content_type = "image/png"
        elif body.startswith((b"GIF87a", b"GIF89a")):
            content_type = "image/gif"
        elif body.startswith(b"RIFF") and body[8:12] == b"WEBP":
            content_type = "image/webp"
        elif body.startswith(b"\xff\xd8\xff"):
            content_type = "image/jpeg"
        else:
            raise NavidromeProtocolError("getCoverArt returned an unsupported image format")
        return body, content_type

    async def _native_login(self) -> str:
        """Log in to the native API and cache its bearer token."""
        _, body = await self._request_bytes(
            "POST",
            "auth/login",
            json_body={"username": self._username, "password": self._password},
            limit=_JSON_LIMIT,
            auth_http_status=True,
        )
        response = self._json_object(body, "auth/login")
        data = response.get("data", response)
        if not isinstance(data, Mapping):
            raise NavidromeProtocolError("auth/login response does not contain an object")
        token = self._as_text(data.get("token"))
        if not token:
            raise NavidromeProtocolError("auth/login response does not contain a token")
        self._native_token = token
        return token

    async def async_login(self) -> str:
        """Log in to Navidrome's native API and return its bearer token."""
        return await self._native_login()

    async def _native_token_or_login(self) -> str:
        """Return the cached bearer token, logging in when this is the first share."""
        return self._native_token if self._native_token else await self._native_login()

    def _native_headers(self, token: str) -> dict[str, str]:
        """Build native API authorization headers for this client instance."""
        return {
            "X-ND-Authorization": f"Bearer {token}",
            "X-ND-Client-Unique-Id": self._client_unique_id,
        }

    async def _native_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> Mapping[str, Any]:
        """Call a native API endpoint, refreshing its token once after an HTTP 401."""
        token = await self._native_token_or_login()
        try:
            _, body = await self._request_bytes(
                method,
                path,
                json_body=json_body,
                headers=self._native_headers(token),
                limit=_JSON_LIMIT,
                auth_http_status=True,
            )
        except NavidromeAuthError:
            if not retry_on_401:
                raise
            self._native_token = None
            token = await self._native_login()
            _, body = await self._request_bytes(
                method,
                path,
                json_body=json_body,
                headers=self._native_headers(token),
                limit=_JSON_LIMIT,
                auth_http_status=True,
            )
        return self._json_object(body, path)

    @staticmethod
    def _native_data(response: Mapping[str, Any], endpoint: str) -> Mapping[str, Any]:
        """Accept either Navidrome's raw-object or ``data``-wrapped result format."""
        data = response.get("data", response)
        if not isinstance(data, Mapping):
            raise NavidromeProtocolError(f"{endpoint} response does not contain an object")
        return data

    async def create_share(
        self,
        tracks: Sequence[Track | str],
        ttl: timedelta,
        max_bit_rate: int,
    ) -> list[str]:
        """Create an MP3 share and return validated stream URLs in input ID order.

        ``tracks`` may contain :class:`Track` instances or IDs.  The server's M3U
        must contain exactly one non-comment URL for each supplied ID.
        """
        _, urls = await self.async_create_stream_urls(
            tracks,
            ttl=ttl,
            max_bit_rate=max_bit_rate,
        )
        return urls

    async def async_create_stream_urls(
        self,
        tracks: Sequence[Track | str],
        *,
        ttl: timedelta,
        max_bit_rate: int,
    ) -> tuple[str, list[str]]:
        """Create one temporary share and return its identifier and ordered stream URLs."""
        if max_bit_rate <= 0:
            raise ValueError("max_bit_rate must be positive")
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        ids = [item.id if isinstance(item, Track) else self._as_text(item) for item in tracks]
        if not ids or any(not track_id for track_id in ids):
            raise ValueError("tracks must contain one or more non-empty IDs")
        expires_at = datetime.now(UTC) + ttl
        payload = {
            "description": "Home Assistant playback",
            "resourceType": "media_file",
            "resourceIds": ",".join(ids),
            "format": "mp3",
            "maxBitRate": max_bit_rate,
            "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
        }
        response = await self._native_request("POST", "api/share/", json_body=payload)
        share = self._native_data(response, "api/share")
        share_id = self._as_text(share.get("id", share.get("shareId")))
        if not share_id:
            raise NavidromeProtocolError("api/share response does not contain a share id")
        try:
            urls = await self._share_m3u(share_id, len(ids))
        except Exception:
            with suppress(NavidromeError):
                await self.async_delete_share(share_id)
            raise
        return share_id, urls

    async def _share_m3u(self, share_id: str, expected_count: int) -> list[str]:
        """Fetch, size-limit, and strictly validate native share playlist entries."""
        _, body = await self._request_bytes(
            "GET",
            f"share/{share_id}/m3u",
            limit=_M3U_LIMIT,
        )
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError as err:
            raise NavidromeProtocolError("share M3U is not UTF-8") from err
        entries = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(entries) != expected_count:
            raise NavidromeProtocolError(
                f"share M3U has {len(entries)} URLs; expected {expected_count}"
            )
        return [self._validate_share_url(entry) for entry in entries]

    def _validate_share_url(self, entry: str) -> str:
        """Resolve a playlist URL and reject origins or paths outside its own share area."""
        candidate = urljoin(f"{self._share_url}/", entry)
        try:
            parts = urlsplit(candidate)
            port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        except ValueError as err:
            raise NavidromeProtocolError("share M3U contains a URL with an invalid port") from err
        if (
            parts.scheme.lower() != self._share_scheme
            or not parts.hostname
            or parts.hostname.lower() != self._share_host
            or port != self._share_port
            or parts.query
            or parts.fragment
            or parts.username is not None
            or parts.password is not None
        ):
            raise NavidromeProtocolError("share M3U contains a URL outside the Navidrome origin")
        prefix = f"{self._share_path}/share/s/" if self._share_path else "/share/s/"
        # Check both the sent path and an unquoted normal form: encoded traversal
        # must not turn an apparently valid URL into a request outside the share.
        normalized = posixpath.normpath(unquote(parts.path))
        if not parts.path.startswith(prefix) or not (normalized + "/").startswith(prefix):
            raise NavidromeProtocolError(
                "share M3U contains a URL outside the Navidrome share path"
            )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    async def async_delete_share(self, share_id: str) -> None:
        """Delete a native share; failures are deliberately surfaced to the caller."""
        if not self._as_text(share_id):
            raise NavidromeProtocolError("share_id must not be empty")
        token = await self._native_token_or_login()
        try:
            await self._request_bytes(
                "DELETE",
                f"api/share/{share_id}/",
                headers=self._native_headers(token),
                limit=_JSON_LIMIT,
                auth_http_status=True,
                allow_not_found=True,
            )
        except NavidromeAuthError:
            self._native_token = None
            token = await self._native_login()
            await self._request_bytes(
                "DELETE",
                f"api/share/{share_id}/",
                headers=self._native_headers(token),
                limit=_JSON_LIMIT,
                auth_http_status=True,
                allow_not_found=True,
            )

    @staticmethod
    def _as_text(value: Any) -> str:
        """Convert scalar nullable API values to text without stringifying containers."""
        if value is None or isinstance(value, (Mapping, list, tuple, set, bytes, bytearray)):
            return ""
        return str(value).strip()

    @staticmethod
    def _as_int(value: Any) -> int | None:
        """Convert nullable integer/string-number API values, rejecting booleans and fractions."""
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_bool(value: Any) -> bool:
        """Convert common nullable Navidrome boolean encodings to a boolean."""
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        return bool(value) if value is not None else False

    @staticmethod
    def _items(value: Any) -> list[Mapping[str, Any]]:
        """Normalize a nullable singleton-or-array API field into object items."""
        if isinstance(value, Mapping):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        return []

    @classmethod
    def _tracks_from_value(cls, value: Any) -> list[Track]:
        """Parse nullable/string-number Subsonic songs without leaking malformed items."""
        tracks: list[Track] = []
        for item in cls._items(value):
            track_id = cls._as_text(item.get("id"))
            if not track_id:
                continue
            tracks.append(
                Track(
                    id=track_id,
                    title=cls._as_text(item.get("title")),
                    artist=cls._as_text(item.get("artist")),
                    album=cls._as_text(item.get("album")),
                    duration=cls._as_int(item.get("duration")) or 0,
                    suffix=cls._as_text(item.get("suffix")),
                    cover_art=cls._as_text(item.get("coverArt", item.get("cover_art"))),
                    genre=cls._as_text(item.get("genre")),
                    year=cls._as_int(item.get("year")),
                    track_number=cls._as_int(
                        item.get("track", item.get("trackNumber", item.get("track_number")))
                    ),
                    disc_number=cls._as_int(item.get("discNumber", item.get("disc_number"))),
                    bit_rate=cls._as_int(item.get("bitRate", item.get("bit_rate"))),
                    size=cls._as_int(item.get("size")),
                    content_type=cls._as_text(item.get("contentType", item.get("content_type"))),
                    created=cls._as_text(item.get("created")),
                )
            )
        return tracks

    @classmethod
    def _playlists_from_value(cls, value: Any) -> list[Playlist]:
        """Parse nullable/string-number Subsonic playlists without malformed items."""
        playlists: list[Playlist] = []
        for item in cls._items(value):
            playlist_id = cls._as_text(item.get("id"))
            if not playlist_id:
                continue
            playlists.append(
                Playlist(
                    id=playlist_id,
                    name=cls._as_text(item.get("name")),
                    owner=cls._as_text(item.get("owner")),
                    song_count=cls._as_int(item.get("songCount", item.get("song_count"))) or 0,
                    duration=cls._as_int(item.get("duration")) or 0,
                    public=cls._as_bool(item.get("public")),
                    cover_art=cls._as_text(item.get("coverArt", item.get("cover_art"))),
                )
            )
        return playlists


__all__ = ["NavidromeClient"]
