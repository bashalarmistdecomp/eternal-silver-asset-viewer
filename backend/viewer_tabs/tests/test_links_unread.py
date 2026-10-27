"""What the links say of a part of the disc they could not read
(viewer_tabs.links), on made-up domains: no game data.

What this CAN catch: a domain that fails, or one that reads past a part
(a script, a map), leaving its links out with no word on the cards; an
error said on stderr more than once, or not at all; a title that could
not be read not said.

What it CANNOT catch: which parts of a real disc fail.
"""

import pytest

from viewer_tabs import links
from viewer_tabs.names import UnknownProgram
from viewer_tabs.refs import ref, written

M4, S6 = ref("map", 4), ref("song", 6)


class _Model:
    pass


def _edges(model):
    return [links.Edge(M4, S6, "Music", "Played on", "", "MadeUp (0x1)")]


def _broken(model):
    raise ValueError("a made-up table that cannot be read")


def _read_past(model):
    return ["script 3: ValueError: a made-up script", "map 9: KeyError: 2"]


def _unread_fails(model):
    raise LookupError("its domain failed")


@pytest.fixture
def unread(monkeypatch):
    """This module's domain reads past a script and a map."""
    monkeypatch.setattr(links, "_UNREAD", [_read_past, _unread_fails])


def _index(model, sources) -> links.LinkIndex:
    index = model.__dict__["_link_index"] = links.LinkIndex(model, sources=sources)
    return index


def _missing(card) -> list[str]:
    return [v for k, v in card["extended"] if k == "Links may be missing"]


def test_a_card_says_its_links_may_be_missing_and_why(unread, capsys):
    model = _Model()
    index = _index(model, [_edges, _broken])
    assert index.errors == [f"{__name__}._broken: ValueError: a made-up table that cannot be read",
                            f"{__name__}: script 3: ValueError: a made-up script",
                            f"{__name__}: map 9: KeyError: 2"]
    err = capsys.readouterr().err
    assert all(err.count(e) == 1 for e in index.errors), err
    # the links that were read are kept
    assert index.out[M4][0].to == S6
    for r in (M4, S6):
        assert _missing(links.build_card(model, r)) == index.errors
    assert "made-up" not in capsys.readouterr().err         # said once, as the index was built


def _not_this_program(model):
    raise UnknownProgram("no names for SLUS_999.98: the decoders do not know SLUS_999.98")


def _names_unreadable(model):
    raise LookupError("no names for SLUS_006.28: LUNADATA.FIL is missing")


def test_a_program_the_decoders_do_not_know_has_none_of_their_links_and_no_error(monkeypatch, capsys):
    monkeypatch.setattr(links, "_UNREAD", [])
    model = _Model()
    index = _index(model, [_edges, _not_this_program])
    assert index.errors == [] and index.out[M4][0].to == S6
    assert _missing(links.build_card(model, M4)) == []
    assert "links: could not read" not in capsys.readouterr().err
    # a program they do know whose names cannot be read is a failure still
    assert _index(_Model(), [_names_unreadable]).errors == [
        f"{__name__}._names_unreadable: LookupError: no names for SLUS_006.28: LUNADATA.FIL is missing"]


def test_a_card_whose_links_were_all_read_says_nothing_of_it(monkeypatch, capsys):
    monkeypatch.setattr(links, "_UNREAD", [])
    model = _Model()
    _index(model, [_edges])
    assert _missing(links.build_card(model, M4)) == []
    assert "links: could not read" not in capsys.readouterr().err


def test_many_parts_not_read_are_counted_past_the_first(monkeypatch):
    monkeypatch.setattr(links, "_UNREAD", [])
    index = links.LinkIndex(_Model(), sources=[])
    index.errors = [f"part {n}" for n in range(links.UNREAD_SHOWN + 3)]
    said = [v for _k, v in links.unread_of(index)]
    assert said == [f"part {n}" for n in range(links.UNREAD_SHOWN)] + ["and 3 more parts not read"]


def test_a_title_that_could_not_be_read_is_said_once_for_its_kind(monkeypatch, capsys):
    links._load_domains()
    monkeypatch.setattr(links, "_UNTITLED", set())

    def title(model, r):
        raise KeyError(r.id[0])
    monkeypatch.setitem(links._TITLES, "song", title)
    model = _Model()
    assert links.title_of(model, S6) == written(S6)
    assert links.title_of(model, ref("song", 7)) == written(ref("song", 7))
    err = capsys.readouterr().err
    assert err.count("title could not be read") == 1 and written(S6) in err and "KeyError: 6" in err
