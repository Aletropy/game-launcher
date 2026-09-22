"""Design tokens.

Every colour and metric used by the stylesheet lives here, so a retheme is
a change to this file rather than a search-and-replace across QSS.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Surface, text and accent colours."""

    # Surfaces, darkest to lightest.
    bg: str = "#0d1117"
    surface: str = "#161b22"
    raised: str = "#21262d"
    hover: str = "#1c2128"
    pressed: str = "#282e33"

    # Lines.
    border: str = "#30363d"
    border_hover: str = "#484f58"

    # Text.
    fg: str = "#c9d1d9"
    fg_bright: str = "#e6edf3"
    fg_muted: str = "#8b949e"
    fg_disabled: str = "#484f58"
    on_accent: str = "#ffffff"

    # Accents.
    accent: str = "#238636"
    accent_hover: str = "#2ea043"
    accent_pressed: str = "#1a7f37"
    link: str = "#58a6ff"
    favorite: str = "#f0c040"
    danger: str = "#f85149"

    # Card placeholder gradient.
    placeholder_top: str = "#1a1e2e"
    placeholder_bottom: str = "#0f1923"

    #: The selected row: the accent, faintly, over the surface. Derived
    #: by the appearance when left empty.
    selection: str = ""
    #: Scrims and shadows stay dark over artwork in every theme, but a
    #: light theme needs darker text and softer lines everywhere else.
    is_light: bool = False


@dataclass(frozen=True)
class Metrics:
    """Spacing, radii and type sizes, in pixels."""

    radius_sm: int = 4
    radius: int = 6
    radius_lg: int = 10

    pad_sm: int = 6
    pad: int = 10
    pad_lg: int = 16

    font_xs: int = 11
    font_sm: int = 12
    font_md: int = 13
    font_lg: int = 14
    font_xl: int = 20
    font_display: int = 32
    font_stat: int = 24

    #: Library rows.
    row_height: int = 46
    icon_size: int = 34


DARK = Palette()
METRICS = Metrics()
