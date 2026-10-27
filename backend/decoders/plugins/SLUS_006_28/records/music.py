"""BGM numbers — what the game plays for music number `n`, from the EXE's
own tables and the code that reads them (docs/spec/sound.md §"BGM numbers").

`MusicPlay(n, _, fade) (0x80054F2C)` is the one "play BGM n" entry —
field scripts (`ScriptCommandMusicPlay (0x8005E494)`), battle code and the jukebox
(`MenuUseMusicPick (0x800772E0)`) all call it:

    n == 0           stop sequence player 0 (sound_music_stop, 0x80023D34)
    n >= 0x45        nothing
    n == 0x3C        CD audio: cd_track_switch(2) (0x8001B71C) -> cd_track_play(2) (0x8001B684), seek
                     to TOC entry 2 (g_CdTocEntries[2] (0x800E0748)) and CdlPlay — track 2
    else             MusicLoadStart (0x80055118): m = g_MusicBankNumbers[n - 1] (0x800127B8), then
                     sound_music_load(m) (0x80023E9C): m clamped to 0x41 from 0x44 up,
                     resource = sound_music_index_get(m) (0x80023E20) + 0xE9 — m - 1 less the
                     entries of g_SoundMusicIndexSkips (0x800AF7A0) below m — loaded into bank slot
                     2 (sound_bank_load (0x80024138) -> resource_load_run (0x800202CC)) and its sequence 0
                     played (sound_music_play (0x80023D0C) -> sound_seq_play(2, 0, 0) (0x80023B24))

The jukebox lists numbers 1..0x44 (MenuUseMusicListSet (0x80077380), unlocked by flags
0x19A + n) and captions number n with string 0x546 + n (MenuUseMusicListDisp, 0x800774EC) —
so that string is BGM n's title.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .programs import address

EXE_BASE = 0x80011000
MAP_ADDR = 0x800127B8           # g_MusicBankNumbers (0x800127B8): u8[0x44], BGM n -> m
SKIP_ADDR = 0x800AF7A0          # g_SoundMusicIndexSkips (0x800AF7A0): s8[6], m values with no bank of their own
SKIP_COUNT = 6
BANK_BASE = 0xE9                # sound_music_load (0x80023E9C): + 0xE9
CLAMP_FROM, CLAMP_TO = 0x44, 0x41
CD_NUMBER = 0x3C                # MusicPlay (0x80054F2C)'s CD-audio branch
CD_TRACK = 2                    # cd_track_play(2) (0x8001B684): TOC entry 2
NUMBER_LIMIT = 0x45             # MusicPlay (0x80054F2C): n >= 0x45 plays nothing
JUKEBOX_FIRST, JUKEBOX_LAST = 1, 0x44   # MenuUseMusicListSet (0x80077380)
TITLE_BASE = 0x546              # MenuUseMusicListDisp (0x800774EC): caption = string n + 0x546


@dataclass(frozen=True)
class Bgm:
    number: int
    kind: str                   # "sequence" | "cd" | "none"
    resource: int | None = None  # the bank (general resource index), sequence 0
    track: int | None = None    # the CD audio track


def _u8(image: bytes, addr: int) -> int:
    return image[addr - EXE_BASE]


def bank_resource(image: bytes, m: int) -> int | None:
    """sound_music_load (0x80023E9C) (with sound_music_index_get (0x80023E20)): the bank resource for music m."""
    if m <= 0:
        return None
    if m >= CLAMP_FROM:
        m = CLAMP_TO
    at = address(image, "g_SoundMusicIndexSkips", SKIP_ADDR) - EXE_BASE
    skips = [struct.unpack_from("b", image, at + i)[0]
             for i in range(SKIP_COUNT)]
    below = 0
    for s in skips:                     # the loop stops at the first entry >= m
        if s >= m:
            break
        below += 1
    return m - below - 1 + BANK_BASE


def bgm(image: bytes, n: int) -> Bgm:
    """MusicPlay(n) (0x80054F2C): what BGM number n plays."""
    n &= 0xFF
    if n == 0 or n >= NUMBER_LIMIT:
        return Bgm(n, "none")
    if n == CD_NUMBER:
        return Bgm(n, "cd", track=CD_TRACK)
    res = bank_resource(image, _u8(image, address(image, "g_MusicBankNumbers", MAP_ADDR) + n - 1))
    return Bgm(n, "sequence" if res is not None else "none", resource=res)


def jukebox(image: bytes) -> list[Bgm]:
    """Every number the jukebox can list (MenuUseMusicListSet (0x80077380): 1..0x44)."""
    return [bgm(image, n) for n in range(JUKEBOX_FIRST, JUKEBOX_LAST + 1)]
