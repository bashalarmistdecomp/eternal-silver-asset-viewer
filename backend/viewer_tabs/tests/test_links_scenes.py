"""The scenes a command is credited to and how they are laid out
(viewer_tabs.links.scenes), on made-up scripts: no game data.

What this CAN catch: a scene that hands over to another script (command
0x42) not credited with what that script does, the debug room's hand-overs
followed, a label credited with a command its run cannot reach (or not
with one it can, asked alone or with others), and a scene's places not
named once together.

What it CANNOT catch: whether the game runs these scripts on these maps.
"""

from types import SimpleNamespace

from viewer_tabs.links import scenes


def test_a_scenes_places_are_named_once_together():
    assert scenes.places_words(["A"]) == ("A", "A")
    assert scenes.places_words(["A", "B", "C"]) == ("A, B and C", "A, B and C")
    assert scenes.places_words(["A", "B", "C", "D", "E"]) == (
        "A, B, C and 2 more places", "A, B, C, D and E")


def test_every_label_reaching_a_command_is_credited_with_it():
    # made-up runs of script 5: label 1 reaches offsets 10 and 20, label 2
    # 20 and 30, label 3 nothing; script 6's label 4 hands over to label 2
    walks = scenes._Walks.__new__(scenes._Walks)
    walks.reach = {5: {1: frozenset({10, 20}), 2: frozenset({20, 30}), 3: frozenset()}}
    walks.handed_from = {(5, 2): [(6, 4)]}
    walks.reaching, walks.held, walks.reached_by = {}, {}, {}
    assert walks.credited(5, [20]) == {20: [(5, 1), (5, 2), (6, 4)]}
    assert walks.credited(5, [30, 10, 40, 30]) == {30: [(5, 2), (6, 4)], 10: [(5, 1)]}
    assert walks.credited(5, [10]) == {10: [(5, 1)]}
    assert walks.credited(7, [10]) == {}


def test_a_scene_that_hands_over_is_credited_with_what_the_other_script_does():
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    from decoders.plugins.SLUS_006_28.formats.tests.test_event_script import WORDS, script, u16
    # script 5: label 1 calls label 3 and ends; label 2 ends; label 3 sets
    # flag 0x100 and returns. Script 6: label 1 hands over to script 5's
    # label 3 (command 0x42); label 2 ends. Script 9, the debug room's,
    # hands over to label 3 too.
    five = script(u16(0x04, 3) + u16(0x5E) + u16(0x5E) + u16(0x09, 0x100, 0) + u16(0x05),
                  (None, 0, 6, 8))
    six = script(u16(0x42, 3) + bytes([5, 0]) + u16(0x5E), (None, 0, 6))
    nine = script(u16(0x42, 3) + bytes([5, 0]), (None, 0))

    def read(sid):
        buf = {5: five, 6: six, 9: nine}[sid]
        cmds, _gaps = es.script_code(buf, WORDS)
        return buf, {c.offset: c for c in cmds}, es.labels(buf)
    field = SimpleNamespace(script_resources={5: 0, 6: 0, 9: 0}, script=read, debug_scripts={9})
    model = SimpleNamespace(field=field)
    model.kept = lambda key, build: model.__dict__.setdefault(key, build(model))
    at = len(five) - 8                  # the 0x09
    assert scenes.credited(model, 5, [at]) == {at: [(5, 1), (5, 3), (6, 1)]}
    assert scenes.credited(model, 5, [len(five) - 10]) == {len(five) - 10: [(5, 2)]}
