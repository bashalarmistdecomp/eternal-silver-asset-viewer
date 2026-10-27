"""The looks and the sprites' links and cards on the user's own SSSC disc,
when the library has it (skipped otherwise; nothing from the disc enters
git).

What this CAN catch: the look index failing to read the disc's object
sets, party sheets or scripts (an error in the index or in the link
index), a heading left empty, a copy two looks claim, a card of a sprite
or a battle sprite that cannot be built, a kind whose home tab claims none
of its rows, and the Japanese member failing where its tables sit
elsewhere.

What it CANNOT catch: whether two copies are truly drawn alike in the game,
or whether an entity is who the who-rule takes them to be.
"""

import pytest

from decoders import config
from viewer_tabs import links, looks
from viewer_tabs.refs import ref

_PROGRAM = "SLUS_006.28"
_JP = "SLPS_013.97"

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
    """The first two looks of every heading, a copy that is not its look's
    first, and a battle sprite."""
    found = looks.of(model)
    out = []
    for g in looks.GROUPS:
        out += [lk.ref for lk in found.looks if lk.group == g][:2]
    out += [next(lk.copies[-1].ref for lk in found.looks if len(lk.copies) > 1)]
    out.append(ref("battle-sprite", 1, 0))
    return out


def _bad_cards(model, refs) -> list[str]:
    bad = []
    for r in refs:
        card = links.build_card(model, r, lambda image: "blob")
        if card["error"]:
            bad.append(f"{r}: {card['error']}")
        elif r.kind == "sprite" and "picture" not in card:
            bad.append(f"{r}: no picture")
    return bad


def test_the_looks_read_the_disc(session):
    found = looks.of(session.model(_member(session, _PROGRAM)))
    assert not found.errors, found.errors[:5]
    assert {lk.group for lk in found.looks} == set(looks.GROUPS)
    claimed = [c.unit for lk in found.looks for c in lk.copies]
    assert len(claimed) == len(set(claimed))
    assert all(found.look_of[c.unit] is lk for lk in found.looks for c in lk.copies)
    # every party member with a name has their field sheet's look
    party = {m for lk in found.looks for m, which in lk.party if which == "own"}
    assert set(range(1, looks.PARTY_LAST + 1)) <= party
    # a look taken from what is said says who and how much
    taken = [lk for lk in found.looks if lk.talk is not None]
    assert taken and all(lk.talk.opens * 2 >= lk.talk.total for lk in taken)


def test_the_index_reads_the_sprites(session):
    index = links.LinkIndex.of(session.model(_member(session, _PROGRAM)))
    assert not [e for e in index.errors if "sprites" in e], index.errors
    made = {(e.frm.kind, e.to.kind) for found in index.out.values() for e in found}
    for pair in [("object-set", "sprite"), ("entity", "sprite"), ("map-monster", "sprite"),
                 ("chest", "sprite"), ("character", "sprite"), ("sprite", "map"),
                 ("monster-set", "battle-sprite"), ("battle-sprite", "monster")]:
        assert pair in made, pair


def test_cards_for_every_heading(session):
    model = session.model(_member(session, _PROGRAM))
    assert not (bad := _bad_cards(model, _some(model))), "\n".join(bad)


def test_a_story_entity_card_says_it_is_taken_to_be_them(session):
    model = session.model(_member(session, _PROGRAM))
    lk = next(lk for lk in looks.of(model).looks if lk.group == looks.STORY)
    card = links.build_card(model, lk.ref)
    assert card["note"].startswith("Taken to be")
    assert any(k == "The who-rule" for k, _v in card["extended"])


def test_each_kind_finds_its_home(session):
    m = _member(session, _PROGRAM)
    model = session.model(m)
    refs = _some(model) + [ref("object-set", sorted(looks.of(model).sets)[0])]
    lost = [str(r) for r in refs if session.locate(r, m) is None]
    assert not lost, lost
    homes = {r.kind: session.locate(r, m)["view"] for r in refs}
    assert homes == {"sprite": "By who", "battle-sprite": "In battle",
                     "object-set": "Object sets"}, homes


def test_the_japanese_looks(session):
    m = _member(session, _JP)
    if m is None:
        pytest.skip("no Japanese SSSC disc in the library")
    model = session.model(m)
    assert not looks.of(model).errors
    assert not [e for e in links.LinkIndex.of(model).errors if "sprites" in e]
    assert not (bad := _bad_cards(model, _some(model))), "\n".join(bad)


def test_discs_with_the_same_files_share_their_reading(session):
    """Two members whose program and LUNADATA.FIL are the same bytes read
    the field, the messages and the looks once (GameModel.twin); a member
    with other files keeps its own."""
    from viewer_tabs.identity import file_digest
    by: dict[tuple, list[int]] = {}
    for m, member in enumerate(session.members):
        ctx = member.ctx
        if not ctx.path("LUNADATA.FIL").exists():
            continue
        by.setdefault((file_digest(ctx.exe_path), file_digest(ctx.path("LUNADATA.FIL"))),
                      []).append(m)
    twins = [ms for ms in by.values() if len(ms) > 1]
    if not twins:
        pytest.skip("no two members share their program and LUNADATA.FIL")
    first, other = (session.model(m) for m in twins[0][:2])
    assert other.twin is first.twin
    assert other.field is first.field and other.messages is first.messages
    assert looks.of(other) is looks.of(first)
    if len(by) > 1:
        apart = [session.model(ms[0]) for ms in by.values()]
        assert len({id(model.twin) for model in apart}) == len(apart)


def test_the_sets_are_read_without_the_looks(session):
    """Object sets and Pages list the sets alone: the looks (every copy's
    print, the who-rule) are made only when they are asked for."""
    from viewer_tabs.model import GameModel
    m = _member(session, _PROGRAM)
    found = looks.Looks(GameModel.for_ctx(session.members[m].ctx))
    assert found.sets and found._grouped is None
    assert found.looks and found._grouped is not None
