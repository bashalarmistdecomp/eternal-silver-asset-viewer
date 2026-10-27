"""The Sound effects tab and the Sound banks' two kinds, on made-up rows: a
row is its number under its kind's heading, the number's home is the row
most things play, and a Sound banks row of a song or a sound effect says
which.

What this CANNOT catch: whether the disc's sound effects are found and
played (test_sound_effects_on_disc).
"""

from types import SimpleNamespace

import pytest

from viewer_server.present import _sound_effect_row, _sound_row
from viewer_tabs.links import sound_effects as lsx
from viewer_tabs.refs import parse, ref, written
from viewer_tabs.tab_providers import SoundEffectRow, SoundEffectsProvider, SoundItem


def _row(n, home, group=lsx.COMMON, bank=232):
    title, note = lsx.HEADINGS[group]
    return SoundEffectRow(lsx.Effect(n, bank, n - 1, group), home, title, note)


def test_a_sound_heard_everywhere_is_its_number_a_places_own_its_bank_too():
    assert lsx.Effect(9, 232, 8, lsx.COMMON).ref == ref("sound-effect", 9)
    assert lsx.Effect(130, 358, 99, lsx.BATTLE).ref == ref("sound-effect", 130)
    own = lsx.Effect(131, 300, 0, lsx.PLACE)
    assert own.ref == ref("sound-effect", 300, 131)
    assert written(own.ref) == "sound effect 300/131"
    assert parse("sound-effect", "300/131") == own.ref
    assert parse("sound-effect", "13") == ref("sound-effect", 13)
    with pytest.raises(ValueError, match="numbered by sound, or bank / sound"):
        parse("sound-effect", "1/2/3")


def test_a_reference_finds_its_row():
    assert SoundEffectsProvider.holds(_row(9, True), ref("sound-effect", 9), None)
    assert not SoundEffectsProvider.holds(_row(9, True), ref("sound-effect", 10), None)
    assert not SoundEffectsProvider.holds(_row(9, True), ref("song", 9), None)
    burg, other = _row(131, False, lsx.PLACE, 300), _row(131, True, lsx.PLACE, 312)
    assert SoundEffectsProvider.holds(burg, ref("sound-effect", 300, 131), None)
    assert not SoundEffectsProvider.holds(other, ref("sound-effect", 300, 131), None)
    # a place's number written without its bank: the row most things play
    assert SoundEffectsProvider.holds(other, ref("sound-effect", 131), None)
    assert not SoundEffectsProvider.holds(burg, ref("sound-effect", 131), None)


def test_a_sound_effect_whose_bank_was_not_read_is_still_compared():
    tab = SoundEffectsProvider()
    tab._scores = SimpleNamespace(_ensure_loaded=lambda ctx: None, _banks=[])
    a, b = (tab.item_identity("sound effect 9", _row(9, True, bank=n), None) for n in (232, 233))
    assert a.digest() != b.digest()
    assert a.digest() == tab.item_identity("sound effect 9", _row(9, True), None).digest()


def test_a_row_is_its_number_then_where_it_plays_under_its_kind():
    row = _sound_effect_row("sound effect 11  a chest opening, scenes",
                            _row(11, True, lsx.PLACE))
    assert row["title"] == "sound effect 11" and row["sub"] == "a chest opening, scenes"
    assert row["group"] == "Each place its own" and row["groupNote"]


def test_the_words_for_songs_and_sound_effects():
    names = SimpleNamespace(titles=lambda ns: "Made-up Theme" if 12 in ns else None)
    assert lsx.song_words(names, [12]) == "song 12 · Made-up Theme"
    assert lsx.song_words(names, [13, 14]) == "songs 13, 14"
    assert lsx.sound_effect_words([9]) == "sound effect 9"
    assert lsx.sound_effect_words([8, 10, 30]) == "sound effects 8, 10 and 30"
    assert lsx.sound_effect_words([131], 300) == "sound effect 300/131"
    assert lsx.song_words(names, []) == lsx.sound_effect_words([]) == ""


def test_a_sound_banks_row_says_song_or_sound_effect():
    seq = SimpleNamespace(seconds=1.5, notes=12, channels=[0, 1])
    bank = SimpleNamespace(resource=300, seqs=[seq, seq], sector=9,
                           vab=SimpleNamespace(vags=[1, 2]))
    effect = _sound_row("", SoundItem("seq", bank, 1, "sound effect 9", "sound-effect"))
    assert effect["title"] == "sound effect 9" and effect["sub"].startswith("sequence 300/1")
    assert (effect["group"], effect["badge"]) == ("Sound effects", "sound effect")
    nameless = _sound_row("", SoundItem("seq", bank, 0, None, "sound-effect"))
    assert nameless["title"] == "sequence 300/0" and nameless["mono"]
    assert nameless["sub"].endswith("no sound effect number plays it")
    song = _sound_row("", SoundItem("seq", bank, 0, "song 12 · Made-up Theme", "song"))
    assert (song["group"], song["badge"]) == ("Songs", "song")
    banked = _sound_row("", SoundItem("bank", bank, None, "the battle's sound effects",
                                      "sound-effect"))
    assert banked["title"] == "sound bank 300 · the battle's sound effects"
    assert banked["badge"] == "sound effects"

