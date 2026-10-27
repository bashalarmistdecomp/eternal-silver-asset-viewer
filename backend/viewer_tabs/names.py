"""The game's names for things — the viewer's one place that composes them.

Every tab that labels something asks `GameNames.for_ctx(ctx)`; none of
them knows a string id. The knowledge lives in the decoders:

    formats.system_strings   the string table (LUNADATA resource 1) and the
                             categories' id rules (`GameStrings`)
    records.music            BGM number -> sequence bank / CD track
    records.areas            map id -> area record (location, party kind, music)
                             and -> the resource holding the map
    records.events           play-event numbers -> movie files / bromides

so a name shown here is the code's own arithmetic over disc and EXE bytes
(docs/spec/text.md). A method answers None when the game has no name for
the thing; the tab keeps its own numbered label then.

Both programs of the game are read: SLUS_006.28 and the Japanese
SLPS_013.97 (records.programs locates its tables). The Japanese strings are
read through the characters its glyph codes stand for
(formats.jp_characters); a glyph with no confident character shows as
{GLYPH:xxxx}.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: The programs these decoders' tables are read in (records.programs).
from decoders.plugins.SLUS_006_28.records.programs import PROGRAMS


class UnknownProgram(LookupError):
    """No names because the decoders do not know the disc's program: what is
    read from the game's own formats says nothing of that disc, as a tab
    that serves other programs is off on it (tab_providers.applies_to). Not
    a failure, where names a known program's files cannot give are."""


@dataclass(frozen=True)
class MapEntry:
    """A loadable map: the game's map id, the resource holding it, its area."""
    map_id: int
    resource: int
    area: object                    # records.areas.Area


class GameNames:
    _cache: dict[tuple[Path, Path], "GameNames"] = {}
    #: (program file, LUNADATA.FIL) -> what reading their names raised, the
    #: last time it was tried (for_ctx tries again each time it is asked)
    _errors: dict[tuple[Path, Path], str] = {}

    def __init__(self, binary, resources: dict, archive: Path):
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        from decoders.plugins.SLUS_006_28.records import areas, events, music
        image = binary.code
        self._binary = binary
        self._image = image
        self._resources = resources
        self._archive = archive
        blk = ss.block(resources[ss.RESOURCE].read(archive))
        self.strings = ss.GameStrings.decode_block(
            blk, ss.words_of(image), ss.exe_char_table(image), ss.characters_of(image))
        self._areas = areas
        self._events = events
        self._bgm = {b.number: b for b in music.jukebox(image)}

    @property
    def binary(self):
        """The program's loaded image (psx.analysis.exe_loader)."""
        return self._binary

    @classmethod
    def for_ctx(cls, ctx) -> "GameNames | None":
        """The names for the disc on screen; None off-SSSC or if unreadable
        (`why_none` says which)."""
        key = cls._key(ctx)
        if key is None:
            return None
        got = cls._cache.get(key)
        if got is None:
            try:
                from decoders.psx.analysis.exe_loader import load_exe
                from decoders.plugins.SLUS_006_28.formats.resource_table import \
                    load_resource_table
                binary = load_exe(key[0])
                resources = {r.index: r for r in load_resource_table(binary)}
                got = cls._cache[key] = cls(binary, resources, key[1])
            except Exception as ex:
                cls._errors[key] = f"{type(ex).__name__}: {ex}"
                return None
            cls._errors.pop(key, None)
        return got

    @staticmethod
    def _key(ctx) -> tuple[Path, Path] | None:
        """The two files the names are read from, or None for a program the
        decoders do not know."""
        try:
            if ctx.program not in PROGRAMS:
                return None
            return Path(ctx.exe_path), Path(ctx.path("LUNADATA.FIL"))
        except Exception:
            return None

    @classmethod
    def why_none(cls, ctx) -> str:
        """Why `for_ctx` gives no names, as words after a colon ("" when it
        gives them): the decoders do not know the program, a file they are
        read from is missing, or what reading them raised."""
        key = cls._key(ctx)
        if key is None:
            return f"the decoders do not know {getattr(ctx, 'program', 'its program')}"
        if key in cls._cache or (key not in cls._errors and cls.for_ctx(ctx) is not None):
            return ""
        missing = [what for what, p in zip(("the program file", "LUNADATA.FIL"), key)
                   if not p.is_file()]
        if missing:
            return f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing"
        return f"they could not be read: {cls._errors.get(key, 'no reason was given')}"

    # -- names by category (the callers' id rules) ------------------------

    def character(self, char_id: int) -> str | None:
        return self.strings.name("character", char_id)

    def enemy(self, enemy_id: int) -> str | None:
        return self.strings.name("enemy", enemy_id)

    def item(self, item_id: int) -> str | None:
        return self.strings.name("item", item_id)

    def item_description(self, item_id: int) -> str | None:
        return self.strings.description("item", item_id)

    def spell(self, row: int) -> str | None:
        return self.strings.name("spell", row)

    def spell_description(self, row: int) -> str | None:
        return self.strings.description("spell", row)

    def enemy_special(self, attack_class: int) -> str | None:
        return self.strings.name("enemy_special", attack_class)

    def location(self, location_id: int) -> str | None:
        return self.strings.name("location", location_id)

    def movie(self, n: int) -> str | None:
        """Movie n's title — the theater lists event n as entry n + 1."""
        return self.strings.name("movie", n + 1)

    def movie_file(self, filename: str) -> str | None:
        """A movie file's title ("_B004.STR" plays as event 4)."""
        n = self._events.movie_number(filename)
        return self.movie(n) if n is not None else None

    def bromide(self, k: int) -> str | None:
        return self.strings.name("bromide", k)

    def bromide_resource(self, resource: int) -> str | None:
        """The bromide a LUNADATA resource holds (PictureShow, 0x80024A7C), or None."""
        k = self._events.bromide_for_resource(resource)
        return self.bromide(k) if k is not None else None

    def bgm(self, number: int) -> str | None:
        return self.strings.name("bgm", number)

    # -- things named through an EXE table --------------------------------

    def bgm_numbers_for_bank(self, resource: int) -> list[int]:
        """The BGM numbers MusicPlay (0x80054F2C) plays from bank `resource` (its
        sequence 0)."""
        return [n for n, b in self._bgm.items()
                if b.kind == "sequence" and b.resource == resource]

    def bgm_numbers_for_cd_track(self, track: int) -> list[int]:
        return [n for n, b in self._bgm.items() if b.kind == "cd" and b.track == track]

    def titles(self, numbers: list[int]) -> str | None:
        """'‹title› / ‹title›' — the named BGM numbers' titles, joined."""
        names = list(dict.fromkeys(t for t in (self.bgm(n) for n in numbers) if t))
        return " / ".join(names) or None

    def maps(self) -> list[MapEntry]:
        """Every map the game can load (g_MapResourcePairs, 0x800AF364), by map id."""
        return [MapEntry(mid, res, area) for mid, res, area in self._areas.maps(self._image)]

    def map_name(self, map_id: int) -> str | None:
        """The location MapSet (0x80068780) sets for the map (area record byte 6)."""
        return self.location(self._areas.area(self._image, map_id).location)

    def location_short(self, location_id: int) -> str | None:
        """The memory-card short form of a location (g_CardSavePlaceNames (0x800A8618),
        card_save_title_set (0x8001BF50) — script_text.read_location_names)."""
        if not hasattr(self, "_short"):
            from decoders.plugins.SLUS_006_28.formats.script_text import \
                read_location_names
            self._short = read_location_names(self._binary)
        return self._short.get(location_id)

    def script_ids_for_resource(self, resource: int) -> list[int]:
        """The event-script ids ScriptResourceLoad (0x80020D20) reads from
        `resource` (g_ScriptResourcePairs (0x800AF268), formats.event_script)."""
        if not hasattr(self, "_scripts"):
            from decoders.plugins.SLUS_006_28.formats.event_script import script_resources
            self._scripts = script_resources(self._image)
        return sorted(sid for sid, res in self._scripts.items() if res == resource)

    def resources(self) -> list:
        """Every resource of the table (resource_table.Resource), by number."""
        return [self._resources[n] for n in sorted(self._resources)]

    def resource_entry(self, index: int):
        """A general resource_table entry (its sectors), or None."""
        return self._resources.get(index)

    def read_resource(self, index: int) -> bytes:
        """A general resource's bytes (resource_table), e.g. a map file."""
        return self._resources[index].read(self._archive)

    def resource_source(self, index: int) -> bytes:
        """A resource's bytes as the code reads them (`resource_source`)."""
        return resource_source(self.read_resource(index), index)


def resource_source(buf: bytes, index: int) -> bytes:
    """Resource `index`'s bytes as the code reads them: a command list's
    commands up to the zero word that ends it (formats.command_list), else
    the whole resource. What lies past a list's end is never read, and it
    differs between discs whose lists match."""
    import struct
    from decoders.plugins.SLUS_006_28.formats import command_list as cl
    from decoders.plugins.SLUS_006_28.formats import resources as rs
    if not rs.is_command_list(index):
        return buf
    return b"".join(struct.pack("<II", c.word, len(c.payload)) + c.payload
                    for c in cl.commands(buf))
