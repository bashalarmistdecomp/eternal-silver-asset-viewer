"""Tier 1 for the item table — a synthetic EXE image, no game data.

What this CAN catch: a row read at the wrong base or stride, ids that are
not 1-based, and a count other than the 0xB6 rows ChrItemUseGet (0x80058088)
allows (it answers -2 for an item number of 0 or above 0xB6), which would
list the spell rows that follow as items.

What it CANNOT catch: whether 0x800A9A68 is this program's table. Only
re-reading the code does that. See decoders/testing.py.
"""

import pytest

from decoders.plugins.SLUS_006_28.formats import system_strings
from decoders.plugins.SLUS_006_28.records import items, level_up, spells


def _image(rows: dict[int, bytes], count: int = items.COUNT) -> bytes:
    img = bytearray(items.BASE_ADDR + count * items.STRIDE - items.EXE_BASE)
    for item_id, raw in rows.items():
        off = items.BASE_ADDR + (item_id - 1) * items.STRIDE - items.EXE_BASE
        img[off:off + len(raw)] = raw
    return bytes(img)


def test_count_is_the_0xB6_rows_ChrItemUseGet_allows():
    assert items.COUNT == 0xB6
    recs = items.read_from_exe(_image({}))
    assert len(recs) == 182
    assert [recs[0].item_id, recs[-1].item_id] == [1, 182]


def test_rows_are_0x12_bytes_from_id_1():
    img = _image({1: bytes([0x34, 0x12, 0x78, 0x56, 3, 0, 0x21, 0, 5, 7, 0x2D, 0, 2]),
                  0xB6: bytes([0, 0, 0, 0, 9])})
    recs = items.read_from_exe(img)
    assert recs[0].values["price"] == 0x1234 and recs[0].values["sell_price"] == 0x5678
    assert recs[0].values["target_modes"] == 0x21 and recs[0].values["use_picture"] == 0
    assert (recs[0].values["function_number"], recs[0].values["show_number"]) == (5, 7)
    assert recs[0].modifiers == [{"selector": 2, "stat": "stat_0a", "amount": 0x2D}]
    assert recs[0xB5].item_id == 0xB6 and recs[0xB5].values["kind"] == 9
    assert items.to_dict(recs[1])["empty"]


def test_the_table_ends_where_spell_1_begins():
    # spell n is read at g_BtlSpellRowsByNumber + n * 12; spell 1 is the
    # first row of g_BtlSpellRows, which a 183rd item would overlap.
    end = items.BASE_ADDR + items.COUNT * items.STRIDE
    assert end == spells.BASE_ADDR + 1 * spells.STRIDE == level_up.SPELL_ROWS_ADDR


def test_the_string_table_names_as_many_items():
    cat = system_strings.BY_CATEGORY["item"]
    assert cat.last - cat.base == items.COUNT


def test_short_image_is_refused():
    with pytest.raises(ValueError):
        items.read_from_exe(_image({}, count=items.COUNT - 1))


def test_every_byte_is_a_named_field():
    widths = {"u8": 1, "u16": 2}
    covered = {o for off, kind, _n, _t in items.FIELDS for o in range(off, off + widths[kind])}
    assert covered == set(range(items.STRIDE))
    names = {name for _o, _k, name, _t in items.FIELDS}
    assert set(items.HEX_FIELDS) <= names


def test_both_bonuses_go_to_the_stats_their_nibbles_select():
    raw = bytearray(items.STRIDE)
    raw[0x0A], raw[0x0B], raw[0x0C] = 3, 4, 0x86      # bonus_1, bonus_2, bonus_stats
    rec = items.parse_record(bytes(raw), 1)
    assert rec.modifiers == [{"selector": 6, "stat": "attack_count", "amount": 3},
                             {"selector": 8, "stat": "walk_reach", "amount": 4}]
