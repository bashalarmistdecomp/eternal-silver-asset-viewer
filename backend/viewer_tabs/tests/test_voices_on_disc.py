"""The Voices tab, its links and its sound, on the user's own SSSC discs
when the library has them (skipped otherwise; nothing from the disc enters
git).

What this CAN catch: a voice a script or a battle names that decodes to
nothing, to silence or to a length other than its span's; a battle voice
played for no one, a spell's voice given to a monster or an attack's to a
character, a set battle's voice not its monster's, the revive's not its
character's; a table read from the wrong
place (voices on no channel, spans that overlap or run past the file); a
voice card that cannot be built; the tab not claiming a voice's link; a
row that does not play.

What it CANNOT catch: whether a voice is the words of the message it is
linked with — only listening does that.
"""

import array
import math

import pytest

from decoders import config
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
    return next(i for i, t in enumerate(session.tabs) if t.key == "voices")


def _sound(session, m):
    from viewer_tabs.voice_audio import VoiceFile
    f = VoiceFile.for_ctx(session.members[m].ctx)
    if f.image is None:
        pytest.skip(f"no disc image: {f.why}")
    return f


def _pcm(wav: bytes) -> tuple[array.array, int]:
    assert wav[:4] == b"RIFF" and wav[12:16] == b"fmt "
    rate = int.from_bytes(wav[24:28], "little")
    at = wav.index(b"data") + 8
    return array.array("h", wav[at:]), rate


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_the_table_places_every_voice_inside_the_file(session, program):
    from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
    from viewer_tabs.links import voices as lv
    m = _member(session, program)
    f = _sound(session, m)
    v = lv.voices(session.model(m))
    assert sorted(v.table) == list(range(xv.FIRST, xv.LAST + 1))
    from decoders.psx.disc.iso_reader import DiscImage, find_file
    with DiscImage(f.image) as image:
        size = find_file(image, xv.FILE_NAME).size // 2048
    by_channel: dict[int, list] = {}
    for voice in v.table.values():
        assert 0 <= voice.channel < xv.CHANNELS and 0 <= voice.start < voice.end <= size, voice
        by_channel.setdefault(voice.channel, []).append(voice)
    for voices in by_channel.values():
        voices.sort(key=lambda x: x.start)
        assert all(a.end <= b.start for a, b in zip(voices, voices[1:]))


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_every_voice_the_scripts_name_sounds_for_its_span(session, program):
    from viewer_tabs.links import voices as lv
    m = _member(session, program)
    f = _sound(session, m)
    v = lv.voices(session.model(m))
    assert not v.errors, v.errors
    named = sorted(n for n, u in v.uses.items() if u.labels or u.plays)
    assert len(named) >= 60
    for n in named:
        voice = v.table[n]
        pcm, rate = _pcm(f.wav(voice))
        seconds = len(pcm) / rate
        # the span holds the voice's sectors and some empty ones
        assert 0.2 < seconds <= voice.seconds + 0.01, (n, seconds, voice.seconds)
        rms = math.sqrt(sum(x * x for x in pcm) / len(pcm))
        assert rms > 200, (n, rms)


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_voices_go_with_messages_and_their_cards_build(session, program):
    from viewer_tabs.links import voices as lv
    m = _member(session, program)
    v = lv.voices(session.model(m))
    uses = v.uses.values()
    assert len([u for u in uses if u.said]) >= 15
    assert len([u for u in uses if u.speaker is not None]) >= 10
    assert len([u for u in uses if u.bromides]) == 4
    for n in sorted(v.table):
        card = session.card(ref("voice", n), m)
        assert not card.get("error"), (n, card.get("error"))
        assert f"voice {n}" in card["title"]
        u = v.uses.get(n)
        if u is not None and u.speaker is not None and lv._face(session.model(m), u):
            assert card.get("picture"), n
    assert session.locate(ref("voice", 1), m)["key"] == "voices"


@pytest.mark.parametrize("program", [_PROGRAM, _JP])
def test_the_battles_voices_sound_and_go_with_their_spells(session, program):
    from decoders.plugins.SLUS_006_28.records import battle_voices as bv
    from viewer_tabs.links import battle
    from viewer_tabs.links import voices as lv
    m = _member(session, program)
    f = _sound(session, m)
    model = session.model(m)
    v = lv.voices(model)
    assert not v.errors, v.errors
    fought = sorted(n for n, u in v.uses.items() if u.battle)
    assert len(fought) >= 15
    for n in fought:
        pcm, _rate = _pcm(f.wav(v.table[n]))
        assert math.sqrt(sum(x * x for x in pcm) / len(pcm)) > 200, n
    # each way a battle plays a voice plays it for someone: a spell for
    # characters, an attack or a set battle for monsters
    t = battle._tables(model)
    kinds = {"spell": "character", "monster-attack": "monster", "battle": "monster",
             "character": "character"}
    for n in fought:
        for b in v.uses[n].battle:
            assert b.casters and {c.kind for c in b.casters} == {kinds[b.by.kind]}, (n, b)
    assert v.uses[bv.REVIVE_VOICE].speaker == ref("character", bv.REVIVER_ID)
    for b, voice in bv.SET_BATTLE_VOICES.items():
        got = [x for x in v.uses[voice].battle if x.by == ref("battle", b)]
        assert got and got[0].casters == (ref("monster", t.monster_ids(b)[0]),)
    assert len([n for n in fought if v.uses[n].speaker is not None]) >= 8
    nothing = [n for n in v.table if lv.heading(model, n)[0] == "Not played"]
    assert 0 < len(nothing) <= 15
    card = session.card(ref("voice", fought[0]), m)
    assert not card.get("error") and dict(card["facts"]).get("In battle")


def test_every_row_is_a_voice_and_plays(session):
    tab = _tab(session)
    rows = session.items(tab, None)["rows"]
    assert len(rows) == 103
    groups = [r["group"] for r in rows]
    # every voice a battle plays is someone's, so none is left "In battle"
    assert "In battle" not in groups
    assert groups.index("Over a scene") < groups.index("Not played")
    for i in (0, len(rows) // 2, len(rows) - 1):
        page = session.select(tab, None, i)
        assert page["ref"]["kind"] == "voice"
        assert page.get("audio"), i
