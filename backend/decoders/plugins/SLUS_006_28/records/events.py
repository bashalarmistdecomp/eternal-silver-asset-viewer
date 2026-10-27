"""Play events — the movies and bromides `MoviePlay(n) (0x800232D4)` shows, and the
theater that replays them (docs/spec/video.md §"Which movie is which").

MoviePlay(n) — the story script (ScriptCommandMoviePlay, 0x8005E2B4), the
opening (StartMoviePlay (0x800435FC), n = 0) and the item menus all call it:

    flag n + 0x154 set (StoryBitSet, 0x800576EC) — what unlocks theater entry n + 1
    0x37 <= n < 0x44    bromide k = n - 0x37: PictureShow(k) (0x80024A7C) loads
                        LUNADATA resource 0x24A + k, and PictureXaPlay(k)
                        (0x800247AC) plays voice g_PictureVoices[k] (0x800AF844)
    otherwise           a movie: BIN(n) checks the disc ("_B%03d.STR" % n;
                        disc 1 below 0x24, disc 2 from it), MENU.BIN's
                        movie_play(n) (0x80196B54) plays "_B%03d.STR" % n up to the
                        frame in its u16 table at 0x8019769C (0 = none)

The theater (an item, MenuUseMovieRun (0x8007757C)) lists entries i in
1..0x37 whose flag i + 0x153 is set; picking one runs MenuUseMoviePick (0x800775D4) ->
MenuUseMoviePlay(i - 1) (0x800778C8) -> MoviePlay(i - 1). A bromide item
(MenuUsePictureRun, 0x8007690C) passes (item +0x07 >> 4) + 0x37.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .programs import EXE_BASE, address

EVENT_FLAG_BASE = 0x154             # MoviePlay (0x800232D4): flag n + 0x154
BROMIDE_FIRST, BROMIDE_COUNT = 0x37, 0x0D   # n - 0x37 < 0xD
BROMIDE_RESOURCE_BASE = 0x24A       # PictureShow(k) (0x80024A7C): resource 0x24A + k
DISC2_FIRST = 0x24                  # BIN: disc 1 below, disc 2 from here
DISC_PROMPT_RESOURCE = 0x257        # resource_load_run(0x257) (0x800202CC): the disc-change and end screens (formats.resource_pictures)
MOVIE_PATTERN = "_B{:03d}.STR"      # STR / movie_play (0x80196B54): "_B%03d.STR"
THEATER_FIRST, THEATER_LAST = 1, 0x37       # MenuUseMovieListSet (0x800776CC): i in 1..0x37
THEATER_FLAG_BASE = 0x153           # ... listed when flag i + 0x153 is set
MENU_BIN_BASE = 0x80196000          # overlay_load (0x80023240)'s load address
END_FRAME_ADDR = 0x8019769C         # movie_play (0x80196B54)'s u16 table, by n
MOVIE_COUNT = 0x37                  # n = 0..0x36
PICTURE_VOICES_ADDR = 0x800AF844    # g_PictureVoices: u8[0xD], bromide k -> its voice

_MOVIE_RE = re.compile(r"^_B(\d{3})\.STR$", re.IGNORECASE)


@dataclass(frozen=True)
class Event:
    number: int
    kind: str                       # "movie" | "bromide"
    movie: str | None = None        # the .STR file
    disc: int | None = None         # the disc BIN asks for
    bromide: int | None = None      # k
    resource: int | None = None     # the bromide's LUNADATA resource


def event(n: int) -> Event:
    """What MoviePlay(n) (0x800232D4) shows."""
    if BROMIDE_FIRST <= n < BROMIDE_FIRST + BROMIDE_COUNT:
        k = n - BROMIDE_FIRST
        return Event(n, "bromide", bromide=k, resource=BROMIDE_RESOURCE_BASE + k)
    return Event(n, "movie", movie=MOVIE_PATTERN.format(n),
                 disc=1 if n < DISC2_FIRST else 2)


def theater_event(entry: int) -> int:
    """MenuUseMoviePick (0x800775D4): theater entry i plays event i - 1."""
    return entry - 1


def movie_number(filename: str) -> int | None:
    """The event number a movie file plays as ("_B004.STR" -> 4)."""
    m = _MOVIE_RE.match(filename)
    return int(m.group(1)) if m else None


def bromide_for_resource(resource: int) -> int | None:
    """k when `resource` is bromide k's (PictureShow, 0x80024A7C), else None."""
    k = resource - BROMIDE_RESOURCE_BASE
    return k if 0 <= k < BROMIDE_COUNT else None


def picture_voices(image: bytes) -> list[int]:
    """g_PictureVoices (0x800AF844): the voice PictureXaPlay (0x800247AC)
    plays with bromide k, by k. `image` is the program's image from
    0x80011000; SLPS_013.97 keeps the table elsewhere (records.programs)."""
    at = address(image, "g_PictureVoices", PICTURE_VOICES_ADDR) - EXE_BASE
    return list(image[at:at + BROMIDE_COUNT])


def resource_role(resource: int) -> str | None:
    """What a LUNADATA resource is to the play-event code: "bromide k",
    "disc-change and end screens", or None when this code does not load it."""
    k = bromide_for_resource(resource)
    if k is not None:
        return f"bromide {k}"
    if resource == DISC_PROMPT_RESOURCE:
        return "disc-change and end screens"
    return None


def end_frames(menu_bin: bytes) -> list[int]:
    """movie_play (0x80196B54)'s table from MENU.BIN: the last frame played for each
    movie n (0 = the game has no movie n). MENU.BIN carries its program's
    stamp, so the Japanese overlay's table is read where its movie_play
    (SLPS_013.97 MENU.BIN 0x80196BFC) reads it."""
    off = address(menu_bin, "D_8019769C", END_FRAME_ADDR) - MENU_BIN_BASE
    return [struct.unpack_from("<H", menu_bin, off + 2 * n)[0] for n in range(MOVIE_COUNT)]
