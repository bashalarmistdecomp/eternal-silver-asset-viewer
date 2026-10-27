"""What each file on a game disc is, and the build stamp the program checks.

The files, as docs/spec/overview.md §"Disc 1's files" and §"Disc 2" give
them: the boot file, its configuration, the movie player's overlay, the
data archive, two .PCM files no code names, the XA audio and the movies.
This module holds that text and the names it is keyed by; the files and
their bytes are the user's disc's.

The program checks one file against itself. Before a movie, overlay_load
(0x80023240) reads the file named at g_OverlayFileName (0x80011734),
MENU.BIN, whole to 0x80196000, and overlay_stamp_check (0x800232B0)
compares the text it begins with to the program's own build stamp,
g_BuildStamp (0x80011000): build_stamp_compare (0x80013D08) is strcmp.
On a difference overlay_load calls assert_fail ("OVERLAY ERROR",
OVERLAY.C line 0xB2), which is empty in this build, so the overlay is used
anyway; overlay_disc_wait (0x80023184), which reads the file's first 0x800
bytes when a disc is changed, asks for the disc again
(docs/spec/code/subsystems/overlay.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from decoders.psx.analysis.symbols import resolve

from ..records.programs import address

OVERLAY_BASE = 0x80196000       # where overlay_load (0x80023240) reads MENU.BIN
STAMP_MAX = 0x100               # how far a stamp is looked for its 0


@dataclass(frozen=True)
class FileRole:
    """What a file is and the code that reads it ("" when no code names it)."""
    what: str
    reader: str = ""


_BOOT = FileRole("the boot file: a loader and the packed executable",
                 "the console's boot, by SYSTEM.CNF's BOOT line")
_PCM = FileRole("no name in the C refers to it (sound.md §\"The .PCM files are empty\")")

_ROLES: dict[str, FileRole] = {
    "SLUS_006.28": _BOOT,
    "SLUS_008.99": _BOOT,           # disc 2: the same file under disc 2's serial
    "SLPS_013.97": _BOOT,           # the Japanese program
    "SLPS_013.98": _BOOT,           # its disc 2: the same file under that serial
    "SYSTEM.CNF": FileRole("the boot configuration: the BOOT line names the program"),
    "MENU.BIN": FileRole(
        "the movie player's overlay: code and data with no header, loaded "
        "whole to 0x80196000 before a movie",
        "overlay_load (0x80023240); overlay_disc_wait (0x80023184) reads its "
        "first 0x800 bytes"),
    "LUNADATA.FIL": FileRole(
        "the game's data: resources 1 to 599, read by number",
        "resource_load (0x80020230), by g_ResourceSectorPairs (0x800AE904)"),
    "LUNAR_DA.PCM": _PCM,
    "BLANK_DA.PCM": _PCM,
    "_AUDIO.XA": FileRole(
        "CD-XA audio: the voices, 16 channels",
        "VoiceSet (0x80055470) / VoiceStart (0x800554C4), by g_XaVoices (0x800ADFF2)"),
    "_SECOND.XA": FileRole(
        "CD-XA audio: after the game's end its nine channels play",
        "GameRun (0x800559F4)"),
}

_MOVIE = re.compile(r"_B(\d{3})\.STR$", re.IGNORECASE)
MOVIE_ROLE = FileRole(
    "a movie, STR/MDEC: play event n is _Bnnn.STR",
    "MoviePlay (0x800232D4) -> overlay_disc_wait (0x80023184), then the "
    "overlay's movie_play (0x80196B54)")


def movie_number(name: str) -> int | None:
    """The play event a movie file is: "_B004.STR" -> 4 (MoviePlay's
    "_B%03d.STR")."""
    m = _MOVIE.match(name)
    return int(m.group(1)) if m else None


def role(name: str) -> FileRole | None:
    """What file `name` of a game disc is; None for a name the spec does not
    give."""
    if _MOVIE.match(name):
        return MOVIE_ROLE
    return _ROLES.get(name.upper())


def c_string(data: bytes) -> bytes:
    """The text up to its 0, as strcmp reads it."""
    return data.split(b"\0", 1)[0]


def program_stamp(binary) -> bytes:
    """g_BuildStamp (0x80011000) in the program's image."""
    at = address(binary, "g_BuildStamp", resolve("g_BuildStamp"))
    return c_string(binary.read_bytes(at, STAMP_MAX))


def overlay_file_name(binary) -> str:
    """The file overlay_load (0x80023240) reads: g_OverlayFileName (0x80011734)."""
    at = address(binary, "g_OverlayFileName", resolve("g_OverlayFileName"))
    return c_string(binary.read_bytes(at, 0x20)).decode("ascii", "replace")


@dataclass(frozen=True)
class StampCheck:
    """overlay_stamp_check (0x800232B0)'s two texts."""
    program: bytes          # g_BuildStamp
    overlay: bytes          # the text the overlay's file begins with

    @property
    def match(self) -> bool:
        """strcmp == 0: the overlay is taken."""
        return self.program == self.overlay


def stamp_check(binary, overlay_head: bytes) -> StampCheck:
    """The program's stamp beside the one `overlay_head` (the overlay file's
    first bytes) begins with."""
    return StampCheck(program_stamp(binary), c_string(overlay_head[:STAMP_MAX]))


def show(stamp: bytes) -> str:
    """A stamp as text."""
    return stamp.decode("ascii", "replace")
