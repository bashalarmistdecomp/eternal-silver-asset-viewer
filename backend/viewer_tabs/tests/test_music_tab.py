"""The Music tab on made-up songs: a row is its song, the page puts what a
player knows first (the title, the sound, how long it plays and whether it
repeats, where it plays) and how the game keeps it last, folded, and the
clip is the song's.

What this CANNOT catch: whether the disc's songs are listed and found (the
on-disc tests).
"""

from types import SimpleNamespace

import pytest

from decoders.plugins.SLUS_006_28.records.music import Bgm
from decoders.psx.formats.tests.test_seq_synth import ONE, _bank, _held, _looped
from decoders.psx.formats.vab import SPU_BASE_RATE
from viewer_server.present import _music_row
from viewer_tabs.links import Edge, LinkIndex
from viewer_tabs.refs import ref
from viewer_tabs.tab_providers import MusicProvider, SongItem, _clock

#: made-up titles: songs 7 and 9 play bank 40, song 8 has no title
TITLES = {7: "Made-up Theme", 9: "Made-up Reprise"}


def _songs():
    return [Bgm(7, "sequence", resource=40), Bgm(8, "sequence", resource=40),
            Bgm(9, "sequence", resource=40), Bgm(10, "sequence", resource=41)]


def _model(edges=()):
    names = SimpleNamespace(bgm=TITLES.get)
    model = SimpleNamespace(need_names=lambda: names, names=names)
    model._link_index = LinkIndex(model, sources=[lambda m: list(edges)])
    return model


def _provider(view="Music"):
    prov = MusicProvider()
    prov.view = view
    prov._songs = lambda names: _songs()
    return prov


def _item(n, score):
    return SongItem(n, next(b for b in _songs() if b.number == n),
                    SimpleNamespace(resource=40 if n < 10 else 41, seqs=[score], vab=_bank(ONE)))


def test_a_song_is_its_own_row():
    item = _item(7, _looped())
    assert MusicProvider.holds(item, ref("song", 7), None)
    assert not MusicProvider.holds(item, ref("song", 8), None)
    assert not MusicProvider.holds(item, ref("sequence", 40, 0), None)


def test_a_row_shows_its_title_then_the_rest():
    assert _music_row("Made-up Theme  song 7  1:05  loops", None) == {
        "title": "Made-up Theme", "sub": "song 7 · 1:05 · loops"}
    assert _music_row("song 8  the same score as song 7", None)["title"] == "song 8"


def test_the_page_lays_the_song_out_simple_to_complex():
    played = Edge(ref("map", 4), ref("song", 7), "Music", "Played on maps", "the map's music")
    prov, item = _provider(), _item(7, _looped())
    result = prov._page(item, _model([played]), None)
    sheet = result.sheet
    assert sheet["title"] == "Made-up Theme"
    titles = [s["title"] for s in sheet["sections"]]
    assert titles == ["", "The song", "Where it plays", "Extended info"]
    sound, facts, where, extended = sheet["sections"]
    assert sound == {"title": "", "sound": True}
    assert extended["extended"] and not where.get("extended")
    # its length: the opening and one pass of the loop, which repeats
    walked = prov._walk(item.bank)
    start, end = walked.loop
    length = ((walked.first_pass or 0) + end - start) / SPU_BASE_RATE
    got = {k: v for k, v, _hint in facts["fields"]}
    assert got["Length"] == _clock(length) and got["Repeats"].startswith("for ever")
    assert got["The same as"] == "song 8, Made-up Reprise (song 9)"
    assert [(g["title"], [link["ref"] for link in g["links"]]) for g in where["links"]] == [
        ("Played on maps", [{"kind": "map", "id": [4]}])]
    assert [link["ref"]["kind"] for link in extended["links"][0]["links"]] == [
        "sound-bank", "sequence"]
    assert result.audio["songs"] == [7] and result.audio["title"] == "Made-up Theme"
    assert result.audio["name"] == "song-7" and result.music is not None


def test_a_song_the_game_gives_no_title_is_its_number():
    prov = _provider()
    sheet = prov._page(_item(8, _looped()), _model(), None).sheet
    assert sheet["title"] == "song 8"
    facts = {k: v for k, v, _hint in sheet["sections"][1]["fields"]}
    assert facts["Title"].startswith("none")
    assert sheet["sections"][2]["note"].startswith("No map, battle or scene plays it.")


def test_a_song_that_ends_plays_once():
    prov = _provider()
    result = prov._page(_item(10, _held()), _model(), None)
    facts = {k: v for k, v, _hint in result.sheet["sections"][1]["fields"]}
    assert facts["Repeats"].startswith("no")
    assert "The same as" not in facts and "loop" not in result.audio


def test_the_arrangement_is_the_songs():
    prov = _provider("Arrangement")
    result = prov._arrangement(_item(7, _looped()), SimpleNamespace(bgm=TITLES.get))
    assert result.timeline is not None
    assert result.info.startswith("Made-up Theme\nsong 7\n")
    assert result.audio["songs"] == [7] and result.audio["name"] == "song-7"
    player = result.music.player(result.music.passes)
    while player.read(1 << 16):
        pass
    assert result.music.describe(player.result())["info"].startswith("Made-up Theme\nsong 7\n")


@pytest.mark.parametrize("seconds, shown", [(0.4, "0:00"), (65.5, "1:06"), (600, "10:00")])
def test_a_length_reads_as_a_player_shows_it(seconds, shown):
    assert _clock(seconds) == shown


@pytest.mark.parametrize("program, lunadata, music", [
    ("SLUS_006.28", True, True), ("SLUS_999.99", False, False), ("SLUS_006.28", False, False)])
def test_cd_tracks_point_to_the_music_tab_only_where_there_is_one(
        monkeypatch, tmp_path, program, lunadata, music):
    from decoders.psx.disc.cd_audio import CdTrack
    from viewer_tabs import tab_providers as tp
    monkeypatch.setattr(tp.GameNames, "for_ctx", classmethod(lambda cls, ctx: None))
    ctx = SimpleNamespace(program=program, has=lambda *names: lunadata)
    (tmp_path / "track.bin").write_bytes(bytes(4 * 100))
    track = CdTrack(2, tmp_path / "track.bin", 0, 4 * 100, 0)
    tab = tp.CdTracksProvider()
    said = tab.on_select(track, None, None, ctx).info
    assert ("Music tab" in said) is music, said
    fields = dict(tab.on_select(None, None, None, ctx).summary["fields"])
    assert ("In-game music" in fields) is music
