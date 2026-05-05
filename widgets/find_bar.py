"""
widgets/find_bar.py
===================
VS Code-style find bar for the terminal.
Slides in from the top-right with:
  - Search input
  - Match counter (e.g., "3 of 12")
  - Previous / Next buttons
  - Case sensitive toggle
  - Regex toggle
  - Close button
  - Smooth show/hide animation
"""

from PyQt6.QtCore    import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QRect
from PyQt6.QtGui     import QPainter, QColor, QFont, QIcon, QPen, QKeyEvent
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLineEdit, QPushButton,
                              QLabel, QFrame, QSizePolicy, QCheckBox)
from themes.vscode_themes import TerminalTheme, DARK_PLUS


class FindBar(QWidget):
    """
    Floating find toolbar that appears inside the terminal panel.
    Positioned at the top-right, overlaying the terminal content.
    """

    search_requested = pyqtSignal(str, bool, bool)  # query, case_sensitive, regex
    navigate_next    = pyqtSignal()
    navigate_prev    = pyqtSignal()
    closed           = pyqtSignal()

    def __init__(self, theme: TerminalTheme = DARK_PLUS, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._match_count   = 0
        self._current_match = 0

        self._build_ui()
        self._apply_theme()
        self.hide()

    def _build_ui(self):
        """Build the find bar UI."""
        self.setFixedHeight(40)
        self.setFixedWidth(380)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Search input
        self._input = QLineEdit()
        self._input.setPlaceholderText("Find in terminal")
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._next)
        layout.addWidget(self._input, stretch=1)

        # Match label
        self._match_label = QLabel("No results")
        self._match_label.setFixedWidth(70)
        self._match_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._match_label)

        # Case sensitive toggle
        self._case_btn = self._make_icon_btn("Aa", "Case sensitive", checkable=True)
        self._case_btn.clicked.connect(self._on_settings_changed)
        layout.addWidget(self._case_btn)

        # Regex toggle
        self._regex_btn = self._make_icon_btn(".*", "Use regular expression", checkable=True)
        self._regex_btn.clicked.connect(self._on_settings_changed)
        layout.addWidget(self._regex_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        layout.addWidget(sep)

        # Previous
        self._prev_btn = self._make_icon_btn("↑", "Previous match (Shift+F3)")
        self._prev_btn.clicked.connect(self._prev)
        layout.addWidget(self._prev_btn)

        # Next
        self._next_btn = self._make_icon_btn("↓", "Next match (F3)")
        self._next_btn.clicked.connect(self._next)
        layout.addWidget(self._next_btn)

        # Close
        self._close_btn = self._make_icon_btn("✕", "Close (Escape)")
        self._close_btn.clicked.connect(self.close_bar)
        layout.addWidget(self._close_btn)

    def _make_icon_btn(self, text: str, tooltip: str, checkable: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(24, 24)
        btn.setCheckable(checkable)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _apply_theme(self):
        t = self.theme
        self.setStyleSheet(f"""
            FindBar {{
                background-color: {t.tab_bar_bg};
                border: 1px solid {t.panel_border};
                border-radius: 4px;
            }}
            QLineEdit {{
                background: {t.input_bg};
                color: {t.input_fg};
                border: 1px solid {t.panel_border};
                border-radius: 3px;
                padding: 2px 6px;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {t.input_border};
            }}
            QLabel {{
                color: {t.tab_inactive_fg};
                font-size: 11px;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            QPushButton {{
                background: transparent;
                color: {t.tab_inactive_fg};
                border: 1px solid transparent;
                border-radius: 3px;
                font-size: 12px;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            QPushButton:hover {{
                background: {t.scrollbar_thumb};
                color: {t.foreground};
                border-color: {t.panel_border};
            }}
            QPushButton:checked {{
                background: {t.input_border};
                color: white;
                border-color: {t.input_border};
            }}
            QPushButton:pressed {{
                background: {t.button_bg};
            }}
            QFrame[frameShape="5"] {{
                color: {t.panel_border};
            }}
        """)

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def show_bar(self):
        """Show and focus the find bar."""
        self.show()
        self._input.setFocus()
        self._input.selectAll()
        self._reposition()

    def close_bar(self):
        """Close the find bar and clear highlights."""
        self.hide()
        self.closed.emit()

    def set_match_info(self, current: int, total: int):
        """Update the match counter display."""
        self._match_count   = total
        self._current_match = current

        if total == 0:
            self._match_label.setText("No results")
            self._match_label.setStyleSheet(f"color: #f14c4c; font-size: 11px;")
        else:
            self._match_label.setText(f"{current + 1} of {total}")
            self._match_label.setStyleSheet(
                f"color: {self.theme.tab_inactive_fg}; font-size: 11px;"
            )

        self._prev_btn.setEnabled(total > 0)
        self._next_btn.setEnabled(total > 0)

    def set_theme(self, theme: TerminalTheme):
        self.theme = theme
        self._apply_theme()

    # ─────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────

    def _on_text_changed(self, text: str):
        self.search_requested.emit(
            text,
            self._case_btn.isChecked(),
            self._regex_btn.isChecked()
        )

    def _on_settings_changed(self):
        self._on_text_changed(self._input.text())

    def _next(self):
        self.navigate_next.emit()

    def _prev(self):
        self.navigate_prev.emit()

    # ─────────────────────────────────────────────
    # Keyboard
    # ─────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
        elif event.key() == Qt.Key.Key_F3:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._prev()
            else:
                self._next()
        else:
            super().keyPressEvent(event)

    # ─────────────────────────────────────────────
    # Positioning
    # ─────────────────────────────────────────────

    def _reposition(self):
        """Position at top-right of parent."""
        if self.parent():
            parent_w = self.parent().width()
            self.move(parent_w - self.width() - 16, 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition()
