"""Tier 1 for what a player can see of a map — made-up attribute planes,
place rows and script commands, no game data.

What this CAN catch: the two party boxes, limit bytes read as pixels, a
place row read (and a row of zeros or one past the payload refused), a
0x27 command's own row against a row number, the box test's cells and a
diagonal let through only in its own corner, the first event id in row
order (an id with no argument or a kind of 10 passed over), a label's
ways through jumps, calls and both arms of a story-bit test, the view
held at the limits and cut to them, a wall the walk does not cross, a
move cell that carries the walk to its place row, kind-5 and kind-4
cells by what their label does, a way in that leads nowhere, two planes'
walks put together, and each camera area cut to what it shows.

What it CANNOT catch: whether those are the rules of MapAttributeFreeCheck
(0x800692D4), MapAttributeFind (0x80069A20), MapAttributeRun
(0x800590C0), MapPartyBoxSet (0x8006497C), MapViewGoalGet (0x80069080)
and ScriptCommandMapPartyPlace (0x8005DCBC): both sides of every
assertion were written together. See decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import map_reach as mr

LEFT_ROOM = (0, 640, 0, 224)        # a strip two screens wide


def _plane() -> list[list[int]]:
    return [[0] * mr.CELLS for _ in range(mr.CELLS)]


def _column(plane, tx: int, value: int, rows: int = 28) -> list[list[int]]:
    for ty in range(rows):
        plane[ty][tx] = value
    return plane


def _free(plane, party_kind, x, y) -> bool:
    import numpy as np
    m = mr.free_mask(np.array(plane, dtype=np.int32), mr.party_box(party_kind))
    return bool(m[y // mr.LATTICE, x // mr.LATTICE])


def test_the_party_boxes_and_the_limits():
    assert mr.party_box(0) == (0, 0, 6, 4)
    assert mr.party_box(1) == mr.party_box(2) == (0, -1, 8, 5)
    assert mr.limits_px(2, 41, 0, 27) == (16, 336, 0, 224)


def test_a_place_row():
    payload = bytearray(0xA00)
    at = mr.PLACE_ROWS_AT + 2 * mr.PLACE_ROW
    payload[at:at + 9] = bytes([0, 0, 2, 41, 0, 27, 20, 12, 1])
    assert mr.place_row(bytes(payload), 2, "row 2") == mr.Start(160, 96, (16, 336, 0, 224), "row 2")
    assert mr.place_row(bytes(payload), 0, "row 0") is None          # zeros: no place
    assert mr.place_row(bytes(payload), mr.PLACE_ROWS, "past") is None
    assert mr.place_row(bytes(payload[:at + 4]), 2, "short") is None
    assert list(mr.payload_places(bytes(payload))) == [2]


def test_a_0x27_command_carries_its_own_row_or_names_one():
    c = bytearray(0xE)
    c[0], c[5:9], c[9], c[0xA] = mr.PARTY_PLACE, bytes([1, 39, 0, 27]), 10, 12
    row, own = mr.script_place(bytes(c), 0)
    assert row == 0 and (own.x, own.y, own.limits) == (80, 96, (8, 320, 0, 224))
    c[2] = 5
    assert mr.script_place(bytes(c), 0) == (5, None)


def test_a_diagonal_is_let_through_in_its_own_corner_only():
    plane = _plane()
    plane[1][1] = 0x0800                    # the box's first row and column
    assert not _free(plane, 0, 14, 12)      # (x0 & 7) + (y0 & 7) = 0
    assert _free(plane, 0, 20, 14)          # 6 + 2 >= 7
    plane[1][1] = 0x1800                    # a last-row, last-column diagonal
    assert not _free(plane, 0, 20, 14)
    plane[1][1] = 0
    plane[2][3] = 0x1800                    # ... where it belongs
    assert _free(plane, 0, 20, 14)          # ((x1 - 1) & 7) + ((y1 - 1) & 7) = 2
    plane[2][3] = mr.FULL
    assert not _free(plane, 0, 20, 14)


def test_the_first_event_in_row_order():
    import numpy as np
    plane = _plane()
    plane[1][2] = (mr.LEAVE_KIND << 7) | 5
    plane[1][1] = (mr.LABEL_KIND << 7) | 3
    box = mr.party_box(0)
    ev = mr.event_ids(np.array(plane, dtype=np.int32), box)
    assert ev[7, 10] == (mr.LABEL_KIND << 7) | 3          # the spot (20, 14)
    plane[1][1] = mr.LABEL_KIND << 7                       # no argument
    ev = mr.event_ids(np.array(plane, dtype=np.int32), box)
    assert ev[7, 10] == (mr.LEAVE_KIND << 7) | 5
    plane[1][2] = (10 << 7) | 1 | mr.FULL                  # kind 10; the shape bits are not the id's
    ev = mr.event_ids(np.array(plane, dtype=np.int32), box)
    assert ev[7, 10] == 0


def test_the_view_is_held_at_the_limits_and_cut_to_them():
    whole = (0, mr.PLANE, 0, mr.PLANE)
    assert mr.view(100, 100, whole) == (0, 0, 320, 224)
    assert mr.view(1000, 1000, whole) == (840, 880, 1160, 1104)
    assert mr.view(2040, 2040, whole) == (1728, 1824, 2048, 2048)
    assert mr.view(100, 50, (0, 200, 0, 100)) == (0, 0, 200, 100)
    assert mr.view(170, 50, (0, 200, 0, 100)) == (0, 0, 200, 100)


def _script():
    """Made-up commands: label n at the offsets below."""
    buf = bytearray(0x40)
    cmds = []

    def put(offset, cid, size, target=None):
        buf[offset] = cid
        if target is not None:
            struct.pack_into("<H", buf, offset + 2, target)
        cmds.append(es.Command(offset=offset, id=cid, end=offset + size))
    put(0x00, 0x26, 4)                      # label 1: a map change
    put(0x04, mr.LABEL_RETURN, 2)           # label 2: returns
    put(0x06, 0x0B, 4, 1)                   # label 3: a bit test to label 1 ...
    put(0x0A, mr.LABEL_RETURN, 2)           # ... else returns
    put(0x0C, 0x0B, 4, 1)                   # label 4: a bit test to label 1 ...
    put(0x10, mr.PARTY_PLACE, 4)            # ... else a move
    put(0x14, mr.LABEL_CALL, 4, 2)          # label 5: calls label 2, then
    put(0x18, 0x26, 4)                      # a map change
    put(0x1C, mr.LABEL_JUMP, 4, 6)          # label 6: jumps to itself
    put(0x20, 0x10, 2)                      # label 7: some command, then
    put(0x22, 0x42, 6)                      # another script
    labels = {1: 0x00, 2: 0x04, 3: 0x06, 4: 0x0C, 5: 0x14, 6: 0x1C, 7: 0x20}
    return bytes(buf), {c.offset: c for c in cmds}, labels


def test_what_a_label_does():
    buf, cmds, labels = _script()
    got = {n: mr.label_act(buf, cmds, labels, n) for n in range(1, 9)}
    assert got == {1: mr.GONE, 2: mr.STAYS, 3: mr.STAYS, 4: mr.GONE, 5: mr.GONE,
                   6: mr.STAYS, 7: mr.STAYS, 8: mr.STAYS}


def _walk(plane, acts=None, places=None, starts=None, party_kind=1):
    starts = starts or [mr.Start(100, 100, LEFT_ROOM, "in")]
    return mr.walk(plane, party_kind, starts, acts or {}, places or {})


def test_the_camera_shows_the_limits_and_no_more():
    r = _walk(_plane())
    assert r.bbox == (0, 0, 640, 224)
    assert int(r.seen.sum()) == 640 * 224
    assert r.blocked == []


def test_a_wall_is_not_crossed():
    # The box (half width 8) meets cell 40 from x = 313 on: the lead stops
    # at 312, and the view at 312 + 160.
    r = _walk(_column(_plane(), 40, mr.FULL))
    assert r.seen[:224, :472].all() and not r.seen[:, 472:].any()


def test_a_move_cell_carries_the_walk_to_its_place_row():
    plane = _column(_plane(), 40, mr.FULL)
    plane[10][10] = (mr.MOVE_KIND << 7) | 3
    there = mr.Start(560, 100, (320, 960, 0, 224), "place row 3")
    r = _walk(plane, places={3: there})
    assert r.seen[:224, :960].all()
    assert there in r.starts


def test_kind_5_and_kind_4_cells_by_what_their_label_does():
    def seen_right(kind, act):
        plane = _column(_plane(), 40, (kind << 7) | 7)
        return bool(_walk(plane, acts={7: act}).seen[:, 500:].any())
    assert not seen_right(mr.PUSH_KIND, mr.STAYS)       # put back: a wall
    assert not seen_right(mr.PUSH_KIND, mr.GONE)        # taken away
    assert seen_right(mr.LABEL_KIND, mr.STAYS)          # a scene, walked past
    assert not seen_right(mr.LABEL_KIND, mr.GONE)
    plane = _column(_plane(), 40, (mr.LEAVE_KIND << 7) | 1)
    assert not _walk(plane).seen[:, 500:].any()


def test_a_way_in_that_leads_nowhere_shows_its_own_view():
    plane = _plane()
    for ty in range(5, 21):
        for tx in range(5, 21):
            plane[ty][tx] = mr.FULL
    start = mr.Start(100, 100, (0, mr.PLANE, 0, mr.PLANE), "stuck")
    r = _walk(plane, starts=[start])
    assert r.blocked == [start]
    assert r.bbox == (0, 0, 320, 224) and int(r.seen.sum()) == 320 * 224


def test_two_planes_put_together():
    walled, open_ = _column(_plane(), 40, mr.FULL), _plane()
    r = mr.reach([walled, open_], 1, [mr.Start(100, 100, LEFT_ROOM, "in")], {}, {})
    assert r.seen[:224, :640].all()
    assert r.spots == _walk(walled).spots + _walk(open_).spots
    assert mr.reach([], 1, [], {}, {}).bbox is None


def test_views_are_put_together():
    seen = mr.seen_mask({(0, 0, 10, 10), (5, 5, 15, 15), (20, 20, 20, 30)})
    assert int(seen.sum()) == 100 + 100 - 25


def test_each_camera_area_cut_to_what_it_shows():
    plane = _column(_plane(), 40, mr.FULL)                       # the left room ends at x 312 + 160
    house = mr.Start(1100, 100, (1000, 1640, 0, 224), "a house")
    r = _walk(plane, starts=[mr.Start(100, 100, LEFT_ROOM, "in"), house])
    assert r.areas == [(0, 0, 472, 224), (1000, 0, 1640, 224)]
