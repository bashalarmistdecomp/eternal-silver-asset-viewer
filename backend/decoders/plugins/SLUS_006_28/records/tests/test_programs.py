"""Tier 1 for telling the two programs apart — made-up stamps, no game data.

What this CAN catch: a stamp read from the wrong place, an image of either
kind (bytes or a loaded binary) read differently, a Japanese address given
for a table that has no row, an image of neither program read as the US
one (a reader would then give plausible numbers instead of an error), a
row whose proof does not name both programs' functions.

What it CANNOT catch: whether a Japanese address is right — only reading
the Japanese function named in its row does that.
"""

import re

import pytest

from decoders.plugins.SLUS_006_28.records import programs as pg


@pytest.fixture
def stamps(monkeypatch):
    """Two made-up stamps standing for the two programs."""
    us, jp = b"made-up stamp one", b"made-up stamp two"
    monkeypatch.setattr(pg, "STAMPS", {pg.stamp_digest(us): pg.US,
                                       pg.stamp_digest(jp): pg.JP})
    return us, jp


def _image(stamp: bytes) -> bytes:
    return stamp + b"\0" + bytes(0x100)


def test_a_stamp_names_its_program(stamps):
    us, jp = stamps
    assert pg.program_of(_image(us)) == pg.US
    assert pg.program_of(_image(jp)) == pg.JP


@pytest.mark.parametrize("image", [_image(b"no such stamp"), b"", bytes(0x100)])
def test_an_unknown_stamp_is_no_program_and_its_tables_are_not_known(stamps, image):
    assert pg.program_of(image) is None
    with pytest.raises(pg.UnknownProgram):
        pg.address(image, "anything", 0x80012345)
    with pytest.raises(pg.UnknownProgram):
        pg.has(image, "anything")
    assert issubclass(pg.UnknownProgram, pg.Unmapped)      # callers that catch one


def test_the_stamp_ends_at_its_zero(stamps):
    _us, jp = stamps
    assert pg.program_of(jp + b"\0" + b"anything after") == pg.JP


def test_a_loaded_binary_is_read_at_the_image_base(stamps):
    _us, jp = stamps

    class Loaded:
        def read_bytes(self, addr, n):
            assert addr == pg.EXE_BASE
            return _image(jp)[:n]

    assert pg.program_of(Loaded()) == pg.JP


def test_the_us_program_keeps_its_own_addresses(stamps):
    us, _jp = stamps
    assert pg.address(_image(us), "anything", 0x80012345) == 0x80012345
    assert pg.has(_image(us), "anything")


def test_the_japanese_program_takes_its_rows(stamps):
    _us, jp = stamps
    name, row = next(iter(pg.JP_TABLES.items()))
    assert pg.address(_image(jp), name, 0x80012345) == row.addr
    assert pg.has(_image(jp), name)


def test_a_table_with_no_row_is_unmapped(stamps):
    _us, jp = stamps
    assert not pg.has(_image(jp), "no_such_table")
    with pytest.raises(pg.Unmapped):
        pg.address(_image(jp), "no_such_table", 0x80012345)


def test_every_row_names_the_function_in_both_programs():
    cite = re.compile(r"\w+ \(0x[0-9A-F]{8}; SLPS_013\.97 (MENU\.BIN )?0x[0-9A-F]{8}\)")
    for name, row in pg.JP_TABLES.items():
        assert cite.search(row.proof), name
        assert 0x80010000 <= row.addr < 0x80200000, name


def test_a_reader_reads_the_japanese_row_and_a_menu_bin_its_own(jp_image):
    from decoders.plugins.SLUS_006_28.records import areas, events
    numbers = pg.JP_TABLES["g_MapTblNumbers"].addr - pg.EXE_BASE
    img = jp_image(areas.AREA_INDEX_ADDR - pg.EXE_BASE + 0x100)
    img[numbers + 0x15] = 3
    img[areas.AREA_INDEX_ADDR - pg.EXE_BASE + 0x15] = 9     # the US place: not read
    assert areas.area_record_index(bytes(img), 0x15) == 3
    frames = pg.JP_TABLES["D_8019769C"].addr - events.MENU_BIN_BASE
    menu = jp_image(frames + 2 * events.MOVIE_COUNT)
    menu[frames + 2 * 3] = 7
    assert events.end_frames(bytes(menu))[3] == 7
