"""Tier 1 for the new-game party table and the party battle record — synthetic bytes.

What this CAN catch: the 0x300/0x342 split ChrRecordsReset (0x80063B30) makes, the
equipment fold (ChrWornItemStatAdd (0x80058910)'s selector map and its plain, unclamped adds,
slot k landing at +0x1D + k), and BtlPartyStatsSet (0x8002A138)'s copies — level from
+0x1C to +0x14, the selector-7 byte to +0x1F, attack/defence mirrored at
+0x1A/+0x1C, the weapon-kind anim picks and the empty-slot item read.

What it CANNOT catch: whether resource 0xE7 is the table, or whether these
are the functions' rules. Only re-reading ChrRecordsReset / BtlPartyStatsSet
does that; the battle savestate's party records are the oracle they were
checked against (byte for byte, the carried items aside). See
decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.formats import party_init as pi


def _items(table: dict[int, dict[int, int]]):
    """An ItemLookup: item id -> {byte offset: value}, 0x12 bytes each."""
    def lookup(item_id):
        b = bytearray(pi.ITEM_STRIDE)
        for off, v in table.get(item_id, {}).items():
            b[off] = v
        return bytes(b)
    return lookup


def _table(records=None, equipment=None, places=None) -> bytes:
    buf = bytearray(0x800)
    for cid, rec in (records or {}).items():
        buf[cid * pi.RECORD:cid * pi.RECORD + len(rec)] = rec
    for cid, items in (equipment or {}).items():
        k = pi.EQUIP_AT + (cid - 1) * pi.EQUIP_SLOTS
        buf[k:k + len(items)] = bytes(items)
    for cid, entry in (places or {}).items():
        s = pi.PLACE_AT + (cid - 1) * pi.PLACE_STRIDE
        buf[s:s + len(entry)] = entry
    return bytes(buf)


def test_parse_splits_where_func_80063B30_does():
    init = pi.parse(_table(records={3: b"\x07" * 4}, equipment={3: [9, 8, 7, 6, 5, 4]},
                           places={11: bytes([30, 18, 1, 2])}))
    assert init.records[3][:4] == b"\x07" * 4 and len(init.records) == 12
    assert init.equipment[3] == (9, 8, 7, 6, 5, 4)
    assert init.place_presets[11][:2] == bytes([30, 18])
    place = pi.place_preset(init.place_presets[11])
    assert (place.place_x, place.place_y, place.presets) == (30, 18, (1, 2, 0, 0, 0, 0))


def test_equip_folds_both_bonuses_by_selector():
    rec = bytearray(pi.RECORD)
    struct.pack_into("<H", rec, 0x0A, 16)                 # defence 16
    items = _items({44: {0x0C: 0x27, 0x0B: 5, 0x0A: 3}})  # sel 2 += 5, sel 7 += 3
    pi.equip(rec, 2, 44, items)
    assert rec[0x1F] == 44                                # slot 2 -> +0x1D + 2
    assert struct.unpack_from("<H", rec, 0x0A)[0] == 21
    assert rec[0x1D] == 3                                 # selector 7 is +0x1D


def test_equip_adds_wrap_and_selector_zero_does_nothing():
    rec = bytearray(pi.RECORD)
    rec[0x12] = 0xFF
    pi.equip(rec, 1, 5, _items({5: {0x0C: 0x60, 0x0B: 2}}))   # sel 6 (u8) += 2; sel 0
    assert rec[0x12] == 0x01


def test_battle_record_copies_and_moves_fields():
    p = bytearray(pi.RECORD)
    struct.pack_into("<9H", p, 0, 32, 32, 10, 10, 20, 21, 21, 18, 15)
    p[0x12], p[0x13], p[0x1C], p[0x1D] = 1, 12, 7, 18
    p[0x2A] = 33
    b = pi.battle_record(bytes(p), 6, _items({}))
    f = b.fields()
    assert (f["hp_max"], f["stat_08"], f["stat_0a"], f["stat_0c"], f["stat_0e"]) == (32, 20, 21, 21, 18)
    assert f["level"] == 7 and f["stat_1f"] == 18 and f["walk_speed"] == 3
    assert (f["stat_08_start"], f["stat_0a_start"]) == (20, 21)
    assert (f["attack_count"], f["walk_reach"]) == (1, 12)
    assert f["spells"][0] == 33


def test_unarmed_and_weapon_kind_pick_the_anims():
    p = bytearray(pi.RECORD)
    assert pi.battle_record(bytes(p), 1, _items({})).anims == (0x0A, 0x05, 0x00)
    p[0x1E] = 1                                           # a weapon in slot 1
    items = _items({1: {0x0F: 0, 0x0B: 4, 0x0D: 9}})      # kind 0
    b = pi.battle_record(bytes(p), 7, items)
    assert b.anims == (0x0B, 0x06, 0x01)
    f = b.fields()
    assert f["worn_items"][0] == 1 and f["least_amount"] == 4 and f["traits"][0] == 9
    assert f["animations"] == {"attack": 0x0B, "stand": 0x06, "move": 0x01}


def test_kind_3_depends_on_the_character():
    p = bytearray(pi.RECORD)
    p[0x1E] = 2
    items = _items({2: {0x0F: 3}})
    assert pi.battle_record(bytes(p), 0x0A, items).anims == (0x0D, 0x08, 0x03)
    assert pi.battle_record(bytes(p), 1, items).anims == (0x0E, 0x09, 0x04)


def test_empty_slots_read_item_zero():
    p = bytearray(pi.RECORD)
    b = pi.battle_record(bytes(p), 1, _items({0: {0x0D: 0x55}}))
    assert b.fields()["traits"][1:] == [0x55] * 5


def test_party_equips_then_derives():
    rec = bytearray(pi.RECORD)
    struct.pack_into("<H", rec, 0x08, 10)
    buf = _table(records={1: bytes(rec)}, equipment={1: [3, 0, 0, 0, 0, 0]})
    m = {x.char_id: x for x in pi.party(buf, _items({3: {0x0C: 0x10, 0x0B: 6, 0x0F: 1}}))}
    assert m[1].level1.stats[0] == 16 and m[1].starting_equipment[0] == 3
    assert m[1].battle.fields()["stat_08"] == 16 and m[1].battle.anims == (0x0D, 0x08, 0x03)


def test_by_level_columns_run_from_the_records_own_level():
    rec = bytearray(pi.RECORD)
    rec[0x1C] = 2
    struct.pack_into("<H", rec, 0x02, 30)

    def set_level(r, level):                              # a stand-in level-up: +5 HP each
        while r[0x1C] < level:
            r[0x1C] += 1
            struct.pack_into("<H", r, 0x02, struct.unpack_from("<H", r, 0x02)[0] + 5)
        r[0x00:0x02] = r[0x02:0x04]

    cols = pi.by_level(bytes(rec), 1, _items({}), set_level, last=5)
    assert cols["first"] == 2
    assert cols["level"] == [2, 3, 4, 5]                  # the battle record's +0x14
    assert cols["hp_max"] == [30, 35, 40, 45] and cols["hp"] == [30, 35, 40, 45]
    assert set(pi.LEVEL_FIELDS) <= set(cols)
