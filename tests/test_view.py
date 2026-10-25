"""Tests for the HTTP endpoint: parameters, fallback and cooldown."""

from __future__ import annotations

import asyncio
from http import HTTPStatus

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.tts_http_gateway.const import ENGINE_HEADER
from custom_components.tts_http_gateway.speech import SpeechOptions

from .conftest import ENDPOINT, FakeEngine, FakeStreamingEngine

URL = f"/api/tts_http_gateway/{ENDPOINT}"


async def test_first_engine_answers(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "你好", "rate": "1.5"})

    assert response.status == HTTPStatus.OK
    assert response.headers[ENGINE_HEADER] == "tts.first"
    assert response.content_type == "audio/mpeg"
    assert await response.read() == b"audio from first"
    assert engines[0].calls == [
        ("你好", "zh-TW", {"voice": "zh-TW-HsiaoChenNeural", "rate": "+50%"})
    ]
    assert engines[1].calls == []

    state = hass.states.get("sensor.reader_last_engine")
    assert state is not None
    assert state.state == "tts.first"
    assert state.attributes["engines"]["tts.first"]["successes"] == 1


async def test_falls_back_on_error(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    engines[0].error = HomeAssistantError("Connection reset")
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "第一句"})

    assert response.status == HTTPStatus.OK
    assert response.headers[ENGINE_HEADER] == "tts.second"
    assert await response.read() == b"first second"

    # Not an HTTP status worth a cooldown, so the next sentence tries the first engine again
    engines[0].error = None
    response = await client.get(URL, params={"text": "第二句"})
    assert response.headers[ENGINE_HEADER] == "tts.first"


async def test_rate_limit_starts_cooldown(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    engines[0].error = HomeAssistantError("Azure TTS failed with HTTP 429: Too many requests")
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "第一句"})
    assert response.headers[ENGINE_HEADER] == "tts.second"

    engines[0].error = None
    response = await client.get(URL, params={"text": "第二句"})
    assert response.headers[ENGINE_HEADER] == "tts.second"
    assert len(engines[0].calls) == 1

    state = hass.states.get("sensor.reader_last_engine")
    assert state is not None
    assert state.attributes["engines"]["tts.first"]["cooldown_until"] is not None


async def test_falls_back_when_first_chunk_is_late(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    engines[0].release = asyncio.Event()
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "慢"})

    assert response.headers[ENGINE_HEADER] == "tts.second"
    state = hass.states.get("sensor.reader_last_engine")
    assert state is not None
    assert state.attributes["engines"]["tts.first"]["last_error"] == "no audio within 0.2 s"

    # Let the abandoned synthesis finish so no task outlives the test
    engines[0].release.set()
    await hass.async_block_till_done()


async def test_error_after_first_chunk_ends_audio(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    engines[0].error = HomeAssistantError("down")
    second = engines[1]
    assert isinstance(second, FakeStreamingEngine)
    second.fail_after_first_chunk = HomeAssistantError("HTTP 429")
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "斷"})

    assert response.status == HTTPStatus.OK
    assert await response.read() == b"first "
    state = hass.states.get("sensor.reader_last_engine")
    assert state is not None
    assert state.attributes["engines"]["tts.second"]["failures"] == 1


async def test_every_engine_fails(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    # A language neither engine supports fails before any audio
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "x", "language": "fr-FR"})

    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    body = await response.text()
    assert "tts.first" in body and "tts.second" in body
    assert "fr-FR" in body


async def test_speech_option_parameters(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "a", "rate": "0.9", "voice": "v2"})
    assert response.status == HTTPStatus.OK
    assert engines[0].calls[-1][2] == {"voice": "v2", "rate": "-10%"}

    response = await client.get(URL, params={"text": "b", "rate": "1.2x", "pitch": "-2st"})
    assert engines[0].calls[-1][2] == {
        "voice": "zh-TW-HsiaoChenNeural",
        "rate": "+20%",
        "pitch": "-22Hz",
    }

    for params in ({"rate": "+20%"}, {"rate": "9"}, {"pitch": "+10Hz"}, {"volume": "-50%"}):
        response = await client.get(URL, params={"text": "c", **params})
        assert response.status == HTTPStatus.BAD_REQUEST
        assert next(iter(params)) in await response.text()


async def test_parameters_override_configured_options(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    gateway_entry.runtime_data.options = SpeechOptions(rate=1.1, pitch=-1.0, volume=80.0)
    gateway_entry.runtime_data.voices = {"tts.first": "v1"}
    client = await hass_client_no_auth()

    # Volume isn't passed to the first engine, which doesn't take it
    await client.get(URL, params={"text": "a"})
    assert engines[0].calls[-1][2] == {"voice": "v1", "rate": "+10%", "pitch": "-11Hz"}

    # An empty parameter keeps the configured value
    await client.get(URL, params={"text": "b", "rate": "0.8", "pitch": "", "voice": "v2"})
    assert engines[0].calls[-1][2] == {"voice": "v2", "rate": "-20%", "pitch": "-11Hz"}


async def test_each_engine_gets_its_voice(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    engines[0].error = HomeAssistantError("down")
    client = await hass_client_no_auth()
    await client.get(URL, params={"text": "聲音"})
    assert engines[0].calls[-1][2] == {"voice": "zh-TW-HsiaoChenNeural"}
    assert engines[1].calls[-1][2] == {"voice": "second-voice"}

    # A request's voice replaces every engine's
    await client.get(URL, params={"text": "聲音二", "voice": "v9"})
    assert engines[0].calls[-1][2] == {"voice": "v9"}
    assert engines[1].calls[-1][2] == {"voice": "v9"}


async def test_volume_only_reaches_engines_that_take_it(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    engines[0].error = HomeAssistantError("down")
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "音量", "volume": "50"})

    assert response.headers[ENGINE_HEADER] == "tts.second"
    assert "volume" not in engines[0].calls[-1][2]
    assert engines[1].calls[-1][2]["volume"] == "-50%"


async def test_post(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    engines: list[FakeEngine],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    client = await hass_client_no_auth()
    response = await client.post(URL, json={"text": "json", "rate": 1})
    assert response.status == HTTPStatus.OK
    response = await client.post(f"{URL}?rate=1.2", data={"message": "form"})
    assert response.status == HTTPStatus.OK
    assert [call[0] for call in engines[0].calls] == ["json", "form"]

    response = await client.post(URL, json=["not", "an", "object"])
    assert response.status == HTTPStatus.BAD_REQUEST


async def test_unknown_endpoint(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    client = await hass_client_no_auth()
    response = await client.get(URL)
    assert response.status == HTTPStatus.BAD_REQUEST
    # The endpoint is the secret, so a wrong one says nothing about the right one
    response = await client.get("/api/tts_http_gateway/reader", params={"text": "a"})
    assert response.status == HTTPStatus.NOT_FOUND
    assert await response.text() == "Not found"


async def test_unload(
    hass: HomeAssistant,
    gateway_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    assert await hass.config_entries.async_unload(gateway_entry.entry_id)
    client = await hass_client_no_auth()
    response = await client.get(URL, params={"text": "a"})
    assert response.status == HTTPStatus.NOT_FOUND
