"""Sound effects, the scripts' songs and the Sound banks' two kinds, on the
user's own SSSC discs when the library has them (skipped otherwise; nothing
from the disc enters git).

What this CAN catch: a Sound effects row that is not titled by its
reference (a place's own by its bank and its number), not under its kind's
heading, or does not play; a reference that does not find its row; a map's
entrance or tile change whose link does not open the very sound its map
plays; a song only a script plays whose page does not list the scenes,
under places, the debug room's last; a scene listed twice on a card; a
Sound banks row of songs or of sound effects not told apart; a Resources
row of a bank not saying what it plays.

What it CANNOT catch: whether a sound effect sounds as the game plays it,
or a use only a table not read here makes (the map objects that see the
party, a battle show's own sounds).
"""

import re

import pytest

from decoders import config
from viewer_tabs.refs import written

_PROGRAM = "SLUS_006.28"
_DISC = config.raw_dir(_PROGRAM)

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (_DISC / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]

HEADINGS = ["Heard everywhere", "In battle", "Each place its own"]


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


@pytest.fixture(scope="module")
def sfx(session):
    from viewer_tabs.links import sound_effects as lsx
    return lsx.sound_effects(session.model(0))


def _tab(session, key) -> int:
    return next(t["index"] for t in session.describe()["tabs"] if t["key"] == key)


def test_every_row_is_a_sound_effect_by_its_number_under_its_kind(session, sfx):
    rows = session.items(_tab(session, "sound-effects"), None)["rows"]
    listed = sfx.listed()
    assert len(rows) == len(listed) > 300
    assert [r["title"] for r in rows] == [written(e.ref) for e in listed]
    assert all(re.fullmatch(r"sound effect \d+/\d+", r["title"]) for r in rows
               if r["group"] == "Each place its own")
    assert not any("/" in r["title"] for r in rows if r["group"] != "Each place its own")
    seen = list(dict.fromkeys(r["group"] for r in rows))
    assert seen == HEADINGS
    assert all(r["sub"] for r in rows)
    # every common number 1 to 24, and the battle's from 31, has its row
    numbers = {e.number for e in listed}
    assert set(range(1, 25)) <= numbers and set(range(31, 127)) <= numbers


def test_a_sound_effect_plays_and_says_what_it_is(session, sfx):
    tab = _tab(session, "sound-effects")
    listed = sfx.listed()
    picks = sorted({0, len(listed) // 2, len(listed) - 1}
                   | {next(i for i, e in enumerate(listed) if e.group == g)
                      for g in ("common", "battle", "place")})
    for i in picks:
        shown = session.select(tab, None, i)
        r = listed[i].ref
        assert shown["ref"] == r.json()
        audio = shown["audio"]
        assert audio["live"] and audio["title"] == written(r)
        assert audio["kind"] == "sound-effect"
        titles = [s["title"] for s in shown["sheet"]["sections"]]
        assert titles[:3] == ["", "The sound effect", "Where it plays"]
        assert titles[-1] == "Extended info"


def test_a_reference_finds_its_row(session, sfx):
    tab = _tab(session, "sound-effects")
    from viewer_tabs.refs import ref
    listed = sfx.listed()
    for k, e in enumerate(listed):
        home = session.locate(e.ref, 0)
        assert (home["key"], home["item"]) == ("sound-effects", k), e.ref
    # a place's number without its bank still finds the place most things play
    home = session.locate(ref("sound-effect", 131), 0)
    assert listed[home["item"]] is sfx.home(131)
    assert session.card(ref("sound-effect", 11), 0)["home"]["tab"] == tab


def test_an_entrances_and_a_tile_changes_sound_is_the_one_its_map_plays(session, sfx):
    from decoders.plugins.SLUS_006_28.records import sound_effects as se
    from viewer_tabs.links import LinkIndex
    index = LinkIndex.of(session.model(0))
    found = 0
    for to, edges in index.into.items():
        if to.kind != "sound-effect":
            continue
        for e in edges:
            if e.frm.kind not in ("entrance", "tile-change"):
                continue
            mid = e.frm.id[0]
            played = se.play(sfx.tables, to.id[-1], mid, sfx.ids.get(sfx.tables.bank(mid), ()))
            mine = sfx.find(to)
            # the link opens the very sound the map plays, the one its use is on
            assert any(u.by == e.frm for u in mine.uses), (e.frm, to)
            assert (mine.bank, mine.sequence) == (played.bank, played.sequence), (e.frm, to)
            found += 1
    assert found > 300                  # the tile changes' and the entrances'


def test_a_song_only_a_script_plays_lists_its_scenes_by_place(session):
    from viewer_tabs.links import LinkIndex, scenes
    from viewer_tabs.links import sound_effects as lsx
    from viewer_tabs.refs import ref
    model = session.model(0)
    index = LinkIndex.of(model)
    sfx = lsx.sound_effects(model)
    only = sorted(to.id[0] for to, edges in index.into.items()
                  if to.kind == "song" and {e.frm.kind for e in edges} <= {"label", "script"})
    assert only
    music = _tab(session, "music")
    home = session.locate(ref("song", only[0]), 0)
    shown = session.select(music, home["view"], home["item"])
    where = next(s for s in shown["sheet"]["sections"] if s["title"] == "Where it plays")
    groups = [g for g in where["links"] if g["dir"] == "in"]
    # the scenes; the pieces holding the command apart, with the extended info in Fan
    held = [g for g in groups if g["title"] == scenes.HELD_IN]
    groups = [g for g in groups if g["title"] != scenes.HELD_IN]
    assert groups and all(g["title"].startswith("Scenes ") for g in groups)
    assert {link["ref"]["kind"] for g in groups for link in g["links"]} <= {"label", "script"}
    assert not any(link.get("advanced") for g in groups for link in g["links"])
    assert held and all(link["advanced"] for g in held for link in g["links"])
    assert "not followed" not in where.get("note", "")
    # the debug room's scenes come after every place's
    debug = sfx.place(sfx.debug_room)
    for to in (ref("song", n) for n in range(1, 0x45)):
        heads = [g["title"] for g in (session.card(to, 0).get("groups") or [])
                 if g["dir"] == "in" and g["title"].startswith("Scenes at")]
        if f"Scenes at {debug}" in heads:
            assert heads[-1] == f"Scenes at {debug}", heads


def test_each_scene_is_listed_once(session, sfx):
    from viewer_tabs.links import LinkIndex, groups
    model = session.model(0)
    index = LinkIndex.of(model)
    shared = 0
    for to in index.into:
        if to.kind not in ("song", "sound-effect"):
            continue
        heads = [g for g in groups(model, index, to) if g["title"].startswith("Scenes ")]
        listed = [link["ref"]["id"] for g in heads for link in g["links"]]
        assert len(listed) == len({tuple(i) for i in listed}), to
        shared += sum(" and " in g["title"] for g in heads)
    assert shared                       # some scenes run on several places


def test_sound_banks_tell_songs_from_sound_effects(session):
    banks = _tab(session, "sound-banks")
    rows = session.items(banks, "Banks")["rows"]
    assert list(dict.fromkeys(r["group"] for r in rows)) == ["Songs", "Sound effects"]
    assert {r["badge"] for r in rows if r["group"] == "Songs"} == {"songs"}
    assert {r["badge"] for r in rows if r["group"] == "Sound effects"} == {"sound effects"}
    seqs = session.items(banks, "Sequences")["rows"]
    assert list(dict.fromkeys(r["group"] for r in seqs)) == ["Songs", "Sound effects"]
    effects = [r for r in seqs if r["group"] == "Sound effects"]
    assert any(r["title"].startswith("sound effect") for r in effects)
    assert all(r["title"].startswith("sound effect") or r.get("mono") for r in effects)
    assert any(re.match(r"sound effects? \d+/\d+", r["title"]) for r in effects)
    songs = [r for r in seqs if r["group"] == "Songs"]
    assert all(re.match(r"songs? \d+", r["title"]) or r.get("mono") for r in songs)
    # a sound effect's score plays under its number
    k = next(i for i, r in enumerate(seqs) if r["title"].startswith("sound effect "))
    shown = session.select(banks, "Sequences", k)
    assert shown["audio"]["title"] == seqs[k]["title"]
    assert shown["audio"]["kind"] == "sound-effect"


def test_resources_name_a_bank_by_what_it_plays(session):
    rows = session.items(_tab(session, "resources"), None)["rows"]
    by = {int(r["label"].split()[0]): r["label"] for r in rows}
    assert "sound effects bank: the common sound effects" in by[232]
    assert "sound effects bank: the battle's sound effects" in by[358]
    assert "sound effects bank: the sound effects of " in by[300]
    assert re.search(r"music bank: songs? \d+", by[240])


def test_where_it_plays_is_never_empty(session, sfx):
    """A sound only the game's own code plays (the menus') says so, rather
    than showing an empty section."""
    tab = _tab(session, "sound-effects")
    listed = sfx.listed()
    for i, e in enumerate(listed):
        if e.group != "common":
            continue
        where = next(s for s in session.select(tab, None, i)["sheet"]["sections"]
                     if s["title"] == "Where it plays")
        assert where.get("links") or where.get("note"), written(e.ref)
