"""The field message window: what a script's text command puts in it, and
how the screen shows it.

A text command (0x02, ScriptCommandMessageDisp (0x8005AB1C)) walks its
message with font_string_walk (0x8005A884) (`system_strings.walk`), the
characters to MessageStringCodePut (0x8005A834) and the controls to
MessageControlRun (0x8005AF20). `Window` keeps the state those two change:

    the text buffer   0x801CBB00, three rows of 0x880 bytes: 17 cells of
                      16 x 16 pixels at 4 bits, 0x80 bytes a cell, 8 bytes a
                      pixel row, the low nibble the even pixel
    the pen           g_FontTarget / g_FontPen: font_code_put (0x80026D64)
                      ORs a glyph in column by column, font_pen_move
                      (0x800270CC) steps it and moves the target a cell on
                      every 16 pixels, past a row's end into the next
    the style         g_FontColBits: font_col_set (0x800270BC), ORed into
                      every drawn pixel
    the row           g_MessageLine: 0xFF02 the next row (font_target_set
                      (0x800270AC)), the third falls into 0xFF01, a new page:
                      mem_clear of 0x1980 bytes, the pen to row 0
    the faces         g_MessageFacePlaces and the cells MessageFaceSet
                      (0x8005B36C) gives faces through CellFacePlacesSet
                      (0x80057608): 0xFAnn place 0x10, 0xFBnn place 0x20

A glyph is font_pattern_get (0x80026B1C)'s 16 x 16 one-bit pattern (codes
0x20-0x7A from g_FontPatterns20 (0x800B217C), 0x9908-0x99F8 from
g_FontPatterns9908 (0x800B035C), any other from the BIOS's kanji ROM
through Krom2RawAdd), outlined by font_pattern_outline (0x80026B98): a set
pixel is 1, a clear one next to a set one (left, right, above, below) is 3.
MessageStringCodePut puts it with mode 1: no centring, its width the
rightmost used column + 1 (a blank glyph 5).

SLPS_013.97 draws the same way with another font: its font_pattern_get
(SLPS_013.97 0x8002A3A0) has no table for 0x20-0x7A; 0x9908-0x99F8 come
from its g_FontPatterns9908, 0x8440-0x8491 from a short list of its own
(`Font`), any other from the kanji ROM; its font_code_put (SLPS_013.97
0x8002A5C0) gives a blank glyph 10 pixels.

The kanji ROM is the console's, not the disc's, and is not read. A `Font`
draws a code from it with what its caller gives (`rom_font`: a character
to a pattern, an installed font in the viewer), by the character the code
stands for (`characters`), else as a box (ROM_STAND_IN); the ideographic
space 0x8140 is blank.

A `Screen` is the window as the player waits on it: at a prompt (0xFF00),
or where text is cleared or closed without one (a page, 0xFF03), or where a
message ends with the window still open. `draw` makes the picture:

    the shade   MessageShadeDraw (0x80015E88): a black box, half
                transparent (tpage 0x1F), x 0..320, y 0xB8 - h * 4 for
                h * 8 rows; MessageOpen (0x8005A6D0) leaves h at 8
    the text    MessageRowDisp (0x8005B4A0) -> CellTextDisp (0x800572E0):
                row k at grid (column, 0x14 + 2k) (8 pixels a grid step),
                its first n cells, the column and n by the face places
                (`US_LAYOUT`: 1: 0xC, 2: 2, 0x10: 0xA, 0x20: 2, none: 2;
                n 17 for all). Row k lies in VRAM from block 17k of the
                font's lines of 16 blocks; font_cell_run_set (0x80016230)
                splits a run that reaches its line's end (block k + n >=
                16) after 16 - k cells and puts the rest 2 * (16 - k) grid
                columns on, a grid row lower past column 40 (`cell_runs`);
                font_cell_draw (0x80016134) draws with palette 0x7ECE: row
                507 from colour 0xE0, the cell's nibble the index
    the faces   FaceCellDraw (0x8001B4B0): 64 x 64, row 503, at the cell
                CellFacePlacesSet (0x80057608) gives the place: 0x10 at
                grid (1, 0x12), 0x20 at (0x1F, 0x12)
    the arrow   at a prompt MessageArrowStep (0x8005A678) ->
                MessageArrowDraw (0x80015F0C)(x, 0xD0): a flat triangle 8
                wide and 5 high, colour 0x20F0F0, x by the face places
                (MessageRowDisp: 0xE0 for 2, 0xE8 for 0x20, else 0x128)

The picture is the screen's rows 144 to 215, where all of these lie. They
are drawn by their ordering-table slots, shade 0x40, text 0x38, faces and
arrow 0x10, the higher slot first: GsClearOt (0x8008FB98) links the
frame's tables reversed (ClearOTagR). Within a slot the order is not
read; the arrow is drawn over the faces here.

SLPS_013.97 lays the window out its own way (`JP_LAYOUT`), read from its
machine code against the US C. Three functions differ in their numbers:

    MessageRowDisp (0x8005B4A0; SLPS_013.97 0x8005E820)   the text column
        and the cells shown by the face places: 1: 0xD and 12, 2: 3 and
        12, 0x10: 0xB and 13, 0x20: 3 and 13, none: 3 and 17; the arrow's
        x as the US's
    CellFacePlacesSet (0x80057608; SLPS_013.97 0x8005A9B4)   place 0x10's
        face at grid (2, 0x12), 0x20's at (0x1E, 0x12); the others as the
        US's
    MessageArrowStep (0x8005A678; SLPS_013.97 0x8005DA9C)   the arrow at
        y 0xC8

The rest is the same instruction for instruction but for addresses:
CellTextDisp (0x800572E0; SLPS_013.97 0x8005A684), still 0x11 cells a
buffer row and three rows; font_cell_run_set (0x80016230; SLPS_013.97
0x800174FC), font_place_split (0x80016204; SLPS_013.97 0x800174D0) and
font_cell_set (0x800161CC; SLPS_013.97 0x80017498); font_cell_draw
(0x80016134; SLPS_013.97 0x80017400) with palette 0x7ECE; FaceCellSet
(0x8001B3DC; SLPS_013.97 0x8001CDE4) and FaceCellDraw (0x8001B4B0;
SLPS_013.97 0x8001CEBC); MessageShadeDraw (0x80015E88; SLPS_013.97
0x80017144), MessageOpen (0x8005A6D0; SLPS_013.97 0x8005DAF4) and
MessageArrowDraw (0x80015F0C; SLPS_013.97 0x800171CC). The text row is
0x14 there too: ScriptLabelRun (0x80059FDC; SLPS_013.97 0x8005D3E8) and
MessageStringDisp (0x8005AB98; SLPS_013.97 0x8005DD90) set g_MessageRow
to it. So with a face up a Japanese row shows the first 12 or 13 of the
17 cells it holds, in one run (block k + n stays below 16); text past
them is in the buffer but not on the screen. With none up a row splits
as the US's does, its rest at grid column 3 + 2 * (16 - k) of the same
grid row.

Uncertain: the twins were paired by the shape of their code, not by a
symbol of the Japanese program's own. A glyph a message puts past its
row's shown cells is left off the screen, as the layout says; whether
the console shows it some other way was not seen. The kanji's widths are
the stand-in font's (`Font`), not the ROM's, so where a row's text ends
can differ from the console's by a few pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw

from . import event_script, system_strings
from .system_strings import EXE_BASE, WordLookup
from ..records import programs

#: The text buffer: three rows of 17 cells (0x801CBB00, MessageControlRun).
ROW_BYTES = 0x880
CELL_BYTES = 0x80
CELL = 16
ROW_CELLS = 17
ROWS = 3
#: MessageControlRun's 0xFF01: mem_clear(0x801CBB00, 0x1980).
PAGE_BYTES = ROWS * ROW_BYTES
#: MessageLinesClear (0x8005BC74) and ScriptLabelRun (0x80059FDC):
#: font_target_clear(0x801CBB00, 0x55), five rows.
CLEARED_BYTES = 0x55 << 7
#: The rows past the window's three: MessageLineDisp (0x8005AD94)'s rows 3
#: to 6, which a pen that runs past row 2 writes into.
BUFFER_BYTES = 7 * ROW_BYTES

#: font_pattern_get (0x80026B1C)'s two tables in the program.
PATTERNS_20 = 0x800B217C
PATTERNS_20_COUNT = 0x5B
PATTERNS_9908 = 0x800B035C
PATTERNS_9908_COUNT = 0xF1
PATTERN_BYTES = 32
#: font_code_put (0x80026D64): the width of a glyph with no used column.
BLANK_WIDTH = 5
#: SLPS_013.97's font_code_put (SLPS_013.97 0x8002A5C0): the same, 10.
JP_BLANK_WIDTH = 10
#: SLPS_013.97's font_pattern_get sends 0x8440-0x8491 to the function at
#: SLPS_013.97 0x8002A348: it finds the code's low byte in the 0-ended byte
#: list at SLPS_013.97 0x800B1338 and takes the pattern that many places
#: past g_FontPatterns9908's 0xF1; a byte not in the list draws nothing.
JP_LIST_FIRST, JP_LIST_COUNT = 0x8440, 0x52
JP_LIST_ADDR = 0x800B1338
#: Shift-JIS's ideographic space: blank in the kanji ROM.
WIDE_SPACE = 0x8140

TEXT_ROW = 0x14
GRID_COLUMNS = 0x28
#: font_place_split (0x80016204): a VRAM font line holds 16 blocks (cells).
LINE_BLOCKS = 0x10
#: CellFacePlacesSet (0x80057608): place bit -> grid (column, row), in the
#: order it gives the bits out.
FACE_CELLS = {1: (3, 0x12), 2: (0x1C, 0x12), 0x10: (1, 0x12), 0x20: (0x1F, 0x12),
              4: (6, 5), 8: (4, 0xB)}
FACE_SIDE = 64

#: The picture: the screen's rows TOP to TOP + HEIGHT - 1.
TOP = 144
HEIGHT = 72
WIDTH = 320
SHADE_HEIGHT = 8                  # MessageOpen (0x8005A6D0)'s last height
SHADE_ALPHA = 128                 # half the background (tpage 0x1F)
ARROW_COLOUR = (0xF0, 0xF0, 0x20, 255)    # 0x20F0F0, red in the low byte
TEXT_CLUT_FIRST = 0xE0            # font_cell_draw's 0x7ECE: row 507, x 0xE0



@dataclass
class Layout:
    """Where a program puts the window's parts (module docstring)."""
    #: MessageRowDisp: (place bit, text column, cells shown, arrow x),
    #: tested in this order
    places: tuple[tuple[int, int, int, int], ...]
    #: the same with none of them up: (text column, cells shown, arrow x)
    no_place: tuple[int, int, int]
    #: CellFacePlacesSet: place bit -> grid (column, row) of its face
    faces: dict[int, tuple[int, int]]
    #: MessageArrowStep's y
    arrow_y: int


US_LAYOUT = Layout(((1, 0xC, 17, 0x128), (2, 2, 17, 0xE0), (0x10, 0xA, 17, 0x128),
                    (0x20, 2, 17, 0xE8)), (2, 17, 0x128), FACE_CELLS, 0xD0)
JP_LAYOUT = Layout(((1, 0xD, 12, 0x128), (2, 3, 12, 0xE0), (0x10, 0xB, 13, 0x128),
                    (0x20, 3, 13, 0xE8)), (3, 17, 0x128),
                   {**FACE_CELLS, 0x10: (2, 0x12), 0x20: (0x1E, 0x12)}, 0xC8)


def layout_of(image: bytes) -> Layout:
    """The program's window layout: SLPS_013.97's or the US program's."""
    return JP_LAYOUT if programs.program_of(image) == programs.JP else US_LAYOUT


#: The splices MessageControlRun walks (code & 0xFF00); 0xF2 and 0xF3 do
#: nothing there.
SPLICES = (0xF000, 0xF100, 0xF400, 0xF500, 0xF600)


def outline(pattern: bytes) -> list[list[int]]:
    """font_pattern_outline (0x80026B98): 17 rows of 16 pixels from a
    pattern's first 15 rows (two bytes a row, high byte first): 1 where the
    pattern is set, 3 where a pixel to its left or right in the row, or the
    one above or below, is set."""
    a = [0] + [pattern[2 * i] << 8 | pattern[2 * i + 1] for i in range(15)] + [0]
    b = [a[i + 1] for i in range(15)] + [0, 0]
    for i in range(15):
        b[i + 2] |= a[i + 1]
    for i in range(1, 16):
        x = a[i]
        b[i] = (b[i] | x | x << 1 | x >> 1) & 0xFFFF
    return [[1 if a[i] & (0x8000 >> c) else 3 if b[i] & (0x8000 >> c) else 0
             for c in range(16)] for i in range(17)]


def glyph_width(rows: list[list[int]], blank: int = BLANK_WIDTH) -> int:
    """font_code_put (0x80026D64)'s width over the first 16 rows: the
    rightmost used column + 1, or `blank` (5)."""
    used = [any(r[c] for r in rows[:16]) for c in range(16)]
    return max((c + 1 for c in range(16) if used[c]), default=0) or blank


#: What stands for a kanji-ROM glyph with nothing to draw it: a box.
ROM_STAND_IN = bytes([0, 0, 0x7F, 0xFC] + [0x40, 0x04] * 11 + [0x7F, 0xFC, 0, 0, 0, 0])


#: What draws a kanji-ROM glyph instead: a character -> its 32-byte
#: pattern, or None for one it cannot draw.
RomFont = Callable[[str], "bytes | None"]


class Font:
    """font_pattern_get (0x80026B1C) over the program's image (SLPS_013.97's
    own, module docstring, for that program's image). `rom_font` draws the
    kanji ROM's glyphs, by their characters; without it, or for a character
    it cannot draw, they are a box."""

    def __init__(self, image: bytes, image_base: int = EXE_BASE,
                 rom_font: RomFont | None = None):
        self._image = image
        self._base = image_base
        self.rom_font = rom_font
        self._outlines: dict[int, list[list[int]]] = {}
        self._boxed: set[int] = set()
        self._columns: dict[int, list[list[tuple[int, int]]]] = {}
        p9908 = programs.address(image, "g_FontPatterns9908", PATTERNS_9908)
        self._jp = programs.program_of(image) == programs.JP
        self._tables = (((p9908, 0x9908, PATTERNS_9908_COUNT),) if self._jp else
                        ((PATTERNS_20, 0x20, PATTERNS_20_COUNT),
                         (p9908, 0x9908, PATTERNS_9908_COUNT)))
        self._list_base = p9908 + PATTERNS_9908_COUNT * PATTERN_BYTES
        self.blank_width = JP_BLANK_WIDTH if self._jp else BLANK_WIDTH
        #: what the codes stand for in a text (system_strings.characters_of)
        self.characters = system_strings.characters_of(image)
        self._glyphs: dict[int, tuple[bool, bool, str]] = {}

    def _bytes(self, addr: int) -> bytes:
        at = addr - self._base
        return bytes(self._image[at:at + PATTERN_BYTES])

    def _listed(self, code: int) -> bytes:
        """The function at SLPS_013.97 0x8002A348: the list's place of the
        code's low byte."""
        at = JP_LIST_ADDR - self._base
        for i in range(0x100):
            b = self._image[at + i]
            if b == 0:
                break
            if b == code & 0xFF:
                return self._bytes(self._list_base + i * PATTERN_BYTES)
        return bytes(PATTERN_BYTES)

    def from_rom(self, code: int) -> bool:
        """True for a code the kanji ROM draws (not on the disc)."""
        if self._jp and 0 <= code - JP_LIST_FIRST < JP_LIST_COUNT:
            return False
        return not any(0 <= code - first < count for _a, first, count in self._tables)

    def pattern(self, code: int) -> bytes | None:
        """The glyph's 32 bytes, or None for a code the kanji ROM draws."""
        for addr, first, count in self._tables:
            if 0 <= code - first < count:
                return self._bytes(addr + (code - first) * PATTERN_BYTES)
        if self._jp and 0 <= code - JP_LIST_FIRST < JP_LIST_COUNT:
            return self._listed(code)
        return None

    def _rom_pattern(self, code: int) -> bytes:
        """A kanji-ROM code's pattern: blank for the ideographic space, else
        `rom_font`'s for its character, else the box."""
        if code == WIDE_SPACE:
            return bytes(PATTERN_BYTES)
        ch = self.characters(code) if self.characters else None
        p = self.rom_font(ch) if ch and self.rom_font else None
        if p is None:
            self._boxed.add(code)
            return ROM_STAND_IN
        return p

    def boxed(self, code: int) -> bool:
        """True for a kanji-ROM code drawn as the box."""
        self.outline(code)
        return code in self._boxed

    def glyph(self, code: int) -> tuple[bool, bool, str]:
        """What a message makes of a character code (Window.message): (the
        kanji ROM draws it, the ideographic space aside; it is drawn as the
        box; its text), worked out once a code."""
        got = self._glyphs.get(code)
        if got is None:
            rom = self.from_rom(code) and code != WIDE_SPACE
            got = self._glyphs[code] = (rom, rom and self.boxed(code),
                                        system_strings.char_text(code, self.characters)[0])
        return got

    def outline(self, code: int) -> list[list[int]]:
        if code not in self._outlines:
            p = self.pattern(code)
            self._outlines[code] = outline(self._rom_pattern(code) if p is None else p)
        return self._outlines[code]

    def columns(self, code: int) -> list[list[tuple[int, int]]]:
        """The glyph as font_code_put puts it: for each of its `glyph_width`
        columns, (row, pixel) for the used pixels of the first 16 rows."""
        if code not in self._columns:
            rows = self.outline(code)
            self._columns[code] = [[(j, rows[j][c]) for j in range(16) if rows[j][c]]
                                   for c in range(glyph_width(rows, self.blank_width))]
        return self._columns[code]


@dataclass
class Screen:
    """The window as the player sees it at one stop."""
    rows: bytes                     # the three rows of the text buffer
    places: int                     # g_MessageFacePlaces
    faces: dict[int, int]           # place bit -> the face its cell shows
    why: str                        # "prompt", "page", "close" or "open"
    text: str                       # the page's text, plain


@dataclass
class Said:
    """A run of a message's text under one set of faces."""
    faces: tuple[tuple[int, int], ...]  # (place bit, face) of the places up
    text: str


@dataclass
class Message:
    """One text command, or one answer command (`answers` set)."""
    offset: int
    label: int | None
    screens: list[Screen] = field(default_factory=list)
    said: list[Said] = field(default_factory=list)
    answers: tuple[str, str] | None = None
    rom_glyphs: int = 0             # glyphs the kanji ROM would draw
    rom_boxed: int = 0              # of those, drawn as the box
    empty_splices: int = 0          # splices of a string slot with offset 0


class Window:
    """The message window's state, changed as MessageStringCodePut and
    MessageControlRun change it."""

    def __init__(self, font: Font, draw: bool = True):
        self.font = font
        self.draw = draw
        self.reset()

    def reset(self) -> None:
        """A label's start: ScriptLabelRun (0x80059FDC) clears five rows and
        puts the pen at row 0 with no style (font_target_clear). No face is
        taken to be up (MessageClose and MessageReset (0x80059F7C) leave
        none), and the face pages to start at page 0: g_FaceCellPage is
        whatever came before."""
        self.buf = bytearray(BUFFER_BYTES)
        self.target = 0
        self.pen = 0
        self.colbits = 0
        self.line = 0
        self.places = 0
        self.cells: dict[int, int] = {}       # place bit -> face page
        self.pages = [0, 0]                   # page -> face loaded there
        self.page = 0
        self._page_text: list[str] = []
        self._unshown = False
        self._speaker: tuple | None = None

    # -- the pen ------------------------------------------------------------

    def pen_move(self, pixels: int) -> None:
        """font_pen_move (0x800270CC)."""
        new = (self.pen + pixels) & 0xFF
        if new >= CELL:
            self.pen = new & 0xF
            self.target += (new >> 4) * CELL_BYTES
        else:
            self.pen = new

    def code_put(self, code: int) -> None:
        """font_code_put (0x80026D64) with mode 1 (MessageStringCodePut).
        A window that does not draw only keeps the text."""
        if not self.draw:
            return
        buf, size = self.buf, len(self.buf)
        for column in self.font.columns(code):
            off = self.target + (self.pen >> 1)
            shift = 4 if self.pen & 1 else 0
            for j, px in column:
                at = off + 8 * j
                if at < size:
                    buf[at] |= (px | self.colbits) << shift
            self.pen_move(1)

    # -- the faces ----------------------------------------------------------

    def _face_cell(self, place: int, face: int) -> None:
        """FaceCellSet (0x8001B3DC): face 0 clears the cell; any other is
        loaded into the current page, the cell shows that page, and the
        page alternates."""
        if face == 0:
            self.cells.pop(place, None)
            return
        self.pages[self.page] = face
        self.cells[place] = self.page
        self.page ^= 1

    def _places_set(self, places: int, face: int) -> None:
        """CellFacePlacesSet (0x80057608): the face into each place bit."""
        for bit in FACE_CELLS:
            if places & bit:
                self._face_cell(bit, face)

    def face_set(self, face: int, places: int) -> None:
        """MessageFaceSet (0x8005B36C). A face given while a place outside
        `places` is up clears the NEW places first, not that one, which
        stays on screen out of g_MessageFacePlaces."""
        if face:
            if self.places & ~places & 0xFFFF:
                self._places_set(places, 0)
                self.places = 0
            self._places_set(places, face)
            self.places = places
        else:
            self._places_set(self.places, 0)
            self.places = 0
        self._speaker = None

    def faces(self) -> dict[int, int]:
        return {place: self.pages[page] for place, page in self.cells.items()}

    def speaker(self) -> tuple[tuple[int, int], ...]:
        """(place bit, face) for each place up that shows a face."""
        if self._speaker is None:
            shown = self.faces()
            self._speaker = tuple((p, shown[p]) for p in FACE_CELLS
                                  if self.places & p and p in shown)
        return self._speaker

    # -- stops --------------------------------------------------------------

    def screen(self, why: str) -> Screen:
        self._unshown = False
        return Screen(bytes(self.buf[:PAGE_BYTES]), self.places, self.faces(), why,
                      system_strings.spaced("".join(self._page_text)).strip("\n"))

    def page_clear(self) -> None:
        """0xFF01: row 0, the three rows cleared, the pen to the start."""
        self.line = 0
        self.buf[:PAGE_BYTES] = bytes(PAGE_BYTES)
        self.target = 0
        self.pen = 0
        self._page_text = []

    def lines_clear(self) -> None:
        """MessageLinesClear (0x8005BC74): font_target_clear over five rows,
        so the style goes too."""
        self.line = 0
        self.buf[:CLEARED_BYTES] = bytes(CLEARED_BYTES)
        self.target = 0
        self.pen = 0
        self.colbits = 0
        self._page_text = []

    # -- a message ----------------------------------------------------------

    def message(self, buf: bytes, offset: int, words: WordLookup | None,
                char_table: Callable[[int], int], table: bytes,
                label: int | None = None) -> Message:
        """Text command 0x02 at `offset`: its walk through this window,
        splices from `table` (resource 1's string table)."""
        out = Message(offset, label)
        said: list[tuple[tuple, list[str]]] = []

        def text(piece: str) -> None:
            self._page_text.append(piece)
            if said:
                said[-1][1].append(piece)

        glyph, draw = self.font.glyph, self.draw

        def emit_char(code: int) -> None:
            rom, boxed, piece = glyph(code)
            if rom:
                out.rom_glyphs += 1
                out.rom_boxed += boxed
            if draw:
                self.code_put(code)
            self._unshown = True
            who = self._speaker
            if who is None:
                who = self.speaker()
            if not said or said[-1][0] != who:
                said.append((who, []))
            self._page_text.append(piece)
            said[-1][1].append(piece)

        def emit_ctl(code: int, depth: int = 0) -> None:
            hi = code & 0xFF00
            if hi in SPLICES:
                at = system_strings.string_offset(table, code & 0xFFF)
                if not at or depth >= 4:
                    out.empty_splices += 1
                    return
                system_strings.walk(table, at, words, char_table, emit_char,
                                    lambda c: emit_ctl(c, depth + 1))
                return
            if code == 0xFF00:
                if self._unshown:
                    out.screens.append(self.screen("prompt"))
            elif code in (0xFF01, 0xFF02):
                if code == 0xFF02:
                    self.line += 1
                    if self.line < ROWS:
                        self.target = self.line * ROW_BYTES
                        self.pen = 0
                        text("\n")
                        return
                if self._unshown:
                    out.screens.append(self.screen("page"))
                text("\n")
                self.page_clear()
            elif code == 0xFF03:
                if self._unshown:
                    out.screens.append(self.screen("close"))
                self.lines_clear()
                self.face_set(0, 0x10)
            elif hi == 0xF900:
                self.pen_move(code & 0xFF)
                text(system_strings.MOVE)
            elif hi == 0xFC00:
                self.colbits = (code & 3) << 2
            elif hi == 0xFA00:
                self.face_set(code & 0xFF, 0x10)
            elif hi == 0xFB00:
                self.face_set(code & 0xFF, 0x20)

        system_strings.walk(buf, offset + 2, words, char_table, emit_char, emit_ctl)
        if self._unshown:
            out.screens.append(self.screen("open"))
        out.said = [Said(who, t) for who, pieces in said
                    if (t := system_strings.spaced("".join(pieces)).strip("\n"))]
        return out


#: Command 0x07: ScriptCommandAnswerRun (0x8005C42C) -> ScriptAnswerRun
#: (0x8005C198), or ScriptPagesRun (0x8005C2C0) in scripts 0 and 0xC8.
ANSWER = 0x07


def answer_strings(buf: bytes, offset: int) -> tuple[int, int]:
    """Where command 0x07's two strings begin: [07][label][byte][pad], then
    the first string up to its 0xFF, then the second (ScriptStringEndFind
    (0x8005C144) steps over each)."""
    first = offset + 6
    return first, buf.index(0xFF, first) + 1


def script_messages(buf: bytes, words: WordLookup | None, char_table: Callable[[int], int],
                    table: bytes, font: Font, draw: bool = True,
                    commands: int = event_script.CMD_COUNT) -> list[Message]:
    """Every text and answer command of a script, in the order of its code
    (event_script.script_code), each read through one window. The window
    starts afresh at every label, as ScriptLabelRun leaves it, and is
    otherwise carried from one message to the next: a message that does
    not close leaves its text and faces to the next one. `commands` is the
    program's handler count (event_script.command_count)."""
    cmds, _gaps = event_script.script_code(buf, words, commands)
    starts: dict[int, int] = {}
    for n, at in sorted(event_script.labels(buf).items()):
        starts.setdefault(at, n)
    window = Window(font, draw)
    label = None
    out: list[Message] = []
    for c in cmds:
        if c.offset in starts:
            label = starts[c.offset]
            window.reset()
        if c.id == event_script.TEXT:
            out.append(window.message(buf, c.offset, words, char_table, table, label))
        elif c.id == ANSWER:
            first, second = answer_strings(buf, c.offset)
            pair = tuple(system_strings.decode(buf, p, words, char_table, table,
                                               font.characters).text
                         for p in (first, second))
            out.append(Message(c.offset, label, answers=pair))
    return out


# -- the picture --------------------------------------------------------------

def row_places(places: int, layout: Layout = US_LAYOUT) -> tuple[int, int, int]:
    """(text column, cells shown, arrow x) for the face places up
    (MessageRowDisp)."""
    for bit, column, cells, arrow in layout.places:
        if places & bit:
            return column, cells, arrow
    return layout.no_place


def cell_runs(column: int, row: int, cells: int, place: int) -> list[tuple[int, int, int, int]]:
    """font_cell_run_set (0x80016230): `cells` cells from VRAM place
    `place`, drawn from grid (column, row), as (grid column, grid row,
    first cell, count). A run that reaches its line's end (block + cells
    >= 16) is split there, the rest from the next line 2 * its first part's
    count grid columns on, a grid row lower past column 40. A rest of no
    cells (block + cells == 16) would give font_cell_set a count of 0,
    which neither program's layout reaches: it is left out."""
    block = place & 0xF
    if block + cells < LINE_BLOCKS:
        return [(column, row, 0, cells)]
    first = LINE_BLOCKS - block
    x, y = column + 2 * first, row
    if x >= GRID_COLUMNS:
        x, y = x - GRID_COLUMNS, y + 1
    runs = [(column, row, 0, first)]
    if cells > first:
        runs.append((x, y, first, cells - first))
    return runs


def row_image(row: bytes, colours) -> Image.Image:
    """One text row, 17 cells across, through row 507 from colour 0xE0."""
    cells = np.frombuffer(bytes(row[:ROW_CELLS * CELL_BYTES]), np.uint8).reshape(ROW_CELLS, CELL, 8)
    index = np.empty((ROW_CELLS, CELL, CELL), np.uint8)
    index[:, :, 0::2] = cells & 0xF
    index[:, :, 1::2] = cells >> 4
    index = index.transpose(1, 0, 2).reshape(CELL, ROW_CELLS * CELL)
    palette = np.array([tuple(colours[TEXT_CLUT_FIRST + n]) for n in range(16)], np.uint8)
    return Image.fromarray(palette[index], "RGBA")


def _paste(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    dst.paste(src, (x, y), src)


def draw(screen: Screen, colours, face_image: Callable[[int], Image.Image | None],
         arrow: bool | None = None, layout: Layout = US_LAYOUT) -> Image.Image:
    """The screen's rows TOP .. TOP + HEIGHT - 1 with the window on them, on
    a clear background, laid out by `layout` (`layout_of` the program).
    `colours` is row 507 (system_dat.colours); `face_image` gives a face's
    64 x 64 picture or None. The arrow is drawn at a prompt unless `arrow`
    says otherwise."""
    im = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shade_top = 0xB8 - SHADE_HEIGHT * 4 - TOP
    im.paste((0, 0, 0, SHADE_ALPHA), (0, shade_top, WIDTH, shade_top + SHADE_HEIGHT * 8))
    column, cells, arrow_x = row_places(screen.places, layout)
    for k in range(ROWS):
        row = row_image(screen.rows[k * ROW_BYTES:(k + 1) * ROW_BYTES], colours)
        for x, y, first, count in cell_runs(column, TEXT_ROW + 2 * k, cells, k * ROW_CELLS):
            _paste(im, row.crop((first * CELL, 0, (first + count) * CELL, CELL)),
                   x * 8, y * 8 - TOP)
    for place, face in screen.faces.items():
        pic = face_image(face)
        if pic is not None and place in (0x10, 0x20):
            gx, gy = layout.faces[place]
            _paste(im, pic, gx * 8, gy * 8 - TOP)
    if arrow if arrow is not None else screen.why == "prompt":
        y = layout.arrow_y - TOP
        ImageDraw.Draw(im).polygon([(arrow_x, y), (arrow_x + 8, y), (arrow_x + 4, y + 5)],
                                   fill=ARROW_COLOUR)
    return im


#: A string's controls `string_image` acts on: the next row, a pen move,
#: a style (MessageControlRun's; font_control_run (0x8002710C) the same).
ROW_BREAK, MOVE, STYLE = 0xFF02, 0xF900, 0xFC00


def string_image(font: Font, codes: list[int], colours,
                 tint: tuple[int, int, int] | None = None) -> Image.Image | None:
    """`codes` (system_strings.codes: a character, or a control from
    0xF000 up) put as font_code_put (0x80026D64) puts them with mode 1, a
    row of 16 pixels at a time: each glyph its columns, a pen move (0xF9nn)
    n pixels on, a style (0xFCnn) ORed into the pixels, 0xFF02 the next
    row. Every other control draws nothing; splices are the caller's.
    Coloured as row 507 from colour 0xE0. With `tint`, the pixels of the
    kanji ROM's glyphs that `font.rom_font` drew are blended half with it.
    None for no glyph at all."""
    rows: list[list[tuple[list[int], bool]]] = [[]]     # row -> (16 indices, tinted)
    colbits = 0
    for code in codes:
        if code == ROW_BREAK:
            rows.append([])
        elif code & 0xFF00 == MOVE:
            rows[-1] += [([0] * CELL, False) for _ in range(code & 0xFF)]
        elif code & 0xFF00 == STYLE:
            colbits = (code & 3) << 2
        elif code < 0xF000:
            drawn = font.from_rom(code) and code != WIDE_SPACE and not font.boxed(code)
            for column in font.columns(code):
                pixels = [0] * CELL
                for j, px in column:
                    pixels[j] = px | colbits
                rows[-1].append((pixels, drawn))
    width = max(len(r) for r in rows)
    if not width:
        return None
    index = np.zeros((CELL * len(rows), width), np.uint8)
    tinted = np.zeros(index.shape, bool)
    for k, r in enumerate(rows):
        for x, (pixels, drawn) in enumerate(r):
            index[k * CELL:(k + 1) * CELL, x] = pixels
            tinted[k * CELL:(k + 1) * CELL, x] = drawn
    palette = np.array([tuple(colours[TEXT_CLUT_FIRST + n]) for n in range(16)], np.uint8)
    rgba = palette[index]
    if tint is not None:
        at = tinted & (index != 0)
        rgba[at, :3] = (rgba[at, :3].astype(np.uint16) + np.array(tint, np.uint16)) // 2
    return Image.fromarray(rgba, "RGBA")
