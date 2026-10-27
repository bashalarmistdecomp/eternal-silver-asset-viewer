"""Tier 1 for the executable's own text — synthetic bytes, no game data.

What this CAN catch: the dictionary read as font_string_word_get (0x80059F4C) counts its
words (exactly 512, numbered from 0, nothing read past the last), the
short-name table's indexing (location id - 0x51, a slot that does not point
at text left out), the runs its texts lie in, the developers' texts read at
the register's addresses, and the blocks the Program text tab is given.

What it CANNOT catch: that 0x800B386C is the dictionary or 0x800A8618 the
short-name table — only re-reading their readers does. See
decoders/testing.py.
"""

import struct

from decoders.psx.analysis.exe_loader import LoadedBinary
from decoders.plugins.SLUS_006_28.formats import script_text as st
from decoders.plugins.SLUS_006_28.formats import system_strings as ss

BASE = 0x80011000
NAMES = 0x800A8618


def image() -> bytearray:
    """An image with 512 dictionary words, then a table that is not words."""
    img = bytearray(ss.WORDS_ADDR - BASE)
    for n in range(ss.WORD_COUNT):
        img += f"w{n} ".encode() + b"\0"
    img += b"\0\0" + b"not a word\0"
    img += bytes(0x800B8700 - BASE - len(img))
    return img


def binary(img: bytes) -> LoadedBinary:
    return LoadedBinary(raw=bytes(img), text_start=BASE, text_size=len(img), entry_point=BASE)


def test_the_dictionary_is_its_512_words_numbered_from_0():
    block = st.dictionary_block(bytes(image()))
    assert len(block.entries) == 512
    assert block.address == ss.WORDS_ADDR
    assert block.entries[0].text == '  0  "w0 "'
    assert block.entries[511].text == '511  "w511 "'
    assert block.entries[1].address == ss.WORDS_ADDR + 4
    assert not any("not a word" in e.text for e in block.entries)
    end = block.entries[511].address + len("w511 ") + 1
    assert f"512 words, 0x{ss.WORDS_ADDR:08X}-0x{end:08X}" in block.note


def test_short_names_by_location_id_and_the_tabs_blocks():
    img = image()
    text = 0x800A9000
    img[text - BASE: text - BASE + 10] = b"Somewhere\0"
    struct.pack_into("<I", img, NAMES - BASE, text)                # id 0x51
    struct.pack_into("<I", img, NAMES - BASE + 4, 0x12345678)      # id 0x52: not in the image
    struct.pack_into("<I", img, NAMES - BASE + 8, ss.WORDS_ADDR + 4)   # id 0x53: "w1 "
    b = binary(img)
    assert st.read_location_names(b) == {0x51: "Somewhere", 0x53: "w1 "}
    blocks = st.exe_text_blocks(b)
    assert [x.label.split(" ")[0] for x in blocks[:2]] == ["Dictionary", "Location"]
    assert blocks[1].entries[0].text == "[0x51] Somewhere"


def test_the_short_names_note_gives_the_runs_their_texts_lie_in():
    # back to back up to word padding; a far text starts a run of its own
    assert st.text_runs([(0x100, "ab"), (0x104, "cdefg"), (0x10C, "h"),
                         (0x104, "cdefg"), (0x200, "far")]) == [(0x100, 0x10D, 3), (0x200, 0x203, 1)]


def test_a_japanese_text_is_measured_in_its_bytes():
    # two characters, four bytes: the next text, 4 bytes past its 0, is
    # the same run
    assert st.text_runs([(0x100, "\u3042\u3044"), (0x108, "x")]) == [(0x100, 0x109, 2)]


def test_the_developers_texts_are_read_at_the_registers_addresses():
    img = image()
    for i, t in enumerate(st.DEVELOPER_TEXTS):
        made_up = f"dev{i}".encode() + b"\0"
        img[t.addr - BASE: t.addr - BASE + len(made_up)] = made_up
    blocks = st.exe_text_blocks(binary(img))
    dev = blocks[-1]
    assert dev.label.startswith("Developers' texts")
    assert [e.address for e in dev.entries] == [t.addr for t in st.DEVELOPER_TEXTS]
    assert dev.entries[2].text.startswith('0x800B8594  D_800B8594  "dev2"')


def test_the_japanese_short_names_are_shift_jis_and_there_is_no_dictionary(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    names = programs.JP_TABLES["g_CardSavePlaceNames"].addr
    img = jp_image(0x800B8700 - BASE)
    made_up = "どこか"                          # a made-up name
    text = 0x800A9000
    raw = made_up.encode("shift_jis") + b"\0"
    img[text - BASE:text - BASE + len(raw)] = raw
    img[text - BASE + 0x10:text - BASE + 0x12] = b"\x81\0"   # half a character
    struct.pack_into("<I", img, names - BASE, text)                # id 0x51
    struct.pack_into("<I", img, names - BASE + 4, text + 0x10)     # id 0x52: not text
    assert st.read_location_names(binary(img)) == {0x51: made_up}
    block = st.dictionary_block(bytes(img))
    assert not block.entries and "no dictionary" in block.note
