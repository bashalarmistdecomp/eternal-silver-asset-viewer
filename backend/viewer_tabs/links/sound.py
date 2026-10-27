"""Songs: what plays them, and what they play from.

A song is a number MusicPlay (0x80054F2C) plays: a bank's first sequence,
or CD track 2 for song 60 (records.music). The game titles it as its
jukebox captions it (string 0x546 + n). A map plays its map record's song
(byte 0xF); a battle plays what starts it, and its win's jingle
(viewer_tabs.battle_music).
"""

from __future__ import annotations

from viewer_tabs import links
from viewer_tabs.links import CardBody, Edge
from viewer_tabs.refs import ref

MUSIC_PLAY = "MusicPlay (0x80054F2C)"


def _jukebox(model) -> dict:
    from decoders.plugins.SLUS_006_28.records import music
    cache = model.__dict__.get("_jukebox")
    if cache is None:
        cache = model.__dict__["_jukebox"] = {
            b.number: b for b in music.jukebox(model.need_names().binary.code)}
    return cache


@links.title("song")
def song_title(model, r) -> str | None:
    names = model.names
    return names.bgm(r.id[0]) if names else None


@links.card("song")
def song_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.records import music
    n = r.id[0]
    names = model.need_names()
    b = _jukebox(model).get(n) or music.bgm(names.binary.code, n)
    facts = []
    if b.kind == "cd":
        facts.append(("Plays from", f"the disc's own audio, CD track {b.track}"))
    elif b.kind != "sequence":
        facts.append(("Plays", "nothing: the game stops the music"))
    jukebox = music.JUKEBOX_FIRST <= n <= music.JUKEBOX_LAST
    if jukebox:
        facts.append(("In the jukebox", "yes, once it is unlocked"))
    if not names.bgm(n):
        facts.append(("Title", "none: the jukebox gives it no caption"))
    extended = [("Title", f"string {music.TITLE_BASE + n} (MenuUseMusicListDisp (0x800774EC))")]
    if b.kind == "sequence":
        extended.append(("Plays from", f"sound bank {b.resource}, its first score "
                                       f"(sequence {b.resource}/0)"))
        extended.append(("Bank", f"resource {b.resource}: g_MusicBankNumbers, then "
                                 f"sound_music_load (0x80023E9C)"))
    return CardBody(title=names.bgm(n) or f"song {n}", subtitle="a song of the soundtrack",
                    facts=facts, extended=extended,
                    proven=[MUSIC_PLAY, "MenuUseMusicListSet (0x80077380)"])


@links.edges(kept=True)
def song_edges(model):
    """Each song -> its bank or CD track; each map -> its song; each battle
    -> what it plays."""
    for n, b in _jukebox(model).items():
        if b.kind == "sequence":
            yield Edge(ref("song", n), ref("sound-bank", b.resource), "Plays from", "Plays",
                       "its first score", MUSIC_PLAY)
        elif b.kind == "cd":
            yield Edge(ref("song", n), ref("cd-track", b.track), "Plays from", "Plays",
                       "the disc's own audio", MUSIC_PLAY)
    names = model.need_names()
    for m in names.maps():
        if m.area.bgm:
            yield Edge(ref("map", m.map_id), ref("song", m.area.bgm), "Music", "Played on maps",
                       "the map's music", "g_MapTbls (map record byte 0xF)")
    yield from _battle_songs(model)


def _battle_songs(model):
    from decoders.plugins.SLUS_006_28.records import encounters as en
    from viewer_tabs import battle_music as bm
    names = model.need_names()
    fm, fights = model.field, model.fights
    for e in en.all_encounters(names.binary.code):
        for s in bm.songs(fm, names, fights, e.id):
            win = s["bgm"] in (bm.WIN_BGM, bm.BOSS_WIN_BGM) and s["note"].startswith("the win")
            yield Edge(ref("battle", e.id), ref("song", s["bgm"]), "Music",
                       "Played in battles", s["note"],
                       "BtlRun (0x80027434)" if win else "MapBtlRun (0x8007AE58)")
