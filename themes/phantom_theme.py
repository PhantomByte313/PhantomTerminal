"""
themes/phantom_theme.py
========================
Phantom Terminal — ultra-dark custom theme.
"""
from themes.vscode_themes import TerminalTheme

PHANTOM_DARK = TerminalTheme(
    name        = "Phantom Dark",
    description = "Phantom Terminal — deep black dark theme",

    background  = "#0a0a0f",
    foreground  = "#c8c8d4",
    cursor_color = "#7c6af7",
    cursor_text  = "#0a0a0f",
    selection_bg = "#2a2450",
    selection_fg = "",

    black          = "#1a1a24",
    red            = "#e05577",
    green          = "#3dd68c",
    yellow         = "#e8c46a",
    blue           = "#5b8af5",
    magenta        = "#a97af8",
    cyan           = "#3ecfcf",
    white          = "#c8c8d4",
    bright_black   = "#3a3a4e",
    bright_red     = "#ff6b8a",
    bright_green   = "#50e8a0",
    bright_yellow  = "#ffd47a",
    bright_blue    = "#7aa8ff",
    bright_magenta = "#c49dff",
    bright_cyan    = "#56e6e6",
    bright_white   = "#e8e8f0",

    tab_bar_bg       = "#08080d",
    tab_active_bg    = "#0a0a0f",
    tab_inactive_bg  = "#0d0d14",
    tab_active_fg    = "#e8e8f0",
    tab_inactive_fg  = "#4a4a60",
    tab_active_border = "#7c6af7",
    scrollbar_bg     = "#0a0a0f",
    scrollbar_thumb  = "#1e1e2e",
    scrollbar_thumb_hover = "#2e2e44",
    title_bar_bg     = "#060609",
    title_bar_fg     = "#8888a0",
    panel_border     = "#16161f",
    toolbar_bg       = "#08080d",
    toolbar_fg       = "#666680",
    button_bg        = "#2a2450",
    button_fg        = "#c8c8d4",
    button_hover_bg  = "#3a3466",
    input_bg         = "#0d0d14",
    input_fg         = "#c8c8d4",
    input_border     = "#7c6af7",
    badge_bg         = "#2a2450",
    badge_fg         = "#c8c8d4",
    link_color       = "#7c6af7",
    find_highlight   = "#3a2e00",
    find_highlight_border = "#e8c46a",
)
