"""
core/terminal_buffer.py
========================
Terminal screen buffer implementation.

Manages a 2D grid of character cells (ScreenCell), handling:
  - Cursor positioning and movement
  - Screen scrolling with configurable scroll region
  - Alternate screen buffer (for vi, less, etc.)
  - Line insertion/deletion
  - Character cell attributes (SGR)
  - Scrollback buffer
  - Selection regions
  - Double-width (CJK) character support
  - Dirty tracking for efficient repainting
"""

import unicodedata
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Set
from copy import deepcopy

from core.ansi_parser import (
    TextAttributes, Color, ColorType,
    ParserEvent, ParserEventType,
    SGRProcessor, ANSIParser
)


# ─────────────────────────────────────────────────────────────────────────────
# Screen Cell
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScreenCell:
    """
    A single character cell in the terminal grid.
    
    char:   The displayed character (may be empty '' for wide char continuation)
    attrs:  SGR text attributes
    wide:   True if this is a CJK/wide character (occupies 2 columns)
    placeholder: True if this cell is the right half of a wide char
    """
    char:        str           = " "
    attrs:       TextAttributes = field(default_factory=TextAttributes)
    wide:        bool          = False
    placeholder: bool          = False

    def clone(self) -> "ScreenCell":
        c = ScreenCell()
        c.char        = self.char
        c.attrs       = self.attrs.copy()
        c.wide        = self.wide
        c.placeholder = self.placeholder
        return c

    def is_blank(self) -> bool:
        return self.char in (" ", "") and self.attrs.bg.is_default()

    def clear(self, attrs: Optional[TextAttributes] = None):
        self.char        = " "
        self.attrs       = attrs.copy() if attrs else TextAttributes()
        self.wide        = False
        self.placeholder = False


def _char_width(c: str) -> int:
    """Return display width of a character (1 or 2)."""
    if not c:
        return 0
    try:
        east = unicodedata.east_asian_width(c)
        return 2 if east in ("W", "F") else 1
    except Exception:
        return 1


# ─────────────────────────────────────────────────────────────────────────────
# Screen Line
# ─────────────────────────────────────────────────────────────────────────────

class ScreenLine:
    """A single row in the terminal buffer."""

    def __init__(self, cols: int):
        self.cols = cols
        self.cells: List[ScreenCell] = [ScreenCell() for _ in range(cols)]
        self.dirty = True
        self.wrapped = False  # Line was soft-wrapped

    def get(self, col: int) -> ScreenCell:
        if 0 <= col < self.cols:
            return self.cells[col]
        return ScreenCell()

    def set(self, col: int, cell: ScreenCell):
        if 0 <= col < self.cols:
            self.cells[col] = cell
            self.dirty = True

    def clear_range(self, start: int, end: int, attrs: Optional[TextAttributes] = None):
        """Clear cells from start to end (exclusive)."""
        for col in range(max(0, start), min(end, self.cols)):
            self.cells[col].clear(attrs)
        self.dirty = True

    def clear_all(self, attrs: Optional[TextAttributes] = None):
        self.clear_range(0, self.cols, attrs)
        self.dirty = True

    def to_text(self) -> str:
        """Extract plain text from line."""
        parts = []
        for cell in self.cells:
            if not cell.placeholder:
                parts.append(cell.char)
        return "".join(parts).rstrip()

    def clone(self) -> "ScreenLine":
        line = ScreenLine(self.cols)
        line.cells   = [c.clone() for c in self.cells]
        line.wrapped  = self.wrapped
        line.dirty    = True
        return line

    def resize(self, new_cols: int, fill_attrs: Optional[TextAttributes] = None):
        """Resize line to new column count."""
        if new_cols > self.cols:
            while len(self.cells) < new_cols:
                self.cells.append(ScreenCell())
        elif new_cols < self.cols:
            self.cells = self.cells[:new_cols]
        self.cols  = new_cols
        self.dirty = True


# ─────────────────────────────────────────────────────────────────────────────
# Cursor
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Cursor:
    row:       int  = 0
    col:       int  = 0
    visible:   bool = True
    blink:     bool = True
    style:     int  = 1    # DECSCUSR: 1=block, 3=bar, 5=underline
    origin:    bool = False # Origin mode (DECOM)

    def clone(self) -> "Cursor":
        return Cursor(self.row, self.col, self.visible, self.blink,
                      self.style, self.origin)

    def save(self) -> dict:
        return {
            "row":    self.row,
            "col":    self.col,
            "visible": self.visible,
            "style":  self.style,
            "origin": self.origin,
        }

    def restore(self, saved: dict):
        self.row    = saved.get("row",    0)
        self.col    = saved.get("col",    0)
        self.visible = saved.get("visible", True)
        self.style  = saved.get("style",  1)
        self.origin = saved.get("origin", False)


# ─────────────────────────────────────────────────────────────────────────────
# Screen Buffer
# ─────────────────────────────────────────────────────────────────────────────

class ScreenBuffer:
    """
    The main terminal screen buffer.
    
    Implements VT220/xterm behavior including:
    - Primary and alternate screen
    - Scrollback history
    - Scroll regions
    - Insert/delete lines/chars
    - Character attributes
    """

    MAX_SCROLLBACK = 50_000   # Maximum scrollback lines

    def __init__(self, cols: int = 220, rows: int = 50):
        self.cols = cols
        self.rows = rows

        # Primary screen
        self._primary_grid:   List[ScreenLine] = self._make_grid(rows)
        self._primary_cursor: Cursor            = Cursor()
        self._primary_saved:  Optional[dict]    = None

        # Alternate screen (for full-screen apps like vim)
        self._alt_grid:       List[ScreenLine] = self._make_grid(rows)
        self._alt_cursor:     Cursor            = Cursor()
        self._alt_active:     bool              = False

        # Active references (point to primary or alt)
        self.grid   = self._primary_grid
        self.cursor = self._primary_cursor

        # Scrollback (primary screen only)
        self._scrollback: List[ScreenLine] = []
        self._scroll_offset: int = 0  # 0 = at bottom, positive = scrolled up

        # Scroll region [top, bottom] (1-indexed row numbers, inclusive)
        self._scroll_top:    int = 1
        self._scroll_bottom: int = rows

        # Modes
        self.insert_mode:     bool = False
        self.auto_wrap:       bool = True
        self.bracketed_paste: bool = False
        self.origin_mode:     bool = False

        # SGR state
        self._sgr = SGRProcessor()
        self._saved_sgr: Optional[TextAttributes] = None

        # Saved cursor (per-screen)
        self._saved_cursor: Optional[dict] = None

        # Dirty tracking
        self.dirty_rows:    Set[int] = set(range(rows))
        self.title: str = ""

        # Tab stops (default every 8 columns)
        self._tab_stops: Set[int] = set(range(0, cols, 8))

    # ─────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────

    @property
    def alt_active(self) -> bool:
        return self._alt_active

    @property
    def scroll_top(self) -> int:
        return self._scroll_top - 1  # 0-indexed

    @property
    def scroll_bottom(self) -> int:
        return self._scroll_bottom - 1  # 0-indexed

    @property
    def total_rows(self) -> int:
        """Total rows including scrollback."""
        return len(self._scrollback) + self.rows

    @property
    def scrollback_count(self) -> int:
        return len(self._scrollback)

    # ─────────────────────────────────────────────
    # Resize
    # ─────────────────────────────────────────────

    def resize(self, new_cols: int, new_rows: int):
        """Resize the terminal buffer."""
        old_rows = self.rows
        old_cols = self.cols

        self.cols = new_cols
        self.rows = new_rows

        # Resize all grids
        for grid in (self._primary_grid, self._alt_grid):
            for line in grid:
                line.resize(new_cols)
            # Add or remove rows
            while len(grid) < new_rows:
                grid.append(ScreenLine(new_cols))
            while len(grid) > new_rows:
                grid.pop()

        # Resize scrollback
        for line in self._scrollback:
            line.resize(new_cols)

        # Clamp cursor
        self._primary_cursor.row = min(self._primary_cursor.row, new_rows - 1)
        self._primary_cursor.col = min(self._primary_cursor.col, new_cols - 1)
        self._alt_cursor.row     = min(self._alt_cursor.row,     new_rows - 1)
        self._alt_cursor.col     = min(self._alt_cursor.col,     new_cols - 1)

        # Reset scroll region if it was full screen
        if self._scroll_top == 1 and self._scroll_bottom == old_rows:
            self._scroll_top    = 1
            self._scroll_bottom = new_rows

        self._scroll_bottom = min(self._scroll_bottom, new_rows)

        # Rebuild tab stops
        self._tab_stops = set(range(0, new_cols, 8))

        self.dirty_rows = set(range(new_rows))

    # ─────────────────────────────────────────────
    # Event processing (main entry point)
    # ─────────────────────────────────────────────

    def process_event(self, event: ParserEvent):
        """Apply a parsed terminal event to the buffer state."""
        t = event.type

        if   t == ParserEventType.PRINT:             self._do_print(event.text)
        elif t == ParserEventType.LINEFEED:          self._do_linefeed()
        elif t == ParserEventType.CARRIAGE_RETURN:   self._do_cr()
        elif t == ParserEventType.BACKSPACE:         self._do_backspace()
        elif t == ParserEventType.TAB:               self._do_tab(event.params[0] if event.params else 1)
        elif t == ParserEventType.BELL:              pass  # handled by UI

        elif t == ParserEventType.CURSOR_UP:         self._move_cursor_relative(-event.params[0], 0)
        elif t == ParserEventType.CURSOR_DOWN:       self._move_cursor_relative( event.params[0], 0)
        elif t == ParserEventType.CURSOR_FORWARD:    self._move_cursor_relative(0,  event.params[0])
        elif t == ParserEventType.CURSOR_BACKWARD:   self._move_cursor_relative(0, -event.params[0])
        elif t == ParserEventType.CURSOR_NEXT_LINE:
            self._move_cursor_relative(event.params[0], 0)
            self.cursor.col = 0
        elif t == ParserEventType.CURSOR_PREV_LINE:
            self._move_cursor_relative(-event.params[0], 0)
            self.cursor.col = 0
        elif t == ParserEventType.CURSOR_COLUMN:
            self.cursor.col = max(0, min(event.params[0] - 1, self.cols - 1))
        elif t == ParserEventType.CURSOR_POSITION:
            self._set_cursor(event.params[0] - 1, event.params[1] - 1)
        elif t == ParserEventType.CURSOR_SAVE:       self._save_cursor()
        elif t == ParserEventType.CURSOR_RESTORE:    self._restore_cursor()
        elif t == ParserEventType.CURSOR_STYLE:
            self.cursor.style = event.params[0] if event.params else 1

        elif t == ParserEventType.ERASE_IN_DISPLAY:  self._erase_display(event.params[0] if event.params else 0)
        elif t == ParserEventType.ERASE_IN_LINE:     self._erase_line(event.params[0] if event.params else 0)
        elif t == ParserEventType.ERASE_CHARS:       self._erase_chars(event.params[0] if event.params else 1)

        elif t == ParserEventType.SCROLL_UP:         self._scroll_up(event.params[0] if event.params else 1)
        elif t == ParserEventType.SCROLL_DOWN:       self._scroll_down(event.params[0] if event.params else 1)
        elif t == ParserEventType.SET_SCROLLREGION:  self._set_scroll_region(event.params)

        elif t == ParserEventType.INSERT_LINES:      self._insert_lines(event.params[0] if event.params else 1)
        elif t == ParserEventType.DELETE_LINES:      self._delete_lines(event.params[0] if event.params else 1)
        elif t == ParserEventType.INSERT_CHARS:      self._insert_chars(event.params[0] if event.params else 1)
        elif t == ParserEventType.DELETE_CHARS:      self._delete_chars(event.params[0] if event.params else 1)

        elif t == ParserEventType.SGR:               self._sgr.apply(event)

        elif t == ParserEventType.ALT_SCREEN_ON:     self._enter_alt_screen()
        elif t == ParserEventType.ALT_SCREEN_OFF:    self._exit_alt_screen()
        elif t == ParserEventType.BRACKETED_PASTE_ON:  self.bracketed_paste = True
        elif t == ParserEventType.BRACKETED_PASTE_OFF: self.bracketed_paste = False

        elif t == ParserEventType.WINDOW_TITLE:      self.title = event.text
        elif t == ParserEventType.HYPERLINK:
            self._sgr.attrs.url = event.text or None

        elif t == ParserEventType.INDEX:             self._index()
        elif t == ParserEventType.REVERSE_INDEX:     self._reverse_index()
        elif t == ParserEventType.NEXT_LINE_CTRL:
            self._do_linefeed()
            self.cursor.col = 0

        elif t == ParserEventType.RESET:             self._full_reset()
        elif t == ParserEventType.SOFT_RESET:        self._soft_reset()

        elif t == ParserEventType.HORIZONTAL_TAB_SET:
            self._tab_stops.add(self.cursor.col)
        elif t == ParserEventType.TAB_CLEAR:
            param = event.params[0] if event.params else 0
            if param == 0:
                self._tab_stops.discard(self.cursor.col)
            elif param == 3:
                self._tab_stops.clear()

        elif t == ParserEventType.PRIVATE_MODE_SET:
            self._set_private_mode(event.params, True)
        elif t == ParserEventType.PRIVATE_MODE_RESET:
            self._set_private_mode(event.params, False)

    # ─────────────────────────────────────────────
    # Print / write characters
    # ─────────────────────────────────────────────

    def _do_print(self, text: str):
        """Write printable characters to the buffer at cursor position."""
        attrs = self._sgr.current()

        for ch in text:
            width = _char_width(ch)
            col   = self.cursor.col
            row   = self.cursor.row

            if col >= self.cols:
                if self.auto_wrap:
                    self._do_cr()
                    self._do_linefeed()
                    col = self.cursor.col
                    row = self.cursor.row
                else:
                    col = self.cols - 1
                    self.cursor.col = col

            line = self.grid[row]

            # Handle wide character
            if width == 2 and col + 1 < self.cols:
                cell = ScreenCell(ch, attrs.copy(), wide=True)
                line.set(col, cell)
                placeholder = ScreenCell("", attrs.copy(), placeholder=True)
                line.set(col + 1, placeholder)
                self.cursor.col = col + 2
            elif width == 2:
                # No room for wide char, write space
                cell = ScreenCell(" ", attrs.copy())
                line.set(col, cell)
                self.cursor.col = col + 1
            else:
                cell = ScreenCell(ch, attrs.copy())
                line.set(col, cell)
                self.cursor.col = col + 1

            self.dirty_rows.add(row)

    # ─────────────────────────────────────────────
    # Cursor control
    # ─────────────────────────────────────────────

    def _do_linefeed(self):
        """Process LF - scroll if at bottom of scroll region."""
        if self.cursor.row == self.scroll_bottom:
            self._scroll_up(1)
        else:
            self.cursor.row = min(self.cursor.row + 1, self.rows - 1)

    def _do_cr(self):
        """Process CR - move to column 0."""
        self.cursor.col = 0

    def _do_backspace(self):
        """Process BS."""
        if self.cursor.col > 0:
            self.cursor.col -= 1

    def _do_tab(self, count: int = 1):
        """Process HT - advance to next tab stop."""
        if count > 0:
            for _ in range(count):
                next_stop = self.cols - 1
                for stop in sorted(self._tab_stops):
                    if stop > self.cursor.col:
                        next_stop = stop
                        break
                self.cursor.col = min(next_stop, self.cols - 1)
        elif count < 0:
            # Backwards tab
            for _ in range(-count):
                prev_stop = 0
                for stop in sorted(self._tab_stops, reverse=True):
                    if stop < self.cursor.col:
                        prev_stop = stop
                        break
                self.cursor.col = max(prev_stop, 0)

    def _set_cursor(self, row: int, col: int):
        """Move cursor to absolute position (0-indexed)."""
        top = self.scroll_top if self.origin_mode else 0
        self.cursor.row = max(top, min(row + top if self.origin_mode else row, self.rows - 1))
        self.cursor.col = max(0, min(col, self.cols - 1))

    def _move_cursor_relative(self, dr: int, dc: int):
        """Move cursor by relative amount, clamped to screen."""
        self.cursor.row = max(0, min(self.cursor.row + dr, self.rows - 1))
        self.cursor.col = max(0, min(self.cursor.col + dc, self.cols - 1))

    def _save_cursor(self):
        self._saved_cursor = self.cursor.save()
        self._saved_sgr    = self._sgr.current()

    def _restore_cursor(self):
        if self._saved_cursor:
            self.cursor.restore(self._saved_cursor)
        if self._saved_sgr:
            self._sgr.attrs = self._saved_sgr.copy()

    # ─────────────────────────────────────────────
    # Erase
    # ─────────────────────────────────────────────

    def _erase_display(self, mode: int):
        """ED - Erase in display."""
        attrs = self._sgr.current()
        row, col = self.cursor.row, self.cursor.col

        if mode == 0:  # Cursor to end
            self.grid[row].clear_range(col, self.cols, attrs)
            self.dirty_rows.add(row)
            for r in range(row + 1, self.rows):
                self.grid[r].clear_all(attrs)
                self.dirty_rows.add(r)

        elif mode == 1:  # Start to cursor
            for r in range(row):
                self.grid[r].clear_all(attrs)
                self.dirty_rows.add(r)
            self.grid[row].clear_range(0, col + 1, attrs)
            self.dirty_rows.add(row)

        elif mode == 2:  # Entire screen
            for r in range(self.rows):
                self.grid[r].clear_all(attrs)
                self.dirty_rows.add(r)

        elif mode == 3:  # Entire screen + scrollback
            for r in range(self.rows):
                self.grid[r].clear_all(attrs)
                self.dirty_rows.add(r)
            self._scrollback.clear()

    def _erase_line(self, mode: int):
        """EL - Erase in line."""
        attrs = self._sgr.current()
        row, col = self.cursor.row, self.cursor.col

        if   mode == 0: self.grid[row].clear_range(col, self.cols, attrs)
        elif mode == 1: self.grid[row].clear_range(0, col + 1, attrs)
        elif mode == 2: self.grid[row].clear_all(attrs)

        self.dirty_rows.add(row)

    def _erase_chars(self, count: int):
        """ECH - Erase characters."""
        attrs = self._sgr.current()
        row, col = self.cursor.row, self.cursor.col
        self.grid[row].clear_range(col, col + count, attrs)
        self.dirty_rows.add(row)

    # ─────────────────────────────────────────────
    # Scrolling
    # ─────────────────────────────────────────────

    def _scroll_up(self, count: int = 1):
        """Scroll content up within scroll region, adding blank lines at bottom."""
        top    = self.scroll_top
        bottom = self.scroll_bottom
        attrs  = self._sgr.current()

        for _ in range(count):
            # Move top line to scrollback (primary screen only)
            if not self._alt_active:
                scrollback_line = self.grid[top].clone()
                self._scrollback.append(scrollback_line)
                if len(self._scrollback) > self.MAX_SCROLLBACK:
                    self._scrollback.pop(0)

            # Shift lines up
            for r in range(top, bottom):
                self.grid[r] = self.grid[r + 1]
                self.dirty_rows.add(r)

            # New blank line at bottom
            self.grid[bottom] = ScreenLine(self.cols)
            self.dirty_rows.add(bottom)

    def _scroll_down(self, count: int = 1):
        """Scroll content down within scroll region, adding blank lines at top."""
        top    = self.scroll_top
        bottom = self.scroll_bottom
        attrs  = self._sgr.current()

        for _ in range(count):
            # Shift lines down
            for r in range(bottom, top, -1):
                self.grid[r] = self.grid[r - 1]
                self.dirty_rows.add(r)

            # New blank line at top
            self.grid[top] = ScreenLine(self.cols)
            self.dirty_rows.add(top)

    def _set_scroll_region(self, params: List[int]):
        """DECSTBM - Set top and bottom margins."""
        top    = params[0] if len(params) > 0 else 1
        bottom = params[1] if len(params) > 1 else self.rows

        top    = max(1, top)
        bottom = min(bottom, self.rows)

        if top < bottom:
            self._scroll_top    = top
            self._scroll_bottom = bottom
            # Reset cursor to home
            self._set_cursor(0, 0)

    def _index(self):
        """IND - Index (like LF but always scroll)."""
        self._do_linefeed()

    def _reverse_index(self):
        """RI - Reverse index (scroll down if at top of region)."""
        if self.cursor.row == self.scroll_top:
            self._scroll_down(1)
        else:
            self.cursor.row = max(0, self.cursor.row - 1)

    # ─────────────────────────────────────────────
    # Insert / delete
    # ─────────────────────────────────────────────

    def _insert_lines(self, count: int):
        """IL - Insert lines at cursor row."""
        row    = self.cursor.row
        bottom = self.scroll_bottom
        attrs  = self._sgr.current()

        for _ in range(min(count, bottom - row + 1)):
            # Remove bottom line of scroll region
            self.grid.pop(bottom)
            # Insert new blank line at cursor row
            self.grid.insert(row, ScreenLine(self.cols))

        for r in range(row, bottom + 1):
            self.dirty_rows.add(r)

    def _delete_lines(self, count: int):
        """DL - Delete lines at cursor row."""
        row    = self.cursor.row
        bottom = self.scroll_bottom
        attrs  = self._sgr.current()

        for _ in range(min(count, bottom - row + 1)):
            self.grid.pop(row)
            self.grid.insert(bottom, ScreenLine(self.cols))

        for r in range(row, bottom + 1):
            self.dirty_rows.add(r)

    def _insert_chars(self, count: int):
        """ICH - Insert characters at cursor position."""
        row  = self.cursor.row
        col  = self.cursor.col
        line = self.grid[row]
        # Shift right, dropping chars that fall off the right edge
        for c in range(self.cols - 1, col + count - 1, -1):
            if c - count >= col:
                line.cells[c] = line.cells[c - count].clone()
        for c in range(col, min(col + count, self.cols)):
            line.cells[c].clear()
        self.dirty_rows.add(row)

    def _delete_chars(self, count: int):
        """DCH - Delete characters at cursor position."""
        row  = self.cursor.row
        col  = self.cursor.col
        line = self.grid[row]
        for c in range(col, self.cols):
            if c + count < self.cols:
                line.cells[c] = line.cells[c + count].clone()
            else:
                line.cells[c].clear()
        self.dirty_rows.add(row)

    # ─────────────────────────────────────────────
    # Alternate screen
    # ─────────────────────────────────────────────

    def _enter_alt_screen(self):
        if self._alt_active:
            return
        self._alt_active  = True
        self.grid         = self._alt_grid
        self.cursor       = self._alt_cursor
        # Clear alt screen
        for r in range(self.rows):
            self.grid[r].clear_all()
            self.dirty_rows.add(r)

    def _exit_alt_screen(self):
        if not self._alt_active:
            return
        self._alt_active = False
        self.grid        = self._primary_grid
        self.cursor      = self._primary_cursor
        self.dirty_rows  = set(range(self.rows))

    # ─────────────────────────────────────────────
    # Private modes
    # ─────────────────────────────────────────────

    def _set_private_mode(self, params: List[int], value: bool):
        for mode in params:
            if   mode == 1:    pass           # DECCKM (cursor keys)
            elif mode == 7:    self.auto_wrap = value
            elif mode == 12:   self.cursor.blink = value
            elif mode == 25:   self.cursor.visible = value
            elif mode == 6:    self.origin_mode = value
            elif mode == 4:    self.insert_mode = value
            # 1049 handled by parser → ALT_SCREEN events

    # ─────────────────────────────────────────────
    # Reset
    # ─────────────────────────────────────────────

    def _full_reset(self):
        """RIS - Full terminal reset."""
        self._exit_alt_screen()
        self.cursor = Cursor()
        self._sgr.reset()
        self._scroll_top    = 1
        self._scroll_bottom = self.rows
        self.auto_wrap      = True
        self.insert_mode    = False
        self.origin_mode    = False
        self._tab_stops     = set(range(0, self.cols, 8))
        self._saved_cursor  = None
        for r in range(self.rows):
            self.grid[r].clear_all()
            self.dirty_rows.add(r)

    def _soft_reset(self):
        """DECSTR - Soft reset."""
        self.cursor.visible = True
        self.cursor.blink   = True
        self.insert_mode    = False
        self.origin_mode    = False
        self._sgr.reset()
        self._scroll_top    = 1
        self._scroll_bottom = self.rows

    # ─────────────────────────────────────────────
    # Public accessors
    # ─────────────────────────────────────────────

    def get_cell(self, row: int, col: int) -> ScreenCell:
        """Get cell from current grid."""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.grid[row].cells[col]
        return ScreenCell()

    def get_scrollback_line(self, idx: int) -> Optional[ScreenLine]:
        """Get a scrollback line by index (0 = oldest)."""
        if 0 <= idx < len(self._scrollback):
            return self._scrollback[idx]
        return None

    def get_text_range(self, start_row: int, start_col: int,
                       end_row: int, end_col: int) -> str:
        """Extract text from a rectangular region."""
        parts = []
        for r in range(start_row, end_row + 1):
            if r < 0 or r >= self.rows:
                continue
            col_start = start_col if r == start_row else 0
            col_end   = end_col   if r == end_row   else self.cols
            line = self.grid[r]
            for c in range(col_start, col_end):
                if c < self.cols and not line.cells[c].placeholder:
                    parts.append(line.cells[c].char)
            if r < end_row:
                parts.append("\n")
        return "".join(parts)

    def take_dirty(self) -> Set[int]:
        """Return dirty row set and clear it."""
        dirty = self.dirty_rows.copy()
        self.dirty_rows.clear()
        return dirty

    def mark_all_dirty(self):
        """Force full repaint."""
        self.dirty_rows = set(range(self.rows))

    # ─────────────────────────────────────────────
    # Scrollback viewport
    # ─────────────────────────────────────────────

    def scroll_viewport_up(self, lines: int = 3):
        """Scroll the viewport up (show older output)."""
        self._scroll_offset = min(
            self._scroll_offset + lines,
            len(self._scrollback)
        )
        self.mark_all_dirty()

    def scroll_viewport_down(self, lines: int = 3):
        """Scroll the viewport down (show newer output)."""
        self._scroll_offset = max(0, self._scroll_offset - lines)
        self.mark_all_dirty()

    def scroll_viewport_to_bottom(self):
        """Jump to bottom of output."""
        self._scroll_offset = 0
        self.mark_all_dirty()

    @property
    def scroll_offset(self) -> int:
        return self._scroll_offset

    def get_visible_line(self, screen_row: int) -> Optional[ScreenLine]:
        """
        Get the ScreenLine visible at screen_row (0-indexed),
        taking scrollback offset into account.
        """
        if self._scroll_offset == 0:
            return self.grid[screen_row] if 0 <= screen_row < self.rows else None

        # Calculate which line from scrollback+screen to show
        total = len(self._scrollback)
        virtual_row = screen_row + (total - self._scroll_offset)

        if virtual_row < 0:
            return None
        elif virtual_row < total:
            return self._scrollback[virtual_row]
        else:
            grid_row = virtual_row - total
            if 0 <= grid_row < self.rows:
                return self.grid[grid_row]
        return None

    # ─────────────────────────────────────────────
    # Factory helpers
    # ─────────────────────────────────────────────

    def _make_grid(self, rows: int) -> List[ScreenLine]:
        return [ScreenLine(self.cols) for _ in range(rows)]
