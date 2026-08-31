"""Parse XiaoAI conversation sensor text into integration commands."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class VoiceCommand:
    """A parsed voice command."""

    action: str
    query: str = ""


def parse_voice_command(
    spoken_text: str,
    *,
    track_phrase: str,
    playlist_phrase: str,
) -> VoiceCommand | None:
    """Parse supported track, playlist and queue-control phrases."""
    text = re.sub(r"\s+", "", spoken_text.strip())
    track_key = re.sub(r"\s+", "", track_phrase.strip())
    playlist_key = re.sub(r"\s+", "", playlist_phrase.strip())
    if not text or not track_key or not playlist_key:
        return None

    control_target = track_key.removeprefix("播放") or track_key
    controls = (
        ("stop", (f"停止{control_target}", f"关闭{control_target}")),
        ("next", (f"下一首{control_target}", f"{control_target}下一首")),
        ("previous", (f"上一首{control_target}", f"{control_target}上一首")),
    )
    for action, phrases in controls:
        if any(phrase in text for phrase in phrases):
            return VoiceCommand(action)

    if playlist_key in text:
        query = _query_after(text, playlist_key)
        return VoiceCommand("play_playlist", query) if query else None
    if track_key in text:
        query = _query_after(text, track_key)
        return VoiceCommand("play", query) if query else None
    return None


def _query_after(text: str, phrase: str) -> str:
    """Extract a query after the last command phrase and trim separators."""
    return text.rsplit(phrase, 1)[-1].lstrip("，,：:。.!！?？")
