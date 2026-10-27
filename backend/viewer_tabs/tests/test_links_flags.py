"""The story flags' links and cards (viewer_tabs.links.flags) and the Story
flags tab's list (viewer_tabs.story_flags) — test_links_world's made-up
maps and object set, every script a made-up one, no game data.

What this CAN catch: a label's set, clear or check of a flag missing or
put on the wrong label, a scene not credited with what its run reaches
through a check's jump, a piece of a scene listed beside it (it is folded
into the scene) or not under Held in, the code's groups (Held in, Goes on
at) not shown with the extended info, a check not leading to the label it
goes on at, a
party id's flag or an object's flag (command 0x25) not linked, the game's
end (command 0x5C) not checking flag 1, a flag's card not saying how it
is set, cleared and checked, two links to one thing not listed once with
both notes, and a flag listed under the wrong place or group.

What it CANNOT catch: whether the scripts are read right (the format's
tests) or whether the code makes these links (the C each edge names).
"""

import pytest

from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats.tests.test_event_script import WORDS, script, u16
from viewer_tabs import links, story_flags
from viewer_tabs.links import flags, world
from viewer_tabs.refs import ref
from viewer_tabs.tests import test_links_world as made


class _Names(made._Names):
    def character(self, n):
        return "Hero" if n == 2 else None


#: Label 1 sets flag 0x100 and goes on at label 2 when 0x100 and 0x481 are
#: set; label 2 sets entity flag 0x580 + 0x21, clears 0x100, has party id 2
#: join and takes definition 1 off the map; label 3 ends the game. Label 1's
#: run reaches label 2's commands through its check, so it is credited with
#: them too (the scene you watch).
_CODE = (u16(0x09, 0x100, 0) + u16(0x0B, 2, 0x100, 0x481, 0) + u16(0x5E)
         + u16(0x0E) + bytes([0x21, 0]) + u16(0x0A, 0x100, 0) + bytes([0x23, 0, 0, 2])
         + u16(0x25) + bytes([1, 0]) + u16(0x5E)
         + u16(0x5C) + u16(0x5E))
_LABELS = (None, 0, 18, 38)


def _script():
    buf = script(_CODE, _LABELS)
    cmds, _gaps = es.script_code(buf, WORDS)
    return buf, {c.offset: c for c in cmds}, es.labels(buf)


@pytest.fixture
def model():
    model = made._model()
    model.__dict__["names"] = _Names()
    model.field.script = lambda sid: _script()
    model.__dict__["_link_index"] = links.LinkIndex(
        model, sources=[world.world_edges, flags.flag_edges])
    assert not model.__dict__["_link_index"].errors
    return model


def _into(model, r) -> dict[str, list]:
    found: dict[str, list] = {}
    for e in links.LinkIndex.of(model).into.get(r, []):
        found.setdefault(e.back, []).append(e.frm)
    return found


def _links(card, title) -> list[tuple]:
    group = next(g for g in card["groups"] if g["title"] == title)
    return [(ref(link["ref"]["kind"], *link["ref"]["id"]), link["note"])
            for link in group["links"]]


def test_labels_set_clear_and_check_their_flags(model):
    one, two, three = (ref("label", 5, n) for n in (1, 2, 3))
    flag = ref("story-flag", 0x100)
    got = _into(model, flag)
    assert got[flags.SET_BY] == [one, ref("label", 6, 1)]
    assert set(got[flags.CLEARED_BY]) == {one, two, ref("label", 6, 1), ref("label", 6, 2)}
    assert set(got[flags.CHECKED_BY]) == {one, ref("label", 6, 1)}
    out = {(e.rel, e.to) for e in links.LinkIndex.of(model).out[flag]}
    assert out == {(flags.GOES_ON_AT, two), (flags.GOES_ON_AT, ref("label", 6, 2))}
    assert one in _into(model, ref("story-flag", 0x481))[flags.CHECKED_BY]
    assert {one, two} <= set(_into(model, ref("story-flag", 0x580 + 0x21))[flags.SET_BY])
    assert {one, two} <= set(_into(model, ref("story-flag", es.PARTY_BASE + 2))[flags.SET_BY])
    # label 3 is reached from no other label: it alone ends the game
    assert set(_into(model, ref("story-flag", es.END_FLAG))[flags.CHECKED_BY]) == {
        three, ref("label", 6, 3)}


def test_a_flags_card_says_how_it_is_set_cleared_and_checked(model):
    card = links.build_card(model, ref("story-flag", 0x100))
    assert [g["title"] for g in card["groups"]] == \
        [flags.SET_BY, flags.CLEARED_BY, flags.CHECKED_BY, flags.HELD_IN, flags.GOES_ON_AT]
    checked = dict(_links(card, flags.CHECKED_BY))
    assert checked[ref("label", 5, 1)] == \
        "on Place A, Place B; whether it and story flag 1153 are set"
    assert dict(_links(card, flags.GOES_ON_AT))[ref("label", 5, 2)] == \
        "if it and story flag 1153 are set"
    # the code's workings: with the extended info in Fan mode
    held = dict(_links(card, flags.HELD_IN))
    assert held[ref("label", 5, 1)] == \
        "sets it; checks it: if it and story flag 1153 are set, goes on at label 5/2"
    assert held[ref("label", 5, 2)] == "clears it"
    for g in card["groups"]:
        advanced = g["title"] in (flags.HELD_IN, flags.GOES_ON_AT)
        assert all(link.get("advanced", False) == advanced for link in g["links"]), g["title"]
    facts = dict(card["facts"])
    assert facts["Set"].startswith("by a script on Place C")
    assert facts["Checked by scripts"].startswith("2 scenes")
    # the entity's flag: set by label 2 twice (0x0E and 0x25), listed once
    entity = links.build_card(model, ref("story-flag", 0x580 + 0x21))
    assert dict(_links(entity, flags.SET_BY))[ref("label", 5, 2)] == \
        "on Place A, Place B; takes Place B · entity 1 off the map"
    assert dict(entity["facts"])["Changes"] == "Place B · entity 1 is gone"
    party = links.build_card(model, ref("story-flag", es.PARTY_BASE + 2))
    assert dict(_links(party, flags.SET_BY))[ref("label", 6, 2)] == \
        "on Place C; Hero joins the party"
    end = dict(_links(links.build_card(model, ref("story-flag", 1)), flags.CHECKED_BY))
    assert end[ref("label", 5, 3)].endswith("then every story flag is cleared")


def test_the_list_puts_a_flag_under_where_it_is_set(model):
    rows = story_flags.story_flags(model)
    listed = {it.ref.id[0]: it.group for _label, it in rows}
    assert listed[0x481] == "Place A"                 # its tile change, on map 10
    assert listed[0x100] == "Place C"                 # a script run on one place first
    assert listed[0x52 + 0x28A] == "Place C"          # entering it
    assert listed[es.END_FLAG] == story_flags.UNSET[1]
    order = list(dict.fromkeys(it.group for _label, it in rows))
    assert order.index("Place A") < order.index("Place C") < order.index(story_flags.UNSET[1])


def test_a_piece_of_a_scene_is_folded_into_it(model):
    # talking to someone starts label 1 of each script; label 2, which
    # label 1's check goes on at, is a piece of that scene
    model.twin.__dict__["_scene_starts"] = {(5, 1): [("talking to someone", [10])],
                                            (6, 1): [("talking to someone", [12])]}
    model.__dict__["_link_index"] = links.LinkIndex(
        model, sources=[world.world_edges, flags.flag_edges])
    one, two = ref("label", 5, 1), ref("label", 5, 2)
    flag = ref("story-flag", 0x100)
    got = _into(model, flag)
    assert set(got[flags.CLEARED_BY]) == {one, ref("label", 6, 1)}
    assert {one, two, ref("label", 6, 2)} <= set(got[flags.HELD_IN])
    entity = _into(model, ref("story-flag", 0x580 + 0x21))
    assert set(entity[flags.SET_BY]) == {one, ref("label", 6, 1)}
    assert two in entity[flags.HELD_IN] and two not in entity[flags.SET_BY]
    # the piece's own card still says which flags its code touches
    card = links.build_card(model, two)
    clears = next(g for g in card["groups"] if g["title"] == flags.CLEARS)
    assert ref("story-flag", 0x100).json() in [link["ref"] for link in clears["links"]]
