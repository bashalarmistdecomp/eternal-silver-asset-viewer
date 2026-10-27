"""The Characters tab and who speaks where, on the user's own SSSC discs
when the library has them (skipped otherwise; nothing from the disc enters
git).

What this CAN catch: a character's page that cannot be built (their
portraits, starting record, levels, magic, the scripts they speak in), a
character past the party's twelve, the tab not claiming a character's
link, the story domain failing to read the messages, a character card
without its portrait, a face of files 13 to 24 given to a character other
than by a copy of their picture, and the portraits no character is not
speaking for themselves.

What it CANNOT catch: whether a portrait in a message is its speaker's,
or whether the numbers by level are the ones a scene sets (records.level_up).
"""

import pytest

from decoders import config
from viewer_tabs import links, whose
from viewer_tabs.links import story
from viewer_tabs.refs import ref

_PROGRAM = "SLUS_006.28"
_JP = "SLPS_013.97"

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (config.raw_dir(_PROGRAM) / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    s = Backend("test", "test").open("lunar-1")
    s.start()
    return s


def _member(session, program):
    found = [m for m, member in enumerate(session.members) if member.ctx.program == program]
    if not found:
        pytest.skip(f"no {program} disc in the library")
    return found[0]


def _tab(session) -> int:
    return next(i for i, t in enumerate(session.tabs) if t.key == "characters")


def test_every_character_has_a_page(session):
    tab = _tab(session)
    rows = session.items(tab, None)["rows"]
    assert len(rows) == 12 and not any(r.get("group") for r in rows)
    for i in range(12):
        page = session.select(tab, None, i)
        sections = {s["title"]: s for s in page["sheet"]["sections"]}
        assert page["ref"] == {"kind": "character", "id": [i + 1]}
        assert sections["Portraits"].get("pictures"), i + 1
        assert "What they say" in sections
        if i + 1 <= 11:                     # the starting records' characters
            levels = sections["By level"]["table"]["rows"]
            assert levels and levels[-1][0] == "99", i + 1


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_characters_speak_and_their_cards_show_them(session, program):
    m = _member(session, program)
    model = session.model(m)
    index = links.LinkIndex.of(model)
    assert not [e for e in index.errors if "story" in e], index.errors
    spoken = story.spoken(model)
    assert len([c for c, s in spoken.items() if c.kind == "character" and s.shown]) >= 10
    assert len([c for c, s in spoken.items() if c.kind == "portrait" and s.shown]) >= 40
    for c in (1, 12):
        card = session.card(ref("character", c), m)
        assert not card.get("error") and card.get("picture"), (c, card.get("error"))
        assert session.locate(ref("character", c), m)["key"] == "characters"
    assert "there is no character 13" in session.card(ref("character", 13), m)["error"]


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_files_13_to_24_are_no_ones_but_for_copies(session, program):
    found = whose.of(session.model(_member(session, program)))
    assert all(found[f].character == (f - 1) // 5 + 1 for f in range(1, 61)
               if found[f].character is not None)
    copies = {f: (w.character, w.copy_of) for f, w in found.items() if f > 60 and w.character}
    # five of them: the same drawing as a character's first portrait
    assert len(copies) == 5 and all(g == (c - 1) * 5 + 1 for c, g in copies.values()), copies
    assert all(w.differ <= whose.COPY_PIXELS for w in found.values() if w.copy_of)


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_entities_say_their_lines(session, program):
    m = _member(session, program)
    index = links.LinkIndex.of(session.model(m))
    made = {(e.frm.kind, e.to.kind, e.rel) for found in index.out.values() for e in found}
    for pair in [("entity", "label", "Talk"), ("entity", "message", "Says"),
                 ("trigger", "label", "Touch"), ("label", "message", "Says"),
                 ("message", "character", "Speakers"), ("message", "portrait", "Speakers"),
                 ("portrait", "script", "Speaks in")]:
        assert pair in made, pair
    talkers = [e for found in index.out.values() for e in found
               if e.frm.kind == "entity" and e.rel == "Says"]
    entity = talkers[len(talkers) // 2].frm
    label = next(e.to for e in index.out[entity] if e.rel == "Talk")
    message = next(e.to for e in index.out[entity] if e.rel == "Says")
    for r in (entity, label, message):
        card = session.card(r, m)
        assert not card.get("error"), (r, card.get("error"))
    assert session.card(message, m).get("picture"), "a message's card draws its window"
    assert session.locate(message, m)["view"] == "Window"
    assert session.locate(label, m)["key"] == "dialogue"
