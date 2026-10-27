"""libspu's reverb preset tables in this EXE, and the reverb the game sets.

WHERE (read off the code, not searched for): the game's
`SpuSetReverbModeType` is SpuSetReverbModeType (0x800A0E68), byte-identical to libspu 4.6
s_srmt.o modulo relocations (`libobj.py --pin`). Aligning its relocation
sites with the Sony object (`sdkbrief.py SpuSetReverbModeType --names`) names its
two tables:

    _spu_rev_startaddr  -> D_800B8140   10 x u32, mBASE per mode
    _spu_rev_param      -> D_800B8170   10 x 0x44-byte register records

The record layout and the network are Sony's and live in
`decoders.psx.formats.spu_reverb`; only the addresses are this
program's.

WHAT THE GAME SETS (transcribed from code, both functions converted):
`sound_init (0x80023D54)` does `li a0, 4; li a1, 0x30; jal sound_reverb_set (0x800241F4)`, and
`sound_reverb_set(mode, depth)` is

    SpuSetReverbModeType(mode | 0x100);          # 0x100: clear work area
    SpuSetReverbModeDepth((s16)(depth << 8),
                          (s16)((depth << 8) | 0x8000));
    SpuSetReverb(SPU_ON);

so mode 4 = SPU_REV_MODE_STUDIO_C, and sound_reverb_set leaves vLOUT = 0x3000,
vROUT = 0xB000 (the or-ed 0x8000 is in the instructions, `addiu a1, zero,
-0x8000; or a1, s0, a1`). That is NOT the depth the game ends up with:
sound_init goes on to call SsStart2 (0x80098388) and then, at
0x80023DDC, `li a0, 0x2800; jal SpuSetReverbModeDepth; move a1, a0` (SpuSetReverbModeDepth is 0x800A1038) —
SpuSetReverbModeDepth(0x2800, 0x2800) — before
SpuSetCommonMasterVolume(0x3F80, 0x3F80). SpuSetReverbModeDepth stores its
two arguments raw to SPU +0x184/+0x186 (libspu s_srmd.o), so the later call
wins: the game's reverb output is vLOUT = vROUT = 0x2800, in phase
(docs/spec/code/libsnd-map.md). FUNC_800241F4_VLOUT / _VROUT keep the pair
the earlier call set. Per-voice enable is the VAB tone's `mode` byte
(VagAtr.mode), bit 2 — read by the renderer.
"""

from __future__ import annotations

from decoders.psx.formats.spu_reverb import (
    PRESET_SIZE, MODE_NAMES, ReverbPreset, ReverbSetting, parse_libspu_tables)

from . import programs

PARAM_ADDR = 0x800B8170         # _spu_rev_param
STARTADDR_ADDR = 0x800B8140     # _spu_rev_startaddr
EXE_BASE = 0x80011000           # where the EXE's header loads its image
COUNT = len(MODE_NAMES)

#: transcribed from sound_init (0x80023D54) -> sound_reverb_set (0x800241F4) (see the docstring)
GAME_MODE = 4
GAME_DEPTH_ARG = 0x30
FUNC_800241F4_VLOUT = (GAME_DEPTH_ARG << 8) & 0xFFFF
FUNC_800241F4_VROUT = ((GAME_DEPTH_ARG << 8) | 0x8000) & 0xFFFF
#: ...overwritten by sound_init (0x80023D54)'s own SpuSetReverbModeDepth(0x2800,
#: 0x2800) at 0x80023DDC: the depth the game plays with
GAME_VLOUT = 0x2800
GAME_VROUT = 0x2800
#: SLPS_013.97's sound_init (SLPS_013.97 0x800267A4) makes the same
#: sound_reverb_set(4, 0x30) call, but sets the final depth another way: the
#: function at SLPS_013.97 0x8009A568, called with (40, 40), scales each
#: depth of 0..127 by 0x7FFF / 127 and sets both reverb depths to it, in phase.
JP_GAME_DEPTH = 40
JP_GAME_VOUT = JP_GAME_DEPTH * 0x7FFF // 127
PROVEN_BY = ("sound_init (0x80023D54)", "sound_reverb_set (0x800241F4)", "SpuSetReverbModeType (0x800A0E68)",
             "SpuSetReverbModeDepth (0x800A1038)", "_spu_setReverbAttr (0x8009FAF8)")


def _read(src, addr: int, size: int) -> bytes:
    """`src` is the code.bin image (bytes, based at EXE_BASE) or anything
    with `read_bytes(addr, n)` (exe_loader.LoadedBinary)."""
    if hasattr(src, "read_bytes"):
        return bytes(src.read_bytes(addr, size))
    off = addr - EXE_BASE
    if off < 0 or len(src) < off + size:
        raise ValueError(f"image of {len(src):#x} bytes does not cover "
                         f"{addr:#x}..+{size:#x}")
    return bytes(src[off:off + size])


def read_from_exe(src) -> list[ReverbPreset]:
    """All ten libspu presets, straight out of the EXE."""
    param = programs.address(src, "_spu_rev_param", PARAM_ADDR)
    start = programs.address(src, "_spu_rev_startaddr", STARTADDR_ADDR)
    return parse_libspu_tables(_read(src, param, COUNT * PRESET_SIZE),
                               _read(src, start, COUNT * 4), COUNT)


def game_setting(src) -> ReverbSetting:
    """The reverb the game configures: STUDIO_C at the depth pair its code
    leaves in the registers (sound_init (0x80023D54)'s final 0x2800 / 0x2800;
    SLPS_013.97's JP_GAME_VOUT on both sides)."""
    preset = read_from_exe(src)[GAME_MODE]
    if programs.program_of(src) == programs.JP:
        return ReverbSetting(preset, JP_GAME_VOUT, JP_GAME_VOUT)
    return ReverbSetting(preset, GAME_VLOUT, GAME_VROUT)
