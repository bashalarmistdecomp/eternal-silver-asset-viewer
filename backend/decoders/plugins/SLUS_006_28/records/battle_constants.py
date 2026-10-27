"""EXE-static constants the Data tables tab shows beside the tables — no
emulator, no save.

The facing step tables are the FIELD's, not the battle's: MapSpotMove
(0x80066848) moves a spot on the map along a facing, for the map's steps and
looks: MapSpotMoveTry (0x8006661C), MapSpotSideMoveTry (0x800668A8),
MapObjectWanderStep (0x8006758C), StepWalkStep (0x800677D4), MapObjectFacingWalk
(0x8007868C), MapObjectOpenFacingFind (0x800787F0) and MapObjectSideFacingGet
(0x80078A44) call it, and no battle function does. They
are plain arrays in the EXE's data region, never written, so they come out of
the EXE image directly. The RNG has no table here, only its functions'
names.

Evidence: docs/spec/code/subsystems/npc-scripting.md §"The step primitive";
docs/spec/code/subsystems/map-enemies.md §"Tables".
"""

from __future__ import annotations

import struct

from .programs import address

EXE_BASE = 0x80011000           # where the EXE's header loads its image

# g_MapFacingDxs (0x80012C1C) / g_MapFacingDys (0x80012C24): two parallel s8[8],
# the step of facing 1..8 (1 toward smaller y, 3 toward larger x, clockwise).
# MapSpotMove(facing, dist, &x, &y) adds dist * dx[(facing - 1) & 7] to x and
# dist * dy[(facing - 1) & 7] to y.
DIR_DX_ADDR = 0x80012C1C
DIR_DY_ADDR = 0x80012C24
DIR_COUNT = 8


def _read_s8_array(image: bytes, addr: int, count: int) -> list[int]:
    off = addr - EXE_BASE
    if off < 0 or len(image) < off + count:
        raise ValueError(
            f"image of {len(image):#x} bytes does not cover {addr:#x}"
            f" .. +{count:#x}")
    return list(struct.unpack_from(f"<{count}b", image, off))


def read_direction_tables(image: bytes) -> tuple[list[int], list[int]]:
    """-> (dx, dy), each s8[8], indexed by `facing - 1`."""
    return (_read_s8_array(image, address(image, "g_MapFacingDxs", DIR_DX_ADDR), DIR_COUNT),
            _read_s8_array(image, address(image, "g_MapFacingDys", DIR_DY_ADDR), DIR_COUNT))


# --- the RNG, for the record -----------------------------------------
# There is deliberately NO reader for the ran55 pool here. The pool is
# generated state, not data: `rng_seed (0x8001C5F8)` is the game's srand() —
# Knuth subtractive init, seed in $a0, three warm-up refills, cursor left
# at 0x37. A port seeds itself by running that function, which is both
# provenance-clean and strictly more useful than a captured pool (any
# seed, not one frozen sequence).
RNG_SEED_FUNC = "rng_seed (0x8001C5F8)"     # srand(seed)
RNG_NEXT_FUNC = "rng_next (0x8001C6B0)"     # rand()
RNG_REFILL_FUNC = "rng_refill (0x8001C548)"   # pool refill
RNG_POOL_SYMBOL = "g_RngNumbers (0x800E0910)"      # 56 words; pool is [1..55]
RNG_CURSOR_SYMBOL = "g_RngCursor (0x800B8978)"
