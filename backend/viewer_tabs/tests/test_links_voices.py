"""The voices domain's links and words (viewer_tabs.links.voices) on a
made-up reading: made-up plays, messages and names, no game data.

What this CAN catch: a speaker named for a voice whose messages show more
than one speaker, a message counted twice, a voice listed under the wrong
heading (a portrait no character is by its number, a voice only a battle
plays, one nothing plays), a battle's casters not taken for its speakers,
a character and a monster of one name not listed as one, a title that does
not fall back from the name to the words to what plays it in battle to the
number, and edges that point the wrong way.

What it CANNOT catch: whether the disc's scripts say what the reading
holds (test_voices_on_disc).
"""

import threading
from types import SimpleNamespace

from decoders.plugins.SLUS_006_28.formats import script_voices as sv
from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
from viewer_tabs.links import voices as lv
from viewer_tabs.refs import ref


def who(n):
    """A made-up speaker: a character up to 12, else a portrait no one is."""
    return ref("character", n) if n <= 12 else ref("portrait", n)


def said(script, number, speakers, text="made up words", when="shown"):
    return lv.Said(script, number, 0x100 + number, when, tuple(speakers),
                   tuple(who(n) for n in speakers), text, text)


def played(script, *s):
    return lv.Played(script, sv.Play(1, 0x10, 0x14), list(s))


def fought(*refs):
    return [lv.InBattle(r, "made-up words", "MadeUpRun (0x80000000)") for r in refs]


def cast(by, *casters):
    return lv.InBattle(by, "made-up words", "MadeUpRun (0x80000000)", tuple(casters),
                       f"casting {by.kind} {by.id[0]}")


def model(uses: dict[int, lv.Use], names: dict[int, str] | None = None,
          monsters: dict[int, str] | None = None):
    reading = lv.Voices.__new__(lv.Voices)
    reading.table = {n: xv.Voice(n, 0, 0, 150, 0, 4, True) for n in range(1, 6)}
    reading.proof = xv.VOICE_GET
    reading.uses = uses
    reading.errors = {}
    m = SimpleNamespace(names=None if names is None else SimpleNamespace(
        character=lambda n: names.get(n), enemy=lambda n: (monsters or {}).get(n)),
        lock=threading.RLock())
    m.__dict__["_voices"] = reading
    m.kept = lambda key, build: m.__dict__[key]     # as GameModel.kept finds it kept
    return m


def test_a_speaker_is_named_only_when_every_message_shows_one_character():
    one = lv.Use(1, [played(3, said(3, 1, [2])), played(4, said(4, 7, [2]))])
    two = lv.Use(2, [played(3, said(3, 2, [2]), said(3, 3, [5]))])
    both = lv.Use(3, [played(3, said(3, 4, [2, 5]))])
    assert (one.speaker, one.speakers) == (who(2), [who(2)])
    assert (two.speaker, two.speakers) == (None, [who(2), who(5)])
    assert both.speaker is None
    assert lv.Use(4).speaker is None


def test_a_message_two_plays_go_with_is_counted_once():
    u = lv.Use(1, [played(3, said(3, 1, [2])), played(3, said(3, 1, [2]), said(3, 2, [2]))])
    assert [(s.script, s.number) for s in u.said] == [(3, 1), (3, 2)]


def test_headings():
    m = model({1: lv.Use(1, [played(3, said(3, 1, [2]))]),
               2: lv.Use(2, [played(3, said(3, 2, [2]), said(3, 3, [5]))]),
               3: lv.Use(3, [played(3, said(3, 4, []))]),
               4: lv.Use(4, [played(3)]),
               5: lv.Use(5, bromides=[0]),
               7: lv.Use(7, [played(3, said(3, 5, [91]))]),
               8: lv.Use(8, battle=fought(ref("spell", 3))),
               9: lv.Use(9, [played(3, said(3, 6, [2]))], battle=fought(ref("spell", 4)))},
              names={2: "Made-up name"})
    got = [lv.heading(m, n)[0] for n in range(1, 10)]
    assert got == ["Made-up name", "More than one speaker", "No portrait", "Over a scene",
                   "With the bromides", "Not played", "portrait 91", "In battle",
                   "Made-up name"]


def test_a_title_falls_back_from_the_name_to_the_words_to_the_number():
    long = "a made-up line of words that runs on past the quote"
    m = model({1: lv.Use(1, [played(3, said(3, 1, [2]))]),
               2: lv.Use(2, [played(3, said(3, 2, [2], long), said(3, 3, [5]))]),
               4: lv.Use(4, [played(3, said(3, 4, [91], "a portrait's line"))])},
              names={2: "Made-up name"})
    assert lv.title(m, 1) == "Made-up name · voice 1"
    assert lv.title(m, 2) == f"“{long[:lv.QUOTE].rstrip()}…” · voice 2"
    assert lv.title(m, 3) == "voice 3"
    assert lv.title(m, 4) == "“a portrait's line” · voice 4"
    m = model({5: lv.Use(5, battle=fought(ref("spell", 3), ref("spell", 3),
                                         ref("monster-attack", 9)))})
    assert lv.title(m, 5) == "spell 3 and 1 more · voice 5"
    m = model({6: lv.Use(6, battle=fought(ref("character", 12)))})
    assert lv.title(m, 6) == "character 12's revive · voice 6"
    assert lv.quote("two\n  lines") == "“two lines”"


def test_edges_point_from_the_label_to_the_voice_to_its_message_and_speaker():
    u = lv.Use(1, [played(3, said(3, 1, [2]))], labels=[(3, 9)])
    edges = list(lv.voice_edges(model({1: u})))
    assert [(e.frm, e.to) for e in edges] == [
        (ref("label", 3, 9), ref("voice", 1)),
        (ref("voice", 1), ref("message", 3, 1)),
        (ref("voice", 1), ref("character", 2))]


def test_battle_edges_point_from_what_plays_it_to_the_voice():
    u = lv.Use(1, battle=fought(ref("spell", 3), ref("monster-attack", 9), ref("battle", 245),
                                ref("character", 12)))
    edges = list(lv.voice_edges(model({1: u})))
    assert [(e.frm, e.to, e.back) for e in edges] == [
        (ref("spell", 3), ref("voice", 1), "Played by spells"),
        (ref("monster-attack", 9), ref("voice", 1), "Played by monster attacks"),
        (ref("battle", 245), ref("voice", 1), "Played in battles"),
        (ref("character", 12), ref("voice", 1), "Played by")]


def test_who_casts_a_voice_in_battle_says_it():
    c2, c3, m7 = ref("character", 2), ref("character", 3), ref("monster", 7)
    m = model({1: lv.Use(1, battle=[cast(ref("spell", 4), c2)]),
               2: lv.Use(2, battle=[cast(ref("spell", 5), c2), cast(ref("monster-attack", 9), m7)]),
               3: lv.Use(3, battle=[cast(ref("spell", 6), c2), cast(ref("spell", 7), c3)]),
               4: lv.Use(4, [played(3, said(3, 1, [91]))], battle=[cast(ref("spell", 8), c2)])},
              names={2: "Made-up name", 3: "Other name"}, monsters={7: "Made-up name"})
    assert lv.voices(m).uses[1].speaker == c2
    assert [lv.heading(m, n)[0] for n in range(1, 5)] == [
        "Made-up name", "Made-up name", "More than one speaker", "More than one speaker"]
    assert lv.title(m, 2) == "Made-up name · voice 2"
    assert lv.speaker_words(m, lv.voices(m).uses[4]) == "portrait 91, Made-up name"
    assert lv.heading(m, 1)[1] == "who casts it in battle"
    edges = [(e.frm, e.to, e.note) for e in lv.voice_edges(m) if e.frm == ref("voice", 2)]
    assert edges == [(ref("voice", 2), c2, "casting spell 5"),
                     (ref("voice", 2), m7, "casting monster-attack 9")]
