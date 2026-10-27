"""A disc's index in the library (viewer_server.index) — made-up discs,
tabs and links, no game data.

What this CAN catch: a game listed from its discs' indexes other than it
is listed from the discs (rows, Fan rows, tags, versions); an item the
index lists but the disc no longer gives as listed (a list in another
order, an item whose identity is not the one the index holds) shown
anyway instead of the tab being read from the disc; an index read after
the disc or the code changed (a stale stamp), and the indexer not making
it again; a damaged, half-written or tampered file read instead of
ignored; the links read back other than they were written, in content or
order; a plain item of a tab that takes it unlisted read again; two
backends making one index at once, or none making it after one stopped
mid-way (its lock left behind); an index made of a dump while it is
replaced; an index that could not be written said to be made; links a
domain failed to make kept for good.

What it CANNOT catch: whether a real disc's index matches the disc (the
lead's snapshot of every tab, with and without the index, does).
"""

import io
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from decoders.psx.gamedb.database import InstalledGame
from viewer_server import index as library_index
from viewer_server import session as session_module
from viewer_server.blobs import BlobStore
from viewer_server.index import DiscIndex, Indexer, Kept, build, stamp_of
from viewer_server.session import GameSession
from viewer_tabs import links
from viewer_tabs import tab_providers
from viewer_tabs.context import DiscContext
from viewer_tabs.identity import of_file
from viewer_tabs.refs import ref
from viewer_tabs.tab_providers import SelectResult


class _Things:
    """A made-up tab: a row per file of the dump whose name starts with
    T, its item the file (a live object: read again when selected)."""
    name = "Things"
    key = "things"
    supports_zoom = supports_grid = supports_layers = False
    #: the order the tab lists its files in: flipped, a list unlike the index's
    backwards = False
    #: swapped, two files' items under each other's labels
    swapped = False

    def __init__(self):
        self.view = "Names"
        self.listed = 0

    def get_views(self):
        return ["Names", "Sizes"]

    def get_items(self, cache, archive, ctx, selected):
        self.listed += 1
        files = sorted((p for p in Path(ctx.data_dir).iterdir() if p.name.startswith("T")),
                       reverse=_Things.backwards)
        labels = [p.name if self.view == "Names" else f"{p.name}  {p.stat().st_size} bytes"
                  for p in files]
        if _Things.swapped:
            files = files[::-1]
        return list(zip(labels, files)) or [("No things", None)]

    def item_identity(self, label, path, ctx):
        return of_file(path.name, path)

    def fan_row(self, label, path, ctx):
        return {"title": path.stem.lower()}

    def get_layer_options(self):
        return []

    def on_select(self, path, cache, archive, ctx):
        return SelectResult(info=f"{path.name}: {path.read_bytes()!r} ({self.view})")


class _Words:
    """A made-up tab whose items are plain data and whose on_select reads
    what it needs itself: the index holds its items."""
    name = "Words"
    key = "words"
    supports_zoom = supports_grid = supports_layers = False
    selects_unlisted = True

    def __init__(self):
        self.listed = 0

    def get_items(self, cache, archive, ctx, selected):
        self.listed += 1
        return [(f"word {n}", ("word", n, f"w{n}")) for n in range(3)]

    def item_identity(self, label, item, ctx):
        from viewer_tabs.identity import of_bytes
        return of_bytes(f"word {item[1]}", item[2].encode())

    def get_layer_options(self):
        return []

    def on_select(self, item, cache, archive, ctx):
        return SelectResult(info=f"{item[2]} of {Path(ctx.data_dir).name}")


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A library of two made-up discs of one made-up program, the tabs
    the two made-up ones, the font none."""
    from viewer_tabs import system_font
    monkeypatch.setattr(system_font, "find", lambda: None)
    monkeypatch.setattr(tab_providers, "providers_for", lambda ctx: [_Things(), _Words()])
    monkeypatch.setattr(session_module, "providers_for", lambda ctx: [_Things(), _Words()])
    monkeypatch.setattr(session_module, "PROVIDER_CLASSES", [_Things, _Words])
    monkeypatch.setattr(_Things, "backwards", False)
    monkeypatch.setattr(_Things, "swapped", False)
    monkeypatch.delenv(library_index.OFF_ENV, raising=False)
    games = []
    for disc, files in (("SLUS_999.98", {"T1.BIN": b"one", "T2.BIN": b"two!", "X.BIN": b"x"}),
                        ("SLUS_999.99", {"T1.BIN": b"one", "T2.BIN": b"2", "T3.BIN": b"three"})):
        raw = tmp_path / "SLUS_999.98" / "raw" / disc
        raw.mkdir(parents=True)
        for name, data in files.items():
            (raw / name).write_bytes(data)
        games.append(InstalledGame(disc_id=disc, title="made-up", region="USA", path=raw,
                                   has_lunadata=False, program="SLUS_999.98"))
    yield games
    for g in games:
        library_index.forget(g.path)


def _ctx(game):
    return DiscContext.for_game(game)


def _session(games):
    s = GameSession("made-up", "Made-up", games, BlobStore())
    s.start()
    return s


def _everything(s):
    """Every tab's every view's rows, and every row's page, as the app
    gets them (result ids dropped)."""
    out = {}
    for t in s.describe()["tabs"]:
        for view in t["views"] or [None]:
            rows = s.items(t["index"], view)
            pages = [s.select(t["index"], rows["view"], i) for i in range(len(rows["rows"]))]
            for p in pages:
                p.pop("id")
            out[f"{t['key']}/{view}"] = (rows, pages)
    return out


def test_a_game_listed_from_its_indexes_is_the_game_read_from_its_discs(library):
    cold = _everything(_session(library))
    for game in library:
        assert build(_ctx(game))
    warm = _session(library)
    assert all(m.index.ready() for m in warm.members)
    assert _everything(warm) == cold
    # every list came from the indexes; a Things page read its disc's list
    # again once, a Words page read nothing
    words = [m.providers["words"] for m in warm.members]
    assert [p.listed for p in words] == [0, 0]
    assert [m.providers["things"].listed for m in warm.members] == [2, 2]


def test_a_row_is_its_entry_in_the_index(library):
    for game in library:
        build(_ctx(game))
    index = DiscIndex(_ctx(library[0]))
    listed = index.listed("things", "Sizes")
    assert [label for label, _kept, _ident in listed] == ["T1.BIN  3 bytes", "T2.BIN  4 bytes"]
    label, kept, ident = listed[1]
    assert isinstance(kept, Kept) and kept.row["title"] == "T2.BIN" and kept.fan == {"title": "t2"}
    assert (ident.key, ident.size) == ("T2.BIN", 4)
    assert ident.digest() == of_file("T2.BIN", Path(library[0].path) / "T2.BIN").digest()
    assert [k.item for _label, k, _ident in index.listed("words", None)] == [
        ("word", 0, "w0"), ("word", 1, "w1"), ("word", 2, "w2")]


def test_a_list_unlike_the_index_is_read_from_the_discs(library):
    for game in library:
        build(_ctx(game))
    s = _session(library)
    rows = s.items(0, "Names")["rows"]
    assert [r["label"] for r in rows] == ["T1.BIN", "T2.BIN", "T3.BIN"]
    _Things.backwards = True                    # what a stale index cannot know
    page = s.select(0, "Names", 0)
    assert "things" in s._unkept
    assert page["label"] == "T3.BIN" and page["info"].startswith("T3.BIN: b'three'")
    assert [r["label"] for r in s.items(0, "Names")["rows"]] == ["T3.BIN", "T2.BIN", "T1.BIN"]


def test_an_item_whose_identity_is_not_the_indexs_is_read_from_the_discs(library):
    for game in library:
        build(_ctx(game))
    s = _session(library)
    s.items(0, "Names")
    _Things.swapped = True                      # the same labels, other files under them
    page = s.select(0, "Names", 0)
    assert "things" in s._unkept
    # read from the discs, the row is the file the disc lists first now
    assert page["label"] == "T1.BIN" and page["info"].startswith("T3.BIN")


def test_a_stale_index_is_not_read_and_is_made_again(library):
    game = library[0]
    assert build(_ctx(game))
    assert DiscIndex(_ctx(game)).ready()
    before = stamp_of(_ctx(game))
    later = time.time() + 5
    (Path(game.path) / "T2.BIN").write_bytes(b"other")
    os.utime(Path(game.path) / "T2.BIN", (later, later))
    assert stamp_of(_ctx(game)) != before
    assert not DiscIndex(_ctx(game)).ready()
    assert DiscIndex(_ctx(game)).listed("things", "Names") is None
    indexer = Indexer()
    library_index.forget(game.path)
    assert indexer.status(game)["state"] == "stale"
    assert indexer.build(game)
    assert indexer.status(game)["state"] == "ready"
    listed = DiscIndex(_ctx(game)).listed("things", "Sizes")
    assert listed[1][0] == "T2.BIN  5 bytes"


def test_a_change_of_code_makes_the_index_stale(library, monkeypatch):
    game = library[0]
    build(_ctx(game))
    monkeypatch.setattr(library_index, "_code", "another viewer's code")
    assert not DiscIndex(_ctx(game)).ready()


def test_a_damaged_index_is_ignored(library):
    game = library[0]
    build(_ctx(game))
    path = library_index.config.index_file(game.path)
    whole = path.read_bytes()
    for damaged in (b"", b"not a zip at all", whole[: len(whole) // 2]):
        path.write_bytes(damaged)
        index = DiscIndex(_ctx(game))
        assert not index.ready()
        assert index.listed("things", "Names") is None
        assert index.links(object()) is None
    # one part's bytes changed (its checksum fails): that tab is read from
    # the disc, the rest from the index
    with zipfile.ZipFile(io.BytesIO(whole)) as zf:
        info = zf.getinfo("tabs/things.json")
    at = info.header_offset + 30 + len(info.filename) + len(info.extra) + info.compress_size // 2
    path.write_bytes(whole[:at] + bytes([whole[at] ^ 0xFF]) + whole[at + 1:])
    index = DiscIndex(_ctx(game))
    assert index.ready()
    assert index.listed("things", "Names") is None
    assert index.listed("words", None) is not None
    # a whole file with one tab unreadable: that tab is read from the disc
    path.write_bytes(whole)
    with zipfile.ZipFile(path) as zf:
        parts = {n: zf.read(n) for n in zf.namelist()}
    part = json.loads(parts["tabs/things.json"])
    part["views"]["Names"][0][0].pop("label")
    parts["tabs/things.json"] = json.dumps(part).encode()
    library_index._write(path, parts)
    index = DiscIndex(_ctx(game))
    assert index.ready()
    assert index.listed("things", "Names") is None
    assert index.listed("things", "Sizes") is not None
    assert index.listed("words", None) is not None


def test_an_index_never_holds_more_than_its_own(library):
    game = library[0]
    build(_ctx(game))
    path = library_index.config.index_file(game.path)
    with zipfile.ZipFile(path) as zf:
        parts = {n: zf.read(n) for n in zf.namelist()}
    part = json.loads(parts["tabs/words.json"])
    part["views"][""][0][3] = {"not": "plain data"}
    parts["tabs/words.json"] = json.dumps(part).encode()
    library_index._write(path, parts)
    assert DiscIndex(_ctx(game)).listed("words", None) is None


def _lock(path, pid: int):
    """The lock another backend, process `pid`, holds on the index at `path`."""
    lock = library_index._lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(pid))


def _gone() -> int:
    """The pid of a process that has ended."""
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()
    return ended.pid


def test_one_backend_makes_an_index_at_a_time(library):
    game = library[0]
    path = library_index.config.index_file(game.path)
    _lock(path, os.getppid())                   # another backend is making it
    indexer = Indexer()
    assert indexer.status(game)["state"] == "making"
    assert not indexer.build(game)
    assert not path.exists()
    old = time.time() - library_index.LOCK_STALE - 1
    os.utime(library_index._lock_path(path), (old, old))    # and stopped
    assert indexer.build(game)
    assert not library_index._lock_path(path).exists()
    assert not [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.parametrize("pid", [_gone, os.getpid])
def test_a_lock_whose_backend_is_gone_is_taken_over(library, pid):
    # The app closed mid-index (the backend exits at once): its lock stays,
    # fresh, naming a process that is gone, or one whose pid is this one's.
    game = library[0]
    path = library_index.config.index_file(game.path)
    _lock(path, pid())
    indexer = Indexer()
    assert indexer.status(game)["state"] == "missing"
    assert indexer.build(game)
    assert indexer.status(game)["state"] == "ready"


def test_a_disc_another_backend_was_making_is_made_when_it_stops(library, monkeypatch):
    game = library[0]
    path = library_index.config.index_file(game.path)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _lock(path, other.pid)
        monkeypatch.setattr(library_index, "LOCK_POLL", 0.02)
        indexer = Indexer()
        monkeypatch.setattr(indexer, "_discs", lambda: [game])
        running = threading.Thread(target=indexer._run, args=(0,))
        running.start()
        time.sleep(0.2)
        assert running.is_alive() and not path.exists()     # waiting its turn
    finally:
        other.kill()
        other.wait()                                         # and it stopped
    running.join(10)
    assert not running.is_alive() and indexer.status(game)["state"] == "ready"


def test_a_dump_being_replaced_is_not_indexed(library):
    game, indexer = library[0], Indexer()
    with indexer.replacing(game.path):
        assert not indexer.build(game)
    assert not library_index.config.index_file(game.path).exists()
    assert indexer.build(game)


def test_an_index_being_made_stops_when_its_dump_is_replaced(library, monkeypatch):
    game, indexer = library[0], Indexer()
    started, built = threading.Event(), []
    listed = _Things.get_items

    def slow(self, *args):
        started.set()
        for _ in range(500):                 # until the dump is being replaced
            if indexer._replaced(game.path):
                break
            time.sleep(0.01)
        return listed(self, *args)

    monkeypatch.setattr(_Things, "get_items", slow)
    making = threading.Thread(target=lambda: built.append(indexer.build(game)))
    making.start()
    assert started.wait(5)
    with indexer.replacing(game.path):
        assert not indexer._making            # it stopped before its next tab
    making.join(5)
    assert built == [False] and not library_index.config.index_file(game.path).exists()


def _edges(model):
    m4, m7, s6 = ref("map", 4), ref("map", 7), ref("song", 6)
    return [links.Edge(m4, s6, "Music", "Played on", "the map's", "MadeUp (0x1)"),
            links.Edge(m7, s6, "Music", "Played on", "", "MadeUp (0x1)"),
            links.Edge(m4, m7, "Leads to", "Led to from", "a door", "MadeUp (0x2)"),
            links.Edge(ref("cell", 4, 1, 2), m4, "On", "Cells", "", "")]


class _Model:
    pass


def _fails(model):
    raise ZeroDivisionError("made-up failure")


def test_links_a_domain_failed_to_make_are_not_kept(library, monkeypatch, capsys):
    from viewer_tabs.model import forget
    game = library[0]
    path = library_index.config.index_file(game.path)

    def parts():
        with zipfile.ZipFile(path) as zf:
            return set(zf.namelist())

    monkeypatch.setattr(links, "_EDGES", [_edges, _fails])
    assert build(_ctx(game))
    assert "stamp.json" in parts() and "links.json" not in parts()
    err = capsys.readouterr().err
    assert "the links are not indexed" in err and "ZeroDivisionError: made-up failure" in err
    forget(game.path)
    monkeypatch.setattr(links, "_EDGES", [_edges])
    assert build(_ctx(game))
    assert {"links.json", "links.bin"} <= parts()
    forget(game.path)


def test_a_program_the_decoders_do_not_know_has_its_links_kept_and_nothing_said(library, capsys):
    from viewer_tabs.model import forget
    game = library[0]                       # SLUS_999.98: the decoders do not know it
    assert build(_ctx(game))
    with zipfile.ZipFile(library_index.config.index_file(game.path)) as zf:
        assert {"links.json", "links.bin"} <= set(zf.namelist())
    err = capsys.readouterr().err
    assert "the links are not indexed" not in err and "links: could not read" not in err, err
    forget(game.path)


def test_an_index_that_cannot_be_written_is_not_said_to_be(library, monkeypatch):
    game = library[0]
    path = library_index.config.index_file(game.path)

    def held(src, dst):
        raise PermissionError(13, "made-up: a reader has it open")

    indexer = Indexer()
    with monkeypatch.context() as patched:
        patched.setattr(library_index.time, "sleep", lambda s: None)
        patched.setattr(library_index.os, "replace", held)
        with pytest.raises(PermissionError):
            indexer.build(game)
        indexer.build_each([game])              # the background's: said on stderr
    assert not path.exists() and not list(path.parent.iterdir())
    assert indexer.status(game)["state"] == "missing"


def test_links_read_back_are_the_links_written():
    model = _Model()
    built = links.LinkIndex(model, sources=[_edges, lambda m: 1 / 0])
    model.__dict__["_link_index"] = built
    head, raw = library_index._links_part(model, "stamp")
    again = _Model()
    read = library_index._read_links(again, json.loads(head), raw)
    for way in ("out", "into"):
        assert list(getattr(read, way)) == list(getattr(built, way))
        assert {r: getattr(read, way)[r] for r in getattr(read, way)} == getattr(built, way)
    assert read.errors == built.errors and len(read.errors) == 1
    assert read.out.get(ref("map", 9), []) == []
    # what a link shows of a thing is what was kept of it
    assert links.title_of(again, ref("song", 6)) == links.title_of(model, ref("song", 6))
    assert links.groups(again, read, ref("map", 4)) == links.groups(model, built, ref("map", 4))
    with pytest.raises(ValueError):
        library_index._read_links(again, json.loads(head), raw[:-4])
    bad = json.loads(head)
    bad["refs"][0] = ["map", 4]
    with pytest.raises(Exception):
        library_index._read_links(again, bad, raw)


def test_a_disc_without_an_index_is_read_as_it_always_was(library, monkeypatch):
    monkeypatch.setenv(library_index.OFF_ENV, "1")
    s = _session(library)
    assert all(m.index is None for m in s.members)
    assert Indexer().status(library[0]) == {"state": "off"}
    assert not Indexer().build(library[0])
    assert s.items(0, "Names")["rows"][0]["label"] == "T1.BIN"
