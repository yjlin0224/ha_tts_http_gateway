"""Synthesize speech with the first engine that answers, falling back down an ordered list."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.tts.const import DATA_TTS_MANAGER
from homeassistant.components.tts.helper import get_engine_instance
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import COOLDOWN_SECONDS, DOMAIN, LAST_ENGINE_MIN_TIMEOUT
from .speech import SpeechOptions, engine_options

_LOGGER = logging.getLogger(__name__)

# Engines report HTTP errors only as text, e.g. "Azure TTS failed with HTTP 429: ..."
_HTTP_STATUS_RE = re.compile(r"\b(?:HTTP|status(?: code)?)[\s:/]*(\d{3})\b", re.IGNORECASE)

DATA_GATEWAYS: HassKey[dict[str, Gateway]] = HassKey(DOMAIN)


def http_status(err: BaseException) -> int | None:
    """Return the HTTP status an engine's error message mentions, if any."""
    if match := _HTTP_STATUS_RE.search(str(err)):
        return int(match.group(1))
    return None


@dataclass
class EngineStats:
    """What a gateway has seen from one engine since it was loaded."""

    successes: int = 0
    failures: int = 0
    last_error: str | None = None
    cooldown_until: datetime | None = None

    def cooling_down(self, now: datetime) -> bool:
        return self.cooldown_until is not None and self.cooldown_until > now


@dataclass
class SpeechResult:
    """Audio from the engine that answered. chunks yields the rest after first_chunk."""

    engine: str
    content_type: str
    first_chunk: bytes
    chunks: AsyncGenerator[bytes]


class NoEngineAvailableError(HomeAssistantError):
    """Every engine failed or is cooling down."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("No TTS engine produced audio: " + "; ".join(errors))
        self.errors = errors


class Gateway:
    """One configured endpoint and the engines it falls back through."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        endpoint: str,
        engines: list[str],
        language: str,
        options: SpeechOptions,
        voices: dict[str, str],
        first_chunk_timeout: float,
    ) -> None:
        self.hass = hass
        self.endpoint = endpoint
        self.engines = engines
        self.language = language
        # Configured speech options; a request's parameters override them
        self.options = options
        # Each engine's voice; a request's voice replaces all of them
        self.voices = voices
        # The entry options this gateway was set up from, kept up to date by the voice entities
        self.loaded_options: dict[str, Any] = {}
        self.first_chunk_timeout = first_chunk_timeout
        self.stats = {engine: EngineStats() for engine in engines}
        self.last_engine: str | None = None
        self.last_first_chunk_ms: int | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call listener whenever the stats change; returns a function that removes it."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _async_notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def async_synthesize(
        self, message: str, *, options: SpeechOptions, language: str | None
    ) -> SpeechResult:
        """Return the audio of the first engine that yields a chunk in time.

        An engine is skipped while it cools down. Errors after the first chunk can't fall back,
        because the response has already started; report them with async_record_stream_error.
        """
        errors: list[str] = []
        for index, engine in enumerate(self.engines):
            stats = self.stats[engine]
            now = dt_util.utcnow()
            if stats.cooling_down(now):
                assert stats.cooldown_until is not None
                remaining = (stats.cooldown_until - now).total_seconds()
                errors.append(f"{engine}: cooling down for {remaining:.0f} s")
                continue

            timeout = self.first_chunk_timeout
            if index == len(self.engines) - 1:
                timeout = max(timeout, LAST_ENGINE_MIN_TIMEOUT)

            start = asyncio.get_running_loop().time()
            try:
                result = await self._async_try_engine(
                    engine, message, options=options, language=language, timeout=timeout
                )
            except TimeoutError:
                self._record_failure(engine, f"no audio within {timeout:g} s", status=None)
            except Exception as err:  # noqa: BLE001  # engines raise anything
                self._record_failure(engine, str(err) or type(err).__name__, http_status(err))
            else:
                stats.successes += 1
                self.last_engine = engine
                self.last_first_chunk_ms = round(
                    (asyncio.get_running_loop().time() - start) * 1000
                )
                self._async_notify()
                return result
            errors.append(f"{engine}: {stats.last_error}")

        self._async_notify()
        raise NoEngineAvailableError(errors)

    async def _async_try_engine(
        self,
        engine: str,
        message: str,
        *,
        options: SpeechOptions,
        language: str | None,
        timeout: float,
    ) -> SpeechResult:
        if (engine_instance := get_engine_instance(self.hass, engine)) is None:
            raise HomeAssistantError(f"{engine} not found")

        # Converted for the engine's platform, then only what it accepts: Home Assistant rejects
        # unknown options. This is also why volume reaches Edge but not Azure Speech TTS.
        if options.voice is None:
            options = replace(options, voice=self.voices.get(engine))
        supported = engine_instance.supported_options or []
        converted: dict[str, Any] = {
            name: value
            for name, value in engine_options(self.hass, engine, options).items()
            if name in supported
        }

        # The file cache would keep every sentence of every book on disk; the memory cache still
        # answers repeats, like going back a sentence.
        stream = self.hass.data[DATA_TTS_MANAGER].async_create_result_stream(
            engine=engine,
            use_file_cache=False,
            language=language or None,
            options=converted,
        )
        stream.async_set_message(message)
        chunks = stream.async_stream_result()
        try:
            async with asyncio.timeout(timeout):
                first_chunk = b""
                while not first_chunk:
                    first_chunk = await anext(chunks)
        except StopAsyncIteration:
            raise HomeAssistantError("returned no audio") from None
        except BaseException:
            await chunks.aclose()
            raise
        return SpeechResult(engine, stream.content_type, first_chunk, chunks)

    @callback
    def async_record_stream_error(self, engine: str, err: Exception) -> None:
        """Count an error from an engine whose audio had already started."""
        self._record_failure(engine, str(err) or type(err).__name__, http_status(err))
        self._async_notify()

    def _record_failure(self, engine: str, error: str, status: int | None) -> None:
        stats = self.stats[engine]
        stats.failures += 1
        stats.last_error = error[:300]
        if (cooldown := COOLDOWN_SECONDS.get(status or 0)) is not None:
            stats.cooldown_until = dt_util.utcnow() + timedelta(seconds=cooldown)
            _LOGGER.warning("%s failed, skipping it for %g s: %s", engine, cooldown, error)
        else:
            _LOGGER.warning("%s failed: %s", engine, error)

    def attributes(self) -> dict[str, Any]:
        """Stats for the sensor's state attributes."""
        now = dt_util.utcnow()
        return {
            "first_chunk_ms": self.last_first_chunk_ms,
            "engines": {
                engine: {
                    "successes": stats.successes,
                    "failures": stats.failures,
                    "last_error": stats.last_error,
                    "cooldown_until": (
                        stats.cooldown_until.isoformat() if stats.cooling_down(now) else None
                    ),
                }
                for engine, stats in self.stats.items()
            },
        }
