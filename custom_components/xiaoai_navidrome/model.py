"""Data models and errors for the XiaoAi Navidrome integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class NavidromeError(Exception):
    """Base class for errors returned by the Navidrome client."""


class NavidromeAuthError(NavidromeError):
    """Raised when Navidrome rejects credentials or an access token."""


class NavidromeConnectionError(NavidromeError):
    """Raised when Navidrome cannot be reached before a response is received."""


class NavidromeProtocolError(NavidromeError):
    """Raised when Navidrome returns an invalid or unsuccessful protocol response."""

    def __init__(self, message: str, *, reason: str = "protocol") -> None:
        """Store a fixed diagnostic reason separately from the safe message."""
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Track:
    """A track returned by Navidrome."""

    id: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: int = 0
    suffix: str = ""
    cover_art: str = ""
    genre: str = ""
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    bit_rate: int | None = None
    size: int | None = None
    content_type: str = ""
    created: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary for the Home Assistant panel."""
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration": self.duration,
            "suffix": self.suffix,
            "cover_art": self.cover_art,
            "genre": self.genre,
            "year": self.year,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "bit_rate": self.bit_rate,
            "size": self.size,
            "content_type": self.content_type,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Track:
        """Restore a track from versioned Home Assistant storage."""
        optional_ints = {
            name: item if isinstance(item, int) and not isinstance(item, bool) else None
            for name in ("year", "track_number", "disc_number", "bit_rate", "size")
            if (item := value.get(name)) is not None
        }
        duration = value.get("duration", 0)
        return cls(
            id=str(value.get("id", "")),
            title=str(value.get("title", "")),
            artist=str(value.get("artist", "")),
            album=str(value.get("album", "")),
            duration=(
                duration if isinstance(duration, int) and not isinstance(duration, bool) else 0
            ),
            suffix=str(value.get("suffix", "")),
            cover_art=str(value.get("cover_art", "")),
            genre=str(value.get("genre", "")),
            content_type=str(value.get("content_type", "")),
            created=str(value.get("created", "")),
            **optional_ints,
        )


@dataclass(frozen=True, slots=True)
class Playlist:
    """A saved Navidrome playlist."""

    id: str
    name: str = ""
    owner: str = ""
    song_count: int = 0
    duration: int = 0
    public: bool = False
    cover_art: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary for the Home Assistant panel."""
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "song_count": self.song_count,
            "duration": self.duration,
            "public": self.public,
            "cover_art": self.cover_art,
        }
