"""A tab's first read, all or none (viewer_tabs.tab_providers), on made-up
tables: the readers are stood in for, no game data.

What this CAN catch: a tab that keeps half of a read that failed (every
face under "No character", no atlas; dialogue with no scripts), one that
says nothing of why, or one that never reads again after a failure; a
map that cannot be played not saying why.

What it CANNOT catch: whether a real disc's tables read (the tests on a
disc do).
"""

from types import SimpleNamespace

from PIL import Image

from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
from decoders.plugins.SLUS_006_28.formats import message_window as mw
from decoders.plugins.SLUS_006_28.formats import system_dat as sd
from decoders.plugins.SLUS_006_28.formats import system_strings as ss
from viewer_tabs import system_font, whose
from viewer_tabs import tab_providers as tp

NAMES = SimpleNamespace(binary=SimpleNamespace(code=b""), read_resource=lambda n: b"",
                        character=lambda i: f"C{i}")


class _Fails:
    """A stand-in that raises while `failing`, else answers `then`."""

    def __init__(self, then):
        self.failing, self.then = True, then

    def __call__(self, *args, **kwargs):
        if self.failing:
            raise RuntimeError("a made-up table that cannot be read")
        return self.then


def _names(monkeypatch):
    monkeypatch.setattr(tp.GameNames, "for_ctx", classmethod(lambda cls, ctx: NAMES))


def test_portraits_are_read_whole_or_say_why_and_read_again(monkeypatch):
    _names(monkeypatch)
    monkeypatch.setattr(sd, "palette_rows", lambda raw: {fb.CLUT_ROW: [0] * 16})
    monkeypatch.setattr(sd, "colours", lambda row: None)
    block = SimpleNamespace(valid=True, images=[bytes(fb.SIDE * fb.SIDE)] * 5, faces=[1] * 5)
    monkeypatch.setattr(fb, "parse", lambda raw: block)
    monkeypatch.setattr(fb, "image", lambda px, colours: Image.new("RGBA", (fb.SIDE, fb.SIDE)))
    read = _Fails({})
    monkeypatch.setattr(whose, "read", read)
    tab = tp.PortraitsProvider()
    [(said, item)] = tab.get_items(None, None, None, None)
    assert item is None and said.endswith("RuntimeError: a made-up table that cannot be read")
    assert tab._faces == {} and tab._scenes == [] and tab._atlas is None
    read.failing = False
    assert tab.get_items(None, None, None, None)[0][1] is not None
    assert tab._error == "" and len(tab._faces) == fb.FACES and tab._atlas is not None


def test_dialogue_is_read_whole_or_says_why_and_reads_again(monkeypatch):
    _names(monkeypatch)
    for module, name in ((ss, "block"), (ss, "words_of"), (ss, "exe_char_table"),
                         (es, "command_count"), (mw, "layout_of"), (mw, "Font"),
                         (sd, "colours")):
        monkeypatch.setattr(module, name, lambda *a, **k: None)
    monkeypatch.setattr(sd, "palette_rows", lambda raw: {sd.TEXT_ROW: [], fb.CLUT_ROW: []})
    monkeypatch.setattr(system_font, "find", lambda: None)
    resources = _Fails({5: 300, 6: 300})
    monkeypatch.setattr(es, "script_resources", resources)
    tab = tp.DialogueProvider()
    monkeypatch.setattr(tab, "_messages", lambda res, drawn=False: [])
    [(said, item)] = tab.get_items(None, None, None, None)
    assert item is None and said.endswith("RuntimeError: a made-up table that cannot be read")
    assert tab._env is None and tab._scripts == []
    resources.failing = False
    assert tab._ensure(None) and tab._error == "" and tab._scripts == [(300, [5, 6])]


def test_sound_banks_that_could_not_be_read_say_why_and_are_read_again(monkeypatch):
    from decoders.plugins.SLUS_006_28.formats import resource_table, sound_banks
    from decoders.psx.analysis import exe_loader
    load = _Fails(None)
    monkeypatch.setattr(exe_loader, "load_exe", load)
    monkeypatch.setattr(resource_table, "load_resource_table", lambda binary: [])
    bank = SimpleNamespace(resource=232, is_sfx=False, seqs=[], vags=[])
    monkeypatch.setattr(sound_banks, "find_banks", lambda path, resources: [bank])
    ctx = SimpleNamespace(exe_path="EXE", path=lambda name: name)
    tab = tp.SoundBanksProvider()
    [(said, item)] = tab.get_items(None, None, ctx, None)
    assert item is None and said == ("The sound banks could not be read: "
                                     "RuntimeError: a made-up table that cannot be read")
    assert tab._banks is None
    load.failing = False
    tab._ensure_loaded(ctx)
    assert tab._banks == [bank] and tab._error == ""


def test_a_map_that_cannot_be_played_says_why(monkeypatch, capsys):
    _names(monkeypatch)
    tab = tp.MapsProvider()
    monkeypatch.setattr(tab, "_field_maps", _Fails(None))
    got = tab.on_select(SimpleNamespace(map_id=5, resource=1), None, None, None)
    assert got.info == "Could not play map 5: RuntimeError: a made-up table that cannot be read"
    assert "RuntimeError" in capsys.readouterr().err        # and the log has where
