"""TTS HTTP Gateway: serve Home Assistant TTS engines over plain HTTP, with fallback."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENDPOINT,
    CONF_ENGINES,
    CONF_FIRST_CHUNK_TIMEOUT,
    CONF_LANGUAGE,
    CONF_VOICE,
    CONF_VOICES,
    DEFAULT_FIRST_CHUNK_TIMEOUT,
    DOMAIN,
    PROSODY_OPTIONS,
)
from .gateway import DATA_GATEWAYS, Gateway
from .speech import SpeechOptions, parse_option, speech_options
from .view import TtsGatewayView

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR, Platform.TEXT]

type TtsGatewayConfigEntry = ConfigEntry[Gateway]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the one view that serves every gateway; views can't be removed later."""
    hass.data[DATA_GATEWAYS] = {}
    hass.http.register_view(TtsGatewayView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TtsGatewayConfigEntry) -> bool:
    """Set up a gateway from a config entry."""
    gateway = Gateway(
        hass,
        endpoint=entry.data[CONF_ENDPOINT],
        engines=list(entry.options[CONF_ENGINES]),
        language=entry.options[CONF_LANGUAGE],
        options=_configured_speech_options(entry),
        voices=dict(entry.options.get(CONF_VOICES, {})),
        first_chunk_timeout=entry.options.get(
            CONF_FIRST_CHUNK_TIMEOUT, DEFAULT_FIRST_CHUNK_TIMEOUT
        ),
    )
    gateway.loaded_options = dict(entry.options)
    entry.runtime_data = gateway
    hass.data[DATA_GATEWAYS][gateway.endpoint] = gateway
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: TtsGatewayConfigEntry) -> bool:
    """Migrate older entries: 1.1 had one voice for every engine instead of one per engine."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        options = dict(entry.options)
        voice = options.pop(CONF_VOICE, None)
        options[CONF_VOICES] = (
            {engine: voice for engine in options.get(CONF_ENGINES, [])} if voice else {}
        )
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TtsGatewayConfigEntry) -> bool:
    """Unload a gateway; its URL answers 404 until it's loaded again."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DATA_GATEWAYS].pop(entry.runtime_data.endpoint, None)
    return unloaded


def _configured_speech_options(entry: TtsGatewayConfigEntry) -> SpeechOptions:
    """Return the rate, pitch and volume stored in the entry, skipping ones that don't parse."""
    values: dict[str, str | float] = {}
    for name in PROSODY_OPTIONS:
        if (value := entry.options.get(name)) in (None, ""):
            continue
        try:
            values[name] = parse_option(name, value)
        except ValueError:
            # Saved by an older version in other units, e.g. a rate of +20%
            _LOGGER.warning(
                "Ignoring the %s option %r of %s; set it again", name, value, entry.title
            )
    return speech_options(values)


async def _async_update_listener(hass: HomeAssistant, entry: TtsGatewayConfigEntry) -> None:
    # A voice entity already applied its change; anything else needs the gateway set up again
    if entry.options == entry.runtime_data.loaded_options:
        return
    await hass.config_entries.async_reload(entry.entry_id)
