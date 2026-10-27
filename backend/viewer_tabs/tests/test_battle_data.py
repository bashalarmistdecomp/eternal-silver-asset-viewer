"""The Battle Data tab's name columns — a synthetic enemy row.

An enemy's kind-7 action is the number at stats +0x1D, kind7_number (row
+0x13): BtlEnemyActionAdjust (0x80029510) gives a kind-7 plan that number,
and BtlActionStringDisp (0x8004987C) shows string number | 0x300 for an
enemy's kind 7. Stats +0x1C, attack_number (row +0x12), is the numbered
attack, which the game shows no name for.
"""

from decoders.plugins.SLUS_006_28.records import enemy_templates as et
from viewer_tabs.tab_providers import DataTablesProvider


def _column(stem: str, name: str):
    return next(index_of for col, _cat, _what, index_of
                in DataTablesProvider._NAME_COLUMNS[stem] if col == name)


def _record(**at) -> dict:
    raw = bytearray(et.STRIDE)
    for off, value in at.items():
        raw[int(off, 16)] = value
    return et.to_dict(et.parse_record(bytes(raw), 0))


def test_the_kind7_column_names_the_number_at_0x1D():
    rec = _record(**{"12": 0x05, "13": 0x09})      # -> stats +0x1C, +0x1D
    assert rec["battle_record"]["attack_number"] == 0x05
    assert rec["battle_record"]["kind7_number"] == 0x09
    assert _column("enemy_templates", "kind7 name")(rec) == 0x09


def test_no_kind7_number_is_no_name():
    assert _column("enemy_templates", "kind7 name")(_record()) is None


def test_win_items_as_BtlWinItemsGive_tries_them():
    """win_item_1 must be 1..0xA4 or neither is tried; win_item_2 has no
    range test, only 0 for none."""
    items = _column("enemy_templates", "win items")
    assert items(_record(**{"1e": 3, "20": 0xB0})) == [3, 0xB0]
    assert items(_record(**{"1e": 3})) == [3]
    assert items(_record(**{"1e": 0xA5, "20": 3})) == []
    assert items(_record(**{"20": 3})) == []


def test_nibble_fields_show_in_hex():
    from viewer_tabs.tab_providers import _fmt_cell
    assert _fmt_cell(0x23, "use_place", 2) == "0x23"
    assert _fmt_cell(0x0101, "wearers", 4) == "0x0101"
    assert _fmt_cell(0x23, "cost") == "35"
