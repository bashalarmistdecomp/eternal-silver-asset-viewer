"""What a fight plays: the music is the starter's, not the encounter's.

Every fight runs through MapBtlRun (0x8007AE58), which plays its seventh
argument (MusicPlay (0x80054F2C)) before BtlRun (0x80027434):

- A map monster, an object of kind 5 or 6 the party touches, runs the
  fight its definition's byte 0xB numbers: MapObjectTouchRun (0x8007ACD8)
  calls MapBtlRun(it, 0, 0, 0, 1, 1, 1), so BGM 1, always.
- A script's BATTLE command (0x2B, ScriptCommandMapBtlRun (0x8005DFF0))
  names its own in byte 6, the encounter through its row of
  g_ScriptMapBtlRows (0x800B366C). 0 is a silent fight.

The fight's end is BtlRun's: a win plays BGM 0x3E for an encounter of the
boss class (id 0xEB on), 0x3D for the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MONSTER_KINDS = (5, 6)
MONSTER_BGM = 1
BOSS_CLASS_FIRST = 0xEB
WIN_BGM, BOSS_WIN_BGM = 0x3D, 0x3E
#: Map names listed in a note before "and n more".
NAMED = 3


@dataclass
class Fights:
    """Encounter -> what starts it."""
    #: the maps whose map monsters run it
    monsters: dict[int, set[int]] = field(default_factory=dict)
    #: (script, the BATTLE command's music byte) of each command that runs it
    scripts: dict[int, list[tuple[int, int]]] = field(default_factory=dict)


def fights(fm) -> Fights:
    """Every starter on the disc: the object sets each map is entered with
    (field_view.FieldMaps.set_for), and every script's BATTLE commands."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
    out = Fights()
    blocks: dict[int, bytes] = {}
    for mid in fm.maps:
        for s in fm.set_for(mid)[1]:
            res = fm.set_resources.get(s) if s else None
            if not res:
                continue
            if s not in blocks:
                blocks[s] = mos.definition_block(fm.read(res))
            for d in fo.made_definitions(blocks[s]):
                if d.kind in MONSTER_KINDS and d.event:
                    out.monsters.setdefault(d.event, set()).add(mid)
    for sid in sorted(fm.script_resources):
        try:
            buf, cmds, _labels = fm.script(sid)
        except Exception:
            continue            # FieldMaps.errors says why
        for b in es.battles(buf, list(cmds.values())):
            if b["row"] < 1:
                continue
            enc = es.encounter_row(fm.image, b["row"])
            out.scripts.setdefault(enc, []).append((sid, b["music"]))
    return out


def _places(names, maps) -> str:
    """"A, B, C and 2 more", by name, the debug room's last."""
    from viewer_tabs.field_view import DEBUG_ROOM
    shown = sorted({names.map_name(m) or f"map {m}" for m in maps if m != DEBUG_ROOM})
    shown += sorted({names.map_name(m) or f"map {m}" for m in maps if m == DEBUG_ROOM}
                    - set(shown))
    more = len(shown) - NAMED
    return ", ".join(shown[:NAMED]) + (f" and {more} more" if more > 0 else "")


def songs(fm, names, f: Fights, eid: int) -> list[dict]:
    """The encounter's music, one entry per BGM: what starts it with that
    BGM (the story's scripts first, then the map monsters, then the debug
    room's list), and the win's jingle."""
    by: dict[int, list[str]] = {}
    debug: dict[int, list[str]] = {}
    for sid, bgm in f.scripts.get(eid, []):
        if not bgm:
            continue
        maps = fm.script_maps.get(sid, set())
        if sid in fm.debug_scripts:
            debug.setdefault(bgm, []).append("the debug room's fights")
        else:
            by.setdefault(bgm, []).append(
                f"script {sid}'s battle command (0x2B)" + (f" ({_places(names, maps)})" if maps else ""))
    if eid in f.monsters:
        by.setdefault(MONSTER_BGM, []).append(f"map monsters on {_places(names, f.monsters[eid])}")
    for bgm, notes in debug.items():
        by.setdefault(bgm, []).extend(notes)
    out = [{"bgm": bgm, "title": names.bgm(bgm) or f"BGM {bgm}",
            "note": "the fight, started by " + "; ".join(dict.fromkeys(notes))}
           for bgm, notes in by.items()]
    if out:
        win = BOSS_WIN_BGM if eid >= BOSS_CLASS_FIRST else WIN_BGM
        out.append({"bgm": win, "title": names.bgm(win) or f"BGM {win}",
                    "note": "the win (BtlRun (0x80027434)"
                    + (", boss class" if eid >= BOSS_CLASS_FIRST else "") + ")"})
    return out
