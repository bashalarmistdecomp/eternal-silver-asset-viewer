"""Tier 1 for the string table — synthetic bytes, no game data.

What this CAN catch: block() taking resource 1's type-1 command
(command_list has the walk's own tests), the table bound,
font_string_walk (0x8005A884)'s two modes — the 0x0E run (b + 0x1F, the control
characters, word refs b - 0x5C / FD + 0xA1 / FE + 0x19E, '$' ending
the message) and the 16-bit codes (splices 0xF0-0xF6, the pen move, the
faces, the style, the wait, the message-window breaks, glyphs) — the plain
text's spacing of a pen move, and the category arithmetic.

What it CANNOT catch: whether resource 1 is the table, whether
0x800B386C is the dictionary, or what a glyph looks like. Only re-reading
main (0x80013D2C) / font_string_put (0x80026F78) / font_string_walk does that. See
decoders/testing.py. The last tests read the user's disc, when the library
has it: the dictionary's extent, and the pen moves of the real table.
"""

import struct

import pytest

from decoders import config
from decoders.plugins.SLUS_006_28.formats import system_strings as ss


def enc(s: str) -> bytes:
    """A 0x0E run: each character as its code - 0x1F."""
    return bytes([0x0E, *((ord(c) - 0x1F) for c in s), 0x00])


def table(strings: dict[int, bytes], slots: int) -> bytes:
    """A block: `slots` u16 offsets, then each string + 0xFF."""
    head = bytearray(2 * slots)
    body = bytearray()
    for sid, raw in strings.items():
        struct.pack_into("<H", head, 2 * sid, 2 * slots + len(body))
        body += raw + b"\xff"
    return bytes(head + body)


FRAGS = [b"ta", b"the ", b"x@y%"]
frag = lambda n: FRAGS[n] if n < len(FRAGS) else b"?"


def test_block_inflates_the_type_1_command():
    buf = bytearray()
    buf += struct.pack("<II", 0x102, 8) + b"abcdefgh"
    buf += struct.pack("<II", 0x001, 4) + b"PAYL"
    buf += struct.pack("<I", 0)
    assert ss.block(bytes(buf), inflate=lambda p: p.lower()) == b"payl"
    with pytest.raises(ValueError):
        ss.block(struct.pack("<II", 2, 0) + b"\0" * 8, inflate=lambda p: p)
    with pytest.raises(ValueError):
        ss.block(bytes(buf), inflate=lambda p: b"\0" * (ss.BLOCK_CAPACITY + 1))


def test_table_bound_stops_at_the_first_string():
    blk = table({1: enc("Abcd"), 2: enc("Efgh")}, slots=4)
    assert ss.table_size(blk) == 4
    assert ss.string_offset(blk, 3) == 0


def test_characters_and_controls():
    # What a message window does with the codes font_string_walk (0x8005A884) emits
    # (MessageControlRun, 0x8005AF20): '%' 0xFF00 the button prompt — NO text; '*' prompt
    # then a new page; '@' 0xFF02 the next row; '^' 0xFF01 a new page;
    # '\\' 0xFF03 close.
    blk = table({1: enc("Hi%there*now@^\\")}, slots=2)
    d = ss.decode(blk, ss.string_offset(blk, 1), frag)
    assert d.text == "Hithere\nnow\n\n"
    assert d.markup == "Hi{PROMPT}there{PROMPT}{PAGE}now\n{PAGE}{CLOSE}"


def test_the_row_break_is_at_sign_and_the_prompt_prints_nothing():
    blk = table({1: enc("a@b"), 2: enc("a%b")}, slots=3)
    assert ss.decode(blk, ss.string_offset(blk, 1), frag).text == "a\nb"
    assert ss.decode(blk, ss.string_offset(blk, 2), frag).text == "ab"


def test_dollar_ends_the_message():
    blk = table({1: enc("ab$cd")}, slots=2)
    d = ss.decode(blk, ss.string_offset(blk, 1), frag)
    assert (d.text, d.markup) == ("ab", "ab{PROMPT}{CLOSE}")


def test_fragment_references():
    raw = bytes([0x0E, ord("A") - 0x1F, 0x5C, 0x5D, 0xFD, 0x00, 0x00])   # 'A' + frag0 + frag1 + frag 0xA1
    blk = table({1: raw}, slots=2)
    big = lambda n: {0: b"ta", 1: b"the ", 0xA1: b"me "}.get(n, b"?")
    d = ss.decode(blk, ss.string_offset(blk, 1), big)
    assert d.text == "Atathe me " and d.words == 3
    raw2 = bytes([0x0E, 0xFE, 0x02, 0x00])                               # FE nn -> 0x19E + nn
    blk2 = table({1: raw2}, slots=2)
    assert ss.decode(blk2, 2 * 2, lambda n: b"kill" if n == 0x1A0 else b"?").text == "kill"


def test_controls_inside_a_fragment():
    blk = table({1: bytes([0x0E, 0x5E, 0x00])}, slots=2)                # frag 2 = "x@y%"
    d = ss.decode(blk, ss.string_offset(blk, 1), frag)
    assert d.text == "x\ny"
    assert d.markup == "x\ny{PROMPT}"


def test_sixteen_bit_codes_splice_move_and_break():
    # outside a 0x0E run: bytes >= 0xD6 are big-endian codes
    raw = enc("Load") + bytes([0xF9, 0x02]) + bytes([0xF0, 0x02]) + bytes([0x02]) + enc("x")
    blk = table({1: raw, 2: enc("?")}, slots=3)
    ct = lambda b: {0x02: 0xFF02}.get(b, 0x9900 | b)
    d = ss.decode(blk, ss.string_offset(blk, 1), frag, ct)
    assert d.text == "Load ?\nx"
    assert d.markup == "Load{MOVE:2px}{STR:0x002}\nx"


def test_a_pen_move_is_one_space_between_text_and_none_at_a_lines_ends():
    # font_pen_move (0x800270CC) moves the pen nn PIXELS and the font is
    # proportional (font_code_put, 0x80026D64): the plain text gives a move one space
    # where it parts two pieces of text, none at the start or end of a
    # line; the markup keeps every move exactly
    move = lambda n: bytes([0xF9, n])
    raw = (move(16) + move(16) + enc("Yes") + move(10) + enc("No ") + move(3)
           + enc("x") + bytes([0x02]) + move(40) + enc("Title") + move(8))
    blk = table({1: raw}, slots=2)
    ct = lambda b: {0x02: 0xFF02}[b]
    d = ss.decode(blk, ss.string_offset(blk, 1), frag, ct)
    assert d.text == "Yes No x\nTitle"
    assert d.markup == ("{MOVE:16px}{MOVE:16px}Yes{MOVE:10px}No {MOVE:3px}x\n"
                        "{MOVE:40px}Title{MOVE:8px}")


def test_a_move_inside_a_splice_parts_it_from_the_text_around_it():
    # the spliced string's own leading move lies between "Do" and its text
    raw = enc("Do") + bytes([0xF0, 0x02])
    blk = table({1: raw, 2: bytes([0xF9, 0x05]) + enc("it")}, slots=3)
    d = ss.decode(blk, ss.string_offset(blk, 1), frag)
    assert d.text == "Do it"
    assert ss.decode(blk, ss.string_offset(blk, 2), frag).text == "it"


def test_the_message_window_controls_are_named():
    # MessageControlRun (0x8005AF20): 0xF8nn waits nn frames, 0xFAnn / 0xFBnn put face nn
    # in the left / right portrait place (face 0 takes the faces down,
    # MessageFaceSet 0x8005B36C), 0xFCnn sets the glyph style; none prints anything
    raw = (bytes([0xFA, 0x38]) + enc("Hi") + bytes([0xF8, 0x1E, 0xFB, 0x06, 0xFC, 0x02])
           + enc("you") + bytes([0xFC, 0x00, 0xFA, 0x00, 0xF7, 0x01]))
    blk = table({1: raw}, slots=2)
    d = ss.decode(blk, ss.string_offset(blk, 1), frag)
    assert d.text == "Hiyou"
    assert d.markup == ("{FACE_LEFT:0x38}Hi{WAIT:30 frames}{FACE_RIGHT:0x06}{STYLE:2}"
                        "you{STYLE:0}{FACES_OFF}{F701}")
    assert ss.control_markup(0xFB00) == "{FACES_OFF}"
    assert [ss.control_markup(c) for c in (0xFF00, 0xFF01, 0xFF02, 0xFF03)] == \
        ["{PROMPT}", "{PAGE}", "\n", "{CLOSE}"]


def test_message_window_codes_prompt_page_and_row():
    # 0xFF00 (the button prompt) adds no text; 0xFF01 (a new page) and
    # 0xFF02 (the next row) read as newlines — the same codes, and so the
    # same names, as a run's '%', '^' and '@'. The shape of string 0x652:
    # "…saved.{FF00}{FF01}To save…blocks{FF02}of RAM space.{FF00}{FF01}"
    raw = (enc("saved.") + bytes([0x04, 0x01]) + enc("To save") + bytes([0x02])
           + enc("space.") + bytes([0x04, 0x01]))
    blk = table({1: raw}, slots=2)
    ct = lambda b: {0x01: 0xFF01, 0x02: 0xFF02, 0x04: 0xFF00}[b]
    d = ss.decode(blk, ss.string_offset(blk, 1), frag, ct)
    assert d.text == "saved.\nTo save\nspace.\n"
    assert d.markup == "saved.{PROMPT}{PAGE}To save\nspace.{PROMPT}{PAGE}"


def test_glyph_codes_and_the_full_width_space():
    blk = table({1: bytes([0x10, 0x11])}, slots=2)
    ct = lambda b: {0x10: 0x8140, 0x11: 0x990A}[b]
    d = ss.decode(blk, ss.string_offset(blk, 1), frag, ct)
    assert d.text == " {GLYPH:990A}"


def test_categories_follow_the_callers_arithmetic():
    assert ss.category(0x001) == ("character", 1)
    assert ss.category(0x081) == ("enemy", 1)           # BtlMenuFirstOpen (0x80044780): id + 0x80
    assert ss.category(0x101) == ("item", 1)            # BtlActionStringDisp (0x8004987C): | 0x100
    assert ss.category(0x1D7) == ("spell", 33)          # row + 0x1B6
    assert ss.category(0x1FD) == ("menu", 0xFD)         # MenuCursorTextDisp (0x8006C8F0): command + 0x100
    assert ss.category(0x2FD) == ("description", 0xFD)  # and + 0x200
    assert ss.category(0x301) == ("enemy_special", 1)   # | 0x300
    assert ss.category(0x080) is None
    assert [c.name for c in ss.CATEGORIES if c.proof is None] == ["bromide"]


def test_words_count_nuls_from_the_base():
    # font_string_word_get (0x80059F4C): word n starts past n 0 bytes; asked
    # out of order, each word is still the one past its own count of 0s
    img = bytearray(ss.WORDS_ADDR - ss.EXE_BASE + 32)
    o = ss.WORDS_ADDR - ss.EXE_BASE
    img[o:o + 12] = b"ox\0ab\0Q \0Zu\0"
    look = ss.Words(bytes(img))
    assert [look(i) for i in (3, 0, 1, 2)] == [b"Zu", b"ox", b"ab", b"Q "]
    assert look.address(3) == ss.WORDS_ADDR + 9


def test_exe_words_are_the_512_words_font_string_word_get_counts():
    img = bytearray(ss.WORDS_ADDR - ss.EXE_BASE)
    for n in range(ss.WORD_COUNT):
        img += f"w{n} ".encode() + b"\0"
    img += b"past\0"
    words = ss.exe_words(bytes(img))
    assert len(words) == 512 and words[0] == (ss.WORDS_ADDR, b"w0 ")
    assert words[511][1] == b"w511 "
    look = ss.Words(bytes(img))
    assert all(look(n) == w for n, (_a, w) in enumerate(words))
    assert words[1][0] == ss.WORDS_ADDR + 4


def test_string_id_follows_each_categorys_rule():
    assert ss.string_id("movie", 1) == 0x501           # theater entry 1 = _B000
    assert ss.string_id("bgm", 60) == 0x546 + 60
    assert ss.string_id("location", 0x51) == 0x451
    assert ss.string_id("bromide", 0) == 0x538
    assert ss.string_id("enemy", 0) is None             # below the range
    assert ss.string_id("bromide", 13) is None          # past it


def test_game_strings_names_descriptions_and_blanks():
    g = ss.GameStrings({0x101: "Brass Knife", 0x201: "A small, plain blade",
                        0x538: "{GLYPH:99F0}", 0x081: "Puddle Beast"})
    assert g.name("item", 1) == "Brass Knife"
    assert g.description("item", 1) == "A small, plain blade"
    assert g.name("enemy", 1) == "Puddle Beast"
    assert g.name("bromide", 0) is None                 # a blank slot is no name
    assert g.name("item", 2) is None
    # icon number n: name n + 0x100, description n + 0x200 (BtlMenuSpellDisp
    # (0x80046258): a spell's icon number is the spell + 0xB6)
    s = ss.GameStrings({0x1B7: "Fire", 0x2B7: "Burns a foe", 0x181: "Ghoul"})
    assert s.description("spell", 1) == "Burns a foe"
    assert s.description("enemy", 1) is None            # an enemy's id is no icon number
    j = ss.GameStrings.from_json({"strings": [{"id": 0x081, "text": "Puddle Beast"}]})
    assert j.name("enemy", 1) == "Puddle Beast"


# ---- codes: font_string_walk (0x8005A884) as it is ------------------------------------------
#
# What this CAN catch: the order and value of every code the handler emits
# for a run (characters, the six controls, '$' ending the message, a
# backslash NOT ending it), a fragment (0x5C.., FD, FE; a backslash and '$'
# both ending the message there), a byte through g_FontStringCodes (0x800B34C0), a two-byte
# code, the 0x5500 fold of 0xD640..0xEFFF, and the index it returns. What it
# CANNOT catch: that these are the rules of the game's handler -- only
# reading the handler's C does; every expectation below was worked out
# from that C, not from this code's output.

CHARS = {1: 0xFF01, 2: 0xFF02, 3: 0xFF03, 4: 0xFF00, 0x10: 0x8140, 0x11: 0xD640, 0x12: 0xEFFF, 0x13: 0xF000}
ct = lambda b: CHARS.get(b, 0)


def test_codes_of_a_run_are_the_characters():
    # each byte of the run is its character less 0x1F (code = c + 0x1F)
    blk = bytes([0x0E, *(ord(c) - 0x1F for c in "Zap"), 0x00, 0xFF])
    assert ss.codes(blk, 0, frag, ct) == ([0x5A, 0x61, 0x70], 5)      # stops ON the 0xFF


def test_codes_of_the_six_run_controls():
    # '%' 0xFF00, '@' 0xFF02, '\' 0xFF03 and the run GOES ON, '*' 0xFF00 0xFF01, '^' 0xFF01
    # each byte is the character less 0x1F
    run = bytes([0x0E, *(ord(c) - 0x1F for c in "a%b@c\\d*e^f"), 0x00, 0xFF])
    assert ss.codes(run, 0, frag, ct)[0] == [0x61, 0xFF00, 0x62, 0xFF02, 0x63, 0xFF03, 0x64, 0xFF00, 0xFF01, 0x65, 0xFF01, 0x66]


def test_codes_dollar_ends_the_message_on_its_own_byte():
    # '$' -> 0xFF00, 0xFF03, return p - 1: p has stepped past the '$' at index 2
    blk = bytes([0x0E, ord("a") - 0x1F, ord("$") - 0x1F, ord("b") - 0x1F, 0x00, 0xFF])
    assert ss.codes(blk, 0, frag, ct) == ([0x61, 0xFF00, 0xFF03], 2)


def test_codes_of_a_fragment_and_its_two_long_forms():
    # 0x5C + n -> fragment n; FD b -> b + 0xA1; FE b -> b + 0x19E
    seen = []
    look = lambda n: (seen.append(n), b"ab")[1]
    blk = bytes([0x0E, 0x5C + 1, 0xFD, 0x02, 0xFE, 0x03, 0x00, 0xFF])
    assert ss.codes(blk, 0, look, ct) == ([0x61, 0x62] * 3, 7)
    assert seen == [1, 0xA3, 0x1A1]


def test_codes_a_fragments_controls_and_its_two_ends():
    # FRAGS[2] = "x@y%": 'x', 0xFF02, 'y', 0xFF00 -- and the run goes on
    blk = bytes([0x0E, 0x5C + 2, ord("z") - 0x1F, 0x00, 0xFF])
    assert ss.codes(blk, 0, frag, ct) == ([0x78, 0xFF02, 0x79, 0xFF00, 0x7A], 4)
    # in a fragment a backslash ENDS the message too, returning
    # the fragment's own index byte: here index 1
    look = lambda n: b"p\\q"
    assert ss.codes(bytes([0x0E, 0x5C, ord("z") - 0x1F, 0x00, 0xFF]), 0, look, ct) == ([0x70, 0xFF03], 1)
    look = lambda n: b"p$q"
    assert ss.codes(bytes([0x0E, 0xFD, 0x00, ord("z") - 0x1F, 0x00, 0xFF]), 0, look, ct) == ([0x70, 0xFF00, 0xFF03], 2)


def test_codes_outside_a_run_table_bytes_and_two_byte_codes():
    # a byte below 0xD6 is g_FontStringCodes[byte] (0x800B34C0); from 0xD6 up it and
    # the next byte; 0xD640..0xEFFF lose 0x5500; above
    # 0xEFFF the code is passed as it is
    blk = bytes([0x10, 0x11, 0x12, 0x13, 0x04, 0xD6, 0x3F, 0xD6, 0x40, 0xF6, 0x6A, 0xFA, 0x38, 0x03, 0xFF])
    assert ss.codes(blk, 0, frag, ct) == (
        [0x8140, 0xD640 - 0x5500, 0xEFFF - 0x5500, 0xF000, 0xFF00, 0xD63F, 0xD640 - 0x5500, 0xF66A, 0xFA38, 0xFF03], 14)


def test_codes_a_stream_with_no_end_is_refused():
    with pytest.raises(ValueError):
        ss.codes(bytes([0x0E, 0x28, 0x00]), 0, frag, ct)
    with pytest.raises(ValueError):
        ss.codes(bytes([0x0E, 0x28]), 0, frag, ct)
    with pytest.raises(ValueError):
        ss.codes(bytes([0xF6]), 0, frag, ct)


def test_walk_hands_characters_and_controls_to_their_own_callbacks():
    chars, ctls = [], []
    blk = enc("a%b") + bytes([0xF9, 0x04, 0xEA, 0x40, 0xFF])
    end = ss.walk(blk, 0, frag, ct, chars.append, ctls.append)
    assert end == len(blk) - 1
    assert chars == [0x61, 0x62, 0xEA40 - 0x5500]
    assert ctls == [0xFF00, 0xF904]


def test_a_message_takes_its_splices_from_the_table_passed_in():
    strings = table({3: enc("bob")}, 4)
    msg = enc("hi ") + bytes([0xF0, 0x03]) + b"\xff"
    d = ss.decode(msg, 0, frag, ct, table=strings)
    assert d.text == "hi bob"
    assert d.markup == "hi {STR:0x003}"
    assert ss.splice_id(0xF603) == 0x603 and ss.splice_id(0xF903) is None


def test_string_codes_gives_every_string_its_bytes_and_codes():
    blk = table({1: enc("Got"), 3: bytes([0xF6, 0x01, 0x04])}, slots=4)
    t = ss.string_codes(blk, frag, ct)
    assert sorted(t) == [1, 3]
    assert t[1] == (enc("Got") + b"\xff", [0x47, 0x6F, 0x74])
    assert t[3] == (bytes([0xF6, 0x01, 0x04, 0xFF]), [0xF601, 0xFF00])
    doc = ss.string_codes_json(t, [7, 8])
    assert doc["char_table"] == [7, 8]
    assert doc["strings"][0] == {"id": 1, "bytes": (enc("Got") + b"\xff").hex(), "codes": [0x47, 0x6F, 0x74]}


def test_char_table_words_are_0xd6_little_endian_words_at_the_symbol():
    assert ss.CHAR_TABLE_ADDR == 0x800B34C0 and ss.CHAR_TABLE_ENTRIES == 0xD6
    off = ss.CHAR_TABLE_ADDR - ss.EXE_BASE
    img = bytearray(b"\xEE" * (off + 2 * 0xD6 + 4))
    img[0] = 0                      # no build stamp: the US program (conftest)
    for b in range(0xD6):
        struct.pack_into("<H", img, off + 2 * b, 0x4000 + b)
    w = ss.char_table_words(bytes(img))
    assert len(w) == 0xD6 and w[0] == 0x4000 and w[4] == 0x4004 and w[0xD5] == 0x40D5
    with pytest.raises(ValueError):
        ss.char_table_words(bytes(img[:off + 2 * 0xD6 - 1]))


# ---- on the user's disc (skipped without it) ---------------------------------


_DISC = config.raw_dir("SLUS_006.28")
_on_disc = pytest.mark.skipif(not (_DISC / "SLUS_006.28").exists(),
                              reason="no extracted SSSC disc in the library")


@pytest.fixture(scope="module")
def disc():
    from decoders.psx.analysis.exe_loader import load_exe
    from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
    binary = load_exe(_DISC / "SLUS_006.28")
    res = {r.index: r for r in load_resource_table(binary)}
    return binary.code, ss.block(res[ss.RESOURCE].read(_DISC / "LUNADATA.FIL"))


@pytest.mark.disc
@_on_disc
def test_disc_the_dictionary_is_512_words_ending_where_the_register_says(disc):
    image, _blk = disc
    words = ss.exe_words(image)
    assert len(words) == 512
    assert all(2 <= len(w) <= 34 and all(0x20 <= c <= 0x7E for c in w) for _a, w in words)
    last_addr, last = words[-1]
    assert last_addr + len(last) + 1 == 0x800B45F0      # g_FontStringWords's end


@pytest.mark.disc
@_on_disc
def test_disc_a_pen_move_never_reads_as_a_run_of_spaces(disc):
    image, blk = disc
    table = ss.strings(blk, ss.Words(image), ss.exe_char_table(image))
    moved = {sid: d for sid, d in table.items() if "{MOVE:" in d.markup}
    assert moved
    for d in moved.values():
        assert "  " not in d.text
        assert all(row == row.strip(" ") for row in d.text.split("\n"))


def test_with_no_dictionary_0x0e_is_a_table_byte():
    # SLPS_013.97's walk: no runs, every byte below 0xD6 through the table
    chars, ctls = [], []
    end = ss.walk(bytes([0x0E, 0x41, 0xFF]), 0, None, lambda b: 0x100 + b,
                  chars.append, ctls.append)
    assert end == 2
    assert (chars, ctls) == ([0x10E, 0x141], [])


def test_the_japanese_program_has_no_dictionary(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    img = bytes(jp_image(0x100))
    assert ss.words_of(img) is None
    with pytest.raises(programs.Unmapped):
        ss.Words(img)


def test_the_japanese_char_table_is_read_at_its_own_address(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    at = programs.JP_TABLES["g_FontStringCodes"].addr - ss.EXE_BASE
    img = jp_image(at + 2 * 0xD6)
    struct.pack_into("<H", img, at + 2 * 0x41, 0x1234)
    assert ss.exe_char_table(bytes(img))(0x41) == 0x1234


def test_a_programs_characters_read_its_glyph_codes():
    # made-up characters for made-up codes; a code with none keeps its mark
    blk = table({1: bytes([0x10, 0x11, 0x12, 0x13])}, slots=2)
    ct = lambda b: {0x10: 0x9A01, 0x11: 0x9A02, 0x12: 0x8140, 0x13: 0x9A03}[b]
    chars = {0x9A01: "x", 0x9A02: "y", 0x8140: "　"}.get
    d = ss.decode(blk, ss.string_offset(blk, 1), None, ct, characters=chars)
    assert d.text == "xy　{GLYPH:9A03}"
    assert ss.GameStrings.decode_block(blk, None, ct, chars).text(1) == d.text


def test_only_the_japanese_program_has_characters(jp_image):
    from decoders.plugins.SLUS_006_28.formats import jp_characters as jc
    assert ss.characters_of(bytes(jp_image(0x100))) is jc.character
    assert ss.characters_of(bytes(0x100)) is None


def test_walk_end_stops_where_walk_does():
    """walk_end is walk with nothing handed on: made-up streams of 0x0E
    runs, dictionary words (ending ones too), two-byte codes and streams
    cut short stop at the same byte, or are refused alike."""
    import random
    words = ss.Words(bytes(ss.WORDS_ADDR - ss.EXE_BASE) + b"ab\x00\x5c\x00$\x00c\x00"
                     + bytes(0x400))
    rng = random.Random(3)

    def run(fn, *a):
        try:
            return fn(*a)
        except ValueError as e:
            return str(e)

    pieces = [b"\x0e", b"\x00", b"\xff", b"\x05", b"\x5c", b"\x5d", b"\x5e", b"\x5f",
              b"\xfd", b"\xfe", b"\xd6", b"\xf0", b"\x41", b"\x24"]
    for _ in range(4000):
        buf = b"".join(rng.choice(pieces) for _ in range(rng.randrange(1, 14)))
        for dictionary in (words, None):
            assert run(ss.walk_end, buf, 0, dictionary) == run(
                ss.walk, buf, 0, dictionary, lambda b: 0, lambda c: None,
                lambda c: None), (buf.hex(), dictionary)
