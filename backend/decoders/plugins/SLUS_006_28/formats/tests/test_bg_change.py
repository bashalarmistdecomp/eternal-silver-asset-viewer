"""Tier 1 for a map's bg change table — made-up tables, no game data.

What this CAN catch: the table's place in the type-9 payload (+0xA00),
its index read high byte first and counted in 16-bit words, an empty
slot skipped, a row's fields and sources in order, the story bit as
0x480 + the byte, a row running past the payload left out, the kind-3
event cells found (and an argument of 0 not), and a copy halving every
value for the tile plane but not for the attribute plane, a cell off the
plane read as 0.

What it CANNOT catch: whether that is the layout MapBgChangeStart
(0x80059900), MapBgChangeStoryBitsCopy (0x80059B6C) and bg_both_copy
(0x800153A0) read: both sides were written together. See
decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.formats import bg_change as bc


def _payload(rows: dict[int, bytes]) -> bytes:
    """A type-9 payload with the given rows at the table's end."""
    index = [0] * bc.CHANGES
    body = b""
    at = 2 * bc.CHANGES
    for n, row in rows.items():
        index[n] = (at + len(body)) // 2
        body += row + (b"\0" if len(row) % 2 else b"")
    return bytes(bc.TABLE_AT) + struct.pack(f">{bc.CHANGES}H", *index) + body


def test_rows_by_id_with_their_sources():
    # change 10: 6 x 4 cells at (50, 30), bit 0x483, one source (70, 90)
    # change 3: 2 x 4 at (32, 10), no bit, two sources, 4 frames apart, sound 16
    p = _payload({10: bytes([50, 30, 6, 4, 3, 1, 1, 0, 70, 90]),
                  3: bytes([32, 10, 2, 4, 0, 2, 4, 16, 96, 108, 98, 108])})
    rows = bc.changes(p)
    assert [r.id for r in rows] == [3, 10]
    door, cave = rows
    assert (cave.x, cave.y, cave.w, cave.h, cave.bit, cave.sources) == (50, 30, 6, 4, 0x483, ((70, 90),))
    assert (door.bit, door.interval, door.frames, door.sound) == (None, 4, 4, 16)
    assert door.sources == ((96, 108), (98, 108))


def test_interval_0_acts_as_1_and_a_short_payload_holds_nothing():
    rows = bc.changes(_payload({1: bytes([0, 0, 2, 2, 0, 1, 0, 0, 4, 4])}))
    assert rows[0].frames == 1
    assert bc.changes(bytes(bc.TABLE_AT + 10)) == []


def test_a_row_past_the_payload_is_left_out():
    p = _payload({2: bytes([0, 0, 2, 2, 0, 5, 0, 0, 4, 4])})   # 5 sources, 1 given
    assert bc.changes(p) == []


def test_kind_3_cells_name_their_change():
    plane = [[0] * 4 for _ in range(3)]
    plane[1][2] = (3 << 7) | 7           # starts change 7
    plane[2][0] = 0x8000 | (3 << 7) | 7  # cover bit above the event word
    plane[0][1] = 3 << 7                 # argument 0: no event
    plane[0][3] = (4 << 7) | 7           # kind 4: a script
    assert bc.trigger_cells(plane) == {7: [(2, 1), (0, 2)]}


def test_a_copy_halves_for_the_tile_plane_and_reads_0_off_it():
    tiles = [[10 * y + x for x in range(4)] for y in range(4)]
    att = [[100 + 10 * y + x for x in range(8)] for y in range(8)]
    row = bc.BgChange(id=1, x=0, y=0, w=4, h=2, bit=None, interval=0, sound=0,
                      sources=((4, 6), (6, 6)))
    bc.apply(tiles, att, row)                     # the last source: (6, 6)
    assert tiles[0][:2] == [33, 0]                # (3, 3), then off the plane
    assert att[0][:4] == [166, 167, 0, 0] and att[1][:2] == [176, 177]
    bc.apply(tiles, None, row, source=0)          # (4, 6) -> tiles (2, 3)
    assert tiles[0][:2] == [32, 33]
