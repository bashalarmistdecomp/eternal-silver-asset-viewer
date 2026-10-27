"""A disc image's identity read from a few of its sectors
(extractor.disc_identity), on made-up images (decoders.testing.iso_image):
the serial its SYSTEM.CNF boots, and its volume id.

What this CAN catch: a plain image, a raw track behind its cue sheet or a
bare raw .bin read wrong; an image with no SYSTEM.CNF, a cue sheet whose
track is gone or a file that is no image at all not said to be one.

What it CANNOT catch: a real disc's layout (the discs the library holds,
which the extraction reads the same way).
"""

import pytest

from decoders.psx.disc.extractor import boot_serial, disc_identity
from decoders.testing import iso_image, raw_sectors

#: a made-up serial, and the SYSTEM.CNF that boots it
SERIAL = "SLUS_999.99"
CNF = b"BOOT = cdrom:\\SLUS_999.99;1\r\nTCB = 4\r\n"


def _cue(tmp_path, image: bytes):
    (tmp_path / "Made up.bin").write_bytes(raw_sectors(image))
    cue = tmp_path / "Made up.cue"
    cue.write_text('FILE "Made up.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    return cue


def test_a_plain_image_says_its_serial_and_volume(tmp_path):
    path = tmp_path / "disc.iso"
    path.write_bytes(iso_image({b"SYSTEM.CNF;1": CNF}, b"MADE_UP"))
    assert disc_identity(path) == (SERIAL, "MADE_UP")


def test_a_raw_track_is_read_through_its_cue_sheet_or_alone(tmp_path):
    cue = _cue(tmp_path, iso_image({b"DATA.BIN;1": bytes(5000), b"SYSTEM.CNF;1": CNF}, b"MADE_UP"))
    assert disc_identity(cue) == (SERIAL, "MADE_UP")
    assert disc_identity(tmp_path / "Made up.bin") == (SERIAL, "MADE_UP")


def test_a_disc_without_system_cnf_has_no_serial(tmp_path):
    path = tmp_path / "disc.iso"
    path.write_bytes(iso_image({b"README.TXT;1": b"made-up text"}, b"MADE_UP"))
    assert disc_identity(path) == (None, "MADE_UP")


def test_a_file_that_is_no_image_is_refused(tmp_path):
    path = tmp_path / "firmware.bin"
    path.write_bytes(bytes(600_000))
    with pytest.raises(ValueError, match="no ISO 9660 volume"):
        disc_identity(path)


def test_a_cue_sheet_whose_track_is_gone_says_so(tmp_path):
    cue = _cue(tmp_path, iso_image({b"SYSTEM.CNF;1": CNF}))
    (tmp_path / "Made up.bin").unlink()
    with pytest.raises(FileNotFoundError, match="Made up.bin"):
        disc_identity(cue)


@pytest.mark.parametrize("text, serial", [
    ("BOOT = cdrom:\\SLUS_999.99;1", SERIAL),
    ("boot=cdrom:SLUS_999.99;1\nTCB=4", SERIAL),
    ("TCB = 4\nEVENT = 10", None),
])
def test_the_boot_line_names_the_serial(text, serial):
    assert boot_serial(text) == serial
