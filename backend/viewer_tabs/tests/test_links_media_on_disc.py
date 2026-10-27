"""The media domain's links and cards on the user's own SSSC discs, when
the library has them (skipped otherwise; nothing from the disc enters git).

What this CAN catch: a link of this domain the disc cannot be read for (the
index's errors), a card that fails on a thing the index links (a movie, a
bromide, an image, a resource, a CD track, a bank, a sequence, a sample, a
disc file), an image or a bromide card with no picture, a thing whose home
tab does not claim its row (`locate`), and the Japanese program read where
the US program keeps a table.

What it CANNOT catch: whether the cards say what the game does.
"""

import pytest

from decoders import config

_PROGRAM = "SLUS_006.28"
_DISC = config.raw_dir(_PROGRAM)

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (_DISC / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]

_DOMAIN = "viewer_tabs.links.media."

#: each kind with a home, and the tab that is its home
_HOMES = {"movie": "movies", "bromide": "bromides", "image": "screens", "resource": "resources",
          "disc-file": "disc-files", "cd-track": "cd-tracks", "sound-bank": "sound-banks",
          "sequence": "sound-banks", "sample": "sound-banks"}


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _member(session, tag):
    return next((m for m, member in enumerate(session.members) if member.tag == tag), None)


def _index(session, m):
    from viewer_tabs.links import LinkIndex
    return LinkIndex.of(session.model(m))


def _things(index) -> dict:
    """A few things of every kind this domain links: the first, the middle
    and the last of each, as the index has them. A movie counts when its
    file is on this disc: the other disc's movies have no row here."""
    from viewer_tabs.refs import Ref

    def here(r) -> bool:
        return r.kind != "movie" or any(e.to.kind == "disc-file" for e in index.out.get(r, []))
    found: dict[str, list[Ref]] = {}
    for r in list(index.out) + list(index.into):
        if r.kind in _HOMES and here(r) and r not in found.setdefault(r.kind, []):
            found[r.kind].append(r)
    picked = {}
    for kind, refs in found.items():
        refs.sort(key=lambda r: r.id)
        picked[kind] = sorted({refs[0], refs[len(refs) // 2], refs[-1]}, key=lambda r: r.id)
    return picked


def _cards(session, m) -> tuple[dict, list[str]]:
    index = _index(session, m)
    things = _things(index)
    problems = [f"index: {e}" for e in index.errors if e.startswith(_DOMAIN)]
    cards = {}
    for kind, refs in things.items():
        for r in refs:
            card = session.card(r, m)
            cards[r] = card
            if card["error"]:
                problems.append(f"{r.key}: {card['error']}")
            if kind in ("image", "bromide") and not (
                    "picture" in card and card["picture"]["w"] and card["picture"]["h"]):
                problems.append(f"{r.key}: no picture")
    return cards, problems


@pytest.fixture(scope="module")
def us(session):
    m = _member(session, "US 1")
    return m, *_cards(session, m)


def test_every_kind_has_cards_on_the_us_disc(us):
    _m, cards, problems = us
    kinds = {r.kind for r in cards}
    # a CD track is linked only where a song plays it, which needs the cue
    assert kinds >= set(_HOMES) - {"cd-track"}, sorted(set(_HOMES) - kinds)
    assert not problems, "\n".join(problems)


def test_each_kind_is_found_in_its_home(us):
    _m, cards, _problems = us
    lost = [f"{r.key}: {card['home']}" for r, card in cards.items()
            if not card["home"] or card["home"]["key"] != _HOMES[r.kind]]
    assert not lost, "\n".join(lost)


def test_the_second_disc_has_its_own_movies(session):
    m = _member(session, "US 2")
    if m is None:
        pytest.skip("no second US disc in the library")
    index = _index(session, m)
    files = session.members[m].ctx.files
    stored = [e for es in index.out.values() for e in es
              if e.frm.kind == "movie" and e.to.kind == "disc-file"]
    assert stored and all(files[e.to.id[0]] == f"_B{e.frm.id[0]:03d}.STR" for e in stored)


def test_the_cards_hold_on_the_japanese_disc(session):
    m = _member(session, "JP 1")
    if m is None:
        pytest.skip("no Japanese disc in the library")
    _cards_found, problems = _cards(session, m)
    assert not problems, "\n".join(problems)
