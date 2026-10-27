"""A disc image extracted into a made-up library (DiscExtractor), from
made-up images (decoders.testing.iso_image) whose serials are gamedb's
own, no game data.

What this CAN catch: a damaged image added, or its staging folder left;
two extractions sharing one staging folder, or a stopped one's never
removed; a dump extracted again deleted before its replacement is in
place, or lost when the replacement cannot go in; a disc gamedb knows by
its serial alone reported as known by its checksum; a refusal in a
developer's words; progress counted in anything but files.

What it CANNOT catch: a real disc's layout (the discs the library holds).
"""

import hashlib
import os
import time

import pytest

from decoders import config
from decoders.psx.disc import extractor
from decoders.psx.disc.extractor import DiscExtractor
from decoders.psx.gamedb import database
from decoders.psx.gamedb.known_games import DISC_ID_LOOKUP, KNOWN_CHECKSUMS, program_of
from decoders.testing import iso_image

ONE = sorted(DISC_ID_LOOKUP)[0]
UNKNOWN = "SLUS_999.99"


@pytest.fixture
def lib(monkeypatch, tmp_path):
    root = tmp_path / "library"
    monkeypatch.setattr(config, "LIBRARY", root)
    monkeypatch.setattr(config, "EXTRACTING_DIR", root / ".extracting")
    monkeypatch.setattr(database, "DISCS_DIR", root / "discs")
    assert UNKNOWN not in DISC_ID_LOOKUP
    return root


def _image(tmp_path, serial=ONE, name="disc.iso", extra=b"made-up data") -> os.PathLike:
    path = tmp_path / name
    path.write_bytes(iso_image({b"SYSTEM.CNF;1": f"BOOT = cdrom:\\{serial};1\r\n".encode(),
                                b"DATA.BIN;1": extra}, b"MADE_UP"))
    return path


def _left(lib) -> list[str]:
    """What extractions left in the library besides dumps."""
    return sorted(p.name for p in lib.glob(".extracting*"))


def test_a_disc_known_by_its_serial_is_placed_and_says_so(lib, tmp_path):
    seen = []
    result = DiscExtractor(lambda *a: seen.append(a)).extract(_image(tmp_path))
    dump = config.raw_dir(program_of(ONE), ONE)
    assert result.output_dir == dump and result.files_extracted == ["SYSTEM.CNF", "DATA.BIN"]
    assert (dump / "DATA.BIN").read_bytes() == b"made-up data" and (dump / "meta.json").exists()
    assert (result.identified_by, result.recognized) == ("serial", False)
    assert [a for a in seen if a[0].startswith("Extracting")] == [
        ("Extracting SYSTEM.CNF...", 0, 2), ("Extracting DATA.BIN...", 1, 2)]
    assert _left(lib) == []


def test_a_disc_known_by_its_checksum_is_recognized(lib, tmp_path, monkeypatch):
    image = _image(tmp_path)
    monkeypatch.setitem(KNOWN_CHECKSUMS, hashlib.sha256(image.read_bytes()).hexdigest(),
                        DISC_ID_LOOKUP[ONE])
    result = DiscExtractor().extract(image)
    assert (result.identified_by, result.recognized) == ("checksum", True)


def test_a_damaged_image_adds_nothing_and_leaves_nothing(lib, tmp_path):
    image = _image(tmp_path, extra=b"\xAA" * 5000)
    image.write_bytes(image.read_bytes()[:-3000])              # cut short
    with pytest.raises(ValueError, match="DATA.BIN runs past its end"):
        DiscExtractor().extract(image)
    assert not config.raw_dir(program_of(ONE), ONE).exists() and _left(lib) == []


def test_a_disc_gamedb_does_not_know_is_refused_in_plain_words(lib, tmp_path):
    with pytest.raises(ValueError) as refused:
        DiscExtractor().extract(_image(tmp_path, UNKNOWN))
    assert str(refused.value) == f"a disc the viewer does not know ({UNKNOWN}), so it was not added"
    assert _left(lib) == []


def test_each_extraction_stages_apart_and_a_stopped_one_s_folder_goes(lib):
    lib.mkdir()
    stopped, legacy = lib / ".extracting-0123", lib / ".extracting"
    for folder in (stopped, legacy):
        folder.mkdir()
        (folder / "FILE.BIN").write_bytes(b"x")
        old = time.time() - extractor.STAGING_STALE - 60
        for p in (folder / "FILE.BIN", folder):
            os.utime(p, (old, old))
    running = lib / ".extracting-4567"
    running.mkdir()
    first, second = extractor._staging(), extractor._staging()
    assert first != second and first.is_dir() and second.is_dir()
    assert not stopped.exists() and not legacy.exists() and running.is_dir()


def test_a_dump_extracted_again_is_replaced_whole(lib, tmp_path):
    image = _image(tmp_path)
    dump = DiscExtractor().extract(image).output_dir
    (dump / "LEFT.OVER").write_bytes(b"from before")
    assert DiscExtractor().extract(image).output_dir == dump
    assert sorted(p.name for p in dump.iterdir()) == ["DATA.BIN", "SYSTEM.CNF", "meta.json"]
    assert _left(lib) == []


def test_a_dump_held_open_stays_whole_and_the_refusal_says_why(lib, tmp_path, monkeypatch):
    image = _image(tmp_path)
    dump = DiscExtractor().extract(image).output_dir
    rename = extractor._rename

    def held(src, dst, tries=8):
        if src == dump:
            raise PermissionError(13, "made-up: held open")
        rename(src, dst, tries)

    monkeypatch.setattr(extractor, "_rename", held)
    with pytest.raises(PermissionError, match="could not be replaced .* try again"):
        DiscExtractor().extract(image)
    assert (dump / "DATA.BIN").read_bytes() == b"made-up data" and _left(lib) == []


def test_when_the_new_dump_cannot_go_in_the_old_one_comes_back(lib, tmp_path, monkeypatch):
    image = _image(tmp_path)
    dump = DiscExtractor().extract(image).output_dir
    (dump / "LEFT.OVER").write_bytes(b"from before")
    rename = extractor._rename

    def refused(src, dst, tries=8):
        if dst == dump and src.name.startswith(".extracting-") and not src.name.endswith("-replaced"):
            raise OSError(28, "made-up: no space left")
        rename(src, dst, tries)

    monkeypatch.setattr(extractor, "_rename", refused)
    with pytest.raises(OSError, match="no space left"):
        DiscExtractor().extract(image)
    assert (dump / "LEFT.OVER").read_bytes() == b"from before" and _left(lib) == []


def test_a_rename_is_tried_again_while_a_file_is_held(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    src, dst, calls = tmp_path / "a", tmp_path / "b", []
    src.mkdir()
    real = type(src).rename

    def flaky(self, target):
        calls.append(self)
        if len(calls) < 3:
            raise PermissionError(13, "held")
        return real(self, target)

    monkeypatch.setattr(type(src), "rename", flaky)
    extractor._rename(src, dst)
    assert dst.is_dir() and len(calls) == 3


def test_a_file_in_a_cue_sheet_s_audio_tracks_comes_out_as_zeros(lib, tmp_path):
    """A split-BIN rip: the data track's directory names a file lying in the
    CD audio track after it, in a file of its own (Lunar's .PCM files)."""
    import struct
    from decoders.config import RAW_SECTOR_SIZE, SECTOR_SIZE
    from decoders.testing import ISO_ROOT_LBA, raw_sectors
    image = bytearray(iso_image({b"SYSTEM.CNF;1": f"BOOT = cdrom:\\{ONE};1\r\n".encode(),
                                 b"AUDIO.PCM;1": b"\x11" * 3000}, b"MADE_UP"))
    at = len(image) // SECTOR_SIZE + 150
    pos = ISO_ROOT_LBA * SECTOR_SIZE            # the root directory's records
    while image[pos + 33:pos + 33 + image[pos + 32]] != b"AUDIO.PCM;1":
        pos += image[pos]
    struct.pack_into("<I", image, pos + 2, at)
    struct.pack_into(">I", image, pos + 6, at)
    struct.pack_into("<I", image, 16 * SECTOR_SIZE + 80, at + 2)
    (tmp_path / "Disc (Track 1).bin").write_bytes(raw_sectors(bytes(image)))
    (tmp_path / "Disc (Track 2).bin").write_bytes(bytes(RAW_SECTOR_SIZE * 4))
    cue = tmp_path / "Disc.cue"
    cue.write_text('FILE "Disc (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
                   'FILE "Disc (Track 2).bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 00 00:00:00\n'
                   '    INDEX 01 00:02:00\n')
    result = DiscExtractor().extract(cue)
    assert result.files_extracted == ["SYSTEM.CNF", "AUDIO.PCM"]
    assert (result.output_dir / "AUDIO.PCM").read_bytes() == bytes(3000)
