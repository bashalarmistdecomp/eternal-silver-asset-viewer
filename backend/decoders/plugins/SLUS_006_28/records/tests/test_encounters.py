"""Tier 1 for the encounter tables — a synthetic EXE image, no game data.

What this CAN catch: a table read at the wrong base or stride, the
1-based encounter / type-list folding, BtlEnemyLoad (0x8002B3AC)'s Y clamp, its
mirror threshold, and its type search (first THREE entries, anything else
-> block 3).

What it CANNOT catch: whether the addresses are the program's. Only
re-reading BtlEnemyLoad / BtlDataLoad (0x80018694) does that. See
decoders/testing.py.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.records import encounters as en


def _image(**writes) -> bytes:
    # (up to the event script's encounter rows' end, which tables_json reads too)
    img = bytearray(0x800B386C - en.EXE_BASE)
    for addr, data in writes.values():
        img[addr - en.EXE_BASE: addr - en.EXE_BASE + len(data)] = data
    return bytes(img)


def test_encounter_is_one_based_on_the_code_base():
    img = _image(e=(en.ENCOUNTER_ADDR + 2 * 7, bytes([3, 9])))
    assert en.encounter(img, 7) == en.Encounter(id=7, set=3, formation=9)
    with pytest.raises(ValueError):
        en.encounter(img, 0)


def test_type_list_stops_at_zero():
    img = _image(t=(en.TYPE_LIST_ADDR + 4 * 2, bytes([5, 6, 0, 8])))
    assert en.type_list(img, 2) == (5, 6)


def test_type_slot_matches_only_three_then_falls_back():
    types = (10, 11, 12, 13)
    assert [en.type_slot(types, i) for i in (10, 11, 12)] == [0, 1, 2]
    assert en.type_slot(types, 13) == 3              # the 4th type: by fall-through
    assert en.type_slot(types, 99) == 3              # a stranger, too


def test_formation_positions_clamp_and_mirror():
    rec = bytes([1, 2, 3, 0, 9, 9, 9, 9,             # ids; 0 ends at slot 3
                 0x0A, 0x18, 0x02, 0, 0, 0, 0, 0,    # x / 8
                 0x0C, 0x20, 0x14, 0, 0, 0, 0, 0])   # y / 8
    img = _image(f=(en.FORMATION_ADDR + 5 * en.FORMATION_STRIDE, rec))
    f = en.formation(img, 5)
    assert [s.enemy_id for s in f.slots] == [1, 2, 3]
    assert [s.actor_slot for s in f.slots] == [6, 7, 8]
    assert [(s.x, s.y) for s in f.slots] == [(80, 0x70), (192, 0xB0), (16, 160)]
    assert [s.y_unclamped for s in f.slots] == [96, 256, 160]
    assert [s.mirrored for s in f.slots] == [False, True, False]   # x >= 0xC0


def test_set_resource_is_u16():
    img = _image(r=(en.SET_RESOURCE_ADDR + 2 * 4, struct.pack("<H", 0x16A)))
    assert en.set_resource(img, 4) == 0x16A and en.set_resource(img, 0) == 0


def test_extents_agree_with_each_other():
    # formations end exactly where encounter 1 begins; type lists start
    # after the encounter table plus 4-alignment.
    assert en.FORMATION_ADDR + en.FORMATION_COUNT * en.FORMATION_STRIDE == \
        en.ENCOUNTER_ADDR + en.ENCOUNTER_FIRST * en.ENCOUNTER_STRIDE
    end_enc = en.ENCOUNTER_ADDR + (en.ENCOUNTER_LAST + 1) * en.ENCOUNTER_STRIDE
    assert en.TYPE_LIST_ADDR + en.SET_FIRST * en.TYPE_LIST_STRIDE == (end_enc + 3) & ~3


def test_max_enemy_id_is_the_largest_id_any_formation_names():
    img = _image(a=(en.FORMATION_ADDR + 3 * en.FORMATION_STRIDE, bytes([4, 0x2A, 7])),
                 b=(en.FORMATION_ADDR + 200 * en.FORMATION_STRIDE, bytes([0x30])))
    assert en.max_enemy_id(img) == 0x30


def test_tables_json_is_the_shape_the_apps_read():
    rec = bytes([5, 0, 0, 0, 0, 0, 0, 0,  0x18, 0, 0, 0, 0, 0, 0, 0,  0x10, 0, 0, 0, 0, 0, 0, 0])
    img = _image(e=(en.ENCOUNTER_ADDR + 2 * 1, bytes([2, 4])),
                 f=(en.FORMATION_ADDR + 4 * en.FORMATION_STRIDE, rec),
                 t=(en.TYPE_LIST_ADDR + 4 * 2, bytes([5, 6, 0, 0])),
                 r=(en.SET_RESOURCE_ADDR + 2 * 2, struct.pack("<H", 0x168)))
    doc = en.tables_json(img)
    assert len(doc["encounters"]) == 255 and len(doc["formations"]) == 256
    assert doc["encounters"][0] == {"id": 1, "set": 2, "formation": 4}
    assert doc["formations"][4]["slots"] == [{"actor_slot": 6, "enemy_id": 5, "x": 0xC0, "y": 0x80,
                                              "y_unclamped": 0x80, "mirrored": True}]
    assert doc["sets"][1] == {"set": 2, "resource": 0x168, "types": [5, 6]}
    assert doc["script_rows"] == []          # an image with no g_ScriptMapBtlRows (0x800B366C) rows


def test_tables_json_carries_the_script_rows():
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    from decoders.plugins.SLUS_006_28.formats import system_strings as ss
    img = bytearray(ss.WORDS_ADDR - en.EXE_BASE)
    base = es.ENCOUNTER_ROWS_ADDR - en.EXE_BASE
    img[base + 8: base + 16] = bytes([0xE3, 0x14, 0x0B, 0x0C, 0x02, 0, 7, 0])
    assert en.tables_json(bytes(img))["script_rows"] == [
        {"row": 2, "encounter": 0xE3, "x_shift": 0x14, "party": [0x0B, 0x0C, 0x02]}]
