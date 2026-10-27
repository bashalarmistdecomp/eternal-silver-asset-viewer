"""Whose a portrait is (viewer_tabs.whose) — made-up pictures, no disc.

What this CAN catch: a face of files 13 to 24 given to a character by its
file number, a picture a few pixels off one of a character's not taken for
theirs, one changed in more than the limit taken for theirs, a blank
picture given to anyone, a copy given to the farther of two originals,
and the words for a speaker.

What it CANNOT catch: whether the disc's pictures are read right (the face
decoder's tests and the on-disc tests do that), or whether the copies the
discs hold are the ones the rule finds (test_characters_on_disc).
"""

from types import SimpleNamespace

from viewer_tabs import whose
from viewer_tabs.refs import ref
from viewer_tabs.whose import COPY_PIXELS, SIDE, Whose, own_character, read

N = SIDE * SIDE


def picture(seed: int) -> bytes:
    """A made-up 64 x 64 picture, no texel 0."""
    return bytes((i * 7 + seed * 31) % 250 + 1 for i in range(N))


def changed(px: bytes, count: int, start: int = 25 * SIDE) -> bytes:
    """`px` with `count` texels changed from `start` on."""
    out = bytearray(px)
    for i in range(start, start + count):
        out[i] = out[i] % 250 + 2
    return bytes(out)


def test_a_characters_file_is_their_number_up_to_twelve():
    assert [own_character(f) for f in (1, 5, 6, 60, 61, 120, 0)] == [1, 1, 2, 12, None, None, None]


def test_a_face_past_the_characters_files_is_no_ones():
    got = read({1: picture(1), 61: picture(2)})
    assert got == {1: Whose(1), 61: Whose(None)}


def test_a_picture_a_few_pixels_off_a_characters_is_theirs():
    got = read({6: picture(3), 98: changed(picture(3), 18)})
    assert got[98] == Whose(2, 6, 18)


def test_the_limit_is_the_last_copy():
    got = read({6: picture(3), 97: changed(picture(3), COPY_PIXELS),
                98: changed(picture(3), COPY_PIXELS + 1)})
    assert got[97] == Whose(2, 6, COPY_PIXELS)
    assert got[98] == Whose(None)


def test_changes_spread_over_many_rows_still_count_by_pixel():
    # one texel in each of 30 rows: 30 rows differ, 30 pixels
    px = bytearray(picture(4))
    for row in range(30):
        px[row * SIDE + 5] ^= 0x40
    assert read({11: picture(4), 99: bytes(px)})[99] == Whose(3, 11, 30)


def test_a_copy_goes_to_the_nearer_original():
    base = picture(5)
    got = read({16: base, 21: changed(base, 10, 0), 100: changed(base, 4)})
    assert got[100] == Whose(4, 16, 4)


def test_a_blank_picture_is_no_ones():
    blank = bytes(N)
    got = read({32: blank, 61: blank, 1: picture(6)})
    assert got[32] == Whose(None) and got[61] == Whose(None)


def test_a_copy_of_a_copy_is_not_followed():
    # only a character's own file is an original
    got = read({6: picture(7), 98: changed(picture(7), 30),
                99: changed(changed(picture(7), 30), 30, 40 * SIDE)})
    assert got[98].character == 2 and got[99] == Whose(None)


def test_the_words_for_a_speaker():
    m = SimpleNamespace(names=SimpleNamespace(character=lambda n: {2: "Made-up"}.get(n)))
    assert whose.word(m, ref("character", 2)) == "Made-up"
    assert whose.word(m, ref("character", 5)) == "character 5"
    assert whose.word(m, ref("portrait", 91)) == "portrait 91"
    assert whose.name(m, 13) is None
