"""Every tab on the user's own Japanese SSSC disc (SLPS_013.97), when the
library has it (skipped otherwise; nothing from the disc enters git).

What this CAN catch: a tab that cannot list the Japanese program's items or
open one: a table read where the US program keeps it, or one not located
(records.programs) that the tab does not say so for. Each tab and view of
the Japanese member lists its items through that member's own provider,
and its first, middle and last item are opened. The merged listing opens a
row's first version, often the US disc's, so test_tabs_on_disc does not
reach these.

What it CANNOT catch: whether what a tab shows is right.
"""

import pytest

from decoders import config

_PROGRAM = "SLPS_013.97"
_DISC = config.raw_dir(_PROGRAM)

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (_DISC / _PROGRAM).exists(),
                                 reason="no extracted Japanese SSSC disc in the library")]

#: what a provider says when it caught a decoder's exception, or when a
#: table it needs is not located in the program
_FAILED = ("Could not", "unreadable", "Traceback", "not located")


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


@pytest.fixture(scope="module")
def member(session):
    found = [m for m in session.members if m.ctx.program == _PROGRAM]
    assert found, "the game lists no member for the Japanese program"
    found[0].start()
    return found[0]


def test_the_japanese_disc_is_in_every_tab_the_us_disc_is(session, member):
    us = {i for i, m in enumerate(session.members) if m.ctx.program == "SLUS_006.28"}
    jp = session.members.index(member)
    tabs = [t for t in session.tabs if us & set(t.members)]
    missing = [t.key for t in tabs if jp not in t.members]
    assert tabs and not missing, missing


def test_every_tab_lists_and_opens_its_items(member):
    problems = []
    for name, prov in member.providers.items():
        for view in getattr(prov, "get_views", lambda: [])() or [None]:
            if view is not None:
                prov.view = view
            items = prov.get_items({}, member.archive, member.ctx, None)
            problems += [f"{name} / {view}: {label}" for label, data in items
                         if data is None and any(w in str(label) for w in _FAILED)]
            live = [k for k, (_label, data) in enumerate(items) if data is not None]
            if not live:
                problems.append(f"{name} / {view}: no items")
                continue
            for k in sorted({live[0], live[len(live) // 2], live[-1]}):
                r = prov.on_select(items[k][1], {}, member.archive, member.ctx)
                shown = f"{r.text or ''}\n{r.info or ''}"
                hit = next((w for w in _FAILED if w in shown), None)
                if hit:
                    at = shown.index(hit)
                    problems.append(f"{name} / {view} item {k}: {shown[at:at + 120]}")
    assert not problems, "\n".join(problems)
