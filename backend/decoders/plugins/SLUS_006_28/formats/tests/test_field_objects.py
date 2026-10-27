"""Tier 1 for the map objects on their map — synthetic bytes, no game data.

What this CAN catch: a MapEnterRow or script command byte read at the
wrong place, the facing's + 1, the made rows packed and the chest's sprite
data 0, the twin's table index, the step list's u16 offset and its byte 1,
the roamers' bounds and speed entry by kind, the free check and class
probes' cell walk, the animation id a pose group and facing pick, the
timer kept within a group, a hold and a restart at an animation's end,
the twin kept as far from its end as the record, the two event flag
forms, an enter row's number, a chest's byte 0xB read as nothing, an
item, an amount's entry or a label, the lock of a chest facing 7, and the
party's sheet and box by party kind.

What it CANNOT catch: whether those rules are the functions'. Only
re-reading MapChange (0x8005922C), MapObjectsInit (0x800655C8),
MapObjectInit (0x800656CC), MapObjectKind7Run (0x80067F84),
MapObjectMoveSet (0x80065A2C),
MapAttributeClassGet (0x8006960C), MapAttributeFreeCheck (0x800692D4),
MapAnimationPoseSet (0x8006633C), MapAnimationSet (0x800663EC),
MapAnimationStart (0x80066468), MapObjectsAnimationStep (0x80065FD8) and
MapPartySpotSet (0x80064B8C) does that: both sides of every assertion
here were written together. See decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.formats import field_objects as fo


def _tables(twins=None) -> fo.FieldTables:
    # Made-up speed tables: entries 3..5 (what the tests' rows use) step 1,
    # 2 and 4 pixels every think; the rest are values no test should reach.
    return fo.FieldTables(twins=bytes(twins or range(0x40, 0x4E)),
                          speed_pixels=bytes([3, 5, 6, 1, 2, 4, 7, 9]),
                          speed_intervals=bytes([3, 5, 2, 1, 1, 1, 6, 4]),
                          dxs=(0, 1, 1, 1, 0, -1, -1, -1),
                          dys=(-1, -1, 0, 1, 1, 1, 0, -1))


#: The tables field_tables reads: name, US address, the bytes the test fills.
_PROGRAM_TABLES = (("g_MapTwinSpriteDataNumbers", fo.TWIN_NUMBERS_ADDR, 12),
                   ("g_MoveSpeedPixels", fo.SPEED_PIXELS_ADDR, 8),
                   ("g_MoveSpeedIntervals", fo.SPEED_INTERVALS_ADDR, 8),
                   ("g_MapFacingDxs", fo.FACING_DXS_ADDR, 8),
                   ("g_MapFacingDys", fo.FACING_DYS_ADDR, 8))


def test_field_tables_read_where_each_program_keeps_them(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    us = bytearray(fo.FACING_DYS_ADDR - fo.EXE_BASE + 8)
    jp = jp_image(programs.JP_TABLES["g_MapFacingDys"].addr - fo.EXE_BASE + 8)
    for image, where in ((us, lambda name, addr: addr),
                         (jp, lambda name, addr: programs.JP_TABLES[name].addr)):
        for k, (name, addr, n) in enumerate(_PROGRAM_TABLES):
            at = where(name, addr) - fo.EXE_BASE
            image[at:at + n] = bytes(range(0x10 * k + 1, 0x10 * k + 1 + n))
        t = fo.field_tables(bytes(image))
        assert t.twins[:12] == bytes(range(1, 13))
        assert t.speed_pixels == bytes(range(0x11, 0x19))
        assert t.speed_intervals == bytes(range(0x21, 0x29))
        assert (t.dxs, t.dys) == (tuple(range(0x31, 0x39)), tuple(range(0x41, 0x49)))


def _plane(cells=None) -> fo.Attributes:
    rows = [[0] * 0x100 for _ in range(0x100)]
    for (x, y), v in (cells or {}).items():
        rows[y][x] = v
    return fo.Attributes(rows)


def _definition(kind=1, sheet=0x20, story=0, mode=0, x=10, y=12, facing=4,
                box=(0, 0, 4, 4), number=3, speed=1, bounds=(-2, 3, -1, 4),
                step_list=0, look=(1, 2, 3, 4, 5), layer=0, think_bit=0) -> bytes:
    raw = bytearray(fo.DEFINITION_SIZE)
    raw[0] = ((kind - 1) & 0x3F) | layer | think_bit
    raw[1:4] = bytes([sheet, story, mode])
    raw[4:7] = bytes([x, y, facing])
    raw[7:0xB] = struct.pack("<2b2B", *box)
    raw[0xC], raw[0xD] = number, speed
    raw[0xE:0x12] = struct.pack("<bBbB", *bounds)
    raw[0x12] = step_list
    raw[0x14:0x19] = bytes(look)
    return bytes(raw)


def _block(defs: dict[int, bytes], step_lists: bytes = b"") -> bytes:
    block = bytearray(fo.STEP_LISTS_AT)
    for i, raw in defs.items():
        block[i * fo.DEFINITION_SIZE:(i + 1) * fo.DEFINITION_SIZE] = raw
    return bytes(block) + step_lists


# -- entries ------------------------------------------------------------------

def test_enter_row_bytes():
    e = fo.enter_row(bytes([0x23, 0x24, 1, 2, 3, 40, 5, 50, 30, 31, 6]), "here")
    assert (e.map, e.object_set, e.fade, e.sound) == (0x23, 0x24, 1, 2)
    assert e.limits == (3, 40, 5, 50)
    assert e.spot == (240, 248)
    assert e.facing == 7                            # the byte is the facing less 1
    assert e.limit_rect == (24, 41 * 8, 40, 51 * 8)
    assert fo.enter_row(bytes(10) + b"\xff", "x").facing == 0


def test_script_entry_takes_the_command_bytes():
    cmd = bytes([0x26, 0, 0, 0, 0, 0, 0x30, 9, 1, 2, 3, 4, 20, 21, 2, 7, 0x31])
    e = fo.script_entry(b"\x00\x00" + cmd, 2, "script")
    assert (e.map, e.object_set, e.fade, e.sound) == (0x30, 0x31, 9, 7)
    assert e.limits == (1, 2, 3, 4)
    assert (e.x, e.y, e.facing) == (20, 21, 3)


# -- the attribute probes -----------------------------------------------------

def test_free_check():
    open_ = _plane()
    assert fo.free_check(open_, 100, 100, 4, 4, 0) == 1
    wall = _plane({(12, 12): 0x3800})
    assert fo.free_check(wall, 100, 100, 4, 4, 0) == 0      # layer 0: any shape is solid
    assert fo.free_check(wall, 100, 100, 4, 4, 0x80) == 1   # else only with 0x4000
    assert fo.free_check(_plane({(12, 12): 0x7800}), 100, 100, 4, 4, 0x80) == 0
    assert fo.free_check(wall, 100, 100, 4, 4, 0, flag=1) == 1


def test_class_get():
    box = fo.Box(0, 0, 4, 4)
    att = _plane()
    assert fo.class_get(att, 1, 0x20, 100, 90, 100, box, 0) == fo.CLASS_OVER   # off the ground
    assert fo.class_get(att, 1, 0x20, 100, 100, 100, box, 0) == fo.CLASS_UNDER
    # a cell with 0x8000 under the box decides by the layer and its 0x4000
    under = _plane({(12, 12): 0x8000})
    assert fo.class_get(under, 1, 0x20, 100, 100, 100, box, 0) == fo.CLASS_UNDER
    assert fo.class_get(under, 1, 0x20, 100, 100, 100, box, 0x80) == fo.CLASS_OVER
    assert fo.class_get(_plane({(12, 12): 0xC000}), 1, 0x20, 100, 100, 100, box,
                        0x80) == fo.CLASS_UNDER
    # a raised record with nothing solid above it stands over the roofs
    assert fo.class_get(att, 1, 0x20, 100, 100, 100, box, 0x80) == fo.CLASS_OVER
    # a wall straight above, nowhere to slide: over
    walled = _plane({(x, y): 0x3800 for x in range(8, 18) for y in range(9, 11)})
    assert fo.class_get(walled, 1, 0x20, 100, 100, 100, box, 0) == fo.CLASS_OVER


# -- animation ----------------------------------------------------------------

def _anim_table() -> fo.AnimTable:
    # ids 0..8: id k starts at step 2k, two steps; id 6 holds
    rows = tuple(((2 | (fo.ANIM_HOLD if k == 6 else 0)), 2 * k) for k in range(9))
    steps = tuple((k, 3 + k) for k in range(18))
    return fo.AnimTable(rows, steps)


def test_pose_set_picks_group_and_column():
    assert fo.pose_set_id(1, 5) == 1
    assert fo.pose_set_id(1, 1) == fo.pose_set_id(1, 2) == fo.pose_set_id(1, 8) == 2
    assert fo.pose_set_id(1, 6) == fo.pose_set_id(1, 7) == 3
    assert fo.pose_set_id(2, 3) == fo.pose_set_id(2, 4) == 8
    assert fo.pose_set_id(1, 9) is None
    assert fo.pose_set_id(0, 9) == 0
    assert fo.pose_set_id(-1, 5, animation=7) == 5     # its own group


def test_anim_set_keeps_the_timer_within_a_group():
    t = _anim_table()
    st = fo.AnimState()
    fo.pose_set(st, t, 1, 5)
    assert (st.animation, st.step, st.end, st.timer, st.length) == (1, 2, 4, 0, 5)
    st.timer = 2
    fo.pose_set(st, t, 1, 3)                    # the same group, another column
    assert (st.animation, st.step, st.end, st.timer, st.length) == (4, 8, 10, 2, 5)
    fo.pose_set(st, t, 2, 5)                    # another group: restarted
    assert (st.animation, st.timer, st.length) == (5, 0, t.length(10))
    fo.pose_set(st, t, 2, 9)                    # a facing with no column: untouched
    assert st.animation == 5


def test_anim_tick_steps_holds_and_restarts():
    t = _anim_table()
    st = fo.AnimState()
    fo.anim_set(st, t, 1)
    for _ in range(5):
        fo.anim_tick(st, t)
    assert (st.step, st.timer) == (3, 0)
    for _ in range(6):
        fo.anim_tick(st, t)
    assert (st.step, st.timer, st.length) == (2, 0, 5)     # restarted
    fo.anim_set(st, t, 6)
    for _ in range(15 + 16):
        fo.anim_tick(st, t)
    assert (st.step, st.length) == (13, 16)                # held on its last
    fo.anim_tick(st, t)
    assert st.step == 13


def test_twin_sync():
    t = _anim_table()
    row, twin = fo.AnimState(), fo.AnimState()
    fo.anim_set(row, t, 2)
    row.step, row.timer, row.length = 5, 1, 7
    fo.twin_sync(twin, t, row)
    assert (twin.animation, twin.step, twin.timer, twin.length) == (2, 5, 1, 7)


# -- the objects --------------------------------------------------------------

def test_move_set_roamer_and_step_list():
    t = _tables()
    obj = fo.place_objects(_block({0: _definition(kind=5, number=0, speed=2, x=1, y=254)}),
                           _plane(), t, {})[0]
    # x 8: left 8 - 16 held at 0, right 8 + 4 * 8; y 2032: bottom held at 0x7FF
    assert obj.bounds == (0, 40, 2032 - 8, 0x7FF)
    assert (obj.speed, obj.interval) == (2, 1)           # kinds 4..6 take entry speed + 2
    assert (obj.look, obj.sight_width, obj.sight_length, obj.length, obj.count) == (1, 2, 3, 4, 5)
    assert obj.group == 1
    person = fo.place_objects(_block({0: _definition(kind=2, number=6, speed=2)}),
                              _plane(), t, {})[0]
    assert (person.speed, person.interval) == (4, 1)     # other kinds entry speed + 3
    lists = struct.pack("<3H", 0, 6, 10) + bytes([0xF0, 7, 0, 0]) + bytes([0xF9, 3])
    mover = fo.place_objects(_block({0: _definition(number=1, step_list=2)}, lists),
                             _plane(), t, {})[0]
    assert (mover.step_list, mover.cursor, mover.busy, mover.group) == (10, 2, 0, 3)
    still = fo.place_objects(_block({0: _definition(number=3)}), _plane(), t, {})[0]
    assert (still.interval, still.interval_left) == (1, 1)


def test_place_objects_rows_twins_and_chests():
    t = _tables()
    table = _anim_table()
    block = _block({3: _definition(sheet=0x22, facing=4),
                    7: _definition(kind=7, sheet=0x30, facing=6, x=4, y=5),
                    9: _definition(sheet=2, facing=0, number=3)})
    objs = fo.place_objects(block, _plane(), t, {0x22: table, 0: table, 2: table, 0x41: table})
    assert [o.row for o in objs] == [0, 1, 2]
    assert [o.definition.index for o in objs] == [3, 7, 9]
    person, chest, twinned = objs
    assert (person.x, person.y, person.depth, person.facing) == (80, 96, 96, 5)
    assert person.anim.animation == 1
    assert chest.sprite_data == 0 and chest.facing == 7     # closed: shown as defined
    assert chest.anim.animation == 3
    assert twinned.twin_data == 0x41                        # g_MapTwinSpriteDataNumbers[2 - 1]
    assert twinned.twin_anim.animation == 2


def _at(index: int, **kw) -> fo.Definition:
    return fo.definition(_block({index: _definition(**kw)}), index)


def test_event_flags():
    assert fo.story_flag(_at(5, kind=2, story=9), 0x30) == 0x580 + 9
    enemy = _at(5, kind=5, story=1)
    assert fo.story_flag(enemy, 0x66) == 5 + 0x680 + 0x80
    assert fo.story_flag(enemy, 0x20) == (5 + 0x680 - 0x45 * 0x80) & 0xFFFF
    assert fo.story_flag(_at(0, story=0), 0x30) is None
    chest = _at(2, kind=7, facing=4)
    assert fo.chest_flag(chest, 0x20) == 2 + 0x2620 + (0x20 - 0x15) * 32
    assert fo.chest_flag(chest, 0x70) == 2 + 0x2620 + (0x70 - 0x35) * 32
    assert fo.chest_flag(_at(2, kind=7, facing=3), 0x20) is None


def test_table_rows_keep_their_numbers():
    payload = bytearray(fo.ENTER_ROWS * fo.ENTER_ROW)
    payload[3 * fo.ENTER_ROW:4 * fo.ENTER_ROW] = bytes([0x21, 4, 0, 0, 0, 9, 0, 9, 2, 3, 0])
    payload[7 * fo.ENTER_ROW:8 * fo.ENTER_ROW] = bytes([0x22, 5, 0, 13, 0, 9, 0, 9, 4, 5, 4])
    payload[0:fo.ENTER_ROW] = bytes([0x23] + [0] * 10)      # row 0 is never the table's
    raw = struct.pack("<II", fo.ENTER_COMMAND, len(payload)) + bytes(payload) + bytes(8)
    rows = fo.table_rows(raw, 0x20)
    assert [(i, e.map, e.object_set, e.sound) for i, e in rows] == [(3, 0x21, 4, 0),
                                                                     (7, 0x22, 5, 13)]
    assert fo.table_entries(raw, 0x20) == [e for _i, e in rows]


def _chest(event: int, facing: int = 4) -> fo.Definition:
    raw = bytearray(_definition(kind=7, facing=facing))
    raw[0xB] = event
    return fo.definition(_block({1: bytes(raw)}), 1)


def test_what_a_chest_holds():
    assert fo.chest_contents(_chest(0)) == fo.ChestContents("empty", 0, True, False)
    assert fo.chest_contents(_chest(0x12)) == fo.ChestContents("item", 0x12, True, True)
    assert fo.chest_contents(_chest(0xB6)).what == "item"
    assert fo.chest_contents(_chest(0xB7)) == fo.ChestContents("money", 0, True, True)
    assert fo.chest_contents(_chest(0xEF)) == fo.ChestContents("money", 0x38, True, True)
    assert fo.chest_contents(_chest(0xF0)) == fo.ChestContents("label", 0x320, False, False)
    assert fo.chest_contents(_chest(0x12, facing=3)) is None        # open: nothing happens
    assert fo.chest_contents(_at(1, kind=2)) is None
    assert fo.chest_lock_flag(_chest(1, facing=6)) == 0x267         # facing 7
    assert fo.chest_lock_flag(_chest(1, facing=5)) is None


def test_chest_amounts(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    image = bytearray(fo.CHEST_AMOUNTS_ADDR - fo.EXE_BASE + 2 * fo.CHEST_AMOUNTS)
    at = fo.CHEST_AMOUNTS_ADDR - fo.EXE_BASE
    image[at:at + 4] = struct.pack("<2H", 250, 1000)
    amounts = fo.chest_amounts(bytes(image))
    assert len(amounts) == 0xEF - 0xB7 + 1 and amounts[:3] == (250, 1000, 0)
    import pytest
    with pytest.raises(ValueError):
        fo.chest_amounts(bytes(16))
    if "g_MapObjectKind7Amounts" not in programs.JP_TABLES:
        with pytest.raises(programs.Unmapped):
            fo.chest_amounts(bytes(jp_image(0x100)))


# -- the party ----------------------------------------------------------------

def test_party_lead():
    t = _tables()
    table = _anim_table()
    e = fo.enter_row(bytes([1, 2, 0, 0, 0, 0, 0, 0, 10, 20, 2]), "row")
    lead = fo.party_lead(e, 1, 1, _plane(), t, {1: table, 0x40: table})
    assert (lead.x, lead.y, lead.depth, lead.facing) == (80, 160, 160, 3)
    assert (lead.kind, lead.sprite_data, lead.twin_data) == (1, 1, 0x40)
    assert lead.anim.animation == 4 and lead.twin_anim.animation == 4
    small = fo.party_lead(e, 0, 1, _plane(), t, {0x10: table})
    assert (small.sprite_data, small.twin_data, small.twin_anim) == (0x10, None, None)
    assert fo.party_box(0) == fo.Box(0, 0, 6, 4) and fo.party_box(2) == fo.Box(0, -1, 8, 5)
