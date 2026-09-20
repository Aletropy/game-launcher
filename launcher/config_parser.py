"""Parser and writer for bash-style .conf game configuration files."""

from __future__ import annotations

import re
from pathlib import Path

# Keys that should be stored as bash arrays: ("item1" "item2")
_ARRAY_KEYS = {"GAME_ARGS", "ADDITIONAL_DLLS", "extra_vars"}

# Regex that matches a single line: KEY=value or KEY="value" or KEY=(array)
_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
_ARRAY_RE = re.compile(r'^\((?P<items>.*)\)\s*$')
_QUOTED_RE = re.compile(r'^"(?P<inner>.*)"$')


def _unquote(raw: str) -> str:
    """Strip surrounding quotes from a value if present."""
    m = _QUOTED_RE.match(raw)
    return m.group("inner") if m else raw


def _parse_array(raw: str) -> list[str]:
    """Parse a bash-style array string into a Python list."""
    m = _ARRAY_RE.match(raw)
    if not m:
        return [_unquote(raw.strip())] if raw.strip() else []
    inner = m.group("items").strip()
    if not inner:
        return []
    return [_unquote(item.strip()) for item in inner.split('" "')]


def load(conf_path: str | Path) -> dict[str, str | list[str]]:
    """Parse a .conf file into a dict.

    Scalar values are plain strings. Array values (GAME_ARGS, ADDITIONAL_DLLS,
    extra_vars) are lists of strings.
    """
    data: dict[str, str | list[str]] = {}
    path = Path(conf_path)
    if not path.is_file():
        return data

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _KEY_RE.match(line)
        if not m:
            continue
        key = m.group("key")
        raw = m.group("value").strip()

        if key in _ARRAY_KEYS:
            data[key] = _parse_array(raw)
        else:
            data[key] = _unquote(raw)

    return data


def save(conf_path: str | Path, data: dict[str, str | list[str]]) -> None:
    """Write a .conf file from a dict.

    Writes scalar values as KEY="value" and array values as KEY=("a" "b").
    """
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            escaped = " ".join(f'"{item}"' for item in value)
            lines.append(f'{key}=({escaped})')
        else:
            lines.append(f'{key}="{value}"')

    Path(conf_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
