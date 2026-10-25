"""Config and options flows: name the gateway, pick its engines in fallback order, then each
engine's voice."""

from __future__ import annotations

import secrets
import string
from typing import Any

import voluptuous as vol
from homeassistant.components.tts import DOMAIN as TTS_DOMAIN
from homeassistant.components.tts.const import DATA_COMPONENT
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_ENDPOINT,
    CONF_ENGINES,
    CONF_FIRST_CHUNK_TIMEOUT,
    CONF_LANGUAGE,
    CONF_PITCH,
    CONF_RATE,
    CONF_REGENERATE_ENDPOINT,
    CONF_VOICES,
    CONF_VOLUME,
    DEFAULT_FIRST_CHUNK_TIMEOUT,
    DEFAULT_LANGUAGE,
    DOMAIN,
    PROSODY_OPTIONS,
    URL_PATH,
)
from .speech import PITCH_RANGE, RATE_RANGE, VOLUME_RANGE, parse_option

# 22 letters and digits are about 131 bits, as many as a 16-byte token
_SECRET_ALPHABET = string.ascii_letters + string.digits
_SECRET_LENGTH = 22


def _new_endpoint(name: str) -> str:
    """Return the name in snake_case followed by a random secret, like ha-mcp's secret path.

    The URL is all a client needs, so the secret part works as its password. slugify romanizes
    other scripts (閱讀器 becomes yue_du_qi); names without letters or digits get only the secret.
    """
    secret = "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(_SECRET_LENGTH))
    if not any(char.isalnum() for char in name):
        return secret
    return f"{slugify(name)}_{secret}"


def _number(bounds: tuple[float, float], step: float, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=bounds[0],
            max=bounds[1],
            step=step,
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


def _options_schema(defaults: dict[str, Any]) -> dict[vol.Marker, Any]:
    return {
        # The selection order is the fallback order
        vol.Required(CONF_ENGINES, default=defaults.get(CONF_ENGINES, [])): EntitySelector(
            EntitySelectorConfig(domain=TTS_DOMAIN, multiple=True)
        ),
        vol.Required(
            CONF_LANGUAGE, default=defaults.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        ): TextSelector(),
        # Rate, pitch and volume; all optional. Voices come on the next step, one per engine.
        vol.Optional(CONF_RATE, description={"suggested_value": defaults.get(CONF_RATE)}): _number(
            RATE_RANGE, 0.05, "×"
        ),
        vol.Optional(
            CONF_PITCH, description={"suggested_value": defaults.get(CONF_PITCH)}
        ): _number(PITCH_RANGE, 0.5, "st"),
        vol.Optional(
            CONF_VOLUME, description={"suggested_value": defaults.get(CONF_VOLUME)}
        ): _number(VOLUME_RANGE, 1, "%"),
        vol.Required(
            CONF_FIRST_CHUNK_TIMEOUT,
            default=defaults.get(CONF_FIRST_CHUNK_TIMEOUT, DEFAULT_FIRST_CHUNK_TIMEOUT),
        ): NumberSelector(
            NumberSelectorConfig(
                min=1, max=30, step=0.5, unit_of_measurement="s", mode=NumberSelectorMode.BOX
            )
        ),
    }


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    options = {
        CONF_ENGINES: list(user_input[CONF_ENGINES]),
        CONF_LANGUAGE: user_input[CONF_LANGUAGE].strip(),
        CONF_FIRST_CHUNK_TIMEOUT: float(user_input[CONF_FIRST_CHUNK_TIMEOUT]),
    }
    for name in PROSODY_OPTIONS:
        if (value := user_input.get(name)) not in (None, ""):
            options[name] = parse_option(name, value)
    return options


def _validate_options(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not user_input.get(CONF_ENGINES):
        errors[CONF_ENGINES] = "no_engines"
    if not user_input.get(CONF_LANGUAGE, "").strip():
        errors[CONF_LANGUAGE] = "no_language"
    for name in PROSODY_OPTIONS:
        if (value := user_input.get(name)) not in (None, ""):
            try:
                parse_option(name, value)
            except ValueError:
                errors[name] = f"invalid_{name}"
    return errors


def _voice_selector(hass: HomeAssistant, engine: str, language: str) -> Any:
    """A dropdown of the engine's voices for the language, or a text field if it lists none.

    Both take a voice that isn't listed: Edge TTS, for one, doesn't list its voices.
    """
    entity = hass.data[DATA_COMPONENT].get_entity(engine)
    voices = entity.async_get_supported_voices(language) if entity is not None else None
    if not voices:
        return TextSelector()
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(
                    value=voice.voice_id,
                    label=(
                        voice.voice_id
                        if voice.name == voice.voice_id
                        else f"{voice.name} ({voice.voice_id})"
                    ),
                )
                for voice in voices
            ],
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
            sort=True,
        )
    )


def _voices_schema(
    hass: HomeAssistant, options: dict[str, Any], voices: dict[str, str]
) -> vol.Schema:
    """One optional field per engine, named by its entity ID."""
    return vol.Schema(
        {
            vol.Optional(engine, description={"suggested_value": voices.get(engine)}): (
                _voice_selector(hass, engine, options[CONF_LANGUAGE])
            )
            for engine in options[CONF_ENGINES]
        }
    )


def _clean_voices(options: dict[str, Any], user_input: dict[str, Any]) -> dict[str, str]:
    return {
        engine: voice
        for engine in options[CONF_ENGINES]
        if (voice := str(user_input.get(engine) or "").strip())
    }


class TtsGatewayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a gateway at a generated URL; its name is only what Home Assistant shows."""

    VERSION = 1
    # 1.2: a voice per engine (CONF_VOICES) instead of one for all
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._title = ""
        self._options: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "no_name"
            errors.update(_validate_options(user_input))
            if not errors:
                self._title = name
                self._options = _clean_options(user_input)
                return await self.async_step_voices()

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): TextSelector(),
                **_options_schema(defaults),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_voices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._title,
                data={CONF_ENDPOINT: _new_endpoint(self._title)},
                options={**self._options, CONF_VOICES: _clean_voices(self._options, user_input)},
            )
        return self.async_show_form(
            step_id="voices", data_schema=_voices_schema(self.hass, self._options, {})
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TtsGatewayOptionsFlow:
        return TtsGatewayOptionsFlow()


class TtsGatewayOptionsFlow(OptionsFlow):
    """Change the engines, defaults and voices, or move the gateway to a new URL."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._regenerate_endpoint = False

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_options(user_input)
            if not errors:
                self._options = _clean_options(user_input)
                self._regenerate_endpoint = bool(user_input.get(CONF_REGENERATE_ENDPOINT))
                return await self.async_step_voices()

        schema = vol.Schema(
            {
                **_options_schema(user_input or dict(entry.options)),
                vol.Required(CONF_REGENERATE_ENDPOINT, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "path": URL_PATH.format(endpoint=entry.data[CONF_ENDPOINT]),
            },
        )

    async def async_step_voices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            if self._regenerate_endpoint:
                # From the current name, in case the gateway was renamed since
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_ENDPOINT: _new_endpoint(entry.title)}
                )
            return self.async_create_entry(
                data={**self._options, CONF_VOICES: _clean_voices(self._options, user_input)}
            )
        return self.async_show_form(
            step_id="voices",
            data_schema=_voices_schema(
                self.hass, self._options, dict(entry.options.get(CONF_VOICES, {}))
            ),
        )
