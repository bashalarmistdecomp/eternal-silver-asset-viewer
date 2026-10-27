"""Tier 1 for the spell table — a synthetic EXE image, no game data.

What this CAN catch: a row read at the wrong base, a row number that is not
the spell's number (the battle reads spell n at g_BtlSpellRowsByNumber
(0x800AA728) + n * 12, one row before g_BtlSpellRows (0x800AA734)), the show
number at +0x06 taken for the spell's, and an extent other than the table's
0x32 rows.

What it CANNOT catch: whether these addresses are this program's tables.
Only re-reading the code does that. See decoders/testing.py.
"""

from decoders.plugins.SLUS_006_28.records import level_up, spells


def _image(rows: dict[int, bytes]) -> bytes:
    img = bytearray(spells.BASE_ADDR + spells.COUNT * spells.STRIDE - spells.EXE_BASE)
    for n, raw in rows.items():
        off = spells.BASE_ADDR + n * spells.STRIDE - spells.EXE_BASE
        img[off:off + len(raw)] = raw
    return bytes(img)


def test_row_n_is_spell_n_and_its_show_number_is_another_number():
    img = _image({7: bytes([9, 0x12, 0x2B, 0x40, 0x0A, 0x1E, 0x2F, 3])})
    rec = spells.read_from_exe(img)[7]
    assert rec.number == 7
    assert rec.values["show_number"] == 0x2F       # +0x06, the show number
    assert rec.values["function_number"] == 0x2B and rec.values["cost"] == 0x0A
    assert rec.values["use_place"] == 0x40          # two nibbles, one byte
    assert spells.to_dict(rec)["number"] == 7


def test_every_byte_is_a_named_field():
    covered = {off for off, *_ in spells.FIELDS}
    assert covered == set(range(spells.STRIDE))
    names = {name for _o, _k, name, _n in spells.FIELDS}
    assert set(spells.HEX_FIELDS) <= names and set(spells.PARAM_GLOBALS) <= names


def test_row_1_is_the_first_row_of_g_BtlSpellRows():
    assert spells.BASE_ADDR + spells.STRIDE == level_up.SPELL_ROWS_ADDR


def test_extent_is_row_0_and_the_tables_0x32_spells():
    rows = spells.read_from_exe(_image({}))
    assert len(rows) == 1 + level_up.SPELL_SCAN == 0x33
    assert rows[-1].number == 0x32
    assert all(r.is_empty for r in rows)
