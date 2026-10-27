"""Cue-sheet parsing.

The cue sheet is what says where a disc's audio tracks begin, so it feeds
the INDEX 01 rule that `cd_audio` depends on (see test_cd_audio.py). The
distinction that matters here is INDEX 00 (pregap) versus INDEX 01 (where
the audio actually starts) — a track carries both, and the parser must keep
them apart rather than collapsing to "the first index it saw". A sheet's
first FILE line lost to a byte-order mark, or a name not in UTF-8 or not
quoted read wrong, is caught here too.
"""

from decoders.psx.disc.cue_parser import parse_cue

SHEET = """FILE "LUNAR.BIN" BINARY
  TRACK 01 MODE2/2352
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    INDEX 00 55:44:33
    INDEX 01 55:46:33
  TRACK 03 AUDIO
    INDEX 00 58:12:00
    INDEX 01 58:14:00
"""


def _write(tmp_path, text=SHEET, name="LUNAR.cue"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_track_count_and_types(tmp_path):
    sheet = parse_cue(_write(tmp_path))
    assert [t.number for t in sheet.tracks] == [1, 2, 3]
    assert sheet.tracks[0].track_type == "MODE2/2352"
    assert sheet.tracks[1].track_type == "AUDIO"


def test_data_and_audio_tracks_are_separated(tmp_path):
    sheet = parse_cue(_write(tmp_path))
    assert sheet.data_track.number == 1
    assert sheet.data_track.is_data
    assert [t.number for t in sheet.audio_tracks] == [2, 3]
    assert not any(t.is_data for t in sheet.audio_tracks)


def test_pregap_and_start_indices_are_kept_apart(tmp_path):
    """INDEX 00 is the pregap; INDEX 01 is where audio starts."""
    track2 = parse_cue(_write(tmp_path)).tracks[1]
    assert track2.indices[0] == "55:44:33"
    assert track2.indices[1] == "55:46:33"


def test_bin_path_resolves_relative_to_the_cue(tmp_path):
    sheet = parse_cue(_write(tmp_path))
    assert sheet.tracks[0].filename == "LUNAR.BIN"
    assert sheet.tracks[0].file_path == tmp_path / "LUNAR.BIN"


def test_split_bin_rip_tracks_their_own_files(tmp_path):
    split = ('FILE "d1 (Track 1).bin" BINARY\n'
             '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
             'FILE "d1 (Track 2).bin" BINARY\n'
             '  TRACK 02 AUDIO\n    INDEX 00 00:00:00\n    INDEX 01 00:02:00\n')
    sheet = parse_cue(_write(tmp_path, split, "split.cue"))
    assert sheet.tracks[0].filename == "d1 (Track 1).bin"
    assert sheet.tracks[1].filename == "d1 (Track 2).bin"


def test_unknown_lines_are_ignored(tmp_path):
    noisy = 'REM GENRE Game\nPERFORMER "Working Designs"\n' + SHEET
    assert len(parse_cue(_write(tmp_path, noisy, "noisy.cue")).tracks) == 3


def test_empty_sheet(tmp_path):
    assert parse_cue(_write(tmp_path, "", "empty.cue")).tracks == []


def test_a_renamed_single_bin_is_the_one_bin_beside_its_sheet(tmp_path):
    (tmp_path / "Renamed (Demo).bin").write_bytes(b"\0" * 16)
    sheet = parse_cue(_write(tmp_path))
    assert sheet.tracks[0].filename == "LUNAR.BIN"            # as the sheet says
    assert all(t.file_path == tmp_path / "Renamed (Demo).bin" for t in sheet.tracks)


def test_a_missing_file_stays_missing_when_the_bin_is_not_certain(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"")
    (tmp_path / "b.bin").write_bytes(b"")
    sheet = parse_cue(_write(tmp_path))
    assert sheet.tracks[0].file_path == tmp_path / "LUNAR.BIN"
    split = ('FILE "d1 (Track 1).bin" BINARY\n'
             '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
             'FILE "d1 (Track 2).bin" BINARY\n'
             '  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n')
    for p in (tmp_path / "a.bin", tmp_path / "b.bin"):
        p.unlink()
    (tmp_path / "only.bin").write_bytes(b"")
    sheet = parse_cue(_write(tmp_path, split, "split.cue"))
    assert sheet.tracks[1].file_path == tmp_path / "d1 (Track 2).bin"


def test_a_sheet_with_a_byte_order_mark_keeps_its_first_file(tmp_path):
    path = tmp_path / "bom.cue"
    path.write_bytes(b"\xef\xbb\xbf" + SHEET.encode())
    sheet = parse_cue(path)
    assert sheet.data_track.filename == "LUNAR.BIN"
    assert sheet.data_track.file_path == tmp_path / "LUNAR.BIN"


def test_a_sheet_not_in_utf8_names_its_file_all_the_same(tmp_path):
    path = tmp_path / "old.cue"
    path.write_bytes(SHEET.replace("LUNAR.BIN", "Lunar \xe9t\xe9.bin").encode("latin-1"))
    assert parse_cue(path).data_track.filename == "Lunar \xe9t\xe9.bin"


def test_an_unquoted_file_name_is_read(tmp_path):
    sheet = parse_cue(_write(tmp_path, SHEET.replace('"LUNAR.BIN"', "LUNAR.BIN"), "bare.cue"))
    assert [t.filename for t in sheet.tracks] == ["LUNAR.BIN"] * 3
