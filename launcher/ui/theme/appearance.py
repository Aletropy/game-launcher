"""How the launcher looks: theme, accent, corners, density and text.

One Appearance is current at a time. `apply` restyles the application and
tells anything that paints itself to repaint; painted widgets read
`palette()` while painting rather than holding on to colours.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from launcher.ui.theme.qss import build_stylesheet
from launcher.ui.theme.themes import DEFAULT_THEME, all_themes, get_theme
from launcher.ui.theme.tokens import Metrics, Palette

if TYPE_CHECKING:
    from launcher.data.settings_store import SettingsStore

#: Corner style -> (small, normal, large) radius.
CORNERS: dict[str, tuple[str, tuple[int, int, int]]] = {
    "square": ("Square", (2, 2, 3)),
    "rounded": ("Rounded", (4, 6, 10)),
    "soft": ("Soft", (6, 10, 16)),
}
#: Density -> (label, library row height, row icon size, button padding).
DENSITIES: dict[str, tuple[str, int, int, int]] = {
    "compact": ("Compact", 36, 26, 4),
    "comfortable": ("Comfortable", 46, 34, 6),
    "spacious": ("Spacious", 58, 44, 8),
}
TEXT_SCALES = (90, 100, 110, 125)


def _mix(a: str, b: str, amount: float) -> str:
    """`amount` of colour a over colour b."""
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() * amount + cb.red() * (1 - amount)),
        round(ca.green() * amount + cb.green() * (1 - amount)),
        round(ca.blue() * amount + cb.blue() * (1 - amount)),
    ).name()


def _readable_on(colour: str) -> str:
    """Black or white, whichever reads better on a colour."""
    c = QColor(colour)
    luminance = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return "#0b0d10" if luminance > 0.55 else "#ffffff"


def derive_selection(colours: Palette) -> Palette:
    """Fill in the selected-row colour: the accent, faintly, over panels."""
    if colours.selection:
        return colours
    amount = 0.16 if colours.is_light else 0.22
    return replace(colours, selection=_mix(colours.accent, colours.surface, amount))


@dataclass(frozen=True)
class Appearance:
    """Every look-and-feel preference."""

    theme: str = DEFAULT_THEME
    #: An accent colour replacing the theme's own; empty keeps it.
    accent: str = ""
    corners: str = "rounded"
    density: str = "comfortable"
    text_scale: int = 100
    #: A font family; empty uses the system's.
    font: str = ""

    @classmethod
    def from_settings(cls, settings: SettingsStore) -> Appearance:
        base = cls()
        theme = settings.get_str("theme")
        corners = settings.get_str("corners")
        density = settings.get_str("density")
        scale = settings.get_int("text_scale")
        accent = settings.get_str("accent")
        return cls(
            theme=theme if theme in all_themes() else base.theme,
            accent=accent if QColor.isValidColorName(accent) else "",
            corners=corners if corners in CORNERS else base.corners,
            density=density if density in DENSITIES else base.density,
            text_scale=scale if scale in TEXT_SCALES else base.text_scale,
            font=settings.get_str("font"),
        )

    def to_settings(self) -> dict[str, Any]:
        return asdict(self)

    def with_(self, **changes: Any) -> Appearance:
        return replace(self, **changes)

    # -- derived tokens --------------------------------------------------

    def palette(self) -> Palette:
        base = get_theme(self.theme).palette
        if self.accent:
            accent = QColor(self.accent)
            base = replace(
                base,
                accent=accent.name(),
                accent_hover=accent.lighter(115).name(),
                accent_pressed=accent.darker(115).name(),
                link=accent.darker(110).name() if base.is_light else accent.lighter(120).name(),
                on_accent=_readable_on(accent.name()),
            )
        return derive_selection(base)

    def metrics(self) -> Metrics:
        small, normal, large = CORNERS[self.corners][1]
        _, row, icon, _ = DENSITIES[self.density]
        scale = self.text_scale / 100

        def font(px: int) -> int:
            return max(8, round(px * scale))

        base = Metrics()
        return replace(
            base,
            radius_sm=small,
            radius=normal,
            radius_lg=large,
            font_xs=font(base.font_xs),
            font_sm=font(base.font_sm),
            font_md=font(base.font_md),
            font_lg=font(base.font_lg),
            font_xl=font(base.font_xl),
            font_display=font(base.font_display),
            font_stat=font(base.font_stat),
            row_height=round(row * max(1.0, scale)),
            icon_size=icon,
        )

    @property
    def button_padding(self) -> int:
        return DENSITIES[self.density][3]


# --------------------------------------------------------------------------
# the current appearance
# --------------------------------------------------------------------------


class _Notifier(QObject):
    changed = Signal()


class _State:
    """The appearance in effect, and what was derived from it."""

    def __init__(self) -> None:
        self.appearance = Appearance()
        self.palette = self.appearance.palette()
        self.metrics = self.appearance.metrics()
        self.notifier: _Notifier | None = None
        #: The platform font before any scaling, so scaling never compounds.
        self.base_font: QFont | None = None


_STATE = _State()


def current() -> Appearance:
    return _STATE.appearance


def palette() -> Palette:
    """The colours in effect. Read while painting; never cache it."""
    return _STATE.palette


def metrics() -> Metrics:
    return _STATE.metrics


def notifier() -> _Notifier:
    """Emits `changed` after a new appearance has been applied."""
    if _STATE.notifier is None:
        _STATE.notifier = _Notifier()
    return _STATE.notifier


def _icon_dir() -> Path:
    """Per-user, so another account cannot plant files in it."""
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    directory = Path(cache) / "launcher" / "theme"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _svg(name: str, colour: str, path: str, width: float = 2.0) -> str:
    """Write a small stroked icon and return its path, for url() in QSS."""
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
        f"<path d='{path}' fill='none' stroke='{colour}' stroke-width='{width}' "
        "stroke-linecap='round' stroke-linejoin='round'/></svg>"
    )
    digest = hashlib.sha1(svg.encode(), usedforsecurity=False).hexdigest()[:10]
    target = _icon_dir() / f"{name}-{digest}.svg"
    if not target.exists():
        target.write_text(svg, encoding="utf-8")
    return target.as_posix()


def indicator_icons(colours: Palette) -> dict[str, str]:
    """Checkmark and arrows, drawn in the theme's colours.

    Generated rather than shipped, so they follow any accent.
    """
    return {
        "icon_check": _svg("check", colours.on_accent, "M3.5 8.5l3 3 6-7", 2.2),
        "icon_down": _svg("down", colours.fg_muted, "M4 6l4 4 4-4", 1.6),
        "icon_up": _svg("up", colours.fg_muted, "M4 10l4-4 4 4", 1.6),
    }


def _qt_palette(colours: Palette) -> QPalette:
    """The platform palette, for what stylesheets do not reach: links,
    selection in text fields, tooltips."""
    qp = QPalette()
    roles = QPalette.ColorRole
    for role, colour in (
        (roles.Window, colours.bg),
        (roles.WindowText, colours.fg_bright),
        (roles.Base, colours.surface),
        (roles.AlternateBase, colours.raised),
        (roles.Text, colours.fg_bright),
        (roles.Button, colours.raised),
        (roles.ButtonText, colours.fg),
        (roles.Highlight, colours.accent),
        (roles.HighlightedText, colours.on_accent),
        (roles.Link, colours.link),
        (roles.LinkVisited, colours.link),
        (roles.ToolTipBase, colours.surface),
        (roles.ToolTipText, colours.fg_bright),
        (roles.PlaceholderText, colours.fg_muted),
    ):
        qp.setColor(role, QColor(colour))
    return qp


def apply(app: QApplication, appearance: Appearance | None = None) -> None:
    """Restyle the whole application."""
    state = _STATE
    appearance = appearance or state.appearance
    state.appearance = appearance
    state.palette = colours = appearance.palette()
    state.metrics = appearance.metrics()

    if state.base_font is None:
        state.base_font = QFont(app.font())
    base = state.base_font
    font = QFont(base)
    if appearance.font:
        font.setFamily(appearance.font)
    if font.pointSizeF() > 0:
        font.setPointSizeF(base.pointSizeF() * appearance.text_scale / 100)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    app.setFont(font)

    app.setPalette(_qt_palette(colours))
    app.setStyleSheet(
        build_stylesheet(
            colours,
            state.metrics,
            icons=indicator_icons(colours),
            button_padding=appearance.button_padding,
        )
    )
    notifier().changed.emit()
