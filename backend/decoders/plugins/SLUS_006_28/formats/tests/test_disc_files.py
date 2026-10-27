"""Tier 1 for the disc's files and the build stamp — built bytes, no game
data; and, when the library holds the disc, overlay_stamp_check
(0x800232B0)'s two texts on it.

What this CAN catch: a file the spec names left without its role, a movie
name read as the wrong play event, a stamp read past its 0 (strcmp stops
there), and the two addresses the stamp check reads.

What it CANNOT catch: a role misread from the code that reads the file;
only re-reading that code does that. See decoders/testing.py.
"""

import pytest

from decoders import config
from decoders.plugins.SLUS_006_28.formats import disc_files as df


def test_every_file_the_spec_names_has_a_role():
    for name in ("SLUS_006.28", "SLUS_008.99", "SYSTEM.CNF", "MENU.BIN", "LUNADATA.FIL",
                 "LUNAR_DA.PCM", "BLANK_DA.PCM", "_AUDIO.XA", "_SECOND.XA", "_B054.STR"):
        assert df.role(name) is not None, name
    assert df.role("README.TXT") is None


def test_movies_by_play_event():
    assert df.role("_B004.STR") is df.MOVIE_ROLE
    assert (df.movie_number("_B004.STR"), df.movie_number("_B054.STR")) == (4, 54)
    assert df.movie_number("MENU.BIN") is None


class _Image:
    """read_bytes over a dict of address -> bytes, as exe_loader's image."""
    def __init__(self, at: dict[int, bytes]):
        self.at = at

    def read_bytes(self, addr, count):
        return self.at[addr][:count].ljust(count, b"\0")


def test_the_stamps_are_read_to_their_0(monkeypatch):
    from decoders.plugins.SLUS_006_28.records import programs
    monkeypatch.setattr(programs, "STAMPS", {programs.stamp_digest(b"$stamp one$"): programs.US})
    image = _Image({0x80011000: b"$stamp one$\0junk", 0x80011734: b"OVL.BIN\0x"})
    assert df.overlay_file_name(image) == "OVL.BIN"
    same = df.stamp_check(image, b"$stamp one$\0other bytes")
    assert same.match and same.overlay == b"$stamp one$"
    assert not df.stamp_check(image, b"$stamp two$\0").match


_DISC = config.raw_dir("SLUS_006.28")


@pytest.mark.disc
@pytest.mark.skipif(not (_DISC / "SLUS_006.28").exists(),
                    reason="SLUS_006.28 is not extracted in the library")
def test_on_the_disc_menu_bin_carries_the_programs_stamp():
    from decoders.psx.analysis.exe_loader import load_exe
    image = load_exe(_DISC / "SLUS_006.28")
    name = df.overlay_file_name(image)
    assert name == "MENU.BIN"
    check = df.stamp_check(image, (_DISC / name).read_bytes()[:df.STAMP_MAX])
    assert check.program and check.match
