"""Tier 1 for the resource regions — the spec's table, no game data; and,
when the library holds the disc, that the regions the code runs as command
lists are command lists on it.

What this CAN catch: a gap or an overlap between regions, a count that
disagrees with docs/spec/file-sector-map/overview.md §"The resources, by
number", the numbers the C computes resources from (FaceDataLoad
(0x8001B1C0), FaceSlot6Load (0x8001B50C), PictureShow (0x80024A7C)).

What it CANNOT catch: a region whose reader was misread — only re-reading
the readers does that. See decoders/testing.py.
"""

import pytest

from decoders import config
from decoders.plugins.SLUS_006_28.formats import command_list as cl
from decoders.plugins.SLUS_006_28.formats import resources as rs


def test_the_regions_cover_1_to_599_once_each():
    covered = [n for r in rs.REGIONS for n in range(r.first, r.last + 1)]
    assert covered == list(range(1, 600))
    assert rs.region(0) is None and rs.region(600) is None


def test_the_counts_the_spec_gives():
    size = {r.key: r.last - r.first + 1 for r in rs.REGIONS}
    assert (size["maps"], size["scripts"], size["object-sets"]) == (97, 62, 97)
    assert (size["portrait-files"], size["scene-portraits"]) == (24, 42)
    assert (size["battle-sets"], size["effects"], size["effect-layers"]) == (48, 64, 16)
    assert size["bromides"] == 13
    banks = sum(size[k] for k in ("sound-common", "sound-music", "sound-area", "sound-battle"))
    assert banks == 127


def test_numbers_the_c_reads_by():
    assert rs.number_in_region(0xA3) == "portrait file 1"
    assert rs.number_in_region(0xE4) == "scene block 42"
    assert rs.number_in_region(0x24A + 12) == "bromide 12"
    assert rs.number_in_region(4) is None


def test_command_lists():
    assert [n for n in (1, 2, 3, 4, 101, 232, 359, 472, 489, 586, 599)
            if rs.is_command_list(n)] == [1, 3, 4, 232, 472, 586, 599]


_DISC = config.raw_dir("SLUS_006.28")


@pytest.mark.disc
@pytest.mark.skipif(not (_DISC / "SLUS_006.28").exists(),
                    reason="SLUS_006.28 is not extracted in the library")
def test_on_the_disc_every_command_list_holds_only_dispatched_types():
    from decoders.psx.analysis.exe_loader import load_exe
    from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
    table = load_resource_table(load_exe(_DISC / "SLUS_006.28"))
    with open(_DISC / "LUNADATA.FIL", "rb") as f:
        for res in table:
            if not rs.is_command_list(res.index):
                continue
            f.seek(res.offset)
            cmds = cl.commands(f.read(res.size))
            assert cmds and all(c.type in cl.TYPES for c in cmds), res.index
