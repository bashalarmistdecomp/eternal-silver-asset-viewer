"""The looks: the who-rule, the headings and the prints — made-up data,
no disc.

What this CAN catch: an entity taken to be someone who opens under half of
what they say, a question or a two-portrait opening counted, portraits no
character is grouped together, a party sheet losing to the who-rule, a look
put under the wrong heading, two copies of
the same pixels kept apart because their texels sit elsewhere on their
pages, or copies drawn with other colours put together.

What it CANNOT catch: whether the game's messages, definitions and pages
are read right; the decoders' tests and the on-disc tests do that.
"""

from types import SimpleNamespace

import numpy as np

from viewer_tabs import looks, scene
from viewer_tabs.looks import (
    MONSTERS, PARTY, PEOPLE, STORY, THINGS, Piece, Talk, classify, group_prints,
    look_talk, print_of, talker)
from viewer_tabs.refs import ref
from viewer_tabs.whose import own_character


def _said(*portraits, answers=None, empty=False):
    """A made-up message whose first run puts up `portraits`."""
    said = [] if empty else [SimpleNamespace(faces=[(0, p) for p in portraits])]
    return SimpleNamespace(answers=answers, said=said)


def _speaker(p):
    """As whose.speaker names a made-up portrait with no copies about:
    1-60 are characters 1-12's files, the rest no one's."""
    c = own_character(p)
    return ref("character", c) if c else ref("portrait", p)


P66, P67, C1, C2 = ref("portrait", 66), ref("portrait", 67), ref("character", 1), ref("character", 2)


# -- the who-rule --------------------------------------------------------------

def test_an_entity_is_the_speaker_who_opens_half_of_what_they_say():
    msgs = [_said(66), _said(66), _said(1), _said(6)]
    assert talker(msgs, _speaker) == Talk(P66, 2, 4)


def test_each_portrait_no_character_is_speaks_for_itself():
    # two portraits of the same file are two speakers: the game ties them
    # to no one, so nothing groups them
    msgs = [_said(66), _said(67), _said(1), _said(6)]
    assert talker(msgs, _speaker) == Talk(None, 1, 4)


def test_a_characters_portraits_are_one_speaker():
    msgs = [_said(1), _said(2), _said(66), _said(6)]
    assert talker(msgs, _speaker) == Talk(C1, 2, 4)


def test_questions_and_silent_messages_do_not_count():
    msgs = [_said(66), _said(1, answers=("Abcd", "Efgh")), _said(1, answers=("Ab", "Cd")),
            _said(empty=True)]
    assert talker(msgs, _speaker) == Talk(P66, 1, 1)


def test_an_opening_of_two_portraits_names_nobody():
    msgs = [_said(66, 1), _said(66, 1), _said(66)]
    assert talker(msgs, _speaker) == Talk(None, 1, 3)


def test_a_tie_takes_the_lower_reference():
    msgs = [_said(66), _said(1)]
    assert talker(msgs, _speaker) == Talk(C1, 1, 2)


def test_nothing_said_is_nobody():
    assert talker([], _speaker) == Talk(None, 0, 0)


def test_a_look_is_the_speaker_most_of_its_entities_are_taken_to_be():
    talks = [Talk(P66, 2, 3), None, Talk(None, 0, 5), Talk(P66, 1, 1), Talk(C2, 4, 4)]
    assert look_talk(talks) == Talk(P66, 3, 4)
    assert look_talk([None, Talk(None, 1, 4)]) is None


# -- the headings ---------------------------------------------------------------

def test_a_party_sheet_puts_a_look_in_the_party_whatever_is_said():
    assert classify([3], Talk(P66, 5, 5), ["entity"]) == (PARTY, 3)


def test_a_party_sheet_past_the_characters_names_nobody():
    assert classify([0xCE], None, []) == (PARTY, None)
    assert classify([13], None, []) == (PARTY, None)


def test_the_who_rule_names_only_portraits_no_character_is():
    # the party's portraits comment on what the party meets: an entity they
    # open is not taken to be them
    assert classify([], Talk(ref("character", 12), 1, 1), ["entity"]) == (PEOPLE, None)
    assert classify([], Talk(P67, 1, 1), ["entity"]) == (STORY, None)


def test_the_rest_by_who_wears_it():
    assert classify([], None, ["entity", "map-monster"]) == (PEOPLE, None)
    assert classify([], Talk(None, 0, 3), ["entity"]) == (PEOPLE, None)
    assert classify([], None, ["map-monster", "chest"]) == (MONSTERS, None)
    assert classify([], None, ["chest"]) == (THINGS, None)
    assert classify([], None, ["trigger"]) == (THINGS, None)
    assert classify([], None, []) == (THINGS, None)


# -- the prints -----------------------------------------------------------------

def _palette(*colours) -> bytes:
    """512 bytes: colour k at index k."""
    out = bytearray(512)
    for k, c in enumerate(colours):
        out[2 * k:2 * k + 2] = c.to_bytes(2, "little")
    return bytes(out)


def _page(lines: int, at: tuple[int, int], texels: list[list[int]]) -> np.ndarray:
    page = np.zeros((lines, 256), np.uint8)
    u, v = at
    page[v:v + len(texels), u:u + len(texels[0])] = texels
    return page


TEXELS = [[1, 2], [3, 1]]
PAL = _palette(0, 0x7C00, 0x03E0, 0x001F)


def _pose(slot, u, v, pts=(0, 0)):
    return {0: [Piece(0, 2, 2, pts, slot, u, v)]}


def test_the_same_texels_elsewhere_on_another_page_print_the_same():
    a = print_of(1, _pose(0, 10, 4), {0: _page(8, (10, 4), TEXELS)}, PAL)
    b = print_of(1, _pose(2, 200, 0), {2: _page(4, (200, 0), TEXELS)}, PAL)
    assert a == b


def test_other_colours_print_apart():
    a = print_of(1, _pose(0, 0, 0), {0: _page(2, (0, 0), TEXELS)}, PAL)
    b = print_of(1, _pose(0, 0, 0), {0: _page(2, (0, 0), TEXELS)},
                 _palette(0, 0x7C00, 0x03E0, 0x7FFF))
    assert a != b


def test_the_same_colours_from_other_indices_print_the_same():
    # what is drawn is the colour, not the index it is kept under
    a = print_of(1, _pose(0, 0, 0), {0: _page(2, (0, 0), TEXELS)}, PAL)
    b = print_of(1, _pose(0, 0, 0), {0: _page(2, (0, 0), [[5, 6], [7, 5]])},
                 _palette(0, 0, 0, 0, 0, 0x7C00, 0x03E0, 0x001F))
    assert a == b


def test_other_pieces_or_poses_print_apart():
    pages = {0: _page(2, (0, 0), TEXELS)}
    base = print_of(1, _pose(0, 0, 0), pages, PAL)
    assert print_of(1, _pose(0, 0, 0, pts=(1, 0)), pages, PAL) != base
    assert print_of(2, _pose(0, 0, 0), pages, PAL) != base
    assert print_of(1, {1: _pose(0, 0, 0)[0]}, pages, PAL) != base


def test_a_piece_off_its_page_draws_nothing():
    pages = {0: _page(2, (0, 0), TEXELS)}
    off = print_of(1, _pose(0, 0, 1), pages, PAL)        # runs past line 2
    assert off != print_of(1, _pose(0, 0, 0), pages, PAL)
    assert off == print_of(1, _pose(0, 100, 1), pages, PAL)
    assert off == print_of(1, _pose(5, 0, 0), pages, PAL)  # no page in slot 5


def test_copies_with_one_print_are_one_look():
    groups = group_prints({(21, 3): b"a", (4, 9): b"a", (0, 1): b"a", (7, 2): b"b",
                           (5, 5): None, (6, 6): None})
    assert groups == [[(0, 1), (4, 9), (21, 3)], [(5, 5)], [(6, 6)], [(7, 2)]]


# -- the page's layout ------------------------------------------------------------

def _sheet(poses=3, w=10, h=20):
    return {"image": None, "cell_w": w, "cell_h": h, "anchor_x": 5, "anchor_y": 18,
            "columns": 16, "poses": poses, "cells": [{}] * poses, "label": "x",
            "anims": [{"index": 0, "hold": False, "steps": [[1, 4], [2, 4]],
                       "name": None, "proof": None}]}


def test_held_poses_hold_each_pose_and_leave_the_sheets_own_anims():
    sheet = _sheet()
    held = scene.held_poses(sheet, "poses")
    assert [a["steps"] for a in held["anims"]] == [[[0, 1]], [[1, 1]], [[2, 1]]]
    assert all(a["hold"] for a in held["anims"])
    assert sheet["anims"][0]["steps"] == [[1, 4], [2, 4]]


def test_stack_puts_each_section_under_the_last():
    a, b = _sheet(), _sheet(h=30)
    w, h, sheets, actors = scene.stack([(a, [(0, "anim 0")]), (b, []),
                                        (b, [(k, f"pose {k}") for k in range(10)])],
                                       max_cols=8)
    assert sheets == [a, b]
    assert [x["sheet"] for x in actors] == [0] + [1] * 10
    first_b = actors[1]
    assert first_b["y"] > actors[0]["y"] and first_b["x"] == actors[0]["x"]
    assert actors[9]["y"] > first_b["y"]                 # the ninth pose wraps
    # cells 10 wide are spaced for their six-letter labels
    pitch = scene.LABEL_CHAR_W * 6 + scene.LABEL_PAD
    assert actors[2]["x"] - actors[1]["x"] == pitch
    assert w == 6 + 8 * pitch and h == (6 + 20 + 6 + 12) + 2 * (30 + 6 + 12) + 6


def test_stack_with_no_column_count_lies_wider_than_tall():
    sheet = _sheet(w=30, h=40)
    w, h, _sheets, _actors = scene.stack([(sheet, [(k, f"pose {k}") for k in range(300)])])
    assert w > h and w < 2 * h * scene.STACK_ASPECT
    # short labels after a long one sit closer, as far apart as the pair needs
    narrow = _sheet(w=10)
    _w, _h, _sheets, actors = scene.stack([(narrow, [(0, "pose 0")] + [(k, str(k))
                                                                    for k in range(1, 9)])],
                                          max_cols=8)
    pair = (len("pose 0") + len("1")) * scene.LABEL_CHAR_W // 2 + scene.LABEL_PAD
    assert pair > 10 + 6
    assert actors[1]["x"] - actors[0]["x"] == pair
    # a handful keeps the least number of columns
    w, h, _sheets, actors = scene.stack([(sheet, [(k, f"anim {k}") for k in range(10)])])
    assert len({a["y"] for a in actors}) == 2


def test_the_party_set_and_the_chest_number_are_the_codes():
    # set 0 makes no objects (an entrance naming it), so its sprite data
    # numbers are free for the party's sheets; kind 7 draws sprite data 0
    assert looks.PARTY_SET == 0 and looks.CHEST_NUMBER == 0
