"""The world's links and cards (viewer_tabs.links.world) — made-up maps,
scripts and an object set, no game data.

What this CAN catch: an edge the domain should make missing or pointing
the wrong way (a map's place and script, an entrance's map, object set
and sound, a tile change's story flag, a place's visited flag, a
script's hand-overs and map changes, an object set's objects by kind,
the maps they stand on, the flags that hide them, a map monster's battle,
a chest's item, lock, own flag and label), a title or a card fact read
from the wrong part, a card for a thing that does not exist not saying
so, and the Maps, Sprites and Dialogue tabs not claiming the rows that
hold a thing.

What it CANNOT catch: whether the disc's rows are read right (the
decoders' own tests) or whether the code makes these links (the C:
MapChange (0x8005922C), MapObjectsInit (0x800655C8), MapObjectKind7Run
(0x80067F84) and the others each edge names).
"""

from types import SimpleNamespace

import pytest

from decoders.plugins.SLUS_006_28.formats import bg_change as bc
from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import field_objects as fo
from decoders.plugins.SLUS_006_28.records.areas import Area
from viewer_tabs import links
from viewer_tabs.links import world
from viewer_tabs.model import GameModel
from viewer_tabs.names import MapEntry
from viewer_tabs.refs import ref


class _Names:
    """Made-up names: places 1, 2 and 0x52, one song."""
    PLACES = {1: "Place A", 2: "Place B", 0x52: "Place C"}

    def location(self, n):
        return self.PLACES.get(n)

    def location_short(self, n):
        return None

    def bgm(self, n):
        return "Song X" if n == 3 else None

    def script_ids_for_resource(self, res):
        return [sid for sid, r in _SCRIPTS.items() if r == res]


_SCRIPTS = {5: 200, 6: 201}


def _area(mid, place, script, party_kind=1, bgm=3):
    raw = bytes([party_kind, 0, 0, 0, 0, 0, place, 0, script, 0, 0, 0, 0, 0, 0, bgm])
    return Area(map_id=mid, record=mid, party_kind=party_kind, tile_animation=0,
                palette_animation=0, location=place, script=script, effect=0, bgm=bgm, raw=raw)


def _definition(index, kind, event=0, story=0, facing=4, think=3):
    raw = bytearray(fo.DEFINITION_SIZE)
    raw[0], raw[1], raw[2], raw[6] = kind - 1, 0x20, story, facing
    raw[0xB], raw[0xC] = event, think
    block = bytearray(fo.STEP_LISTS_AT)
    block[index * fo.DEFINITION_SIZE:(index + 1) * fo.DEFINITION_SIZE] = raw
    return fo.definition(bytes(block), index)


def _script():
    """Script 5: a 0x5D to map 12 handing over to script 6, a 0x26 taking
    enter row 3, a 0x42 to script 6."""
    buf = bytearray(0x80)
    buf[0x10:0x17] = bytes([es.MAP_CHANGE, 0, 0, 0, 6, 0, 12])
    buf[0x30:0x35] = bytes([es.SCENE_JUMP, 0, 0, 0, 3])
    buf[0x50:0x55] = bytes([es.SCRIPT_JUMP, 0, 0, 0, 6])
    cmds = {o: es.Command(o, i, o + 0x12) for o, i in
            ((0x10, es.MAP_CHANGE), (0x30, es.SCENE_JUMP), (0x50, es.SCRIPT_JUMP))}
    return bytes(buf), cmds, {800: 0x60}


#: Map 10 (place A) leads to map 11 (place B) through its enter row 3,
#: with object set 7 and sound 13; map 12 (place C) is reached only by
#: script 5. Object set 7: entity 1 (hidden by a flag), map monster 2
#: (battle 46), trigger 3, chest 4 (item 18, locked), chest 5 (money),
#: chest 6 (a label).
_ROW = fo.enter_row(bytes([11, 7, 0, 13, 0, 9, 0, 9, 2, 3, 2]), "map 10's enter row 3")


def _model():
    maps = {10: MapEntry(10, 100, _area(10, 1, 5)), 11: MapEntry(11, 101, _area(11, 2, 5)),
            12: MapEntry(12, 102, _area(12, 0x52, 6, party_kind=2))}
    scripted = fo.enter_row(bytes([12, 0, 0, 0, 0, 9, 0, 9, 1, 1, 0]), "script 5")
    entries = {11: [_ROW], 12: [scripted]}

    def set_for(mid):
        by = {}
        for e in entries.get(mid, []):
            by.setdefault(e.object_set, []).append(e)
        named = [s for s in by if s]
        return (named[0] if named else 0), by
    fm = SimpleNamespace(
        maps=maps, entries=entries, debug_entries=set(), set_for=set_for,
        script_resources=dict(_SCRIPTS), script_maps={5: {10, 11}, 6: {12}},
        debug_scripts=set(), set_resources={7: 300}, script=lambda sid: _script(),
        image=b"", tables=None, read=lambda res: b"")
    model = GameModel(SimpleNamespace(data_dir="/made/up"))
    model.__dict__["names"] = _Names()
    model.__dict__["field"] = fm
    w = world._world(model)
    w._rows = {10: [(3, _ROW)], 11: [], 12: []}
    w._changes = {10: [bc.BgChange(2, 4, 4, 2, 2, 0x481, 3, 9, ((8, 8), (10, 10)))],
                  11: [], 12: []}
    w._cells = {10: {(1, 3): 4, (bc.KIND_BG_CHANGE, 2): 1}, 11: {}, 12: {}}
    w._defs = {7: {1: _definition(1, 2, event=9, story=0x21),
                   2: _definition(2, 5, event=46, think=6),
                   3: _definition(3, 4, event=12),
                   4: _definition(4, 7, event=18, facing=6),
                   5: _definition(5, 7, event=0xB8),
                   6: _definition(6, 7, event=0xF0)}}
    w._amounts = (250, 1000) + (0,) * (fo.CHEST_AMOUNTS - 2)
    model.__dict__["_link_index"] = links.LinkIndex(model, sources=[world.world_edges])
    return model


def _edges(model):
    index = links.LinkIndex.of(model)
    assert not index.errors
    return {(e.frm, e.rel, e.to) for found in index.out.values() for e in found}


def test_the_maps_and_their_ways():
    model = _model()
    edges = _edges(model)
    way = ref("entrance", 10, 3)
    for e in [(ref("map", 10), "Place", ref("place", 1)),
              (ref("map", 10), "Script", ref("script", 5)),
              (ref("map", 10), "Ways out", way),
              (way, "Leads to", ref("map", 11)),
              (ref("map", 10), "Leads to", ref("map", 11)),
              (way, "Object set", ref("object-set", 7)),
              (way, "Sound", ref("sound-effect", 13)),
              (ref("map", 11), "Object set", ref("object-set", 7)),
              (ref("map", 10), "Tile changes", ref("tile-change", 10, 2)),
              (ref("tile-change", 10, 2), "Story flag", ref("story-flag", 0x481)),
              (ref("tile-change", 10, 2), "Sound", ref("sound-effect", 9)),
              (ref("place", 0x52), "Story flag", ref("story-flag", 0x52 + 0x28A)),
              (ref("script", 5), "Hands over to", ref("script", 6)),
              (ref("script", 5), "Takes the party to", ref("map", 12))]:
        assert e in edges, e
    assert not any(f.kind == "place" and f.id == (1,) and rel == "Story flag"
                   for f, rel, _t in edges)          # place 1 is no town


def test_the_objects():
    model = _model()
    edges = _edges(model)
    entity, monster, trigger = ref("entity", 7, 1), ref("map-monster", 7, 2), ref("trigger", 7, 3)
    locked, money, label = ref("chest", 7, 4), ref("chest", 7, 5), ref("chest", 7, 6)
    for e in [(ref("object-set", 7), "Entities", entity),
              (ref("object-set", 7), "Map monsters", monster),
              (ref("object-set", 7), "Triggers", trigger),
              (ref("object-set", 7), "Chests", locked),
              (entity, "Stands on", ref("map", 11)),
              (entity, "Story flag", ref("story-flag", 0x580 + 0x21)),
              (monster, "Battle", ref("battle", 46)),
              (locked, "Holds", ref("item", 18)),
              (locked, "Story flag", ref("story-flag", 0x267)),
              (locked, "Story flag", ref("story-flag", fo.chest_flag(_definition(4, 7, facing=6), 11))),
              (label, "Runs", ref("label", 5, 800))]:
        assert e in edges, e
    assert not any(f == money and rel == "Holds" for f, rel, _t in edges)
    assert not any(f == trigger and rel == "Battle" for f, rel, _t in edges)


def test_titles():
    model = _model()
    assert links.title_of(model, ref("map", 10)) == "Place A"
    assert links.title_of(model, ref("map", 13)) == "map 13"
    assert links.title_of(model, ref("place", 0x52)) == "Place C"
    assert links.title_of(model, ref("entrance", 10, 3)) == "Place A · entrance 3"
    assert links.title_of(model, ref("tile-change", 10, 2)) == "Place A · tile change 2"
    assert links.title_of(model, ref("entity", 7, 1)) == "Place B · entity 1"
    assert links.title_of(model, ref("chest", 7, 4)) == "Place B · chest 4"
    assert links.title_of(model, ref("script", 5)) == "Place A, Place B"
    assert links.title_of(model, ref("story-flag", 3)) == "story flag 3"


def _facts(card) -> dict:
    assert not card["error"], card["error"]
    return dict(card["facts"])


def test_cards():
    model = _model()
    m = links.build_card(model, ref("map", 10))
    assert (m["title"], m["subtitle"]) == ("Place A", "Towns")
    f = _facts(m)
    assert f["Place"] == "Place A" and f["Song"] == "Song X"
    assert f["The party walks it"] == world.WALKS[1]
    assert _facts(links.build_card(model, ref("map", 11)))["Ways in"] == "1 (1 entrance)"
    assert _facts(links.build_card(model, ref("map", 12)))["Ways in"] == "1 (0 entrances, 1 by scripts)"
    way = _facts(links.build_card(model, ref("entrance", 10, 3)))
    assert way["Leads to"] == "Place B (map 11)"
    assert way["Puts the party"] == "at (16, 24), facing right"
    assert way["Taken by"] == "stepping on 4 squares of the map or the map's script"
    change = _facts(links.build_card(model, ref("tile-change", 10, 2)))
    assert change["Changes"] == "a 16 × 16 part of the map at (32, 32)"
    assert change["In"] == "2 steps, 3 frames apart"
    assert change["Started by"] == "stepping on 1 square of the map"
    assert _facts(links.build_card(model, ref("chest", 7, 5)))["Holds"] == "1000 in money"
    label = links.build_card(model, ref("chest", 7, 6))
    assert label["subtitle"] == "something to examine"
    locked = _facts(links.build_card(model, ref("chest", 7, 4)))
    assert locked["Holds"] == "item 18" and "story flag 615" in locked["Locked"]
    entity = links.build_card(model, ref("entity", 7, 1))
    assert entity["title"] == "Place B · entity 1"
    assert _facts(entity)["Gone while set"] == f"story flag {0x580 + 0x21}"
    assert _facts(links.build_card(model, ref("map-monster", 7, 2)))["Behaviour"] == \
        "keeps a look out for the party"
    flag = _facts(links.build_card(model, ref("story-flag", 0x481)))
    assert flag == {"Set": "when Place A · tile change 2 starts",
                    "Changes": "Place A · tile change 2 loads changed"}
    assert _facts(links.build_card(model, ref("story-flag", 0x580 + 0x21))) == \
        {"Changes": "Place B · entity 1 is gone"}
    nothing = links.build_card(model, ref("story-flag", 3))
    assert nothing["facts"] == [] and nothing["note"]
    assert _facts(links.build_card(model, ref("object-set", 7)))["Chests"] == "3"
    assert _facts(links.build_card(model, ref("script", 5)))["Run on"] == "2 maps: Place A, Place B"


def test_a_thing_that_does_not_exist_says_so():
    model = _model()
    for r, said in [(ref("map", 99), "no map 99"),
                    (ref("entrance", 10, 4), "no row 4"),
                    (ref("tile-change", 10, 5), "no tile change 5"),
                    (ref("entity", 7, 4), "is a chest, not an entity"),
                    (ref("chest", 7, 9), "makes nothing of definition 9"),
                    (ref("trigger", 8, 1), "no object set 8"),
                    (ref("script", 9), "no script 9"),
                    (ref("place", 9), "no map shows place 9")]:
        assert said in links.build_card(model, r)["error"], r


def test_the_tabs_hold_their_things(monkeypatch):
    from viewer_tabs import tab_providers as tp
    model = _model()
    monkeypatch.setattr(GameModel, "for_ctx", classmethod(lambda cls, ctx: model))
    monkeypatch.setattr(tp.GameNames, "for_ctx", classmethod(lambda cls, ctx: _Names()))
    maps = model.field.maps
    holds = tp.MapsProvider.holds
    assert holds(maps[10], ref("map", 10), None) and not holds(maps[11], ref("map", 10), None)
    assert holds(maps[11], ref("place", 2), None)
    assert holds(maps[10], ref("entrance", 10, 3), None)
    assert holds(maps[10], ref("tile-change", 10, 2), None)
    assert holds(maps[11], ref("chest", 7, 4), None)         # the map shown with set 7
    assert not holds(maps[10], ref("entity", 7, 1), None)
    assert all(k in tp.MapsProvider.homes for k in world.OBJECT_KINDS)
    assert tp.SpritesProvider.holds(("set", 7), ref("object-set", 7), None)
    assert not tp.SpritesProvider.holds(("data", 7, 0x20), ref("object-set", 7), None)
    assert tp.DialogueProvider.holds(("script", 201), ref("script", 6), None)
    assert not tp.DialogueProvider.holds(("script", 200), ref("script", 6), None)


def test_the_map_page_objects_carry_their_reference():
    from viewer_tabs import field_view as fv
    assert fv.object_ref(2, 7, 1) == {"kind": "entity", "id": [7, 1]}
    assert fv.object_ref(6, 7, 2) == {"kind": "map-monster", "id": [7, 2]}
    assert fv.object_ref(7, 7, 4) == {"kind": "chest", "id": [7, 4]}
    assert fv.object_ref(9, 7, 4) is None


@pytest.mark.parametrize("kind", world.OBJECT_KINDS)
def test_every_object_kind_has_a_card_and_a_title(kind):
    assert kind in links._CARDS and kind in links._TITLES
