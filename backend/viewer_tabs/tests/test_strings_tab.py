"""The Strings tab's In the program view on made-up regions: no game data.

What this CAN catch: a region the program does not have (the Japanese
program's dictionary) given an address all the same.

What it CANNOT catch: whether the program's regions are where the tab
reads them (the tests on a disc).
"""

from decoders.plugins.SLUS_006_28.formats.script_text import TextBlock, TextEntry
from viewer_tabs.tab_providers import ProgramText


def test_a_region_the_program_lacks_gives_no_address():
    none = TextBlock("Made-up words", note="this program has none")
    got = ProgramText().on_select(none, None, None, None)
    assert "address" not in got.info and "this program has none" in got.info
    some = TextBlock("Made-up words", 0x80012340, [TextEntry('0  "made"', 0x80012340)])
    got = ProgramText().on_select(some, None, None, None)
    assert got.text.splitlines()[:4] == ["Made-up words", "1 entries", "address 0x80012340", ""]


def test_the_program_text_says_why_it_could_not_be_read_and_tries_again(tmp_path):
    from types import SimpleNamespace
    ctx = SimpleNamespace(exe_path=tmp_path / "NO_EXE", data_dir=tmp_path)
    view = ProgramText()
    ((label, block),) = view.get_items(None, None, ctx, None)
    assert block is None and label.startswith("Could not read the program's text: "), label
    assert view._blocks is None                 # not kept: the next look reads again
