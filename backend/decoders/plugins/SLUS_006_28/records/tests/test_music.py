"""Tier 1 for BGM numbers — a synthetic EXE image, no game data.

What this CAN catch: MusicPlay (0x80054F2C)'s branches (0 / >= 0x45 / the CD number
0x3C / the sequence path), the g_MusicBankNumbers (0x800127B8) indirection, sound_music_load (0x80023E9C)'s
clamp and sound_music_index_get (0x80023E20)'s skip count (stopping at the first entry >= m).

What it CANNOT catch: whether those addresses are this program's tables —
only re-reading MusicLoadStart (0x80055118) / sound_music_load does that. See
decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.records import music as mu


def _image(mapping: list[int], skips: list[int]) -> bytes:
    img = bytearray(mu.SKIP_ADDR - mu.EXE_BASE + 16)
    img[mu.MAP_ADDR - mu.EXE_BASE:mu.MAP_ADDR - mu.EXE_BASE + len(mapping)] = bytes(mapping)
    for i, s in enumerate(skips):
        struct.pack_into("b", img, mu.SKIP_ADDR - mu.EXE_BASE + i, s)
    return bytes(img)


IDENTITY = list(range(1, 0x45))


def test_resource_counts_the_skips_below_m():
    img = _image(IDENTITY, [25, 28, 47, 54, 57, 63])
    assert mu.bank_resource(img, 1) == 0xE9            # m - 1 + 0xE9
    assert mu.bank_resource(img, 25) == 0xE9 + 24      # 25 itself is not below 25
    assert mu.bank_resource(img, 26) == 0xE9 + 24      # one skip below: shares 25's bank
    assert mu.bank_resource(img, 0) is None


def test_clamp_from_0x44():
    img = _image(IDENTITY, [100] * 6)
    assert mu.bank_resource(img, 0x44) == mu.bank_resource(img, 0x41)


def test_bgm_branches():
    mapping = IDENTITY[:]
    mapping[4] = 8                                      # n = 5 -> m = 8
    img = _image(mapping, [100] * 6)
    assert mu.bgm(img, 0).kind == "none"
    assert mu.bgm(img, 0x45).kind == "none"
    cd = mu.bgm(img, 0x3C)
    assert (cd.kind, cd.track) == ("cd", 2)
    assert mu.bgm(img, 5).resource == mu.bank_resource(img, 8)
    assert len(mu.jukebox(img)) == 0x44
