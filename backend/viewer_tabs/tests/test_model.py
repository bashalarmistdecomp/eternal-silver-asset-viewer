"""The model's parts and their lifetime — made-up discs, no game data.

What this CAN catch: two callers that ask for a part at once (the links'
warm-up and a click on Maps) each reading it and keeping a copy of their
own; a dump replaced (re-extracted) still answered from what was read of
it before, through its model, a model that reads its parts through it
(its twin), its names or its voices' file; another disc's kept reading
dropped with it.

A links domain registered `kept` read again for a disc whose twin made
its edges already, or a domain not registered so made once for twins (its
edges are the disc's own) is caught too, and an index of chosen sources
(a test's) answered from edges made before.

Names that could not be read are caught saying so: the decoders not
knowing the program, a file of theirs missing, or what reading them
raised, never "missing" for a file that is there.

What it CANNOT catch: whether every place that keeps a disc's reading is
known to `forget` (a new cache would have to be added there), or whether a
domain registered `kept` reads the program and LUNADATA.FIL alone.
"""

import threading
import time
from types import SimpleNamespace

from viewer_tabs import field_view
from viewer_tabs.model import GameModel, forget
from viewer_tabs.names import GameNames
from viewer_tabs.voice_audio import VoiceFile


def test_two_callers_at_once_read_the_field_once(monkeypatch):
    built = []

    class SlowField:
        def __init__(self, names):
            time.sleep(0.05)            # long enough for the other caller to arrive
            built.append(self)

    monkeypatch.setattr(field_view, "FieldMaps", SlowField)
    monkeypatch.setattr(GameNames, "for_ctx", classmethod(lambda cls, ctx: object()))
    model = GameModel(SimpleNamespace(data_dir="/made/up"))
    start = threading.Barrier(3)
    got = []

    def ask():
        start.wait()
        got.append(model.field)

    threads = [threading.Thread(target=ask) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(built) == 1
    assert all(g is built[0] for g in got) and model.field is built[0]


def test_a_part_set_by_hand_is_the_part():
    model = GameModel(SimpleNamespace(data_dir="/made/up"))
    model.__dict__["names"] = None
    assert model.names is None          # None is a reading, not "not read yet"


def _models(monkeypatch, tmp_path):
    a, b, c = (GameModel(SimpleNamespace(data_dir=str(tmp_path / n))) for n in "abc")
    b.__dict__["twin"] = a              # b's parts are a's
    monkeypatch.setattr(GameModel, "_cache", {tmp_path / "a": a, tmp_path / "b": b,
                                              tmp_path / "c": c})
    monkeypatch.setattr(GameModel, "_twins", {("made-up", "a"): a, ("made-up", "c"): c})
    monkeypatch.setattr(GameNames, "_cache", {
        (tmp_path / "a" / "EXE", tmp_path / "a" / "LUNADATA.FIL"): "a's names",
        (tmp_path / "c" / "EXE", tmp_path / "c" / "LUNADATA.FIL"): "c's names"})
    monkeypatch.setattr(GameNames, "_errors", {
        (tmp_path / "a" / "EXE", tmp_path / "a" / "LUNADATA.FIL"): "a's error",
        (tmp_path / "c" / "EXE", tmp_path / "c" / "LUNADATA.FIL"): "c's error"})
    monkeypatch.setattr(VoiceFile, "_cache", {tmp_path / "a": "a's voices",
                                              tmp_path / "c": "c's voices"})
    return a, b, c


def test_forgetting_a_dump_drops_its_reading_and_its_twins(monkeypatch, tmp_path):
    a, b, c = _models(monkeypatch, tmp_path)
    forget(tmp_path / "a")
    assert list(GameModel._cache.values()) == [c]
    assert list(GameModel._twins.values()) == [c]
    assert list(GameNames._cache.values()) == ["c's names"]
    assert list(GameNames._errors.values()) == ["c's error"]
    assert list(VoiceFile._cache.values()) == ["c's voices"]
    again = GameModel.for_ctx(SimpleNamespace(data_dir=str(tmp_path / "a")))
    assert again is not a


def _disc(tmp_path, program="SLUS_006.28"):
    return SimpleNamespace(program=program, data_dir=str(tmp_path), exe_path=tmp_path / "EXE",
                           path=lambda name: tmp_path / name)


def test_names_that_could_not_be_read_say_why(monkeypatch, tmp_path):
    monkeypatch.setattr(GameNames, "_cache", {})
    monkeypatch.setattr(GameNames, "_errors", {})
    monkeypatch.setattr(GameModel, "_twins", {})
    ctx = _disc(tmp_path)
    (tmp_path / "LUNADATA.FIL").write_bytes(bytes(2048))
    assert GameNames.for_ctx(ctx) is None
    assert GameNames.why_none(ctx) == "the program file is missing"
    (tmp_path / "EXE").write_bytes(b"not a program")        # there, but not one
    assert GameNames.for_ctx(ctx) is None
    why = GameNames.why_none(ctx)
    assert why.startswith("they could not be read: ") and "missing" not in why, why
    model = GameModel(ctx)
    try:
        model.need_names()
    except LookupError as ex:
        assert str(ex) == f"no names for SLUS_006.28: {why}"
    else:
        raise AssertionError("names read from a made-up program")
    from viewer_tabs.tab_providers import CharactersProvider, ResourcesProvider
    for tab in (CharactersProvider(), ResourcesProvider()):
        [(said, _item)] = tab.get_items(None, None, ctx, None)
        assert said.endswith(f": {why}."), said
    assert GameNames.why_none(_disc(tmp_path, "SLUS_999.99")) == \
        "the decoders do not know SLUS_999.99"
    monkeypatch.setitem(GameNames._cache, (tmp_path / "EXE", tmp_path / "LUNADATA.FIL"), "read")
    assert GameNames.why_none(ctx) == ""


def test_a_dump_is_known_however_its_path_is_spelled(monkeypatch, tmp_path):
    _models(monkeypatch, tmp_path)
    forget(tmp_path / "c" / ".." / "a")
    assert len(GameModel._cache) == 1 and len(VoiceFile._cache) == 1


def test_a_kept_domain_links_once_for_twin_discs(monkeypatch, tmp_path):
    from viewer_tabs import links
    from viewer_tabs.links import Edge
    from viewer_tabs.refs import ref
    a, b, c = _models(monkeypatch, tmp_path)
    made = []

    def shared(model):
        made.append(("shared", model))
        yield Edge(ref("map", 1), ref("map", 2), "To", "From")

    def own(model):
        made.append(("own", model))
        yield Edge(ref("map", 3), ref("map", 4), "To", "From")

    monkeypatch.setattr(links, "_EDGES", [])
    monkeypatch.setattr(links, "_KEPT", set())
    links.edges(kept=True)(shared)
    links.edges(own)
    for model in (a, b, c):
        index = links.LinkIndex(model)
        assert [e.to for e in index.out[ref("map", 1)]] == [ref("map", 2)]
        assert [e.to for e in index.out[ref("map", 3)]] == [ref("map", 4)]
    assert [m for kind, m in made if kind == "shared"] == [a, c]      # b's are a's
    assert [m for kind, m in made if kind == "own"] == [a, b, c]
    links.LinkIndex(b, sources=[shared])
    assert made[-1] == ("shared", b)                                  # made afresh
