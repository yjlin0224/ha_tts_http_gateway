"""Tests for the speech option units and their conversion for each platform."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.tts_http_gateway.speech import (
    SpeechOptions,
    engine_options,
    parse_option,
    speech_options,
)


@pytest.mark.parametrize(
    ("name", "value", "parsed"),
    [
        ("rate", "1.2", 1.2),
        ("rate", "0.5x", 0.5),
        ("rate", " 2 ", 2.0),
        ("rate", 1.5, 1.5),
        ("pitch", "+2", 2.0),
        ("pitch", "-1.5st", -1.5),
        ("pitch", "0", 0.0),
        ("volume", "60", 60.0),
        ("volume", "0%", 0.0),
        ("volume", 100, 100.0),
        ("voice", " zh-TW-HsiaoChenNeural ", "zh-TW-HsiaoChenNeural"),
    ],
)
def test_parse_option(name: str, value: Any, parsed: str | float) -> None:
    assert parse_option(name, value) == parsed


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("rate", "fast"),
        ("rate", "+20%"),
        ("rate", "0.2"),
        ("rate", "5"),
        ("pitch", "+10Hz"),
        ("pitch", "21"),
        ("volume", "loud"),
        ("volume", "-50%"),
        ("volume", "120"),
    ],
)
def test_parse_option_rejects(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        parse_option(name, value)


def test_merged() -> None:
    configured = speech_options({"voice": "v1", "rate": 1.2, "volume": 50.0})
    assert configured.merged(speech_options({"rate": 0.8, "pitch": 2.0})) == SpeechOptions(
        voice="v1", rate=0.8, pitch=2.0, volume=50.0
    )


def _register(hass: HomeAssistant, platform: str) -> str:
    entry = er.async_get(hass).async_get_or_create("tts", platform, f"{platform}_engine")
    return entry.entity_id


@pytest.mark.parametrize(
    ("options", "edge", "azure"),
    [
        (
            SpeechOptions(voice="v", rate=1.5, pitch=2.0, volume=60.0),
            {"voice": "v", "rate": "+50%", "pitch": "+24Hz", "volume": "-40%"},
            {"voice": "v", "rate": "+50%", "pitch": "+2st", "volume": "-40%"},
        ),
        # The Microsoft service only speaks at 0.5 to 2 times the normal speed
        (
            SpeechOptions(rate=0.25, pitch=-12.0),
            {"rate": "-50%", "pitch": "-100Hz"},
            {"rate": "-50%", "pitch": "-12st"},
        ),
        (
            SpeechOptions(rate=4.0, pitch=-1.5, volume=100.0),
            {"rate": "+100%", "pitch": "-17Hz", "volume": "+0%"},
            {"rate": "+100%", "pitch": "-1.5st", "volume": "+0%"},
        ),
        (SpeechOptions(), {}, {}),
    ],
)
def test_microsoft_adapters(
    hass: HomeAssistant,
    options: SpeechOptions,
    edge: dict[str, str],
    azure: dict[str, str],
) -> None:
    assert engine_options(hass, _register(hass, "edge_tts"), options) == edge
    assert engine_options(hass, _register(hass, "azure_speech_tts"), options) == azure


ALL = SpeechOptions(voice="v", rate=1.5, pitch=2.0, volume=50.0)
LIMITS = SpeechOptions(rate=4.0, pitch=-20.0, volume=0.0)


@pytest.mark.parametrize(
    ("platform", "options", "expected"),
    [
        (
            "microsoft",
            ALL,
            {"voice": "v", "rate": "+50%", "pitch": "+12%", "volume": "-50%"},
        ),
        (
            "google_cloud",
            ALL,
            {"voice": "v", "speed": 1.5, "pitch": 2.0, "gain": -6.0},
        ),
        ("google_cloud", LIMITS, {"speed": 4.0, "pitch": -20.0, "gain": -96.0}),
        ("openai_tts", ALL, {"voice": "v", "speed": 1.5, "gain_db": -6.0}),
        ("openai_tts", LIMITS, {"speed": 4.0, "gain_db": -12.0}),
        ("kokoro_tts", ALL, {"persona": "v", "speed": 1.5, "volume_multiplier": 0.5}),
        ("fish_audio", ALL, {"voice_id": "v", "speed": 1.5}),
        ("fish_audio", LIMITS, {"speed": 2.0}),
    ],
)
def test_other_adapters(
    hass: HomeAssistant, platform: str, options: SpeechOptions, expected: dict[str, Any]
) -> None:
    assert engine_options(hass, _register(hass, platform), options) == expected


def test_unknown_platform_only_gets_the_voice(hass: HomeAssistant) -> None:
    assert engine_options(hass, _register(hass, "cloud"), ALL) == {"voice": "v"}
    assert engine_options(hass, _register(hass, "wyoming"), LIMITS) == {}
    assert engine_options(hass, "tts.not_registered", ALL) == {"voice": "v"}
