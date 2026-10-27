"""Which file a disc is added from (library._image_for)."""

from viewer_server.library import _image_for


def test_a_bin_is_added_through_the_sheet_that_describes_it(tmp_path):
    image = tmp_path / "Renamed (Demo).bin"
    image.write_bytes(b"")
    cue = tmp_path / "Renamed (Demo).cue"
    cue.write_text('FILE "OLD NAME.BIN" BINARY\n  TRACK 01 MODE2/2352\n'
                   '    INDEX 01 00:00:00\n')
    assert _image_for(image) == cue
    assert _image_for(cue) == cue


def test_a_bin_no_sheet_describes_is_added_itself(tmp_path):
    image = tmp_path / "a.bin"
    image.write_bytes(b"")
    (tmp_path / "b.bin").write_bytes(b"")
    (tmp_path / "x.cue").write_text('FILE "c.bin" BINARY\n  TRACK 01 MODE2/2352\n'
                                    '    INDEX 01 00:00:00\n')
    assert _image_for(image) == image


def test_a_sheet_s_suffix_is_matched_in_any_case(tmp_path):
    image = tmp_path / "LUNAR.BIN"
    image.write_bytes(b"")
    cue = tmp_path / "LUNAR.CUE"
    cue.write_text('FILE "LUNAR.BIN" BINARY\n  TRACK 01 MODE2/2352\n'
                   '    INDEX 01 00:00:00\n')
    assert _image_for(image) == cue
