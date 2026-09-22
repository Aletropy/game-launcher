"""The built-in themes."""

from __future__ import annotations

from dataclasses import dataclass

from launcher.ui.theme.tokens import Palette


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    palette: Palette


THEMES: dict[str, Theme] = {
    theme.id: theme
    for theme in (
        Theme("midnight", "Midnight", Palette()),
        Theme(
            "steam",
            "Harbour",
            Palette(
                bg="#12161d", surface="#1a2230", raised="#243248", hover="#1f2a3b",
                pressed="#2b3b54", border="#2c3a50", border_hover="#41546f",
                fg="#c7d5e0", fg_bright="#eef4f8", fg_muted="#8196a8",
                fg_disabled="#46566a", on_accent="#0b1118",
                accent="#66c0f4", accent_hover="#86d0f8", accent_pressed="#4aa6dc",
                link="#66c0f4", placeholder_top="#1b2b40", placeholder_bottom="#111a26",
            ),
        ),
        Theme(
            "nebula",
            "Nebula",
            Palette(
                bg="#110f1a", surface="#18152a", raised="#241f3d", hover="#1e1a33",
                pressed="#2d2750", border="#322b52", border_hover="#4a4176",
                fg="#d6d0ee", fg_bright="#f2eeff", fg_muted="#8f87b3",
                fg_disabled="#4a4466", on_accent="#ffffff",
                accent="#8b5cf6", accent_hover="#a07cff", accent_pressed="#7443e0",
                link="#b69cff", placeholder_top="#2a1f4a", placeholder_bottom="#15112a",
            ),
        ),
        Theme(
            "frost",
            "Frost",
            Palette(
                bg="#1f232b", surface="#272c36", raised="#323846", hover="#2c313c",
                pressed="#3b4252", border="#3b4252", border_hover="#4c566a",
                fg="#d8dee9", fg_bright="#eceff4", fg_muted="#8a93a6",
                fg_disabled="#4c566a", on_accent="#1f232b",
                accent="#88c0d0", accent_hover="#9fd0de", accent_pressed="#6fa9ba",
                link="#88c0d0", placeholder_top="#2e3a4a", placeholder_bottom="#20262f",
            ),
        ),
        Theme(
            "ember",
            "Ember",
            Palette(
                bg="#140f0c", surface="#1d1612", raised="#2a201a", hover="#241b16",
                pressed="#352820", border="#3a2c23", border_hover="#564234",
                fg="#e8d9cc", fg_bright="#fbf1e8", fg_muted="#a38d7c",
                fg_disabled="#5a4a3f", on_accent="#1a0f08",
                accent="#f59e0b", accent_hover="#fbbf24", accent_pressed="#d97706",
                link="#fbbf24", placeholder_top="#3a2416", placeholder_bottom="#1a110c",
            ),
        ),
        Theme(
            "oled",
            "Pitch Black",
            Palette(
                bg="#000000", surface="#0a0a0b", raised="#17171a", hover="#111113",
                pressed="#202024", border="#232327", border_hover="#3a3a40",
                fg="#d4d4d8", fg_bright="#fafafa", fg_muted="#85858f",
                fg_disabled="#3f3f46", on_accent="#000000",
                accent="#22c55e", accent_hover="#4ade80", accent_pressed="#16a34a",
                link="#4ade80", placeholder_top="#141418", placeholder_bottom="#050506",
            ),
        ),
        Theme(
            "paper",
            "Paper",
            Palette(
                bg="#f4f5f7", surface="#ffffff", raised="#eceef2", hover="#f0f2f5",
                pressed="#e2e5ea", border="#d9dde3", border_hover="#b9c0ca",
                fg="#2b3038", fg_bright="#101318", fg_muted="#6b7280",
                fg_disabled="#b3b9c2", on_accent="#ffffff",
                accent="#2563eb", accent_hover="#3b82f6", accent_pressed="#1d4ed8",
                link="#2563eb", favorite="#d49b00", danger="#dc2626",
                placeholder_top="#dfe5ee", placeholder_bottom="#c9d2de",
                is_light=True,
            ),
        ),
    )
}

DEFAULT_THEME = "midnight"

#: Accent presets offered next to the theme's own.
ACCENTS: dict[str, str] = {
    "Green": "#22c55e",
    "Blue": "#3b82f6",
    "Sky": "#38bdf8",
    "Violet": "#8b5cf6",
    "Pink": "#ec4899",
    "Red": "#ef4444",
    "Orange": "#f97316",
    "Gold": "#eab308",
    "Teal": "#14b8a6",
}
