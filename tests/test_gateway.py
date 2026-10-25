"""Tests for the HTTP status parsing."""

import pytest

from custom_components.tts_http_gateway.gateway import http_status


@pytest.mark.parametrize(
    ("message", "status"),
    [
        ("Azure TTS failed with HTTP 429: Too many requests", 429),
        ("Azure TTS failed with HTTP 403: Quota exceeded", 403),
        ("Request failed, status code: 401", 401),
        ("HTTP/503", 503),
        ("No audio received for 429 sentences", None),
        ("Connection reset", None),
    ],
)
def test_http_status(message: str, status: int | None) -> None:
    assert http_status(Exception(message)) == status
