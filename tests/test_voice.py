"""Tests for voice command parsing."""

from custom_components.xiaoai_navidrome.voice import VoiceCommand, parse_voice_command


def parse(value: str) -> VoiceCommand | None:
    """Parse a synthetic command with default phrases."""
    return parse_voice_command(
        value,
        track_phrase="播放家庭音乐",
        playlist_phrase="播放家庭歌单",
    )


def test_track_and_playlist_commands() -> None:
    assert parse("请播放家庭音乐：示例曲目") == VoiceCommand("play", "示例曲目")
    assert parse("播放家庭歌单，示例列表") == VoiceCommand("play_playlist", "示例列表")


def test_transport_commands() -> None:
    assert parse("家庭音乐下一首") == VoiceCommand("next")
    assert parse("上一首家庭音乐") == VoiceCommand("previous")
    assert parse("关闭家庭音乐") == VoiceCommand("stop")


def test_invalid_or_empty_commands() -> None:
    assert parse("") is None
    assert parse("播放家庭音乐") is None
    assert parse("普通对话") is None
