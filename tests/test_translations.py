"""Tests for the translation files, which hassfest checks on release."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

TRANSLATIONS = Path(__file__).parent.parent / "custom_components/tts_http_gateway/translations"


def _strings(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, str):
        yield path, node


@pytest.mark.parametrize("name", ["en.json", "zh-Hant.json"])
def test_no_html(name: str) -> None:
    # hassfest rejects anything that looks like a tag, even <random> as a placeholder
    strings = dict(_strings(json.loads((TRANSLATIONS / name).read_text(encoding="utf-8"))))
    assert not {path: text for path, text in strings.items() if re.search(r"<[^>]*>", text)}


def test_same_keys() -> None:
    english, chinese = (
        set(dict(_strings(json.loads((TRANSLATIONS / name).read_text(encoding="utf-8")))))
        for name in ("en.json", "zh-Hant.json")
    )
    assert english == chinese
