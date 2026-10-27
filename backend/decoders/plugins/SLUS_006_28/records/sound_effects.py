"""Sound effects: what SoundPlay (0x800555F0) plays for a sound number
(docs/spec/sound.md §6, "Sound effects — SoundPlay").

A sound effect is a number the game hands SoundPlay(n, slot). What it plays
depends on where the game is: g_SoundMapNumber (0x800B8DED), the byte
SoundMapSet (0x800555CC) keeps, is the map's number on a map (MapSet
(0x80068780)), 0 in battle (MapBtlRun (0x8007AE58)) and 1 on the start
screen (StartScreenShow (0x80043C64)). SoundPlay then picks a bank slot and
a sequence of the bank loaded there:

    n == 0            stops what the slot plays
    n >= 0x12B        nothing
    1 to 10           the common bank (slot 0), sequence n - 1
    11 to 0x82        in battle and on map 0x32: 0x82 -> slot 1's sequence 1;
                      0x18 -> common sequence 0x17; below 0x1F refused;
                      the rest slot 1's sequence n - 0x1F.
                      On any other map: below 0x1F common sequence n - 1;
                      from 0x1F refused
    0x83 to 0x12A     on a map: the place in g_SoundIds (0x800E4CD8) of n,
                      slot 1's sequence of that number; not there, nothing.
                      In battle refused
    refused           common sequence 1 (SoundPlay answers 2)

and a common sequence from 9 to 25 is played two lower. sound_effect_play
(0x80024514) plays the common bank's below 0x16, slot 1's below 0x60 by
the number and below 8 by g_SoundIds; sound_seq_play (0x80023B24) plays
nothing for a sequence the bank does not have.

The banks: slot 0 holds the common bank, 232 (sound_common_load
(0x80023E00)); slot 1 the bank of the map's sound area (sound_area_load
(0x80023F78)): sound_area_get (0x80024784) turns the map's number into an
area through g_SoundMapAreas (0x800AF7A8), and sound_pair_find (0x80023E5C)
finds the area's bank in g_SoundAreaBankPairs (0x800AF694) — the last
pair's, 358, for an area the list does not name, which is how a battle
(map number 0) has the battle's bank. g_SoundIds is the sixteen numbers of
the area bank's command 17 (sound_id_table_set (0x800244E4)), written as
the bank loads.

So numbers 1 to 24 are one sound wherever they play; 0x1F up to 0x82 are
the battle's (and map 0x32's own bank's); from 0x83 a number is a sound of
the place: each area's bank has its own, and the same number is another
sound, or none, in another place.

CALLS lists the calls whose number is written in the code, with what they
are for in plain words (docs/spec/sound.md, "The battle's sound
requests"); the numbers the data holds (an entrance's, a tile change's, a
script's, a monster's) are read where that data is.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .programs import address

EXE_BASE = 0x80011000
MAP_AREAS_ADDR = 0x800AF7A8     # g_SoundMapAreas: u8 per map number below 0x9A
MAP_AREAS_COUNT = 0x9A          # sound_area_get (0x80024784)
PAIRS_ADDR = 0x800AF694         # g_SoundAreaBankPairs: (area, resource) u16 pairs, value 0 ends
PAIRS_MAX = 0x100               # a guard: the list has 66 pairs

COMMON_BANK = 232               # sound_common_load (0x80023E00): bank slot 0
BATTLE_MAP = 0                  # MapBtlRun (0x8007AE58): SoundMapSet(0)
OWN_BANK_MAP = 0x32             # SoundPlay: the map that plays slot 1 by the number, as in battle
STOP = 0
LIMIT = 0x12B                   # SoundPlay: from here, nothing
FIRST_AREA_NUMBER = 0x83        # SoundPlay: from here, looked up in g_SoundIds
FIRST_SLOT1_NUMBER = 0x1F       # SoundPlay: in battle, slot 1's sequence n - 0x1F from here
SECOND_SEQUENCE = 0x82          # SoundPlay: in battle, slot 1's sequence 1
COMMON_IN_BATTLE = 0x18         # SoundPlay: in battle, the common sequence 0x17
REFUSED_SEQUENCE = 1            # SoundPlay: a refused number plays common sequence 1
SHIFTED = range(9, 26)          # SoundPlay: common sequences 9..25 play two lower
SHIFT = 2
COMMON_LIMIT = 0x16             # sound_effect_play (0x80024514): kind 1
SLOT1_LIMIT = 0x60              # kind 2
IDS_LIMIT = 8                   # kind 3
IDS_COUNT = 16                  # sound_id_table_set (0x800244E4): sixteen numbers
SOUND_IDS_COMMAND = 17          # formats.command_list.SOUND_IDS

SOUND_PLAY = "SoundPlay (0x800555F0)"
EFFECT_PLAY = "sound_effect_play (0x80024514)"
AREA_LOAD = "sound_area_load (0x80023F78)"
PAIR_FIND = "sound_pair_find (0x80023E5C)"
AREA_GET = "sound_area_get (0x80024784)"
IDS_SET = "sound_id_table_set (0x800244E4)"


@dataclass(frozen=True)
class Played:
    """What SoundPlay plays for one number in one place."""
    number: int
    bank: int           # the bank's resource: 232, an area's, or 358
    sequence: int
    refused: bool = False   # SoundPlay answered 2: common sequence 1 in its place
    how: str = ""           # which branch, in words


@dataclass(frozen=True)
class Tables:
    """The two tables that give a map its bank of sound effects."""
    areas: bytes                        # g_SoundMapAreas
    pairs: tuple[tuple[int, int], ...]  # g_SoundAreaBankPairs, to the ending pair

    def area(self, map_number: int) -> int:
        """sound_area_get (0x80024784): the map number's area."""
        return self.areas[map_number] if map_number < MAP_AREAS_COUNT else map_number

    def bank(self, map_number: int) -> int:
        """The bank sound_area_load (0x80023F78) loads into slot 1 for the
        map number: sound_pair_find (0x80023E5C) of its area, the last
        pair's resource when no pair names the area."""
        a = self.area(map_number)
        for area, resource in self.pairs:
            if area == a:
                return resource
        return self.pairs[-1][1]

    @property
    def battle_bank(self) -> int:
        return self.bank(BATTLE_MAP)

    @property
    def area_banks(self) -> list[int]:
        """Every bank a pair names, but the battle's, each once."""
        return sorted({r for _a, r in self.pairs} - {self.battle_bank})


def tables(image: bytes) -> Tables:
    """g_SoundMapAreas (0x800AF7A8) and g_SoundAreaBankPairs (0x800AF694)
    from the program's image."""
    at = address(image, "g_SoundMapAreas", MAP_AREAS_ADDR) - EXE_BASE
    areas = bytes(image[at:at + MAP_AREAS_COUNT])
    at = address(image, "g_SoundAreaBankPairs", PAIRS_ADDR) - EXE_BASE
    pairs = []
    for i in range(PAIRS_MAX):
        area, resource = struct.unpack_from("<hh", image, at + 4 * i)
        if resource == 0:               # sound_pair_find stops at a value of 0
            break
        pairs.append((area, resource))
    if not pairs:
        raise ValueError("g_SoundAreaBankPairs names no bank")
    return Tables(areas, tuple(pairs))


def sound_ids(bank: bytes) -> tuple[int, ...]:
    """The sixteen numbers a bank's command 17 gives g_SoundIds
    (sound_id_table_set (0x800244E4)); () for a bank with none. The last
    such command wins, as resource_command_run (0x800202FC) runs them all."""
    from decoders.plugins.SLUS_006_28.formats import command_list as cl
    c = cl.effective(bank, SOUND_IDS_COMMAND)
    if c is None or len(c.payload) < 2 * IDS_COUNT:
        return ()
    return struct.unpack_from(f"<{IDS_COUNT}H", c.payload)


def play(t: Tables, n: int, map_number: int, ids: tuple[int, ...] = ()) -> Played | None:
    """What SoundPlay(n) plays with g_SoundMapNumber at `map_number`; `ids`
    are g_SoundIds there (sound_ids of the map's bank). None when it plays
    nothing: n is 0 (a stop), too high, not in g_SoundIds, or a sequence
    sound_effect_play does not play."""
    if n == STOP or n >= LIMIT:
        return None
    kind, seq, refused, how = 1, n - 1, False, "heard everywhere"
    battle_like = map_number in (BATTLE_MAP, OWN_BANK_MAP)
    if n >= 0xB:
        if n < FIRST_AREA_NUMBER:
            if battle_like:
                if n == SECOND_SEQUENCE:
                    kind, seq, how = 2, 1, "the battle's sounds"
                elif n == COMMON_IN_BATTLE:
                    kind, seq = 1, n - 1
                elif n < FIRST_SLOT1_NUMBER:
                    refused = True
                else:
                    kind, seq, how = 2, n - FIRST_SLOT1_NUMBER, "the battle's sounds"
            elif n < FIRST_SLOT1_NUMBER:
                kind, seq = 1, n - 1
            else:
                refused = True
        elif map_number != BATTLE_MAP:
            if n not in ids:
                return None
            kind, seq, how = 3, ids.index(n), "the place's own"
        else:
            refused = True
    if refused:
        kind, seq, how = 1, REFUSED_SEQUENCE, "refused: common sequence 1 in its place"
    if kind == 1 and seq in SHIFTED:
        seq -= SHIFT
    limit = {1: COMMON_LIMIT, 2: SLOT1_LIMIT, 3: IDS_LIMIT}[kind]
    if seq >= limit:
        return None
    bank = COMMON_BANK if kind == 1 else t.bank(map_number)
    if kind == 2 and map_number == OWN_BANK_MAP:
        how = "the place's own, by the number"
    return Played(n, bank, seq, refused, how)


@dataclass(frozen=True)
class Call:
    """A call of SoundPlay whose number is written in the code."""
    number: int
    function: str           # "Name (0xADDR)"
    what: str               # what it is for, in plain words
    battle: bool = False    # in battle (g_SoundMapNumber 0)


#: The calls with a number of their own (docs/spec/sound.md, "The battle's
#: sound requests"). The menus' requests are g_MenuSoundRequest's
#: (0x800B8F4A): 1 a move, 2 a choice, 3 a page left, 4 a refusal; the
#: battle's menu and a shop's screen keep theirs in g_BtlMenuSoundRequest
#: (0x800B8B4C). The numbers a battle's shows play of their own
#: (BtlActingShowRun (0x8003A158)'s handlers, BtlShowSoundSet (0x80089EF8))
#: are not listed.
CALLS: tuple[Call, ...] = (
    Call(1, "MenuPagesRun (0x8006D900)", "the cursor moving in the menu"),
    Call(1, "MessageAnswerRun (0x8005B6C0)", "the cursor moving between two answers"),
    Call(1, "StartMenuRun (0x80043E08)", "the cursor moving on the start screen's menu"),
    Call(2, "MenuPagesRun (0x8006D900)", "a choice taken in the menu"),
    Call(2, "MessageAnswerRun (0x8005B6C0)", "an answer taken"),
    Call(2, "StartScreenShow (0x80043C64)", "the start button pressed on the start screen"),
    Call(2, "StartMenuRun (0x80043E08)", "a row taken on the start screen's menu"),
    Call(3, "MenuPagesRun (0x8006D900)", "leaving a page of the menu"),
    Call(4, "MenuPagesRun (0x8006D900)", "the menu refusing a choice"),
    Call(5, "MenuOpen (0x8006A328)", "the menu opening"),
    Call(5, "ShopOpen (0x800506EC)", "a shop's screen opening"),
    Call(6, "ShopClose (0x800512C4)", "a shop's screen closing"),
    Call(1, "ShopStepsRun (0x800516CC)", "a shop's screen: its cursor and choices"),
    Call(2, "ShopStepsRun (0x800516CC)", "a shop's screen: its cursor and choices"),
    Call(3, "ShopStepsRun (0x800516CC)", "a shop's screen: its cursor and choices"),
    Call(3, "ShopRefusalDisp (0x800524C4)", "a shop refusing a deal"),
    Call(4, "ShopRefusalDisp (0x800524C4)", "a shop refusing a deal"),
    Call(11, "MapObjectKind7Run (0x80067F84)", "a chest opening"),
    Call(12, "MessageNoticeDisp (0x8005BD84)", "a notice coming up under a message"),
    Call(14, "MapPartyPose4Play (0x80068334)", "the party's pose before some map changes, "
                                               "as the map goes dark round them"),
    Call(24, "ScriptCommandPartyHpMpFill (0x8005E3D0)", "the party's HP and MP filled, "
                                                        "with a flash"),
    Call(1, "BtlMenuFrameStep (0x80048964)", "the battle's menu: its cursor and choices", True),
    Call(2, "BtlMenuFrameStep (0x80048964)", "the battle's menu: its cursor and choices", True),
    Call(3, "BtlMenuFrameStep (0x80048964)", "the battle's menu: its cursor and choices", True),
    Call(2, "BtlFrameStep (0x80038D2C)", "a battle option switched (vibration, the "
                                         "actions' names): 2 one way, 3 the other", True),
    Call(3, "BtlFrameStep (0x80038D2C)", "a battle option switched (vibration, the "
                                         "actions' names): 2 one way, 3 the other", True),
    Call(0x2A, "BtlWalkSet (0x8002BAA4)", "a party member walking in battle", True),
    Call(0x1F, "BtlWinRun (0x80028140)", "a level gained after a won battle", True),
    Call(0x24, "BtlTargetMissShow (0x80036838)", "an attack dodged", True),
    Call(0x24, "BtlTargetBackMove (0x8002FD1C)", "an attack dodged", True),
    Call(0x26, "BtlSlotLeave (0x8002E398)", "someone getting away from the battle", True),
    Call(0x26, "BtlPartyEscapeTry (0x80027DAC)", "the party getting away", True),
    Call(0x27, "BtlEscapeFailMove (0x80036BE4)", "a failed escape's stagger", True),
    Call(0x28, "BtlFallRun (0x800385B4)", "a monster falling", True),
    Call(0x38, "BtlAttackHitShow (0x800314B8)", "a hit", True),
    Call(0x38, "BtlTargetOutcomeShow (0x80041484)", "a hit", True),
    Call(0x68, "BtlTargetFrontMark (0x8003568C)", "a monster winding up its attack", True),
)
