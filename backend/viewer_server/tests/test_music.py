"""Live music on a made-up score: what the app pulls a chunk at a time is
the score as straight play gives it, an endless loop plays on with its
passes shown on the map, a seek lands where straight play is, the loop
switch takes effect at the first loop end heard after the frame the app
names, a new selection closes the stream unless it is the transport's
track (held, too, however many selections follow), and a WAV export is
a whole render of the passes asked for.

The score (test_seq_synth._song): an intro note, an endless loop of two
notes, one of them sent to the reverb, and an ending note. A pass is 30
sound ticks, half a second.
"""

import io
import wave
from types import SimpleNamespace

import pytest

from decoders.psx.disc.cd_audio import pcm_to_wav
from decoders.psx.formats import seq_synth
from decoders.psx.formats.tests.test_seq_synth import (KW, TICK, _song,
                                                       _song_bank)
from viewer_server import music
from viewer_server.merge import Entry, Row, Version
from viewer_server.music import MusicStream, Stale
from viewer_server import session
from viewer_server.session import GameSession, Tab
from viewer_tabs.score import ScoreSource
from viewer_tabs.tab_providers import SelectResult

pytest.importorskip("numpy")

RATE = 44100
PASS = 30 * TICK


def _source(reverb=True) -> ScoreSource:
    vab, setting = _song_bank()
    setting = setting if reverb else None
    walked = seq_synth.walk(_song(), vab, passes=2, **KW)
    return ScoreSource(
        label="song",
        player=lambda passes: seq_synth.Player(_song(), vab, passes=passes,
                                               reverb=setting, **KW),
        passes=2, rate=RATE,
        frames=walked.end + seq_synth.tail_frames(RATE, reverb=setting) + 1,
        first_pass=walked.first_pass, loop=walked.loop,
        describe=lambda stats: {"info": f"peak {stats.peak}"})


def _straight(frames, looping_off_at=None, passes=None) -> bytes:
    """The score played straight through: `frames` of it, the loop switch
    thrown off at `looping_off_at`."""
    player = _source().player(passes)
    if looping_off_at is not None:
        player.set_looping(False, looping_off_at)
    return player.read(frames)


def _pull(stream, start, frames, sizes=(4410, 22050, 735)):
    """What the app pulls from `start`, in chunks, up to `frames` of it or
    the end -> (pcm, the chunks' X-Music)."""
    out, where, at, i = b"", [], start, 0
    while len(out) < 4 * frames:
        data, w = stream.pcm(at, min(sizes[i % len(sizes)],
                                     frames - len(out) // 4))
        where.append(w)
        out += data
        at += w["frames"]
        i += 1
        if w["done"]:
            break
    return out, where


@pytest.fixture
def stream():
    s = MusicStream(_source())
    yield s
    s.close()


def _map_frame(marks, frame):
    """The map position of stream `frame` by the marks in force there."""
    at, base, limit, part, n = max((m for m in marks if m[0] <= frame),
                                   key=lambda m: m[0])
    return min(base + frame - at, limit), part, n


def test_the_chunks_are_straight_play(stream):
    played, where = _pull(stream, 0, 8 * RATE)
    assert played == _straight(8 * RATE)
    assert [w["from"] for w in where[1:]] == \
        [w["from"] + w["frames"] for w in where[:-1]]
    with pytest.raises(Stale):
        stream.pcm(0, 100)                          # not where it is


def test_an_endless_loop_plays_on_its_passes_folded_into_the_map(stream):
    src = stream.source
    _, where = _pull(stream, 0, 10 * RATE)
    assert not where[-1]["done"]
    marks = [m for w in where for m in w["marks"]]
    parts = []
    for m in marks:
        if (m[3], m[4]) not in parts:
            parts.append((m[3], m[4]))
    assert parts[:4] == [("intro", 0), ("loop", 1), ("loop", 2), ("loop", 3)]
    assert len(parts) > 15 and "ending" not in [p for p, _ in parts]
    last_start, last_end = src.loop
    # every pass from the map's last on is shown in the map's last pass
    for frame in range(src.loop[1], 10 * RATE, 997):
        shown, part, n = _map_frame(marks, frame)
        assert part == "loop" and n >= src.passes
        assert last_start <= shown <= last_end
    # the passes before it, where they are
    assert _map_frame(marks, src.first_pass + 100) == \
        (src.first_pass + 100, "loop", 1)


@pytest.mark.parametrize("copies", [False, True])
def test_a_seek_lands_where_straight_play_is(monkeypatch, copies):
    """Replayed from the start, from a copy the stream kept of itself, or
    (`copies`) from the overview's copies along the map."""
    if copies:
        monkeypatch.setattr(music, "COPY_SECONDS", 0.1)
        monkeypatch.setattr(music, "OVERVIEW_CHUNK", 2048)
    src = _source()
    intro = src.first_pass - 500
    in_last_pass = src.loop[0] + 1234
    in_ending = src.loop[1] + 2000
    s = MusicStream(src)
    try:
        for frame, looping in ((intro, True), (in_last_pass, True),
                               (in_last_pass, False), (in_ending, True),
                               (in_ending, False), (src.first_pass + 77, False)):
            if copies:          # a stream that has played nothing yet
                s.close()
                s = MusicStream(src)
                s.overview.join(10)
                ending = src.passes if frame >= src.loop[1] else None
                assert s.overview.fitting(frame, ending).frame > 0
            moved = s.seek(frame / RATE, looping)
            frame = moved["from"]
            got, where = _pull(s, frame, 2 * RATE)
            if frame >= src.loop[1]:            # the map's own ending
                want = _straight(frame + 2 * RATE, passes=src.passes)
            else:
                want = _straight(frame + 2 * RATE,
                                 None if looping else frame)
            assert got == want[4 * frame:4 * frame + len(got)], (frame, looping)
            assert _map_frame(moved["marks"], frame)[0] == frame
            if not looping or frame >= src.loop[1]:
                rest, end = _pull(s, frame + len(got) // 4, 60 * RATE)
                assert end[-1]["done"] and end[-1]["marks"][-1][3] == "ending"
    finally:
        s.close()


def test_the_loop_switch_off_ends_after_the_pass_it_is_heard_in(stream):
    held = int(1.2 * RATE)                  # what the app holds ahead
    played, _ = _pull(stream, 0, 4 * RATE)
    at = 4 * RATE - held                    # the next frame it will hear
    answer = stream.set_loop(False, at)
    # a loop end met in what the app holds was jumped back: played again
    assert answer["from"] == at
    rest, where = _pull(stream, at, 60 * RATE)
    assert where[-1]["done"]
    whole = played[:4 * at] + rest
    assert whole == _straight(60 * RATE, looping_off_at=at)
    # it went on at the first loop end heard at `at` or after
    player = stream.player
    went = player.reader.went_on
    assert player.at(went) >= at
    assert not [j for j in player.reader.jumps[:-1] if player.at(j) >= at]


def test_the_loop_switch_waits_for_a_loop_end_not_yet_met(stream):
    played, _ = _pull(stream, 0, 3 * RATE + PASS // 3, sizes=(735,))
    at = stream.player.pos                  # nothing held ahead
    assert stream.set_loop(False, at) == {"from": None}
    rest, where = _pull(stream, at, 60 * RATE)
    assert where[-1]["done"]
    assert played + rest == _straight(60 * RATE, looping_off_at=at)


def test_switching_the_loop_back_on_before_its_loop_end_keeps_it_looping(stream):
    _pull(stream, 0, 3 * RATE)
    at = stream.player.pos
    stream.set_loop(False, at)
    stream.set_loop(True, at)
    _, where = _pull(stream, at, 6 * RATE)
    assert not where[-1]["done"]
    assert stream.player.reader.went_on is None


def test_the_overview_draws_the_map_and_measures_it(stream):
    stream.overview.join(10)
    state = stream.overview_state(0, 0)
    assert state["done"] and len(state["lo"]) == state["columns"]
    whole, stats = seq_synth.render(_song(), _song_bank()[0], passes=2,
                                    reverb=_song_bank()[1], **KW)
    assert state["info"] == f"peak {stats.peak}"
    assert stream.source.frames == len(whole) // 4


# -- the session --------------------------------------------------------------

def _wav(passes=None) -> bytes:
    vab, setting = _song_bank()
    return pcm_to_wav(seq_synth.render(_song(), vab, passes=passes or 2,
                                       reverb=setting, **KW)[0])


class _Provider:
    """A tab of two items: a score and a picture."""

    def on_select(self, data, cache, archive, ctx):
        if data == "score":
            return SelectResult(info="a score", music=_source(),
                                audio={"name": "song", "midi": None,
                                       "render_wav": _wav, "passes": 2,
                                       "loop": (0.5, 1.0)})
        return SelectResult(info="a picture")


class _Store:
    def put_bytes(self, data, mime):
        return mime


def _session(exports=None):
    s = GameSession("k", "t", [], _Store())
    s.members = [SimpleNamespace(
        providers={"_Provider": _Provider()}, archive=None, tag="X",
        ctx=SimpleNamespace(program="SLUS_999.99", exports_dir=lambda: exports))]
    s.tabs = [Tab(_Provider, [0])]
    rows = [Row(("k", i), [Version([Entry((0,), i, label, label, None)])])
            for i, label in enumerate(("score", "picture", "score"))]
    s._rows = lambda index, view: (None, rows)
    return s


def test_a_new_selection_closes_the_stream_unless_the_transport_has_it():
    s = _session()
    try:
        first = s.select(0, None, 0)
        assert first["audio"]["live"]["loop"] == list(_source().loop)
        stream = s.music_stream(first["id"])
        s.select(0, None, 1)                        # the picture
        assert stream.overview.stopped.is_set() and not s.music
        with pytest.raises(KeyError):
            s.music_stream(first["id"])
        # the app came back to it: it plays again
        again = s.music_stream(first["id"], reopen=True)
        assert again is not stream and list(s.music) == [first["id"]]
        # the transport's, it outlives the next selections
        third = s.select(0, None, 2, keep=first["id"])
        s.select(0, None, 1, keep=first["id"])
        assert list(s.music) == [first["id"]]
        assert s.music_stream(first["id"]) is again
        with pytest.raises(KeyError):
            s.music_stream(third["id"])
        # ... however many: it stays held, to export
        for _ in range(session.KEEP_RESULTS + 2):
            s.select(0, None, 1, keep=first["id"])
        assert first["id"] in s._results and third["id"] not in s._results
    finally:
        s.close()
    assert not s.music


def _frames(path) -> int:
    with wave.open(io.BytesIO(path.read_bytes())) as w:
        return w.getnframes()


def test_a_wav_export_renders_the_passes_asked_for(tmp_path):
    s = _session(tmp_path)
    try:
        rid = s.select(0, None, 0)["id"]
        (two,) = s.export(rid, "wav", None, False)
        (three,) = s.export(rid, "wav", None, False, passes=3)
    finally:
        s.close()
    assert two.endswith("song.wav") and three.endswith("song_x3.wav")
    two, three = tmp_path / "song.wav", tmp_path / "song_x3.wav"
    assert _frames(two) == _source().frames
    walked = seq_synth.walk(_song(), _song_bank()[0], passes=2, **KW)
    start, end = walked.loop
    assert _frames(three) - _frames(two) == end - start
