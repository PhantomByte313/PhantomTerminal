"""
ui/terminal_panel.py
=====================
The main terminal panel — combines:
  - TabBar       (multiple sessions)
  - TerminalWidget (rendering + input)
  - FindBar      (search overlay)
  - Toolbar      (shell selector, split, clear, etc.)
  - Status bar   (cursor position, encoding, shell info)

Manages the lifecycle of PTY sessions per tab.
"""

import os
from typing import Dict, Optional

from PyQt6.QtCore    import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui     import QColor, QFont, QKeyEvent, QPainter, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QComboBox, QSizePolicy, QFrame,
    QSplitter, QToolButton, QMenu, QCheckBox
)

from core.pty_handler      import PTYHandler
from widgets.terminal_widget import TerminalWidget
from widgets.tab_bar         import TabBar
from widgets.find_bar        import FindBar
from themes.vscode_themes    import TerminalTheme, DARK_PLUS, get_theme, ALL_THEMES


class TerminalSession:
    """Encapsulates a single terminal tab (PTY + widget)."""

    def __init__(self, tab_id: int, theme: TerminalTheme):
        self.tab_id  = tab_id
        self.widget  = TerminalWidget(theme)
        self.pty     = PTYHandler()
        self.title   = "bash"
        self.exit_code: Optional[int] = None

    def start(self, shell: str = None, cwd: str = None) -> bool:
        """Start the PTY session."""
        self.widget.attach_pty(self.pty)
        cols, rows = self.widget._calc_grid_size()

        ok = self.pty.start(cols=max(80, cols), rows=max(24, rows),
                            shell=shell, cwd=cwd)
        return ok

    def stop(self):
        """Stop the PTY session."""
        self.widget.detach_pty()
        self.pty.stop()


class TerminalPanel(QWidget):
    """
    Full terminal panel with tab management.
    
    This is the main embeddable widget — place it in your window layout.
    """

    title_changed  = pyqtSignal(str)
    session_exited = pyqtSignal(int, int)   # (tab_id, exit_code)

    def __init__(self, theme: TerminalTheme = DARK_PLUS, parent=None):
        super().__init__(parent)
        self.theme = theme

        self._sessions:     Dict[int, TerminalSession] = {}
        self._active_tab_id: Optional[int] = None

        self._build_ui()
        self._apply_theme()

        # Auto-create first terminal
        QTimer.singleShot(100, self.new_terminal)

    # ─────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ───────────────────────────────
        self._toolbar = self._build_toolbar()
        layout.addWidget(self._toolbar)

        # ── Tab bar ───────────────────────────────
        self._tab_bar = TabBar(self.theme)
        self._tab_bar.tab_selected.connect(self._on_tab_selected)
        self._tab_bar.tab_close_requested.connect(self._on_tab_close)
        self._tab_bar.tab_add_requested.connect(self.new_terminal)
        layout.addWidget(self._tab_bar)

        # ── Terminal stack ────────────────────────
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Expanding)
        layout.addWidget(self._stack, stretch=1)

        # ── Status bar ────────────────────────────
        self._status_bar = self._build_status_bar()
        layout.addWidget(self._status_bar)

        # ── Find bar (floating overlay) ───────────
        self._find_bar = FindBar(self.theme, parent=self._stack)
        self._find_bar.search_requested.connect(self._on_find)
        self._find_bar.navigate_next.connect(self._find_next)
        self._find_bar.navigate_prev.connect(self._find_prev)
        self._find_bar.closed.connect(self._on_find_closed)

    def _build_toolbar(self) -> QWidget:
        """Build the top toolbar — minimal, functional only."""
        toolbar = QWidget()
        toolbar.setFixedHeight(34)
        toolbar.setObjectName("toolbar")

        lay = QHBoxLayout(toolbar)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(4)

        # ── Label ─────────────────────────────────
        shell_label = QLabel("TERMINAL")
        shell_label.setObjectName("panel_title")
        lay.addWidget(shell_label)

        lay.addStretch()

        # ── Shell selector ────────────────────────
        self._shell_combo = QComboBox()
        self._shell_combo.setFixedWidth(90)
        self._shell_combo.setObjectName("shell_combo")
        self._populate_shells()
        lay.addWidget(self._shell_combo)

        lay.addSpacing(6)
        lay.addWidget(self._make_separator())
        lay.addSpacing(6)

        # ── Functional buttons only ───────────────
        for icon, tip, callback in [
            ("＋",  "New Terminal   Ctrl+Shift+`",  self.new_terminal),
            ("⌫",   "Clear          Ctrl+K",        self.clear_active),
            ("⌕",   "Find           Ctrl+Shift+F",  self.show_find),
            ("⚙",   "Settings",                     self._show_settings),
        ]:
            lay.addWidget(self._make_toolbar_btn(icon, tip, callback))

        return toolbar

    def _build_status_bar(self) -> QWidget:
        """Build the bottom status bar."""
        bar = QWidget()
        bar.setFixedHeight(22)
        bar.setObjectName("status_bar")

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(12)

        self._status_shell   = QLabel("bash")
        self._status_pid     = QLabel("PID: —")
        self._status_cursor  = QLabel("Ln 1, Col 1")
        self._status_size    = QLabel("220×50")
        self._status_enc     = QLabel("UTF-8")

        for lbl in [self._status_shell, self._status_pid,
                    self._status_cursor, self._status_size,
                    self._status_enc]:
            lbl.setObjectName("status_label")
            lay.addWidget(lbl)

        lay.addStretch()

        self._status_scroll = QLabel("")
        self._status_scroll.setObjectName("status_label")
        lay.addWidget(self._status_scroll)

        return bar

    def _make_toolbar_btn(self, icon: str, tooltip: str, callback) -> QToolButton:
        btn = QToolButton()
        btn.setText(icon)
        btn.setToolTip(tooltip)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(callback)
        btn.setObjectName("toolbar_btn")
        return btn

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        sep.setObjectName("separator")
        return sep

    def _populate_shells(self):
        """Find available shells and populate the combo."""
        shells = []
        for shell in ["/bin/bash", "/bin/zsh", "/bin/fish",
                      "/usr/bin/bash", "/usr/bin/zsh"]:
            if os.path.isfile(shell) and os.access(shell, os.X_OK):
                name = os.path.basename(shell)
                if name not in [s[0] for s in shells]:
                    shells.append((name, shell))

        if not shells:
            shells = [("bash", "/bin/bash")]

        for name, path in shells:
            self._shell_combo.addItem(name, path)

    def _apply_theme(self):
        """Apply Phantom Dark theme styling."""
        t = self.theme
        self.setStyleSheet(f"""
            QWidget#toolbar {{
                background-color: {t.toolbar_bg};
                border-bottom: 1px solid {t.panel_border};
            }}
            QWidget#status_bar {{
                background-color: {t.tab_bar_bg};
                border-top: 1px solid {t.panel_border};
            }}
            QLabel#panel_title {{
                color: {t.tab_inactive_fg};
                font-family: 'Segoe UI', 'SF Pro Text', system-ui, sans-serif;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.5px;
            }}
            QLabel#status_label {{
                color: {t.tab_inactive_fg};
                font-family: 'Segoe UI', 'SF Pro Text', system-ui, sans-serif;
                font-size: 11px;
            }}
            QToolButton#toolbar_btn {{
                background: transparent;
                color: #44445a;
                border: none;
                border-radius: 4px;
                font-size: 15px;
                padding: 2px;
            }}
            QToolButton#toolbar_btn:hover {{
                background: rgba(124,106,247,0.15);
                color: #c8c8d4;
            }}
            QToolButton#toolbar_btn:pressed {{
                background: rgba(124,106,247,0.3);
                color: #e8e8f0;
            }}
            QComboBox#shell_combo {{
                background: {t.input_bg};
                color: #6666808;
                border: 1px solid {t.panel_border};
                border-radius: 3px;
                padding: 2px 6px;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 11px;
            }}
            QComboBox#shell_combo:hover {{
                border-color: #2a2a3e;
                color: {t.foreground};
            }}
            QComboBox#shell_combo::drop-down {{ border: none; width: 14px; }}
            QComboBox#shell_combo QAbstractItemView {{
                background: {t.input_bg};
                color: {t.foreground};
                border: 1px solid {t.panel_border};
                selection-background-color: rgba(124,106,247,0.3);
                outline: none;
            }}
            QFrame#separator {{
                color: {t.panel_border};
            }}
            QStackedWidget {{
                background: {t.background};
            }}
        """)

    # ─────────────────────────────────────────────
    # Session management
    # ─────────────────────────────────────────────

    def new_terminal(self, shell: str = None, cwd: str = None):
        """Create a new terminal tab."""
        shell = shell or self._shell_combo.currentData()
        cwd   = cwd   or os.path.expanduser("~")

        session = TerminalSession(0, self.theme)  # id assigned after tab creation

        # Create tab first to get ID
        tab_id = self._tab_bar.add_tab(
            title=os.path.basename(shell) if shell else "bash"
        )
        session.tab_id = tab_id

        # Connect signals
        session.widget.title_changed.connect(
            lambda title, tid=tab_id: self._on_title_changed(tid, title)
        )
        session.widget.process_exited.connect(
            lambda code, tid=tab_id: self._on_session_exited(tid, code)
        )
        session.widget.bell_triggered.connect(self._on_bell)

        # Add to stack
        self._sessions[tab_id] = session
        self._stack.addWidget(session.widget)

        # Start PTY
        ok = session.start(shell=shell, cwd=cwd)
        if not ok:
            self._tab_bar.set_badge(tab_id, "✕")

        # Activate
        self._activate_tab(tab_id)

        # Update status
        self._update_status(tab_id)

    def close_terminal(self, tab_id: int):
        """Close a terminal tab."""
        session = self._sessions.pop(tab_id, None)
        if not session:
            return

        session.stop()
        self._stack.removeWidget(session.widget)
        session.widget.deleteLater()
        self._tab_bar.remove_tab(tab_id)

        # Activate remaining tab
        if self._sessions:
            remaining = next(iter(self._sessions))
            self._activate_tab(remaining)
        else:
            # No more tabs — create new one
            QTimer.singleShot(50, self.new_terminal)

    def split_terminal(self):
        """Open a new terminal (split would require splitter widget)."""
        self.new_terminal()

    def clear_active(self):
        """Clear the active terminal."""
        session = self._active_session()
        if session:
            # Send Ctrl+L to shell
            session.widget.write_to_pty(b"\x0c")

    def show_find(self):
        """Show the find bar."""
        self._find_bar.show_bar()

    # ─────────────────────────────────────────────
    # Tab switching
    # ─────────────────────────────────────────────

    def _activate_tab(self, tab_id: int):
        """Switch to the given tab."""
        self._active_tab_id = tab_id
        self._tab_bar.set_active(tab_id)

        session = self._sessions.get(tab_id)
        if session:
            self._stack.setCurrentWidget(session.widget)
            session.widget.setFocus()
            self._update_status(tab_id)

    def _active_session(self) -> Optional[TerminalSession]:
        """Return the currently active session."""
        return self._sessions.get(self._active_tab_id)

    # ─────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────

    def _on_tab_selected(self, tab_id: int):
        self._activate_tab(tab_id)

    def _on_tab_close(self, tab_id: int):
        self.close_terminal(tab_id)

    def _on_title_changed(self, tab_id: int, title: str):
        if title:
            self._tab_bar.set_title(tab_id, title)
            if tab_id == self._active_tab_id:
                self.title_changed.emit(title)
                self._status_shell.setText(title)

    def _on_session_exited(self, tab_id: int, code: int):
        self._tab_bar.set_exit_code(tab_id, code)
        session = self._sessions.get(tab_id)
        if session:
            session.exit_code = code
        self.session_exited.emit(tab_id, code)

    def _on_bell(self):
        """Flash the taskbar or play system bell."""
        # Flash window
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.beep()
        except Exception:
            pass

    def _on_theme_changed(self, index: int):
        key   = self._theme_combo.itemData(index)
        theme = get_theme(key)
        self.set_theme(theme)

    def _on_find(self, query: str, case_sensitive: bool, regex: bool):
        session = self._active_session()
        if session:
            count = session.widget.find(query, case_sensitive, regex)
            self._find_bar.set_match_info(0, count)

    def _find_next(self):
        session = self._active_session()
        if session:
            session.widget.find_next()

    def _find_prev(self):
        session = self._active_session()
        if session:
            session.widget.find_prev()

    def _on_find_closed(self):
        session = self._active_session()
        if session:
            session.widget.clear_find()
            session.widget.setFocus()

    def _show_settings(self):
        """Open settings dialog."""
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.theme, parent=self)
        if dlg.exec():
            self.set_theme(dlg.selected_theme())

    # ─────────────────────────────────────────────
    # Status bar update
    # ─────────────────────────────────────────────

    def _update_status(self, tab_id: int):
        session = self._sessions.get(tab_id)
        if not session:
            return

        buf = session.widget._buffer
        shell = os.path.basename(session.pty.shell) if session.pty.shell else "bash"

        self._status_shell.setText(shell)
        self._status_pid.setText(f"PID: {session.pty.get_pid() or '—'}")
        self._status_cursor.setText(
            f"Ln {buf.cursor.row + 1}, Col {buf.cursor.col + 1}"
        )
        self._status_size.setText(f"{buf.cols}×{buf.rows}")
        self._status_enc.setText("UTF-8")

    # ─────────────────────────────────────────────
    # Theme management
    # ─────────────────────────────────────────────

    def set_theme(self, theme: TerminalTheme):
        """Apply a theme to all sessions and chrome."""
        self.theme = theme
        self._tab_bar.set_theme(theme)
        self._find_bar.set_theme(theme)
        self._apply_theme()

        for session in self._sessions.values():
            session.widget.set_theme(theme)

    # ─────────────────────────────────────────────
    # Keyboard shortcuts
    # ─────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        mods = event.modifiers()
        key  = event.key()

        if mods & Qt.KeyboardModifier.ControlModifier:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                if key == Qt.Key.Key_QuoteLeft:  # Ctrl+Shift+`
                    self.new_terminal()
                    return
                elif key == Qt.Key.Key_F:
                    self.show_find()
                    return
                elif key == Qt.Key.Key_W:
                    if self._active_tab_id:
                        self.close_terminal(self._active_tab_id)
                    return

            if key == Qt.Key.Key_K:
                self.clear_active()
                return
            elif key == Qt.Key.Key_Tab:
                self._cycle_tab(1)
                return

        super().keyPressEvent(event)

    def _cycle_tab(self, direction: int):
        """Cycle through tabs."""
        ids  = list(self._sessions.keys())
        if len(ids) < 2:
            return
        if self._active_tab_id in ids:
            idx = ids.index(self._active_tab_id)
            idx = (idx + direction) % len(ids)
            self._activate_tab(ids[idx])

    # ─────────────────────────────────────────────
    # Resize
    # ─────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Reposition find bar
        if self._find_bar.isVisible():
            sw = self._stack.width()
            self._find_bar.move(sw - self._find_bar.width() - 16, 8)
