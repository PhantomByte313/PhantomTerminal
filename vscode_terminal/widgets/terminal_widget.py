"""
widgets/terminal_widget.py
===========================
The main terminal rendering widget.

Renders the terminal grid using QPainter with:
  - Cell-by-cell character rendering
  - Font metrics for precise glyph placement
  - Cursor blinking animation (Qt timer)
  - Mouse selection with clipboard integration
  - Smooth scrolling
  - High-DPI / Retina support
  - Bracketed paste mode
  - URL detection and hover
  - Find/search highlight overlay
  - Resize handling with PTY notification
"""

import re
import time
from typing import Optional, Set, Tuple, List

from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, pyqtSignal, QMimeData,
    QThread, pyqtSlot
)
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QKeyEvent,
    QMouseEvent, QWheelEvent, QPaintEvent, QResizeEvent,
    QClipboard, QCursor, QPen, QBrush, QFontDatabase,
    QGuiApplication, QTextCursor
)
from PyQt6.QtWidgets import (
    QWidget, QApplication, QSizePolicy, QToolTip, QAbstractScrollArea
)

from core.terminal_buffer import ScreenBuffer, ScreenCell, ScreenLine, Cursor
from core.ansi_parser     import (
    ANSIParser, ParserEvent, ParserEventType, TextAttributes,
    Color, ColorType, ANSI16_PALETTE
)
from core.pty_handler     import PTYHandler
from themes.vscode_themes import TerminalTheme, DARK_PLUS


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Cursor blink intervals (ms)
CURSOR_BLINK_ON  = 600
CURSOR_BLINK_OFF = 300

# Mouse selection modes
SEL_NONE   = 0
SEL_CHAR   = 1
SEL_WORD   = 2
SEL_LINE   = 3

# URL regex for hyperlink detection
URL_RE = re.compile(
    r"https?://[^\s\x1b\x07\"'<>()[\]{}\\]*[^\s\x1b\x07\"'<>()[\]{}\\.,;:!?]",
    re.IGNORECASE
)


# ─────────────────────────────────────────────────────────────────────────────
# Terminal Widget
# ─────────────────────────────────────────────────────────────────────────────

class TerminalWidget(QWidget):
    """
    The core terminal rendering/input widget.
    
    Combines:
      - ScreenBuffer  (the terminal state machine)
      - ANSIParser    (escape sequence decoder)
      - PTYHandler    (the shell process)
    
    Renders using raw QPainter calls for maximum performance.
    """

    # ── Signals ──────────────────────────────────
    title_changed    = pyqtSignal(str)
    bell_triggered   = pyqtSignal()
    data_sent        = pyqtSignal(bytes)
    process_exited   = pyqtSignal(int)
    selection_changed = pyqtSignal(str)
    url_hovered      = pyqtSignal(str)

    # ── Sizing constants ──────────────────────────
    MIN_COLS = 5
    MIN_ROWS = 2

    def __init__(self, theme: TerminalTheme = DARK_PLUS, parent=None):
        super().__init__(parent)

        # ── State ─────────────────────────────────
        self.theme   = theme
        self._buffer  = ScreenBuffer()
        self._parser  = ANSIParser()
        self._pty:    Optional[PTYHandler] = None

        # ── Font ──────────────────────────────────
        self._font_family   = ""
        self._font_size_pt  = 13
        self._font:  QFont          = None
        self._bold_font: QFont      = None
        self._italic_font: QFont    = None
        self._bold_italic_font: QFont = None
        self._fm:    QFontMetrics   = None
        self._cell_w = 8
        self._cell_h = 18
        self._cell_asc = 14   # Ascender height

        # ── Cursor ────────────────────────────────
        self._cursor_visible  = True   # Blink state
        self._cursor_blink_on = True
        self._blink_timer     = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_cursor)

        # ── Selection ─────────────────────────────
        self._sel_mode      = SEL_NONE
        self._sel_start:    Optional[Tuple[int, int]] = None  # (row, col)
        self._sel_end:      Optional[Tuple[int, int]] = None
        self._sel_dragging  = False
        self._double_click_word: Optional[str] = None

        # ── Find ──────────────────────────────────
        self._find_results: List[Tuple[int,int,int,int]] = []  # (r,c,r2,c2)
        self._find_current  = -1

        # ── Scrollbar ─────────────────────────────
        self._scroll_bar_dragging = False
        self._scroll_bar_x        = 0
        self._scroll_bar_width    = 6   # Thin like VS Code
        self._scroll_hover        = False

        # ── URL detection ─────────────────────────
        self._hovered_url: Optional[str] = None
        self._url_cells:   List[Tuple[Tuple[int,int],Tuple[int,int],str]] = []

        # ── Padding ───────────────────────────────
        self._padding_h = 4   # Horizontal padding (px)
        self._padding_v = 2   # Vertical padding (px)

        # ── Timing ────────────────────────────────
        self._last_paint  = time.monotonic()
        self._dirty_timer = QTimer(self)
        self._dirty_timer.setInterval(16)   # ~60fps
        self._dirty_timer.timeout.connect(self._repaint_dirty)
        self._dirty_timer.start()

        # ── Resize debounce ───────────────────────
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._do_resize)

        # ── Setup ─────────────────────────────────
        self._init_font()
        self._init_colors()
        self._setup_widget()

    # ─────────────────────────────────────────────
    # Initialization
    # ─────────────────────────────────────────────

    def _init_font(self):
        """Initialize the terminal font (monospace, matching VS Code)."""
        # Priority list matching VS Code's default font stacks
        preferred = [
            "Cascadia Code",
            "Cascadia Mono",
            "Fira Code",
            "JetBrains Mono",
            "Source Code Pro",
            "Hack",
            "DejaVu Sans Mono",
            "Liberation Mono",
            "Consolas",
            "Courier New",
            "Monospace",
        ]

        available = QFontDatabase.families()
        chosen    = "Monospace"

        for name in preferred:
            if name in available:
                chosen = name
                break

        self._font_family = chosen
        self._rebuild_fonts()

    def _rebuild_fonts(self):
        """Rebuild font objects after size/family change."""
        def make(bold=False, italic=False) -> QFont:
            f = QFont(self._font_family, self._font_size_pt)
            f.setBold(bold)
            f.setItalic(italic)
            f.setFixedPitch(True)
            f.setStyleHint(QFont.StyleHint.Monospace)
            f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
            f.setKerning(False)
            return f

        self._font            = make()
        self._bold_font       = make(bold=True)
        self._italic_font     = make(italic=True)
        self._bold_italic_font = make(bold=True, italic=True)

        self._fm = QFontMetrics(self._font)
        self._cell_w   = self._fm.horizontalAdvance("M")
        self._cell_h   = self._fm.height()
        self._cell_asc = self._fm.ascent()

        if self._pty:
            # Notify shell of new size
            cols, rows = self._calc_grid_size()
            self._buffer.resize(cols, rows)
            self._pty.resize(cols, rows)

    def _init_colors(self):
        """Pre-compute QColor objects from theme for performance."""
        t = self.theme
        self._qc_bg         = QColor(t.background)
        self._qc_fg         = QColor(t.foreground)
        self._qc_cursor     = QColor(t.cursor_color)
        self._qc_sel_bg     = QColor(t.selection_bg)
        self._qc_sel_bg.setAlpha(180)
        self._qc_scrollbar  = QColor(t.scrollbar_thumb)
        self._qc_scrollbar_hover = QColor(t.scrollbar_thumb_hover)
        self._qc_link       = QColor(t.link_color)
        self._qc_find_hl    = QColor(t.find_highlight)
        self._qc_find_hl.setAlpha(140)
        self._qc_find_border = QColor(t.find_highlight_border)

        # Precompute ANSI palette QColors
        self._ansi_palette: List[QColor] = []
        for hex_color in t.ansi_palette():
            self._ansi_palette.append(QColor(hex_color))

    def _setup_widget(self):
        """Configure widget properties."""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        # Start cursor blink
        self._blink_timer.start(CURSOR_BLINK_ON)

    # ─────────────────────────────────────────────
    # PTY connection
    # ─────────────────────────────────────────────

    def attach_pty(self, pty: PTYHandler):
        """Connect this widget to a PTY handler."""
        self._pty = pty
        pty.data_received.connect(self._on_data_received)
        pty.process_exited.connect(self.process_exited)
        pty.process_exited.connect(self._on_process_exited)

    def detach_pty(self):
        """Disconnect from PTY."""
        if self._pty:
            try:
                self._pty.data_received.disconnect(self._on_data_received)
            except Exception:
                pass
            self._pty = None

    # ─────────────────────────────────────────────
    # Data I/O
    # ─────────────────────────────────────────────

    @pyqtSlot(bytes)
    def _on_data_received(self, data: bytes):
        """Process raw bytes from the PTY and update the buffer."""
        events = self._parser.feed(data)
        for event in events:
            if event.type == ParserEventType.BELL:
                self.bell_triggered.emit()
            elif event.type == ParserEventType.WINDOW_TITLE:
                self.title_changed.emit(event.text)
            else:
                self._buffer.process_event(event)

        # Title from buffer
        if self._buffer.title:
            self.title_changed.emit(self._buffer.title)
            self._buffer.title = ""

    @pyqtSlot(int)
    def _on_process_exited(self, code: int):
        """Shell process died."""
        self._pty = None
        self._blink_timer.stop()
        self.update()

    def write_to_pty(self, data: bytes):
        """Send bytes to the shell."""
        if self._pty:
            self._pty.write(data)
            self.data_sent.emit(data)

    # ─────────────────────────────────────────────
    # Painting
    # ─────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        """Main paint handler - renders the terminal grid."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        try:
            self._paint_terminal(painter, event.rect())
        finally:
            painter.end()

        self._last_paint = time.monotonic()

    def _paint_terminal(self, p: QPainter, clip: QRect):
        """Render the full terminal grid."""
        cw = self._cell_w
        ch = self._cell_h
        ph = self._padding_h
        pv = self._padding_v

        # Fill background
        p.fillRect(self.rect(), self._qc_bg)

        # Calculate visible row range from clip rect
        first_row = max(0, (clip.top() - pv) // ch)
        last_row  = min(self._buffer.rows - 1, (clip.bottom() - pv) // ch + 1)

        cursor_row = self._buffer.cursor.row
        cursor_col = self._buffer.cursor.col

        for screen_row in range(first_row, last_row + 1):
            y = pv + screen_row * ch

            # Get the line (accounting for scrollback viewport)
            line = self._buffer.get_visible_line(screen_row)
            if line is None:
                continue

            self._paint_row(p, screen_row, line, y, ph, cw, ch, cursor_row, cursor_col)

        # Cursor overlay
        if (self._buffer.cursor.visible and self._cursor_blink_on
                and self._buffer.scroll_offset == 0):
            self._paint_cursor(p, cursor_row, cursor_col, ph, pv, cw, ch)

        # Selection overlay
        if self._sel_start and self._sel_end:
            self._paint_selection(p, ph, pv, cw, ch)

        # Find highlights
        if self._find_results:
            self._paint_find_highlights(p, ph, pv, cw, ch)

        # Scrollbar
        self._paint_scrollbar(p)

    def _paint_row(self, p: QPainter, row: int, line: ScreenLine,
                   y: int, ph: int, cw: int, ch: int,
                   cursor_row: int, cursor_col: int):
        """Paint a single row of cells."""
        # Batch cells with identical attributes for efficient rendering
        batch_start = 0
        batch_attrs: Optional[TextAttributes] = None
        batch_text   = []
        batch_x      = ph

        cells = line.cells
        num_cells = len(cells)

        def flush_batch(end_col: int):
            nonlocal batch_start, batch_attrs, batch_text, batch_x
            if not batch_text or batch_attrs is None:
                return

            text = "".join(batch_text)
            x    = ph + batch_start * cw
            w    = end_col * cw - batch_start * cw

            # Background
            eff_bg = batch_attrs.effective_bg()
            if not eff_bg.is_default():
                bg_color = self._resolve_color(eff_bg)
                p.fillRect(x, y, w, ch, bg_color)

            # Foreground
            eff_fg = batch_attrs.effective_fg()
            if eff_fg.is_default():
                fg_color = self._qc_fg
            else:
                fg_color = self._resolve_color(eff_fg)

            # Dimming
            if batch_attrs.dim:
                fg_color = QColor(
                    fg_color.red()   * 2 // 3,
                    fg_color.green() * 2 // 3,
                    fg_color.blue()  * 2 // 3,
                )

            # Invisible
            if batch_attrs.invisible:
                fg_color = QColor(0, 0, 0, 0)

            # Choose font variant
            if batch_attrs.bold and batch_attrs.italic:
                p.setFont(self._bold_italic_font)
            elif batch_attrs.bold:
                p.setFont(self._bold_font)
            elif batch_attrs.italic:
                p.setFont(self._italic_font)
            else:
                p.setFont(self._font)

            # Draw text
            p.setPen(fg_color)
            p.drawText(x, y + self._cell_asc, text)

            # Underline
            if batch_attrs.underline or batch_attrs.underline2:
                ul_color = self._resolve_color(batch_attrs.underline_color) \
                    if not batch_attrs.underline_color.is_default() else fg_color
                p.setPen(QPen(ul_color, 1 if batch_attrs.underline else 2))
                uy = y + self._cell_asc + 2
                p.drawLine(x, uy, x + w, uy)

            # Strikethrough
            if batch_attrs.strikethrough:
                p.setPen(QPen(fg_color, 1))
                sy = y + ch // 2
                p.drawLine(x, sy, x + w, sy)

            # Overline
            if batch_attrs.overline:
                p.setPen(QPen(fg_color, 1))
                p.drawLine(x, y + 1, x + w, y + 1)

            # URL underline
            if batch_attrs.url:
                p.setPen(QPen(self._qc_link, 1))
                p.drawLine(x, y + self._cell_asc + 2, x + w, y + self._cell_asc + 2)

            batch_text  = []
            batch_start = end_col
            batch_attrs = None

        for col in range(min(num_cells, self._buffer.cols)):
            cell = cells[col]

            if cell.placeholder:
                if batch_attrs is not None:
                    batch_text.append(" ")  # placeholder for wide char right half
                continue

            attrs = cell.attrs

            # Check if we need to flush batch (attrs changed)
            if batch_attrs is not None and not self._attrs_equal(attrs, batch_attrs):
                flush_batch(col)

            if batch_attrs is None:
                batch_start = col
                batch_attrs = attrs

            batch_text.append(cell.char if cell.char else " ")

        flush_batch(self._buffer.cols)

    def _attrs_equal(self, a: TextAttributes, b: TextAttributes) -> bool:
        """Fast attribute comparison for batching."""
        return (
            a.fg         == b.fg     and
            a.bg         == b.bg     and
            a.bold       == b.bold   and
            a.italic     == b.italic and
            a.dim        == b.dim    and
            a.underline  == b.underline and
            a.inverse    == b.inverse   and
            a.invisible  == b.invisible and
            a.strikethrough == b.strikethrough and
            a.url        == b.url
        )

    def _paint_cursor(self, p: QPainter, row: int, col: int,
                      ph: int, pv: int, cw: int, ch: int):
        """Draw the cursor based on cursor style."""
        x = ph + col * cw
        y = pv + row * ch
        style = self._buffer.cursor.style

        p.setPen(Qt.PenStyle.NoPen)

        if style in (1, 2):  # Block
            if self.hasFocus():
                p.fillRect(x, y, cw, ch, self._qc_cursor)
                # Draw char in cursor background
                cell = self._buffer.get_cell(row, col)
                if cell.char and cell.char != " ":
                    p.setFont(self._bold_font if cell.attrs.bold else self._font)
                    p.setPen(QColor(self.theme.cursor_text))
                    p.drawText(x, y + self._cell_asc, cell.char)
            else:
                # Unfocused: outline cursor
                p.setPen(QPen(self._qc_cursor, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(x, y, cw - 1, ch - 1)

        elif style in (3, 4):  # Underline
            p.fillRect(x, y + ch - 2, cw, 2, self._qc_cursor)

        elif style in (5, 6):  # Bar (I-beam)
            p.fillRect(x, y, 2, ch, self._qc_cursor)

    def _paint_selection(self, p: QPainter, ph: int, pv: int, cw: int, ch: int):
        """Paint selection highlight overlay."""
        start = self._sel_start
        end   = self._sel_end

        if start > end:
            start, end = end, start

        sr, sc = start
        er, ec = end

        p.setBrush(QBrush(self._qc_sel_bg))
        p.setPen(Qt.PenStyle.NoPen)

        if sr == er:
            # Single line
            x = ph + sc * cw
            y = pv + sr * ch
            w = (ec - sc) * cw
            if w > 0:
                p.drawRect(x, y, w, ch)
        else:
            # First line: sc to end
            x = ph + sc * cw
            y = pv + sr * ch
            w = (self._buffer.cols - sc) * cw
            p.drawRect(x, y, w, ch)

            # Middle lines: full width
            for r in range(sr + 1, er):
                y = pv + r * ch
                p.drawRect(ph, y, self._buffer.cols * cw, ch)

            # Last line: 0 to ec
            if ec > 0:
                y = pv + er * ch
                p.drawRect(ph, y, ec * cw, ch)

    def _paint_find_highlights(self, p: QPainter, ph: int, pv: int, cw: int, ch: int):
        """Paint find/search highlights."""
        for i, (sr, sc, er, ec) in enumerate(self._find_results):
            is_current = (i == self._find_current)
            color = self._qc_find_border if is_current else self._qc_find_hl

            if is_current:
                p.setPen(QPen(self._qc_find_border, 1))
                p.setBrush(QBrush(self._qc_find_hl))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(self._qc_find_hl))

            x = ph + sc * cw
            y = pv + sr * ch
            w = (ec - sc) * cw if sr == er else (self._buffer.cols - sc) * cw
            p.drawRect(x, y, w, ch)

    def _paint_scrollbar(self, p: QPainter):
        """Paint the thin scrollbar on the right edge (VS Code style)."""
        total      = self._buffer.total_rows
        visible    = self._buffer.rows
        scrollback = self._buffer.scrollback_count
        offset     = self._buffer.scroll_offset

        if total <= visible:
            return  # No scrollbar needed

        bar_x = self.width() - self._scroll_bar_width
        bar_h = self.height()

        # Thumb geometry
        thumb_h = max(20, int(bar_h * visible / total))
        # Position: offset=0 → bottom, offset=scrollback → top
        progress = 1.0 - (offset / scrollback) if scrollback > 0 else 1.0
        thumb_y  = int((bar_h - thumb_h) * progress)

        color = self._qc_scrollbar_hover if self._scroll_hover else self._qc_scrollbar
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(bar_x + 1, thumb_y, self._scroll_bar_width - 2, thumb_h, 2, 2)

    def _resolve_color(self, color: Color) -> QColor:
        """Convert a Color to QColor."""
        if color.type == ColorType.ANSI16:
            idx = color.value
            if 0 <= idx < len(self._ansi_palette):
                return self._ansi_palette[idx]
            return self._qc_fg
        elif color.type in (ColorType.ANSI256, ColorType.TRUE):
            return QColor(color.r, color.g, color.b)
        return self._qc_fg

    @pyqtSlot()
    def _repaint_dirty(self):
        """Repaint only dirty rows (called by 60fps timer)."""
        dirty = self._buffer.take_dirty()
        if not dirty:
            return

        cw = self._cell_w
        ch = self._cell_h
        pv = self._padding_v

        if len(dirty) > self._buffer.rows // 2:
            # More than half dirty, just repaint all
            self.update()
        else:
            for row in dirty:
                y = pv + row * ch
                self.update(0, y, self.width(), ch + 1)

    # ─────────────────────────────────────────────
    # Cursor blink
    # ─────────────────────────────────────────────

    @pyqtSlot()
    def _toggle_cursor(self):
        """Toggle cursor blink state."""
        self._cursor_blink_on = not self._cursor_blink_on

        # Schedule next blink
        interval = CURSOR_BLINK_ON if self._cursor_blink_on else CURSOR_BLINK_OFF
        self._blink_timer.setInterval(interval)

        # Repaint cursor cell
        row = self._buffer.cursor.row
        col = self._buffer.cursor.col
        x   = self._padding_h + col * self._cell_w
        y   = self._padding_v + row * self._cell_h
        self.update(x, y, self._cell_w * 2, self._cell_h)

    def _reset_cursor_blink(self):
        """Reset cursor to visible state (on keypress)."""
        self._cursor_blink_on = True
        self._blink_timer.stop()
        self._blink_timer.start(CURSOR_BLINK_ON)

    # ─────────────────────────────────────────────
    # Keyboard input
    # ─────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard input and translate to terminal sequences."""
        self._reset_cursor_blink()

        key  = event.key()
        mods = event.modifiers()
        text = event.text()

        # ── Ctrl combinations ──────────────────────
        if mods & Qt.KeyboardModifier.ControlModifier:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                # Ctrl+Shift combinations (VS Code shortcuts)
                if key == Qt.Key.Key_C:
                    self._copy_selection()
                    return
                elif key == Qt.Key.Key_V:
                    self._paste()
                    return
                elif key == Qt.Key.Key_F:
                    # Find - handled by parent
                    return
                elif key == Qt.Key.Key_Equal:
                    self.increase_font_size()
                    return
                elif key == Qt.Key.Key_Minus:
                    self.decrease_font_size()
                    return
                elif key == Qt.Key.Key_0:
                    self.reset_font_size()
                    return

            # Ctrl+letter → control character
            elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                ctrl_char = bytes([key - Qt.Key.Key_A + 1])
                self.write_to_pty(ctrl_char)
                return
            elif key == Qt.Key.Key_BracketLeft:
                self.write_to_pty(b"\x1b")  # ESC
                return
            elif key == Qt.Key.Key_Backslash:
                self.write_to_pty(b"\x1c")
                return
            elif key == Qt.Key.Key_BracketRight:
                self.write_to_pty(b"\x1d")
                return
            elif key == Qt.Key.Key_6:
                self.write_to_pty(b"\x1e")
                return
            elif key == Qt.Key.Key_Minus:
                self.write_to_pty(b"\x1f")
                return

        # ── Alt combinations ───────────────────────
        if mods & Qt.KeyboardModifier.AltModifier:
            if text:
                self.write_to_pty(b"\x1b" + text.encode("utf-8"))
                return

        # ── Function keys ──────────────────────────
        seq = self._key_to_escape_sequence(key, mods)
        if seq:
            self.write_to_pty(seq)
            return

        # ── Regular text ───────────────────────────
        if text:
            encoded = text.encode("utf-8", errors="replace")
            self.write_to_pty(encoded)
            return

        event.ignore()

    def _key_to_escape_sequence(self, key: int, mods) -> Optional[bytes]:
        """Map Qt key to VT/xterm escape sequence."""
        shift   = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl    = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt     = bool(mods & Qt.KeyboardModifier.AltModifier)

        # Modifier suffix for arrow keys (xterm 1006 style)
        mod_code = 1
        if shift:    mod_code += 1
        if alt:      mod_code += 2
        if ctrl:     mod_code += 4
        mod_suffix = f";{mod_code}" if mod_code > 1 else ""

        K = Qt.Key

        # Arrow keys
        if key == K.Key_Up:
            return f"\x1b[1{mod_suffix}A".encode() if mod_suffix else b"\x1b[A"
        elif key == K.Key_Down:
            return f"\x1b[1{mod_suffix}B".encode() if mod_suffix else b"\x1b[B"
        elif key == K.Key_Right:
            return f"\x1b[1{mod_suffix}C".encode() if mod_suffix else b"\x1b[C"
        elif key == K.Key_Left:
            return f"\x1b[1{mod_suffix}D".encode() if mod_suffix else b"\x1b[D"

        # Navigation
        elif key == K.Key_Home:
            return f"\x1b[1{mod_suffix}H".encode() if mod_suffix else b"\x1b[H"
        elif key == K.Key_End:
            return f"\x1b[1{mod_suffix}F".encode() if mod_suffix else b"\x1b[F"
        elif key == K.Key_PageUp:
            return f"\x1b[5{mod_suffix}~".encode()
        elif key == K.Key_PageDown:
            return f"\x1b[6{mod_suffix}~".encode()
        elif key == K.Key_Insert:
            return f"\x1b[2{mod_suffix}~".encode()
        elif key == K.Key_Delete:
            return f"\x1b[3{mod_suffix}~".encode()

        # Special
        elif key == K.Key_Return or key == K.Key_Enter:
            return b"\r"
        elif key == K.Key_Escape:
            return b"\x1b"
        elif key == K.Key_Backspace:
            return b"\x7f" if not ctrl else b"\x08"
        elif key == K.Key_Tab:
            return b"\x1b[Z" if shift else b"\t"

        # Function keys F1-F20
        fkey_map = {
            K.Key_F1:  b"\x1bOP",    K.Key_F2:  b"\x1bOQ",
            K.Key_F3:  b"\x1bOR",    K.Key_F4:  b"\x1bOS",
            K.Key_F5:  b"\x1b[15~",  K.Key_F6:  b"\x1b[17~",
            K.Key_F7:  b"\x1b[18~",  K.Key_F8:  b"\x1b[19~",
            K.Key_F9:  b"\x1b[20~",  K.Key_F10: b"\x1b[21~",
            K.Key_F11: b"\x1b[23~",  K.Key_F12: b"\x1b[24~",
        }
        if key in fkey_map:
            return fkey_map[key]

        return None

    # ─────────────────────────────────────────────
    # Mouse input
    # ─────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press - start selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            pos   = event.position().toPoint()
            r, c  = self._pixel_to_cell(pos)

            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Extend selection
                if self._sel_start:
                    self._sel_end = (r, c)
                    self.update()
                return

            self._sel_mode     = SEL_CHAR
            self._sel_start    = (r, c)
            self._sel_end      = (r, c)
            self._sel_dragging = True
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())

        elif event.button() == Qt.MouseButton.MiddleButton:
            self._paste_primary_selection()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Double click: select word."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos  = event.position().toPoint()
            r, c = self._pixel_to_cell(pos)
            start, end = self._find_word_bounds(r, c)
            self._sel_start = start
            self._sel_end   = end
            self._sel_mode  = SEL_WORD
            self._copy_selection(to_clipboard=False)
            self.update()

    def mouseTripleClickEvent(self, event: QMouseEvent):
        """Triple click: select line."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos  = event.position().toPoint()
            r, c = self._pixel_to_cell(pos)
            self._sel_start = (r, 0)
            self._sel_end   = (r, self._buffer.cols - 1)
            self._sel_mode  = SEL_LINE
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse drag - extend selection."""
        pos  = event.position().toPoint()
        r, c = self._pixel_to_cell(pos)

        if self._sel_dragging:
            self._sel_end = (r, c)
            self.update()

        # URL hover detection
        self._update_hover_url(r, c)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._sel_dragging = False
            if self._sel_start and self._sel_end:
                # Auto-copy on selection (like VS Code)
                sel_text = self._get_selection_text()
                if sel_text:
                    self.selection_changed.emit(sel_text)

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel - scroll buffer or send to shell."""
        delta = event.angleDelta().y()
        lines = max(1, abs(delta) // 40)

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Wheel: zoom
            if delta > 0:
                self.increase_font_size()
            else:
                self.decrease_font_size()
            return

        if self._buffer.scrollback_count > 0:
            if delta > 0:
                self._buffer.scroll_viewport_up(lines)
            else:
                self._buffer.scroll_viewport_down(lines)
            self.update()
        else:
            # Send scroll to shell (for mouse-aware apps like less)
            if delta > 0:
                self.write_to_pty(b"\x1b[A" * lines)
            else:
                self.write_to_pty(b"\x1b[B" * lines)

    def enterEvent(self, event):
        self._scroll_hover = True
        self.update()

    def leaveEvent(self, event):
        self._scroll_hover = False
        self._sel_dragging = False
        self.update()

    # ─────────────────────────────────────────────
    # Selection helpers
    # ─────────────────────────────────────────────

    def _pixel_to_cell(self, pos: QPoint) -> Tuple[int, int]:
        """Convert pixel coordinates to (row, col)."""
        col = (pos.x() - self._padding_h) // self._cell_w
        row = (pos.y() - self._padding_v) // self._cell_h
        col = max(0, min(col, self._buffer.cols - 1))
        row = max(0, min(row, self._buffer.rows - 1))
        return row, col

    def _find_word_bounds(self, row: int, col: int) -> Tuple[Tuple[int,int], Tuple[int,int]]:
        """Find word boundaries at (row, col)."""
        line = self._buffer.grid[row] if row < self._buffer.rows else None
        if not line:
            return (row, col), (row, col)

        text = line.to_text()
        if col >= len(text):
            return (row, col), (row, col)

        # Find word chars
        word_re = re.compile(r"\w")
        c = col

        # Expand left
        start = c
        while start > 0 and word_re.match(text[start - 1]):
            start -= 1

        # Expand right
        end = c
        while end < len(text) and word_re.match(text[end]):
            end += 1

        return (row, start), (row, end)

    def _get_selection_text(self) -> str:
        """Get the currently selected text."""
        if not self._sel_start or not self._sel_end:
            return ""

        start = self._sel_start
        end   = self._sel_end
        if start > end:
            start, end = end, start

        return self._buffer.get_text_range(
            start[0], start[1], end[0], end[1]
        )

    def _copy_selection(self, to_clipboard: bool = True):
        """Copy selection to clipboard."""
        text = self._get_selection_text()
        if text and to_clipboard:
            QApplication.clipboard().setText(text)

    def _paste(self):
        """Paste from clipboard."""
        text = QApplication.clipboard().text()
        if not text:
            return

        if self._buffer.bracketed_paste:
            data = b"\x1b[200~" + text.encode("utf-8") + b"\x1b[201~"
        else:
            data = text.encode("utf-8")

        self.write_to_pty(data)

    def _paste_primary_selection(self):
        """Middle-click paste from primary selection."""
        clipboard = QApplication.clipboard()
        text = clipboard.text(QClipboard.Mode.Selection)
        if text:
            self.write_to_pty(text.encode("utf-8"))

    # ─────────────────────────────────────────────
    # Resize handling
    # ─────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent):
        """Widget resized - debounce PTY resize."""
        super().resizeEvent(event)
        self._resize_timer.start()

    @pyqtSlot()
    def _do_resize(self):
        """Apply resize to buffer and PTY."""
        cols, rows = self._calc_grid_size()
        cols = max(self.MIN_COLS, cols)
        rows = max(self.MIN_ROWS, rows)

        if cols != self._buffer.cols or rows != self._buffer.rows:
            self._buffer.resize(cols, rows)
            if self._pty:
                self._pty.resize(cols, rows)
            self.update()

    def _calc_grid_size(self) -> Tuple[int, int]:
        """Calculate grid dimensions from widget size."""
        w = self.width()  - 2 * self._padding_h - self._scroll_bar_width
        h = self.height() - 2 * self._padding_v
        cols = max(self.MIN_COLS, w // self._cell_w)
        rows = max(self.MIN_ROWS, h // self._cell_h)
        return cols, rows

    def sizeHint(self) -> QSize:
        cols = 220
        rows = 50
        w = 2 * self._padding_h + cols * self._cell_w + self._scroll_bar_width
        h = 2 * self._padding_v + rows * self._cell_h
        return QSize(w, h)

    # ─────────────────────────────────────────────
    # Font size control
    # ─────────────────────────────────────────────

    def increase_font_size(self):
        self._font_size_pt = min(self._font_size_pt + 1, 72)
        self._rebuild_fonts()
        self._buffer.mark_all_dirty()
        self.update()

    def decrease_font_size(self):
        self._font_size_pt = max(self._font_size_pt - 1, 6)
        self._rebuild_fonts()
        self._buffer.mark_all_dirty()
        self.update()

    def reset_font_size(self):
        self._font_size_pt = 13
        self._rebuild_fonts()
        self._buffer.mark_all_dirty()
        self.update()

    def set_font(self, family: str = None, size: int = None):
        """Set font family and/or size."""
        if family:
            self._font_family = family
        if size:
            self._font_size_pt = size
        self._rebuild_fonts()
        self._buffer.mark_all_dirty()
        self.update()

    # ─────────────────────────────────────────────
    # Theme
    # ─────────────────────────────────────────────

    def set_theme(self, theme: TerminalTheme):
        """Apply a new color theme."""
        self.theme = theme
        self._init_colors()
        self._buffer.mark_all_dirty()
        self.update()

    # ─────────────────────────────────────────────
    # URL hover
    # ─────────────────────────────────────────────

    def _update_hover_url(self, row: int, col: int):
        """Check if mouse is over a URL."""
        cell = self._buffer.get_cell(row, col)
        if cell.attrs.url and cell.attrs.url != self._hovered_url:
            self._hovered_url = cell.attrs.url
            self.url_hovered.emit(cell.attrs.url)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif not cell.attrs.url and self._hovered_url:
            self._hovered_url = None
            self.url_hovered.emit("")
            self.setCursor(Qt.CursorShape.IBeamCursor)

    # ─────────────────────────────────────────────
    # Find / search
    # ─────────────────────────────────────────────

    def find(self, query: str, case_sensitive: bool = False,
             regex: bool = False) -> int:
        """Search visible content for query. Returns match count."""
        self._find_results.clear()
        self._find_current = -1

        if not query:
            self.update()
            return 0

        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            pattern = re.compile(query if regex else re.escape(query), flags)
        except re.error:
            return 0

        for r in range(self._buffer.rows):
            line = self._buffer.grid[r]
            text = line.to_text()
            for m in pattern.finditer(text):
                self._find_results.append((r, m.start(), r, m.end()))

        if self._find_results:
            self._find_current = 0

        self.update()
        return len(self._find_results)

    def find_next(self):
        """Jump to next find result."""
        if self._find_results:
            self._find_current = (self._find_current + 1) % len(self._find_results)
            self.update()

    def find_prev(self):
        """Jump to previous find result."""
        if self._find_results:
            self._find_current = (self._find_current - 1) % len(self._find_results)
            self.update()

    def clear_find(self):
        """Clear search highlights."""
        self._find_results.clear()
        self._find_current = -1
        self.update()

    # ─────────────────────────────────────────────
    # Context menu
    # ─────────────────────────────────────────────

    def _show_context_menu(self, global_pos):
        """Show right-click context menu."""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(self._context_menu_style())

        copy_action  = menu.addAction("Copy")
        paste_action = menu.addAction("Paste")
        menu.addSeparator()
        select_all   = menu.addAction("Select All")
        menu.addSeparator()
        clear_action = menu.addAction("Clear")

        copy_action.setEnabled(bool(self._get_selection_text()))
        copy_action.setShortcut("Ctrl+Shift+C")
        paste_action.setShortcut("Ctrl+Shift+V")

        action = menu.exec(global_pos)
        if action == copy_action:
            self._copy_selection()
        elif action == paste_action:
            self._paste()
        elif action == select_all:
            self._sel_start = (0, 0)
            self._sel_end   = (self._buffer.rows - 1, self._buffer.cols - 1)
            self.update()
        elif action == clear_action:
            self._buffer._erase_display(2)
            self._buffer.cursor.row = 0
            self._buffer.cursor.col = 0
            self.update()

    def _context_menu_style(self) -> str:
        t = self.theme
        return f"""
            QMenu {{
                background-color: {t.tab_bar_bg};
                color: {t.foreground};
                border: 1px solid {t.panel_border};
                border-radius: 4px;
                padding: 4px 0px;
                font-family: 'Segoe UI', 'SF Pro Text', system-ui, sans-serif;
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 6px 20px 6px 12px;
                border-radius: 2px;
                margin: 1px 4px;
            }}
            QMenu::item:selected {{
                background-color: {t.input_border};
                color: white;
            }}
            QMenu::item:disabled {{
                color: {t.tab_inactive_fg};
            }}
            QMenu::separator {{
                height: 1px;
                background: {t.panel_border};
                margin: 4px 0px;
            }}
        """

    # ─────────────────────────────────────────────
    # Drag & drop
    # ─────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = " ".join(
                f'"{url.toLocalFile()}"'
                for url in event.mimeData().urls()
                if url.isLocalFile()
            )
            if paths:
                self.write_to_pty(paths.encode("utf-8"))
        elif event.mimeData().hasText():
            self.write_to_pty(event.mimeData().text().encode("utf-8"))

    # ─────────────────────────────────────────────
    # IME support
    # ─────────────────────────────────────────────

    def inputMethodEvent(self, event):
        """Handle IME input for CJK / complex scripts."""
        if event.commitString():
            self.write_to_pty(event.commitString().encode("utf-8"))

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            row = self._buffer.cursor.row
            col = self._buffer.cursor.col
            x   = self._padding_h + col * self._cell_w
            y   = self._padding_v + row * self._cell_h
            return QRect(x, y, self._cell_w, self._cell_h)
        return super().inputMethodQuery(query)

    # ─────────────────────────────────────────────
    # Focus events
    # ─────────────────────────────────────────────

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._cursor_blink_on = True
        self._blink_timer.start(CURSOR_BLINK_ON)
        # Repaint cursor area
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Show unfocused cursor (outline only)
        self.update()
