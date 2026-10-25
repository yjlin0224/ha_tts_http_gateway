"""Fixtures: fake TTS engines and a gateway that falls back through them."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.components.tts import DOMAIN as TTS_DOMAIN
from homeassistant.components.tts import (
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.tts_http_gateway.const import (
    CONF_ENDPOINT,
    CONF_ENGINES,
    CONF_FIRST_CHUNK_TIMEOUT,
    CONF_LANGUAGE,
    CONF_VOICES,
    DOMAIN,
)
from custom_components.tts_http_gateway.speech import ADAPTERS

FAKE_DOMAIN = "fake_tts"
ENDPOINT = "reader_Secret0123456789abcdef"


class FakeEngine(TextToSpeechEntity):
    """An engine that returns fixed audio, raises an error, or waits until released."""

    _attr_supported_languages = ["zh-TW", "en-US"]
    _attr_default_language = "en-US"
    # Like Azure Speech TTS: no volume
    _attr_supported_options = ["voice", "rate", "pitch"]

    def __init__(self, name: str, *, audio: bytes | None = None) -> None:
        self._attr_name = name
        self._attr_unique_id = name
        self.audio = audio if audio is not None else f"audio from {name}".encode()
        self.error: Exception | None = None
        self.release: asyncio.Event | None = None
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.voices: list[tuple[str, str]] | None = None

    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        if self.voices is None:
            return None
        return [Voice(voice_id, name) for voice_id, name in self.voices]

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        self.calls.append((message, language, dict(options)))
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return "mp3", self.audio


class FakeStreamingEngine(FakeEngine):
    """A streaming engine that can fail after its first chunk."""

    # Like Edge TTS: volume too
    _attr_supported_options = ["voice", "rate", "pitch", "volume"]

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.fail_after_first_chunk: Exception | None = None

    async def async_stream_tts_audio(self, request: TTSAudioRequest) -> TTSAudioResponse:
        message = "".join([chunk async for chunk in request.message_gen])
        self.calls.append((message, request.language, dict(request.options)))

        async def data_gen() -> AsyncGenerator[bytes]:
            yield b"first "
            # Give the gateway time to read the first chunk; an error before that falls back
            await asyncio.sleep(0.05)
            if self.fail_after_first_chunk is not None:
                raise self.fail_after_first_chunk
            yield b"second"

        return TTSAudioResponse("mp3", data_gen())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/ from the repository."""


@pytest.fixture(autouse=True)
def fake_adapter() -> Generator[None]:
    """Convert options for the fake engines the way Edge's adapter does."""
    with patch.dict(ADAPTERS, {FAKE_DOMAIN: ADAPTERS["edge_tts"]}):
        yield


@pytest.fixture(autouse=True)
def tts_cache_dir(tmp_path: Path) -> Generator[Path]:
    """Keep the TTS file cache out of the test configuration directory."""
    with patch("homeassistant.components.tts._init_tts_cache_dir", return_value=str(tmp_path)):
        yield tmp_path


class FakeFlow(ConfigFlow):
    """Config entries need a flow handler, even ones only created by tests."""


@pytest.fixture
def engines() -> list[FakeEngine]:
    first = FakeEngine("first")
    first.voices = [("zh-TW-HsiaoChenNeural", "HsiaoChen"), ("v1", "v1")]
    return [first, FakeStreamingEngine("second")]


@pytest.fixture
async def setup_engines(hass: HomeAssistant, engines: list[FakeEngine]) -> list[FakeEngine]:
    """Load the fake engines as tts.first and tts.second."""
    assert await async_setup_component(hass, TTS_DOMAIN, {})

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.TTS])
        return True

    async def async_setup_entry_platform(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        async_add_entities(engines)

    mock_integration(hass, MockModule(FAKE_DOMAIN, async_setup_entry=async_setup_entry))
    mock_platform(
        hass,
        f"{FAKE_DOMAIN}.{TTS_DOMAIN}",
        MockPlatform(async_setup_entry=async_setup_entry_platform),
    )
    mock_platform(hass, f"{FAKE_DOMAIN}.config_flow")
    entry = MockConfigEntry(domain=FAKE_DOMAIN)
    entry.add_to_hass(hass)
    with mock_config_flow(FAKE_DOMAIN, FakeFlow):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return engines


@pytest.fixture
def gateway_options() -> dict[str, Any]:
    return {
        CONF_ENGINES: ["tts.first", "tts.second"],
        CONF_LANGUAGE: "zh-TW",
        CONF_VOICES: {"tts.first": "zh-TW-HsiaoChenNeural", "tts.second": "second-voice"},
        CONF_FIRST_CHUNK_TIMEOUT: 0.2,
    }


@pytest.fixture
async def gateway_entry(
    hass: HomeAssistant, setup_engines: list[FakeEngine], gateway_options: dict[str, Any]
) -> MockConfigEntry:
    """A loaded gateway at /api/tts_http_gateway/<ENDPOINT>."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Reader",
        data={CONF_ENDPOINT: ENDPOINT},
        options=gateway_options,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
