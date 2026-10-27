"""The voices the battles play.

A battle plays a voice in three places, and VoiceSet (0x80055470) has no
other callers but the scripts' command 0x52 and the bromides:

**A show's voice.** BtlShowNumberRun (0x8007BB80) plays show n, what an
action looks like (a spell's or a monster attack's show number). For n of 1
to 0x5A, BtlShowOpen (0x8007B7C8) loads effect n (BtlEffectLoad
(0x800897DC)), whose 4-byte row of g_BtlEffectRows holds its flags, its
tile row and two voices. With byte 2 not 0, BtlShowOpen keeps a voice
(VoiceSet): byte 3 when the acting slot's id (g_BtlSlotIds) is 0xB, 0x7C
or 0x7D, byte 2 for any other. The show starts it by raising the voice byte
g_BtlShowVoiceState, with its own store or through BtlShowActingPlay
(0x8008A95C), which raises it only when byte 2 is not 0; BtlShowVoiceStep
(0x80089D78) then plays it. Every show of 1 to 0x5A whose row names a
voice raises the byte.

**A set battle's.** BtlActingShowRun (0x8003A158), the shows numbered 0x97
and up, plays a voice of its own before the show when the acting slot is 6
in battle 0xF5, 0xF6, 0xF7 or 0xFE (g_BtlNumber), and waits for its end.

**The revive's.** BtlSlot5ReviveTry (0x80027B6C), once a round while slot
5's id is 0xC, may bring a fallen party member back with BtlSlot5Revive
(0x80028E5C), which plays voice 0x3D as it does.

**Who casts what**, and so whose a show's voice is. A party slot's id is
the character's number, a monster slot's the monster's.

- A character casts the spells kept in their record (+0x2A, eight bytes).
  ChrLevelUp (0x80028554) keeps, for ids 1 to 6 and 0xB, the first spell
  row whose owner byte (+7) is the id (1 for 0xB) and whose level (+0) is
  the level just reached; the scripts' command 0x59
  (ScriptCommandChrSpellSet (0x8005EE30)) keeps one whose owner byte is the
  id (1 for 0xB) and hangs the game for any other.
- A party slot acting by itself casts what BtlActingSpellPick (0x800393F0)
  picks from its id's own list (`PICKED_SPELLS`); ids 7 and 9 pick none.
- A monster uses the attack rows its row names (+0x1C its attack, kind 2;
  +0x1D its kind 7), and in a battle numbered 0xEB or more the ones its
  id's planner picks (BtlEnemyActionSpecialSet (0x800417E4), `PLANNED`):
  a planned number of 0x7F to 0x83 is a series BtlActionSeriesRun
  (0x8002DD88) runs as two attacks or one (`SERIES`).

The Japanese program has the same constants in these functions
(BtlShowOpen at SLPS_013.97 0x8007DEC4, BtlActingShowRun at 0x8003DAD8,
BtlSlot5Revive at 0x8002C694, BtlActingSpellPick at 0x8003CD5C, ChrLevelUp
at 0x8002BD80, BtlEnemyActionSpecialSet at 0x80044BA0, BtlActionSeriesRun
at 0x8003163C, the planners from 0x80044D70 to 0x80046688) and the same
effect rows, kept elsewhere (records.programs).
"""

from __future__ import annotations

from dataclasses import dataclass

from decoders.plugins.SLUS_006_28.records.programs import EXE_BASE, address

#: g_BtlEffectRows: 0x190 bytes to the next symbol, 4 a row.
EFFECT_ROWS_ADDR = 0x800AC43C
EFFECT_COUNT = 100
ROW_SIZE = 4
#: The shows BtlShowNumberRun opens with BtlShowOpen and runs from its
#: table of 90 functions.
SHOW_FIRST, SHOW_LAST = 1, 0x5A
#: The acting ids BtlShowOpen keeps byte 3 for.
OTHER_VOICE_IDS = (0x0B, 0x7C, 0x7D)
#: BtlActingShowRun: battle number -> the voice it plays for acting slot 6.
SET_BATTLE_VOICES = {0xF5: 0x3A, 0xF6: 0x3B, 0xF7: 0x38, 0xFE: 0x38}
#: The acting slot BtlActingShowRun plays them for.
SET_BATTLE_SLOT = 6
#: BtlSlot5Revive's voice, and the id slot 5 must have for a revive.
REVIVE_VOICE = 0x3D
REVIVER_ID = 0x0C

#: ChrLevelUp: the ids that keep the spells a level brings -> the owner
#: byte of the rows they keep.
LEVEL_SPELL_OWNERS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 0x0B: 1}
#: ScriptCommandChrSpellSet: the owner byte a spell row must hold for an id.
SCRIPT_SPELL_OWNERS = {0x0B: 1}
#: BtlActingSpellPick: the spells a party slot of each id picks from.
PICKED_SPELLS = {
    1: (1, 2, 3, 4), 0x0B: (1, 2, 3, 4),
    2: (9, 10, 11, 12, 0x2B, 0x2C, 0x2D, 0x2E),
    3: (0x0D, 0x0E, 0x10, 0x12),
    4: (0x15, 0x16, 0x17, 0x19, 0x1A, 0x1B),
    5: (0x1D, 0x1E, 0x1F, 0x20),
    6: (0x21, 0x22, 0x23, 0x25, 0x26),
    8: (0x27, 0x28, 0x29, 0x2A),
    0x0A: (0x2F,),
}
#: The planners of BtlEnemyActionSpecialSet: a monster id -> the numbers
#: its function plans for kind 7 (BtlEnemy6EEnemy70ActionSet plans kind 2
#: alone).
PLANNED = {
    0x6F: (0x4F, 0x50), 0x71: (0x51,), 0x72: (0x52, 0x53), 0x73: (0x54, 0x55),
    0x74: (0x56, 0x57), 0x75: (0x58, 0x59), 0x76: (0x5A,),
    0x77: (0x5C, 0x5D, 0x5E, 0x7E), 0x78: (0x5F, 0x60, 0x61),
    0x79: (0x62, 0x63, 0x64, 0x65), 0x7A: (0x6A, 0x6B, 0x6C, 0x6D, 0x6E),
    0x7B: (0x6F, 0x70, 0x71), 0x7C: (0x7F, 0x80, 0x81, 0x82, 0x83),
    0x7D: (0x63, 0x73), 0x7E: (0x74, 0x75, 0x76), 0x7F: (0x39, 0x3A),
}
#: BtlActionSeriesRun: a series number -> the attack rows it runs.
SERIES = {0x7F: (0x64, 0x72), 0x80: (0x62, 0x63), 0x81: (0x68, 0x67),
          0x82: (0x73, 0x65), 0x83: (0x66,)}

SHOW_OPEN = "BtlShowOpen (0x8007B7C8)"
EFFECT_LOAD = "BtlEffectLoad (0x800897DC)"
ACTING_PLAY = "BtlShowActingPlay (0x8008A95C)"
ACTING_SHOW_RUN = "BtlActingShowRun (0x8003A158)"
REVIVE = "BtlSlot5Revive (0x80028E5C)"
REVIVE_TRY = "BtlSlot5ReviveTry (0x80027B6C)"
LEVEL_UP = "ChrLevelUp (0x80028554)"
SCRIPT_SPELL = "ScriptCommandChrSpellSet (0x8005EE30)"
SPELL_PICK = "BtlActingSpellPick (0x800393F0)"
PLANNER = "BtlEnemyActionSpecialSet (0x800417E4)"
SERIES_RUN = "BtlActionSeriesRun (0x8002DD88)"


@dataclass(frozen=True)
class EffectRow:
    """One effect's row of g_BtlEffectRows."""
    number: int
    flags: int          # 1 sprite data, 2 a palette, 4 the tile layer
    tile_row: int       # its row of g_BtlEffectTileRows
    voice: int          # byte 2: kept for most acting ids; 0 for none
    other_voice: int    # byte 3: kept for OTHER_VOICE_IDS


def effect_rows(image: bytes) -> list[EffectRow]:
    """g_BtlEffectRows, by effect number. `image` is the program's image
    from 0x80011000; SLPS_013.97 keeps the table elsewhere
    (records.programs)."""
    at = address(image, "g_BtlEffectRows", EFFECT_ROWS_ADDR) - EXE_BASE
    if at < 0 or at + EFFECT_COUNT * ROW_SIZE > len(image):
        raise LookupError("g_BtlEffectRows runs past the program's image")
    return [EffectRow(n, *image[at + n * ROW_SIZE: at + (n + 1) * ROW_SIZE])
            for n in range(EFFECT_COUNT)]


def show_voices(image: bytes) -> dict[int, EffectRow]:
    """Show n -> its effect's row, for each show BtlShowOpen opens whose
    row names a voice (byte 2 not 0): the shows that play one."""
    rows = effect_rows(image)
    return {n: rows[n] for n in range(SHOW_FIRST, SHOW_LAST + 1) if rows[n].voice}


def other_voice(slot_id: int) -> bool:
    """True when BtlShowOpen keeps an effect's other voice for a slot of
    this id."""
    return slot_id in OTHER_VOICE_IDS


def level_spells(spells: dict[int, tuple[int, int]]) -> dict[int, set[int]]:
    """Spell -> the ids ChrLevelUp keeps it for. `spells` is spell number ->
    (its level byte, its owner byte); a level brings the first row of the
    owner whose level is the one reached, 2 to 99."""
    out: dict[int, set[int]] = {}
    for slot_id, owner in LEVEL_SPELL_OWNERS.items():
        for level in range(2, 100):
            for n in sorted(spells):
                if spells[n] == (level, owner):
                    out.setdefault(n, set()).add(slot_id)
                    break
    return out


def script_spell_ok(slot_id: int, owner: int) -> bool:
    """True when command 0x59 lets id `slot_id` keep a spell whose row's
    owner byte is `owner`."""
    return SCRIPT_SPELL_OWNERS.get(slot_id, slot_id) == owner


def planned_attacks(monster_id: int) -> list[int]:
    """The attack rows a monster's planner can have it use, its series
    opened (BtlEnemyActionSpecialSet, BtlActionSeriesRun)."""
    out: list[int] = []
    for n in PLANNED.get(monster_id, ()):
        for a in SERIES.get(n, (n,)):
            if a not in out:
                out.append(a)
    return out
