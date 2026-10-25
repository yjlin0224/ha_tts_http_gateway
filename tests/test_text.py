"""Tests for the per-engine voice entities."""

from __future__ import annotations

from homeassistant.components.text import ATTR_VALUE
from homeassistant.components.text import DOMAIN as TEXT_DOMAIN
from homeassistant.components.text import SERVICE_SET_VALUE
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.tts_http_gateway.const import CONF_ENGINES, CONF_VOICES

from .conftest import ENDPOINT, FakeEngine

URL = f"/api/tts_http_gateway/{ENDPOINT}"


async def _set(hass: HomeAssistant, entity_id: str, value: str) -> None:
    await hass.services.async_call(
        TEXT_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_one_voice_entity_per_engine(
    hass: HomeAssistant, gateway_entry: MockConfigEntry
) -> None:
    first = hass.states.get("text.reader_first_voice")
    second = hass.states.get("text.reader_second_voice")
    assert first is not None and second is not None
    assert first.state == "zh-TW-HsiaoChenNeural"
    assert first.attributes["engine"] == "tts.first"
    assert second.state == "second-voice"


async def test_setting_a_voice_applies_without_reloading(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    gateway = gateway_entry.runtime_data
    await _set(hass, "text.reader_first_voice", " v7 ")

    assert gateway_entry.runtime_data is gateway
    assert gateway.voices == {"tts.first": "v7", "tts.second": "second-voice"}
    assert gateway_entry.options[CONF_VOICES] == gateway.voices
    state = hass.states.get("text.reader_first_voice")
    assert state is not None and state.state == "v7"

    client = await hass_client_no_auth()
    await client.get(URL, params={"text": "新聲音"})
    assert engines[0].calls[-1][2] == {"voice": "v7"}

    # Empty leaves it to the engine's default voice
    await _set(hass, "text.reader_first_voice", "")
    assert gateway.voices == {"tts.second": "second-voice"}
    await client.get(URL, params={"text": "預設聲音"})
    assert engines[0].calls[-1][2] == {}


async def test_voice_entities_follow_the_engines(
    hass: HomeAssistant, gateway_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        gateway_entry, options={**gateway_entry.options, CONF_ENGINES: ["tts.second"]}
    )
    await hass.async_block_till_done()

    assert hass.states.get("text.reader_second_voice") is not None
    assert hass.states.get("text.reader_first_voice") is None
    assert er.async_get(hass).async_get("text.reader_first_voice") is None
