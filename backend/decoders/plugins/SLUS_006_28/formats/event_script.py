"""The map EVENT SCRIPT bytecode — a static walker.

A map's event script is a LUNADATA resource copied by ScriptResourceLoad (0x80020D20) to
`*g_ScriptBase (0x800B8B80)` (0x801DCB80, 0x9F80 bytes). The area record's byte 8 names
the script (`records.areas`, MapLoad (0x80068A10) -> ScriptChange(rec[8]) (0x80068D7C)), and
resource_pair_find (0x80020C58)(g_ScriptResourcePairs (0x800AF268), id) gives the resource.

**Layout.** The first u16s are the LABEL TABLE: label n (a u16 everywhere a
script names one) starts at byte `2 * u16[2n]` of the resource
(ScriptLabelRun (0x80059FDC): `g_ScriptCommandPointer (0x800B8BA0) = g_ScriptBase + u16[n] * 2`). The table ends where
the first label's code begins. The code is a stream of u16-aligned commands:
`g_ScriptCommandPointer` points at a u16 COMMAND ID, ScriptLabelRun dispatches
`g_ScriptCommandFunctions[id] (0x800B333C)` (97 handlers, ids 0..0x60; 0, 1, 6, 0x1B are the error
handler ScriptErrorHang (0x8005B568)) and each handler moves `g_ScriptCommandPointer` past its own
operands. This module is that movement, handler by handler, and nothing
else: each `_len_*` below cites the handler it transcribes.

**Operand helpers** (all absolute-address arithmetic; the buffer base is
4-aligned, so an offset has its address's alignment):

* `ScriptPointerAdvance(n) (0x8005B5B8)`: `BA0 = (BA0 & -n) + n`            -> `_align`
* `ScriptListCount(1, s) (0x8005B5D8)`: a byte list, step `s`, ends at a zero byte at `t`;
  the cursor goes to `t + 1` rounded up to even          -> `_list1`
* `ScriptListCount(2, 1)`: a u16 list ended by a zero word  -> `_list2`
* a conditional command keeps its JUMP LABEL at `+2`
  (ScriptCommandLabelJump (0x8005BF5C) reads `u16[BA0 + 2]`) and its operands from `+4`.

**What this decodes and what it cannot.** Because every jump target is a
label and every label starts a command, a linear sweep of the code area
from the first label sees every command the interpreter can ever reach;
no control-flow following is needed. A sweep is only as good as its
lengths, so `sweep()` reports where it STOPS and `label_boundaries()`
checks that every label is a command boundary of the sweep: a wrong length
cannot survive that for long. Anything the sweep cannot step over is
reported as an unresolved stop, never guessed through.

The BATTLE command is id 0x2B (ScriptCommandMapBtlRun (0x8005DFF0), battle.md §"The script's
BATTLE command"): `[2B 00][label u16][row+1 u8][restore u8][music u8][bgm
u8]`, `row + 1` indexing the 8-byte encounter rows at g_ScriptMapBtlRows (0x800B366C).

**SLPS_013.97.** The Japanese program's g_ScriptCommandFunctions
(SLPS_013.97 0x800B1738, ScriptLabelRun (0x80059FDC; SLPS_013.97
0x8005D3E8)) has 0x5F handlers: ids 0 to 0x5E are the US program's, their
operands moved alike, and 0x5F and 0x60 are not there (`command_count`).
Its handler 0x5E (SLPS_013.97 0x8006199C) returns at once. A message has
no runs (formats.system_strings): its walk is given no dictionary.
"""

from __future__ import annotations

import hashlib
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass

from . import system_strings
from .system_strings import WordLookup
from ..records import programs

EXE_BASE = 0x80011000

SCRIPT_TABLE_ADDR = 0x800AF268      # g_ScriptResourcePairs (0x800AF268): (s16 script id, s16 resource) pairs
ENCOUNTER_ROWS_ADDR = 0x800B366C    # g_ScriptMapBtlRows (0x800B366C): 8-byte rows, [0] = encounter id
ENCOUNTER_ROW_SIZE = 8
SCRIPT_BYTES = 0x9F80               # ScriptResourceLoad (0x80020D20)'s copy length

CMD_COUNT = 0x61
#: SLPS_013.97's g_ScriptCommandFunctions (SLPS_013.97 0x800B1738): 0x5F handlers.
JP_CMD_COUNT = 0x5F
ERROR_COMMANDS = (0, 1, 6, 0x1B)    # handler table -> ScriptErrorHang (0x8005B568)
TEXT = 0x02
BATTLE = 0x2B
SPELL_SET = 0x59                    # ScriptCommandChrSpellSet (0x8005EE30): u8[c + 2] keeps spell u8[c + 3]
SHOP_RUN = 0x2E                     # ScriptCommandShopRun (0x8005E384): ShopRun (0x80050694)(u8[c + 2])
SET_LOCATION = 0x49                 # ScriptCommandPlaceNameSet (0x8005E9D4): g_MapPlaceName (0x800B8CD8) = u8[c + 2]
SCRIPT_JUMP = 0x42                  # ScriptCommandScriptChange (0x8005BFCC): run script u8[c + 4], label u16[c + 2]
MAP_CHANGE = 0x5D                   # ScriptCommandMapScriptChange (0x8005F068)
SCENE_JUMP = 0x26                   # ScriptCommandMapChange (0x8005DB3C)
SCENE_INLINE = 0x27                 # ScriptCommandMapPartyPlace (0x8005DCBC)
SPAWN = 0x34                        # ScriptCommandMoveChrRowActorSet (0x80061EAC)
PARTY_KIND_SET = 0x48               # ScriptCommandMapPartyKindSet (0x8005E890)
PARTY_KIND_NOT_ONE = 3              # ... whose c[2] of 3 sets g_MapPartyWalkStepCount instead
SPAWN_OWN_FROM = 0xB                # its slots from 0xB make an actor of their own


class WalkError(Exception):
    """The sweep met something it cannot step over."""


def _align(n: int, p: int) -> int:
    return (p & -n) + n


def _list1(buf: bytes, p: int, step: int) -> int:
    """ScriptListCount(1, step) (0x8005B5D8) from p: the cursor after the zero byte, even."""
    t = p
    while t < len(buf) and buf[t] != 0:
        t += step
    if t >= len(buf):
        raise WalkError("unterminated byte list")
    return (t | 1) + 1


def _list2(buf: bytes, p: int) -> int:
    """ScriptListCount(2, 1) (0x8005B5D8) from p: a u16 list ended by a zero word."""
    t = p
    while t + 2 <= len(buf) and struct.unpack_from("<H", buf, t)[0] != 0:
        t += 2
    if t + 2 > len(buf):
        raise WalkError("unterminated word list")
    return t + 2


def text_end(buf: bytes, p: int, words: WordLookup | None) -> int:
    """font_string_walk (0x8005A884)'s stop pointer, run from `p`: the
    position `system_strings.walk` answers, the codes dropped
    (system_strings.walk_end; `words` is the dictionary's reader,
    system_strings.Words)."""
    try:
        return system_strings.walk_end(buf, p, words)
    except ValueError as e:
        raise WalkError("text runs off the resource") from e


def _text(buf, c, words):
    r = text_end(buf, c + 2, words)
    v = r + 1
    return v + 1 if v & 1 else v


def _select(buf, c, words):
    """ScriptAnswerRun (0x8005C198) / ScriptPagesRun (0x8005C2C0) (both read the same entry): [07][label]
    [u8][pad], then two 0xFF-terminated strings (ScriptStringEndFind(0) (0x8005C144) then
    (1): the second end rounded up to even)."""
    def scan(p, even):
        while p < len(buf) and buf[p] != 0xFF:
            p += 1
        if p >= len(buf):
            raise WalkError("select string runs off the resource")
        p += 1
        return p + 1 if even and p & 1 else p
    return scan(scan(_align(2, c + 4), False), True)


def _spawn(buf, c, words):
    """ScriptCommandMoveChrRowActorSet (0x80061EAC) (0x34): slot = u8[c + 2]; below 0xB the
    operands are 4 bytes, otherwise next = c + 0x10."""
    return c + (4 if buf[c + 2] < 0xB else 0x10)


def _entity(buf, c, words):
    """ScriptCommandMoveChrCommandsSet (0x80062534) (0x38): [38][slot] then movement opcodes 0xF0..
    until 0xF9; F0/F1/F2/F5/F6 take 2 bytes, F3/F4/F7 five, F8 four."""
    p = c + 3
    while True:
        if p >= len(buf):
            raise WalkError("entity script runs off the resource")
        b = buf[p]
        if b == 0xF9:
            break
        d = b - 0xF0
        if d in (0, 1, 2, 5, 6):
            p += 2
        elif d in (3, 4, 7):
            p += 5
        elif d == 8:
            p += 4
        else:
            raise WalkError(f"entity opcode {b:#x}")
    return p + 1 if p & 1 else p + 2


def _scene_inline(buf, c, words):
    """ScriptCommandMapPartyPlace (0x8005DCBC) (0x27): flag u8[c + 2]; 0 = an inline 11-byte entry."""
    return c + (0xE if buf[c + 2] == 0 else 4)


def _scene_jump(buf, c, words):
    """ScriptCommandMapChange (0x8005DB3C) (0x26): [cmd][label][a0][b][...]; a0 == 0 = inline
    entry (11 bytes from c + 6, the parameter byte at c + 0x11)."""
    return c + (0x12 if buf[c + 4] == 0 else 8)


def _p(n):
    return lambda buf, c, words: c + n


def _l1(off, step=1):
    return lambda buf, c, words: _list1(buf, c + off, step)


def _l2(off):
    return lambda buf, c, words: _list2(buf, c + off)


def _a4(buf, c, words):
    """Ids 0x1C..0x1E (ScriptCommandMoneyAdd, ScriptCommandMoneyTake,
    ScriptCommandMoneyAboveJump): operand word at the next 4-aligned address."""
    return _align(4, c + 2) + 4


#: id -> end-of-command function. Every line cites its handler.
_LEN = {
    0x02: _text,                      # ScriptCommandMessageDisp (0x8005AB1C)
    0x03: _p(4),                      # ScriptCommandLabelJump (0x8005BF5C): [cmd][label]
    0x04: _p(4),                      # ScriptCommandLabelCall (0x8005C06C): return = c + 4
    0x05: _p(2),                      # ScriptCommandLabelReturn (0x8005C0E4)
    0x07: _select,                    # ScriptCommandAnswerRun (0x8005C42C): two answers or the paged form
    0x08: _l2(2),                     # ScriptCommandLabelPick (0x8005C470)
    0x09: _l2(2),                     # ScriptCommandStoryBitsSet (0x8005C504)
    0x0A: _l2(2),                     # ScriptCommandStoryBitsClear (0x8005C570)
    0x0B: _l2(4),                     # ScriptCommandStoryBitsAllCheck (0x8005C5DC): label + words
    0x0C: _l2(4),                     # ScriptCommandStoryBitsNoneCheck (0x8005C684): label + words
    0x0D: _l2(4),                     # ScriptCommandStoryBitsAnyCheck (0x8005C72C): label + words
    0x0E: _l1(2),                     # ScriptCommandStoryBits580Set (0x8005C7D4)
    0x0F: _l1(2),                     # ScriptCommandStoryBits580Clear (0x8005C844)
    0x10: _l1(4),                     # ScriptCommandStoryBits580AllCheck (0x8005C8B4): label + bytes
    0x11: _l1(4),                     # ScriptCommandStoryBits580NoneCheck (0x8005C960): label + bytes
    0x12: _l1(4),                     # ScriptCommandStoryBits580AnyCheck (0x8005CA0C): label + bytes
    0x13: _l1(2, 2),                  # ScriptCommandStoryBitPairsSet (0x8005CAB8): byte pairs
    0x14: _l1(2, 2),                  # ScriptCommandStoryBitPairsClear (0x8005CB38): byte pairs
    0x15: _l1(4, 2),                  # ScriptCommandStoryBitPairsAllCheck (0x8005CBB8)
    0x16: _l1(4, 2),                  # ScriptCommandStoryBitPairsNoneCheck (0x8005CC74)
    0x17: _l1(4, 2),                  # ScriptCommandStoryBitPairsAnyCheck (0x8005CD30)
    0x18: _l1(2),                     # ScriptCommandStoryBits480Set (0x8005CDEC)
    0x19: _l1(2),                     # ScriptCommandStoryBits480Clear (0x8005CE5C)
    0x1A: _l1(2, 2),                  # ScriptCommandStoryBitPairs2620Set (0x8005CECC)
    0x1C: _a4,                        # ScriptCommandMoneyAdd (0x8005CF6C)
    0x1D: _a4,                        # ScriptCommandMoneyTake (0x8005CFF8)
    0x1E: _a4,                        # ScriptCommandMoneyAboveJump (0x8005D078)
    0x1F: _p(4),                      # ScriptCommandChrItemGive (0x8005D0E0)
    0x20: _p(4),                      # ScriptCommandChrItemRemove (0x8005D164)
    0x21: _p(6),                      # ScriptCommandChrItemHeldJump (0x8005D1CC)
    0x22: _p(6),                      # ScriptCommandChrLevelItemSet (0x8005D2F0)
    0x23: _p(4),                      # ScriptCommandPartyJoin (0x8005D60C)
    0x24: _p(6),                      # ScriptCommandPartyLeave (0x8005D70C)
    0x25: _l1(2),                     # ScriptCommandMapObjectsRemove (0x8005D9D4)
    0x26: _scene_jump,                # ScriptCommandMapChange (0x8005DB3C)
    0x27: _scene_inline,              # ScriptCommandMapPartyPlace (0x8005DCBC)
    0x28: _p(4),                      # ScriptCommandMapBgChangeStart (0x8005DD84)
    0x29: _p(4),                      # ScriptCommandMapFadeOut (0x8005DE88)
    0x2A: _p(4),                      # ScriptCommandMapFadeIn (0x8005DF08)
    0x2B: _p(8),                      # ScriptCommandMapBtlRun (0x8005DFF0): BATTLE
    0x2C: _p(6),                      # ScriptCommandMapViewShakeStart (0x8005E274)
    0x2D: _p(6),                      # ScriptCommandMoviePlay (0x8005E2B4)
    0x2E: _p(4),                      # ScriptCommandShopRun (0x8005E384)
    0x2F: _p(2),                      # ScriptCommandPartyHpMpFill (0x8005E3D0)
    0x30: _p(4),                      # ScriptCommandMusicPlay (0x8005E494)
    0x31: _p(4),                      # ScriptCommandSoundPlay (0x8005E524)
    0x32: _p(2),                      # ScriptCommandMoveChrCommandsStart (0x80061C54)
    0x33: _p(4),                      # ScriptCommandMoveChrRowsAllEnd (0x80061CF8)
    0x34: _spawn,                     # ScriptCommandMoveChrRowActorSet (0x80061EAC)
    0x35: _l1(2),                     # ScriptCommandMoveChrRowsEnd (0x80062314)
    0x36: _l1(2),                     # ScriptCommand36Skip (0x800624DC)
    0x37: _l1(2),                     # ScriptCommand37Skip (0x80062508)
    0x38: _entity,                    # ScriptCommandMoveChrCommandsSet (0x80062534)
    0x39: _p(2),                      # ScriptCommandMoveChrPartyFollowStart (0x80062640)
    0x3A: _p(2),                      # ScriptCommandMoveChrPartyFollowEnd (0x80062680)
    0x3B: _p(2),                      # ScriptCommandMoveChrAttributeCheckOn (0x800628C4)
    0x3C: _p(2),                      # ScriptCommandMoveChrAttributeCheckOff (0x800628E0)
    0x3D: lambda buf, c, words: (c & -4) + 8,  # ScriptCommandMoveChrCommandEndWait (0x80062984)
    0x3E: _l1(2),                     # ScriptCommandFaceListSet (0x8005E610)
    0x3F: _p(2),                      # ScriptCommandMoveChrViewFollowStart (0x800628F8)
    0x40: _p(2),                      # ScriptCommandMoveChrViewFollowEnd (0x8006293C)
    0x41: _l1(2),                     # ScriptCommandMapObjectsAdd (0x8005D7E0)
    0x42: _p(6),                      # ScriptCommandScriptChange (0x8005BFCC): [cmd][label][script id]
    0x43: _p(4),                      # ScriptCommandChr1ChrBChange (0x8005D470)
    0x44: _p(4),                      # ScriptCommandMapDrawAreaClose (0x8005DF58)
    0x45: _p(4),                      # ScriptCommandMapDrawAreaOpen (0x8005DFA4)
    0x46: _p(6),                      # ScriptCommandMapColSet (0x8005DDC4)
    0x47: _p(4),                      # ScriptCommandColMix (0x8005DE54)
    0x48: _p(4),                      # ScriptCommandMapPartyKindSet (0x8005E890)
    0x49: _p(4),                      # ScriptCommandPlaceNameSet (0x8005E9D4)
    0x4A: _l1(2),                     # ScriptCommand4ASkip (0x800629B8)
    0x4B: _l1(2),                     # ScriptCommand4BSkip (0x800629E4)
    0x4C: _p(2),                      # ScriptCommandMoveChrSecondViewFollowStart (0x80062A10)
    0x4D: _p(2),                      # ScriptCommandMoveChrSecondViewFollowEnd (0x80062A54)
    0x4E: _l1(2),                     # ScriptCommandMixGroupSet (0x80062ACC)
    0x4F: _l1(2),                     # ScriptCommandMixGroupClear (0x80062C38)
    0x50: _p(6),                      # ScriptCommandMixGroupFadeStart (0x80062E00)
    0x51: _p(2),                      # ScriptCommandMixFadeWait (0x80062EBC)
    0x52: _p(4),                      # ScriptCommandVoiceSet (0x8005E9FC)
    0x53: _p(2),                      # ScriptCommandVoiceStart (0x8005EA44)
    0x54: _p(2),                      # ScriptCommandVoiceEndWait (0x8005EA8C)
    0x55: _p(4),                      # ScriptCommandMessageTimedSet (0x8005EB04)
    0x56: _p(4),                      # ScriptCommandMapPadDirectionsChange (0x8005EB98)
    0x57: _p(4),                      # ScriptCommandChrLevelGapAdd (0x8005EC30)
    0x58: _p(2),                      # ScriptCommandPartyMpHalve (0x8005ECC8)
    0x59: _p(4),                      # ScriptCommandChrSpellSet (0x8005EE30)
    0x5A: _p(4),                      # ScriptCommandMusicLevelSet (0x8005E5A4)
    0x5B: _p(2),                      # ScriptCommandPartyMpClear (0x8005EEE0)
    0x5C: _p(2),                      # ScriptCommandStoryBitsItemsReset (0x8005EF58)
    0x5D: _p(0x12),                   # ScriptCommandMapScriptChange (0x8005F068)
    0x5E: _p(2),                      # ScriptCommandGameEnterRequest (0x8005F1A8)
    0x5F: _p(4),                      # ScriptCommandActuatorLevelsSet (0x8005D23C)
    0x60: _p(4),                      # ScriptCommandActuatorListStart (0x8005D294)
}

#: commands after which the interpreter never falls through (the sweep
#: still continues: the next label may begin there).
TERMINAL = frozenset({0x03, 0x05, 0x26, 0x42, 0x5D, 0x5E})


@dataclass(frozen=True)
class Command:
    offset: int
    id: int
    end: int

    def u8(self, buf: bytes, at: int) -> int:
        return buf[self.offset + at]

    def u16(self, buf: bytes, at: int) -> int:
        return struct.unpack_from("<H", buf, self.offset + at)[0]


def script_resources(image: bytes) -> dict[int, int]:
    """resource_pair_find (0x80020C58) over g_ScriptResourcePairs (0x800AF268): script id -> resource (first match)."""
    out: dict[int, int] = {}
    o = programs.address(image, "g_ScriptResourcePairs", SCRIPT_TABLE_ADDR) - EXE_BASE
    while o + 4 <= len(image):
        sid, res = struct.unpack_from("<hh", image, o)
        if res == 0:
            break
        out.setdefault(sid, res)
        o += 4
    return out


def labels(buf: bytes) -> dict[int, int]:
    """label n -> byte offset (0 = unused). The table ends where the first
    label's code begins."""
    words = struct.unpack_from(f"<{len(buf) // 2}H", buf, 0)
    out: dict[int, int] = {}
    low = len(buf)                      # lowest label target so far
    n = 1
    while 2 * n < low and n < len(words):
        if words[n]:
            out[n] = 2 * words[n]
            low = min(low, 2 * words[n])
        n += 1
    return out


def command_count(image: bytes) -> int:
    """How many handlers `image`'s program's g_ScriptCommandFunctions has."""
    return JP_CMD_COUNT if programs.program_of(image) == programs.JP else CMD_COUNT


def sweep(buf: bytes, start: int, words: WordLookup | None,
          commands: int = CMD_COUNT) -> tuple[list[Command], str | None]:
    """Linear walk from `start`. Returns (commands, why it stopped) —
    why is None when it ran off the end, else a short reason (an error
    command id, an unknown id, or a WalkError). `words` is the dictionary
    a message's run reads (system_strings.Words; None for a program with
    none), `commands` the program's handler count (`command_count`)."""
    out: list[Command] = []
    c = start
    while c + 2 <= len(buf):
        cid = struct.unpack_from("<H", buf, c)[0]
        if cid in ERROR_COMMANDS or cid >= commands:
            return out, f"command {cid:#x} at {c:#x}"
        try:
            end = _LEN[cid](buf, c, words)
        except WalkError as exc:
            return out, f"{exc} at {c:#x}"
        except IndexError:
            return out, f"operand past the resource at {c:#x}"
        out.append(Command(c, cid, end))
        c = end
    return out, None


@dataclass(frozen=True)
class Gap:
    """Bytes the sweep did not decode, between a stop and the next label.

    `kind`: "end" (the zero padding after the last command), "filler"
    (only 0x00 / 0xFF bytes), "dead" (the command before it falls through
    into an invalid id, so the interpreter faults there — no label lies in
    the gap, so nothing can reach it), or "unresolved" (a length this
    module could not compute: WalkError)."""
    start: int
    end: int
    kind: str
    reason: str


#: The last scripts swept (`script_code`), by the sha1 of their bytes, the
#: dictionary's key (system_strings.Words.key) and the command count: the
#: maps, the dialogue and the links each sweep every script, on each disc
#: of a game, and the same bytes are swept once while they are kept.
KEEP_SWEPT = 512
_swept: OrderedDict[tuple, tuple] = OrderedDict()
_swept_lock = threading.Lock()


def script_code(buf: bytes, words: WordLookup | None,
                commands: int = CMD_COUNT) -> tuple[list[Command], list[Gap]]:
    """Sweep the whole code area: from the lowest label, and — after any
    stop — again from the next label past it (labels are the only entry
    points, so nothing between a stop and the next label can run).

    A script swept before with the same bytes, dictionary and command count
    is not swept again (`_swept`; a dictionary reader with no `key` is
    always swept)."""
    wkey = None if words is None else getattr(words, "key", None)
    if words is not None and wkey is None:
        return _script_code(buf, words, commands)
    key = (hashlib.sha1(buf).digest(), commands, wkey)
    with _swept_lock:
        got = _swept.get(key)
        if got is not None:
            _swept.move_to_end(key)
    if got is None:
        cmds, gaps = _script_code(buf, words, commands)
        got = (tuple(cmds), tuple(gaps))
        with _swept_lock:
            _swept[key] = got
            while len(_swept) > KEEP_SWEPT:
                _swept.popitem(last=False)
    return list(got[0]), list(got[1])


def _script_code(buf: bytes, words: WordLookup | None,
                 commands: int) -> tuple[list[Command], list[Gap]]:
    """`script_code`, swept every time."""
    lab = labels(buf)
    if not lab:
        return [], []
    starts = sorted(set(lab.values()))
    cmds: list[Command] = []
    gaps: list[Gap] = []
    pos = starts[0]
    while True:
        seg, why = sweep(buf, pos, words, commands)
        cmds.extend(seg)
        stop = seg[-1].end if seg else pos
        if why is None:
            break
        nxt = next((o for o in starts if o > stop), None)
        end = nxt if nxt is not None else len(buf)
        body = buf[stop:end]
        if not any(body):
            kind = "end" if nxt is None else "filler"
        elif all(b in (0, 0xFF) for b in body):
            kind = "filler"
        elif why.startswith("command "):
            kind = "dead"
        else:
            kind = "unresolved"
        gaps.append(Gap(stop, end, kind, why))
        if nxt is None:
            break
        pos = nxt
    return cmds, gaps


def label_boundaries(buf: bytes, cmds: list[Command]) -> dict[int, int]:
    """label -> offset, for labels that are NOT command boundaries of the
    sweep (a wrong length shows up here). A label at or past the end of the
    last command is the script's end sentinel (label 999 in scripts 7 and 8
    points at the first zero word after the code), not a length error."""
    if not cmds:
        return {}
    bounds = {c.offset for c in cmds}
    end = cmds[-1].end
    return {n: o for n, o in labels(buf).items() if o not in bounds and o < end}


# -- following a label --------------------------------------------------------

LABEL_JUMP = 0x03                   # ScriptCommandLabelJump (0x8005BF5C): to label u16[c + 2]
LABEL_CALL = 0x04                   # ScriptCommandLabelCall (0x8005C06C): label u16[c + 2], back to c + 4
LABEL_RETURN = 0x05                 # ScriptCommandLabelReturn (0x8005C0E4): back to the caller, or the end
ANSWER = 0x07                       # ScriptAnswerRun (0x8005C198): answer 1 jumps to label u16[c + 2]
LABEL_PICK = 0x08                   # ScriptCommandLabelPick (0x8005C470): rng_draw picks one
#: The commands that jump to their label u16[c + 2] when their test holds
#: and fall through when not, each by way of ScriptCommandLabelJump: the
#: story-flag checks (ScriptCommandStoryBitsAllCheck (0x8005C5DC) and its
#: kin), ScriptCommandMoneyAboveJump (0x8005D078), ScriptCommandChrItemHeldJump
#: (0x8005D1CC).
TESTS = frozenset({0x0B, 0x0C, 0x0D, 0x10, 0x11, 0x12, 0x15, 0x16, 0x17, 0x1E, 0x21})
#: Scripts whose command 0x07 shows pages instead of asking
#: (ScriptCommandAnswerRun (0x8005C42C): ScriptPagesRun for 0 and 0xC8).
PAGED = frozenset({0, 0xC8})


@dataclass
class LabelWalk:
    """What running a label can reach, every way its tests can go."""
    #: the commands reached, in the order a depth-first walk meets them,
    #: falling through before jumping
    reached: list[int]
    #: the text commands among them, in that order
    texts: list[int]
    #: (script id, label) another script is run from (command 0x42)
    handed_over: list[tuple[int, int]]
    #: labels the walk could not follow: not in the table, or not a command
    #: of the sweep
    lost: list[int]


def walk_label(buf: bytes, cmds: dict[int, Command], label: int,
               script: int | None = None, table: dict[int, int] | None = None) -> LabelWalk:
    """Every command running `label` of a script can reach (ScriptLabelRun
    (0x80059FDC) from the label's offset), following each command's ways on
    as its handler has them:

    - a jump goes to its label; a call goes to its label and, once that
      returns, on to the next command; a return ends the way;
    - a test (`TESTS`), a question (0x07; in the paged scripts it only shows
      pages) and a pick (0x08: any label of its list, or on) go both ways;
    - a BATTLE (0x2B, ScriptCommandMapBtlRun (0x8005DFF0)) goes to its label
      when it is won (label 0 ends the script there), ends the script when
      the battle says 2, and otherwise goes on;
    - a map change (0x26, 0x5D), another script (0x42: noted in
      `handed_over`) and command 0x5E end the way.

    `cmds` is the sweep's commands by offset (script_code); `table` the
    script's labels (labels), when the caller has them."""
    table = labels(buf) if table is None else table
    reached: list[int] = []
    texts: list[int] = []
    handed: list[tuple[int, int]] = []
    lost: list[int] = []
    seen: set[int] = set()

    def target(n: int) -> int | None:
        at = table.get(n)
        if at is None or at not in cmds:
            if n not in lost:
                lost.append(n)
            return None
        return at

    start = target(label)
    stack = [start] if start is not None else []
    while stack:
        at = stack.pop()
        while at is not None and at not in seen:
            c = cmds.get(at)
            if c is None:
                break
            seen.add(at)
            reached.append(at)
            ways: list[int | None] = []
            nxt: int | None = c.end
            if c.id == TEXT:
                texts.append(at)
            elif c.id == LABEL_JUMP:
                nxt = target(c.u16(buf, 2))
            elif c.id == LABEL_CALL:
                ways.append(target(c.u16(buf, 2)))
            elif c.id in (LABEL_RETURN, SCENE_JUMP, MAP_CHANGE, 0x5E):
                nxt = None
            elif c.id == SCRIPT_JUMP:
                handed.append((c.u8(buf, 4), c.u16(buf, 2)))
                nxt = None
            elif c.id in TESTS or (c.id == ANSWER and script not in PAGED):
                ways.append(target(c.u16(buf, 2)))
            elif c.id == LABEL_PICK:
                p = c.offset + 2
                while p + 2 <= c.end and (n := struct.unpack_from("<H", buf, p)[0]):
                    ways.append(target(n))
                    p += 2
            elif c.id == BATTLE and c.u16(buf, 2):
                ways.append(target(c.u16(buf, 2)))
            # the other ways are walked after this one, nearest first
            stack.extend(w for w in reversed(ways) if w is not None)
            at = nxt
    return LabelWalk(reached, texts, handed, lost)


def battles(buf: bytes, cmds: list[Command]) -> list[dict]:
    """Every BATTLE command (id 0x2B): its offset, label and encounter row."""
    out = []
    for c in cmds:
        if c.id == BATTLE:
            out.append({"offset": c.offset, "label": c.u16(buf, 2),
                        "row": c.u8(buf, 4), "restore": c.u8(buf, 5),
                        "music": c.u8(buf, 6), "bgm": c.u8(buf, 7)})
    return out


def spells_given(buf: bytes, cmds) -> list[tuple[int, int]]:
    """(id, spell) for every command 0x59 (ScriptCommandChrSpellSet
    (0x8005EE30)): it keeps the spell among the character's own."""
    return [(c.u8(buf, 2), c.u8(buf, 3)) for c in cmds if c.id == SPELL_SET]


def shop_runs(buf: bytes, cmds) -> list[tuple[int, int]]:
    """(offset, shop) for every command 0x2E: ScriptCommandShopRun
    (0x8005E384) hands the byte after its command word to ShopRun
    (0x80050694), the shop's number (records.shops)."""
    return [(c.offset, c.u8(buf, 2)) for c in cmds if c.id == SHOP_RUN]


def scene_changes(buf: bytes, cmds: list[Command]) -> list[dict]:
    """Every scene change a script asks MapChange (0x8005922C) for: commands 0x26
    (ScriptCommandMapChange, 0x8005DB3C) and 0x5D (ScriptCommandMapScriptChange, 0x8005F068).

    Both build the 11-byte scene entry from the command's own bytes —
    `e.b[0] = c[6]` the destination map, `e.b[1] = c[0x10]` the OBJECT SET
    it spawns (MapObjectsInit, 0x800655C8), the other nine from c[7]..c[0xF] — and pass
    it with index 0. A 0x26 whose c[4] is not 0 passes that index instead:
    MapChange reads row c[4] of the CURRENT map's scene table, the 11-byte
    rows at g_MapEnterTable (0x800B8D04) that the map resource's command 9 fills
    (docs/spec/code/subsystems/npc-scripting.md §"A map's object definitions come
    from its object set, not its map file"), and the command then carries no
    entry of its own (`map` and `object_set` are None).

    -> {"offset", "id", "entry", "map", "object_set"} per command. This is
    the one way a map can be entered with a set no scene table names."""
    out = []
    for c in cmds:
        if c.id == SCENE_JUMP and c.u8(buf, 4) != 0:
            out.append({"offset": c.offset, "id": c.id, "entry": c.u8(buf, 4),
                        "map": None, "object_set": None})
        elif c.id in (SCENE_JUMP, MAP_CHANGE):
            out.append({"offset": c.offset, "id": c.id, "entry": 0,
                        "map": c.u8(buf, 6), "object_set": c.u8(buf, 0x10)})
    return out


@dataclass(frozen=True)
class ActorSpawn:
    """A command 0x34 whose slot is 0xB or more: ScriptCommandMoveChrRowActorSet
    (0x80061EAC) makes actor slot - 0xB of g_MoveChrOwnActors from the
    command's own bytes and MapRecordInit (0x80065940)(actor, kind, mode,
    sprite data) gives it its draw word (`map_object_sets.record_draw`).
    A sprite data number below 0xF also makes a twin on
    g_MapTwinSpriteDataNumbers (0x80012C00)[number - 1], same kind and mode."""
    offset: int
    slot: int               # c[2]
    sprite_data: int        # c[3]: the g_MapSpriteDataEntries (0x800B8C68) number
    kind: int               # c[4]
    x: int                  # c[5], 8-pixel units
    y: int                  # c[6], 8-pixel units: the ground y
    height: int             # c[7]: taken off the drawn y
    facing: int             # c[8]
    layer: int              # c[9]
    mode: int               # c[0xA]


def actor_spawns(buf: bytes, cmds: list[Command]) -> list[ActorSpawn]:
    """Every command 0x34 that makes an actor of its own (slot 0xB or
    more; a lower slot takes a map object that is already there)."""
    out = []
    for c in cmds:
        if c.id != SPAWN or c.u8(buf, 2) < SPAWN_OWN_FROM:
            continue
        b = buf[c.offset + 2:c.offset + 0xB]
        out.append(ActorSpawn(c.offset, *b))
    return out


def script_switches(buf: bytes, cmds: list[Command]) -> list[tuple[int, int | None]]:
    """The scripts a script hands over to: (script, map) for command 0x5D
    (ScriptCommandMapScriptChange (0x8005F068): ScriptChange(c[4]) after
    MapChange to map c[6]) and (script, None) for command 0x42
    (ScriptCommandScriptChange (0x8005BFCC): ScriptChange(c[4]) on the map
    it is on)."""
    out = []
    for c in cmds:
        if c.id == MAP_CHANGE:
            out.append((c.u8(buf, 4), c.u8(buf, 6)))
        elif c.id == SCRIPT_JUMP:
            out.append((c.u8(buf, 4), None))
    return out


def party_kinds_set(buf: bytes, cmds: list[Command]) -> set[int]:
    """The party kinds the script's commands 0x48 set: c[2]
    (ScriptCommandMapPartyKindSet (0x8005E890) makes it g_MapPartyKind
    (0x800B8CEE); 3 is not a kind, it sets g_MapPartyWalkStepCount)."""
    return {c.u8(buf, 2) for c in cmds
            if c.id == PARTY_KIND_SET and c.u8(buf, 2) != PARTY_KIND_NOT_ONE}


def map_scripts(entered: dict[int, int],
                switches: dict[int, list[tuple[int, int | None]]]) -> dict[int, set[int]]:
    """map -> every script that can run on it: the one MapSet (0x80068780)
    takes from the map's area record (`entered`: map -> script), the ones a
    0x5D hands the map to, and, from those, every script a 0x42 hands over
    to (`switches`: script -> `script_switches`). Read off the commands
    alone: whether a story ever takes a path is not."""
    out: dict[int, set[int]] = {m: {s} for m, s in entered.items()}
    for moves in switches.values():
        for script, m in moves:
            if m is not None:
                out.setdefault(m, set()).add(script)
    for scripts in out.values():
        todo = list(scripts)
        while todo:
            for script, m in switches.get(todo.pop(), ()):
                if m is None and script not in scripts:
                    scripts.add(script)
                    todo.append(script)
    return out


def encounter_row(image: bytes, row: int) -> int:
    """g_ScriptMapBtlRows (0x800B366C) row `row` (the command's operand is row + 1): its [0],
    the encounter id."""
    if row < 1:
        raise ValueError("BATTLE rows are 1-based (operand = row + 1)")
    base = programs.address(image, "g_ScriptMapBtlRows", ENCOUNTER_ROWS_ADDR)
    return image[base - EXE_BASE + (row - 1) * ENCOUNTER_ROW_SIZE]


#: The rows end where the next table begins (g_FontStringWords (0x800B386C), the
#: dictionary of words): 64 rows. A layout reading — the code bounds the row only by
#: the u8 operand it reads it from. In SLPS_013.97 they end at 0x800B1C60, where the
#: table ScriptLabelRun (SLPS_013.97 0x8005D3E8) also reads begins: 64 rows too.
ENCOUNTER_ROW_COUNT = (system_strings.WORDS_ADDR - ENCOUNTER_ROWS_ADDR) // ENCOUNTER_ROW_SIZE


@dataclass(frozen=True)
class EncounterRow:
    """One 8-byte row of g_ScriptMapBtlRows (0x800B366C), as ScriptCommandMapBtlRun (0x8005DFF0) (matching C) reads it."""
    row: int                # the BATTLE command's operand: the 1-based row
    encounter: int          # [0] -> MapBtlRun (0x8007AE58) arg0, the encounter id
    x_shift: int            # [1] -> MapBtlRun (0x8007AE58) arg1: subtracted from each
                            #   member's place x as it is copied to g_BtlPartyPlaceXCells (0x800B8E88)
    party: tuple[int, ...]  # [2..7] up to the first 0: the fight's own party
                            #   list (empty = the field party g_PartyIds (0x800B8BC0))

    def slot_ids(self) -> tuple[int, ...] | None:
        """g_BtlSlotIds (0x800E48E0) slots 0..5 as ScriptCommandMapBtlRun (0x8005DFF0)
        fills them from the row's own list: id 0xC to slot 5, every other id
        in order from slot 0. None when the row has no list (the field party)."""
        if not self.party:
            return None
        slots, n = [0] * 6, 0
        for cid in self.party:
            if cid == 0xC:
                slots[5] = cid
            else:
                slots[n] = cid
                n += 1
        return tuple(slots)


def encounter_rows(image: bytes) -> list[EncounterRow]:
    """Every row of g_ScriptMapBtlRows (0x800B366C) that names an encounter (byte 0 != 0), in table order.

    ScriptCommandMapBtlRun (0x8005DFF0): `p = g_ScriptMapBtlRows + (operand - 1) * 8; enc = *p++; arg1 =
    *p++;` then, when `*p` is 0, the party list g_BtlSlotIds (0x800E48E0) is filled from the
    field party, else from the row's own bytes — up to six, to the first 0,
    id 0xC to slot 5 and the rest in order — and `MapBtlRun (0x8007AE58)(enc, arg1,
    label, ...)` runs the fight. MapBtlRun copies each member's place cells
    (its ChrPlacePresetRecord, chr.h) to the battle's tables, the x less arg1
    (battle.md, "Party stage state").
    The ids in `party` are as stored (0xC included)."""
    base = programs.address(image, "g_ScriptMapBtlRows", ENCOUNTER_ROWS_ADDR) - EXE_BASE
    if len(image) < base + ENCOUNTER_ROW_COUNT * ENCOUNTER_ROW_SIZE:
        raise ValueError("the image ends before g_ScriptMapBtlRows (0x800B366C)'s rows do")
    out = []
    for i in range(ENCOUNTER_ROW_COUNT):
        off = base + i * ENCOUNTER_ROW_SIZE
        b = image[off:off + ENCOUNTER_ROW_SIZE]
        if b[0] == 0:
            continue
        party = []
        for v in b[2:8]:
            if v == 0:
                break
            party.append(v)
        out.append(EncounterRow(row=i + 1, encounter=b[0], x_shift=b[1], party=tuple(party)))
    return out


# -- the music and the sound effects a script plays ------------------------------

MUSIC_PLAY = 0x30                   # ScriptCommandMusicPlay (0x8005E494)
SOUND_PLAY = 0x31                   # ScriptCommandSoundPlay (0x8005E524)


def music_plays(buf: bytes, cmds) -> list[tuple[int, int, int]]:
    """(offset, song, time) for every command 0x30: ScriptCommandMusicPlay
    (0x8005E494) hands u8[c + 2] and u8[c + 3] to MusicPlay (0x80054F2C), the
    song's number and a time. Song 0 stops the music (sound_music_stop
    (0x80023D34)); any other is the song that plays next, brought in over
    the time when it is not 0 (MusicLoadStart (0x80055118): MusicFadeStep
    (0x80055214) mode 1)."""
    return [(c.offset, c.u8(buf, 2), c.u8(buf, 3)) for c in cmds if c.id == MUSIC_PLAY]


def sound_plays(buf: bytes, cmds) -> list[tuple[int, int]]:
    """(offset, sound) for every command 0x31: ScriptCommandSoundPlay
    (0x8005E524) hands u16[c + 2] to SoundPlay (0x800555F0) on sequence slot
    4 or 5, the two in turn (g_ScriptSoundNextSlot). Sound 0 stops both
    slots."""
    return [(c.offset, c.u16(buf, 2)) for c in cmds if c.id == SOUND_PLAY]


def label_reach(buf: bytes, cmds: dict[int, Command],
                script: int | None = None) -> dict[int, frozenset[int]]:
    """label -> the offsets of every command running it can reach
    (walk_label: through its jumps and calls, every way its tests go)."""
    table = labels(buf)
    return {label: frozenset(walk_label(buf, cmds, label, script, table).reached)
            for label in sorted(table)}


def labels_reaching(buf: bytes, cmds: dict[int, Command], offsets,
                    script: int | None = None) -> dict[int, list[int]]:
    """offset -> the labels whose run can reach the command there, in
    order, for each of `offsets`; an offset no label reaches is left out.
    These are the scenes a command is credited to in its own script: the
    scenes you watch it in (ruled 2026-10-26; viewer_tabs.links.scenes
    adds the scenes of other scripts that hand over to it)."""
    want = set(offsets)
    found: dict[int, list[int]] = {}
    if not want:
        return found
    reach = label_reach(buf, cmds, script)
    for label in sorted(reach):
        for at in sorted(want.intersection(reach[label])):
            found.setdefault(at, []).append(label)
    return found


def command_labels(buf: bytes, cmds) -> dict[int, tuple[int, ...]]:
    """command offset -> the labels whose code holds it: those that start
    at the last label start at or before it, with no command between that
    never falls through (TERMINAL). Every jump, call, answer, pick and
    battle goes to a label, so a command that is not at a label start is
    reached only through the commands before it, from that start: whatever
    runs it runs the label first. A command after a TERMINAL one and before
    the next label can never run, and is left out. These are the pieces a
    command is written in; the scenes it is credited to are
    `labels_reaching`'s."""
    starts: dict[int, list[int]] = {}
    for n, at in sorted(labels(buf).items()):
        starts.setdefault(at, []).append(n)
    out: dict[int, tuple[int, ...]] = {}
    held: tuple[int, ...] = ()
    for c in sorted(cmds, key=lambda c: c.offset):
        if c.offset in starts:
            held = tuple(starts[c.offset])
        if held:
            out[c.offset] = held
        if c.id in TERMINAL:
            held = ()
    return out


# -- story flags ----------------------------------------------------------------
#
# Every command below hands a number n to StoryBitSet (0x800576EC), StoryBitClear
# (0x80057730) or StoryBitCheck (0x80057778): bit (n & 7) of byte (n >> 3) of the
# 0x800 bytes g_StoryBits (0x800B8944) points at, n cut to 16 bits. So there is one
# store and one number space; the commands differ only in how their operands
# become n, and each form is the one another part of the program numbers its own
# flags by:
#
#   0x09-0x0D  u16 words to a 0 word: n itself
#   0x0E-0x12  bytes to a 0 byte: 0x580 + b, an entity's flag (MapObjectsInit
#              (0x800655C8): kinds 1-3, 0x580 + definition byte 2)
#   0x13-0x17  byte pairs (m, d) to a pair whose m is 0: (m << 7) + d - 0x2C00,
#              the flag of definition d's object of another kind on map m
#              (MapObjectsInit: d + 0x680 + ((map - 0x65) << 7), the same number)
#   0x18-0x19  bytes to a 0 byte: 0x480 + b, a tile change's (MapBgChangeStart
#              (0x80059900): byte 4 of its row + 0x480)
#   0x1A       byte pairs (m, d): d + 0x2620 + ((m - 0x35 if m >= 0x65 else
#              m - 0x15) << 5), the flag that shows chest d of map m open
#              (MapObjectInit (0x800656CC), whose test is map > 100)
#   0x5C       no operand: StoryBitCheck(1), the game ending when it is set; then
#              all 0x800 bytes cleared (ScriptCommandStoryBitsItemsReset)
#
# A check keeps its label at c + 2 and its list from c + 4, and goes on at the
# label when all of its flags are set (All), none is (None) or one or more is
# (Any); else on to the next command (ScriptCommandLabelJump (0x8005BF5C)).
#
# Two more commands touch the flags 0x2BC + a party id: 0x23 sets it as the id
# joins and 0x24 clears it as the id leaves (ScriptCommandPartyJoin (0x8005D60C),
# ScriptCommandPartyLeave (0x8005D70C): ids 0x10-0x1E taken as id - 0xF, and 0x1F
# and up as 0xD; nothing happens when the id is already in the party, or not in
# it). A 0x23 whose c[2] is not 0 takes its id from a map object
# (MoveChrRowIdGet), and 0x43 (ScriptCommandChr1ChrBChange (0x8005D470)) adds 0xF
# to its id on a map of party kind 0: neither number is known from the script,
# and neither is read here.
#
# SLPS_013.97's handlers (its g_ScriptCommandFunctions (0x800B1738) entries 0x09
# to 0x1A from 0x8005F8E0, 0x23 at 0x80060998, 0x24 at 0x80060A9C, 0x5C at
# 0x8006239C) add the same numbers.

SET, CLEAR, ALL, NONE, ANY, RESET = "set", "clear", "all", "none", "any", "reset"
#: id -> (what it does, how its operands are written, its handler)
FLAG_COMMANDS = {
    0x09: (SET, "words", "ScriptCommandStoryBitsSet (0x8005C504)"),
    0x0A: (CLEAR, "words", "ScriptCommandStoryBitsClear (0x8005C570)"),
    0x0B: (ALL, "words", "ScriptCommandStoryBitsAllCheck (0x8005C5DC)"),
    0x0C: (NONE, "words", "ScriptCommandStoryBitsNoneCheck (0x8005C684)"),
    0x0D: (ANY, "words", "ScriptCommandStoryBitsAnyCheck (0x8005C72C)"),
    0x0E: (SET, "580", "ScriptCommandStoryBits580Set (0x8005C7D4)"),
    0x0F: (CLEAR, "580", "ScriptCommandStoryBits580Clear (0x8005C844)"),
    0x10: (ALL, "580", "ScriptCommandStoryBits580AllCheck (0x8005C8B4)"),
    0x11: (NONE, "580", "ScriptCommandStoryBits580NoneCheck (0x8005C960)"),
    0x12: (ANY, "580", "ScriptCommandStoryBits580AnyCheck (0x8005CA0C)"),
    0x13: (SET, "pairs", "ScriptCommandStoryBitPairsSet (0x8005CAB8)"),
    0x14: (CLEAR, "pairs", "ScriptCommandStoryBitPairsClear (0x8005CB38)"),
    0x15: (ALL, "pairs", "ScriptCommandStoryBitPairsAllCheck (0x8005CBB8)"),
    0x16: (NONE, "pairs", "ScriptCommandStoryBitPairsNoneCheck (0x8005CC74)"),
    0x17: (ANY, "pairs", "ScriptCommandStoryBitPairsAnyCheck (0x8005CD30)"),
    0x18: (SET, "480", "ScriptCommandStoryBits480Set (0x8005CDEC)"),
    0x19: (CLEAR, "480", "ScriptCommandStoryBits480Clear (0x8005CE5C)"),
    0x1A: (SET, "2620", "ScriptCommandStoryBitPairs2620Set (0x8005CECC)"),
    0x23: (SET, "party", "ScriptCommandPartyJoin (0x8005D60C)"),
    0x24: (CLEAR, "party", "ScriptCommandPartyLeave (0x8005D70C)"),
    0x5C: (RESET, "none", "ScriptCommandStoryBitsItemsReset (0x8005EF58)"),
}
CHECKS = frozenset({ALL, NONE, ANY})
#: the bases the byte forms add
ENTITY_BASE, TILE_CHANGE_BASE = 0x580, 0x480
#: the pairs' (m << 7) + d - 0x2C00: (m - 0x58) * 0x80 + d
PAIR_BASE = 0x2C00
#: the chest pairs' d + 0x2620 + (k << 5), k = m - 0x35 from map 0x65, else m - 0x15
CHEST_BASE, CHEST_HIGH_MAPS, CHEST_HIGH, CHEST_LOW = 0x2620, 0x65, 0x35, 0x15
#: ScriptCommandPartyJoin, ScriptCommandPartyLeave: flag 0x2BC + the id
PARTY_BASE = 0x2BC
PARTY_FOLD_FIRST, PARTY_FOLD, PARTY_OTHER_FROM, PARTY_OTHER = 0x10, 0xF, 0x1F, 0xD
#: ScriptCommandStoryBitsItemsReset tests this flag before it clears them all
END_FLAG = 1
#: ScriptCommandMoviePlay (0x8005E2B4): MoviePlay (0x800232D4) of byte 2
MOVIE_PLAY = 0x2D
#: ScriptCommandMapObjectsRemove (0x8005D9D4) sets, ScriptCommandMapObjectsAdd
#: (0x8005D7E0) clears, the flag of each definition of its list
OBJECTS_REMOVE, OBJECTS_ADD = 0x25, 0x41


@dataclass(frozen=True)
class FlagUse:
    """One command's use of the story flags."""
    offset: int
    id: int
    does: str                   # SET, CLEAR, ALL / NONE / ANY (a check), RESET
    flags: tuple[int, ...]      # in the command's order
    label: int | None = None    # a check's: where it goes on when it holds
    #: the operands as written: words, bytes, (map, definition) pairs, the id
    written: tuple = ()


def pair_flag(m: int, d: int) -> int:
    """Commands 0x13-0x17: the pair (m, d)'s flag."""
    return ((m << 7) + d - PAIR_BASE) & 0xFFFF


def chest_pair_flag(m: int, d: int) -> int:
    """Command 0x1A: the pair (m, d)'s flag."""
    k = m - CHEST_HIGH if m >= CHEST_HIGH_MAPS else m - CHEST_LOW
    return (d + CHEST_BASE + (k << 5)) & 0xFFFF


def party_flag(n: int) -> int:
    """Commands 0x23, 0x24: party id n's flag, n folded as the handlers fold it."""
    if PARTY_FOLD_FIRST <= n < PARTY_OTHER_FROM:
        n -= PARTY_FOLD
    return PARTY_BASE + (PARTY_OTHER if n >= PARTY_OTHER_FROM else n)


def _byte_list(buf: bytes, p: int, step: int) -> list[int]:
    """The list ScriptListCount(1, step) counts from p: its entries' first bytes."""
    out = []
    while buf[p] != 0:
        out.append(p)
        p += step
    return out


def flag_uses(buf: bytes, cmds) -> list[FlagUse]:
    """Every story-flag command of `cmds` (FLAG_COMMANDS) and the flags it
    touches, in the order of the code. A 0x23 that takes its id from a map
    object is left out (its number is not in the script)."""
    out = []
    for c in cmds:
        if c.id not in FLAG_COMMANDS:
            continue
        does, form, _fn = FLAG_COMMANDS[c.id]
        at = c.offset + (4 if does in CHECKS else 2)
        label = c.u16(buf, 2) if does in CHECKS else None
        if form == "words":
            written = []
            while (w := struct.unpack_from("<H", buf, at)[0]) != 0:
                written.append(w)
                at += 2
            flags = list(written)
        elif form in ("580", "480"):
            written = [buf[p] for p in _byte_list(buf, at, 1)]
            base = ENTITY_BASE if form == "580" else TILE_CHANGE_BASE
            flags = [base + b for b in written]
        elif form in ("pairs", "2620"):
            written = [(buf[p], buf[p + 1]) for p in _byte_list(buf, at, 2)]
            fn = pair_flag if form == "pairs" else chest_pair_flag
            flags = [fn(m, d) for m, d in written]
        elif form == "party":
            if c.id == 0x23 and buf[c.offset + 2] != 0:
                continue
            n = buf[c.offset + (3 if c.id == 0x23 else 2)]
            written, flags = [n], [party_flag(n)]
        else:
            written, flags = [], [END_FLAG]
        out.append(FlagUse(c.offset, c.id, does, tuple(flags), label, tuple(written)))
    return out


def movie_plays(buf: bytes, cmds) -> list[tuple[int, int]]:
    """(offset, number) for every command 0x2D: ScriptCommandMoviePlay
    (0x8005E2B4) hands byte 2 to MoviePlay (0x800232D4), which sets story
    flag number + 0x154 (records.events) and plays the movie or shows the
    bromide."""
    return [(c.offset, c.u8(buf, 2)) for c in cmds if c.id == MOVIE_PLAY]


def objects_changed(buf: bytes, cmds) -> list[tuple[int, int, tuple[int, ...]]]:
    """(offset, command, definitions) for every 0x25 and 0x41. Each
    definition's object leaves the map (0x25) or comes onto it (0x41), and
    its flag, MapObjectsInit's number for it on the map the script runs on
    (field_objects.story_flag), is set or cleared when its byte 2 is not 0."""
    return [(c.offset, c.id, tuple(buf[p] for p in _byte_list(buf, c.offset + 2, 1)))
            for c in cmds if c.id in (OBJECTS_REMOVE, OBJECTS_ADD)]
