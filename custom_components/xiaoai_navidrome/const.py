"""Constants for the XiaoAI Navidrome integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "xiaoai_navidrome"
NAME: Final = "XiaoAI Navidrome"
VERSION: Final = "1.0.4"

CONF_NAVIDROME_URL: Final = "navidrome_url"
CONF_SHARE_URL: Final = "share_url"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_MEDIA_PLAYER: Final = "media_player"
CONF_CONVERSATION_SENSOR: Final = "conversation_sensor"
CONF_TRACK_PHRASE: Final = "track_phrase"
CONF_PLAYLIST_PHRASE: Final = "playlist_phrase"
CONF_MAX_BIT_RATE: Final = "max_bit_rate"
CONF_SHARE_TTL_HOURS: Final = "share_ttl_hours"
CONF_QUEUE_MAX_TRACKS: Final = "queue_max_tracks"
CONF_PLAYLIST_GAP_SECONDS: Final = "playlist_gap_seconds"
CONF_INDEX_REFRESH_MINUTES: Final = "index_refresh_minutes"
CONF_EMBEDDING_ENABLED: Final = "embedding_enabled"
CONF_EMBEDDING_URL: Final = "embedding_url"
CONF_EMBEDDING_PROVIDER: Final = "embedding_provider"
CONF_EMBEDDING_MODEL: Final = "embedding_model"
CONF_EMBEDDING_API_KEY: Final = "embedding_api_key"
CONF_CLEAR_EMBEDDING_API_KEY: Final = "clear_embedding_api_key"
CONF_AUTOPLAY_MIN_SCORE: Final = "autoplay_min_score"
CONF_AUTOPLAY_MIN_MARGIN: Final = "autoplay_min_margin"
CONF_EMBEDDING_WEIGHT: Final = "embedding_weight"
CONF_SEMANTIC_AUTOPLAY_MIN_SCORE: Final = "semantic_autoplay_min_score"
CONF_SEMANTIC_AUTOPLAY_MIN_MARGIN: Final = "semantic_autoplay_min_margin"

DEFAULT_VERIFY_SSL: Final = True
DEFAULT_TRACK_PHRASE: Final = "播放家庭音乐"
DEFAULT_PLAYLIST_PHRASE: Final = "播放家庭歌单"
DEFAULT_MAX_BIT_RATE: Final = 128
DEFAULT_SHARE_TTL_HOURS: Final = 6
DEFAULT_QUEUE_MAX_TRACKS: Final = 500
DEFAULT_PLAYLIST_GAP_SECONDS: Final = 2
DEFAULT_INDEX_REFRESH_MINUTES: Final = 30
DEFAULT_EMBEDDING_ENABLED: Final = False
DEFAULT_EMBEDDING_PROVIDER: Final = "ollama"
DEFAULT_EMBEDDING_MODEL: Final = "qwen3-embedding:0.6b"
DEFAULT_AUTOPLAY_MIN_SCORE: Final = 0.72
DEFAULT_AUTOPLAY_MIN_MARGIN: Final = 0.08
DEFAULT_EMBEDDING_WEIGHT: Final = 0.35
DEFAULT_SEMANTIC_AUTOPLAY_MIN_SCORE: Final = 0.60
DEFAULT_SEMANTIC_AUTOPLAY_MIN_MARGIN: Final = 0.05

SERVICE_PLAY: Final = "play"
SERVICE_PLAY_PLAYLIST: Final = "play_playlist"
SERVICE_PREVIOUS: Final = "previous"
SERVICE_NEXT: Final = "next"
SERVICE_RESUME: Final = "resume"
SERVICE_STOP: Final = "stop"
SERVICE_CLEAR_QUEUE: Final = "clear_queue"
SERVICE_SYNC_LIBRARY: Final = "sync_library"

ATTR_QUERY: Final = "query"
ATTR_MEDIA_PLAYER: Final = "media_player"
ATTR_ENTRY_ID: Final = "config_entry_id"

PANEL_URL_PATH: Final = "xiaoai-navidrome"
PANEL_ELEMENT: Final = "xiaoai-navidrome-panel"
PANEL_STATIC_URL: Final = "/xiaoai_navidrome_static"
COVER_API_URL: Final = "/api/xiaoai_navidrome/cover"

STORAGE_VERSION: Final = 1
STORAGE_KEY_PREFIX: Final = "xiaoai_navidrome"
INDEX_STORAGE_VERSION: Final = 1

WS_PREFIX: Final = "xiaoai_navidrome"
EVENT_QUEUE_UPDATED: Final = "xiaoai_navidrome_queue_updated"
