"""Tier 1 for play events — synthetic values, no game data.

What this CAN catch: MoviePlay (0x800232D4)'s split (bromides at 0x37..0x43, movies
otherwise), the movie file name and disc rule, the theater's entry - 1,
the bromide resource base, the MENU.BIN table's offset and stride, and
the picture voice table's place and length.

What it CANNOT catch: whether those constants are this program's — only
re-reading MoviePlay / movie_play (0x80196B54) does that. See
decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.records import events as ev


def test_events_split_at_the_bromides():
    m = ev.event(4)
    assert (m.kind, m.movie, m.disc) == ("movie", "_B004.STR", 1)
    assert ev.event(0x24).disc == 2
    b = ev.event(0x37 + 2)
    assert (b.kind, b.bromide, b.resource) == ("bromide", 2, 0x24C)
    assert ev.event(0x44).kind == "movie"


def test_theater_and_file_names():
    assert ev.theater_event(1) == 0
    assert ev.movie_number("_B035.STR") == 35
    assert ev.movie_number("MENU.BIN") is None


def test_bromide_resources():
    assert ev.bromide_for_resource(0x24A) == 0
    assert ev.bromide_for_resource(0x256) == 12
    assert ev.bromide_for_resource(0x257) is None


def test_end_frame_table():
    blob = bytearray(ev.END_FRAME_ADDR - ev.MENU_BIN_BASE + 2 * ev.MOVIE_COUNT)
    struct.pack_into("<H", blob, ev.END_FRAME_ADDR - ev.MENU_BIN_BASE + 2 * 3, 812)
    frames = ev.end_frames(bytes(blob))
    assert len(frames) == ev.MOVIE_COUNT and frames[3] == 812 and frames[0] == 0


def test_resource_roles():
    assert ev.resource_role(0x24B) == "bromide 1"
    assert ev.resource_role(0x257) == "disc-change and end screens"
    assert ev.resource_role(0x167) is None


def test_picture_voices_are_read_by_bromide():
    image = bytearray(ev.PICTURE_VOICES_ADDR - 0x80011000 + ev.BROMIDE_COUNT + 4)
    at = ev.PICTURE_VOICES_ADDR - 0x80011000
    image[at:at + ev.BROMIDE_COUNT] = bytes(range(40, 40 + ev.BROMIDE_COUNT))
    image[at + ev.BROMIDE_COUNT] = 99                   # past the table
    voices = ev.picture_voices(bytes(image))
    assert voices == list(range(40, 40 + ev.BROMIDE_COUNT))
