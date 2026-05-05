"""
ui/settings_dialog.py
======================
VS Code-style settings dialog for the terminal emulator.
Covers font, theme, cursor, scrollback, and keybindings.
"""

from PyQt6.QtCore    import Qt, pyqtSignal
from PyQt6.QtGui     import QFont, QFontDatabase, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QComboBox, QSlider, QSpinBox, QCheckBox,
    QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QDialogButtonBox, QListWidget, QListWidgetItem,
    QScrollArea, QFrame, QSizePolicy
)

from themes.vscode_themes import TerminalTheme, DARK_PLUS, ALL_THEMES, get_theme


class SettingsDialog(QDialog):
    """
    Modal settings dialog.
    Organized into tabs: Appearance, Terminal, Keyboard.
    """

    def __init__(self, theme: TerminalTheme = DARK_PLUS, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._selected_theme = theme

        self.setWindowTitle("Terminal Settings")
        self.setMinimumSize(560, 480)
        self.resize(620, 520)
        self.setModal(True)

        self._build_ui()
        self._apply_theme()

    # ─────────────────────────────────────────────
    # Build UI
    # ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("dialog_header")
        header.setFixedHeight(48)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 20, 0)
        title = QLabel("⚙  Settings")
        title.setObjectName("dialog_title")
        h_lay.addWidget(title)
        layout.addWidget(header)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setObjectName("settings_tabs")
        self._tabs.addTab(self._build_appearance_tab(), "Appearance")
        self._tabs.addTab(self._build_terminal_tab(),   "Terminal")
        self._tabs.addTab(self._build_keyboard_tab(),   "Keyboard")
        self._tabs.addTab(self._build_about_tab(),      "About")
        layout.addWidget(self._tabs, stretch=1)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        btn_box.setObjectName("btn_box")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        btn_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._on_apply
        )
        layout.addWidget(btn_box)

    def _build_appearance_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)

        # Theme
        grp = self._make_group("Color Theme")
        g_lay = QFormLayout(grp)

        self._theme_list = QListWidget()
        self._theme_list.setFixedHeight(140)
        for key, t in ALL_THEMES.items():
            item = QListWidgetItem(t.name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._theme_list.addItem(item)
            if t.name == self.theme.name:
                self._theme_list.setCurrentItem(item)
        self._theme_list.currentItemChanged.connect(self._on_theme_selected)
        g_lay.addRow(self._theme_list)
        lay.addWidget(grp)

        # Font
        grp2  = self._make_group("Font")
        g_lay2 = QFormLayout(grp2)

        self._font_family = QComboBox()
        self._font_family.setObjectName("combo")
        self._font_family.setFixedWidth(220)
        for family in sorted(QFontDatabase.families()):
            self._font_family.addItem(family)
        g_lay2.addRow("Font Family:", self._font_family)

        self._font_size = QSpinBox()
        self._font_size.setRange(6, 72)
        self._font_size.setValue(13)
        self._font_size.setSuffix(" pt")
        g_lay2.addRow("Font Size:", self._font_size)

        self._font_ligatures = QCheckBox("Enable font ligatures")
        self._font_ligatures.setChecked(True)
        g_lay2.addRow(self._font_ligatures)
        lay.addWidget(grp2)

        # Cursor
        grp3  = self._make_group("Cursor")
        g_lay3 = QFormLayout(grp3)

        self._cursor_style = QComboBox()
        self._cursor_style.setObjectName("combo")
        self._cursor_style.addItems(["Block", "Underline", "Bar (I-beam)"])
        g_lay3.addRow("Cursor Style:", self._cursor_style)

        self._cursor_blink = QCheckBox("Cursor blinking")
        self._cursor_blink.setChecked(True)
        g_lay3.addRow(self._cursor_blink)
        lay.addWidget(grp3)

        lay.addStretch()
        return w

    def _build_terminal_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)

        grp = self._make_group("Shell")
        g_lay = QFormLayout(grp)

        self._default_shell = QLineEdit("/bin/bash")
        self._default_shell.setObjectName("line_edit")
        g_lay.addRow("Default Shell:", self._default_shell)

        self._shell_args = QLineEdit("")
        self._shell_args.setObjectName("line_edit")
        self._shell_args.setPlaceholderText("e.g. --login")
        g_lay.addRow("Shell Arguments:", self._shell_args)
        lay.addWidget(grp)

        grp2  = self._make_group("Behavior")
        g_lay2 = QFormLayout(grp2)

        self._scrollback = QSpinBox()
        self._scrollback.setRange(100, 100000)
        self._scrollback.setValue(10000)
        self._scrollback.setSingleStep(1000)
        g_lay2.addRow("Scrollback Lines:", self._scrollback)

        self._bell = QCheckBox("Audible bell")
        self._bell.setChecked(False)
        g_lay2.addRow(self._bell)

        self._inherit_env = QCheckBox("Inherit environment variables")
        self._inherit_env.setChecked(True)
        g_lay2.addRow(self._inherit_env)

        self._right_click_paste = QCheckBox("Right-click to paste")
        self._right_click_paste.setChecked(False)
        g_lay2.addRow(self._right_click_paste)

        self._focus_follows_mouse = QCheckBox("Focus terminal on mouse hover")
        self._focus_follows_mouse.setChecked(False)
        g_lay2.addRow(self._focus_follows_mouse)
        lay.addWidget(grp2)

        grp3  = self._make_group("Rendering")
        g_lay3 = QFormLayout(grp3)

        self._gpu_accel = QCheckBox("Hardware acceleration (requires restart)")
        self._gpu_accel.setChecked(True)
        g_lay3.addRow(self._gpu_accel)

        self._smooth_scroll = QCheckBox("Smooth scrolling")
        self._smooth_scroll.setChecked(True)
        g_lay3.addRow(self._smooth_scroll)
        lay.addWidget(grp3)

        lay.addStretch()
        return w

    def _build_keyboard_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)

        bindings = [
            ("New Terminal",        "Ctrl+Shift+`"),
            ("Close Terminal",      "Ctrl+Shift+W"),
            ("Split Terminal",      "Ctrl+Shift+5"),
            ("Next Tab",            "Ctrl+Tab"),
            ("Previous Tab",        "Ctrl+Shift+Tab"),
            ("Copy",                "Ctrl+Shift+C"),
            ("Paste",               "Ctrl+Shift+V"),
            ("Find",                "Ctrl+Shift+F"),
            ("Clear",               "Ctrl+K"),
            ("Increase Font Size",  "Ctrl+Shift+="),
            ("Decrease Font Size",  "Ctrl+Shift+-"),
            ("Reset Font Size",     "Ctrl+Shift+0"),
            ("Scroll Up",           "Shift+PageUp"),
            ("Scroll Down",         "Shift+PageDown"),
            ("Toggle Terminal",     "Ctrl+`"),
        ]

        lbl = QLabel("Keyboard Shortcuts")
        lbl.setObjectName("group_title")
        lay.addWidget(lbl)

        table = QListWidget()
        table.setObjectName("key_table")
        table.setAlternatingRowColors(True)
        for action, shortcut in bindings:
            item = QListWidgetItem(f"  {action:<35} {shortcut}")
            item.setFont(QFont("Consolas, 'Courier New', monospace", 12))
            table.addItem(item)
        lay.addWidget(table)

        note = QLabel("* Shortcuts follow VS Code conventions and cannot be customized in this version.")
        note.setObjectName("note_label")
        note.setWordWrap(True)
        lay.addWidget(note)

        return w

    def _build_about_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("VSCode Terminal Emulator")
        title.setObjectName("about_title")
        lay.addWidget(title)

        info = QLabel(
            "Version 1.0.0\n\n"
            "A professional terminal emulator built with Python and PyQt6.\n"
            "Implements VS Code terminal specifications including:\n\n"
            "  • Full PTY (pseudo-terminal) support\n"
            "  • ANSI / VT100 / VT220 / xterm escape sequences\n"
            "  • 256-color and True Color (24-bit) support\n"
            "  • Multiple terminal sessions with tab management\n"
            "  • VS Code-matching color themes\n"
            "  • Find/search overlay\n"
            "  • Mouse selection and clipboard integration\n"
            "  • Bracketed paste mode\n"
            "  • Scrollback buffer (up to 50,000 lines)\n"
            "  • Font zoom (Ctrl+Scroll)\n\n"
            "Built with:\n"
            "  PyQt6 · Python 3.8+"
        )
        info.setObjectName("about_text")
        info.setWordWrap(True)
        lay.addWidget(info)

        lay.addStretch()
        return w

    def _make_group(self, title: str) -> QGroupBox:
        grp = QGroupBox(title)
        grp.setObjectName("settings_group")
        return grp

    # ─────────────────────────────────────────────
    # Theme
    # ─────────────────────────────────────────────

    def _apply_theme(self):
        t = self.theme
        self.setStyleSheet(f"""
            QDialog {{
                background: {t.tab_bar_bg};
                color: {t.foreground};
            }}
            QWidget#dialog_header {{
                background: {t.title_bar_bg};
                border-bottom: 1px solid {t.panel_border};
            }}
            QLabel#dialog_title {{
                color: {t.foreground};
                font-size: 15px;
                font-weight: 600;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            QTabWidget#settings_tabs::pane {{
                border: none;
                background: {t.tab_bar_bg};
            }}
            QTabWidget#settings_tabs QTabBar::tab {{
                background: {t.tab_inactive_bg};
                color: {t.tab_inactive_fg};
                border: none;
                padding: 8px 20px;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
            }}
            QTabWidget#settings_tabs QTabBar::tab:selected {{
                background: {t.tab_active_bg};
                color: {t.tab_active_fg};
                border-bottom: 2px solid {t.tab_active_border};
            }}
            QGroupBox#settings_group {{
                color: {t.foreground};
                border: 1px solid {t.panel_border};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 12px;
                font-weight: 600;
            }}
            QGroupBox#settings_group::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                color: {t.tab_inactive_fg};
            }}
            QLabel {{
                color: {t.foreground};
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 12px;
            }}
            QLabel#note_label, QLabel#group_title {{
                color: {t.tab_inactive_fg};
                font-size: 11px;
            }}
            QLabel#about_title {{
                color: {t.foreground};
                font-size: 18px;
                font-weight: 700;
                margin-bottom: 8px;
            }}
            QLabel#about_text {{
                color: {t.foreground};
                font-size: 12px;
                line-height: 1.6;
            }}
            QListWidget {{
                background: {t.input_bg};
                color: {t.foreground};
                border: 1px solid {t.panel_border};
                border-radius: 3px;
                font-size: 12px;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            QListWidget::item:selected {{
                background: {t.input_border};
                color: white;
            }}
            QListWidget::item:hover:!selected {{
                background: {t.scrollbar_thumb};
            }}
            QComboBox#combo, QLineEdit#line_edit {{
                background: {t.input_bg};
                color: {t.foreground};
                border: 1px solid {t.panel_border};
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 12px;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            QComboBox#combo:focus, QLineEdit#line_edit:focus {{
                border-color: {t.input_border};
            }}
            QSpinBox {{
                background: {t.input_bg};
                color: {t.foreground};
                border: 1px solid {t.panel_border};
                border-radius: 3px;
                padding: 3px 6px;
            }}
            QCheckBox {{
                color: {t.foreground};
                font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {t.panel_border};
                border-radius: 2px;
                background: {t.input_bg};
            }}
            QCheckBox::indicator:checked {{
                background: {t.input_border};
                border-color: {t.input_border};
            }}
            QDialogButtonBox#btn_box {{
                padding: 8px 16px;
                border-top: 1px solid {t.panel_border};
                background: {t.tab_bar_bg};
            }}
            QPushButton {{
                background: {t.button_bg};
                color: {t.button_fg};
                border: none;
                border-radius: 3px;
                padding: 6px 16px;
                font-size: 12px;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            QPushButton:hover {{ background: {t.button_hover_bg}; }}
            QPushButton[text="Cancel"] {{
                background: transparent;
                color: {t.foreground};
                border: 1px solid {t.panel_border};
            }}
            QPushButton[text="Cancel"]:hover {{ background: {t.scrollbar_thumb}; }}
        """)

    # ─────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────

    def _on_theme_selected(self, current, previous):
        if current:
            key = current.data(Qt.ItemDataRole.UserRole)
            self._selected_theme = get_theme(key)

    def _on_apply(self):
        pass  # Could apply live preview

    def selected_theme(self) -> TerminalTheme:
        return self._selected_theme
