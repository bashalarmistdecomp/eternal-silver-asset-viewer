"""The Art tabs, Bromides and Screens, on the user's own SSSC discs, when
the library has them (skipped otherwise; nothing from the disc enters git).

What this CAN catch: a bromide whose page cannot be read, that comes
without its show (the pan's rows and the fade, the whole picture as the
screen looks down it) or without its voice; a picture the Images tab
listed that All images lost; a screen of the US or the Japanese program
missing from Screens; an image or a bromide whose card does not open in
its row of these tabs.

What it CANNOT catch: whether the pictures are drawn right.
"""

import pytest

from decoders import config
from viewer_tabs.refs import ref

_PROGRAM = "SLUS_006.28"
_DISC = config.raw_dir(_PROGRAM)

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (_DISC / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _tab(session, key):
    return next(t for t in session.describe()["tabs"] if t["key"] == key)


def test_each_bromide_has_its_page_its_show_and_its_voice(session):
    tab = _tab(session, "bromides")
    rows = session.items(tab["index"], None)["rows"]
    assert len(rows) == 13 and not any(r["empty"] for r in rows)
    problems = []
    for i, row in enumerate(rows):
        vm = session.select(tab["index"], None, i)
        page, pan = vm.get("page"), vm.get("pan")
        if not page or page["error"]:
            problems.append(f"{row['sub']}: no page {page and page['error']}")
            continue
        if not pan or len(pan["rows"]) != 752 or len(pan["dark"]) != 752:
            problems.append(f"{row['sub']}: no show")
        elif (pan["w"], pan["h"]) != (320, max(pan["rows"]) + pan["screenH"]):
            problems.append(f"{row['sub']}: the picture is {pan['w']} x {pan['h']}")
        voices = [link for g in page["groups"] for link in g["links"] if link["ref"]["kind"] == "voice"]
        if len(voices) != 1:
            problems.append(f"{row['sub']}: voices {voices}")
    assert not problems, "\n".join(problems)


def test_all_images_keeps_every_picture_and_screens_the_screens(session):
    tab = _tab(session, "screens")
    every = session.items(tab["index"], "All images")["rows"]
    assert len(every) == 41
    screens = session.items(tab["index"], "Screens")["rows"]
    us = [r for r in screens if "US 1" in r["tags"]]
    jp = [r for r in screens if "JP 1" in r["tags"]]
    assert len(us) == 10                    # a card, three pages, four disc changes, two ends
    if any("JP 1" in r["tags"] for r in every):
        assert len(jp) == 12                # five cards, three pages, four disc changes
    assert {r["group"] for r in screens} == {"The title", "Changing discs", "After the end"}


def test_an_image_and_a_bromide_open_in_their_rows(session):
    m = next(m for m, member in enumerate(session.members) if member.tag == "US 1")
    image = session.locate(ref("image", 599, 4), m)
    assert (image["key"], image["view"]) == ("screens", "All images")
    tab = _tab(session, "screens")
    vm = session.select(tab["index"], image["view"], image["item"])
    assert vm["ref"] == {"kind": "image", "id": [599, 4]}
    bromide = session.locate(ref("bromide", 7), m)
    assert bromide["key"] == "bromides"
    vm = session.select(_tab(session, "bromides")["index"], None, bromide["item"])
    assert vm["ref"] == {"kind": "bromide", "id": [7]}
