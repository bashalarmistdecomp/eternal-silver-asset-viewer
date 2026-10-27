"""Tier 1 for SLPS_013.97's glyph codes as characters — no game data.

What this CAN catch: a code of the program's own glyphs read as Shift-JIS
(0x99xx is level-2 kanji there, 0x84xx Cyrillic), a list letter at the
wrong code (0x847F skipped), a placeholder turned into a guess, and the
plain Shift-JIS fallback.

What it CANNOT catch: whether a character is the glyph's. That was
checked by eye against each glyph (the module docstring); see
decoders/testing.py.
"""

from decoders.plugins.SLUS_006_28.formats import jp_characters as jc


def test_the_table_covers_the_program_s_own_glyphs():
    own = [c for c in jc.CHARACTERS if not 0x8440 <= c <= 0x8491]
    assert own == list(range(0x9908, 0x99F9))
    assert all(jc.own(c) for c in jc.CHARACTERS)


def test_the_list_letters_are_0x8440_and_0x8470_past_a():
    for c, ch in jc.CHARACTERS.items():
        if 0x8440 <= c < 0x8470:
            assert ch == chr(ord("A") + c - 0x8440)
        elif c >= 0x8470 and c < 0x9900:
            assert c != 0x847F
            assert ch == chr(ord("a") + c - 0x8470 - (c > 0x847F))


def test_an_own_code_with_no_character_is_none_not_shift_jis():
    placeholders = [c for c, ch in jc.CHARACTERS.items() if ch is None]
    assert placeholders and all(jc.character(c) is None for c in placeholders)
    missing = next(c for c in range(0x8440, 0x8492) if c not in jc.CHARACTERS)
    assert jc.character(missing) is None


def test_any_other_code_is_plain_shift_jis():
    assert jc.character(0x8140) == "　"
    assert jc.character(0x889F) == "亜"
    assert jc.character(0x41) is None
    assert jc.character(0x81AD) is None             # no character there
