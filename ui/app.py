"""
ui/app.py
==========
Main application window — pixel-perfect VS Code window chrome.

Features:
  - Custom frameless window with title bar
  - Traffic-light buttons (close, minimize, maximize) on Linux/Mac
  - VS Code activity bar (left sidebar icons) — decorative
  - Status bar at bottom
  - Resizable with drop-shadow
  - System tray integration
  - Session persistence (re-opens last CWD)
  - Full keyboard shortcut handling
"""

import sys
import os
import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore    import Qt, QSize, QPoint, QRect, QSettings, QTimer, pyqtSlot
from PyQt6.QtGui     import (QColor, QFont, QPainter, QBrush, QPen,
                              QIcon, QPixmap, QPalette, QKeySequence,
                              QAction, QShortcut, QGuiApplication)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QFrame, QSystemTrayIcon,
    QMenu, QToolBar, QStatusBar, QMenuBar
)

from ui.terminal_panel   import TerminalPanel
from themes.vscode_themes import TerminalTheme, DARK_PLUS, get_theme
from themes.phantom_theme import PHANTOM_DARK


# ─────────────────────────────────────────────────────────────────────────────
# Custom title bar (VS Code style)
# ─────────────────────────────────────────────────────────────────────────────

class TitleBar(QWidget):
    """Frameless window title bar with traffic-light buttons."""

    def __init__(self, window: "MainWindow", theme: TerminalTheme):
        super().__init__(window)
        self._window  = window
        self.theme    = theme
        self._drag_pos: QPoint = None

        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(0)

        # ── Phantom logo + title ──────────────────
        logo = QLabel("◈")
        logo.setObjectName("logo_label")
        logo.setFixedWidth(26)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)

        lay.addSpacing(8)

        self._title_label = QLabel("Phantom Terminal")
        self._title_label.setObjectName("title_label")
        self._title_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self._title_label)

        lay.addStretch()

        # ── Window controls (right, minimal) ─────
        self._minimize_btn = self._make_ctrl_btn("─", self._on_minimize, "minimize")
        self._maximize_btn = self._make_ctrl_btn("□", self._on_maximize, "maximize")
        self._close_btn    = self._make_ctrl_btn("✕", self._on_close,    "close")

        for btn in [self._minimize_btn, self._maximize_btn, self._close_btn]:
            lay.addWidget(btn)
            lay.addSpacing(2)

    def _make_ctrl_btn(self, symbol: str, callback, name: str) -> QPushButton:
        btn = QPushButton(symbol)
        btn.setFixedSize(32, 22)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setObjectName(f"ctrl_{name}")
        btn.clicked.connect(callback)
        return btn

    def _apply_theme(self):
        t = self.theme
        self.setStyleSheet(f"""
            TitleBar {{
                background: {t.title_bar_bg};
                border-bottom: 1px solid {t.panel_border};
            }}
            QLabel#logo_label {{
                color: #7c6af7;
                font-size: 16px;
                font-weight: bold;
            }}
            QLabel#title_label {{
                color: {t.title_bar_fg};
                font-family: 'Segoe UI', 'SF Pro Text', system-ui, sans-serif;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.5px;
            }}
            QPushButton#ctrl_minimize,
            QPushButton#ctrl_maximize {{
                background: transparent;
                color: #555568;
                border: none;
                font-size: 12px;
                border-radius: 0;
            }}
            QPushButton#ctrl_minimize:hover,
            QPushButton#ctrl_maximize:hover {{
                background: rgba(255,255,255,0.08);
                color: #c8c8d4;
            }}
            QPushButton#ctrl_close {{
                background: transparent;
                color: #555568;
                border: none;
                font-size: 11px;
                border-radius: 0;
            }}
            QPushButton#ctrl_close:hover {{
                background: #c0392b;
                color: #ffffff;
            }}
        """)

    def set_title(self, title: str):
        self._title_label.setText(f"Phantom Terminal — {title}")

    def set_theme(self, theme: TerminalTheme):
        self.theme = theme
        self._apply_theme()

    # ── Window drag ───────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - \
                             self._window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos:
            self._window.move(
                event.globalPosition().toPoint() - self._drag_pos
            )

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_maximize()

    # ── Button actions ────────────────────────────

    def _on_close(self):
        self._window.close()

    def _on_minimize(self):
        self._window.showMinimized()

    def _on_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()



# ─────────────────────────────────────────────────────────────────────────────
# Activity Bar (left sidebar icons — VS Code style)
# ─────────────────────────────────────────────────────────────────────────────

class ActivityBar(QWidget):
    """Left sidebar with VS Code-style activity bar icons."""

    def __init__(self, theme: TerminalTheme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedWidth(48)
        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Only the phantom logo icon at top
        logo = self._make_icon("◈", "Phantom Terminal", True)
        lay.addWidget(logo)

        lay.addStretch()

        # Settings at bottom
        sett = self._make_icon("⚙", "Settings")
        lay.addWidget(sett)

    def _make_icon(self, icon: str, tooltip: str, active: bool = False) -> QLabel:
        lbl = QLabel(icon)
        lbl.setFixedSize(48, 48)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setToolTip(tooltip)
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        lbl.setObjectName("active_icon" if active else "inactive_icon")
        return lbl

    def _apply_theme(self):
        t = self.theme
        self.setStyleSheet(f"""
            ActivityBar {{
                background: {t.title_bar_bg};
                border-right: 1px solid {t.panel_border};
            }}
            QLabel#active_icon {{
                color: #7c6af7;
                font-size: 17px;
                border-left: 2px solid #7c6af7;
            }}
            QLabel#inactive_icon {{
                color: #2a2a3e;
                font-size: 17px;
                border-left: 2px solid transparent;
            }}
            QLabel#inactive_icon:hover {{
                color: #6666808;
            }}
        """)

    def set_theme(self, theme: TerminalTheme):
        self.theme = theme
        self._apply_theme()


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QWidget):
    """
    The application main window.
    Frameless, custom-painted, full VS Code layout.
    """

    def __init__(self, theme: TerminalTheme = DARK_PLUS):
        super().__init__()
        self.theme = theme

        # State
        self._resize_edge  = None
        self._resize_start = None
        self._resize_rect  = None
        self._is_maximized = False

        self._setup_window()
        self._build_ui()
        self._setup_shortcuts()
        self._restore_geometry()

    def _setup_window(self):
        """Configure base window properties."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumSize(800, 500)
        self.resize(1280, 800)
        self.setWindowTitle("Phantom Terminal")
        self.setMouseTracking(True)

    def _build_ui(self):
        """Build the complete VS Code-style layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Title bar ─────────────────────────────
        self._title_bar = TitleBar(self, self.theme)
        main_layout.addWidget(self._title_bar)

        # ── Body (activity bar + terminal) ─────────
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Activity bar (left)
        self._activity_bar = ActivityBar(self.theme)
        body_layout.addWidget(self._activity_bar)

        # Terminal panel (center)
        self._terminal_panel = TerminalPanel(self.theme)
        self._terminal_panel.title_changed.connect(self._on_title_changed)
        body_layout.addWidget(self._terminal_panel, stretch=1)

        main_layout.addWidget(body, stretch=1)

        # ── Bottom status bar ─────────────────────
        self._bottom_bar = self._build_bottom_status_bar()
        main_layout.addWidget(self._bottom_bar)

    def _build_bottom_status_bar(self) -> QWidget:
        """VS Code-style status bar at the very bottom."""
        bar = QWidget()
        bar.setFixedHeight(22)
        bar.setObjectName("vscode_status_bar")

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(0)

        # Left items
        self._sb_branch = self._make_sb_item("⎇  main", clickable=True)
        self._sb_errors = self._make_sb_item("✕ 0  ⚠ 0", clickable=True)
        lay.addWidget(self._sb_branch)
        lay.addWidget(self._sb_errors)
        lay.addStretch()

        # Right items
        self._sb_cursor  = self._make_sb_item("Ln 1, Col 1")
        self._sb_spaces  = self._make_sb_item("Spaces: 4")
        self._sb_enc     = self._make_sb_item("UTF-8")
        self._sb_eol     = self._make_sb_item("LF")
        self._sb_lang    = self._make_sb_item("Shell")
        self._sb_notifs  = self._make_sb_item("🔔")

        for w in [self._sb_cursor, self._sb_spaces, self._sb_enc,
                  self._sb_eol, self._sb_lang, self._sb_notifs]:
            lay.addWidget(w)

        self._apply_bottom_bar_theme(bar)
        return bar

    def _make_sb_item(self, text: str, clickable: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sb_item")
        lbl.setContentsMargins(6, 0, 6, 0)
        if clickable:
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        return lbl

    def _apply_bottom_bar_theme(self, bar=None):
        target = bar if bar is not None else self._bottom_bar
        target.setStyleSheet("""
            QWidget#vscode_status_bar {
                background: #0d0b1a;
                border-top: 1px solid #1a1830;
            }
            QLabel#sb_item {
                color: #3a3a52;
                font-family: 'Segoe UI', 'SF Pro Text', system-ui, sans-serif;
                font-size: 11px;
            }
            QLabel#sb_item:hover {
                background: rgba(124,106,247,0.12);
                color: #8888a0;
            }
        """)

    # ─────────────────────────────────────────────
    # Shortcuts
    # ─────────────────────────────────────────────

    def _setup_shortcuts(self):
        shortcuts = [
            (QKeySequence("Ctrl+Shift+`"),   self._terminal_panel.new_terminal),
            (QKeySequence("Ctrl+`"),         self._toggle_terminal_focus),
            (QKeySequence("Ctrl+Shift+F"),   self._terminal_panel.show_find),
            (QKeySequence("Ctrl+K"),         self._terminal_panel.clear_active),
            (QKeySequence("Ctrl+Shift+="),   self._font_zoom_in),
            (QKeySequence("Ctrl+Shift+-"),   self._font_zoom_out),
            (QKeySequence("Ctrl+Shift+0"),   self._font_zoom_reset),
            (QKeySequence("F11"),            self._toggle_fullscreen),
        ]
        for seq, callback in shortcuts:
            sc = QShortcut(seq, self)
            sc.activated.connect(callback)

    def _toggle_terminal_focus(self):
        session = self._terminal_panel._active_session()
        if session:
            session.widget.setFocus()

    def _font_zoom_in(self):
        s = self._terminal_panel._active_session()
        if s: s.widget.increase_font_size()

    def _font_zoom_out(self):
        s = self._terminal_panel._active_session()
        if s: s.widget.decrease_font_size()

    def _font_zoom_reset(self):
        s = self._terminal_panel._active_session()
        if s: s.widget.reset_font_size()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ─────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────

    def _on_title_changed(self, title: str):
        self._title_bar.set_title(title)

    # ─────────────────────────────────────────────
    # Geometry persistence
    # ─────────────────────────────────────────────

    def _restore_geometry(self):
        try:
            settings = QSettings("PhantomTerminal", "MainWindow")
            geom     = settings.value("geometry")
            if geom:
                self.restoreGeometry(geom)
        except Exception:
            pass

    def _save_geometry(self):
        try:
            settings = QSettings("PhantomTerminal", "MainWindow")
            settings.setValue("geometry", self.saveGeometry())
        except Exception:
            pass

    def closeEvent(self, event):
        self._save_geometry()
        # Stop all sessions
        for session in list(self._terminal_panel._sessions.values()):
            session.stop()
        event.accept()

    # ─────────────────────────────────────────────
    # Frameless window resize
    # ─────────────────────────────────────────────

    RESIZE_MARGIN = 6

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._get_resize_edge(event.position().toPoint())
            if edge:
                self._resize_edge  = edge
                self._resize_start = event.globalPosition().toPoint()
                self._resize_rect  = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_edge and self._resize_start:
            delta = event.globalPosition().toPoint() - self._resize_start
            self._apply_resize(delta)
            event.accept()
            return

        # Update cursor
        edge = self._get_resize_edge(event.position().toPoint())
        cursor = self._edge_to_cursor(edge)
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_edge  = None
        self._resize_start = None
        self._resize_rect  = None
        super().mouseReleaseEvent(event)

    def _get_resize_edge(self, pos: QPoint) -> Optional[str]:
        m  = self.RESIZE_MARGIN
        w  = self.width()
        h  = self.height()
        x, y = pos.x(), pos.y()

        if x <= m and y <= m:       return "nw"
        if x >= w - m and y <= m:   return "ne"
        if x <= m and y >= h - m:   return "sw"
        if x >= w - m and y >= h - m: return "se"
        if x <= m:                  return "w"
        if x >= w - m:              return "e"
        if y <= m:                  return "n"
        if y >= h - m:              return "s"
        return None

    def _edge_to_cursor(self, edge):
        if not edge:
            return Qt.CursorShape.ArrowCursor
        cursors = {
            "n":  Qt.CursorShape.SizeVerCursor,
            "s":  Qt.CursorShape.SizeVerCursor,
            "e":  Qt.CursorShape.SizeHorCursor,
            "w":  Qt.CursorShape.SizeHorCursor,
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
        }
        return cursors.get(edge, Qt.CursorShape.ArrowCursor)

    def _apply_resize(self, delta: QPoint):
        if not self._resize_rect or not self._resize_edge:
            return
        r   = QRect(self._resize_rect)
        dx  = delta.x()
        dy  = delta.y()
        edge = self._resize_edge

        if "e" in edge: r.setRight(r.right()   + dx)
        if "s" in edge: r.setBottom(r.bottom() + dy)
        if "w" in edge: r.setLeft(r.left()     + dx)
        if "n" in edge: r.setTop(r.top()       + dy)

        if r.width()  < self.minimumWidth():  r.setWidth(self.minimumWidth())
        if r.height() < self.minimumHeight(): r.setHeight(self.minimumHeight())

        self.setGeometry(r)

    def paintEvent(self, event):
        """Draw phantom border."""
        p = QPainter(self)
        p.setPen(QPen(QColor("#16161f"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Application entry point
# ─────────────────────────────────────────────────────────────────────────────

from typing import Optional


class TerminalApp:
    """Application bootstrap."""

    def __init__(self):
        self.app    = None
        self.window = None

    def run(self):
        """Start the application."""
        self.app = QApplication.instance() or QApplication(sys.argv)

        # High-DPI support (AA_UseHighDpiPixmaps removed in PyQt6 — handled automatically)

        # Apply global font
        app_font = QFont("Segoe UI", 11)
        self.app.setFont(app_font)

        # Load saved theme
        settings = QSettings("PhantomTerminal", "App")
        theme_key = settings.value("theme", "dark_plus")
        theme     = PHANTOM_DARK  # Always start with Phantom Dark

        # Create main window
        self.window = MainWindow(theme)
        self.window.show()

        # Connect theme save on exit
        def on_exit():
            settings.setValue("theme", "dark_plus")  # TODO: track current theme

        self.app.aboutToQuit.connect(on_exit)

        sys.exit(self.app.exec())
