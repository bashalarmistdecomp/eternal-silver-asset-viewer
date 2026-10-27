"""Tier 1 for the level-up — a synthetic EXE image, no game data.

What this CAN catch: a gain read at the wrong header word or level index,
the 999 / 255 / u8-wrap rules, the MP skip for ids 7 and 9, the EXP table
indexed by the OLD level, the spell scan (first match only, id 0xB as 1,
jtbl_800118DC's slots), ChrLevelAdd (0x8002844C)'s 99 cap and EXP bookkeeping, and
ScriptCommandChrLevelItemSet (0x8005D2F0)'s refill.

What it CANNOT catch: whether 0x800ACA38 / 0x800AA734 are this program's
tables. Only re-reading ChrLevelUp (0x80028554) does that. See decoders/testing.py.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.records import level_up as lu

POOL = 0x200                     # byte-pool offsets used below (from GAINS_ADDR)
EXP = 0x400                      # the EXP table's offset


def _image(char_id=1, gains=None, exp=None, spells=()) -> bytes:
    """gains: {word: {level: byte}}; exp: {level: u32}; spells: (row, level, who)."""
    img = bytearray(lu.GAINS_ADDR + 0x800 - lu.EXE_BASE)
    put = lambda addr, data: img.__setitem__(slice(addr - lu.EXE_BASE, addr - lu.EXE_BASE + len(data)), data)
    hdr = lu.GAINS_ADDR + (char_id - 1) * lu.HEADER
    for w in range(9):
        put(hdr + 2 * w, struct.pack(">H", POOL + w * 0x40))
    put(hdr + 18, struct.pack(">H", EXP))
    for w, by_level in (gains or {}).items():
        for level, b in by_level.items():
            put(lu.GAINS_ADDR + POOL + w * 0x40 + level, bytes([b]))
    for level, v in (exp or {}).items():
        put(lu.GAINS_ADDR + EXP + 4 * level, struct.pack(">I", v))
    for row, level, who in spells:
        a = lu.SPELL_ROWS_ADDR + (row - 1) * lu.SPELL_STRIDE
        put(a, bytes([level])); put(a + 7, bytes([who]))
    return bytes(img)


def _rec(level=1, **u16) -> bytearray:
    r = bytearray(0x40)
    r[0x1C] = level
    for off, v in u16.items():
        struct.pack_into("<H", r, int(off[1:], 16), v)
    return r


def test_gains_index_the_old_level_and_land_where_the_code_puts_them():
    img = _image(gains={0: {3: 5}, 1: {3: 2}, 2: {3: 4}, 6: {3: 1}, 7: {3: 1}, 8: {3: 2}},
                 exp={3: 777})
    r = _rec(level=3)
    g = lu.level_up(r, 1, img)
    assert (g.hp, g.mp, g.stats, g.swings, g.stat_13) == (5, 2, (4, 0, 0, 0, 1), 1, 2)
    assert struct.unpack_from("<H", r, 0x02)[0] == 5 and struct.unpack_from("<H", r, 0x06)[0] == 2
    assert struct.unpack_from("<H", r, 0x08)[0] == 4 and r[0x14] == 4     # stat + its u8 mirror
    assert struct.unpack_from("<H", r, 0x10)[0] == 1 and r[0x18] == 1
    assert (r[0x12], r[0x19], r[0x13], r[0x1A]) == (1, 1, 2, 2)
    assert r[0x1C] == 4
    assert struct.unpack_from("<I", r, 0x3C)[0] == 777                  # table[old level]


def test_caps_saturation_and_wrap():
    img = _image(gains={0: {1: 10}, 2: {1: 10}, 7: {1: 10}})
    r = _rec(level=1, x02=995, x08=992)
    r[0x14], r[0x12] = 250, 250
    lu.level_up(r, 1, img)
    assert struct.unpack_from("<H", r, 0x02)[0] == 999                  # ChrLevelGainAdd (0x800289E0)
    assert struct.unpack_from("<H", r, 0x08)[0] == 999                  # inline clamp
    assert r[0x14] == 255                                               # mirror saturates
    assert r[0x12] == (250 + 10) & 0xFF                                 # +0x12 wraps


@pytest.mark.parametrize("cid", [7, 9])
def test_ids_7_and_9_gain_no_mp(cid):
    img = _image(char_id=cid, gains={1: {1: 9}})
    r = _rec(level=1)
    assert lu.level_up(r, cid, img).mp == 0
    assert struct.unpack_from("<H", r, 0x06)[0] == 0


def test_first_matching_row_at_the_new_level_is_learned():
    img = _image(char_id=2, spells=[(10, 5, 2), (43, 5, 2), (11, 6, 2)])
    r = _rec(level=4)
    assert lu.level_up(r, 2, img).learned == 10                         # row 43 never reached
    assert r[0x2A + 1] == 10                                            # id 2: row < 13 -> row - 9
    r2 = _rec(level=4)
    img2 = _image(char_id=2, spells=[(43, 5, 2)])
    lu.level_up(r2, 2, img2)
    assert r2[0x2A + 4] == 43                                           # row >= 13 -> row - 39


def test_id_0xb_learns_id_1s_rows():
    img = _image(char_id=0x0B, spells=[(3, 2, 1)])
    r = _rec(level=1)
    assert lu.level_up(r, 0x0B, img).learned == 3 and r[0x2A + 2] == 3


def test_jump_table_slots():
    assert [lu.spell_slot(c, r) for c, r in ((1, 1), (3, 13), (4, 28), (5, 29), (6, 38))] \
        == [0, 0, 7, 0, 5]
    with pytest.raises(ValueError):
        lu.spell_slot(8, 39)                                            # no case: stale register


def test_raise_levels_pays_exp_and_stops_at_99():
    img = _image(exp={97: 50, 98: 60})
    r = _rec(level=97)
    struct.pack_into("<I", r, 0x38, 1000)
    struct.pack_into("<I", r, 0x3C, 40)
    assert len(lu.raise_levels(r, 1, 5, img)) == 2
    assert r[0x1C] == 99
    assert struct.unpack_from("<I", r, 0x38)[0] == 1000 + 40 + 50       # each level adds +0x3C
    assert struct.unpack_from("<I", r, 0x3C)[0] == 0                    # zeroed at 99
    assert lu.raise_levels(r, 1, 1, img) == []                          # nothing past 99


def test_exp_total_caps():
    img = _image()
    r = _rec(level=1)
    struct.pack_into("<I", r, 0x38, lu.EXP_CAP - 1)
    struct.pack_into("<I", r, 0x3C, 10)
    lu.raise_levels(r, 1, 1, img)
    assert struct.unpack_from("<I", r, 0x38)[0] == lu.EXP_CAP


def test_set_level_refills_and_refuses_to_lower():
    img = _image(gains={0: {1: 7, 2: 7}, 1: {1: 3, 2: 3}})
    r = _rec(level=1, x00=1, x02=10, x04=0, x06=4)
    lu.set_level(r, 1, 3, img)
    assert r[0x1C] == 3
    assert struct.unpack_from("<HHHH", r, 0) == (24, 24, 10, 10)
    with pytest.raises(ValueError):
        lu.set_level(r, 1, 2, img)
