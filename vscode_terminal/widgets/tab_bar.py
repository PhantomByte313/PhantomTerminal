"""
widgets/tab_bar.py
==================
VS Code-style terminal tab bar with:
  - Add/close/reorder tabs
  - Active tab indicator (colored bottom border)
  - Hover effects
  - Close button on hover
  - Drag to reorder (basic)
  - Tab overflow with scroll
  - Context menu per tab
  - Badge support (for process exit codes)
"""

from PyQt6.QtCore  import Qt, QRect, QPoint, QSize, pyqtSignal, QTimer, QMimeData
from PyQt6.QtGui   import (QPainter, QColor, QFont, QFontMetrics, QPen,
                            QBrush, QMouseEvent, QPaintEvent, QDrag, QCursor)
from PyQt6.QtWidgets import QWidget, QSizePolicy, QMenu, QToolTip
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from themes.vscode_themes import TerminalTheme, DARK_PLUS


@dataclass
class TabInfo:
    """Data for a single tab."""
    tab_id:   int
    title:    str          = "bash"
    icon:     str          = "⬡"       # Unicode shell icon
    pid:      int          = 0
    active:   bool         = False
    running:  bool         = True      # Shell alive
    exit_code: Optional[int] = None
    badge:    str          = ""        # Optional badge text
    dirty:    bool         = False     # Unsaved changes (future)

    # Geometry (set by layout pass)
    x:        int          = 0
    width:    int          = 0


class TabBar(QWidget):
    """
    VS Code-style tab bar for multiple terminal sessions.
    
    Signals:
      tab_selected(int)    – user clicked a tab (tab_id)
      tab_close_requested(int) – user clicked X or middle-clicked
      tab_add_requested()  – user clicked the + button
      tab_renamed(int, str)    – user double-clicked and renamed
    """

    tab_selected       = pyqtSignal(int)   # tab_id
    tab_close_requested = pyqtSignal(int)  # tab_id
    tab_add_requested  = pyqtSignal()
    tab_renamed        = pyqtSignal(int, str)

    # ── Geometry constants ────────────────────────
    TAB_MIN_WIDTH   = 100
    TAB_MAX_WIDTH   = 220
    TAB_HEIGHT      = 35
    CLOSE_BTN_SIZE  = 16
    ADD_BTN_WIDTH   = 36
    PADDING_H       = 12   # Horizontal text padding
    ICON_WIDTH      = 18
    BORDER_WIDTH    = 2    # Active tab bottom border

    def __init__(self, theme: TerminalTheme = DARK_PLUS, parent=None):
        super().__init__(parent)
        self.theme = theme

        self._tabs:        List[TabInfo] = []
        self._active_id:   Optional[int] = None
        self._next_id:     int           = 1
        self._hover_tab:   Optional[int] = None   # tab_id under cursor
        self._hover_close: Optional[int] = None   # tab_id with close btn hovered
        self._scroll_x:    int           = 0      # Horizontal scroll offset
        self._drag_start:  Optional[QPoint] = None
        self._drag_tab:    Optional[int]    = None

        # Font
        self._font = QFont("Segoe UI", 12)
        self._font.setWeight(QFont.Weight.Medium)
        self._fm   = QFontMetrics(self._font)

        # Colors (precomputed)
        self._init_colors()

        self.setFixedHeight(self.TAB_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def add_tab(self, title: str = "bash", pid: int = 0) -> int:
        """Add a new tab. Returns its tab_id."""
        tab_id = self._next_id
        self._next_id += 1

        tab = TabInfo(tab_id=tab_id, title=title, pid=pid)
        self._tabs.append(tab)
        self.set_active(tab_id)
        self._layout_tabs()
        self.update()
        return tab_id

    def remove_tab(self, tab_id: int):
        """Remove a tab by id."""
        self._tabs = [t for t in self._tabs if t.tab_id != tab_id]
        if self._active_id == tab_id and self._tabs:
            self.set_active(self._tabs[-1].tab_id)
        self._layout_tabs()
        self.update()

    def set_active(self, tab_id: int):
        """Set the active tab."""
        self._active_id = tab_id
        for t in self._tabs:
            t.active = (t.tab_id == tab_id)
        self._ensure_visible(tab_id)
        self.update()

    def set_title(self, tab_id: int, title: str):
        """Update tab title."""
        for t in self._tabs:
            if t.tab_id == tab_id:
                t.title = title[:40]  # Truncate
                break
        self._layout_tabs()
        self.update()

    def set_exit_code(self, tab_id: int, code: int):
        """Mark tab as exited."""
        for t in self._tabs:
            if t.tab_id == tab_id:
                t.running   = False
                t.exit_code = code
                t.icon      = "✕" if code != 0 else "✓"
                break
        self.update()

    def set_badge(self, tab_id: int, badge: str):
        """Set badge text on tab."""
        for t in self._tabs:
            if t.tab_id == tab_id:
                t.badge = badge
                break
        self.update()

    def tab_count(self) -> int:
        return len(self._tabs)

    def active_tab_id(self) -> Optional[int]:
        return self._active_id

    def set_theme(self, theme: TerminalTheme):
        self.theme = theme
        self._init_colors()
        self.update()

    # ─────────────────────────────────────────────
    # Layout
    # ─────────────────────────────────────────────

    def _layout_tabs(self):
        """Calculate tab widths and positions."""
        if not self._tabs:
            return

        available = self.width() - self.ADD_BTN_WIDTH - 2
        n         = len(self._tabs)
        tab_w     = max(self.TAB_MIN_WIDTH,
                        min(self.TAB_MAX_WIDTH, available // n))

        x = 0
        for tab in self._tabs:
            tab.x     = x - self._scroll_x
            tab.width = tab_w
            x        += tab_w

    def _ensure_visible(self, tab_id: int):
        """Scroll to make the given tab visible."""
        for t in self._tabs:
            if t.tab_id == tab_id:
                if t.x < 0:
                    self._scroll_x = max(0, self._scroll_x + t.x)
                elif t.x + t.width > self.width() - self.ADD_BTN_WIDTH:
                    overshoot = (t.x + t.width) - (self.width() - self.ADD_BTN_WIDTH)
                    self._scroll_x += overshoot
                self._layout_tabs()
                break

    # ─────────────────────────────────────────────
    # Colors
    # ─────────────────────────────────────────────

    def _init_colors(self):
        t = self.theme
        self._c_bar_bg       = QColor(t.tab_bar_bg)
        self._c_active_bg    = QColor(t.tab_active_bg)
        self._c_inactive_bg  = QColor(t.tab_inactive_bg)
        self._c_active_fg    = QColor(t.tab_active_fg)
        self._c_inactive_fg  = QColor(t.tab_inactive_fg)
        self._c_active_border = QColor(t.tab_active_border)
        self._c_separator    = QColor(t.panel_border)
        self._c_close_hover  = QColor(255, 255, 255, 40)
        self._c_badge_bg     = QColor(t.badge_bg)
        self._c_badge_fg     = QColor(t.badge_fg)

    # ─────────────────────────────────────────────
    # Painting
    # ─────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        self._layout_tabs()

        # Background
        p.fillRect(self.rect(), self._c_bar_bg)

        # Bottom border
        p.setPen(QPen(self._c_separator, 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

        # Draw tabs
        for tab in self._tabs:
            self._paint_tab(p, tab)

        # Add button
        self._paint_add_button(p)

        p.end()

    def _paint_tab(self, p: QPainter, tab: TabInfo):
        x = tab.x
        w = tab.width
        h = self.TAB_HEIGHT

        if x + w < 0 or x > self.width():
            return  # Out of view

        # ── Background ──────────────────────────────
        if tab.active:
            bg = self._c_active_bg
        elif tab.tab_id == self._hover_tab:
            bg = QColor(self._c_inactive_bg.red()   + 10,
                        self._c_inactive_bg.green()  + 10,
                        self._c_inactive_bg.blue()   + 10)
        else:
            bg = self._c_inactive_bg

        p.fillRect(x, 0, w, h, bg)

        # ── Active tab bottom border ─────────────────
        if tab.active:
            p.fillRect(x, h - self.BORDER_WIDTH, w, self.BORDER_WIDTH,
                       self._c_active_border)

        # ── Right separator ──────────────────────────
        p.setPen(QPen(self._c_separator, 1))
        p.drawLine(x + w - 1, 4, x + w - 1, h - 4)

        # ── Icon ─────────────────────────────────────
        fg = self._c_active_fg if tab.active else self._c_inactive_fg
        p.setPen(fg)
        p.setFont(QFont("Segoe UI Emoji", 11))
        icon_x = x + self.PADDING_H
        p.drawText(QRect(icon_x, 0, self.ICON_WIDTH, h - 2),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   tab.icon if tab.icon else "⬡")

        # ── Title ─────────────────────────────────────
        p.setFont(self._font)
        p.setPen(fg)
        close_w  = self.CLOSE_BTN_SIZE + 8
        badge_w  = (self._fm.horizontalAdvance(tab.badge) + 10) if tab.badge else 0
        text_x   = icon_x + self.ICON_WIDTH + 4
        text_w   = w - (text_x - x) - close_w - badge_w - 4

        if text_w > 10:
            title = tab.title
            # Elide if too long
            etext = self._fm.elidedText(title, Qt.TextElideMode.ElideMiddle, text_w)
            p.drawText(QRect(text_x, 0, text_w, h - 2),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       etext)

        # ── Badge ─────────────────────────────────────
        if tab.badge:
            bx = x + w - close_w - badge_w - 4
            by = (h - 16) // 2
            p.fillRect(bx, by, badge_w, 16,
                       self._c_badge_bg if tab.running else QColor("#cd3131"))
            p.setPen(self._c_badge_fg)
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRect(bx, by, badge_w, 16),
                       Qt.AlignmentFlag.AlignCenter, tab.badge)
            p.setFont(self._font)

        # ── Close button ──────────────────────────────
        if tab.active or tab.tab_id == self._hover_tab:
            cx = x + w - close_w + (close_w - self.CLOSE_BTN_SIZE) // 2
            cy = (h - self.CLOSE_BTN_SIZE) // 2

            if tab.tab_id == self._hover_close:
                p.setBrush(QBrush(self._c_close_hover))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(cx - 2, cy - 2,
                                  self.CLOSE_BTN_SIZE + 4,
                                  self.CLOSE_BTN_SIZE + 4, 3, 3)

            p.setPen(QPen(fg, 1.5))
            margin = 4
            p.drawLine(cx + margin, cy + margin,
                       cx + self.CLOSE_BTN_SIZE - margin,
                       cy + self.CLOSE_BTN_SIZE - margin)
            p.drawLine(cx + self.CLOSE_BTN_SIZE - margin,
                       cy + margin,
                       cx + margin,
                       cy + self.CLOSE_BTN_SIZE - margin)

    def _paint_add_button(self, p: QPainter):
        """Paint the + new terminal button."""
        x = self.width() - self.ADD_BTN_WIDTH
        h = self.TAB_HEIGHT
        w = self.ADD_BTN_WIDTH

        is_hover = getattr(self, "_add_hover", False)
        if is_hover:
            p.fillRect(x, 0, w, h - 1, QColor(255, 255, 255, 20))

        p.setPen(QPen(self._c_inactive_fg, 1.5))
        cx = x + w // 2
        cy = h // 2 - 1
        sz = 8
        p.drawLine(cx - sz, cy, cx + sz, cy)
        p.drawLine(cx, cy - sz, cx, cy + sz)

    # ─────────────────────────────────────────────
    # Mouse events
    # ─────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        pos    = event.position().toPoint()
        tab_id = self._tab_at(pos)

        if event.button() == Qt.MouseButton.LeftButton:
            # Check add button
            if pos.x() >= self.width() - self.ADD_BTN_WIDTH:
                self.tab_add_requested.emit()
                return

            if tab_id is not None:
                # Check close button
                if self._is_on_close(pos, tab_id):
                    self.tab_close_requested.emit(tab_id)
                    return
                # Select tab
                self.tab_selected.emit(tab_id)
                self._drag_start = pos
                self._drag_tab   = tab_id

        elif event.button() == Qt.MouseButton.MiddleButton:
            if tab_id is not None:
                self.tab_close_requested.emit(tab_id)

        elif event.button() == Qt.MouseButton.RightButton:
            if tab_id is not None:
                self._show_tab_context_menu(tab_id, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent):
        pos    = event.position().toPoint()
        tab_id = self._tab_at(pos)

        self._hover_tab   = tab_id
        self._hover_close = tab_id if (tab_id and self._is_on_close(pos, tab_id)) else None
        self._add_hover   = pos.x() >= self.width() - self.ADD_BTN_WIDTH

        # Tooltip
        if tab_id:
            for t in self._tabs:
                if t.tab_id == tab_id:
                    QToolTip.showText(event.globalPosition().toPoint(),
                                      f"{t.title} (PID: {t.pid})")
                    break

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None
        self._drag_tab   = None

    def leaveEvent(self, event):
        self._hover_tab   = None
        self._hover_close = None
        self._add_hover   = False
        self.update()

    def wheelEvent(self, event):
        """Horizontal scroll through tabs."""
        delta = event.angleDelta().y()
        max_scroll = max(0, sum(t.width for t in self._tabs) - self.width() + self.ADD_BTN_WIDTH)
        self._scroll_x = max(0, min(self._scroll_x - delta // 4, max_scroll))
        self._layout_tabs()
        self.update()

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────

    def _tab_at(self, pos: QPoint) -> Optional[int]:
        """Return tab_id at pixel position, or None."""
        for tab in self._tabs:
            if tab.x <= pos.x() < tab.x + tab.width and 0 <= pos.y() < self.TAB_HEIGHT:
                return tab.tab_id
        return None

    def _is_on_close(self, pos: QPoint, tab_id: int) -> bool:
        """Check if pos is on the close button of the given tab."""
        for tab in self._tabs:
            if tab.tab_id != tab_id:
                continue
            close_w = self.CLOSE_BTN_SIZE + 8
            cx = tab.x + tab.width - close_w
            cy = (self.TAB_HEIGHT - self.CLOSE_BTN_SIZE) // 2
            return (cx <= pos.x() <= tab.x + tab.width and
                    cy - 2 <= pos.y() <= cy + self.CLOSE_BTN_SIZE + 2)
        return False

    def _show_tab_context_menu(self, tab_id: int, global_pos):
        t = self.theme
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {t.tab_bar_bg}; color: {t.foreground};
                border: 1px solid {t.panel_border}; border-radius: 4px;
                padding: 4px 0; font-size: 12px;
            }}
            QMenu::item {{ padding: 6px 20px 6px 12px; }}
            QMenu::item:selected {{ background: {t.input_border}; color: white; }}
            QMenu::separator {{ height: 1px; background: {t.panel_border}; margin: 4px 0; }}
        """)

        rename   = menu.addAction("Rename Tab")
        menu.addSeparator()
        close_t  = menu.addAction("Close Terminal")
        close_ot = menu.addAction("Close Other Terminals")
        menu.addSeparator()
        split    = menu.addAction("Split Terminal")

        action = menu.exec(global_pos)
        if action == close_t:
            self.tab_close_requested.emit(tab_id)
        elif action == close_ot:
            for t in list(self._tabs):
                if t.tab_id != tab_id:
                    self.tab_close_requested.emit(t.tab_id)
        elif action == split:
            self.tab_add_requested.emit()

    def resizeEvent(self, event):
        self._layout_tabs()
        self.update()
