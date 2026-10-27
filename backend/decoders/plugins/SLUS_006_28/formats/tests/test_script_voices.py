"""Tier 1 for the voices' messages (formats.script_voices) — made-up
scripts, no game data.

What this CAN catch: which message the rule pairs with a voice — the one
left up as it starts, those after it starts, and where that stops (a
close, 0x54, the next 0x52, a disc read, a wait for the player, a timed
message going on, the label's end) — and that calls, returns and tests are
followed as the runner takes them.

What it CANNOT catch: that a command's handler does what READS_DISC,
CLEARS_WINDOW and WAITS_FOR_PLAYER say — only re-reading the handlers
does that.
"""

import struct

from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import script_voices as sv

# a made-up character table: 0x01 waits for the player, 0x02 clears the
# rows, 0x03 closes the window, anything else is a letter
CONTROLS = {0x01: 0xFF00, 0x02: 0xFF01, 0x03: 0xFF03}


def chars(b: int) -> int:
    return CONTROLS.get(b, 0x0040 + b)


def u16(*w):
    return b"".join(struct.pack("<H", x) for x in w)


def text(*codes: int) -> bytes:
    """A message command: its codes, the 0xFF, padded to even."""
    body = u16(es.TEXT) + bytes(codes) + b"\xff"
    return body + (b"\x00" if len(body) & 1 else b"")


def voice_set(n: int) -> bytes:
    return u16(sv.VOICE_SET) + bytes([n, 0])


START = u16(sv.VOICE_START)
END_WAIT = u16(sv.VOICE_END_WAIT)
RETURN = u16(es.LABEL_RETURN)
MUSIC = u16(0x30, 1)                        # a song: it reads the disc


def timed(on: bool) -> bytes:
    return u16(sv.MESSAGE_TIMED) + bytes([1 if on else 0, 0])


def build(*labels: bytes):
    """A resource whose label n (from 1) is the n-th piece of code, and
    the offset of each piece."""
    table = bytearray(2 * (len(labels) + 2))
    at = len(table)
    starts = []
    for i, piece in enumerate(labels, start=1):
        struct.pack_into("<H", table, 2 * i, at // 2)
        starts.append(at)
        at += len(piece)
    return bytes(table) + b"".join(labels), starts


def run(*labels: bytes, script=None):
    buf, starts = build(*labels)
    cmds, _gaps = es.script_code(buf, None)
    cmds = {c.offset: c for c in cmds}
    ends = {o: sv.text_end(buf, o, None, chars, None) for o, c in cmds.items() if c.id == es.TEXT}
    return sv.script_voices(buf, cmds, ends, script), starts, cmds


def texts(cmds) -> list[int]:
    return [o for o, c in sorted(cmds.items()) if c.id == es.TEXT]


# -- how a message leaves the window -------------------------------------------

def test_text_end_reads_prompts_and_what_is_left():
    buf, _ = build(text(0x30, 0x01, 0x31) + text(0x30, 0x03) + text(0x30, 0x02) + text())
    cmds = {c.offset: c for c in es.script_code(buf, None)[0]}
    got = [sv.text_end(buf, o, None, chars, None) for o in texts(cmds)]
    assert got == [sv.TextEnd(1, "text"), sv.TextEnd(0, "closed"), sv.TextEnd(0, "page"),
                   sv.TextEnd(0, "empty")]


# -- what goes with a voice ------------------------------------------------------

def test_the_message_left_up_is_shown_as_the_voice_starts():
    got, _, cmds = run(text(0x30) + voice_set(7) + START + RETURN)
    (play,) = got.plays
    assert (play.voice, play.shown, play.during) == (7, texts(cmds), [])
    assert play.labels == [1]


def test_a_closed_message_is_not_shown():
    got, _, _ = run(text(0x30, 0x03) + voice_set(7) + START + RETURN)
    (play,) = got.plays
    assert play.shown == [] and play.during == []


def test_messages_after_the_start_count_until_the_player_is_waited_for():
    got, _, cmds = run(voice_set(7) + START + text(0x30, 0x01) + text(0x31) + RETURN)
    first, _second = texts(cmds)
    (play,) = got.plays
    # the prompt's own message counts; the one after it may come after the end
    assert play.shown == [] and play.during == [first]


def test_timed_messages_do_not_wait_for_the_player():
    got, _, cmds = run(timed(True) + voice_set(7) + START + text(0x30, 0x01) + text(0x31)
                       + RETURN)
    (play,) = got.plays
    assert play.during == texts(cmds)


def test_end_wait_the_next_voice_and_a_disc_read_end_the_voice():
    for stop in (END_WAIT, voice_set(8), MUSIC):
        got, _, _ = run(voice_set(7) + START + stop + text(0x30) + RETURN)
        assert got.plays[0].during == [], stop


def test_a_start_with_no_voice_kept_plays_nothing():
    got, _, _ = run(text(0x30) + START + RETURN)
    assert got.plays == [] and got.kept == []


def test_a_call_runs_its_label_and_comes_back():
    got, starts, cmds = run(voice_set(7) + START + u16(es.LABEL_CALL, 2) + text(0x31) + RETURN,
                            text(0x30) + RETURN)
    callee, caller = starts[1], texts(cmds)[0]
    assert caller < callee
    (play,) = got.plays
    assert play.during == [callee, caller]
    (kept,) = got.kept
    assert (kept.voice, kept.labels) == (7, [1])


def test_a_label_that_calls_itself_is_walked_once_round(monkeypatch):
    # label 1 calls itself before its message: walked call within call, the
    # message is never reached and every round is a new stack (the guard
    # kept low so a walk that does that ends quickly)
    monkeypatch.setattr(sv, "MAX_STEPS", 2_000)
    got, starts, cmds = run(voice_set(7) + START + u16(es.LABEL_CALL, 1) + text(0x30) + RETURN)
    (play,) = got.plays
    assert play.during == texts(cmds)


def test_every_way_a_test_goes_is_taken():
    # label 1: a story test jumps to label 2, else keeps voice 7; both meet
    # one 0x53 in label 3
    got, starts, cmds = run(u16(0x0B, 2, 5, 0) + text(0x30) + voice_set(7) + u16(es.LABEL_JUMP, 3),
                            text(0x31, 0x03) + voice_set(8) + u16(es.LABEL_JUMP, 3),
                            START + RETURN)
    up = texts(cmds)[0]
    assert sorted((p.voice, p.shown) for p in got.plays) == [(7, [up]), (8, [])]
    assert {k.voice: k.labels for k in got.kept} == {7: [1], 8: [1, 2]}
    assert all(p.start_at == starts[2] for p in got.plays)


def test_the_label_end_takes_the_window_down():
    # label 2 runs on its own: nothing label 1 left up is shown there
    got, _, _ = run(text(0x30) + RETURN, voice_set(7) + START + RETURN)
    assert got.plays[0].shown == []


def test_a_message_that_clears_the_window_is_not_shown():
    notice = u16(0x20, 0)                  # an item taken: its notice takes the window
    got, _, _ = run(text(0x30) + notice + voice_set(7) + START + RETURN)
    assert got.plays[0].shown == []
