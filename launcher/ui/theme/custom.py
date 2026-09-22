"""Themes the user makes: generating them, checking them, keeping them.

Each custom theme is a small JSON file in the config directory, so it
can be backed up, shared, or edited by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields, replace
from pathlib import Path

from PySide6.QtGui import QColor

from launcher.ui.theme.themes import THEMES, Theme, all_themes, register, set_custom, unregister
from launcher.ui.theme.tokens import Palette

#: Palette fields that are colours, in the order the editor shows them.
COLOUR_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(Palette) if f.name not in ("is_light", "selection")
)
_FORMAT = 1


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------


def _with_lightness(colour: QColor, lightness: float, saturation: float | None = None) -> str:
    """The same hue at another HSL lightness (0-1)."""
    hue = colour.hslHueF()
    sat = colour.hslSaturationF() if saturation is None else saturation
    return QColor.fromHslF(max(hue, 0.0), min(1.0, sat), max(0.0, min(1.0, lightness))).name()


def luminance(colour: str) -> float:
    """WCAG relative luminance."""
    c = QColor(colour)

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(c.redF())
        + 0.7152 * channel(c.greenF())
        + 0.0722 * channel(c.blueF())
    )


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable_on(colour: str) -> str:
    """Near-black or white, whichever contrasts more with a colour."""
    dark, light = "#0b0d10", "#ffffff"
    return dark if contrast(dark, colour) >= contrast(light, colour) else light


def generate(background: str, accent: str, *, light: bool | None = None) -> Palette:
    """A whole palette from a background and an accent colour.

    Surfaces step away from the background, text is tinted with its hue,
    and the accent gets hover, pressed and readable-text variants.
    """
    bg = QColor(background)
    if light is None:
        light = luminance(background) > 0.35
    base_l = bg.lightnessF()
    # Keep text and lines barely tinted, however saturated the background.
    tint = min(bg.hslSaturationF(), 0.25)

    # Near black, equal lightness steps barely change luminance, so panels
    # and buttons would blend together; step further there.
    scale = 1.0 if light else 1.0 + max(0.0, 0.08 - base_l) * 8

    def step(amount: float) -> str:
        amount *= scale
        return _with_lightness(bg, base_l + (-amount if light else amount))

    def text(lightness: float) -> str:
        return _with_lightness(bg, lightness, tint * 0.6)

    acc = QColor(accent)
    return Palette(
        bg=bg.name(),
        surface=_with_lightness(bg, min(1.0, base_l + 0.03)) if light else step(0.035),
        raised=step(0.06 if light else 0.075),
        hover=step(0.03 if light else 0.055),
        pressed=step(0.09 if light else 0.1),
        border=step(0.12),
        border_hover=step(0.22 if light else 0.2),
        fg=text(0.2 if light else 0.82),
        fg_bright=text(0.07 if light else 0.94),
        fg_muted=text(0.45 if light else 0.6),
        fg_disabled=text(0.72 if light else 0.32),
        on_accent=readable_on(acc.name()),
        accent=acc.name(),
        accent_hover=acc.lighter(112).name(),
        accent_pressed=acc.darker(115).name(),
        link=acc.darker(115).name() if light else acc.lighter(125).name(),
        favorite="#d49b00" if light else "#f0c040",
        danger="#dc2626" if light else "#f85149",
        placeholder_top=step(0.1),
        placeholder_bottom=step(0.02),
        is_light=light,
    )


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

#: What must be readable on what: (label, foreground, background, minimum).
_CHECKS = (
    ("Text on the background", "fg", "bg", 4.5),
    ("Text on panels", "fg", "surface", 4.5),
    ("Headings", "fg_bright", "bg", 7.0),
    ("Secondary text", "fg_muted", "surface", 3.0),
    ("Button text on the accent", "on_accent", "accent", 4.5),
    ("Buttons against panels", "raised", "surface", 1.1),
)


def check(colours: Palette) -> list[tuple[str, float, float]]:
    """(what, ratio, minimum) for each pairing that matters."""
    return [
        (label, contrast(getattr(colours, fg), getattr(colours, bg)), minimum)
        for label, fg, bg, minimum in _CHECKS
    ]


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------


def slug(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return cleaned or "theme"


def to_json(theme: Theme) -> dict:
    return {
        "format": _FORMAT,
        "name": theme.label,
        "light": theme.palette.is_light,
        "colours": {name: getattr(theme.palette, name) for name in COLOUR_FIELDS},
    }


def from_json(raw: object, theme_id: str) -> Theme:
    """Read a theme, filling anything missing or invalid from Midnight."""
    if not isinstance(raw, dict):
        raise ValueError("not a theme file")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("the theme has no name")
    colours = raw.get("colours") or raw.get("colors") or {}
    if not isinstance(colours, dict):
        raise ValueError("the theme has no colours")
    base = THEMES["midnight"].palette
    values = {
        key: QColor(value).name()
        for key, value in colours.items()
        if key in COLOUR_FIELDS and isinstance(value, str) and QColor.isValidColorName(value)
    }
    if "bg" not in values or "accent" not in values:
        raise ValueError("a theme needs at least a background and an accent colour")
    palette = replace(base, **values, is_light=bool(raw.get("light", False)))
    return Theme(theme_id, name, palette, custom=True)


class CustomThemeStore:
    """The user's themes, as JSON files in one folder."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, theme_id: str) -> Path:
        return self.directory / f"{theme_id}.json"

    def load_all(self) -> list[Theme]:
        """Read every theme file and register the valid ones."""
        themes = []
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("*.json")):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    themes.append(from_json(raw, path.stem))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        set_custom(themes)
        return themes

    def new_id(self, name: str) -> str:
        """An id no theme has yet, derived from a name."""
        base = f"custom-{slug(name)}"
        taken = set(all_themes())
        candidate, n = base, 1
        while candidate in taken or self._path(candidate).exists():
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def save(self, theme: Theme) -> Theme:
        theme = replace(theme, custom=True)
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self._path(theme.id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(to_json(theme), indent=2), encoding="utf-8")
        tmp.replace(target)
        register(theme)
        return theme

    def delete(self, theme_id: str) -> None:
        self._path(theme_id).unlink(missing_ok=True)
        unregister(theme_id)

    def export(self, theme: Theme, target: Path) -> None:
        target.write_text(json.dumps(to_json(theme), indent=2), encoding="utf-8")

    def import_file(self, source: Path) -> Theme:
        """Add a theme from a file, under a new id so nothing is overwritten."""
        raw = json.loads(source.read_text(encoding="utf-8"))
        theme = from_json(raw, "pending")
        return self.save(replace(theme, id=self.new_id(theme.label)))
