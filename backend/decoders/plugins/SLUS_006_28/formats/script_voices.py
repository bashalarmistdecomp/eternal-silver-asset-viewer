"""Where the scripts play their voices, and which messages are on screen
while one plays.

No table ties a voice to a message: the script plays a voice with its own
commands, among the message commands, and what the player sees while it
plays is whatever those commands leave in the message window. This module
follows a label's commands as ScriptLabelRun (0x80059FDC) runs them and
keeps, at every command, what the window shows and what the voice does.

**The voice.** Command 0x52 (ScriptCommandVoiceSet (0x8005E9FC)) first
waits out a voice still playing (it runs ScriptCommandVoiceEndWait
(0x8005EA8C)), then keeps its voice (VoiceSet (0x80055470):
g_VoiceKeptNumber). Command 0x53 (ScriptCommandVoiceStart (0x8005EA44))
starts the kept voice (VoiceStart (0x800554C4)); with none kept since the
label began (ScriptLabelRun sets g_Voice to 0) it hangs the game
(ScriptErrorHang, error 9). From then on the script goes on while the voice
plays: every frame it waits, ScriptFrameStep (0x8005A1F0) steps the voice
(ScriptVoiceStep (0x8005A328) -> VoiceStep (0x80055524)) until its sectors
are read. It ends there, or sooner:

- at 0x54 (ScriptCommandVoiceEndWait), which waits for its end, or at the
  next 0x52, which does the same;
- at a command that reads the disc (`READS_DISC`): cd_sector_load
  (0x80020E88) and pc_load (0x80021584) stop a playing voice first
  (VoiceStep(0));
- at the label's end, after which the label's messages are over.

**The window.** A message (command 0x02, ScriptCommandMessageDisp
(0x8005AB1C)) runs whole before the next command: its text is typed a
glyph at a time (MessageLineDisp (0x8005AD94)), each prompt (0xFF00,
MessageControlRun (0x8005AF20)) waits for the player — unless the script
has made its messages timed (0x55, ScriptCommandMessageTimedSet
(0x8005EB04)), when the wait ends by itself — and only a close (0xFF03,
MessageClose (0x8005A72C)) takes the window down. So a message that does
not close leaves its last words up for the commands after it, until the
next message, a command that puts something else in the window
(`CLEARS_WINDOW`), or the label's end (ScriptLabelRun closes the window).

**What goes with a voice**, for each 0x53 (a `Play`):

- `shown`: the message whose words are up as the voice starts;
- `during`: the messages that come up after it starts while nothing in the
  code has ended it yet — before 0x54, the next 0x52, a disc read or the
  label's end — and before the script has waited for the player (a
  prompt, a question, a shop): the voice may be over by the time the
  player moves on. The message whose prompt waits is itself counted.

A play with neither goes with no message: the voice plays over the scene.
Every way a label's tests can go is followed, as event_script.walk_label
follows them; a call (0x04) runs its label and comes back.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable

from . import event_script as es
from . import system_strings

VOICE_SET = 0x52            # ScriptCommandVoiceSet (0x8005E9FC): voice u8[c + 2]
VOICE_START = 0x53          # ScriptCommandVoiceStart (0x8005EA44)
VOICE_END_WAIT = 0x54       # ScriptCommandVoiceEndWait (0x8005EA8C)
MESSAGE_TIMED = 0x55        # ScriptCommandMessageTimedSet (0x8005EB04): on when u8[c + 2]

#: Commands whose handlers read the disc (resource_load -> cd_sector_load
#: (0x80020E88)), which stops a voice that plays: 0x1F, 0x22 an item given
#: with no room (MenuRun -> FaceListLoad), 0x23 a party member joining
#: (MapPartySpriteDataLoad), 0x27 a party move (MapPartyPlace), 0x2B a
#: battle (MapBtlRun), 0x2D a movie (MoviePlay, MovieScreenClose stops it
#: too), 0x30 a song (MusicPlay -> MusicBankLoad), 0x3E a portrait list
#: (FaceListByteLoad), 0x43 (MapPartySpriteDataLoad), 0x5C
#: (ScriptCommandStoryBitsItemsReset (0x8005EF58): resource 0xE7).
READS_DISC = frozenset({0x1F, 0x22, 0x23, 0x27, 0x2B, 0x2D, 0x30, 0x3E, 0x43, 0x5C})
#: Commands that wait for the player: a question (0x07, ScriptAnswerRun
#: (0x8005C198)), a shop (0x2E, ShopRun (0x80050694)), an item given with
#: no room (0x1F, 0x22: MenuRun).
WAITS_FOR_PLAYER = frozenset({es.ANSWER, 0x2E, 0x1F, 0x22})
#: Commands that put something else in the message window or set it up
#: again: a question (0x07, MessageAnswerRun (0x8005B6C0)), the notices of
#: money and items (0x1C, 0x1D: MessageNoticeNumberDisp (0x8005BA70);
#: 0x20: MessageNoticeItemDisp (0x8005BB6C)), an item given (0x1F, 0x22),
#: a battle (0x2B: MessageReset (0x80059F7C)), a movie (0x2D), a shop
#: (0x2E: MessageRecordsInit (0x8005A580)).
CLEARS_WINDOW = frozenset({es.ANSWER, 0x1C, 0x1D, 0x1F, 0x20, 0x22, es.BATTLE, 0x2D, 0x2E})
#: Commands after which the label runs on no more.
_ENDS = frozenset({es.LABEL_RETURN, es.SCENE_JUMP, es.MAP_CHANGE, es.SCRIPT_JUMP, 0x5E})
#: A walk's commands, at most: a guard, far above any label's.
MAX_STEPS = 200_000
#: Calls deep, at most: a guard, far above any script's. Past it, or into
#: a call already on the way (a label that calls itself), a call is walked
#: past: each time round would make a new stack, and the walk would never
#: see a place it had been.
MAX_CALLS = 32

PROOF = ("ScriptCommandVoiceSet (0x8005E9FC)", "ScriptCommandVoiceStart (0x8005EA44)",
         "ScriptCommandVoiceEndWait (0x8005EA8C)", "ScriptVoiceStep (0x8005A328)",
         "ScriptCommandMessageDisp (0x8005AB1C)", "MessageControlRun (0x8005AF20)",
         "ScriptCommandMessageTimedSet (0x8005EB04)")


# -- how a message leaves the window -------------------------------------------

@dataclass(frozen=True)
class TextEnd:
    """What a message command does to the window."""
    #: its waits for the player (0xFF00)
    prompts: int
    #: "text": its last words stay up; "page": the window stays open with
    #: its rows cleared (0xFF01); "closed" (0xFF03); "empty": it shows nothing
    left: str


def text_end(buf: bytes, offset: int, words, char_table: Callable[[int], int],
             table: bytes | None) -> TextEnd:
    """How message command 0x02 at `offset` leaves the window: its codes
    through font_string_walk (0x8005A884) as MessageControlRun takes them,
    a splice (0xF0nn-0xF6nn) walked from the string table `table` as the
    handler walks it (to four deep)."""
    state = {"left": "empty", "prompts": 0}

    def emit_char(_code: int) -> None:
        state["left"] = "text"

    def emit_ctl(code: int, depth: int = 0) -> None:
        hi = code & 0xFF00
        if hi in (0xF000, 0xF100, 0xF400, 0xF500, 0xF600):
            if table is None or depth >= 4:
                return
            at = system_strings.string_offset(table, code & 0xFFF)
            if at:
                system_strings.walk(table, at, words, char_table, emit_char,
                                    lambda c: emit_ctl(c, depth + 1))
        elif code == 0xFF00:
            state["prompts"] += 1
        elif code == 0xFF01:
            state["left"] = "page"
        elif code == 0xFF03:
            state["left"] = "closed"

    system_strings.walk(buf, offset + 2, words, char_table, emit_char, emit_ctl)
    return TextEnd(state["prompts"], state["left"])


# -- the voices a label plays ----------------------------------------------------

@dataclass
class Play:
    """One 0x53 of a script, reached with one 0x52's voice kept: the voice
    it starts and what goes with it."""
    voice: int
    #: the 0x52 that kept the voice, and the 0x53 that starts it
    set_at: int
    start_at: int
    #: the messages whose words can be up as it starts (by offset), and the
    #: labels whose run reaches it
    shown: list[int] = field(default_factory=list)
    during: list[int] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)

    @property
    def messages(self) -> list[int]:
        """`shown` then `during`, each once."""
        return list(dict.fromkeys(self.shown + self.during))


@dataclass
class Kept:
    """One 0x52 of a script: the voice it keeps, and the labels whose run
    reaches it."""
    offset: int
    voice: int
    labels: list[int] = field(default_factory=list)


@dataclass
class ScriptVoices:
    """What a script's labels do with voices, each in the order of the code."""
    kept: list[Kept]
    plays: list[Play]


@dataclass(frozen=True)
class _At:
    up: int | None = None               # the message whose words are up
    kept: tuple | None = None           # (voice, its 0x52)
    playing: tuple | None = None        # (voice, its 0x52, its 0x53)
    waited: bool = False                # the player was waited for since it started
    timed: bool = False


def voice_sets(buf: bytes, cmds: dict[int, es.Command]) -> list[tuple[int, int]]:
    """(offset, voice) of every 0x52 of a script, in the order of its code."""
    return [(o, c.u8(buf, 2)) for o, c in sorted(cmds.items()) if c.id == VOICE_SET]


def script_voices(buf: bytes, cmds: dict[int, es.Command], ends: dict[int, TextEnd],
                  script: int | None = None, labels: list[int] | None = None) -> ScriptVoices:
    """Every 0x52 and 0x53 the labels of a script reach, each 0x53 with
    what goes with it. `cmds` is the sweep's commands by offset
    (event_script.script_code), `ends` each message command's TextEnd by
    offset (a message missing from it counts as one that closes), `labels`
    the labels to run (all of the script's by default), `script` its
    number (the paged scripts' 0x07 asks nothing: event_script.PAGED)."""
    table = es.labels(buf)
    found: dict[tuple[int, int], Play] = {}     # by (its 0x53, its 0x52)
    kept: dict[int, Kept] = {}
    for label in (sorted(table) if labels is None else labels):
        _walk(buf, cmds, ends, table, label, script, found, kept)
    return ScriptVoices([kept[o] for o in sorted(kept)], [found[k] for k in sorted(found)])


def plays(buf: bytes, cmds: dict[int, es.Command], ends: dict[int, TextEnd],
          script: int | None = None, labels: list[int] | None = None) -> list[Play]:
    """`script_voices`' plays alone."""
    return script_voices(buf, cmds, ends, script, labels).plays


def _add(seq: list, item) -> None:
    if item not in seq:
        seq.append(item)


def _walk(buf, cmds, ends, table, label, script, found, kept) -> None:
    def target(n: int) -> int | None:
        at = table.get(n)
        return at if at in cmds else None

    start = target(label)
    if start is None:
        return
    # (offset, state, the calls to come back to)
    stack: list[tuple[int, _At, tuple]] = [(start, _At(), ())]
    seen: set = set()
    steps = 0
    while stack:
        at, st, calls = stack.pop()
        while at is not None:
            key = (at, st, calls)
            c = cmds.get(at)
            if c is None or key in seen or steps >= MAX_STEPS:
                break
            seen.add(key)
            steps += 1
            nxt: int | None = c.end
            ways: list[int | None] = []
            cid = c.id
            if cid == es.TEXT:
                te = ends.get(at, TextEnd(0, "closed"))
                if st.playing is not None and not st.waited:
                    _add(found[st.playing[2], st.playing[1]].during, at)
                waited = st.waited or (st.playing is not None and te.prompts > 0 and not st.timed)
                st = _At(at if te.left == "text" else None, st.kept, st.playing, waited, st.timed)
            elif cid == VOICE_SET:
                k = kept.get(at)
                if k is None:
                    k = kept[at] = Kept(at, c.u8(buf, 2))
                _add(k.labels, label)
                st = _At(st.up, (k.voice, at), None, False, st.timed)
            elif cid == VOICE_START:
                if st.kept is None:
                    break                   # ScriptErrorHang: the game stops here
                play = found.get((at, st.kept[1]))
                if play is None:
                    play = found[at, st.kept[1]] = Play(st.kept[0], st.kept[1], at)
                _add(play.labels, label)
                if st.up is not None:
                    _add(play.shown, st.up)
                st = _At(st.up, st.kept, (st.kept[0], st.kept[1], at), False, st.timed)
            elif cid == VOICE_END_WAIT:
                st = _At(st.up, st.kept, None, False, st.timed)
            elif cid == MESSAGE_TIMED:
                st = _At(st.up, st.kept, st.playing, st.waited, c.u8(buf, 2) != 0)
            if cid != es.TEXT:
                up = None if cid in CLEARS_WINDOW else st.up
                playing = None if cid in READS_DISC else st.playing
                waited = st.waited or (playing is not None and cid in WAITS_FOR_PLAYER)
                if (up, playing, waited) != (st.up, st.playing, st.waited):
                    st = _At(up, st.kept, playing, waited, st.timed)
            # the ways on, as event_script.walk_label takes them
            if cid == es.LABEL_JUMP:
                nxt = target(c.u16(buf, 2))
            elif cid == es.LABEL_CALL:
                if c.end not in calls and len(calls) < MAX_CALLS:
                    calls = calls + (c.end,)
                    nxt = target(c.u16(buf, 2))
            elif cid == es.LABEL_RETURN:
                nxt = calls[-1] if calls else None
                calls = calls[:-1]
            elif cid in _ENDS:
                nxt = None
            elif cid in es.TESTS or (cid == es.ANSWER and script not in es.PAGED):
                ways.append(target(c.u16(buf, 2)))
            elif cid == es.LABEL_PICK:
                p = c.offset + 2
                while p + 2 <= c.end and (n := struct.unpack_from("<H", buf, p)[0]):
                    ways.append(target(n))
                    p += 2
            elif cid == es.BATTLE and c.u16(buf, 2):
                ways.append(target(c.u16(buf, 2)))
            stack.extend((w, st, calls) for w in reversed(ways) if w is not None)
            at = nxt
