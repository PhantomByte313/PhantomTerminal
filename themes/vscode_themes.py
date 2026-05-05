"""
themes/vscode_themes.py
========================
VS Code color themes for the terminal emulator.
Includes Dark+, Light+, Monokai, Solarized, One Dark, etc.
All colors are matched pixel-perfect to VS Code's actual theme values.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class TerminalTheme:
    """Complete color theme for the terminal."""
    name:            str
    description:     str

    # Terminal background/foreground
    background:      str   # '#RRGGBB'
    foreground:      str
    cursor_color:    str
    cursor_text:     str   # Color of char under cursor
    selection_bg:    str
    selection_fg:    str   # '' = keep original

    # 16 ANSI colors
    black:           str
    red:             str
    green:           str
    yellow:          str
    blue:            str
    magenta:         str
    cyan:            str
    white:           str
    bright_black:    str
    bright_red:      str
    bright_green:    str
    bright_yellow:   str
    bright_blue:     str
    bright_magenta:  str
    bright_cyan:     str
    bright_white:    str

    # UI chrome colors
    tab_bar_bg:      str
    tab_active_bg:   str
    tab_inactive_bg: str
    tab_active_fg:   str
    tab_inactive_fg: str
    tab_active_border: str
    scrollbar_bg:    str
    scrollbar_thumb: str
    scrollbar_thumb_hover: str
    title_bar_bg:    str
    title_bar_fg:    str
    panel_border:    str
    toolbar_bg:      str
    toolbar_fg:      str
    button_bg:       str
    button_fg:       str
    button_hover_bg: str
    input_bg:        str
    input_fg:        str
    input_border:    str
    badge_bg:        str
    badge_fg:        str
    link_color:      str
    find_highlight:  str
    find_highlight_border: str

    def ansi_palette(self) -> list:
        """Return 16-color ANSI palette as list of '#RRGGBB' strings."""
        return [
            self.black, self.red, self.green, self.yellow,
            self.blue, self.magenta, self.cyan, self.white,
            self.bright_black, self.bright_red, self.bright_green,
            self.bright_yellow, self.bright_blue, self.bright_magenta,
            self.bright_cyan, self.bright_white,
        ]


# ─────────────────────────────────────────────────────────────────────────────
# VS Code Dark+ (Default Dark)
# ─────────────────────────────────────────────────────────────────────────────

DARK_PLUS = TerminalTheme(
    name        = "Dark+ (default dark)",
    description = "VS Code's default dark theme",

    background  = "#1e1e1e",
    foreground  = "#cccccc",
    cursor_color = "#aeafad",
    cursor_text  = "#1e1e1e",
    selection_bg = "#264f78",
    selection_fg = "",

    # ANSI colors (matched to VS Code Dark+ workbench)
    black          = "#000000",
    red            = "#cd3131",
    green          = "#0dbc79",
    yellow         = "#e5e510",
    blue           = "#2472c8",
    magenta        = "#bc3fbc",
    cyan           = "#11a8cd",
    white          = "#e5e5e5",
    bright_black   = "#666666",
    bright_red     = "#f14c4c",
    bright_green   = "#23d18b",
    bright_yellow  = "#f5f543",
    bright_blue    = "#3b8eea",
    bright_magenta = "#d670d6",
    bright_cyan    = "#29b8db",
    bright_white   = "#e5e5e5",

    # UI chrome
    tab_bar_bg       = "#252526",
    tab_active_bg    = "#1e1e1e",
    tab_inactive_bg  = "#2d2d2d",
    tab_active_fg    = "#ffffff",
    tab_inactive_fg  = "#8d8d8d",
    tab_active_border = "#0078d4",
    scrollbar_bg     = "#1e1e1e",
    scrollbar_thumb  = "#424242",
    scrollbar_thumb_hover = "#555555",
    title_bar_bg     = "#3c3c3c",
    title_bar_fg     = "#cccccc",
    panel_border     = "#464646",
    toolbar_bg       = "#252526",
    toolbar_fg       = "#cccccc",
    button_bg        = "#0e639c",
    button_fg        = "#ffffff",
    button_hover_bg  = "#1177bb",
    input_bg         = "#3c3c3c",
    input_fg         = "#cccccc",
    input_border     = "#0078d4",
    badge_bg         = "#4d4d4d",
    badge_fg         = "#ffffff",
    link_color       = "#3794ff",
    find_highlight   = "#9e6a03",
    find_highlight_border = "#d6a520",
)


# ─────────────────────────────────────────────────────────────────────────────
# VS Code Light+ (Default Light)
# ─────────────────────────────────────────────────────────────────────────────

LIGHT_PLUS = TerminalTheme(
    name        = "Light+ (default light)",
    description = "VS Code's default light theme",

    background  = "#ffffff",
    foreground  = "#333333",
    cursor_color = "#000000",
    cursor_text  = "#ffffff",
    selection_bg = "#add6ff",
    selection_fg = "",

    black          = "#000000",
    red            = "#cd3131",
    green          = "#008000",
    yellow         = "#795e26",
    blue           = "#0070c1",
    magenta        = "#af00db",
    cyan           = "#098658",
    white          = "#555555",
    bright_black   = "#666666",
    bright_red     = "#f14c4c",
    bright_green   = "#23d18b",
    bright_yellow  = "#f5f543",
    bright_blue    = "#3b8eea",
    bright_magenta = "#d670d6",
    bright_cyan    = "#29b8db",
    bright_white   = "#a5a5a5",

    tab_bar_bg       = "#f3f3f3",
    tab_active_bg    = "#ffffff",
    tab_inactive_bg  = "#ececec",
    tab_active_fg    = "#333333",
    tab_inactive_fg  = "#8f8f8f",
    tab_active_border = "#0078d4",
    scrollbar_bg     = "#f3f3f3",
    scrollbar_thumb  = "#c1c1c1",
    scrollbar_thumb_hover = "#a8a8a8",
    title_bar_bg     = "#dddddd",
    title_bar_fg     = "#333333",
    panel_border     = "#d4d4d4",
    toolbar_bg       = "#f3f3f3",
    toolbar_fg       = "#333333",
    button_bg        = "#0078d4",
    button_fg        = "#ffffff",
    button_hover_bg  = "#006abc",
    input_bg         = "#ffffff",
    input_fg         = "#333333",
    input_border     = "#0078d4",
    badge_bg         = "#c4c4c4",
    badge_fg         = "#333333",
    link_color       = "#006ab1",
    find_highlight   = "#a8c7fa",
    find_highlight_border = "#0078d4",
)


# ─────────────────────────────────────────────────────────────────────────────
# Monokai
# ─────────────────────────────────────────────────────────────────────────────

MONOKAI = TerminalTheme(
    name        = "Monokai",
    description = "Monokai classic theme",

    background  = "#272822",
    foreground  = "#f8f8f2",
    cursor_color = "#f8f8f0",
    cursor_text  = "#272822",
    selection_bg = "#49483e",
    selection_fg = "",

    black          = "#272822",
    red            = "#f92672",
    green          = "#a6e22e",
    yellow         = "#f4bf75",
    blue           = "#66d9ef",
    magenta        = "#ae81ff",
    cyan           = "#a1efe4",
    white          = "#f8f8f2",
    bright_black   = "#75715e",
    bright_red     = "#f92672",
    bright_green   = "#a6e22e",
    bright_yellow  = "#f4bf75",
    bright_blue    = "#66d9ef",
    bright_magenta = "#ae81ff",
    bright_cyan    = "#a1efe4",
    bright_white   = "#f9f8f5",

    tab_bar_bg       = "#1e1f1c",
    tab_active_bg    = "#272822",
    tab_inactive_bg  = "#232421",
    tab_active_fg    = "#f8f8f2",
    tab_inactive_fg  = "#75715e",
    tab_active_border = "#a6e22e",
    scrollbar_bg     = "#272822",
    scrollbar_thumb  = "#49483e",
    scrollbar_thumb_hover = "#75715e",
    title_bar_bg     = "#1e1f1c",
    title_bar_fg     = "#f8f8f2",
    panel_border     = "#464741",
    toolbar_bg       = "#1e1f1c",
    toolbar_fg       = "#f8f8f2",
    button_bg        = "#a6e22e",
    button_fg        = "#272822",
    button_hover_bg  = "#c1f55e",
    input_bg         = "#3e3d32",
    input_fg         = "#f8f8f2",
    input_border     = "#a6e22e",
    badge_bg         = "#49483e",
    badge_fg         = "#f8f8f2",
    link_color       = "#66d9ef",
    find_highlight   = "#ffe792",
    find_highlight_border = "#f4bf75",
)


# ─────────────────────────────────────────────────────────────────────────────
# One Dark Pro
# ─────────────────────────────────────────────────────────────────────────────

ONE_DARK = TerminalTheme(
    name        = "One Dark Pro",
    description = "Atom's iconic One Dark theme",

    background  = "#282c34",
    foreground  = "#abb2bf",
    cursor_color = "#528bff",
    cursor_text  = "#282c34",
    selection_bg = "#3e4451",
    selection_fg = "",

    black          = "#3f4451",
    red            = "#e06c75",
    green          = "#98c379",
    yellow         = "#e5c07b",
    blue           = "#61afef",
    magenta        = "#c678dd",
    cyan           = "#56b6c2",
    white          = "#abb2bf",
    bright_black   = "#4f5666",
    bright_red     = "#be5046",
    bright_green   = "#98c379",
    bright_yellow  = "#d19a66",
    bright_blue    = "#4dc4ff",
    bright_magenta = "#ff80ff",
    bright_cyan    = "#4cd1e0",
    bright_white   = "#ffffff",

    tab_bar_bg       = "#21252b",
    tab_active_bg    = "#282c34",
    tab_inactive_bg  = "#21252b",
    tab_active_fg    = "#abb2bf",
    tab_inactive_fg  = "#5c6370",
    tab_active_border = "#528bff",
    scrollbar_bg     = "#282c34",
    scrollbar_thumb  = "#4b5263",
    scrollbar_thumb_hover = "#606d7c",
    title_bar_bg     = "#21252b",
    title_bar_fg     = "#abb2bf",
    panel_border     = "#181a1f",
    toolbar_bg       = "#21252b",
    toolbar_fg       = "#abb2bf",
    button_bg        = "#528bff",
    button_fg        = "#ffffff",
    button_hover_bg  = "#6da5ff",
    input_bg         = "#1d2026",
    input_fg         = "#abb2bf",
    input_border     = "#528bff",
    badge_bg         = "#528bff",
    badge_fg         = "#ffffff",
    link_color       = "#61afef",
    find_highlight   = "#e5c07b",
    find_highlight_border = "#d19a66",
)


# ─────────────────────────────────────────────────────────────────────────────
# Solarized Dark
# ─────────────────────────────────────────────────────────────────────────────

SOLARIZED_DARK = TerminalTheme(
    name        = "Solarized Dark",
    description = "Ethan Schoonover's Solarized Dark",

    background  = "#002b36",
    foreground  = "#839496",
    cursor_color = "#839496",
    cursor_text  = "#002b36",
    selection_bg = "#073642",
    selection_fg = "",

    black          = "#073642",
    red            = "#dc322f",
    green          = "#859900",
    yellow         = "#b58900",
    blue           = "#268bd2",
    magenta        = "#d33682",
    cyan           = "#2aa198",
    white          = "#eee8d5",
    bright_black   = "#002b36",
    bright_red     = "#cb4b16",
    bright_green   = "#586e75",
    bright_yellow  = "#657b83",
    bright_blue    = "#839496",
    bright_magenta = "#6c71c4",
    bright_cyan    = "#93a1a1",
    bright_white   = "#fdf6e3",

    tab_bar_bg       = "#001e26",
    tab_active_bg    = "#002b36",
    tab_inactive_bg  = "#001e26",
    tab_active_fg    = "#839496",
    tab_inactive_fg  = "#586e75",
    tab_active_border = "#268bd2",
    scrollbar_bg     = "#002b36",
    scrollbar_thumb  = "#073642",
    scrollbar_thumb_hover = "#0d4c5a",
    title_bar_bg     = "#001e26",
    title_bar_fg     = "#839496",
    panel_border     = "#073642",
    toolbar_bg       = "#001e26",
    toolbar_fg       = "#839496",
    button_bg        = "#268bd2",
    button_fg        = "#fdf6e3",
    button_hover_bg  = "#3398e0",
    input_bg         = "#073642",
    input_fg         = "#839496",
    input_border     = "#268bd2",
    badge_bg         = "#268bd2",
    badge_fg         = "#fdf6e3",
    link_color       = "#268bd2",
    find_highlight   = "#b58900",
    find_highlight_border = "#d19a00",
)


# ─────────────────────────────────────────────────────────────────────────────
# GitHub Dark
# ─────────────────────────────────────────────────────────────────────────────

GITHUB_DARK = TerminalTheme(
    name        = "GitHub Dark",
    description = "GitHub's official dark theme",

    background  = "#0d1117",
    foreground  = "#c9d1d9",
    cursor_color = "#c9d1d9",
    cursor_text  = "#0d1117",
    selection_bg = "#3b5070",
    selection_fg = "",

    black          = "#484f58",
    red            = "#ff7b72",
    green          = "#3fb950",
    yellow         = "#d29922",
    blue           = "#58a6ff",
    magenta        = "#bc8cff",
    cyan           = "#39c5cf",
    white          = "#b1bac4",
    bright_black   = "#6e7681",
    bright_red     = "#ffa198",
    bright_green   = "#56d364",
    bright_yellow  = "#e3b341",
    bright_blue    = "#79c0ff",
    bright_magenta = "#d2a8ff",
    bright_cyan    = "#56d4dd",
    bright_white   = "#cdd9e5",

    tab_bar_bg       = "#010409",
    tab_active_bg    = "#0d1117",
    tab_inactive_bg  = "#010409",
    tab_active_fg    = "#c9d1d9",
    tab_inactive_fg  = "#6e7681",
    tab_active_border = "#58a6ff",
    scrollbar_bg     = "#0d1117",
    scrollbar_thumb  = "#21262d",
    scrollbar_thumb_hover = "#30363d",
    title_bar_bg     = "#161b22",
    title_bar_fg     = "#c9d1d9",
    panel_border     = "#30363d",
    toolbar_bg       = "#161b22",
    toolbar_fg       = "#c9d1d9",
    button_bg        = "#238636",
    button_fg        = "#ffffff",
    button_hover_bg  = "#2ea043",
    input_bg         = "#0d1117",
    input_fg         = "#c9d1d9",
    input_border     = "#58a6ff",
    badge_bg         = "#1f6feb",
    badge_fg         = "#ffffff",
    link_color       = "#58a6ff",
    find_highlight   = "#d29922",
    find_highlight_border = "#f0883e",
)


# ─────────────────────────────────────────────────────────────────────────────
# Dracula
# ─────────────────────────────────────────────────────────────────────────────

DRACULA = TerminalTheme(
    name        = "Dracula",
    description = "Dracula — a dark theme for many editors",

    background  = "#282a36",
    foreground  = "#f8f8f2",
    cursor_color = "#f8f8f2",
    cursor_text  = "#282a36",
    selection_bg = "#44475a",
    selection_fg = "",

    black          = "#21222c",
    red            = "#ff5555",
    green          = "#50fa7b",
    yellow         = "#f1fa8c",
    blue           = "#bd93f9",
    magenta        = "#ff79c6",
    cyan           = "#8be9fd",
    white          = "#f8f8f2",
    bright_black   = "#6272a4",
    bright_red     = "#ff6e6e",
    bright_green   = "#69ff94",
    bright_yellow  = "#ffffa5",
    bright_blue    = "#d6acff",
    bright_magenta = "#ff92df",
    bright_cyan    = "#a4ffff",
    bright_white   = "#ffffff",

    tab_bar_bg       = "#191a21",
    tab_active_bg    = "#282a36",
    tab_inactive_bg  = "#191a21",
    tab_active_fg    = "#f8f8f2",
    tab_inactive_fg  = "#6272a4",
    tab_active_border = "#ff79c6",
    scrollbar_bg     = "#282a36",
    scrollbar_thumb  = "#44475a",
    scrollbar_thumb_hover = "#6272a4",
    title_bar_bg     = "#191a21",
    title_bar_fg     = "#f8f8f2",
    panel_border     = "#44475a",
    toolbar_bg       = "#191a21",
    toolbar_fg       = "#f8f8f2",
    button_bg        = "#bd93f9",
    button_fg        = "#282a36",
    button_hover_bg  = "#caa9fa",
    input_bg         = "#21222c",
    input_fg         = "#f8f8f2",
    input_border     = "#bd93f9",
    badge_bg         = "#bd93f9",
    badge_fg         = "#282a36",
    link_color       = "#8be9fd",
    find_highlight   = "#f1fa8c",
    find_highlight_border = "#f1fa8c",
)


# ─────────────────────────────────────────────────────────────────────────────
# Theme Registry
# ─────────────────────────────────────────────────────────────────────────────

ALL_THEMES: Dict[str, TerminalTheme] = {
    "dark_plus":      DARK_PLUS,
    "light_plus":     LIGHT_PLUS,
    "monokai":        MONOKAI,
    "one_dark":       ONE_DARK,
    "solarized_dark": SOLARIZED_DARK,
    "github_dark":    GITHUB_DARK,
    "dracula":        DRACULA,
}

DEFAULT_THEME = "dark_plus"


def get_theme(name: str) -> TerminalTheme:
    """Get theme by name, falling back to Dark+."""
    return ALL_THEMES.get(name, DARK_PLUS)
