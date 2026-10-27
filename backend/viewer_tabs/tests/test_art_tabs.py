"""The Art tabs, Bromides and Screens, on made-up pictures and names: no
game data.

What this CAN catch: a picture titled other than by what the code does
with it (the cards the US program never shows, the Japanese program's five
before the title, the disc-change screens, the two after the end), a
screen listed under the wrong heading or one that is no screen listed in
Screens, a picture of All images missing, a bromide listed without its
voice or its number, a tab that does not claim its row (`holds`), and a
row that does not carry its heading to the app.

What it CANNOT catch: whether the disc's pictures are what these say
(test_art_on_disc).
"""

from types import SimpleNamespace

import pytest

from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
from decoders.plugins.SLUS_006_28.formats.resources import BROMIDE_BASE, DISC_CHANGE
from decoders.plugins.SLUS_006_28.records import programs
from viewer_server import present
from viewer_tabs import tab_providers as tp
from viewer_tabs.refs import ref
from viewer_tabs.tab_providers import BromidesProvider, ScreensProvider, Shown


def pic(resource, picture, vram_x=0, height=224):
    return rp.Picture(resource, 0x10 * (picture or 0), 1, picture, 320, height,
                      1, vram_x, 0, True)


#: the made-up names: a bromide's title is "made-up title k"
NAMES = SimpleNamespace(bromide=lambda k: f"made-up title {k}",
                        resource_entry=lambda n: n != BROMIDE_BASE + 5 or None)


@pytest.fixture
def program(monkeypatch):
    """Which program the made-up names are: the US one unless set."""
    which = {"it": programs.US}
    monkeypatch.setattr(ScreensProvider, "_program", staticmethod(lambda names: which["it"]))
    return which


def test_a_picture_is_titled_by_what_the_code_does_with_it(program):
    title = lambda p: ScreensProvider.title(NAMES, p)       # noqa: E731
    assert title(pic(rp.GLYPH_ATLAS_RESOURCE, None)) == "The font's letters"
    assert title(pic(rp.TITLE_RESOURCE, 0)) == "Before the title"
    assert title(pic(rp.TITLE_RESOURCE, 3)) == "Never shown in the game"
    assert title(pic(rp.TITLE_RESOURCE, None, vram_x=384)) == "The title screen: the logo"
    assert title(pic(BROMIDE_BASE + 2, 1)) == "made-up title 2: bottom picture"
    assert title(pic(DISC_CHANGE, 1)) == "Asks for disc 2"
    assert title(pic(DISC_CHANGE, 2)) == "Asks for disc 1 again, after a refused disc"
    assert title(pic(DISC_CHANGE, 5)) == "After the end, the last screen"
    program["it"] = programs.JP
    assert title(pic(rp.TITLE_RESOURCE, 3)) == "Before the title, 4 of 5"
    assert title(pic(rp.TITLE_RESOURCE, None, vram_x=384)) == "A page of the title screen"


def _screens(monkeypatch, view: str) -> list:
    found = [(pic(rp.GLYPH_ATLAS_RESOURCE, None), 0)]
    found += [(pic(rp.TITLE_RESOURCE, n), n) for n in range(5)]
    found += [(pic(rp.TITLE_RESOURCE, None, vram_x=768), 5)]
    found += [(pic(BROMIDE_BASE, n), n) for n in (0, 1)]
    found += [(pic(DISC_CHANGE, n, height=240 if n > 3 else 224), n) for n in range(6)]
    monkeypatch.setattr(tp.GameNames, "for_ctx", classmethod(lambda cls, ctx: NAMES))
    p = ScreensProvider()
    p._found = found
    p.view = view
    return p.get_items({}, None, SimpleNamespace(), None)


def test_screens_lists_the_screens_under_theirs_and_all_images_every_picture(monkeypatch, program):
    shown = _screens(monkeypatch, "Screens")
    assert [(s.picture.resource, s.picture.picture) for _l, s in shown] == [
        (3, 0), (3, None), (599, 0), (599, 1), (599, 2), (599, 3), (599, 4), (599, 5)]
    assert [s.group for _l, s in shown] == ([ScreensProvider.TITLE[0]] * 2
                                            + [ScreensProvider.DISCS[0]] * 4
                                            + [ScreensProvider.END[0]] * 2)
    program["it"] = programs.JP
    jp = _screens(monkeypatch, "Screens")
    assert sum(1 for _l, s in jp if s.group == ScreensProvider.TITLE[0]) == 6
    every = _screens(monkeypatch, "All images")
    assert len(every) == 15
    assert {s.group for _l, s in every} == {"Resource 1", "Resource 3", "Resources 586 to 598",
                                            "Resource 599"}
    label, first = every[0]
    assert label.split("  ")[1:] == ["image 1/0", "320x224", "sent at once"]


def test_a_screen_row_carries_its_heading():
    item = Shown(pic(DISC_CHANGE, 0), 0, "made up", "Changing discs", "what it holds")
    row = present._screen_row("made up  image 599/0", item)
    assert (row["title"], row["sub"], row["group"]) == ("made up", "image 599/0", "Changing discs")


def test_the_tabs_claim_their_rows():
    item = Shown(pic(DISC_CHANGE, 3), 3, "", "", "")
    assert ScreensProvider.holds(item, ref("image", DISC_CHANGE, 3), None)
    assert not ScreensProvider.holds(item, ref("image", DISC_CHANGE, 2), None)
    assert not ScreensProvider.holds(None, ref("image", DISC_CHANGE, 3), None)
    assert BromidesProvider.holds(4, ref("bromide", 4), None)
    assert not BromidesProvider.holds(4, ref("image", 4, 0), None)


def test_each_bromide_is_listed_with_its_number_and_voice(monkeypatch):
    voice = SimpleNamespace(number=101, seconds=11.44)
    monkeypatch.setattr(tp.GameNames, "for_ctx", classmethod(lambda cls, ctx: NAMES))
    monkeypatch.setattr(BromidesProvider, "_voices",
                        staticmethod(lambda names: ([101] * 13, {101: voice})))
    items = BromidesProvider().get_items({}, None, SimpleNamespace(), None)
    assert [k for _l, k in items] == [k for k in range(13) if k != 5]   # no resource 591
    assert items[3][0].split("  ") == ["made-up title 3", "bromide 3", "voice 101, 11.4 s"]
    monkeypatch.setattr(BromidesProvider, "_voices", staticmethod(lambda names: (None, {})))
    assert BromidesProvider().get_items({}, None, SimpleNamespace(), None)[0][0].split("  ") \
        == ["made-up title 0", "bromide 0"]
