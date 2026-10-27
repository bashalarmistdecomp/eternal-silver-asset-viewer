"""A map's bg changes: the rectangles of tiles and attributes it copies
over its own, the change that opens a door or leaves a place changed for
good.

THE TABLE -- resource_map_enter_table_set (0x80020B8C) copies a map's
type-9 payload whole to 0x801E6B00; GameStart (0x80055B60) points
g_MapBgChangeTable (0x800B8CFC) at 0x801E7500, so the table is the
payload from +0xA00 (the enter rows lie at +0, the party places at
+0x580). It starts with 0x80 words stored high byte first
(u16_bytes_swap (0x80013EA0)): word n, when it is not 0, is where change
n's row lies, counted in 16-bit words from the table's start.

A ROW (MapBgChangeRow), every place and size in 8-px attribute cells:

    +0  dest x    +1  dest y    +2  width    +3  height
    +4  story bit less 0x480, 0 for none
    +5  the number of sources n    +6  frames between two copies
    +7  the sound played with the first copy, 0 for none
    +8  n x (source x, source y)

MapBgChangeCopy (0x80059B0C), the one caller of bg_both_copy
(0x800153A0), copies the rectangle from a source: the tile
words of the 16-px tile plane (every value halved, bg_copy (0x80015224))
and the attribute cells as they are (bg_attribute_copy (0x800157DC)).
MapBgChangeStart (0x80059900) plays a row from its first source, one
copy every max(interval, 1) frames (MapBgChangeStep (0x80059A18)), and
sets its story bit first: a row with a bit runs once, and the bit is its
memory. MapBgChangeStoryBitsCopy (0x80059B6C), on every map change, load,
movie and battle's end, copies the LAST source of every row whose bit is
set, rows 0 to 0x7F in order, at once and silently. A row without a bit
is never copied again: the map's planes reload closed.

WHAT STARTS ONE -- an attribute cell whose event word (cell & 0x7FF,
MapAttributeFind (0x80069A20)) has kind 3 (bits 7..10) starts change
(word & 0x7F) when the party steps on it (MapAttributeRun (0x800590C0));
script command 0x28 starts one too (ScriptCommandMapBgChangeStart
(0x8005DD84)), and a script that sets a row's bit leaves the change for
the next copy of the bits.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from decoders.plugins.SLUS_006_28.formats import command_list

TABLE_AT = 0xA00            # in the type-9 payload: 0x801E7500 - 0x801E6B00
CHANGES = 0x80              # MapBgChangeStoryBitsCopy walks ids 0..0x7F
BIT_BASE = 0x480            # the row's +4 is the story bit less this
ROW_HEAD = 8
EVENT_MASK = 0x7FF          # MapAttributeFind: id = cell & 0x7FF
EVENT_KIND_SHIFT = 7
EVENT_ARG = 0x7F
KIND_BG_CHANGE = 3          # MapAttributeRun's case 3


@dataclass(frozen=True)
class BgChange:
    """One row of the table: a rectangle and the places it is copied from."""
    id: int
    x: int                  # destination, 8-px cells
    y: int
    w: int
    h: int
    bit: int | None         # 0x481..0x57F, or None
    interval: int           # as stored; 0 acts as 1
    sound: int              # 0: none
    sources: tuple          # ((x, y), ...) in 8-px cells, in copy order

    @property
    def frames(self) -> int:
        """Field frames between two copies (MapBgChangeStep)."""
        return max(self.interval, 1)


def changes(payload: bytes) -> list[BgChange]:
    """The rows of a type-9 payload's bg change table, by id. A payload too
    short to hold the table holds none; a row running past the payload is
    left out."""
    t = payload[TABLE_AT:]
    if len(t) < 2 * CHANGES:
        return []
    out = []
    for n in range(CHANGES):
        (word,) = struct.unpack_from(">H", t, 2 * n)
        if not word:
            continue
        o = 2 * word
        if o + ROW_HEAD > len(t):
            continue
        dx, dy, w, h, bit, count, interval, sound = t[o:o + ROW_HEAD]
        if o + ROW_HEAD + 2 * count > len(t):
            continue
        sources = tuple((t[o + ROW_HEAD + 2 * k], t[o + ROW_HEAD + 1 + 2 * k])
                        for k in range(count))
        out.append(BgChange(id=n, x=dx, y=dy, w=w, h=h,
                            bit=BIT_BASE + bit if bit else None,
                            interval=interval, sound=sound, sources=sources))
    return out


def map_changes(raw_map: bytes) -> list[BgChange]:
    """A map resource's bg changes: its last type-9 command's (the one the
    load leaves in place)."""
    c = command_list.effective(raw_map, command_list.MAP_ENTER_TABLES)
    return changes(c.payload) if c is not None else []


def trigger_cells(att_plane: list[list[int]]) -> dict[int, list[tuple[int, int]]]:
    """Change id -> the attribute cells (x, y) whose event starts it when
    the party steps on them (kind 3; an argument of 0 is no event)."""
    out: dict[int, list[tuple[int, int]]] = {}
    for y, row in enumerate(att_plane):
        for x, cell in enumerate(row):
            ev = cell & EVENT_MASK
            if ev >> EVENT_KIND_SHIFT == KIND_BG_CHANGE and ev & EVENT_ARG:
                out.setdefault(ev & EVENT_ARG, []).append((x, y))
    return out


def copy(plane: list[list[int]], dx: int, dy: int, sx: int, sy: int, w: int, h: int) -> None:
    """bg_copy / bg_attribute_copy over a plane, in place: cell by cell in
    row order from the source rectangle, a cell off the plane read as 0.
    The tile plane takes every value halved (16-px tiles)."""
    rows = len(plane)
    for j in range(h):
        for i in range(w):
            ty, tx = sy + j, sx + i
            v = plane[ty][tx] if 0 <= ty < rows and 0 <= tx < len(plane[ty]) else 0
            y, x = dy + j, dx + i
            if 0 <= y < rows and 0 <= x < len(plane[y]):
                plane[y][x] = v


def apply(tiles: list[list[int]], att: list[list[int]] | None, row: BgChange,
          source: int = -1) -> None:
    """One copy of a row, both planes in place: its source `source` (the
    last by default, as MapBgChangeStoryBitsCopy copies it)."""
    sx, sy = row.sources[source]
    copy(tiles, row.x // 2, row.y // 2, sx // 2, sy // 2, row.w // 2, row.h // 2)
    if att is not None:
        copy(att, row.x, row.y, sx, sy, row.w, row.h)
