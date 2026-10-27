"""Every tab on the user's own SSSC disc, when the library has it (skipped
otherwise; nothing from the disc enters git).

What this CAN catch: a tab that cannot list its items or open one. A
provider turns a decoder's exception into a row or a text that says
"Could not …", so a field renamed in one module and still read by another
shows up here and in no unit test. Each tab and view lists its items, and
its first, middle and last item are opened.

What it CANNOT catch: whether what a tab shows is right.
"""

import pytest

from decoders import config

_PROGRAM = "SLUS_006.28"
_DISC = config.raw_dir(_PROGRAM)

pytestmark = [pytest.mark.disc,
              pytest.mark.skipif(not (_DISC / _PROGRAM).exists(),
                                 reason="no extracted SSSC disc in the library")]

#: what a provider says when it caught a decoder's exception (a select
#: that fails raises, and so fails the test by itself)
_FAILED = ("Could not", "unreadable", "Traceback")


@pytest.fixture(scope="module")
def session():
    from viewer_server.routes import Backend
    return Backend("test", "test").open("lunar-1")


def _views(session):
    for i, tab in enumerate(session.describe()["tabs"]):
        for view in tab.get("views") or [None]:
            yield i, tab["name"], view


def test_every_tab_lists_and_opens_its_items(session):
    problems = []
    for i, name, view in _views(session):
        rows = session.items(i, view)["rows"]
        problems += [f"{name} / {view}: {r['title']}" for r in rows
                     if r.get("empty") and any(w in str(r.get("title")) for w in _FAILED)]
        live = [k for k, r in enumerate(rows) if not r.get("empty")]
        if not live:
            problems.append(f"{name} / {view}: no items")
            continue
        for k in sorted({live[0], live[len(live) // 2], live[-1]}):
            shown = str(session.select(i, view, k))
            hit = next((w for w in _FAILED if w in shown), None)
            if hit:
                at = shown.index(hit)
                problems.append(f"{name} / {view} item {k}: {shown[at:at + 120]}")
    assert not problems, "\n".join(problems)


def test_each_discs_items_have_keys_of_their_own(session):
    """Every game tab says what each item is (item_identity), and no two
    items of one disc share a key: they would be listed as versions of one
    row."""
    from collections import Counter
    problems = []
    for member in session.members:
        member.start()
        for name, prov in member.providers.items():
            identify = getattr(prov, "item_identity", None)
            if identify is None:
                problems.append(f"{member.tag} {name}: no item identity")
                continue
            for view in getattr(prov, "get_views", lambda: [])() or [None]:
                if view is not None:
                    prov.view = view
                items = prov.get_items({}, member.archive, member.ctx, None)
                keys = Counter(identify(label, data, member.ctx).key
                               for label, data in items if data is not None)
                twice = [k for k, n in keys.items() if n > 1]
                if twice:
                    problems.append(f"{member.tag} {name} / {view}: {twice[:3]}")
    assert not problems, "\n".join(problems)


#: The tabs whose every row Fan mode words itself (TabProvider.fan_row),
#: by the view whose rows those are.
_FAN_WORDED = {"Battles": "Battles", "Movies": None, "Menus": None}


def test_fan_mode_words_rows_plainly(session):
    """A row's Fan words carry no hex, and the tabs that word their rows
    word every one (a fan_row that fails leaves the row as written, so
    only this shows it)."""
    problems = []
    for i, name, view in _views(session):
        rows = session.items(i, view)["rows"]
        for r in rows:
            fan = r.get("fan") or {}
            words = f"{fan.get('title', '')} {fan.get('sub', '')}"
            if "0x" in words:
                problems.append(f"{name} / {view}: {words}")
        # None: every view of the tab
        if name in _FAN_WORDED and _FAN_WORDED[name] in (None, view):
            bare = [r["title"] for r in rows if not r.get("empty") and not r.get("fan")]
            if bare:
                problems.append(f"{name} / {view}: no Fan words for {len(bare)} rows")
    assert not problems, "\n".join(problems)


def test_a_thing_is_headed_by_its_title(session):
    """The Inspector heads a thing of the game with its title and its
    reference."""
    tabs = session.describe()["tabs"]
    i = next(t["index"] for t in tabs if t["key"] == "characters")
    shown = session.select(i, None, 0)
    assert shown["written"] == "character 1" and shown["hex"]
    assert shown["title"] and shown["title"] != shown["written"]
