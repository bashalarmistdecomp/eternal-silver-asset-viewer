"""The installed-font stand-in for the kanji ROM: which face is tried
first, and what the info says. Made-up faces; the one test that draws
with a real font skips on a machine without a Japanese one."""

import pytest

from viewer_tabs import system_font as sf


def face(path, index, family, style="Regular"):
    return sf.Face(path, index, family, style)


def test_a_face_named_for_japanese_comes_before_the_one_fc_match_gives():
    kr = face("/f/cjk.ttc", 1, "Some Sans CJK KR")
    jp = face("/f/cjk.ttc", 0, "Some Sans CJK JP")
    assert sf.rank([kr, jp], ("/f/cjk.ttc", 1))[0] == jp


def test_sans_before_serif_then_fc_match_then_a_regular_weight():
    serif = face("/f/a.ttc", 0, "Some Serif CJK JP")
    other = face("/f/b.ttf", 0, "Other Gothic")
    bold = face("/f/c.ttc", 0, "Some Sans JP", "Bold")
    regular = face("/f/c.ttc", 2, "Some Sans JP")
    assert sf.rank([serif, other, bold, regular], ("/f/c.ttc", 0)) == [bold, regular, other, serif]
    assert sf.rank([serif, other, bold, regular], None) == [other, regular, bold, serif]


def test_the_info_names_the_font_or_says_there_is_none():
    class Named:
        def __str__(self):
            return "Made Up Gothic (madeup.ttc)"
    said = " ".join(sf.kanji_lines(Named(), 7, 2, tinted=True))
    assert said.startswith("7 glyphs are the console's")
    assert "Krom2RawAdd" in said and "Made Up Gothic (madeup.ttc)" in said
    assert "not the game's" in said and "2 have no glyph in it" in said
    assert "second layer" in said
    none = " ".join(sf.kanji_lines(None))
    assert none.startswith("The kanji are") and "a box" in none
    assert all(len(line) <= 70 for line in sf.kanji_lines(Named(), 7, 2, tinted=True))


def test_an_installed_font_draws_in_the_cell_the_outline_reads():
    font = sf.find()
    if font is None:
        pytest.skip("no Japanese font on this machine")
    p = font.pattern(sf.SQUARE)
    assert p is not None and len(p) == sf.PATTERN_BYTES
    assert any(p[:30]) and not any(p[30:])         # 15 rows, the 16th clear
    assert font.pattern("\u0378") is None          # unassigned: no glyph
