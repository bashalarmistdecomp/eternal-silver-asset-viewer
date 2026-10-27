"""Tier 1 for the program's reverb tables — a synthetic EXE image.

What this CAN catch: the tables read at the wrong base, stride or order,
the startaddr/param pairing per mode, and the depth pair the game's code
leaves (sound_reverb_set (0x800241F4): depth << 8 left, (depth << 8) | 0x8000 right, then
overwritten by sound_init (0x80023D54)'s SpuSetReverbModeDepth(0x2800, 0x2800)).

What it CANNOT catch: whether PARAM_ADDR / STARTADDR_ADDR are this
program's — that came from aligning SpuSetReverbModeType (0x800A0E68)'s relocations with libspu
s_srmt.o (sdkbrief), and is re-provable only by re-reading that code.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.records import spu_reverb as RR


def _image(img: bytearray | None = None, param: int = RR.PARAM_ADDR,
           start: int = RR.STARTADDR_ADDR) -> bytes:
    end = max(param + RR.COUNT * 0x44, start + RR.COUNT * 4) - RR.EXE_BASE
    img = bytearray(end) if img is None else img + bytes(end - len(img))
    for m in range(RR.COUNT):
        rec = struct.pack("<I32H", 0, *([0x100 + m] * 32))
        o = param - RR.EXE_BASE + m * 0x44
        img[o:o + 0x44] = rec
        struct.pack_into("<I", img, start - RR.EXE_BASE + 4 * m, 0xF000 + m)
    return bytes(img)


def test_reads_both_tables_per_mode():
    ps = RR.read_from_exe(_image())
    assert len(ps) == 10
    assert ps[4].reg("dAPF1") == 0x104 and ps[4].base == 0xF004
    assert ps[9].reg("vRIN") == 0x109


def test_game_setting_is_studio_c_at_the_codes_depth():
    s = RR.game_setting(_image())
    assert s.preset.mode == 4 and s.preset.name == "STUDIO_C"
    # sound_init (0x80023D54)'s SpuSetReverbModeDepth(0x2800, 0x2800) overwrites the
    # pair sound_reverb_set (0x800241F4) computed — the later register write is the game's
    assert (s.vlout, s.vrout) == (0x2800, 0x2800)
    assert s.depth == (pytest.approx(0.3125), pytest.approx(0.3125))
    assert (RR.FUNC_800241F4_VLOUT, RR.FUNC_800241F4_VROUT) == (0x3000, 0xB000)


def test_short_image_is_an_error():
    with pytest.raises(ValueError):
        RR.read_from_exe(b"\0" * 16)


def test_reads_through_a_loaded_binary():
    img = _image()

    class FakeBinary:                         # exe_loader.LoadedBinary shape
        def read_bytes(self, addr, n):
            o = addr - RR.EXE_BASE
            return img[o:o + n]
    assert RR.game_setting(FakeBinary()).preset.base == 0xF004


def test_the_japanese_program_reads_its_own_tables_and_plays_depth_40(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    img = _image(jp_image(0x100), programs.JP_TABLES["_spu_rev_param"].addr,
                 programs.JP_TABLES["_spu_rev_startaddr"].addr)
    ps = RR.read_from_exe(img)
    assert ps[4].reg("dAPF1") == 0x104 and ps[4].base == 0xF004
    s = RR.game_setting(img)
    assert s.preset.mode == 4
    # the depth (40, 40) on 0..127, scaled by 0x7FFF / 127, both in phase
    assert (s.vlout, s.vrout) == (0x2850, 0x2850)
