"""A link finds its thing's row (GameSession.locate) — made-up tabs and
rows, no game data.

What this CAN catch: the row claimed in the first tab that is the kind's
home, and every tab's that is one, looked for in the view the tab is on when that is one of the kind's
views (else its first), the version held by the disc the thing was met on,
no row for a thing no tab lists, the thing a result shows and its links
reaching the app, which disc a request means, and a picture the app drew
saved in the item's folder (a PNG only, its name made safe, blown up with
each pixel a block).

What it CANNOT catch: whether the tabs claim the right rows (the on-disc
links test).
"""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from viewer_server.merge import Entry, Row, Version
from viewer_server.session import GameSession, Tab
from viewer_tabs.refs import ref
from viewer_tabs.tab_providers import SelectResult


class _Maps:
    key = "maps"

    def on_select(self, data, cache, archive, ctx):
        return SelectResult(info="a map", ref=ref("map", 4))


class _Sound:
    key = "sound"
    name = "Sound"
    VIEWS = ("Samples", "Scores", "Timelines")
    homes = {"song": ("Scores", "Timelines")}

    def __init__(self):
        self.view = "Samples"

    def get_views(self):
        return list(self.VIEWS)

    @staticmethod
    def holds(data, r, ctx):
        return data == f"bgm{r.id[0]}"


class _Store:
    def put_bytes(self, data, mime):
        return mime


def _row(*versions) -> Row:
    """Versions as (holders, data)."""
    return Row(("k",), [Version([Entry(holders, 0, data, data, None)]) for holders, data in versions])


def _session(exports=None):
    s = GameSession("k", "t", [], _Store())
    sound = [_Sound(), _Sound()]
    s.members = [SimpleNamespace(providers={"maps": _Maps(), "sound": sound[m]}, archive=None,
                                 tag=f"disc {m}", ctx=SimpleNamespace(program="SLUS_999.99",
                                                                      exports_dir=lambda: exports))
                 for m in (0, 1)]
    s.tabs = [Tab(_Maps, [0, 1]), Tab(_Sound, [0, 1])]
    asked = []
    rows = {
        0: [_row(((1,), "map"), ((0,), "map"))],
        1: [_row(((0, 1), "bgm8")), _row(((1,), "bgm6"), ((0,), "bgm6")), _row(((0,), "bgm7"))],
    }

    def listed(index, view):
        if index == 1:
            asked.append(view)
            for p in sound:
                p.view = view
        return view, rows[index]
    s._rows = listed
    return s, sound, asked


def test_the_row_that_holds_a_thing():
    s, sound, asked = _session()
    s._links = lambda m, r: [{"title": "Music", "dir": "out", "links": [{"ref": ref("song", 6).json(), "m": m}]}]
    try:
        r = s.select(0, None, 0, version=1)             # the map, as disc 0 holds it
        assert r["ref"] == {"kind": "map", "id": [4]}
        assert r["disc"] == "disc 0"
        assert r["links"][0]["links"][0] == {"ref": {"kind": "song", "id": [6]}, "m": 0}
        m = s.member_of(result=r["id"])
        assert m == 0 and s.member_of(disc="disc 1") == 1 and s.member_of() == 0
        song = ref("song", 6)
        assert s.locate(song, m) == {"tab": 1, "key": "sound", "name": "Sound", "view": "Scores",
                                     "item": 1, "version": 1}
        assert asked == ["Scores"]                      # the tab was on Samples
        sound[0].view = "Timelines"
        assert s.locate(song, m)["view"] == "Timelines"
        assert s.locate(ref("song", 9), m) is None
        assert s.locate(ref("map", 4), m) is None       # no tab says it is a map's home
        with pytest.raises(KeyError):
            s.member_of(result="gone")
        with pytest.raises(KeyError):
            s.member_of(disc="disc 9")
    finally:
        s.close()


def test_a_disc_whose_links_cannot_be_read_shows_none():
    s, _sound, _asked = _session()
    try:
        r = s.select(0, None, 0)
        assert r["ref"] == {"kind": "map", "id": [4]} and r["links"] == []
    finally:
        s.close()


def test_a_picture_the_app_drew_is_saved_with_the_item(tmp_path):
    s, _sound, _asked = _session(tmp_path)
    try:
        rid = s.select(0, None, 0)["id"]
        png = b"\x89PNG\r\n\x1a\n" + b"made up"
        path = s.save(rid, "area 01", png)
        assert path == str(tmp_path / "map" / "area_01.png")
        assert (tmp_path / "map" / "area_01.png").read_bytes() == png
        assert s.save(rid, "../../up", png) == str(tmp_path / "map" / ".._.._up.png")
        buf = io.BytesIO()
        Image.new("RGBA", (2, 1), (9, 8, 7, 255)).save(buf, "PNG")
        big = Image.open(s.save(rid, "big", buf.getvalue(), scale=4))
        assert big.size == (8, 4) and big.getpixel((3, 3)) == (9, 8, 7, 255)
        with pytest.raises(ValueError):
            s.save(rid, "not a picture", b"GIF89a")
        with pytest.raises(ValueError):
            s.save(rid, "huge", png, scale=99)
        with pytest.raises(KeyError):
            s.save("gone", "x", png)
    finally:
        s.close()


def test_a_thing_with_two_homes_opens_in_the_first(monkeypatch):
    """A chest's homes are its map and Items' Treasure: every tab that
    claims it is a home, in the tabs' order, and the first is its "Open in"."""
    s, _sound, _asked = _session()
    monkeypatch.setattr(_Maps, "name", "Maps", raising=False)
    monkeypatch.setattr(_Maps, "homes", {"song": (None,)}, raising=False)
    monkeypatch.setattr(_Maps, "holds", staticmethod(lambda data, r, ctx: data == "map"),
                        raising=False)
    try:
        song = ref("song", 6)
        assert [(h["key"], h["item"]) for h in s.homes(song, 0)] == [("maps", 0), ("sound", 1)]
        assert s.locate(song, 0)["key"] == "maps"
        assert s.homes(ref("song", 9), 0) == [{"tab": 0, "key": "maps", "name": "Maps",
                                               "view": None, "item": 0, "version": 1}]
    finally:
        s.close()
