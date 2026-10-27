"""The story flags' links, cards and tab on the user's own SSSC discs, when
the library has them (skipped otherwise; nothing from the disc enters git).

What this CAN catch: the flags domain failing to read a disc's scripts (an
error in the link index), a kind of setter or checker the brief needs
missing altogether (a flag a label sets and a tile change checks, a
chest's, a movie's, a party id's, the game's end), a flag's card that
cannot be built, the Story flags tab not claiming a flag the links name,
and the Japanese member failing any of these.

What it CANNOT catch: whether the links are the ones the code makes (the
C each edge names) or whether a card says it in the right words.
"""

import pytest

from decoders import config
from decoders.plugins.SLUS_006_28.formats import event_script as es
from viewer_tabs import links, story_flags
from viewer_tabs.links import flags
from viewer_tabs.refs import ref

_US, _JP = "SLUS_006.28", "SLPS_013.97"
#: what the index's errors of this domain begin with
_DOMAIN = "viewer_tabs.links.flags."

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (config.raw_dir(_US) / _US).exists(),
                                 reason="no extracted SSSC disc in the library")]


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _member(session, program):
    found = [m for m, member in enumerate(session.members) if member.ctx.program == program]
    if not found:
        pytest.skip(f"no {program} disc in the library")
    session.members[found[0]].start()
    return found[0]


def _by(index, r) -> set[tuple[str, str]]:
    """(back, kind) of every link into flag r."""
    return {(e.back, e.frm.kind) for e in index.into.get(r, [])}


@pytest.mark.parametrize("program", [_US, _JP])
def test_every_way_of_touching_a_flag_is_read(session, program):
    model = session.model(_member(session, program))
    index = links.LinkIndex.of(model)
    assert not (bad := [e for e in index.errors if e.startswith(_DOMAIN)]), bad
    every = flags.touched(model)
    ways = [_by(index, r) for r in every]
    both = {(flags.SET_BY, "label"), (flags.CHECKED_BY, "tile-change")}
    assert any(both <= w for w in ways), "no flag a label sets and a tile change checks"
    for way in [(flags.SET_BY, "chest"), (flags.SET_BY, "movie"), (flags.SET_BY, "item"),
                (flags.SET_BY, "map-monster"), (flags.CLEARED_BY, "label"),
                (flags.CHECKED_BY, "label")]:
        assert any(way in w for w in ways), way
    party = ref("story-flag", es.PARTY_BASE + 2)
    assert (flags.SET_BY, "label") in _by(index, party)
    assert (flags.CHECKED_BY, "label") in _by(index, ref("story-flag", es.END_FLAG))


@pytest.mark.parametrize("program", [_US, _JP])
def test_every_flag_has_a_card_and_a_row(session, program):
    m = _member(session, program)
    model = session.model(m)
    every = flags.touched(model)
    bad = [f"{r}: {card['error']}" for r in every
           if (card := links.build_card(model, r))["error"]]
    assert not bad, "\n".join(bad[:20])
    rows = story_flags.story_flags(model)
    assert {it.ref for _label, it in rows} == set(every)
    lost = [str(r) for r in every[::200] if session.locate(r, m) is None]
    assert not lost, lost


def test_a_flag_is_credited_to_the_scenes_that_reach_its_command(session):
    """The scene you watch (ruled 2026-10-26): a command is credited to
    every label whose run reaches it, such as a scene run by talking to
    someone that calls the shared label holding it, and the scenes of other
    scripts that hand over to its script."""
    from viewer_tabs.links import story
    model = session.model(_member(session, _US))
    f = flags._flags(model)
    runs = story._runs(model)
    callers = handed = 0
    for sid, uses in f.uses.items():
        starts = f.labels[sid]
        for labs, u in uses:
            assert labs and len(labs) == len(set(labs)), (sid, u.offset)
            own = [lab for s, lab in labs if s == sid]
            assert own and own == sorted(own) and labs[:len(own)] == [(sid, lab) for lab in own]
            # where the code holding the command starts
            here = max((at for at in starts.values() if at <= u.offset), default=None)
            callers += any(starts.get(lab) != here and runs.get((sid, lab)) for lab in own)
            handed += len(labs) > len(own)
    assert callers > 100, "no flag credited to a talked-to scene that reaches a shared label"
    assert handed > 100, "no flag credited to a scene that hands over to another script"


def test_a_flag_lists_the_scenes_a_player_sees_and_its_pieces_apart(session):
    """Each scene once (ruled 2026-10-26): a piece of a scene is folded into
    it, losing nothing, as the scene reaches what the piece does; the
    pieces holding the command are Held in, and they and where a check goes
    on are shown with the extended info in Fan mode."""
    from viewer_tabs.links import scenes
    model = session.model(_member(session, _US))
    f = flags._flags(model)
    starts = scenes.started(model)
    folded = 0
    for sid, uses in f.uses.items():
        for labs, u in uses:
            shown = scenes.scenes_of(model, labs)
            assert shown and len(shown) == len(set(shown)), (sid, u.offset)
            for at in labs:
                if at not in shown:
                    folded += 1
                    assert at not in starts and set(scenes.part_of(model, *at)) <= set(labs)
    assert folded > 1000, "no piece folded into its scene"
    index = links.LinkIndex.of(model)
    flag = ref("story-flag", 1098)
    groups = {g["title"]: g["links"] for g in links.groups(model, index, flag)}
    for title in (flags.SET_BY, flags.CHECKED_BY):
        listed = [(link["ref"]["kind"], tuple(link["ref"]["id"])) for link in groups[title]]
        assert len(listed) == len(set(listed))
        assert not any(link["title"].startswith("Part of") for link in groups[title])
        assert not any(link.get("advanced") for link in groups[title])
    for title in (flags.HELD_IN, flags.GOES_ON_AT):
        assert groups[title] and all(link["advanced"] for link in groups[title])
