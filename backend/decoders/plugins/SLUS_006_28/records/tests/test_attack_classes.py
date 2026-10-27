"""Tier 1 for the attack / special class table — a synthetic EXE image, no
game data.

What this CAN catch: a row read at the wrong base or stride, a field at
the wrong offset (each byte below is distinct, so a swap shows), the
class -> name-string rule, and the extent stopping where the level-up
table begins.

What it CANNOT catch: whether 0x800AC640 is this program's table, or what
the effect handlers do with the values. Only re-reading BtlActionRowRun (0x80031ABC) /
BtlActionTargetAdjust (0x8002ED34) / BtlEnemyKind7Pick (0x8004CF48) does that. See decoders/testing.py.
"""

import pytest

from decoders.plugins.SLUS_006_28.records import attack_classes as ac
from decoders.plugins.SLUS_006_28.records import level_up


def _image(rows: dict[int, bytes]) -> bytes:
    img = bytearray(ac.BASE_ADDR + ac.COUNT * ac.STRIDE - ac.EXE_BASE)
    for cls, raw in rows.items():
        off = ac.BASE_ADDR + cls * ac.STRIDE - ac.EXE_BASE
        img[off:off + len(raw)] = raw
    return bytes(img)


def test_fields_land_where_func_80031ABC_reads_them():
    img = _image({0x2A: bytes([7, 0x40, 0x14, 1, 2, 9, 0x97, 0])})
    rec = ac.read_from_exe(img)[0x2A]
    assert rec.class_id == 0x2A
    assert rec.values == {"target_mode": 7, "effect_id": 0x40, "effect_magnitude": 0x14,
                          "effect_param1": 1, "effect_param2": 2, "element_id": 9,
                          "spell_id": 0x97}
    assert not rec.is_empty


def test_rows_are_eight_bytes_and_zero_rows_read_empty():
    img = _image({1: bytes([3, 0x21, 0x30, 0, 4, 6, 0x88, 0]),
                  2: bytes(8)})
    rows = ac.read_from_exe(img)
    assert len(rows) == ac.COUNT
    assert rows[1].values["effect_id"] == 0x21 and rows[1].values["spell_id"] == 0x88
    assert rows[2].is_empty and rows[0].is_empty


def test_name_string_is_class_or_0x300():
    assert ac.parse_record(bytes(8), 0x40).name_string == 0x340
    assert ac.parse_record(bytes(8), 0x7E).name_string == 0x37E


def test_extent_ends_where_the_level_up_table_begins():
    assert ac.BASE_ADDR + ac.COUNT * ac.STRIDE == level_up.GAINS_ADDR


def test_short_image_is_refused():
    with pytest.raises(ValueError):
        ac.read_from_exe(bytes(ac.BASE_ADDR - ac.EXE_BASE + 8))


def test_to_dict_is_the_shape_the_apps_read():
    d = ac.to_dict(ac.parse_record(bytes([2, 0x25, 7, 0, 0, 4, 0x8C, 0]), 0x43))
    assert d["class_id"] == 0x43 and d["effect_id"] == 0x25 and d["target_mode"] == 2
    assert d["name_string"] == 0x343 and d["raw"] == "0225070000048c00"
