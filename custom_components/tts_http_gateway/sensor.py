"""Sensor showing which engine answered last, with per-engine stats as attributes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN

if TYPE_CHECKING:
    from . import TtsGatewayConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TtsGatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LastEngineSensor(entry)])


class LastEngineSensor(SensorEntity):
    """The entity ID of the engine that produced the last response."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_engine"
    _attr_should_poll = False
    # The stats change with every request; recording them would add a row per sentence read
    _unrecorded_attributes = frozenset({"first_chunk_ms", "engines"})

    def __init__(self, entry: TtsGatewayConfigEntry) -> None:
        self._gateway = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_last_engine"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._gateway.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str | None:
        return self._gateway.last_engine

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._gateway.attributes()
