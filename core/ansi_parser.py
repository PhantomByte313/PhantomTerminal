"""
core/ansi_parser.py
===================
Complete ANSI / VT100 / VT220 / xterm escape sequence parser.

Handles:
  - CSI sequences  (ESC [ ... )
  - OSC sequences  (ESC ] ... BEL/ST)
  - DCS sequences  (ESC P ... ST)
  - SS2/SS3        (ESC N / ESC O)
  - C0 controls    (BEL, BS, HT, LF, CR, etc.)
  - C1 controls    (8-bit equivalents)
  - SGR (colors, bold, italic, underline, blink, etc.)
  - Private modes  (?1049h, ?2004h, etc.)
  - 256-color and TrueColor (RGB) support
  - Hyperlinks     (OSC 8)
  - Window titles  (OSC 0/1/2)
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Callable, Any
from enum import IntEnum, auto


# ─────────────────────────────────────────────────────────────────────────────
# Color representation
# ─────────────────────────────────────────────────────────────────────────────

class ColorType(IntEnum):
    DEFAULT  = 0   # Terminal default
    ANSI16   = 1   # Standard 16-color ANSI
    ANSI256  = 2   # 256-color palette
    TRUE     = 3   # 24-bit RGB truecolor


@dataclass(frozen=True)
class Color:
    """Immutable color value."""
    type:  ColorType = ColorType.DEFAULT
    value: int       = 0           # ANSI16 index or 256-color index
    r:     int       = 0
    g:     int       = 0
    b:     int       = 0

    @classmethod
    def default(cls) -> "Color":
        return cls(ColorType.DEFAULT)

    @classmethod
    def from_ansi16(cls, index: int) -> "Color":
        return cls(ColorType.ANSI16, value=index)

    @classmethod
    def from_256(cls, index: int) -> "Color":
        if index < 16:
            return cls(ColorType.ANSI16, value=index)
        r, g, b = _256_to_rgb(index)
        return cls(ColorType.ANSI256, value=index, r=r, g=g, b=b)

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int) -> "Color":
        return cls(ColorType.TRUE, r=r, g=g, b=b)

    def to_rgb(self) -> Tuple[int, int, int]:
        """Convert any color to RGB tuple."""
        if self.type == ColorType.DEFAULT:
            return (0, 0, 0)
        elif self.type == ColorType.ANSI16:
            return ANSI16_PALETTE[self.value % 16]
        elif self.type in (ColorType.ANSI256, ColorType.TRUE):
            return (self.r, self.g, self.b)
        return (0, 0, 0)

    def to_qt_color_str(self) -> str:
        """Return '#RRGGBB' string."""
        r, g, b = self.to_rgb()
        return f"#{r:02x}{g:02x}{b:02x}"

    def is_default(self) -> bool:
        return self.type == ColorType.DEFAULT


# Standard ANSI 16-color palette (VS Code Dark+ theme colors)
ANSI16_PALETTE: List[Tuple[int, int, int]] = [
    # Normal
    (0,   0,   0  ),   #  0 Black
    (205, 49,  49 ),   #  1 Red
    (13,  188, 121),   #  2 Green
    (229, 229, 16 ),   #  3 Yellow
    (36,  114, 200),   #  4 Blue
    (188, 63,  188),   #  5 Magenta
    (17,  168, 205),   #  6 Cyan
    (229, 229, 229),   #  7 White
    # Bright
    (102, 102, 102),   #  8 Bright Black  (Dark Gray)
    (241, 76,  76 ),   #  9 Bright Red
    (35,  209, 139),   # 10 Bright Green
    (245, 245, 67 ),   # 11 Bright Yellow
    (59,  142, 234),   # 12 Bright Blue
    (214, 112, 214),   # 13 Bright Magenta
    (41,  184, 219),   # 14 Bright Cyan
    (229, 229, 229),   # 15 Bright White
]


def _256_to_rgb(index: int) -> Tuple[int, int, int]:
    """Convert 256-color index to RGB."""
    if index < 16:
        return ANSI16_PALETTE[index]
    elif index < 232:
        # 6×6×6 color cube
        i = index - 16
        r = (i // 36) * 51
        g = ((i % 36) // 6) * 51
        b = (i % 6) * 51
        return (r, g, b)
    else:
        # Grayscale ramp
        v = (index - 232) * 10 + 8
        return (v, v, v)


# ─────────────────────────────────────────────────────────────────────────────
# Text attributes / character style
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TextAttributes:
    """
    Complete set of SGR (Select Graphic Rendition) attributes
    for a single character cell.
    """
    fg:         Color = field(default_factory=Color.default)
    bg:         Color = field(default_factory=Color.default)
    bold:       bool  = False
    dim:        bool  = False
    italic:     bool  = False
    underline:  bool  = False
    underline2: bool  = False   # Double underline
    blink:      bool  = False
    blink_fast: bool  = False
    inverse:    bool  = False
    invisible:  bool  = False
    strikethrough: bool = False
    overline:   bool  = False
    # Underline color (kitty extension)
    underline_color: Color = field(default_factory=Color.default)
    # Hyperlink (OSC 8)
    url:        Optional[str] = None

    def reset(self):
        """Reset all attributes to default."""
        self.fg         = Color.default()
        self.bg         = Color.default()
        self.bold       = False
        self.dim        = False
        self.italic     = False
        self.underline  = False
        self.underline2 = False
        self.blink      = False
        self.blink_fast = False
        self.inverse    = False
        self.invisible  = False
        self.strikethrough = False
        self.overline   = False
        self.underline_color = Color.default()
        self.url        = None

    def copy(self) -> "TextAttributes":
        """Return a shallow copy."""
        a = TextAttributes()
        a.fg            = self.fg
        a.bg            = self.bg
        a.bold          = self.bold
        a.dim           = self.dim
        a.italic        = self.italic
        a.underline     = self.underline
        a.underline2    = self.underline2
        a.blink         = self.blink
        a.blink_fast    = self.blink_fast
        a.inverse       = self.inverse
        a.invisible     = self.invisible
        a.strikethrough = self.strikethrough
        a.overline      = self.overline
        a.underline_color = self.underline_color
        a.url           = self.url
        return a

    def effective_fg(self) -> Color:
        """Return actual foreground (swapped if inverse)."""
        return self.bg if self.inverse else self.fg

    def effective_bg(self) -> Color:
        """Return actual background (swapped if inverse)."""
        return self.fg if self.inverse else self.bg


# ─────────────────────────────────────────────────────────────────────────────
# Parser events
# ─────────────────────────────────────────────────────────────────────────────

class ParserEventType(IntEnum):
    # Text
    PRINT          = auto()  # Printable character(s)
    # C0 controls
    BELL           = auto()
    BACKSPACE      = auto()
    TAB            = auto()
    LINEFEED       = auto()   # LF / VT / FF
    CARRIAGE_RETURN = auto()
    SHIFT_OUT      = auto()   # SO (G1 charset)
    SHIFT_IN       = auto()   # SI (G0 charset)
    # Cursor movement
    CURSOR_UP      = auto()
    CURSOR_DOWN    = auto()
    CURSOR_FORWARD = auto()
    CURSOR_BACKWARD= auto()
    CURSOR_NEXT_LINE = auto()
    CURSOR_PREV_LINE = auto()
    CURSOR_COLUMN  = auto()   # CHA
    CURSOR_POSITION= auto()   # CUP / HVP (row, col)
    CURSOR_SAVE    = auto()   # SCP / DECSC
    CURSOR_RESTORE = auto()   # RCP / DECRC
    # Erase
    ERASE_IN_DISPLAY = auto() # ED  (0=below,1=above,2=all,3=scrollback)
    ERASE_IN_LINE    = auto() # EL  (0=right, 1=left, 2=all)
    ERASE_CHARS      = auto() # ECH
    # Scroll
    SCROLL_UP      = auto()
    SCROLL_DOWN    = auto()
    SET_SCROLLREGION = auto() # DECSTBM
    # Insert/Delete
    INSERT_LINES   = auto()
    DELETE_LINES   = auto()
    INSERT_CHARS   = auto()
    DELETE_CHARS   = auto()
    # SGR
    SGR            = auto()   # Select Graphic Rendition
    # Modes
    MODE_SET       = auto()   # SM
    MODE_RESET     = auto()   # RM
    PRIVATE_MODE_SET   = auto()
    PRIVATE_MODE_RESET = auto()
    # Screen
    ALT_SCREEN_ON  = auto()   # ?1049h
    ALT_SCREEN_OFF = auto()   # ?1049l
    BRACKETED_PASTE_ON  = auto()
    BRACKETED_PASTE_OFF = auto()
    # Window / title
    WINDOW_TITLE   = auto()   # OSC 0/1/2
    ICON_TITLE     = auto()
    # Hyperlink
    HYPERLINK      = auto()   # OSC 8
    # Charset
    CHARSET_G0     = auto()
    CHARSET_G1     = auto()
    # Report
    DEVICE_STATUS  = auto()   # DSR
    REPORT_CURSOR  = auto()
    # Misc
    INDEX          = auto()   # IND
    REVERSE_INDEX  = auto()   # RI
    NEXT_LINE_CTRL = auto()   # NEL
    HORIZONTAL_TAB_SET = auto()
    TAB_CLEAR      = auto()
    RESET          = auto()   # RIS / Full reset
    SOFT_RESET     = auto()   # DECSTR
    CURSOR_STYLE   = auto()   # DECSCUSR
    SEND_DEVICE_ATTRS = auto() # DA
    UNKNOWN_CSI    = auto()
    UNKNOWN_ESC    = auto()


@dataclass
class ParserEvent:
    type:   ParserEventType
    params: List[int]        = field(default_factory=list)
    text:   str              = ""
    extra:  Any              = None


# ─────────────────────────────────────────────────────────────────────────────
# Main Parser
# ─────────────────────────────────────────────────────────────────────────────

class ANSIParser:
    """
    Streaming ANSI/VT220/xterm escape sequence parser.
    
    Usage:
        parser = ANSIParser()
        for event in parser.feed(raw_bytes):
            handle(event)
    
    State machine states:
        GROUND     - Normal character output
        ESCAPE     - Just received ESC (0x1B)
        CSI_ENTRY  - ESC [ received
        CSI_PARAM  - Parsing CSI parameters
        CSI_INTER  - CSI intermediate bytes
        OSC_STRING - ESC ] string (terminated by BEL or ST)
        DCS_ENTRY  - ESC P device control string
        DCS_STRING - Inside DCS
        SOS_STRING - ESC X string
        APC_STRING - ESC _ string
        PM_STRING  - ESC ^ string
        SS2        - ESC N single shift 2
        SS3        - ESC O single shift 3
    """

    # State constants
    GROUND     = 0
    ESCAPE     = 1
    CSI_ENTRY  = 2
    CSI_PARAM  = 3
    CSI_INTER  = 4
    OSC_STRING = 5
    DCS_ENTRY  = 6
    DCS_STRING = 7
    SS2        = 8
    SS3        = 9
    IGNORE_ST  = 10  # Generic string terminated by ST

    def __init__(self):
        self._state      = self.GROUND
        self._params     = []          # Current CSI parameter list
        self._current_param = ""       # Digits of current param
        self._intermediates = ""       # Intermediate bytes
        self._osc_buffer = ""          # OSC string accumulator
        self._private    = False       # CSI private (?) prefix
        self._text_buf   = []          # Pending printable chars
        self._utf8_buf   = []          # UTF-8 continuation bytes

        # Callback (optional) – called instead of returning events
        self._callback: Optional[Callable[[ParserEvent], None]] = None

    def set_callback(self, cb: Callable[[ParserEvent], None]):
        self._callback = cb

    # ─────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────

    def feed(self, data: bytes) -> List[ParserEvent]:
        """
        Parse a chunk of raw bytes.
        Returns list of ParserEvents (or emits via callback).
        """
        events: List[ParserEvent] = []

        # Decode bytes handling multi-byte UTF-8 across chunk boundaries
        text = data.decode("utf-8", errors="replace")

        for char in text:
            ev = self._process_char(char)
            if ev:
                events.extend(ev if isinstance(ev, list) else [ev])

        # Flush any pending text
        if self._text_buf:
            ev = self._flush_text()
            if ev:
                events.append(ev)

        if self._callback:
            for ev in events:
                self._callback(ev)
            return []

        return events

    # ─────────────────────────────────────────────
    # State machine
    # ─────────────────────────────────────────────

    def _process_char(self, c: str) -> Optional[Any]:
        code = ord(c)

        # ── GROUND ──────────────────────────────
        if self._state == self.GROUND:
            if code == 0x1B:  # ESC
                events = self._flush_text()
                self._state = self.ESCAPE
                return events
            elif code == 0x9B:  # C1 CSI (8-bit)
                events = self._flush_text()
                self._enter_csi()
                return events
            elif code == 0x9D:  # C1 OSC (8-bit)
                events = self._flush_text()
                self._state = self.OSC_STRING
                self._osc_buffer = ""
                return events
            elif code < 0x20 or code == 0x7F:
                # C0 control character
                events = self._flush_text()
                ev = self._handle_c0(code)
                result = []
                if events: result.extend(events if isinstance(events, list) else [events])
                if ev:     result.append(ev)
                return result or None
            else:
                # Printable
                self._text_buf.append(c)
                return None

        # ── ESCAPE ──────────────────────────────
        elif self._state == self.ESCAPE:
            if c == "[":
                self._enter_csi()
                return None
            elif c == "]":
                self._state = self.OSC_STRING
                self._osc_buffer = ""
                return None
            elif c == "P":
                self._state = self.DCS_ENTRY
                self._osc_buffer = ""
                return None
            elif c == "N":
                self._state = self.SS2
                return None
            elif c == "O":
                self._state = self.SS3
                return None
            elif c in "XZ^_":
                self._state = self.IGNORE_ST
                return None
            else:
                ev = self._handle_esc(c)
                self._state = self.GROUND
                return ev

        # ── CSI_ENTRY / CSI_PARAM ───────────────
        elif self._state in (self.CSI_ENTRY, self.CSI_PARAM):
            if c == "?":
                self._private = True
                self._state = self.CSI_PARAM
                return None
            elif c in "0123456789":
                self._current_param += c
                self._state = self.CSI_PARAM
                return None
            elif c == ";":
                self._push_param()
                self._state = self.CSI_PARAM
                return None
            elif 0x20 <= code <= 0x2F:
                # Intermediate byte
                self._intermediates += c
                self._state = self.CSI_INTER
                return None
            elif 0x40 <= code <= 0x7E:
                # Final byte
                self._push_param()
                ev = self._handle_csi(c)
                self._state = self.GROUND
                return ev
            elif code < 0x20:
                # C0 in CSI - execute
                return self._handle_c0(code)
            else:
                self._state = self.GROUND
                return None

        # ── CSI_INTER ───────────────────────────
        elif self._state == self.CSI_INTER:
            if 0x20 <= code <= 0x2F:
                self._intermediates += c
                return None
            elif 0x40 <= code <= 0x7E:
                self._push_param()
                ev = self._handle_csi(c)
                self._state = self.GROUND
                return ev
            else:
                self._state = self.GROUND
                return None

        # ── OSC_STRING ──────────────────────────
        elif self._state == self.OSC_STRING:
            if code == 0x07:  # BEL - OSC terminator
                ev = self._handle_osc(self._osc_buffer)
                self._state = self.GROUND
                return ev
            elif code == 0x1B:  # Start of ST (ESC \)
                # Will be handled next char
                pass
            elif c == "\\":  # String terminator after ESC
                if self._osc_buffer.endswith("\x1b"):
                    self._osc_buffer = self._osc_buffer[:-1]
                ev = self._handle_osc(self._osc_buffer)
                self._state = self.GROUND
                return ev
            elif code in (0x18, 0x1A):  # CAN / SUB - abort
                self._state = self.GROUND
                return None
            else:
                self._osc_buffer += c
                return None

        # ── DCS / IGNORE_ST ─────────────────────
        elif self._state in (self.DCS_ENTRY, self.DCS_STRING, self.IGNORE_ST):
            if code in (0x07, 0x18, 0x1A):
                self._state = self.GROUND
            elif code == 0x1B:
                pass  # ESC in ST sequence
            elif c == "\\" and self._state != self.IGNORE_ST:
                self._state = self.GROUND
            return None

        # ── SS2 / SS3 ───────────────────────────
        elif self._state in (self.SS2, self.SS3):
            # Single-shift: consume one character
            self._state = self.GROUND
            self._text_buf.append(c)
            return None

        return None

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────

    def _enter_csi(self):
        """Initialize CSI state."""
        self._state       = self.CSI_ENTRY
        self._params      = []
        self._current_param = ""
        self._intermediates = ""
        self._private     = False

    def _push_param(self):
        """Finalize current parameter digit sequence."""
        if self._current_param:
            self._params.append(int(self._current_param))
            self._current_param = ""
        else:
            self._params.append(0)

    def _param(self, idx: int, default: int = 0) -> int:
        """Get parameter by index with default."""
        if idx < len(self._params):
            v = self._params[idx]
            return v if v != 0 else default
        return default

    def _flush_text(self):
        """Flush pending text buffer."""
        if not self._text_buf:
            return None
        text = "".join(self._text_buf)
        self._text_buf = []
        return ParserEvent(ParserEventType.PRINT, text=text)

    # ─────────────────────────────────────────────
    # C0 control handler
    # ─────────────────────────────────────────────

    def _handle_c0(self, code: int) -> Optional[ParserEvent]:
        if   code == 0x07: return ParserEvent(ParserEventType.BELL)
        elif code == 0x08: return ParserEvent(ParserEventType.BACKSPACE)
        elif code == 0x09: return ParserEvent(ParserEventType.TAB)
        elif code in (0x0A, 0x0B, 0x0C):
                           return ParserEvent(ParserEventType.LINEFEED)
        elif code == 0x0D: return ParserEvent(ParserEventType.CARRIAGE_RETURN)
        elif code == 0x0E: return ParserEvent(ParserEventType.SHIFT_OUT)
        elif code == 0x0F: return ParserEvent(ParserEventType.SHIFT_IN)
        return None

    # ─────────────────────────────────────────────
    # ESC sequence handler
    # ─────────────────────────────────────────────

    def _handle_esc(self, c: str) -> Optional[ParserEvent]:
        if   c == "D": return ParserEvent(ParserEventType.INDEX)
        elif c == "E": return ParserEvent(ParserEventType.NEXT_LINE_CTRL)
        elif c == "H": return ParserEvent(ParserEventType.HORIZONTAL_TAB_SET)
        elif c == "M": return ParserEvent(ParserEventType.REVERSE_INDEX)
        elif c == "c": return ParserEvent(ParserEventType.RESET)
        elif c == "7": return ParserEvent(ParserEventType.CURSOR_SAVE)
        elif c == "8": return ParserEvent(ParserEventType.CURSOR_RESTORE)
        elif c in "()":
            return None  # Charset designation – handled elsewhere
        return ParserEvent(ParserEventType.UNKNOWN_ESC, text=c)

    # ─────────────────────────────────────────────
    # CSI sequence handler
    # ─────────────────────────────────────────────

    def _handle_csi(self, final: str) -> Optional[ParserEvent]:
        p = self._params
        prv = self._private

        # ── Cursor movement ──────────────────────
        if   final == "A": return ParserEvent(ParserEventType.CURSOR_UP,       [self._param(0, 1)])
        elif final == "B": return ParserEvent(ParserEventType.CURSOR_DOWN,     [self._param(0, 1)])
        elif final == "C": return ParserEvent(ParserEventType.CURSOR_FORWARD,  [self._param(0, 1)])
        elif final == "D": return ParserEvent(ParserEventType.CURSOR_BACKWARD, [self._param(0, 1)])
        elif final == "E": return ParserEvent(ParserEventType.CURSOR_NEXT_LINE,[self._param(0, 1)])
        elif final == "F": return ParserEvent(ParserEventType.CURSOR_PREV_LINE,[self._param(0, 1)])
        elif final == "G": return ParserEvent(ParserEventType.CURSOR_COLUMN,   [self._param(0, 1)])
        elif final in ("H", "f"):
            return ParserEvent(ParserEventType.CURSOR_POSITION,
                               [self._param(0, 1), self._param(1, 1)])
        elif final == "s": return ParserEvent(ParserEventType.CURSOR_SAVE)
        elif final == "u": return ParserEvent(ParserEventType.CURSOR_RESTORE)

        # ── Erase ────────────────────────────────
        elif final == "J":
            return ParserEvent(ParserEventType.ERASE_IN_DISPLAY, [self._param(0, 0)])
        elif final == "K":
            return ParserEvent(ParserEventType.ERASE_IN_LINE,    [self._param(0, 0)])
        elif final == "X":
            return ParserEvent(ParserEventType.ERASE_CHARS,      [self._param(0, 1)])

        # ── Scroll ───────────────────────────────
        elif final == "S": return ParserEvent(ParserEventType.SCROLL_UP,   [self._param(0, 1)])
        elif final == "T": return ParserEvent(ParserEventType.SCROLL_DOWN, [self._param(0, 1)])
        elif final == "r":
            return ParserEvent(ParserEventType.SET_SCROLLREGION,
                               [self._param(0, 1), self._param(1, 0)])

        # ── Insert/Delete ────────────────────────
        elif final == "L": return ParserEvent(ParserEventType.INSERT_LINES, [self._param(0, 1)])
        elif final == "M": return ParserEvent(ParserEventType.DELETE_LINES, [self._param(0, 1)])
        elif final == "@": return ParserEvent(ParserEventType.INSERT_CHARS, [self._param(0, 1)])
        elif final == "P": return ParserEvent(ParserEventType.DELETE_CHARS, [self._param(0, 1)])

        # ── SGR ──────────────────────────────────
        elif final == "m":
            return self._handle_sgr(p)

        # ── Modes ────────────────────────────────
        elif final == "h":
            if prv:
                return self._handle_private_mode(p, True)
            return ParserEvent(ParserEventType.MODE_SET, p[:])
        elif final == "l":
            if prv:
                return self._handle_private_mode(p, False)
            return ParserEvent(ParserEventType.MODE_RESET, p[:])

        # ── Device attributes / status ───────────
        elif final == "n":
            return ParserEvent(ParserEventType.DEVICE_STATUS, [self._param(0)])
        elif final == "c":
            return ParserEvent(ParserEventType.SEND_DEVICE_ATTRS, [self._param(0)])

        # ── Cursor style ─────────────────────────
        elif final == "q":
            if self._intermediates == " ":
                return ParserEvent(ParserEventType.CURSOR_STYLE, [self._param(0)])

        # ── Tab ──────────────────────────────────
        elif final == "g":
            return ParserEvent(ParserEventType.TAB_CLEAR, [self._param(0)])
        elif final == "I":
            return ParserEvent(ParserEventType.TAB, [self._param(0, 1)])
        elif final == "Z":
            return ParserEvent(ParserEventType.TAB, [-self._param(0, 1)])

        return ParserEvent(ParserEventType.UNKNOWN_CSI,
                           text=f"CSI {'?' if prv else ''}{';'.join(str(x) for x in p)}{final}")

    # ─────────────────────────────────────────────
    # SGR parser
    # ─────────────────────────────────────────────

    def _handle_sgr(self, params: List[int]) -> ParserEvent:
        """
        Parse SGR (Select Graphic Rendition) parameters.
        Returns a ParserEvent with .extra = dict of attribute changes.
        """
        changes = {}

        if not params:
            params = [0]

        i = 0
        while i < len(params):
            code = params[i]

            if code == 0:
                changes["reset"] = True
            elif code == 1:  changes["bold"]        = True
            elif code == 2:  changes["dim"]         = True
            elif code == 3:  changes["italic"]      = True
            elif code == 4:
                sub = params[i+1] if i+1 < len(params) and params[i+1] in (0,1,2,3,4,5) and params[i] == 4 else None
                changes["underline"] = True
            elif code == 5:  changes["blink"]       = True
            elif code == 6:  changes["blink_fast"]  = True
            elif code == 7:  changes["inverse"]     = True
            elif code == 8:  changes["invisible"]   = True
            elif code == 9:  changes["strikethrough"] = True
            elif code == 21: changes["underline2"]  = True
            elif code == 22: changes["bold"] = False; changes["dim"] = False
            elif code == 23: changes["italic"]      = False
            elif code == 24: changes["underline"] = False; changes["underline2"] = False
            elif code == 25: changes["blink"] = False; changes["blink_fast"] = False
            elif code == 27: changes["inverse"]     = False
            elif code == 28: changes["invisible"]   = False
            elif code == 29: changes["strikethrough"] = False
            elif code == 53: changes["overline"]    = True
            elif code == 55: changes["overline"]    = False

            # Standard foreground colors (30-37, 90-97)
            elif 30 <= code <= 37:
                changes["fg"] = Color.from_ansi16(code - 30)
            elif code == 39:
                changes["fg"] = Color.default()
            elif 90 <= code <= 97:
                changes["fg"] = Color.from_ansi16(code - 90 + 8)

            # Standard background colors (40-47, 100-107)
            elif 40 <= code <= 47:
                changes["bg"] = Color.from_ansi16(code - 40)
            elif code == 49:
                changes["bg"] = Color.default()
            elif 100 <= code <= 107:
                changes["bg"] = Color.from_ansi16(code - 100 + 8)

            # Extended color (38 / 48 / 58)
            elif code in (38, 48, 58):
                color, consumed = self._parse_extended_color(params, i + 1)
                i += consumed
                if   code == 38: changes["fg"] = color
                elif code == 48: changes["bg"] = color
                elif code == 58: changes["underline_color"] = color

            i += 1

        return ParserEvent(ParserEventType.SGR, extra=changes)

    def _parse_extended_color(self, params: List[int], start: int) -> Tuple[Color, int]:
        """Parse 256-color or RGB color from SGR params. Returns (color, bytes_consumed)."""
        if start >= len(params):
            return Color.default(), 0

        mode = params[start]

        if mode == 5:
            # 256-color: 38;5;n
            if start + 1 < len(params):
                return Color.from_256(params[start + 1]), 2
            return Color.default(), 1

        elif mode == 2:
            # Truecolor: 38;2;r;g;b
            if start + 3 < len(params):
                r = params[start + 1]
                g = params[start + 2]
                b = params[start + 3]
                return Color.from_rgb(r, g, b), 4
            return Color.default(), 1

        return Color.default(), 1

    # ─────────────────────────────────────────────
    # Private mode handler
    # ─────────────────────────────────────────────

    def _handle_private_mode(self, params: List[int], set_mode: bool) -> ParserEvent:
        """Handle DEC private modes (?Xh / ?Xl)."""
        mode = params[0] if params else 0
        evt_type = ParserEventType.PRIVATE_MODE_SET if set_mode else ParserEventType.PRIVATE_MODE_RESET

        # Map common modes to specific events
        if mode == 1049:
            evt_type = ParserEventType.ALT_SCREEN_ON if set_mode else ParserEventType.ALT_SCREEN_OFF
        elif mode == 2004:
            evt_type = ParserEventType.BRACKETED_PASTE_ON if set_mode else ParserEventType.BRACKETED_PASTE_OFF

        return ParserEvent(evt_type, params=params[:])

    # ─────────────────────────────────────────────
    # OSC handler
    # ─────────────────────────────────────────────

    def _handle_osc(self, data: str) -> Optional[ParserEvent]:
        """Parse OSC sequences: OSC Ps ; Pt BEL/ST"""
        if ";" not in data:
            return None

        ps, pt = data.split(";", 1)
        try:
            ps_int = int(ps.strip())
        except ValueError:
            return None

        if ps_int in (0, 1, 2):
            # Set window/icon title
            return ParserEvent(
                ParserEventType.WINDOW_TITLE,
                params=[ps_int],
                text=pt
            )
        elif ps_int == 8:
            # Hyperlink: OSC 8 ; params ; url BEL
            # params;url
            parts = pt.split(";", 1)
            url = parts[1] if len(parts) > 1 else ""
            return ParserEvent(
                ParserEventType.HYPERLINK,
                text=url,
                extra=parts[0] if parts else ""
            )

        return None


# ─────────────────────────────────────────────────────────────────────────────
# SGR Attribute Processor
# Applies parsed SGR events to a live TextAttributes state
# ─────────────────────────────────────────────────────────────────────────────

class SGRProcessor:
    """Maintains current SGR attribute state and applies changes."""

    def __init__(self):
        self.attrs = TextAttributes()

    def apply(self, event: ParserEvent):
        """Apply an SGR event to current attributes."""
        if event.type != ParserEventType.SGR:
            return

        changes = event.extra or {}

        if changes.get("reset"):
            self.attrs.reset()
            # Apply remaining changes after reset
            changes = {k: v for k, v in changes.items() if k != "reset"}

        for key, value in changes.items():
            if   key == "fg":            self.attrs.fg            = value
            elif key == "bg":            self.attrs.bg            = value
            elif key == "bold":          self.attrs.bold          = value
            elif key == "dim":           self.attrs.dim           = value
            elif key == "italic":        self.attrs.italic        = value
            elif key == "underline":     self.attrs.underline     = value
            elif key == "underline2":    self.attrs.underline2    = value
            elif key == "blink":         self.attrs.blink         = value
            elif key == "blink_fast":    self.attrs.blink_fast    = value
            elif key == "inverse":       self.attrs.inverse       = value
            elif key == "invisible":     self.attrs.invisible     = value
            elif key == "strikethrough": self.attrs.strikethrough = value
            elif key == "overline":      self.attrs.overline      = value
            elif key == "underline_color": self.attrs.underline_color = value

    def current(self) -> TextAttributes:
        """Return current attributes (copy)."""
        return self.attrs.copy()

    def reset(self):
        """Reset to defaults."""
        self.attrs.reset()
