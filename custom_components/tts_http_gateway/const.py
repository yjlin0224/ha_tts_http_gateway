"""Constants for TTS HTTP Gateway."""

from typing import Final

DOMAIN: Final = "tts_http_gateway"

# Config entry data: the last part of the URL, generated and kept secret like a token
CONF_ENDPOINT: Final = "endpoint"

# Config entry options: changeable in the options flow
CONF_ENGINES: Final = "engines"
CONF_LANGUAGE: Final = "language"
CONF_VOICE: Final = "voice"
CONF_RATE: Final = "rate"
CONF_PITCH: Final = "pitch"
CONF_VOLUME: Final = "volume"

# Options passed to the engines, each only to those whose supported_options list it. A request's
# parameter of the same name overrides the configured value.
SPEECH_OPTIONS: Final = (CONF_VOICE, CONF_RATE, CONF_PITCH, CONF_VOLUME)
# The ones set for the whole gateway; the voice is set for each engine (CONF_VOICES)
PROSODY_OPTIONS: Final = (CONF_RATE, CONF_PITCH, CONF_VOLUME)
CONF_FIRST_CHUNK_TIMEOUT: Final = "first_chunk_timeout"
# Each engine's voice, by entity ID: voice names differ between platforms
CONF_VOICES: Final = "voices"

# Options flow only, never stored
CONF_REGENERATE_ENDPOINT: Final = "regenerate_endpoint"

DEFAULT_LANGUAGE: Final = "zh-TW"
DEFAULT_FIRST_CHUNK_TIMEOUT: Final = 5.0

# The last engine has nothing to fall back to, so it gets at least this long
LAST_ENGINE_MIN_TIMEOUT: Final = 30.0

# Seconds an engine is skipped after it answers with one of these HTTP statuses. 429 is a rate or
# concurrency limit and clears quickly; 401 and 403 mean a bad key or a used-up quota.
COOLDOWN_SECONDS: Final[dict[int, float]] = {
    401: 3600.0,
    403: 3600.0,
    429: 60.0,
}

URL_PATH: Final = "/api/tts_http_gateway/{endpoint}"

ENGINE_HEADER: Final = "X-TTS-Engine"
