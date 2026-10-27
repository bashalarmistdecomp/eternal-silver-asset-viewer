"""The In game view's glue (field_view.reach_data, debug_scripts) and the
World Maps list's groups — made-up inputs, no game data.

What this CAN catch: a doubtful move taken where its first screen is
drawn and left out where it is black (and all left out with no picture),
the mask black where hidden and clear where seen at half scale, the box,
no view without a way in, the scripts only the debug room hands over to
(a script another map's script reaches too stays), and a map's row put
under its party kind's heading.

What it CANNOT catch: whether the game's maps and scripts are read right
(the on-disc tabs tests open them), nor whether the walk follows the
field's rules (formats/tests/test_map_reach.py).
"""

from types import SimpleNamespace

from PIL import Image

from decoders.plugins.SLUS_006_28.formats import map_reach as mr
from viewer_tabs import field_view as fv


def _plane():
    return [[0] * mr.CELLS for _ in range(mr.CELLS)]


def _fm(starts, doubtful):
    inputs = fv.ReachInputs(party_kind=1, starts=starts, places={}, acts={},
                            planes=[_plane()], doubtful=doubtful)
    return SimpleNamespace(reach_inputs=lambda _map_id: inputs)


IN = mr.Start(100, 100, (0, 640, 0, 224), "an entry")
DRAWN = mr.Start(1200, 600, (960, 1600, 480, 800), "a move over a drawn screen")
BLACK = mr.Start(1800, 1500, (1600, 2048, 1300, 1700), "a move over a black one")


def _picture():
    pic = Image.new("RGB", (mr.PLANE, mr.PLANE))
    pic.paste((200, 200, 200), (960, 480, 1600, 800))
    return pic


def test_a_doubtful_move_counts_where_its_first_screen_is_drawn():
    r = fv.reach_data(_fm([IN], [DRAWN, BLACK]), 0, _picture())
    assert (r["ways"], r["skipped"]) == (2, 1)
    assert r["bbox"] == [0, 0, 1600, 800]
    r = fv.reach_data(_fm([IN], [DRAWN, BLACK]), 0)
    assert (r["ways"], r["skipped"]) == (1, 2) and r["bbox"] == [0, 0, 640, 224]


def test_the_mask_is_black_where_hidden():
    r = fv.reach_data(_fm([IN], []), 0)
    mask = r["mask"]
    assert r["scale"] == fv.REACH_SCALE and mask.size == (mr.PLANE // 2, mr.PLANE // 2)
    assert mask.getpixel((50, 50)) == (0, 0, 0, 0)          # map (100, 100): seen
    assert mask.getpixel((319, 111)) == (0, 0, 0, 0)        # the limits' last pixel
    assert mask.getpixel((320, 50)) == (0, 0, 0, 255)       # past the limits
    assert mask.getpixel((900, 900)) == (0, 0, 0, 255)


def test_no_way_in_no_view():
    assert fv.reach_data(_fm([], []), 0) is None
    assert fv.reach_data(_fm([], [BLACK]), 0, _picture()) is None


def test_the_scripts_only_the_debug_room_hands_over_to():
    switches = {
        0: [(0xC8, None)],                  # the room's script -> a menu
        0xC8: [(0x64, None), (0xC8, 0x15)],  # which warps and goes on running
        7: [(8, None)],
        9: [(0x64, 0x16)],                  # another map's script reaches 0x64 too
    }
    areas = {0x09: 0, 0x15: 7, 0x16: 9}
    assert fv.debug_scripts(switches, areas, 0x09) == {0, 0xC8}
    assert fv.debug_scripts(switches, areas, 0x30) == set()


def test_a_map_row_comes_under_its_type():
    from viewer_server.present import _world_map_row
    for kind, group in ((0, "Overworld"), (1, "Towns"), (2, "Dungeons"), (5, "Party kind 5")):
        row = _world_map_row("A place  map 21  a tune",
                             SimpleNamespace(area=SimpleNamespace(party_kind=kind)))
        assert row["group"] == group and row["title"] == "A place"
        assert row["groupNote"]
