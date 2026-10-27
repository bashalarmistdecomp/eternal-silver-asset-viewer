"""The ISO 9660 reader on a made-up image: a plain 2048-byte-sector image
with a volume descriptor and one root directory
(decoders.testing.iso_image).

What this CAN catch: a file name from the image that is written anywhere
but in the folder the disc is extracted to (a "../" climbing out, a "/"
or a drive making the path absolute, a backslash on Windows), a refusal
that comes after some files were already written, and an ordinary disc's
files no longer coming out byte for byte; an image cut short, or a size,
place or record damaged, read as zeros or a guess (or built up to its
size) instead of refused, and the files a refusal names; progress counted
in anything but files.

What it CANNOT catch: anything of a real disc's layout (Mode 2 sectors,
XA, a directory over several sectors), which the on-disc tests and the
extractor's own use cover.
"""

import struct

import pytest

from decoders.config import SECTOR_SIZE
from decoders.psx.disc.iso_reader import MAX_DIRECTORY, ISO9660Reader, file_path
from decoders.testing import ISO_ROOT_LBA
from decoders.testing import iso_image as _image


def test_an_ordinary_disc_s_files_come_out_whole(tmp_path):
    files = {b"SYSTEM.CNF;1": b"made-up text", b"DATA.BIN;1": bytes(range(256)) * 9}
    out = tmp_path / "disc"
    got = ISO9660Reader(_image(files)).extract_all(out)
    assert got == ["SYSTEM.CNF", "DATA.BIN"]
    assert (out / "SYSTEM.CNF").read_bytes() == b"made-up text"
    assert (out / "DATA.BIN").read_bytes() == bytes(range(256)) * 9


@pytest.mark.parametrize("name", [b"../ESCAPE.TXT;1", b"..", b"SUB/../../ESCAPE.TXT"])
def test_a_name_that_climbs_out_is_refused_and_nothing_is_written(tmp_path, name):
    out = tmp_path / "library" / "staging"
    image = _image({b"FIRST.BIN;1": b"first", name: b"made-up payload"})
    with pytest.raises(ValueError):
        ISO9660Reader(image).extract_all(out)
    assert not out.exists()
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


@pytest.mark.parametrize("name", ["/ESCAPE.TXT", "\\ESCAPE.TXT", "SUB\\ESCAPE.TXT",
                                  "C:ESCAPE.TXT", "A/B", "", ".", "TAB\tNAME"])
def test_a_name_that_is_not_a_file_name_is_refused(tmp_path, name):
    with pytest.raises(ValueError):
        file_path(tmp_path, name)


def test_an_absolute_name_never_reaches_the_file_system(tmp_path):
    out = tmp_path / "staging"
    image = _image({b"/" + str(tmp_path / "ESCAPE.TXT").lstrip("/").encode(): b"x"})
    with pytest.raises(ValueError):
        ISO9660Reader(image).extract_all(out)
    assert not (tmp_path / "ESCAPE.TXT").exists() and not out.exists()


def test_a_name_resolving_through_a_link_out_of_the_folder_is_refused(tmp_path):
    out = tmp_path / "staging"
    out.mkdir()
    (out / "LINK.BIN").symlink_to(tmp_path / "elsewhere.bin")
    with pytest.raises(ValueError):
        file_path(out, "LINK.BIN")


def test_a_plain_name_is_written_in_the_folder(tmp_path):
    assert file_path(tmp_path, "SLUS_000.00") == tmp_path / "SLUS_000.00"


def _record(image: bytearray, name: bytes) -> int:
    """Where the root directory's record of `name` begins."""
    pos = ISO_ROOT_LBA * SECTOR_SIZE
    while image[pos]:
        if image[pos + 33:pos + 33 + image[pos + 32]] == name:
            return pos
        pos += image[pos]
    raise KeyError(name)


def _sized(image: bytearray, name: bytes, size: int) -> None:
    at = _record(image, name)
    struct.pack_into("<I", image, at + 10, size)
    struct.pack_into(">I", image, at + 14, size)


FILES = {b"SYSTEM.CNF;1": b"made-up text", b"BIG.DAT;1": b"\xAA" * 5000,
         b"LAST.DAT;1": b"\xBB" * 3000}


def test_an_image_cut_short_is_refused_naming_what_is_missing(tmp_path):
    image = bytearray(_image(FILES))
    last = struct.unpack_from("<I", image, _record(image, b"LAST.DAT;1") + 2)[0]
    out = tmp_path / "disc"
    with pytest.raises(ValueError, match=r"cut short or damaged: LAST.DAT runs past its end"):
        ISO9660Reader(bytes(image[:last * SECTOR_SIZE + 100])).extract_all(out)
    assert not out.exists()


def test_a_damaged_size_is_refused_before_it_is_read(tmp_path):
    image = bytearray(_image(FILES))
    _sized(image, b"BIG.DAT;1", 0xFFFF_FFFF)          # 4 GiB: never built
    _sized(image, b"LAST.DAT;1", 64 << 20)
    with pytest.raises(ValueError, match="BIG.DAT and LAST.DAT run past its end"):
        ISO9660Reader(bytes(image)).extract_all(tmp_path / "disc")
    reader = ISO9660Reader(bytes(image))
    big = next(e for e in reader.read_directory(ISO_ROOT_LBA, SECTOR_SIZE) if e.name == "BIG.DAT")
    with pytest.raises(ValueError, match="BIG.DAT runs past the end"):
        reader.extract_file(big)


def test_an_empty_file_may_start_anywhere(tmp_path):
    image = bytearray(_image({b"EMPTY.DAT;1": b"", b"SYSTEM.CNF;1": b"made-up text"}))
    struct.pack_into("<I", image, _record(image, b"EMPTY.DAT;1") + 2, 0x00FF_FFFF)
    out = tmp_path / "disc"
    assert ISO9660Reader(bytes(image)).extract_all(out) == ["EMPTY.DAT", "SYSTEM.CNF"]
    assert (out / "EMPTY.DAT").read_bytes() == b""


def test_a_directory_past_the_end_or_too_large_is_refused():
    reader = ISO9660Reader(_image(FILES))
    with pytest.raises(ValueError, match="past the end"):
        reader.read_directory(10_000, SECTOR_SIZE)
    with pytest.raises(ValueError, match="a damaged image"):
        reader.read_directory(ISO_ROOT_LBA, MAX_DIRECTORY + 1)


@pytest.mark.parametrize("length", [1, 20, 32])
def test_a_record_shorter_than_its_fields_is_refused(length):
    image = bytearray(_image(FILES))
    image[ISO_ROOT_LBA * SECTOR_SIZE] = length
    with pytest.raises(ValueError, match="damaged record"):
        ISO9660Reader(bytes(image)).read_directory(ISO_ROOT_LBA, SECTOR_SIZE)


def test_a_name_longer_than_its_record_is_refused():
    image = bytearray(_image(FILES))
    at = _record(image, b"BIG.DAT;1")
    image[at + 32] = 200
    with pytest.raises(ValueError, match="damaged record"):
        ISO9660Reader(bytes(image)).read_directory(ISO_ROOT_LBA, SECTOR_SIZE)


def test_a_file_that_cannot_be_written_fails_the_rest_written(tmp_path):
    out = tmp_path / "disc"
    (out / "BIG.DAT").mkdir(parents=True)                 # a folder where a file goes
    with pytest.raises(OSError, match="BIG.DAT .* could not be written"):
        ISO9660Reader(_image(FILES)).extract_all(out)
    assert (out / "LAST.DAT").read_bytes() == b"\xBB" * 3000


def test_progress_counts_the_files(tmp_path):
    seen = []
    ISO9660Reader(_image(FILES)).extract_all(tmp_path / "disc", lambda *a: seen.append(a))
    assert seen == [("SYSTEM.CNF", 0, 3), ("BIG.DAT", 1, 3), ("LAST.DAT", 2, 3)]


def _in_audio(space_after: int) -> tuple[bytes, int]:
    """FILES with LAST.DAT moved 150 sectors past the data's end, as a
    split-BIN rip's file in its CD audio tracks lies, and the volume's
    sector count set `space_after` sectors past LAST.DAT's start."""
    image = bytearray(_image(FILES))
    at = len(image) // SECTOR_SIZE + 150
    rec = _record(image, b"LAST.DAT;1")
    struct.pack_into("<I", image, rec + 2, at)
    struct.pack_into(">I", image, rec + 6, at)
    struct.pack_into("<I", image, 16 * SECTOR_SIZE + 80, at + space_after)
    return bytes(image), at


def test_a_file_in_the_other_tracks_is_written_as_zeros_of_its_size(tmp_path):
    image, _at = _in_audio(space_after=2)
    out = tmp_path / "disc"
    assert "LAST.DAT" in ISO9660Reader(image, other_tracks=True).extract_all(out)
    assert (out / "LAST.DAT").read_bytes() == bytes(3000)
    assert (out / "BIG.DAT").read_bytes() == b"\xAA" * 5000
    # without other tracks, the same file is an image cut short
    with pytest.raises(ValueError, match="LAST.DAT runs past its end"):
        ISO9660Reader(image).extract_all(tmp_path / "alone")


def test_a_file_past_the_volume_is_refused_though_there_are_other_tracks(tmp_path):
    image, _at = _in_audio(space_after=1)              # LAST.DAT needs 2 sectors
    with pytest.raises(ValueError, match="LAST.DAT runs past its end"):
        ISO9660Reader(image, other_tracks=True).extract_all(tmp_path / "disc")


def test_a_file_running_on_into_the_other_tracks_keeps_what_the_data_holds(tmp_path):
    # LAST.DAT's first sector in the data, its second past its end
    image = bytearray(_image(FILES))
    last = struct.unpack_from("<I", image, _record(image, b"LAST.DAT;1") + 2)[0]
    struct.pack_into("<I", image, 16 * SECTOR_SIZE + 80, last + 2)
    cut = bytes(image[:(last + 1) * SECTOR_SIZE])
    out = tmp_path / "disc"
    ISO9660Reader(cut, other_tracks=True).extract_all(out)
    assert (out / "LAST.DAT").read_bytes() == b"\xBB" * 2048 + bytes(3000 - 2048)
    with pytest.raises(ValueError, match="LAST.DAT runs past its end"):
        ISO9660Reader(cut).extract_all(tmp_path / "alone")


def test_a_volume_larger_than_a_cd_is_not_believed(tmp_path):
    image = bytearray(_in_audio(space_after=2)[0])
    struct.pack_into("<I", image, 16 * SECTOR_SIZE + 80, 0xFFFF_FFFF)
    rec = _record(image, b"LAST.DAT;1")
    struct.pack_into("<I", image, rec + 10, 0xFFFF_0000)    # 4 GiB of zeros: never
    with pytest.raises(ValueError, match="LAST.DAT runs past its end"):
        ISO9660Reader(bytes(image), other_tracks=True).extract_all(tmp_path / "disc")
