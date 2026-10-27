"""The world's links and cards on the user's own SSSC disc, when the
library has it (skipped otherwise; nothing from the disc enters git).

What this CAN catch: the world domain failing to read the disc's maps,
scripts or object sets (an error in the link index), a card for a map,
place, entrance, tile change, script, object set, story flag or object
that cannot be built, a kind whose home tab claims none of its rows, and
the Japanese member's cards failing where its tables sit elsewhere.

What it CANNOT catch: whether the links are the ones the code makes (the
C each edge names) or whether a card says it in the right words.
"""

import pytest

from decoders import config
from viewer_tabs import links
from viewer_tabs.field_view import OBJECT_REF_KINDS
from viewer_tabs.links import world
from viewer_tabs.refs import ref

_PROGRAM = "SLUS_006.28"
_JP = "SLPS_013.97"
#: what the index's errors of this domain begin with ("<module>.<function>: ...")
_DOMAIN = "viewer_tabs.links.world."

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (config.raw_dir(_PROGRAM) / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _member(session, program):
    found = [m for m, member in enumerate(session.members) if member.ctx.program == program]
    if not found:
        return None
    session.members[found[0]].start()
    return found[0]


def _some(model) -> list:
    """A few things of every kind the domain makes cards for."""
    w = world._world(model)
    out = []
    for mid in sorted(w.fm.maps)[::40] + [next(m for m in sorted(w.fm.maps) if w.rows(m))]:
        out += [ref("map", mid), ref("place", w.fm.maps[mid].area.location)]
        out += [ref("entrance", mid, row) for row, _e in w.rows(mid)[:1]]
        out += [ref("tile-change", mid, c.id) for c in w.changes(mid)[:1]]
    out += [ref("script", sid) for sid in sorted(w.fm.script_resources)[::60]]
    out += [ref("object-set", s) for s in sorted(w.set_maps)[:2]]
    seen = set()
    for s in sorted(w.set_maps):
        for i, d in sorted(w.definitions(s).items()):
            kind = OBJECT_REF_KINDS.get(d.kind)
            if kind and kind not in seen:
                seen.add(kind)
                out.append(ref(kind, s, i))
    index = links.LinkIndex.of(model)
    out += sorted({e.to for found in index.out.values() for e in found
                   if e.to.kind == "story-flag"})[::100]
    return out


def _bad_cards(model, refs) -> list[str]:
    bad = []
    for r in refs:
        card = links.build_card(model, r)
        if card["error"]:
            bad.append(f"{r}: {card['error']}")
    return bad


def _errors(index) -> list[str]:
    return [e for e in index.errors if e.startswith(_DOMAIN)]


def test_the_index_reads_the_world(session):
    index = links.LinkIndex.of(session.model(_member(session, _PROGRAM)))
    assert not _errors(index), _errors(index)
    made = {(e.frm.kind, e.to.kind) for found in index.out.values() for e in found}
    for pair in [("map", "place"), ("map", "script"), ("map", "entrance"), ("entrance", "map"),
                 ("map", "tile-change"), ("tile-change", "story-flag"), ("object-set", "entity"),
                 ("map-monster", "battle"), ("chest", "item"), ("chest", "label")]:
        assert pair in made, pair


def test_cards_for_every_kind(session):
    model = session.model(_member(session, _PROGRAM))
    refs = _some(model)
    kinds = {r.kind for r in refs}
    assert {"map", "place", "entrance", "tile-change", "script", "object-set",
            "story-flag", *world.OBJECT_KINDS} <= kinds, kinds
    assert not (bad := _bad_cards(model, refs)), "\n".join(bad)


def test_each_kind_finds_its_home(session):
    m = _member(session, _PROGRAM)
    model = session.model(m)
    firsts = {}
    for r in _some(model):
        if r.kind != "story-flag":
            firsts.setdefault(r.kind, r)
    lost = [str(r) for r in firsts.values() if session.locate(r, m) is None]
    assert not lost, lost


def test_the_japanese_cards(session):
    m = _member(session, _JP)
    if m is None:
        pytest.skip("no Japanese SSSC disc in the library")
    model = session.model(m)
    assert not (errors := _errors(links.LinkIndex.of(model))), errors
    assert not (bad := _bad_cards(model, _some(model))), "\n".join(bad)
