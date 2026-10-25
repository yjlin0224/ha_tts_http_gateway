"""A text entity per engine for its voice, so voices can be set from the device page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_VOICES, DOMAIN

if TYPE_CHECKING:
    from . import TtsGatewayConfigEntry


def _unique_id(entry: TtsGatewayConfigEntry, engine: str) -> str:
    return f"{entry.entry_id}_voice_{engine}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TtsGatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    gateway = entry.runtime_data
    registry = er.async_get(hass)

    # Engines taken out of the gateway leave their voice entities behind; remove those
    current = {_unique_id(entry, engine) for engine in gateway.engines}
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            registered.domain == Platform.TEXT
            and registered.unique_id.startswith(f"{entry.entry_id}_voice_")
            and registered.unique_id not in current
        ):
            registry.async_remove(registered.entity_id)

    async_add_entities(
        VoiceText(entry, engine, _engine_name(hass, engine)) for engine in gateway.engines
    )


def _engine_name(hass: HomeAssistant, engine: str) -> str:
    """The engine's name as Home Assistant shows it, for the entity's name."""
    if (registered := er.async_get(hass).async_get(engine)) is not None:
        if name := registered.name or registered.original_name:
            return name
    if (state := hass.states.get(engine)) is not None:
        return state.name
    return engine


class VoiceText(TextEntity):
    """The voice one engine gets; empty leaves it to the engine's default voice."""

    _attr_has_entity_name = True
    _attr_translation_key = "voice"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_native_min = 0
    _attr_native_max = 255

    def __init__(self, entry: TtsGatewayConfigEntry, engine: str, engine_name: str) -> None:
        self._entry = entry
        self._engine = engine
        self._attr_unique_id = _unique_id(entry, engine)
        self._attr_translation_placeholders = {"engine": engine_name}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_extra_state_attributes = {"engine": engine}

    @property
    def native_value(self) -> str:
        return self._entry.runtime_data.voices.get(self._engine, "")

    async def async_set_value(self, value: str) -> None:
        gateway = self._entry.runtime_data
        voices = dict(gateway.voices)
        if voice := value.strip():
            voices[self._engine] = voice
        else:
            voices.pop(self._engine, None)

        # Takes effect right away; the stored options only need to match, so saving them doesn't
        # reload the entry (see _async_update_listener)
        gateway.voices = voices
        options = {**self._entry.options, CONF_VOICES: voices}
        gateway.loaded_options = options
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
