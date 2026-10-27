"""SLPS_013.97's glyph codes as Unicode characters: our transcription.

The Japanese program's text is 16-bit glyph codes (formats.system_strings:
a byte below 0xD6 through its g_FontStringCodes, else two bytes, 0xD640 to
0xEFFF less 0x5500). Its font_pattern_get (0x80026B1C; SLPS_013.97
0x8002A3A0) draws a code from one of three places (formats.message_window):

    0x9908-0x99F8   g_FontPatterns9908 (SLPS_013.97 0x800AEE90), the
                    program's own glyphs: punctuation, full-width digits and
                    capitals, the kana, eight kanji and a few signs
    0x8440-0x8491   the byte list at SLPS_013.97 0x800B1338 and the glyphs
                    past that table: narrow Latin letters, 0x8440 + n the
                    capital n letters past A, 0x8470 + n the small one
                    (0x847F, no Shift-JIS code, is skipped)
    any other       the console's kanji ROM through Krom2RawAdd, by its
                    Shift-JIS code

Shift-JIS has other characters at the first two ranges (level-2 kanji at
0x99xx, Cyrillic at 0x84xx), so those codes read as `CHARACTERS` has them
and nothing else; any other code is plain Shift-JIS (`character`).

How the table was made: each of the program's 277 glyphs was compared as
a picture with candidate characters drawn by installed fonts (all of JIS X
0208, ASCII and some blocks of signs, in Japanese sans and serif faces and
Latin serif and mono faces), keeping the closest ten. Every entry was then
checked by eye against the glyph and against the text it stands in. The
picture match put the chosen character first for 177 of the 275 entries
and among its ten for 251; the eye settled the rest (the serif digits and
letters, some kana with marks). The glyphs run in JIS order (punctuation,
digits, capitals, hiragana, katakana, then eight JIS level-2 kanji, which
the console's ROM does not hold). That order settled what no picture tells
apart: the three dashes (ー, ― and －), へ and ヘ, and the katakana shaped
like kanji (ロ, ニ, ハ and the like). The 0x99xx capitals and digits are as
wide as the kana, so they are the full-width forms; the list's letters are
narrow, so they are ASCII.

Two glyphs have no confident match and are None, shown as a placeholder
where text is read: 0x99EF, a ball crossed by a line, and 0x99F7, a
note-like sign. The crescent 0x99ED is read as ☽ and both stars 0x99F1
and 0x99F4 as ★.
"""

from __future__ import annotations

#: The ranges font_pattern_get draws from the program's own glyphs.
OWN_RANGES = ((0x9908, 0x99F8), (0x8440, 0x8491))


def _run(first: int, chars: str) -> dict[int, str]:
    return {first + i: ch for i, ch in enumerate(chars)}


def _small(letter: str) -> int:
    """The list's code of a small letter: 0x8470 + n, past 0x847F."""
    n = ord(letter) - ord("a")
    return 0x8470 + n + (n >= 0xF)


#: Code -> character (None: no confident match).
CHARACTERS: dict[int, str | None] = {
    **_run(0x9908, "、，・：？！々ー―／〜…’（）［］「」『』－＝‼⁉○"),
    **_run(0x9922, "０１２３４５６７８９"),
    **_run(0x992C, "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＲＳＴＵＶＷＸＹ"),
    **_run(0x9944, "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞ"
                   "ただちっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽ"
                   "まみむめもゃやゅゆょよらりるれろわをん"),
    **_run(0x9993, "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾ"
                   "タダチッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポ"
                   "マミムメモャヤュユョヨラリルレロワヲンヴヵヶ"),
    **_run(0x99E5, "棍璧痺綺罠翔翡蜃"),
    0x99ED: "☽", 0x99EE: "♥", 0x99EF: None, 0x99F0: "☆", 0x99F1: "★",
    0x99F2: "●", 0x99F3: "☀", 0x99F4: "★", 0x99F5: "♪", 0x99F6: "♫",
    0x99F7: None, 0x99F8: "▷",
    **{0x8440 + ord(c) - ord("A"): c for c in "BCDFGHIMNPRSTUVW"},
    **{_small(c): c for c in "acdefghiklmnoprstuvy"},
}


def own(code: int) -> bool:
    """True for a code the program draws from its own glyphs."""
    return any(lo <= code <= hi for lo, hi in OWN_RANGES)


def character(code: int) -> str | None:
    """The character `code` stands for in SLPS_013.97's text: the table's
    for the program's own glyphs, Shift-JIS's for any other. None for a
    code with no confident match, a list code with no glyph, or a code
    Shift-JIS lacks."""
    if own(code):
        return CHARACTERS.get(code)
    if code < 0x100:
        return None
    try:
        return bytes((code >> 8, code & 0xFF)).decode("shift_jis")
    except UnicodeDecodeError:
        return None
