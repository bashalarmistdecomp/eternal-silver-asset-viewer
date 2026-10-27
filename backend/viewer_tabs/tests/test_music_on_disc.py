"""The Music tab on the user's own SSSC discs, when the library has them
(skipped otherwise; nothing from the disc enters git).

What this CAN catch: a song MusicPlay plays that Music does not list, or
lists out of the game's order; a row not titled as the game titles it; a
song whose home is not its own row, in the view the tab is on; a map's or
a battle's music that does not find its song in Music (what their music
buttons and a song card's Open in follow); the CD song's page; a Sound
banks row not named by its reference.

What it CANNOT catch: whether a song sounds as the game plays it.
"""

import re

import pytest

from decoders import config

_PROGRAM = "SLUS_006.28"
_DISC = config.raw_dir(_PROGRAM)

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (_DISC / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _tab(session, key) -> int:
    return next(t["index"] for t in session.describe()["tabs"] if t["key"] == key)


def _songs(session) -> list[int]:
    from viewer_tabs.tab_providers import MusicProvider
    return [b.number for b in MusicProvider._songs(session.model(0).need_names())]


def test_every_song_is_listed_by_its_title_in_the_games_order(session):
    names = session.model(0).need_names()
    rows = session.items(_tab(session, "music"), "Music")["rows"]
    songs = _songs(session)
    assert len(songs) > 60
    assert [r["title"] for r in rows] == [names.bgm(n) or f"song {n}" for n in songs]
    assert all(f"song {n}" in r["sub"] or r["title"] == f"song {n}"
               for r, n in zip(rows, songs))


def test_each_song_is_found_in_its_own_row(session):
    from viewer_tabs.refs import ref
    music = _tab(session, "music")
    for view in ("Arrangement", "Music"):
        session.items(music, view)
        for item, n in enumerate(_songs(session)):
            home = session.locate(ref("song", n), 0)
            assert home is not None and (home["key"], home["view"], home["item"]) == (
                "music", view, item), (n, home)


def test_the_music_of_maps_and_battles_is_found_in_music(session):
    from viewer_tabs.links import LinkIndex
    index = LinkIndex.of(session.model(0))
    played = {e.frm.kind: e.to for edges in index.into.values() for e in edges
              if e.to.kind == "song" and e.frm.kind in ("map", "battle")}
    assert set(played) == {"map", "battle"}
    for song in played.values():
        assert session.locate(song, 0)["key"] == "music"
        assert session.card(song, 0)["home"]["key"] == "music"


def test_the_disc_audio_song_opens(session):
    music = _tab(session, "music")
    rows = session.items(music, "Music")["rows"]
    cd = [i for i, r in enumerate(rows) if "the disc's own audio" in r["sub"]]
    assert len(cd) == 1
    shown = session.select(music, "Music", cd[0])
    assert shown["ref"]["kind"] == "song" and shown["sheet"]["sections"]
    if shown.get("audio"):
        assert shown["audio"]["songs"] == [shown["ref"]["id"][0]]


def test_sound_banks_rows_are_named_by_their_references(session):
    banks = _tab(session, "sound-banks")
    samples = session.items(banks, "Samples")["rows"]
    assert samples and all(re.fullmatch(r"sample \d+/\d+", r["title"]) for r in samples)
    sequences = session.items(banks, "Sequences")["rows"]
    named = [r for r in sequences if r.get("mono")]
    assert named and all(re.fullmatch(r"sequence \d+/\d+", r["title"]) for r in named)
    assert all(r["sub"].startswith("sequence ") for r in sequences if not r.get("mono"))
    assert all(re.match(r"sound bank \d+", r["title"])
               for r in session.items(banks, "Banks")["rows"])
