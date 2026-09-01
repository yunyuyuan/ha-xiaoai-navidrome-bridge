"""Config flow for XiaoAI Navidrome."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import suppress
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_AUTOPLAY_MIN_MARGIN,
    CONF_AUTOPLAY_MIN_SCORE,
    CONF_CLEAR_EMBEDDING_API_KEY,
    CONF_CONVERSATION_SENSOR,
    CONF_EMBEDDING_API_KEY,
    CONF_EMBEDDING_ENABLED,
    CONF_EMBEDDING_MODEL,
    CONF_EMBEDDING_PROVIDER,
    CONF_EMBEDDING_URL,
    CONF_EMBEDDING_WEIGHT,
    CONF_INDEX_REFRESH_MINUTES,
    CONF_MAX_BIT_RATE,
    CONF_MEDIA_PLAYER,
    CONF_NAVIDROME_URL,
    CONF_PANEL_ENABLED,
    CONF_PANEL_TITLE,
    CONF_PASSWORD,
    CONF_PLAYLIST_GAP_SECONDS,
    CONF_PLAYLIST_PHRASE,
    CONF_QUEUE_MAX_TRACKS,
    CONF_SEMANTIC_AUTOPLAY_MIN_MARGIN,
    CONF_SEMANTIC_AUTOPLAY_MIN_SCORE,
    CONF_SHARE_TTL_HOURS,
    CONF_SHARE_URL,
    CONF_TRACK_PHRASE,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_AUTOPLAY_MIN_MARGIN,
    DEFAULT_AUTOPLAY_MIN_SCORE,
    DEFAULT_EMBEDDING_ENABLED,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDING_WEIGHT,
    DEFAULT_INDEX_REFRESH_MINUTES,
    DEFAULT_MAX_BIT_RATE,
    DEFAULT_PANEL_ENABLED,
    DEFAULT_PANEL_TITLE,
    DEFAULT_PLAYLIST_GAP_SECONDS,
    DEFAULT_PLAYLIST_PHRASE,
    DEFAULT_QUEUE_MAX_TRACKS,
    DEFAULT_SEMANTIC_AUTOPLAY_MIN_MARGIN,
    DEFAULT_SEMANTIC_AUTOPLAY_MIN_SCORE,
    DEFAULT_SHARE_TTL_HOURS,
    DEFAULT_TRACK_PHRASE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    NAME,
)
from .navidrome import (
    NavidromeAuthError,
    NavidromeClient,
    NavidromeConnectionError,
    NavidromeError,
    NavidromeProtocolError,
)
from .panel import normalize_panel_title

_LOGGER = logging.getLogger(__name__)


def _log_validation_failure(stage: str, err: NavidromeError) -> None:
    """Log a fixed setup stage and safe error category without upstream text."""
    if isinstance(err, NavidromeAuthError):
        category = "authentication"
    elif isinstance(err, NavidromeConnectionError):
        category = "connection"
    else:
        category = "protocol"
    reason = err.reason if isinstance(err, NavidromeProtocolError) else category
    _LOGGER.warning(
        "Navidrome setup validation failed at %s (%s error; reason=%s)",
        stage,
        category,
        reason,
    )


def _normalize_url(value: str) -> str:
    """Validate and normalize one absolute HTTP URL without credentials/query data."""
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        _port = parsed.port
    except ValueError as err:
        raise vol.Invalid("invalid URL") from err
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise vol.Invalid("invalid URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _connection_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_NAVIDROME_URL,
                default=values.get(CONF_NAVIDROME_URL, "https://navidrome.example.invalid"),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Required(CONF_USERNAME, default=values.get(CONF_USERNAME, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_SHARE_URL,
                description={"suggested_value": values.get(CONF_SHARE_URL, "")},
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Required(
                CONF_VERIFY_SSL, default=values.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            ): BooleanSelector(),
        }
    )


def _options_schema(defaults: Mapping[str, Any], *, allow_key_clear: bool = False) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_PANEL_ENABLED,
            default=defaults.get(CONF_PANEL_ENABLED, DEFAULT_PANEL_ENABLED),
        ): BooleanSelector(),
        vol.Required(
            CONF_PANEL_TITLE,
            default=defaults.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE),
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        vol.Required(
            CONF_MEDIA_PLAYER, default=defaults.get(CONF_MEDIA_PLAYER, "")
        ): EntitySelector(EntitySelectorConfig(domain="media_player")),
        vol.Optional(
            CONF_CONVERSATION_SENSOR,
            description={"suggested_value": defaults.get(CONF_CONVERSATION_SENSOR)},
        ): EntitySelector(EntitySelectorConfig(domain="sensor")),
        vol.Required(
            CONF_TRACK_PHRASE, default=defaults.get(CONF_TRACK_PHRASE, DEFAULT_TRACK_PHRASE)
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        vol.Required(
            CONF_PLAYLIST_PHRASE,
            default=defaults.get(CONF_PLAYLIST_PHRASE, DEFAULT_PLAYLIST_PHRASE),
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        vol.Required(
            CONF_MAX_BIT_RATE, default=defaults.get(CONF_MAX_BIT_RATE, DEFAULT_MAX_BIT_RATE)
        ): NumberSelector(
            NumberSelectorConfig(
                min=32,
                max=320,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="kbps",
            )
        ),
        vol.Required(
            CONF_SHARE_TTL_HOURS,
            default=defaults.get(CONF_SHARE_TTL_HOURS, DEFAULT_SHARE_TTL_HOURS),
        ): NumberSelector(
            NumberSelectorConfig(
                min=1,
                max=720,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="h",
            )
        ),
        vol.Required(
            CONF_QUEUE_MAX_TRACKS,
            default=defaults.get(CONF_QUEUE_MAX_TRACKS, DEFAULT_QUEUE_MAX_TRACKS),
        ): NumberSelector(
            NumberSelectorConfig(min=1, max=5000, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(
            CONF_PLAYLIST_GAP_SECONDS,
            default=defaults.get(CONF_PLAYLIST_GAP_SECONDS, DEFAULT_PLAYLIST_GAP_SECONDS),
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=30,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Required(
            CONF_INDEX_REFRESH_MINUTES,
            default=defaults.get(CONF_INDEX_REFRESH_MINUTES, DEFAULT_INDEX_REFRESH_MINUTES),
        ): NumberSelector(
            NumberSelectorConfig(
                min=5,
                max=1440,
                step=5,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        ),
        vol.Required(
            CONF_EMBEDDING_ENABLED,
            default=defaults.get(CONF_EMBEDDING_ENABLED, DEFAULT_EMBEDDING_ENABLED),
        ): BooleanSelector(),
        vol.Required(
            CONF_EMBEDDING_PROVIDER,
            default=defaults.get(CONF_EMBEDDING_PROVIDER, DEFAULT_EMBEDDING_PROVIDER),
        ): SelectSelector(SelectSelectorConfig(options=["ollama", "openai"])),
        vol.Optional(
            CONF_EMBEDDING_URL,
            description={"suggested_value": defaults.get(CONF_EMBEDDING_URL, "")},
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(
            CONF_EMBEDDING_MODEL,
            default=defaults.get(CONF_EMBEDDING_MODEL, DEFAULT_EMBEDDING_MODEL),
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        vol.Optional(CONF_EMBEDDING_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(
            CONF_AUTOPLAY_MIN_SCORE,
            default=defaults.get(CONF_AUTOPLAY_MIN_SCORE, DEFAULT_AUTOPLAY_MIN_SCORE),
        ): NumberSelector(
            NumberSelectorConfig(min=0, max=1, step=0.01, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(
            CONF_AUTOPLAY_MIN_MARGIN,
            default=defaults.get(CONF_AUTOPLAY_MIN_MARGIN, DEFAULT_AUTOPLAY_MIN_MARGIN),
        ): NumberSelector(
            NumberSelectorConfig(min=0, max=1, step=0.01, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(
            CONF_EMBEDDING_WEIGHT,
            default=defaults.get(CONF_EMBEDDING_WEIGHT, DEFAULT_EMBEDDING_WEIGHT),
        ): NumberSelector(
            NumberSelectorConfig(min=0, max=1, step=0.01, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(
            CONF_SEMANTIC_AUTOPLAY_MIN_SCORE,
            default=defaults.get(
                CONF_SEMANTIC_AUTOPLAY_MIN_SCORE,
                DEFAULT_SEMANTIC_AUTOPLAY_MIN_SCORE,
            ),
        ): NumberSelector(
            NumberSelectorConfig(min=0, max=1, step=0.01, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(
            CONF_SEMANTIC_AUTOPLAY_MIN_MARGIN,
            default=defaults.get(
                CONF_SEMANTIC_AUTOPLAY_MIN_MARGIN,
                DEFAULT_SEMANTIC_AUTOPLAY_MIN_MARGIN,
            ),
        ): NumberSelector(
            NumberSelectorConfig(min=0, max=1, step=0.01, mode=NumberSelectorMode.BOX)
        ),
    }
    if allow_key_clear:
        fields[vol.Required(CONF_CLEAR_EMBEDDING_API_KEY, default=False)] = BooleanSelector()
    return vol.Schema(fields)


async def _validate_connection(hass: Any, values: Mapping[str, Any]) -> None:
    """Validate credentials against both Subsonic and native APIs."""
    client = NavidromeClient(
        session=async_get_clientsession(hass),
        base_url=_normalize_url(str(values[CONF_NAVIDROME_URL])),
        share_url=(
            _normalize_url(str(values[CONF_SHARE_URL])) if values.get(CONF_SHARE_URL) else None
        ),
        username=str(values[CONF_USERNAME]).strip(),
        password=str(values[CONF_PASSWORD]),
        verify_ssl=bool(values[CONF_VERIFY_SSL]),
    )
    try:
        await client.async_ping()
    except NavidromeError as err:
        _log_validation_failure("Subsonic ping", err)
        raise
    try:
        await client.async_login()
    except NavidromeError as err:
        _log_validation_failure("native login", err)
        raise
    try:
        tracks = await client.async_search_tracks("", 1)
    except NavidromeError as err:
        _log_validation_failure("library probe", err)
        raise
    if tracks:
        share_id = ""
        try:
            share_id, _ = await client.async_create_stream_urls(
                [tracks[0]],
                max_bit_rate=DEFAULT_MAX_BIT_RATE,
                ttl=timedelta(minutes=5),
            )
        except NavidromeError as err:
            _log_validation_failure("share probe", err)
            raise
        finally:
            if share_id:
                with suppress(NavidromeError):
                    await client.async_delete_share(share_id)


class XiaoAINavidromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for XiaoAI Navidrome."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize temporary flow state."""
        self._connection_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle initial setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                normalized = dict(user_input)
                normalized[CONF_NAVIDROME_URL] = _normalize_url(str(normalized[CONF_NAVIDROME_URL]))
                if normalized.get(CONF_SHARE_URL):
                    normalized[CONF_SHARE_URL] = _normalize_url(str(normalized[CONF_SHARE_URL]))
                else:
                    normalized.pop(CONF_SHARE_URL, None)
                normalized[CONF_USERNAME] = str(normalized[CONF_USERNAME]).strip()
                await _validate_connection(self.hass, normalized)
            except NavidromeAuthError:
                errors["base"] = "invalid_auth"
            except NavidromeConnectionError:
                errors["base"] = "cannot_connect"
            except vol.Invalid:
                errors["base"] = "invalid_url"
            except NavidromeError:
                errors["base"] = "invalid_response"
            else:
                parsed = urlsplit(normalized[CONF_NAVIDROME_URL])
                await self.async_set_unique_id(
                    f"{parsed.scheme}://{parsed.netloc}{parsed.path}|{normalized[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()
                self._connection_data = normalized
                return await self.async_step_playback()
        return self.async_show_form(
            step_id="user", data_schema=_connection_schema(user_input), errors=errors
        )

    async def async_step_playback(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect playback, voice and optional semantic matching settings."""
        if not self._connection_data:
            return await self.async_step_user()
        if user_input is not None:
            values = dict(user_input)
            values[CONF_PANEL_ENABLED] = bool(values[CONF_PANEL_ENABLED])
            values[CONF_PANEL_TITLE] = normalize_panel_title(values[CONF_PANEL_TITLE])
            values.pop(CONF_CLEAR_EMBEDDING_API_KEY, None)
            for optional in (
                CONF_CONVERSATION_SENSOR,
                CONF_EMBEDDING_URL,
                CONF_EMBEDDING_API_KEY,
            ):
                if not values.get(optional):
                    values.pop(optional, None)
            return self.async_create_entry(
                title=NAME,
                data=self._connection_data,
                options=values,
            )
        return self.async_show_form(
            step_id="playback",
            data_schema=_options_schema(self._connection_data),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm new credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = {**entry.data, **user_input}
            try:
                await _validate_connection(self.hass, values)
            except NavidromeAuthError:
                errors["base"] = "invalid_auth"
            except NavidromeConnectionError:
                errors["base"] = "cannot_connect"
            except NavidromeError:
                errors["base"] = "invalid_response"
            else:
                return self.async_update_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure the Navidrome connection."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            values = dict(user_input)
            try:
                values[CONF_NAVIDROME_URL] = _normalize_url(values[CONF_NAVIDROME_URL])
                if values.get(CONF_SHARE_URL):
                    values[CONF_SHARE_URL] = _normalize_url(values[CONF_SHARE_URL])
                else:
                    values.pop(CONF_SHARE_URL, None)
                values[CONF_USERNAME] = values[CONF_USERNAME].strip()
                await _validate_connection(self.hass, values)
            except NavidromeAuthError:
                errors["base"] = "invalid_auth"
            except NavidromeConnectionError:
                errors["base"] = "cannot_connect"
            except vol.Invalid:
                errors["base"] = "invalid_url"
            except NavidromeError:
                errors["base"] = "invalid_response"
            else:
                return self.async_update_and_abort(entry, data=values)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> XiaoAINavidromeOptionsFlow:
        """Create the options flow."""
        return XiaoAINavidromeOptionsFlow(config_entry)


class XiaoAINavidromeOptionsFlow(config_entries.OptionsFlow):
    """Handle XiaoAI Navidrome options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            values = dict(user_input)
            values[CONF_PANEL_ENABLED] = bool(values[CONF_PANEL_ENABLED])
            values[CONF_PANEL_TITLE] = normalize_panel_title(values[CONF_PANEL_TITLE])
            clear_api_key = bool(values.pop(CONF_CLEAR_EMBEDDING_API_KEY, False))
            if clear_api_key:
                values.pop(CONF_EMBEDDING_API_KEY, None)
            elif not values.get(CONF_EMBEDDING_API_KEY):
                existing_key = self._entry.options.get(CONF_EMBEDDING_API_KEY)
                if existing_key:
                    values[CONF_EMBEDDING_API_KEY] = existing_key
                else:
                    values.pop(CONF_EMBEDDING_API_KEY, None)
            if not values.get(CONF_CONVERSATION_SENSOR):
                values.pop(CONF_CONVERSATION_SENSOR, None)
            if not values.get(CONF_EMBEDDING_URL):
                values.pop(CONF_EMBEDDING_URL, None)
            return self.async_create_entry(title="", data=values)
        defaults = {**self._entry.data, **self._entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(defaults, allow_key_clear=True),
        )
