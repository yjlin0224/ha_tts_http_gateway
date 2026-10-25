"""Tests for the config and options flows."""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.tts_http_gateway.const import (
    CONF_ENDPOINT,
    CONF_ENGINES,
    CONF_FIRST_CHUNK_TIMEOUT,
    CONF_LANGUAGE,
    CONF_PITCH,
    CONF_RATE,
    CONF_REGENERATE_ENDPOINT,
    CONF_VOICE,
    CONF_VOICES,
    CONF_VOLUME,
    DOMAIN,
)
from custom_components.tts_http_gateway.speech import SpeechOptions

from .conftest import ENDPOINT, FakeEngine

USER_INPUT: dict[str, Any] = {
    "name": "My Reader",
    CONF_ENGINES: ["tts.first", "tts.second"],
    CONF_LANGUAGE: " zh-TW ",
    CONF_FIRST_CHUNK_TIMEOUT: 4,
}


async def _create(
    hass: HomeAssistant, user_input: dict[str, Any], voices: dict[str, str] | None = None
) -> Any:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    if result["type"] is FlowResultType.FORM and result["step_id"] == "voices":
        result = await hass.config_entries.flow.async_configure(result["flow_id"], voices or {})
    return result


async def test_user_flow(hass: HomeAssistant, setup_engines: list[FakeEngine]) -> None:
    result = await _create(hass, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My Reader"
    assert re.fullmatch(r"my_reader_[A-Za-z0-9]{22}", result["data"][CONF_ENDPOINT])
    assert result["options"] == {
        CONF_ENGINES: ["tts.first", "tts.second"],
        CONF_LANGUAGE: "zh-TW",
        CONF_FIRST_CHUNK_TIMEOUT: 4.0,
        CONF_VOICES: {},
    }

    # The random part keeps gateways with the same name apart
    second = await _create(hass, USER_INPUT)
    assert second["type"] is FlowResultType.CREATE_ENTRY
    assert second["data"][CONF_ENDPOINT] != result["data"][CONF_ENDPOINT]


async def test_user_flow_romanizes_or_drops_the_name(
    hass: HomeAssistant, setup_engines: list[FakeEngine]
) -> None:
    result = await _create(hass, {**USER_INPUT, "name": "閱讀器"})
    assert re.fullmatch(r"yue_du_qi_[A-Za-z0-9]{22}", result["data"][CONF_ENDPOINT])

    result = await _create(hass, {**USER_INPUT, "name": "！？"})
    assert result["title"] == "！？"
    assert re.fullmatch(r"[A-Za-z0-9]{22}", result["data"][CONF_ENDPOINT])


async def test_user_flow_errors(hass: HomeAssistant, setup_engines: list[FakeEngine]) -> None:
    result = await _create(hass, {**USER_INPUT, "name": " ", CONF_ENGINES: [], CONF_LANGUAGE: " "})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "name": "no_name",
        CONF_ENGINES: "no_engines",
        CONF_LANGUAGE: "no_language",
    }


async def test_user_flow_rejects_out_of_range(
    hass: HomeAssistant, setup_engines: list[FakeEngine]
) -> None:
    # The number selectors already hold rate, pitch and volume to their ranges
    for name, value in ((CONF_RATE, 9), (CONF_PITCH, 30), (CONF_VOLUME, -5)):
        with pytest.raises(InvalidData):
            await _create(hass, {**USER_INPUT, name: value})


async def test_user_flow_speech_options(
    hass: HomeAssistant, setup_engines: list[FakeEngine]
) -> None:
    result = await _create(hass, {**USER_INPUT, CONF_RATE: 1.25, CONF_PITCH: -2, CONF_VOLUME: 60})
    assert result["options"][CONF_RATE] == 1.25
    assert result["options"][CONF_PITCH] == -2.0
    assert result["options"][CONF_VOLUME] == 60.0
    assert result["result"].runtime_data.options == SpeechOptions(
        rate=1.25, pitch=-2.0, volume=60.0
    )


async def test_user_flow_voices(hass: HomeAssistant, setup_engines: list[FakeEngine]) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["step_id"] == "voices"
    fields = {str(marker): selector for marker, selector in result["data_schema"].schema.items()}
    # tts.first lists its voices, tts.second doesn't
    assert [option["value"] for option in fields["tts.first"].config["options"]] == [
        "zh-TW-HsiaoChenNeural",
        "v1",
    ]
    assert fields["tts.first"].config["custom_value"] is True
    assert "options" not in fields["tts.second"].config

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"tts.first": " v1 ", "tts.second": ""}
    )
    assert result["options"][CONF_VOICES] == {"tts.first": "v1"}
    assert result["result"].runtime_data.voices == {"tts.first": "v1"}


async def test_one_voice_for_all_engines_migrates(
    hass: HomeAssistant, setup_engines: list[FakeEngine]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Old",
        data={CONF_ENDPOINT: "old_Secret0123456789abcdef"},
        options={**USER_INPUT, CONF_LANGUAGE: "zh-TW", CONF_VOICE: "v1"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.minor_version == 2
    assert CONF_VOICE not in entry.options
    assert entry.options[CONF_VOICES] == {"tts.first": "v1", "tts.second": "v1"}
    assert entry.runtime_data.voices == {"tts.first": "v1", "tts.second": "v1"}


async def test_older_options_are_ignored(
    hass: HomeAssistant, setup_engines: list[FakeEngine]
) -> None:
    # Saved in the units of an earlier version
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Old",
        data={CONF_ENDPOINT: "old_Secret0123456789abcdef"},
        options={**USER_INPUT, CONF_LANGUAGE: "zh-TW", CONF_RATE: "+20%", CONF_PITCH: "+10Hz"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.options == SpeechOptions()


async def _configure_options(
    hass: HomeAssistant, entry: MockConfigEntry, user_input: dict[str, Any], voices: dict[str, str]
) -> Any:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["step_id"] == "voices"
    return await hass.config_entries.options.async_configure(result["flow_id"], voices)


async def test_options_flow(hass: HomeAssistant, gateway_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(gateway_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"path": f"/api/tts_http_gateway/{ENDPOINT}"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ENGINES: ["tts.second", "tts.first"],
            CONF_LANGUAGE: "en-US",
            CONF_RATE: 1.5,
            CONF_FIRST_CHUNK_TIMEOUT: 3,
            CONF_REGENERATE_ENDPOINT: False,
        },
    )
    assert result["step_id"] == "voices"
    # The current voices are suggested, in the new engine order
    markers = list(result["data_schema"].schema)
    assert [str(marker) for marker in markers] == ["tts.second", "tts.first"]
    assert [marker.description["suggested_value"] for marker in markers] == [
        "second-voice",
        "zh-TW-HsiaoChenNeural",
    ]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tts.second": "v2", "tts.first": "zh-TW-HsiaoChenNeural"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert gateway_entry.options == {
        CONF_ENGINES: ["tts.second", "tts.first"],
        CONF_LANGUAGE: "en-US",
        CONF_RATE: 1.5,
        CONF_FIRST_CHUNK_TIMEOUT: 3.0,
        CONF_VOICES: {"tts.second": "v2", "tts.first": "zh-TW-HsiaoChenNeural"},
    }
    assert gateway_entry.data[CONF_ENDPOINT] == ENDPOINT
    assert gateway_entry.runtime_data.engines == ["tts.second", "tts.first"]
    assert gateway_entry.runtime_data.voices == {
        "tts.second": "v2",
        "tts.first": "zh-TW-HsiaoChenNeural",
    }


async def test_options_flow_regenerates_endpoint(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    # Renamed since it was created; the new URL follows the current name
    hass.config_entries.async_update_entry(gateway_entry, title="Book Reader")
    result = await _configure_options(
        hass,
        gateway_entry,
        {
            CONF_ENGINES: ["tts.first"],
            CONF_LANGUAGE: "zh-TW",
            CONF_FIRST_CHUNK_TIMEOUT: 5,
            CONF_REGENERATE_ENDPOINT: True,
        },
        {},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    endpoint = gateway_entry.data[CONF_ENDPOINT]
    assert re.fullmatch(r"book_reader_[A-Za-z0-9]{22}", endpoint)
    assert gateway_entry.runtime_data.endpoint == endpoint

    client = await hass_client_no_auth()
    response = await client.get(f"/api/tts_http_gateway/{ENDPOINT}", params={"text": "a"})
    assert response.status == HTTPStatus.NOT_FOUND
    response = await client.get(f"/api/tts_http_gateway/{endpoint}", params={"text": "a"})
    assert response.status == HTTPStatus.OK
