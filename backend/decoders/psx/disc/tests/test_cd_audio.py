"""Red Book track resolution — and the INDEX 01 trap.

The trap (docs/spec/sound.md): a track must be read from **INDEX 01**, not
from byte 0. INDEX 00 is the pregap — for Lunar's split-BIN rip that is two
seconds (150 sectors) of silence at the head of every track file, and
reading from zero prepends it to the music.

Fixtures here are synthetic BINs filled with a recognisable pattern, so a
test can tell "started at the right byte" from "started at zero" — which a
silence-only fixture could not.
"""

from decoders.psx.disc import cd_audio

PREGAP_SECTORS = 150          # two seconds at 75 sectors/second


def _bin(tmp_path, name, pregap_sectors, audio_sectors):
    """A track file: silent pregap, then a non-zero body."""
    path = tmp_path / name
    path.write_bytes(b"\x00" * (pregap_sectors * cd_audio.CD_SECTOR)
                     + b"\x7F" * (audio_sectors * cd_audio.CD_SECTOR))
    return path


def _cue(tmp_path, text, name="disc.cue"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_msf_to_sectors():
    assert cd_audio.msf_to_sectors("00:00:00") == 0
    assert cd_audio.msf_to_sectors("00:02:00") == PREGAP_SECTORS
    assert cd_audio.msf_to_sectors("01:00:00") == 75 * 60
    assert cd_audio.msf_to_sectors("00:00:74") == 74      # 75 frames/second


def test_malformed_msf_is_zero_not_an_exception():
    assert cd_audio.msf_to_sectors("garbage") == 0
    assert cd_audio.msf_to_sectors("") == 0


def test_track_starts_at_index_01_not_byte_zero(tmp_path):
    """THE trap."""
    _bin(tmp_path, "track2.bin", PREGAP_SECTORS, 10)
    cue = _cue(tmp_path, 'FILE "track2.bin" BINARY\n'
                         '  TRACK 02 AUDIO\n'
                         '    INDEX 00 00:00:00\n'
                         '    INDEX 01 00:02:00\n')
    (track,) = cd_audio.load_tracks(cue)

    assert track.start == PREGAP_SECTORS * cd_audio.CD_SECTOR
    assert track.pregap_sectors == PREGAP_SECTORS
    # The first bytes read must be audio, not the silent lead-in.
    assert track.read(frames=4) == b"\x7F" * 16


def test_size_excludes_the_pregap(tmp_path):
    _bin(tmp_path, "track2.bin", PREGAP_SECTORS, 10)
    cue = _cue(tmp_path, 'FILE "track2.bin" BINARY\n'
                         '  TRACK 02 AUDIO\n'
                         '    INDEX 00 00:00:00\n    INDEX 01 00:02:00\n')
    (track,) = cd_audio.load_tracks(cue)
    assert track.sectors == 10
    assert track.frames == 10 * cd_audio.CD_FRAMES_PER_SECTOR


def test_data_track_is_not_returned(tmp_path):
    _bin(tmp_path, "data.bin", 0, 4)
    cue = _cue(tmp_path, 'FILE "data.bin" BINARY\n'
                         '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    assert cd_audio.load_tracks(cue) == []


def test_missing_bin_is_skipped_not_raised(tmp_path):
    cue = _cue(tmp_path, 'FILE "absent.bin" BINARY\n'
                         '  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n')
    assert cd_audio.load_tracks(cue) == []


def test_single_bin_track_ends_where_the_next_begins(tmp_path):
    """The other cue layout: consecutive tracks sharing one file."""
    path = tmp_path / "whole.bin"
    path.write_bytes(b"\x11" * (20 * cd_audio.CD_SECTOR))
    cue = _cue(tmp_path, 'FILE "whole.bin" BINARY\n'
                         '  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n'
                         '  TRACK 03 AUDIO\n    INDEX 01 00:00:10\n')
    first, second = cd_audio.load_tracks(cue)
    assert first.sectors == 10, "track 2 must stop where track 3 starts"
    assert second.start == 10 * cd_audio.CD_SECTOR


def test_start_past_end_of_file_falls_back_to_zero(tmp_path):
    """A cue whose INDEX 01 overruns its BIN must still be readable."""
    _bin(tmp_path, "short.bin", 0, 1)
    cue = _cue(tmp_path, 'FILE "short.bin" BINARY\n'
                         '  TRACK 02 AUDIO\n    INDEX 01 10:00:00\n')
    (track,) = cd_audio.load_tracks(cue)
    assert track.start == 0


def test_read_clamps_to_the_track(tmp_path):
    _bin(tmp_path, "track2.bin", 0, 2)
    cue = _cue(tmp_path, 'FILE "track2.bin" BINARY\n'
                         '  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n')
    (track,) = cd_audio.load_tracks(cue)
    assert len(track.read(frames=10 ** 9)) == track.size
    assert track.read(start_frame=track.frames) == b""


def test_to_wav_is_stereo_44k(tmp_path):
    _bin(tmp_path, "track2.bin", 0, 1)
    cue = _cue(tmp_path, 'FILE "track2.bin" BINARY\n'
                         '  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n')
    (track,) = cd_audio.load_tracks(cue)
    wav = track.to_wav(frames=100)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert int.from_bytes(wav[22:24], "little") == cd_audio.CD_CHANNELS
    assert int.from_bytes(wav[24:28], "little") == cd_audio.CD_RATE


def test_a_track_without_index_00_has_no_pregap_in_its_file(tmp_path):
    # Single BIN: data, then audio after a PREGAP line (not stored).
    path = tmp_path / "one.bin"
    path.write_bytes(b"\x01" * (4 * cd_audio.CD_SECTOR) + b"\x7F" * (3 * cd_audio.CD_SECTOR))
    cue = _cue(tmp_path, 'FILE "one.bin" BINARY\n'
                         '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
                         '  TRACK 02 AUDIO\n    PREGAP 00:02:00\n    INDEX 01 00:00:04\n')
    (track,) = cd_audio.load_tracks(cue)
    assert track.start == 4 * cd_audio.CD_SECTOR and track.pregap_sectors == 0
    assert track.read(frames=2) == b"\x7F" * 8
