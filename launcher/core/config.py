"""Parser and writer for bash-style .conf game configuration files."""

from __future__ import annotations

import re
from pathlib import Path

# Keys that should be stored as bash arrays: ("item1" "item2")
_ARRAY_KEYS = {"GAME_ARGS", "ADDITIONAL_DLLS", "extra_vars"}

# Regex that matches a single line: KEY=value or KEY="value" or KEY=(array)
_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
_ARRAY_RE = re.compile(r'^\((?P<items>.*)\)\s*$')
# A double-quoted string, allowing backslash-escaped characters inside.
_QUOTED_RE = re.compile(r'^"(?P<inner>(?:[^"\\]|\\.)*)"$')
_ITEM_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')

# Characters bash still expands inside double quotes; they must be backslash
# escaped because game-launcher.sh sources these files.
_ESCAPE_RE = re.compile(r'([\\"`$])')
# Only the sequences we write are unescaped again, so a lone backslash in an
# older hand-written conf survives untouched.
_UNESCAPE_RE = re.compile(r'\\([\\"`$])')


def _escape(value: str) -> str:
    """Escape a value so bash reads it back verbatim from "..."."""
    return _ESCAPE_RE.sub(r"\\\1", value)


def _unescape(value: str) -> str:
    """Reverse :func:`_escape`."""
    return _UNESCAPE_RE.sub(r"\1", value)


def _unquote(raw: str) -> str:
    """Strip surrounding quotes from a value if present, undoing escapes."""
    m = _QUOTED_RE.match(raw)
    return _unescape(m.group("inner")) if m else raw


def _parse_array(raw: str) -> list[str]:
    """Parse a bash-style array string into a Python list."""
    m = _ARRAY_RE.match(raw)
    if not m:
        return [_unquote(raw.strip())] if raw.strip() else []
    inner = m.group("items").strip()
    if not inner:
        return []
    items = _ITEM_RE.findall(inner)
    if items:
        return [_unescape(item) for item in items]
    return [_unquote(item.strip()) for item in inner.split()]


_ENV_PAIR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def normalize_env_pairs(items: list[str]) -> list[str]:
    """Split packed "A=1 B=2" entries into separate environment pairs.

    Older configs stored several variables in a single array element.
    An element is only split when every resulting token is itself a
    KEY=VALUE pair, so a legitimate FOO="bar baz" keeps its value.
    """
    result: list[str] = []
    for item in items:
        parts = item.split()
        if len(parts) > 1 and all(_ENV_PAIR.match(p) for p in parts):
            result.extend(parts)
        else:
            result.append(item)
    return result


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
            values = _parse_array(raw)
            data[key] = normalize_env_pairs(values) if key == "extra_vars" else values
        else:
            data[key] = _unquote(raw)

    return data


def save(conf_path: str | Path, data: dict[str, str | list[str]]) -> None:
    """Write a .conf file from a dict.

    Writes scalar values as KEY="value" and array values as KEY=("a" "b").
    Values are escaped so that sourcing the file in bash cannot execute them.
    """
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            escaped = " ".join(f'"{_escape(item)}"' for item in value)
            lines.append(f'{key}=({escaped})')
        else:
            lines.append(f'{key}="{_escape(str(value))}"')

    Path(conf_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
