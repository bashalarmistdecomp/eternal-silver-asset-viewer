"""A thing of the game, pointed at: its kind and its number (docs/taxonomy.md).

Every thing the viewer can show or link to has one reference, a `Ref`: the
kind (`map`, `battle`, `song` …) and the number the game knows it by, one
part or several (`message 11/37` is the 37th message of script 11). A kind
may be numbered two ways: a sound effect heard everywhere or in battle by
its number (`sound effect 13`), a place's own by its bank and its number
(`sound effect 300/131`; ruled 2026-10-26). The
reference does not depend on a tab, a view or a list's order, so a link
made anywhere finds its thing anywhere.

A reference is written in decimal (`map 21`); the extended info gives it in
hex too (`map 0x15`). `KINDS` names every kind the reference page names,
with what each part of its number is and the code's name for it, which a
card's extended info shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


@dataclass(frozen=True)
class Kind:
    key: str                    # the reference's kind: "map", "story-flag"
    name: str                   # as written: "map", "story flag"
    plural: str                 # "maps", "story flags"
    parts: tuple[str, ...]      # what each part of the number is
    code: str                   # the code's name for the kind
    digits: int = 2             # hex digits of the last part
    advanced: bool = False      # its home is only in Advanced mode
    also: tuple[tuple[str, ...], ...] = ()     # the other ways it is numbered

    @property
    def forms(self) -> tuple[tuple[str, ...], ...]:
        """Every way a thing of the kind is numbered, its usual one first."""
        return (self.parts, *self.also)

    @property
    def title(self) -> str:
        """The kind as a heading: "Story flag"."""
        return self.name[:1].upper() + self.name[1:]


def _k(key, name, plural, parts, code, digits=2, advanced=False, also=()) -> Kind:
    return Kind(key, name, plural, tuple(parts), code, digits, advanced,
                tuple(tuple(a) for a in also))


#: Every kind, by its key (docs/taxonomy.md, "The kinds").
KINDS: dict[str, Kind] = {k.key: k for k in (
    # the world
    _k("map", "map", "maps", ["map"], "map (g_MapNumber)"),
    _k("place", "place", "places", ["place"], "place (g_MapPlaceName)"),
    _k("entrance", "entrance", "entrances", ["map", "entrance"], "enter row (g_MapEnterTable)"),
    _k("party-move", "party move", "party moves", ["map", "move"], "party place row (g_MapPartyPlaceRows)"),
    _k("tile-change", "tile change", "tile changes", ["map", "change"], "bg change (MapBgChangeStart)"),
    _k("cell", "cell", "cells", ["map", "x", "y"], "attribute cell (MapAttributeRun)"),
    _k("story-flag", "story flag", "story flags", ["flag"], "story bit (g_StoryBits)", digits=4),
    # on the maps
    _k("object-set", "object set", "object sets", ["object set"], "object set (g_MapObjectsDataResourceNumbers)"),
    _k("entity", "entity", "entities", ["object set", "definition"], "object kinds 1–3 (MapPartyTalkCheck)"),
    _k("trigger", "trigger", "triggers", ["object set", "definition"], "object kind 4 (MapObjectTouchRun)"),
    _k("map-monster", "map monster", "map monsters", ["object set", "definition"], "object kinds 5, 6 (MapObjectTouchRun)"),
    _k("chest", "chest", "chests", ["object set", "definition"], "object kind 7 (MapObjectKind7Run)"),
    _k("actor", "actor", "actors", ["script", "offset"], "actor (ScriptCommandMoveChrRowActorSet)", digits=4),
    # characters, monsters and their pictures
    _k("character", "character", "characters", ["character"], "character record (g_ChrRecords); face file"),
    _k("portrait", "portrait", "portraits", ["portrait"], "face (FaceCellSet)"),
    _k("portrait-list", "portrait list", "portrait lists", ["list"], "face list (g_FaceList)"),
    _k("sprite", "sprite", "sprites", ["object set", "sprite"], "sprite data (g_MapSpriteDataEntries)"),
    _k("battle-sprite", "battle sprite", "battle sprites", ["monster set", "block"], "enemy block, party block (BtlDataLoad)"),
    # story
    _k("message", "message", "messages", ["script", "message"], "message (MessageDisp, command 0x02)"),
    _k("script", "script", "scripts", ["script"], "script (g_ScriptResourcePairs)"),
    _k("label", "label", "labels", ["script", "label"], "label (ScriptLabelRun)"),
    _k("movie", "movie", "movies", ["movie"], "movie (MoviePlay)"),
    _k("bromide", "bromide", "bromides", ["bromide"], "picture (PictureShow)"),
    # adventure
    _k("item", "item", "items", ["item"], "item (g_BtlItemTable)"),
    _k("shop", "shop", "shops", ["shop"], "shop (g_ShopStockRows)"),
    _k("spell", "spell", "spells", ["spell"], "spell (g_BtlSpellRows)"),
    _k("battle", "battle", "battles", ["battle"], "battle number (g_BtlNumber)"),
    _k("scripted-battle", "scripted battle", "scripted battles", ["row"], "script battle row (g_ScriptMapBtlRows)"),
    _k("monster", "monster", "monsters", ["monster"], "enemy (g_BtlEnemyRows)"),
    _k("monster-attack", "monster attack", "monster attacks", ["attack"], "attack row (g_BtlAttackRows)"),
    _k("monster-set", "monster set", "monster sets", ["monster set"], "enemy set (g_BtlEnemySet)"),
    _k("monster-group", "monster group", "monster groups", ["group"], "enemy group (g_BtlEnemyGroups)"),
    _k("battle-effect", "battle effect", "battle effects", ["effect"], "show (BtlShowNumberRun)"),
    # sound
    _k("song", "song", "songs", ["song"], "music (MusicPlay, g_MusicNumber)"),
    _k("voice", "voice", "voices", ["voice"], "voice (VoiceSet, g_XaVoices)"),
    # one heard everywhere or in battle by its number; a place's own by its
    # bank, then its number (ruled 2026-10-26)
    _k("sound-effect", "sound effect", "sound effects", ["sound"], "sound (SoundPlay, g_SoundIds)", digits=3,
       also=[["bank", "sound"]]),
    _k("sound-bank", "sound bank", "sound banks", ["resource"], "VAB + SEQ (SOUND.C)", digits=3, advanced=True),
    _k("sequence", "sequence", "sequences", ["resource", "sequence"], "SEQ", advanced=True),
    _k("sample", "sample", "samples", ["resource", "sample"], "VAG", advanced=True),
    _k("sound-area", "sound area", "sound areas", ["area"], "sound area (g_SoundMapAreas)"),
    # art
    _k("image", "image", "images", ["resource", "picture"], "TIM (resource_tim_add)"),
    _k("icon", "icon", "icons", ["icon"], "icon (ICON.C)"),
    # the disc and its storage
    _k("disc-file", "disc file", "disc files", ["name"], "ISO 9660", advanced=True),
    _k("resource", "resource", "resources", ["resource"], "resource (g_ResourceSectorPairs)", digits=3, advanced=True),
    _k("cd-track", "CD track", "CD tracks", ["track"], "the CUE sheet", advanced=True),
    _k("string", "string", "strings", ["string"], "string (font_string_put)", digits=3, advanced=True),
)}


class Ref(NamedTuple):
    """A kind and a number: `Ref("map", (21,))`."""
    kind: str
    id: tuple[int, ...]

    @property
    def key(self) -> str:
        """"map:21", "message:11/37": a dictionary key, and the id of the
        reference in a URL."""
        return f"{self.kind}:{'/'.join(str(i) for i in self.id)}"

    def json(self) -> dict:
        return {"kind": self.kind, "id": list(self.id)}


def ref(kind: str, *ids: int) -> Ref:
    """`ref("message", 11, 37)`; the kind must be one of KINDS."""
    if kind not in KINDS:
        raise KeyError(f"no kind {kind!r}")
    return Ref(kind, tuple(int(i) for i in ids))


def parse(kind: str, id_text: str) -> Ref:
    """A reference from a URL's parts: ("message", "11/37")."""
    try:
        ids = [int(p, 0) for p in id_text.split("/") if p != ""]
    except ValueError:
        raise ValueError(f"{kind} {id_text!r}: the number is not a number") from None
    k = KINDS.get(kind)
    if k is None:
        raise KeyError(f"no kind {kind!r}")
    if all(len(ids) != len(form) for form in k.forms):
        raise ValueError(f"a {k.name} is numbered by "
                         + ", or ".join(" / ".join(form) for form in k.forms))
    return Ref(kind, tuple(ids))


def number(r: Ref) -> str:
    """The number as written: "21", "11/37", "21/(4, 7)"."""
    if r.kind == "cell":
        return f"{r.id[0]}/({r.id[1]}, {r.id[2]})"
    return "/".join(str(i) for i in r.id)


def number_hex(r: Ref) -> str:
    """The number in hex: "0x15", "0x0B/0x25"."""
    digits = KINDS[r.kind].digits
    parts = [f"0x{i:0{2 if n < len(r.id) - 1 else digits}X}" for n, i in enumerate(r.id)]
    if r.kind == "cell":
        return f"{parts[0]}/({r.id[1]}, {r.id[2]})"
    return "/".join(parts)


def written(r: Ref) -> str:
    """"map 21": the kind and the number, in decimal."""
    return f"{KINDS[r.kind].name} {number(r)}"


def written_hex(r: Ref) -> str:
    """"map 0x15": the kind and the number, in hex."""
    return f"{KINDS[r.kind].name} {number_hex(r)}"
