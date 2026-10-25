"""Speech options in the gateway's own units, and their conversion for each TTS platform.

Home Assistant only standardizes the voice option; every integration names and scales the rest
its own way. Requests and settings therefore use one set of units, modeled on Google Cloud TTS:

- rate: a multiple of the normal speed, 1.0 is normal (0.25 to 4.0)
- pitch: semitones up or down, 0 is normal (-20 to 20)
- volume: a percentage of the normal volume, 100 is normal (0 to 100)

An adapter per platform turns them into that integration's options and clamps them to what it
accepts. Platforms without an adapter only get the voice.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from homeassistant.components.tts import ATTR_VOICE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_PITCH, CONF_RATE, CONF_VOICE, CONF_VOLUME

RATE_RANGE = (0.25, 4.0)
PITCH_RANGE = (-20.0, 20.0)
VOLUME_RANGE = (0.0, 100.0)

# Edge only takes the pitch in Hz, which depends on the voice. This is about the base frequency
# of a female voice; a male voice moves about half as much.
EDGE_PITCH_BASE_HZ = 200.0

_NUMBER_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_RATE_RE = re.compile(rf"^({_NUMBER_RE})x?$", re.IGNORECASE)
_PITCH_RE = re.compile(rf"^({_NUMBER_RE})(?:st)?$", re.IGNORECASE)
_VOLUME_RE = re.compile(rf"^({_NUMBER_RE})%?$")

OPTION_EXAMPLES = {
    CONF_RATE: "a multiple of the normal speed from 0.25 to 4, e.g. 1.2",
    CONF_PITCH: "semitones from -20 to 20, e.g. 2 or -1.5",
    CONF_VOLUME: "a percentage of the normal volume from 0 to 100, e.g. 60",
}


@dataclass(frozen=True)
class SpeechOptions:
    """Speech options in the gateway's units; None leaves an option to the engine."""

    voice: str | None = None
    rate: float | None = None
    pitch: float | None = None
    volume: float | None = None

    def merged(self, overrides: SpeechOptions) -> SpeechOptions:
        """Return these options with every option overrides sets replacing ours."""
        changes = {name: value for name, value in vars(overrides).items() if value is not None}
        return replace(self, **changes)


def _parse_number(pattern: re.Pattern[str], value: str, bounds: tuple[float, float]) -> float:
    if (match := pattern.match(value.strip())) is None:
        raise ValueError(f"Invalid value {value!r}")
    number = float(match.group(1))
    if not bounds[0] <= number <= bounds[1]:
        raise ValueError(f"{number:g} is out of range")
    return number


def parse_option(name: str, value: Any) -> str | float:
    """Parse a request parameter or setting; raise ValueError when it's invalid.

    Takes 1.2 or 1.2x for the rate, 2 or 2st for the pitch, and 60 or 60% for the volume.
    """
    if name == CONF_VOICE:
        return str(value).strip()
    pattern, bounds = {
        CONF_RATE: (_RATE_RE, RATE_RANGE),
        CONF_PITCH: (_PITCH_RE, PITCH_RANGE),
        CONF_VOLUME: (_VOLUME_RE, VOLUME_RANGE),
    }[name]
    return _parse_number(pattern, str(value), bounds)


def speech_options(values: dict[str, Any]) -> SpeechOptions:
    """Build options from parsed values, leaving out empty ones."""
    return SpeechOptions(
        **{
            name: values[name]
            for name in (CONF_VOICE, CONF_RATE, CONF_PITCH, CONF_VOLUME)
            if values.get(name) not in (None, "")
        }
    )


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _gain_db(volume: float, low: float, high: float) -> float:
    """Return a percentage of the normal volume as decibels of gain, within low to high."""
    if volume <= 0:
        return low
    return round(_clamp(20 * math.log10(volume / 100), low, high), 1)


def _microsoft_options(options: SpeechOptions, *, pitch_unit: str) -> dict[str, Any]:
    """Prosody for integrations of the Microsoft speech service: Edge and Azure.

    The service only speaks at 0.5 to 2 times the normal speed, and its normal volume is already
    the loudest. pitch_unit is what the integration takes: Edge only Hz, a signed whole number
    like its rate and volume; Azure Speech TTS semitones, which are exact; and the Microsoft
    integration from pajeronda/microsoft only % or Hz.
    """
    result: dict[str, Any] = {}
    if options.voice:
        result[ATTR_VOICE] = options.voice
    if options.rate is not None:
        result[CONF_RATE] = f"{round((_clamp(options.rate, 0.5, 2.0) - 1) * 100):+d}%"
    if options.pitch is not None:
        ratio = 2 ** (options.pitch / 12)
        if pitch_unit == "Hz":
            result[CONF_PITCH] = f"{round(EDGE_PITCH_BASE_HZ * (ratio - 1)):+d}Hz"
        elif pitch_unit == "%":
            result[CONF_PITCH] = f"{round((ratio - 1) * 100):+d}%"
        else:
            result[CONF_PITCH] = f"{options.pitch:+g}st"
    if options.volume is not None:
        result[CONF_VOLUME] = f"{round(options.volume - 100):+d}%"
    return result


def _google_cloud_options(options: SpeechOptions) -> dict[str, Any]:
    """Google Cloud TTS: the gateway's units, with the volume as -96 to 16 dB of gain."""
    result: dict[str, Any] = {}
    if options.voice:
        result[ATTR_VOICE] = options.voice
    if options.rate is not None:
        result["speed"] = options.rate
    if options.pitch is not None:
        result[CONF_PITCH] = options.pitch
    if options.volume is not None:
        result["gain"] = _gain_db(options.volume, -96.0, 16.0)
    return result


def _openai_tts_options(options: SpeechOptions) -> dict[str, Any]:
    """OpenAI TTS from sfortis/openai_tts: speed 0.25 to 4, and -12 to 12 dB of gain."""
    result: dict[str, Any] = {}
    if options.voice:
        result[ATTR_VOICE] = options.voice
    if options.rate is not None:
        result["speed"] = options.rate
    if options.volume is not None:
        result["gain_db"] = _gain_db(options.volume, -12.0, 12.0)
    return result


def _kokoro_options(options: SpeechOptions) -> dict[str, Any]:
    """Kokoro TTS from beecho01/Kokoro-TTS: the voice is a persona, the volume a multiplier."""
    result: dict[str, Any] = {}
    if options.voice:
        result["persona"] = options.voice
    if options.rate is not None:
        result["speed"] = options.rate
    if options.volume is not None:
        result["volume_multiplier"] = round(options.volume / 100, 2)
    return result


def _fish_audio_options(options: SpeechOptions) -> dict[str, Any]:
    """Fish Audio: the voice is a voice ID, and the speed must be 0.5 to 2."""
    result: dict[str, Any] = {}
    if options.voice:
        result["voice_id"] = options.voice
    if options.rate is not None:
        result["speed"] = _clamp(options.rate, 0.5, 2.0)
    return result


def _voice_only(options: SpeechOptions) -> dict[str, Any]:
    return {ATTR_VOICE: options.voice} if options.voice else {}


# Integration domains (an entity's platform) and how to convert for them. Only integrations with
# entities count: legacy providers like Baidu and Yandex can't be picked as engines. The others,
# e.g. Home Assistant Cloud, Piper (Wyoming), ElevenLabs and OpenAI in Home Assistant itself, take
# no speech options per request, so they only get the voice.
ADAPTERS: dict[str, Callable[[SpeechOptions], dict[str, Any]]] = {
    "edge_tts": lambda options: _microsoft_options(options, pitch_unit="Hz"),
    "azure_speech_tts": lambda options: _microsoft_options(options, pitch_unit="st"),
    # pajeronda/microsoft replaces the built-in Microsoft integration, which has no entities
    "microsoft": lambda options: _microsoft_options(options, pitch_unit="%"),
    "google_cloud": _google_cloud_options,
    "openai_tts": _openai_tts_options,
    "kokoro_tts": _kokoro_options,
    "fish_audio": _fish_audio_options,
}


def engine_options(hass: HomeAssistant, engine: str, options: SpeechOptions) -> dict[str, Any]:
    """Return the options for one engine, in its integration's names and formats."""
    entry = er.async_get(hass).async_get(engine)
    adapter = ADAPTERS.get(entry.platform if entry else "", _voice_only)
    return adapter(options)
