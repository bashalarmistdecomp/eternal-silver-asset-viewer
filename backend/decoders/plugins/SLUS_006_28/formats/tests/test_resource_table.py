"""Tier 1 for the resource table — a synthetic EXE image, no game data.

What this CAN catch: the table's size (601 pairs, to g_ScriptResourcePairs
(0x800AF268)), so the pairs that follow it are not read as resources, and
which pairs are left out (a start or a length of 0).

What it CANNOT catch: whether the pairs are this program's — only
re-reading resource_load (0x80020230) does that. See decoders/testing.py.
"""

import pytest

from decoders import config
from decoders.psx.analysis.exe_loader import LoadedBinary, load_exe
from decoders.psx.analysis.symbols import lookup
from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
from decoders.testing import u16

TABLE = lookup("g_ResourceSectorPairs")
NEXT_SYMBOL = 0x800AF268            # g_ScriptResourcePairs


def _binary(pairs: list[tuple[int, int]], after: list[tuple[int, int]]) -> LoadedBinary:
    body = b"".join(u16(a, b) for a, b in pairs + after)
    return LoadedBinary(raw=body, text_start=TABLE.addr, text_size=len(body),
                        entry_point=TABLE.addr)


def test_the_table_ends_at_the_next_symbol():
    assert TABLE.addr + TABLE.size == NEXT_SYMBOL
    assert TABLE.size // 4 == 601


def test_pairs_one_to_599_are_read_and_nothing_after():
    pairs = [(0, 599)] + [(16 + i, 1) for i in range(599)] + [(615, 0)]
    script_pairs = [(0, 101), (1, 102)]         # what follows the table
    res = load_resource_table(_binary(pairs, script_pairs))
    assert [r.index for r in res] == list(range(1, 600))
    assert (res[0].start_sector, res[0].size_sectors) == (16, 1)
    assert res[-1].offset == (16 + 598) * 2048 and res[-1].size == 2048


# -- the user's disc, when the library holds it ------------------------------

_DISC = config.raw_dir("SLUS_006.28")


@pytest.mark.disc
@pytest.mark.skipif(not (_DISC / "SLUS_006.28").exists(),
                    reason="SLUS_006.28 is not extracted in the library")
def test_the_disc_s_resources_tile_the_archive():
    res = load_resource_table(load_exe(_DISC / "SLUS_006.28"))
    assert [r.index for r in res] == list(range(1, 600))
    for before, r in zip(res, res[1:]):
        assert r.start_sector == before.start_sector + before.size_sectors
    assert res[-1].offset + res[-1].size == (_DISC / "LUNADATA.FIL").stat().st_size
