"""Putting several discs' items together (viewer_server.merge)."""

from viewer_server.merge import Listing, merge
from viewer_tabs.identity import Identity, of_bytes, same


def _item(key, content):
    return (key, object(), of_bytes(key, content))


def test_the_same_content_is_one_version_held_by_both_discs():
    rows = merge([Listing((0,), "g", [_item("a", b"x")]),
                  Listing((1,), "g", [_item("a", b"x")])])
    assert len(rows) == 1
    assert len(rows[0].versions) == 1
    assert rows[0].holders == [0, 1]


def test_different_content_is_two_versions_of_one_row():
    rows = merge([Listing((0,), "g", [_item("a", b"x")]),
                  Listing((1,), "g", [_item("a", b"y")])])
    assert len(rows) == 1
    assert [v.holders for v in rows[0].versions] == [[0], [1]]


def test_another_program_group_is_never_a_version():
    rows = merge([Listing((0,), "game", [_item("a", b"x")]),
                  Listing((1,), "bonus", [_item("a", b"x")])])
    assert [r.holders for r in rows] == [[0], [1]]


def test_discs_with_identical_sources_hold_every_item():
    rows = merge([Listing((0, 1), "g", [("a", 1, None), ("b", 2, None)])])
    assert [r.holders for r in rows] == [[0, 1], [0, 1]]


def test_items_without_identity_never_merge_by_content():
    rows = merge([Listing((0,), "g", [("a", 1, None)]),
                  Listing((1,), "g", [("a", 1, None)])])
    assert len(rows) == 1
    assert [v.holders for v in rows[0].versions] == [[0], [1]]


def test_rows_keep_each_disc_order():
    rows = merge([Listing((0,), "g", [_item("a", b"1"), _item("b", b"2")]),
                  Listing((1,), "g", [_item("c", b"3"), _item("a", b"1"),
                                      _item("d", b"4")])])
    assert [r.key[1] for r in rows] == ["c", "a", "b", "d"]


def test_an_item_one_disc_has_follows_what_that_disc_listed_before_it():
    # Script s1's messages differ (keyed by their place in each text): each
    # disc's run sits before the next row it shares, the first disc's first.
    rows = merge([Listing((0,), "g", [_item("s1", b"1"), _item("s1 m0", b"a"),
                                      _item("s1 m4", b"b"), _item("s2", b"2")]),
                  Listing((1,), "g", [_item("s1", b"1"), _item("s1 m0", b"c"),
                                      _item("s1 m3", b"d"), _item("s1 m6", b"e"),
                                      _item("s2", b"2"), _item("s2 m0", b"f")]),
                  Listing((2,), "g", [_item("s1 m3", b"d"), _item("s1 m5", b"g"),
                                      _item("s2", b"2")])])
    assert [r.key[1] for r in rows] == ["s1", "s1 m0", "s1 m4", "s1 m3", "s1 m6",
                                        "s1 m5", "s2", "s2 m0"]
    assert [v.holders for v in rows[1].versions] == [[0], [1]]
    assert rows[3].holders == [1, 2]


def test_a_placeholder_shows_only_when_no_disc_has_items():
    rows = merge([Listing((0,), "g", [("None here", None, None)]),
                  Listing((1,), "g", [_item("a", b"1")])])
    assert [r.key[1] for r in rows] == ["a"]
    rows = merge([Listing((0,), "g", [("None here", None, None)]),
                  Listing((1,), "g", [("None here", None, None)])])
    assert len(rows) == 1 and rows[0].holders == [0, 1]


def test_sizes_that_differ_decide_without_a_digest():
    def never():
        raise AssertionError("digest read although the sizes differ")
    assert not same(Identity("a", 1, never), Identity("a", 2, never))
