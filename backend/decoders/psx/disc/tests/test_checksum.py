"""Which bytes identify a disc (checksum, extractor.data_track_range).

gamedb's checksums are of the data track alone. A single-BIN image holds
the audio tracks after it in the same file, so its checksum must stop
where the next track begins, or a known disc reads as unknown.
"""

import hashlib

from decoders.psx.disc.cd_audio import CD_SECTOR
from decoders.psx.disc.checksum import sha256_file
from decoders.psx.disc.cue_parser import parse_cue
from decoders.psx.disc.extractor import data_track_range

DATA = (bytes(range(256)) * 46)[:5 * CD_SECTOR]          # 5 made-up sectors
AUDIO = b"\x7F" * (3 * CD_SECTOR)


def test_sha256_of_a_range(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(DATA + AUDIO)
    assert sha256_file(path) == hashlib.sha256(DATA + AUDIO).hexdigest()
    assert sha256_file(path, 0, len(DATA)) == hashlib.sha256(DATA).hexdigest()
    assert sha256_file(path, len(DATA)) == hashlib.sha256(AUDIO).hexdigest()


def test_single_bin_data_track_ends_where_the_next_track_begins(tmp_path):
    (tmp_path / "one.bin").write_bytes(DATA + AUDIO)
    cue = tmp_path / "one.cue"
    cue.write_text('FILE "one.bin" BINARY\n'
                   '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
                   '  TRACK 02 AUDIO\n    PREGAP 00:02:00\n    INDEX 01 00:00:05\n'
                   '  TRACK 03 AUDIO\n    INDEX 00 00:00:06\n    INDEX 01 00:00:07\n')
    sheet = parse_cue(cue)
    start, end = data_track_range(sheet)
    assert (start, end) == (0, len(DATA))
    assert sha256_file(sheet.data_track.file_path, start, end) == \
        hashlib.sha256(DATA).hexdigest()


def test_split_bin_data_track_is_its_whole_file(tmp_path):
    (tmp_path / "t1.bin").write_bytes(DATA)
    (tmp_path / "t2.bin").write_bytes(AUDIO)
    cue = tmp_path / "split.cue"
    cue.write_text('FILE "t1.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
                   'FILE "t2.bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 00 00:00:00\n'
                   '    INDEX 01 00:00:01\n')
    assert data_track_range(parse_cue(cue)) == (0, None)
