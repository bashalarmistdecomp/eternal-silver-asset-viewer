"""Tier 1 for the battles' voices — a made-up image, no game data.

What this CAN catch: the effect rows read from the wrong place (in either
program) or with the wrong stride, a byte read as the wrong field, a show
past 0x5A or one whose row names no voice taken as playing one, a table
that runs past the image not said so, a level giving more than its first
row or id 11 not reading id 1's rows, a script spell given to another
owner, and a planner's series not opened.

What it CANNOT catch: whether the constants are this program's (the
acting ids, the set battles, the revive's voice, the spell lists, the
planners) — only re-reading BtlShowOpen (0x8007B7C8), BtlActingShowRun
(0x8003A158), BtlSlot5Revive (0x80028E5C), BtlActingSpellPick
(0x800393F0) and the planners of BtlEnemyActionSpecialSet (0x800417E4)
does that. See decoders/testing.py.
"""

import pytest

from decoders.plugins.SLUS_006_28.records import battle_voices as bv
from decoders.plugins.SLUS_006_28.records.programs import EXE_BASE


def image(rows: dict[int, tuple[int, int, int, int]]) -> bytes:
    """A made-up image from 0x80011000 with the given effect rows."""
    out = bytearray(bv.EFFECT_ROWS_ADDR - EXE_BASE + bv.EFFECT_COUNT * bv.ROW_SIZE + 8)
    for n, row in rows.items():
        at = bv.EFFECT_ROWS_ADDR - EXE_BASE + n * bv.ROW_SIZE
        out[at:at + bv.ROW_SIZE] = bytes(row)
    return bytes(out)


def test_a_row_is_flags_tile_row_and_two_voices():
    rows = bv.effect_rows(image({3: (1, 2, 30, 31)}))
    assert len(rows) == bv.EFFECT_COUNT
    assert rows[3] == bv.EffectRow(3, 1, 2, 30, 31)
    assert rows[4] == bv.EffectRow(4, 0, 0, 0, 0)


def test_only_shows_up_to_0x5a_with_a_voice_play_one():
    img = image({1: (3, 0, 7, 8), 2: (3, 0, 0, 9), bv.SHOW_LAST: (1, 0, 5, 5),
                 bv.SHOW_LAST + 1: (1, 0, 6, 6)})
    got = bv.show_voices(img)
    assert sorted(got) == [1, bv.SHOW_LAST]
    assert (got[1].voice, got[1].other_voice) == (7, 8)


def test_a_short_image_says_so():
    with pytest.raises(LookupError):
        bv.effect_rows(bytes(16))


def test_the_japanese_program_keeps_the_rows_elsewhere(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    at = programs.JP_TABLES["g_BtlEffectRows"].addr - EXE_BASE
    img = jp_image(at + bv.EFFECT_COUNT * bv.ROW_SIZE)
    img[at + 5 * bv.ROW_SIZE: at + 6 * bv.ROW_SIZE] = bytes((3, 0, 11, 12))
    assert bv.show_voices(bytes(img)) == {5: bv.EffectRow(5, 3, 0, 11, 12)}


def test_a_level_brings_the_first_row_of_its_owner_and_id_11_reads_1s():
    # spell -> (level, owner byte)
    spells = {1: (2, 1), 2: (2, 1), 3: (5, 1), 4: (0, 1), 5: (3, 2), 6: (3, 7)}
    got = bv.level_spells(spells)
    assert got[1] == {1, 0x0B} and got[3] == {1, 0x0B} and got[5] == {2}
    assert 2 not in got            # a second row of the same level
    assert 4 not in got            # level 0: no level reached brings it
    assert 6 not in got            # id 7 keeps no spells by level


def test_a_script_gives_a_spell_only_to_its_owner():
    assert bv.script_spell_ok(2, 2) and bv.script_spell_ok(0x0B, 1)
    assert not bv.script_spell_ok(0x0B, 0x0B) and not bv.script_spell_ok(3, 2)


def test_a_planners_series_opens_into_its_attacks():
    assert bv.planned_attacks(0x7C) == [0x64, 0x72, 0x62, 0x63, 0x68, 0x67, 0x73, 0x65, 0x66]
    assert bv.planned_attacks(0x76) == [0x5A]
    assert bv.planned_attacks(0x10) == []


def test_the_other_voice_is_for_three_ids():
    assert [i for i in range(256) if bv.other_voice(i)] == [0x0B, 0x7C, 0x7D]
