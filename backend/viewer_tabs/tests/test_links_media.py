"""The media domain's links and cards (viewer_tabs.links.media) on made-up
discs: made-up files, resources, pictures and banks, no game data.

What this CAN catch: an image numbered other than by its kept number (a
picture sent at once after the kept ones), a movie linked that the game does
not have or to a file this disc lacks, the wrong story flag, a resource's
readers linked the wrong way round, a bank's sequences and samples not
listed on it, a card that does not refuse a thing that does not exist,
and a tab that does not claim its row (`holds`) or names another thing
for a row (`ref`).

What it CANNOT catch: whether the disc's own tables say what these read
(test_links_media_on_disc).
"""

import threading
from types import SimpleNamespace

import pytest

from decoders.plugins.SLUS_006_28.formats import command_list as cl
from decoders.plugins.SLUS_006_28.formats.resource_pictures import Picture
from decoders.plugins.SLUS_006_28.records import events as ev
from decoders.psx.formats.tests.test_seq_synth import ONE, _bank, _looped
from viewer_tabs.links import CardBody, LinkIndex, media
from viewer_tabs.refs import ref
from viewer_tabs.tab_providers import (BromidesProvider, DiscFilesProvider, MoviesProvider,
                                       ResourcesProvider, ScreensProvider, Shown, SoundItem,
                                       SoundBanksProvider)

US = "SLUS_006.28"


def _model(tmp_path, files=(), names=None, program=US):
    for name in files:
        (tmp_path / name).write_bytes(b"made up " + name.encode())
    ctx = SimpleNamespace(program=program, files=tuple(sorted(files)),
                          path=lambda n: tmp_path / n, source=None)

    def need_names():
        if names is None:
            raise LookupError("no names")
        return names
    return SimpleNamespace(ctx=ctx, names=names, need_names=need_names, lock=threading.RLock())


def _cmd(offset, sub):
    return cl.Command(offset, cl.TIM, cl.TIM | (sub << 8), b"")


# -- numbers ----------------------------------------------------------------

def test_an_image_keeps_its_kept_number_and_one_sent_at_once_follows_them():
    cmds = [_cmd(0, 0), _cmd(10, 1), cl.Command(20, 4, 4, b""), _cmd(30, 2), _cmd(40, 0)]
    assert media.image_numbers(cmds) == {0: (2, None), 10: (0, 0), 30: (1, 1), 40: (3, None)}
    assert media.image_numbers([cl.Command(0, 4, 4, b"")]) == {}


def test_lengths_in_plain_words():
    assert media._length(0.042) == "0.04 s"
    assert media._length(4.24) == "4.2 s"
    assert media._length(42.4) == "42 s"
    assert media._length(77.6) == "1 min 18 s"


# -- edges ------------------------------------------------------------------

def test_movies_link_their_files_here_and_their_flags(tmp_path, monkeypatch):
    model = _model(tmp_path, files=["_B000.STR", "_B002.STR", "OTHER.BIN"], names=object())
    frames = [0] * ev.MOVIE_COUNT
    frames[0] = frames[1] = 900                  # movie 1's file is on the other disc
    frames[2] = 0                                # no movie 2, though a file says so
    monkeypatch.setattr(media, "_end_frames", lambda m: frames)
    edges = list(media.movie_edges(model))
    assert {(e.frm, e.to) for e in edges} == {
        (ref("movie", 0), ref("disc-file", 1)),
        (ref("movie", 0), ref("story-flag", ev.EVENT_FLAG_BASE)),
        (ref("movie", 1), ref("story-flag", ev.EVENT_FLAG_BASE + 1)),
    }
    monkeypatch.setattr(media, "_end_frames", lambda m: None)      # no overlay on the disc
    known = {e.frm for e in media.movie_edges(model)}
    assert known == {ref("movie", 0), ref("movie", 2)}


def test_a_disc_of_another_program_has_none_of_these_links(tmp_path):
    model = _model(tmp_path, files=["_B000.STR"], program="SLUS_999.99")
    assert list(media.movie_edges(model)) == []
    assert list(media.bank_edges(model)) == []


def test_a_bromide_links_its_resource_pictures_flag_and_voice(tmp_path, monkeypatch):
    names = SimpleNamespace(resource_entry=lambda n: object() if n != 590 else None)
    model = _model(tmp_path, names=names)
    monkeypatch.setattr(media, "_image_index", lambda m: {586: [(0, 0), (1, 1), (2, None)]})
    monkeypatch.setattr(media, "_voices", lambda m: list(range(70, 70 + ev.BROMIDE_COUNT)))
    edges = list(media.bromide_edges(model)) + list(media.bromide_voice_edges(model))
    first = {(e.rel, e.to) for e in edges if e.frm == ref("bromide", 0)}
    assert first == {("Stored in", ref("resource", 586)),
                     ("Pictures", ref("image", 586, 0)), ("Pictures", ref("image", 586, 1)),
                     ("Story flag", ref("story-flag", ev.BROMIDE_FIRST + ev.EVENT_FLAG_BASE)),
                     ("Voice", ref("voice", 70))}
    fourth = {e.to.kind for e in edges if e.frm == ref("bromide", 4)}
    assert fourth == {"story-flag", "voice"}         # resource 590 is not in the table


def test_a_bromide_item_shows_the_bromide_in_its_high_bits(tmp_path, monkeypatch):
    from decoders.plugins.SLUS_006_28.records import items
    rows = [SimpleNamespace(item_id=1, values={"use_picture": 0x34}),
            SimpleNamespace(item_id=2, values={"use_picture": 0x37}),       # another use
            SimpleNamespace(item_id=3, values={"use_picture": 0xF4})]       # no bromide 15
    monkeypatch.setattr(items, "read_from_exe", lambda image: rows)
    model = _model(tmp_path, names=SimpleNamespace(binary=SimpleNamespace(code=b"")))
    edges = list(media.bromide_item_edges(model))
    assert [(e.frm, e.to) for e in edges] == [(ref("item", 1), ref("bromide", 3))]


def test_what_the_code_reads_from_a_resource_links_to_it(tmp_path):
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    from decoders.plugins.SLUS_006_28.formats import party_init as pi
    table = {7, 101, fb.file_resource(2), fb.scene_resource(3), pi.RESOURCE}
    names = SimpleNamespace(
        maps=lambda: [SimpleNamespace(map_id=21, resource=7)],
        resources=lambda: [SimpleNamespace(index=n) for n in sorted(table)],
        resource_entry=lambda n: object() if n in table else None,
        script_ids_for_resource=lambda n: [11, 12] if n == 101 else [])
    edges = list(media.resource_edges(_model(tmp_path, names=names)))
    into = {}
    for e in edges:
        into.setdefault(e.to, set()).add(e.frm)
    assert into[ref("resource", 7)] == {ref("map", 21)}
    assert into[ref("resource", 101)] == {ref("script", 11), ref("script", 12)}
    assert into[ref("resource", fb.file_resource(2))] == {ref("portrait", n) for n in range(6, 11)}
    assert into[ref("resource", fb.scene_resource(3))] == {ref("portrait-list", 3)}
    assert into[ref("resource", pi.RESOURCE)] == {
        ref("character", c) for c in range(pi.CHAR_FIRST, pi.CHAR_LAST + 1)}
    assert set(into) == {ref("resource", n) for n in table}


def test_a_bank_lists_its_sequences_and_samples_both_ways(tmp_path, monkeypatch):
    vab = _bank(ONE)
    bank = SimpleNamespace(resource=240, seqs=[_looped(), _looped()], vab=vab)
    monkeypatch.setattr(media, "_banks", lambda m: {240: bank})
    model = _model(tmp_path, names=object())
    index = LinkIndex(model, [media.bank_edges])
    on_bank = {(e.back, e.frm) for e in index.into[ref("sound-bank", 240)]}
    assert on_bank == ({("Sequences", ref("sequence", 240, i)) for i in (0, 1)}
                       | {("Samples", ref("sample", 240, v.index)) for v in vab.vags})
    assert [e.to for e in index.out[ref("sound-bank", 240)]] == [ref("resource", 240)]


# -- cards ------------------------------------------------------------------

def test_a_movie_card_refuses_a_bromide_and_a_movie_the_game_lacks(tmp_path, monkeypatch):
    model = _model(tmp_path, names=SimpleNamespace(movie=lambda n: None))
    monkeypatch.setattr(media, "_end_frames", lambda m: [0] * ev.MOVIE_COUNT)
    with pytest.raises(LookupError, match="bromide 0"):
        media.movie_card(model, ref("movie", ev.BROMIDE_FIRST))
    with pytest.raises(LookupError, match="no movie 3"):
        media.movie_card(model, ref("movie", 3))
    with pytest.raises(LookupError, match="numbered 0 to"):
        media.movie_card(model, ref("movie", 200))


def test_a_movie_whose_file_is_on_the_other_disc_says_so(tmp_path, monkeypatch):
    model = _model(tmp_path, names=SimpleNamespace(movie=lambda n: None))
    frames = [700] * ev.MOVIE_COUNT
    monkeypatch.setattr(media, "_end_frames", lambda m: frames)
    body = media.movie_card(model, ref("movie", ev.DISC2_FIRST + 1))
    assert body.title == "movie 37" and body.picture is None
    assert ("Disc", "disc 2") in body.facts and "not on this one" in body.note
    assert dict(body.extended)["Frames played"].startswith("0 to 695")


def test_a_disc_file_card_is_its_name_and_says_how_it_is_numbered(tmp_path):
    model = _model(tmp_path, files=["B.DAT", "A.DAT"], program="SLUS_999.99")
    body = media.disc_file_card(model, ref("disc-file", 1))
    assert isinstance(body, CardBody) and body.title == "B.DAT"
    assert "by name, from 0: file 2 of 2" in dict(body.extended)["Numbered by"]
    assert media.disc_file_title(model, ref("disc-file", 0)) == "A.DAT"
    assert media.disc_file_title(model, ref("disc-file", 2)) is None
    with pytest.raises(LookupError, match="2 files"):
        media.disc_file_card(model, ref("disc-file", 2))


def test_a_sequence_and_a_sample_card(tmp_path, monkeypatch):
    vab = _bank(ONE)
    bank = SimpleNamespace(resource=240, seqs=[_looped()], vab=vab)
    monkeypatch.setattr(media, "_banks", lambda m: {240: bank})
    model = _model(tmp_path, names=SimpleNamespace(binary=None))
    seq = media.sequence_card(model, ref("sequence", 240, 0))
    assert "loop for ever" in dict(seq.facts)["Length"]
    with pytest.raises(LookupError, match="has 1 sequence$"):
        media.sequence_card(model, ref("sequence", 240, 1))
    i = vab.vags[0].index
    sample = media.sample_card(model, ref("sample", 240, i))
    assert dict(sample.facts)["Rate"].endswith("Hz")
    with pytest.raises(LookupError, match="no sample 99"):
        media.sample_card(model, ref("sample", 240, 99))
    with pytest.raises(LookupError, match="not a sound bank"):
        media.sound_bank_card(model, ref("sound-bank", 241))


def test_a_cd_track_card_says_why_a_disc_has_none(tmp_path, monkeypatch):
    model = _model(tmp_path)
    monkeypatch.setattr(media, "_cd_tracks", lambda m: ([], "made-up reason"))
    with pytest.raises(LookupError, match="made-up reason"):
        media.cd_track_card(model, ref("cd-track", 2))


# -- the tabs: their homes claim their rows, and a row names its thing ------------

def test_the_tabs_claim_their_rows(tmp_path):
    ctx = SimpleNamespace(program=US, files=("A.DAT", "_B004.STR"))
    assert DiscFilesProvider.holds(("_B004.STR", None, None), ref("disc-file", 1), ctx)
    assert not DiscFilesProvider.holds(("A.DAT", None, None), ref("disc-file", 1), ctx)
    assert not DiscFilesProvider.holds(("A.DAT", None, None), ref("disc-file", 9), ctx)
    assert ResourcesProvider.holds(SimpleNamespace(index=21), ref("resource", 21), ctx)
    assert MoviesProvider.holds(("_B004.STR", None), ref("movie", 4), ctx)
    assert not MoviesProvider.holds(("_B004.STR", None), ref("movie", 4),
                                    SimpleNamespace(program="SLUS_999.99"))
    top = Shown(Picture(586 + 2, 0, 1, 0, 320, 256, 1, 320, 0, True), 0, "", "", "")
    assert ScreensProvider.holds(top, ref("image", 588, 0), ctx)
    assert not ScreensProvider.holds(top, ref("image", 588, 1), ctx)
    assert not ScreensProvider.holds(top, ref("bromide", 2), ctx)
    assert BromidesProvider.holds(2, ref("bromide", 2), ctx)
    assert not BromidesProvider.holds(2, ref("bromide", 3), ctx)
    bank = SimpleNamespace(resource=232)
    assert SoundBanksProvider.holds(SoundItem("vag", bank, 3), ref("sample", 232, 3), ctx)
    assert not SoundBanksProvider.holds(SoundItem("seq", bank, 3), ref("sample", 232, 3), ctx)


def test_a_resource_names_the_tabs_that_show_it():
    from viewer_tabs.tab_providers import PROVIDER_CLASSES
    keys = {cls.key for cls in PROVIDER_CLASSES}
    assert {t for tabs in ResourcesProvider.TABS.values() for t in tabs} <= keys
    assert ResourcesProvider.TABS["scripts"] == ("dialogue", "story-flags")
    assert ResourcesProvider.TABS["party-sheets"] == ("sprites",)


def test_a_sound_row_names_the_thing_it_is(tmp_path):
    ctx = SimpleNamespace(files=("_AUDIO.XA",))
    bank = SimpleNamespace(resource=232)
    assert SoundBanksProvider._ref(SoundItem("bank", bank), ctx) == ref("sound-bank", 232)
    assert SoundBanksProvider._ref(SoundItem("vag", bank, 3), ctx) == ref("sample", 232, 3)
    assert SoundBanksProvider._ref(SoundItem("seq", bank, 1), ctx) == ref("sequence", 232, 1)
    assert SoundBanksProvider._ref(SoundItem("file", tmp_path / "_AUDIO.XA"), ctx) == ref("disc-file", 0)
