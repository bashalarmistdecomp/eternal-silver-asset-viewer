"""What a fight plays (viewer_tabs.battle_music) — made-up object sets,
scripts and names, no game data.

What this CAN catch: a map monster (kind 5 or 6 with a fight number)
counted for every map entered with its set and nothing else counted (an
object of another kind, one with no fight, one not made), a BATTLE
command's encounter read through its row, a silent fight (music 0) left
out, the story's scripts before the map monsters before the debug room,
notes put together per BGM, the win's jingle by the boss class, and no
music at all for a fight nothing starts.

What it CANNOT catch: whether those are the rules of MapObjectTouchRun
(0x8007ACD8), ScriptCommandMapBtlRun (0x8005DFF0) and BtlRun
(0x80027434): both sides of every assertion were written together. See
decoders/testing.py.
"""

import struct
from types import SimpleNamespace

from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import field_objects as fo
from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
from viewer_tabs import battle_music as bm


def _block(*defs) -> bytes:
    """Definitions (index, kind, sprite data, fight) in a block of 0x80."""
    block = bytearray(fo.DEFINITION_SIZE * fo.DEFINITION_COUNT)
    for i, kind, sprite, event in defs:
        at = i * fo.DEFINITION_SIZE
        block[at] = kind - 1
        block[at + 1] = sprite
        block[at + 0xB] = event
    return bytes(block)


def _battle(label, row, music) -> bytes:
    return bytes([es.BATTLE, 0]) + struct.pack("<H", label) + bytes([row, 0, music, 0xFF])


def _fm():
    sets = {
        1: _block((0, 5, 0x20, 0x10), (1, 6, 0x21, 0x11), (2, 4, 0x22, 0x12),
                  (3, 5, 0x20, 0), (4, 5, 0, 0x13)),
        2: _block((0, 5, 0x20, 0x10)),
    }
    scripts = {
        0x0B: _battle(1, 1, 3) + _battle(2, 2, 0),      # rows 1, 2 -> 0x11, 0x14
        0x30: _battle(1, 3, 3),                         # row 3 -> 0x10
    }
    entered = {0x15: {1: []}, 0x16: {2: [], 0: []}, 0x17: {}}

    def script(sid):
        buf = scripts[sid]
        cmds = {o: es.Command(offset=o, id=es.BATTLE, end=o + 8) for o in range(0, len(buf), 8)}
        return buf, cmds, {}
    return SimpleNamespace(
        maps={0x15: None, 0x16: None, 0x17: None},
        set_for=lambda mid: (None, entered[mid]),
        set_resources={1: "set 1", 2: "set 2"},
        read=lambda res: sets[int(res.split()[1])],
        script_resources={0x0B: None, 0x30: None},
        script=script, image=b"",
        script_maps={0x0B: {0x15}}, debug_scripts={0x30})


NAMES = SimpleNamespace(map_name=lambda m: {0x15: "Town", 0x16: "Field"}.get(m),
                        bgm=lambda n: {1: "Fight", 3: "Story fight", 0x3D: "Win",
                                       0x3E: "Boss win"}.get(n))


def _fights(monkeypatch):
    monkeypatch.setattr(mos, "definition_block", lambda raw: raw)
    monkeypatch.setattr(es, "encounter_row", lambda image, row: {1: 0x11, 2: 0x14, 3: 0x10}[row])
    fm = _fm()
    return fm, bm.fights(fm)


def test_the_starters(monkeypatch):
    _, f = _fights(monkeypatch)
    assert f.monsters == {0x10: {0x15, 0x16}, 0x11: {0x15}}
    assert f.scripts == {0x11: [(0x0B, 3)], 0x14: [(0x0B, 0)], 0x10: [(0x30, 3)]}


def test_a_script_that_cannot_be_read_is_passed_over(monkeypatch):
    fm, f = _fights(monkeypatch)
    read = fm.script

    def script(sid):
        if sid == 0x20:
            raise ValueError("a made-up script that cannot be read")
        return read(sid)
    fm.script, fm.script_resources = script, {0x0B: None, 0x20: None, 0x30: None}
    assert bm.fights(fm) == f


def test_what_each_fight_plays(monkeypatch):
    fm, f = _fights(monkeypatch)
    got = {eid: [(s["bgm"], s["note"]) for s in bm.songs(fm, NAMES, f, eid)]
           for eid in (0x10, 0x11, 0x14, 0x12, 0xF0)}
    assert got[0x11] == [(3, "the fight, started by script 11's battle command (0x2B) (Town)"),
                         (1, "the fight, started by map monsters on Town"),
                         (0x3D, "the win (BtlRun (0x80027434))")]
    assert got[0x10] == [(1, "the fight, started by map monsters on Field, Town"),
                         (3, "the fight, started by the debug room's fights"),
                         (0x3D, "the win (BtlRun (0x80027434))")]
    assert got[0x14] == got[0x12] == got[0xF0] == []    # silent; a script label; nothing


def test_a_boss_wins_to_its_own_jingle(monkeypatch):
    fm, f = _fights(monkeypatch)
    f.monsters[0xEB] = {0x15}
    assert [s["title"] for s in bm.songs(fm, NAMES, f, 0xEB)] == ["Fight", "Boss win"]
