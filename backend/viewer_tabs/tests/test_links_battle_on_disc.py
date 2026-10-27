"""The battle domain's links and cards (viewer_tabs.links.battle) on the
user's own SSSC disc, when the library has it (skipped otherwise; nothing
from the disc enters git).

What this CAN catch: a table, resource or script the domain cannot read
on the real disc (the index's errors), a kind that makes no links, a card
that cannot be built for things of each kind, a portrait card without its
face, a home no tab claims, and a card that breaks on the Japanese
program.

What it CANNOT catch: whether what the cards and links say is right.
"""

import pytest

from decoders import config
from viewer_tabs import links
from viewer_tabs.links import battle
from viewer_tabs.refs import ref

_PROGRAM = "SLUS_006.28"
_DISC = config.raw_dir(_PROGRAM)

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (_DISC / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]

#: the kinds this domain makes cards for
KINDS = ("battle", "scripted-battle", "monster-set", "monster-group", "monster",
         "monster-attack", "item", "spell", "shop", "character", "portrait",
         "portrait-list")
#: each kind with a home, and the tab that is it
HOMES = {"battle": "battles", "monster-set": "battles", "monster": "monsters",
         "monster-attack": "monsters", "item": "items", "spell": "magic", "shop": "items",
         "character": "characters", "portrait": "portraits", "portrait-list": "portraits"}


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _member(session, tag: str) -> int | None:
    return next((m for m, member in enumerate(session.members) if member.tag == tag), None)


#: the domain's edges, by the functions that make them
_SOURCES = (battle.battle_edges, battle.scripted_battle_edges, battle.monster_edges,
            battle.goods_edges, battle.shop_edges, battle.cast_edges)


def _ours(model):
    """Every edge this domain makes on the disc, and what it could not read."""
    index = links.LinkIndex(model, _SOURCES)
    return [e for found in index.out.values() for e in found], index.errors


def _samples(edges, kinds=KINDS) -> list:
    """The first, middle and last thing of each kind the links reach."""
    by_kind: dict[str, set] = {}
    for e in edges:
        for r in (e.frm, e.to):
            by_kind.setdefault(r.kind, set()).add(r)
    out = []
    for kind in kinds:
        found = sorted(by_kind.get(kind, ()))
        assert found, f"no {kind} is linked"
        out += sorted({found[0], found[len(found) // 2], found[-1]})
    return out


def _check_cards(session, m: int, kinds=KINDS) -> list:
    model = session.model(m)
    edges, errors = _ours(model)
    assert errors == []
    problems = []
    for r in _samples(edges, kinds):
        card = session.card(r, m)
        if card["error"]:
            problems.append(f"{r.key}: {card['error']}")
        if r.kind == "portrait" and "picture" not in card:
            problems.append(f"{r.key}: no picture")
    return problems


def test_every_kind_links_and_its_cards_build(session):
    problems = _check_cards(session, 0)
    assert not problems, "\n".join(problems)


def test_each_home_is_found(session):
    model = session.model(0)
    edges, _errors = _ours(model)
    problems = []
    for kind, key in HOMES.items():
        r = next(x for e in edges for x in (e.frm, e.to) if x.kind == kind)
        home = session.locate(r, 0)
        if home is None or home["key"] != key:
            problems.append(f"{r.key}: {home}")
    assert not problems, "\n".join(problems)


def test_the_cards_build_on_the_japanese_program(session):
    m = _member(session, "JP 1")
    if m is None:
        pytest.skip("no JP 1 disc in the library")
    # the Japanese program's shop stock is not located (records.programs): a
    # shop its scripts open says so, one no script opens cannot be read
    problems = _check_cards(session, m, tuple(k for k in KINDS if k != "shop"))
    card = session.card(ref("shop", 1), m)
    assert card["error"] == "" and "not located" in dict(card["facts"])["Sells"]
    assert "not located" in session.card(ref("shop", 8), m)["error"]
    assert not problems, "\n".join(problems)
