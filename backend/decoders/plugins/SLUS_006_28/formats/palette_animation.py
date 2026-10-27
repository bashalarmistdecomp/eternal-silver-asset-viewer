"""A map's palette animation: colours of the tile palette's second row
copied in from a strip, or turned round, every few frames.

THE SET -- MapLoad (0x80068A10) passes the area record's byte +5 to
palette_animation_set (0x800262FC), after the map's palette is loaded. It
stops the eight slots of g_PaletteAnimations (0x800E4808), and for a set
other than 0 looks up the row-508 copy (palette_animation_copy_set
(0x8002628C)) and starts the set's seed rows: g_PaletteAnimationSets
(0x800AFD4C) holds a byte pair {first seed row, count} a set at
[(set - 1) * 2], and seed rows first .. first + count - 1 of
g_PaletteAnimationRows (0x800AFD9C) go to slots 0 .. count - 1 with timer
and frame 0. A seed row (PaletteAnimationSeed) is

    +0 u8 mode   1 copy a frame of the strip, 2 turn the colours up one,
                 3 turn them down one
    +1 u8 delay  frames between two steps
    +2 u8 frames steps before the frame counter wraps
    +3 u8 first  the first colour, in row 1 of the colour buffer
    +4 u16 count the number of colours
    +6 u16 source  mode 1: the strip's first colour

THE STEP -- palette_animation_step (0x800263F4), every field frame, takes
slots 0 to 7 in order (two slots of a set may share colours: the order
shows), and for each running slot counts timer up to delay; on reaching
it, timer = 0 and frame steps (0 again at frames), and the colours
first .. first + count - 1 of row 1 change by the mode (`step`). The row
is VRAM row 501, re-sent whole (palette_update (0x80020134)): every tile
drawn through it (word bit 12) changes colour, and nothing else does; the
roofs' rows 510 / 511 are never re-sent.

THE STRIP -- g_PaletteAnimationCols (0x800B8B04), which GameStart
(0x80055B60) points into SYSTEM.DAT's type-1 block (system_dat
`block_places`). Mode 1 copies frame * count words from source on, as
they are: a word 0 there is a hole in the tiles (palette_zero_fix
(0x80020830) ran at the load, not here).

THE COPY -- g_PaletteAnimationCopyRows (0x800B0334), three-byte rows {set,
first, count} ended by a set of 0: while the set has a row,
palette_update copies CLUTs first .. first + count - 1 of row 1 to VRAM
row 508 every frame, bit 15 set on every colour and colour 0 of each CLUT
made 0 -- the second layer's CLUTs (world_map `layer2_clut_words`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from decoders.plugins.SLUS_006_28.formats import world_map as wm
from decoders.plugins.SLUS_006_28.records.programs import address

EXE_BASE = 0x80011000
SETS_ADDR = 0x800AFD4C          # g_PaletteAnimationSets
ROWS_ADDR = 0x800AFD9C          # g_PaletteAnimationRows
COPY_ROWS_ADDR = 0x800B0334     # g_PaletteAnimationCopyRows
SLOTS = 8
SEED = 8
COPY_ROW = 3
COPY_ROWS_MAX = 0x40            # a walk past this many rows is not a table
MODE_COPY, MODE_UP, MODE_DOWN = 1, 2, 3
ROW = 1                         # the buffer row a step writes: VRAM row 501
COLOURS = 256
U8 = 0xFF


@dataclass
class PaletteAnimation:
    """One slot of g_PaletteAnimations (palette.h PaletteAnimation)."""
    mode: int
    delay: int
    frames: int
    first: int
    count: int
    source: int
    timer: int = 0
    frame: int = 0
    #: mode 1: the strip's frames * count words from `source` on
    strip: tuple = field(default=(), repr=False)

    @property
    def period(self) -> int:
        """Frames before the slot's colours come round again: a strip's
        frames, or a turn's count, of max(delay, 1) frames each."""
        return max(self.delay, 1) * (self.frames if self.mode == MODE_COPY else self.count)

    def step(self, row: list[int]) -> bool:
        """palette_animation_step for this slot over `row` (row 1, 256
        words), in place. True when the slot stepped. Colours past the
        row's end are not written (no seed reaches them)."""
        self.timer = (self.timer + 1) & U8
        if self.timer < self.delay:
            return False
        self.timer = 0
        self.frame = (self.frame + 1) & U8
        if self.frame >= self.frames:
            self.frame = 0
        n = min(self.count, COLOURS - self.first)
        if n <= 0:
            return True
        q = self.first
        if self.mode == MODE_COPY:
            at = self.frame * self.count
            words = self.strip[at:at + n]
            row[q:q + len(words)] = words
        elif self.mode == MODE_UP:
            row[q:q + n] = [row[q + n - 1]] + row[q:q + n - 1]
        elif self.mode == MODE_DOWN:
            row[q:q + n] = row[q + 1:q + n] + [row[q]]
        return True


def animations(image: bytes, set_id: int) -> list[PaletteAnimation]:
    """palette_animation_set: the slots set `set_id` starts (0: none),
    read where the image's program keeps the tables (records.programs).
    A seed of mode 0 leaves its slot stopped."""
    if set_id == 0:
        return []
    sets = address(image, "g_PaletteAnimationSets", SETS_ADDR) - EXE_BASE
    rows = address(image, "g_PaletteAnimationRows", ROWS_ADDR) - EXE_BASE
    at = sets + ((set_id - 1) * 2 & U8)
    first, n = image[at], image[at + 1]
    out = []
    for k in range(min(n, SLOTS)):
        mode, delay, frames, col, count, source = struct.unpack_from(
            "<BBBBHH", image, rows + (first + k) * SEED)
        if mode:
            out.append(PaletteAnimation(mode=mode, delay=delay, frames=frames,
                                        first=col, count=count, source=source))
    return out


def copy_range(image: bytes, set_id: int) -> tuple[int, int] | None:
    """palette_animation_copy_set: the set's row-508 copy as (first CLUT,
    CLUTs), or None when it has none."""
    if set_id == 0:
        return None
    rows = address(image, "g_PaletteAnimationCopyRows", COPY_ROWS_ADDR) - EXE_BASE
    for k in range(COPY_ROWS_MAX):
        sid, first, count = struct.unpack_from("<bbb", image, rows + k * COPY_ROW)
        if sid == 0:
            return None
        if sid == set_id:
            return first, count
    raise ValueError(f"the copy rows run past {COPY_ROWS_MAX} rows without an end")


def with_strips(slots: list[PaletteAnimation], block: bytes, place: int) -> list[PaletteAnimation]:
    """The mode-1 slots given their strip words from the type-1 block,
    `place` being g_PaletteAnimationCols' place in it. ValueError when a
    strip runs past the block."""
    for s in slots:
        if s.mode != MODE_COPY:
            continue
        n = max(s.frames, 1) * s.count     # frames 0 still shows frame 0
        at = place + 2 * s.source
        if at + 2 * n > len(block):
            raise ValueError(f"the strip of colours {s.source}..{s.source + n - 1} runs past "
                             f"the type-1 block ({len(block):#x} bytes)")
        s.strip = struct.unpack_from(f"<{n}H", block, at)
    return slots


def step(slots: list[PaletteAnimation], row: list[int]) -> bool:
    """One field frame of palette_animation_step over row 1, in place:
    the slots in order. True when a slot stepped."""
    stepped = False
    for s in slots:
        stepped = s.step(row) or stepped
    return stepped


def second_row(row: list[int], cluts: list[list[int]], copy: tuple[int, int] | None) -> list[list[int]]:
    """Row 508 as palette_update leaves it: the copied CLUTs taken again
    from `row` (bit 15 set, colour 0 of each CLUT 0), the others as the
    load set them (`cluts`)."""
    out = [list(c) for c in cluts]
    if copy is None:
        return out
    first, count = copy
    fresh = wm.layer2_cluts(row)
    for n in range(max(first, 0), min(first + count, len(out))):
        out[n] = fresh[n]
    return out
