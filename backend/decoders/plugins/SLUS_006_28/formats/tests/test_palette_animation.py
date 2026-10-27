"""Tier 1 for a map's palette animation — made-up tables, strips and
rows, no game data.

What this CAN catch: the set table's byte pair read at (set - 1) * 2, a
seed row's fields and a mode-0 seed left stopped, the copy rows walked to
their end, the tables read where the Japanese program keeps them, a
strip cut from the block at its place and one running past it refused, a
slot's timer and frame wrap, the three modes' changes (a strip's word 0
copied as it is), slots stepped in order over shared colours, a period,
and row 508 taken again only for the copied CLUTs.

What it CANNOT catch: whether those are the rules of
palette_animation_set (0x800262FC), palette_animation_copy_set
(0x8002628C), palette_animation_step (0x800263F4) and palette_update
(0x80020134): both sides of every assertion were written together. See
decoders/testing.py.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.formats import palette_animation as pa


def _seed(mode, delay, frames, first, count, source=0) -> bytes:
    return struct.pack("<BBBBHH", mode, delay, frames, first, count, source)


def _image(sets_at=pa.SETS_ADDR, rows_at=pa.ROWS_ADDR, copy_at=pa.COPY_ROWS_ADDR,
           image=None) -> bytearray:
    image = image if image is not None else bytearray(
        max(sets_at, rows_at, copy_at) - pa.EXE_BASE + 0x100)
    s, r, c = sets_at - pa.EXE_BASE, rows_at - pa.EXE_BASE, copy_at - pa.EXE_BASE
    image[s + 4:s + 6] = bytes([3, 2])                 # set 3: seed rows 3 and 4
    image[r + 3 * 8:r + 4 * 8] = _seed(2, 6, 4, 40, 4)
    image[r + 4 * 8:r + 5 * 8] = _seed(1, 5, 3, 100, 2, source=7)
    image[s + 6:s + 8] = bytes([5, 1])                 # set 4: a mode-0 seed
    image[r + 5 * 8:r + 6 * 8] = _seed(0, 5, 3, 9, 2)
    image[c:c + 9] = bytes([2, 1, 1, 3, 12, 2, 0, 0, 0])   # sets 2 and 3, then the end
    return image


def test_a_set_starts_its_seed_rows_in_order():
    got = pa.animations(bytes(_image()), 3)
    assert [(a.mode, a.delay, a.frames, a.first, a.count, a.source) for a in got] == [
        (2, 6, 4, 40, 4, 0), (1, 5, 3, 100, 2, 7)]
    assert pa.animations(bytes(_image()), 4) == []     # mode 0: stopped
    assert pa.animations(bytes(_image()), 0) == []


def test_the_copy_rows_end_at_set_0():
    image = bytes(_image())
    assert pa.copy_range(image, 3) == (12, 2)
    assert pa.copy_range(image, 2) == (1, 1)
    assert pa.copy_range(image, 5) is None and pa.copy_range(image, 0) is None


def test_the_japanese_program_keeps_the_tables_elsewhere(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    at = {n: programs.JP_TABLES[n].addr for n in (
        "g_PaletteAnimationSets", "g_PaletteAnimationRows", "g_PaletteAnimationCopyRows")}
    image = jp_image(max(at.values()) - pa.EXE_BASE + 0x100)
    _image(*at.values(), image=image)
    assert [a.first for a in pa.animations(bytes(image), 3)] == [40, 100]
    assert pa.copy_range(bytes(image), 3) == (12, 2)


def test_a_strip_is_cut_from_its_place_in_the_block():
    slots = pa.animations(bytes(_image()), 3)
    block = bytes(0x20) + struct.pack("<20H", *range(0x100, 0x114))
    pa.with_strips(slots, block, 0x20)
    assert slots[0].strip == ()                        # a turn reads none
    assert slots[1].strip == tuple(range(0x107, 0x10D))     # 3 frames of 2 from 7
    with pytest.raises(ValueError):
        pa.with_strips(pa.animations(bytes(_image()), 3), block[:0x2A], 0x20)


def test_the_three_modes_and_the_timer():
    row = list(range(256))
    up = pa.PaletteAnimation(mode=pa.MODE_UP, delay=2, frames=3, first=10, count=4, source=0)
    assert not up.step(row) and row[10:14] == [10, 11, 12, 13]     # timer 1 of 2
    assert up.step(row) and row[10:14] == [13, 10, 11, 12]
    down = pa.PaletteAnimation(mode=pa.MODE_DOWN, delay=0, frames=1, first=20, count=3, source=0)
    assert down.step(row) and row[20:23] == [21, 22, 20]           # delay 0 steps each frame
    copy = pa.PaletteAnimation(mode=pa.MODE_COPY, delay=1, frames=3, first=30, count=2,
                               source=0, strip=(1, 2, 0, 4, 5, 6))
    copy.step(row)
    assert row[30:32] == [0, 4]        # frame 1 first; a word 0 is copied as it is
    copy.step(row)
    copy.step(row)
    assert copy.frame == 0 and row[30:32] == [1, 2]     # frame 0 on the wrap
    assert (up.period, down.period, copy.period) == (8, 3, 3)


def test_slots_step_in_order_over_shared_colours():
    row = list(range(256))
    slots = [pa.PaletteAnimation(mode=pa.MODE_COPY, delay=1, frames=2, first=0, count=4,
                                 source=0, strip=(50, 51, 52, 53, 60, 61, 62, 63)),
             pa.PaletteAnimation(mode=pa.MODE_UP, delay=1, frames=1, first=2, count=2, source=0)]
    assert pa.step(slots, row)
    assert row[:4] == [60, 61, 63, 62]     # copied, then turned


def test_row_508_takes_only_the_copied_cluts_again():
    row = [0x100 + i for i in range(256)]
    cluts = [[7] * 16 for _ in range(16)]
    got = pa.second_row(row, cluts, (2, 1))
    assert got[1] == [7] * 16 and got[3] == [7] * 16
    assert got[2][0] == 0 and got[2][1] == 0x8121 and got[2][15] == 0x812F
    assert pa.second_row(row, cluts, None) == cluts
