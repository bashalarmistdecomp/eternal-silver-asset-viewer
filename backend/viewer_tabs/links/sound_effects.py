"""Sound effects: what plays them, where, and what they play from; and the
songs the scripts play.

A sound effect is a number SoundPlay (0x800555F0) plays
(records.sound_effects). Numbers 1 to 24 are one sound everywhere, the
common bank's; from 0x1F the battle's bank plays them; from 0x83 a number
is a sound of the place, looked up in the bank of the map's sound area, so
one number is a different sound, or none, in another place. A sound
effect as the game plays it is therefore a number and the bank it plays
from: `Effect`, one row of the Sound effects tab each. One heard
everywhere or in battle is written by its number (`sound effect 13`), a
place's own by its bank and its number (`sound effect 300/131`; ruled
2026-10-26), so a link from an entrance, a tile change or a scene opens
the very sound its place plays.

What plays one, as the code shows it:

- a map's entrance (MapChange (0x8005922C) plays its byte 3 on the map it
  leaves) and a tile change (MapBgChangeStart (0x80059900)), on their map;
- a script's command 0x31 (ScriptCommandSoundPlay (0x8005E524)), on the
  maps that run the script: those whose area record names it and those it
  is handed over to (event_script.map_scripts), but for the debug room's
  hand-overs; a script only the debug room hands over to runs in the debug
  room. The scenes credited are those whose run reaches the command, a
  scene's pieces folded into it (links.scenes: the scene you watch); the
  pieces whose code holds the command are *Held in*, with the extended
  info in Fan mode;
- a monster's row in battle: its attack's, its steps' and its actions'
  sounds (BtlAttackAnimationRun (0x800315A8), BtlWalkPathFollow
  (0x8002CA78), BtlActingShowRun (0x8003A158));
- the code's own calls (records.sound_effects.CALLS): the menus, a chest,
  a notice, the battle's hits and escapes.

A use is kept where it plays something: a script's command on a map whose
bank has no sound of that number plays nothing there, and that map is not
counted. A number SoundPlay refuses (a battle's number on a map, a field
number from 11 to 23 in battle) plays the common bank's second sound in
its place; such a use is kept on the number's sound, said to be refused.

The songs: command 0x30 (ScriptCommandMusicPlay (0x8005E494)) hands a song
to MusicPlay (0x80054F2C); song 0 stops the music. Its scenes are found as
a sound's are. A scene is listed once, under every place its script runs
on together (links.scenes.places_words).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from viewer_tabs import links
from viewer_tabs.links import CardBody, Edge, scenes
from viewer_tabs.refs import Ref, ref, written

links.advanced_groups("song", scenes.HELD_IN)
links.advanced_groups("sound-effect", scenes.HELD_IN)

SOUND_PLAY = "SoundPlay (0x800555F0)"
SCRIPT_SOUND = "ScriptCommandSoundPlay (0x8005E524)"
SCRIPT_MUSIC = "ScriptCommandMusicPlay (0x8005E494)"
MAP_CHANGE = "MapChange (0x8005922C)"
BG_START = "MapBgChangeStart (0x80059900)"

#: The three kinds of sound effect, as SoundPlay finds the bank.
COMMON, BATTLE, PLACE = "common", "battle", "place"
GROUPS = (COMMON, BATTLE, PLACE)
#: A kind's heading, and what it means, in plain words.
HEADINGS = {
    COMMON: ("Heard everywhere", "numbers 1 to 24: one sound wherever the game plays it"),
    BATTLE: ("In battle", "the battle's own sounds: in a fight, numbers from 31 are the "
                          "battle bank's"),
    PLACE: ("Each place its own", "from 131 a number is a sound of the place: each place "
                                  "has its own, and the same number is another sound "
                                  "elsewhere"),
}
#: What a sound effect of each kind is, as a card's subtitle.
SUBTITLES = {COMMON: "a sound heard everywhere", BATTLE: "a sound of the battles",
             PLACE: "a sound of the place"}
#: The monster row's sounds: its field, what plays it, and the function.
MONSTER_SOUNDS = (
    ("attack_sound", "its attack", "BtlAttackAnimationRun (0x800315A8)"),
    ("walk_sound", "its steps", "BtlWalkPathFollow (0x8002CA78)"),
    ("action_sound", "its actions", "BtlActingShowRun (0x8003A158)"),
)
#: A walk sound of 0xFF plays nothing (BtlWalkPathFollow).
NO_WALK_SOUND = 0xFF
#: A piece's note on what its code holds.
HOLDS = "its code holds the command"
#: A heading for the scenes of a script no map is found to run.
NO_MAP = "a script no map is found to run"


@dataclass
class Use:
    """One thing that plays a sound effect."""
    by: Ref | None              # the entrance, tile change, label, script or monster
    what: str                   # how it plays, in plain words
    proof: str
    maps: set[int] = field(default_factory=set)     # where; empty in battle or anywhere
    battle: bool = False
    refused: bool = False


@dataclass
class Effect:
    """A sound effect as the game plays it: a number and its bank."""
    number: int
    bank: int
    sequence: int
    group: str
    #: the maps whose bank it is: where the number means this sound
    maps: tuple[int, ...] = ()
    uses: list[Use] = field(default_factory=list)

    @property
    def key(self) -> tuple[int, int]:
        return self.number, self.bank

    @property
    def ref(self) -> Ref:
        """`sound effect 13` heard everywhere or in battle; a place's own
        `sound effect 300/131`, by its bank then its number."""
        if self.group == PLACE:
            return ref("sound-effect", self.bank, self.number)
        return ref("sound-effect", self.number)

    def use(self, by, what, proof, maps=(), battle=False, refused=False) -> None:
        for u in self.uses:
            if (u.by, u.what, u.proof, u.battle, u.refused) == (by, what, proof, battle,
                                                                refused):
                u.maps.update(maps)
                return
        self.uses.append(Use(by, what, proof, set(maps), battle, refused))


@dataclass(frozen=True)
class Scene:
    """A script's command that plays a song or a sound effect, and one
    scene credited with it."""
    script: int                 # the command's script
    label: int | None           # the scene's label; None: no label's run reaches it
    offset: int
    number: int                 # the song, or the sound effect
    time: int = 0               # a song's: brought in over this time, 0 at once
    #: the scene's script: the command's, or one that hands over to it
    by: int | None = None

    @property
    def scene_script(self) -> int:
        return self.script if self.by is None else self.by


class SoundEffects:
    """The disc's sound effects and what plays them, and the scripts'
    songs: read once per disc."""

    def __init__(self, model):
        from decoders.plugins.SLUS_006_28.formats import command_list as cl
        from decoders.plugins.SLUS_006_28.records import sound_effects as se
        from viewer_tabs.field_view import DEBUG_ROOM
        names = model.need_names()
        self.model = model
        self.debug_room = DEBUG_ROOM
        t = self.tables = se.tables(names.binary.code)
        fm = model.field
        #: what could not be read, as a sentence each
        self.errors: list[str] = []
        #: bank -> the maps that load it into slot 1, by number
        self.bank_maps: dict[int, list[int]] = {}
        for mid in sorted(fm.maps):
            self.bank_maps.setdefault(t.bank(mid), []).append(mid)
        self.battle_bank = t.battle_bank
        banks = set(self.bank_maps) | {se.COMMON_BANK, self.battle_bank}
        self.counts: dict[int, int] = {}
        self.ids: dict[int, tuple[int, ...]] = {}
        for b in sorted(banks):
            buf = names.read_resource(b)
            self.counts[b] = sum(1 for c in cl.commands(buf) if c.type == cl.SEQUENCE)
            self.ids[b] = se.sound_ids(buf)
        self.field_map = next(m for m in sorted(fm.maps)
                              if m not in (se.BATTLE_MAP, se.OWN_BANK_MAP))
        self.effects: dict[tuple[int, int], Effect] = {}
        self._made(se)
        #: script -> the maps it runs on; the debug room's alone, last
        self.script_maps = self._script_maps(model)
        #: the scripts' songs, and sound effects, in the order of their code:
        #: each scene credited with the command
        self.songs: list[Scene] = []
        self.sounds: list[Scene] = []
        #: the same, each piece whose code holds the command (Held in)
        self.song_pieces: list[Scene] = []
        self.sound_pieces: list[Scene] = []
        self._scripts(model)
        self._uses(model, se)

    # -- the sound effects ------------------------------------------------------

    def _made(self, se) -> None:
        """Every sound effect a number can play: the common ones, the
        battle's, and each place's (g_SoundIds of the bank, below 8)."""
        for n in range(1, se.FIRST_SLOT1_NUMBER):
            self._effect(se, n, self.field_map)
        for n in range(se.FIRST_SLOT1_NUMBER, se.FIRST_AREA_NUMBER):
            self._effect(se, n, se.BATTLE_MAP)
        for b, maps in sorted(self.bank_maps.items()):
            if b in (se.COMMON_BANK, self.battle_bank):
                continue
            for n in dict.fromkeys(self.ids.get(b, ())):
                if n >= se.FIRST_AREA_NUMBER:
                    self._effect(se, n, maps[0])

    def _effect(self, se, n: int, map_number: int, make: bool = True):
        """The sound effect number n plays with g_SoundMapNumber at
        `map_number`, made the first time (unless not `make`); None when it
        plays nothing, and the effect with `refused` set when SoundPlay
        refuses it."""
        p = se.play(self.tables, n, map_number, self.ids.get(self.tables.bank(map_number), ()))
        if p is None or p.sequence >= self.counts.get(p.bank, 0):
            return None, False
        if p.refused:
            mine = self.of_number(n)
            return (mine[0] if mine else None), True
        e = self.effects.get((n, p.bank))
        if e is None and not make:
            return None, False
        if e is None:
            group = (COMMON if p.bank == se.COMMON_BANK
                     else BATTLE if p.bank == self.battle_bank else PLACE)
            maps = tuple(self.bank_maps.get(p.bank, ())) if group == PLACE else ()
            e = self.effects[n, p.bank] = Effect(n, p.bank, p.sequence, group, maps)
        return e, False

    def of_number(self, n: int) -> list[Effect]:
        """The sound effects number n is, in the order the tab lists them."""
        return [e for e in self.listed() if e.number == n]

    def listed(self) -> list[Effect]:
        """Every sound effect, by kind, then number, then first map."""
        return sorted(self.effects.values(),
                      key=lambda e: (GROUPS.index(e.group), e.number, e.maps[:1], e.bank))

    def same(self, e: Effect) -> list[Effect]:
        """The other numbers that play the same sequence of the same bank."""
        return [o for o in self.listed() if o is not e and (o.bank, o.sequence) == (
            e.bank, e.sequence)]

    def home(self, n: int) -> Effect | None:
        """The row `sound effect n` opens: the one sound of a number heard
        everywhere or in battle; for a place's number, written without its
        bank, the place's sound most things play."""
        mine = self.of_number(n)
        return max(mine, key=lambda e: len(e.uses)) if mine else None

    def find(self, r: Ref) -> Effect | None:
        """The sound effect reference `r` is: `sound effect 300/131` that
        bank's; `sound effect 13` that number's (home)."""
        if len(r.id) == 2:
            e = self.effects.get((r.id[1], r.id[0]))
            return e if e is not None and e.group == PLACE else None
        return self.home(r.id[0])

    def played(self, n: int, map_number: int) -> Effect | None:
        """The sound effect number n is on map `map_number`: the one SoundPlay
        plays there (the common bank's second for a number it refuses there:
        that number's own row stands for it); None when it plays nothing."""
        from decoders.plugins.SLUS_006_28.records import sound_effects as se
        return self._effect(se, n, map_number, make=False)[0]

    # -- what plays them ----------------------------------------------------------

    def _script_maps(self, model) -> dict[int, tuple[int, ...]]:
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        fm = model.field
        switches = {}
        for sid in sorted(fm.script_resources):
            if sid in fm.debug_scripts:
                continue
            try:
                buf, cmds, _labels = fm.script(sid)
            except Exception:
                continue                    # FieldMaps.errors says why
            switches[sid] = es.script_switches(buf, list(cmds.values()))
        entered = {mid: m.area.script for mid, m in fm.maps.items() if mid != self.debug_room}
        out: dict[int, set[int]] = {}
        for mid, sids in es.map_scripts(entered, switches).items():
            for sid in sids:
                out.setdefault(sid, set()).add(mid)
        found = {sid: tuple(sorted(maps)) for sid, maps in out.items()}
        for sid in fm.debug_scripts:
            found[sid] = (self.debug_room,)
        return found

    def _scripts(self, model) -> None:
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        fm = model.field
        for sid in sorted(fm.script_resources):
            try:
                buf, commands, _labels = fm.script(sid)
            except Exception:
                continue
            cmds = list(commands.values())
            songs = [(o, n, time) for o, n, time in es.music_plays(buf, cmds) if n]
            sounds = [(o, n) for o, n in es.sound_plays(buf, cmds) if n]
            if not songs and not sounds:
                continue
            reach = scenes.credited(model, sid, [s[0] for s in songs + sounds])

            def credit(o):
                # the scenes a player sees, a scene's pieces folded into it
                return scenes.scenes_of(model, reach[o]) if o in reach else [(None, None)]
            for o, n, time in songs:
                self.songs += [Scene(sid, lab, o, n, time, by) for by, lab in credit(o)]
                self.song_pieces += [Scene(sid, lab, o, n, time)
                                     for _s, lab in scenes.held_in(model, sid, o)]
            for o, n in sounds:
                self.sounds += [Scene(sid, lab, o, n, 0, by) for by, lab in credit(o)]
                self.sound_pieces += [Scene(sid, lab, o, n)
                                      for _s, lab in scenes.held_in(model, sid, o)]

    def _uses(self, model, se) -> None:
        from viewer_tabs.links import world
        w = world._world(model)
        for c in se.CALLS:
            e, refused = self._effect(se, c.number, se.BATTLE_MAP if c.battle else self.field_map)
            if e is not None:
                e.use(None, c.what, c.function, battle=c.battle, refused=refused)
        for mid in sorted(model.field.maps):
            try:
                rows, changes = w.rows(mid), w.changes(mid)
            except Exception as ex:
                self.errors.append(f"map {mid}: {type(ex).__name__}: {ex}")
                continue
            for row, en in rows:
                if en.sound:
                    e, refused = self._effect(se, en.sound, mid)
                    if e is not None:
                        e.use(ref("entrance", mid, row), "as the party goes through",
                              MAP_CHANGE, (mid,), refused=refused)
            for c in changes:
                if c.sound:
                    e, refused = self._effect(se, c.sound, mid)
                    if e is not None:
                        e.use(ref("tile-change", mid, c.id), "with the change's first copy",
                              BG_START, (mid,), refused=refused)
        for s in self.sounds:
            by = _scene_ref(s)
            maps = self.scene_maps(s)
            for mid in maps:
                e, refused = self._effect(se, s.number, mid)
                if e is not None:
                    e.use(by, "as the scene runs", SCRIPT_SOUND, (mid,), refused=refused)
            if not maps and s.number < se.FIRST_SLOT1_NUMBER:
                # a common number plays the same wherever the script runs
                e, refused = self._effect(se, s.number, self.field_map)
                if e is not None:
                    e.use(by, "as the scene runs", SCRIPT_SOUND, refused=refused)
        try:
            self._monsters(model, se)
        except LookupError as ex:
            self.errors.append(f"the monsters' sounds: {ex}")

    def _monsters(self, model, se) -> None:
        from viewer_tabs.links import battle
        t = battle._tables(model)
        for m, rec in sorted(t.monsters.items()):
            if rec.is_empty:
                continue
            for key, what, proof in MONSTER_SOUNDS:
                n = rec.values.get(key, 0)
                if not n or (key == "walk_sound" and n == NO_WALK_SOUND):
                    continue
                e, refused = self._effect(se, n, se.BATTLE_MAP)
                if e is not None:
                    e.use(ref("monster", m), what, proof, battle=True, refused=refused)

    def scene_maps(self, s: Scene) -> tuple[int, ...]:
        """Where a scene plays its command: the maps the command's script
        runs on, those of them its scene's script runs on too when the
        scene hands over to it (command 0x42 goes on on the same map)."""
        maps = self.script_maps.get(s.script, ())
        if s.scene_script == s.script:
            return maps
        mine = set(self.script_maps.get(s.scene_script, ()))
        return tuple(m for m in maps if m in mine) or maps

    # -- words ----------------------------------------------------------------

    def place(self, mid: int) -> str:
        from viewer_tabs.links import world
        title = world._world(self.model).map_title(mid)
        return f"{title} (the debug room)" if mid == self.debug_room else title

    def places(self, maps) -> list[str]:
        """The maps' places, each once, in the maps' order, the debug room last."""
        ordered = sorted(maps, key=lambda m: (m == self.debug_room, m))
        return list(dict.fromkeys(self.place(m) for m in ordered))

    def heard(self, e: Effect) -> str:
        """Where a sound effect plays, in plain words: the places that play
        a place's own sound; what plays the others."""
        plays = [u for u in e.uses if not u.refused]
        if e.group == PLACE:
            maps = {m for u in plays for m in u.maps}
            said = _listed(self.places(maps or e.maps))
            return said if maps else f"{said}'s own; nothing found plays it"
        found = list(dict.fromkeys(_use_word(u) for u in plays))
        return _listed(found) if found else "nothing found plays it"


def _listed(words: list[str], named: int = 2) -> str:
    more = len(words) - named
    return ", ".join(words[:named]) + (f" and {more} more" if more > 0 else "")


def _use_word(u: Use) -> str:
    """A use in a few words: what the code plays it for, else "entrances",
    "tile changes", "scenes", "monsters"."""
    if u.by is None:
        return u.what
    return {"entrance": "entrances", "tile-change": "tile changes", "label": "scenes",
            "script": "scenes", "monster": "monsters"}.get(u.by.kind, u.what)


def sound_effects(model) -> SoundEffects:
    """The disc's sound effects, kept for as long as the disc is open (and
    shared with its twin: GameModel.kept)."""
    return model.kept("_sound_effects", SoundEffects)


@links.unread
def sound_effects_unread(model) -> list[str]:
    """The maps whose sound effects could not be read, and the monsters'."""
    return sound_effects(model).errors


# -- the scenes, by place ----------------------------------------------------------

def scene_heading(place: str) -> str:
    """The group a scene is listed under on what it plays: its places."""
    return f"Scenes at {place}" if place != NO_MAP else f"Scenes of {NO_MAP}"


def _scene_note(by: Ref) -> str:
    return ("as the scene runs" if by.kind == "label"
            else "as the script runs; no label's run is found to reach it")


def by_places(sfx: SoundEffects, found: list) -> list[tuple[str, str, object]]:
    """(maps, what) rows -> (places, every place, what) rows: each row once,
    under all of its maps' places together (links.scenes.places_words; the
    second names every one when the first does not), by its places' first
    map, the debug room's last, then a script's no map is found to run."""
    out = []
    for maps, what in found:
        places = sfx.places(maps)
        if not places:
            out.append(((2, 0), NO_MAP, NO_MAP, what))
            continue
        heading, every = scenes.places_words(places)
        first = min(maps, key=lambda m: (m == sfx.debug_room, m))
        out.append(((1 if first == sfx.debug_room else 0, first), heading, every, what))
    out.sort(key=lambda f: (f[0], f[1]))
    return [(heading, every, what) for _k, heading, every, what in out]


def _at(heading: str, every: str) -> str:
    """A scene's note naming every place, when its heading does not."""
    return f"; at {every}" if every != heading else ""


# -- the links ---------------------------------------------------------------------

def _what_number(n: int) -> str:
    from decoders.plugins.SLUS_006_28.records import sound_effects as se
    if n < se.FIRST_SLOT1_NUMBER:
        return "a number of the common sounds: the same sound wherever it plays"
    if n < se.FIRST_AREA_NUMBER:
        return "a number of the battle's sounds"
    return "a number of the place's own sounds: each place has its own sound for it"


def subtitle(sfx: SoundEffects, e: Effect) -> str:
    """"a sound heard everywhere", "a sound of the battles", "a sound of
    ‹place›"."""
    if e.group == PLACE and e.maps:
        return f"a sound of {_listed(sfx.places(e.maps))}"
    return SUBTITLES[e.group]


def elsewhere(sfx: SoundEffects, e: Effect) -> list[Effect]:
    """The other places' sounds of a place's own number."""
    return [o for o in sfx.of_number(e.number) if o is not e] if e.group == PLACE else []


@links.card("sound-effect")
def sound_effect_card(model, r) -> CardBody:
    sfx = sound_effects(model)
    n = r.id[-1]
    mine = sfx.of_number(n)
    if not mine:
        raise LookupError(f"sound effect {n} plays nothing SoundPlay (0x800555F0) can play "
                          f"on any map or in battle")
    e = sfx.find(r)
    if e is None:
        said = ", ".join(written(o.ref) for o in mine[:4])
        raise LookupError(f"{written(r)} is no sound SoundPlay (0x800555F0) plays: number {n} "
                          f"is {said}")
    if len(r.id) == 1 and e.group == PLACE:
        # a place's number without its bank: every place's sound for it
        facts = [("The number", _what_number(n)),
                 ("Sounds", f"{len(mine)} different sounds: one for each place that has "
                            f"its own, {_listed([written(o.ref) for o in mine], 3)}"),
                 ("Heard", ", ".join(dict.fromkeys(p for o in mine
                                                    for p in sfx.places(o.maps)[:1])))]
        return CardBody(title=written(r), subtitle=SUBTITLES[PLACE], facts=facts,
                        proven=[SOUND_PLAY, "sound_area_load (0x80023F78)"])
    facts = [("The number", _what_number(n)), ("Heard", sfx.heard(e))]
    same = [written(o.ref) for o in sfx.same(e)]
    if same:
        facts.append(("The same sound as", _listed(same, 3)))
    others = elsewhere(sfx, e)
    if others:
        facts.append(("Its number elsewhere", _listed(
            [f"{written(o.ref)} on {sfx.places(o.maps)[0]}" if o.maps else written(o.ref)
             for o in others], 3)))
    extended = [("Plays from", f"sequence {e.bank}/{e.sequence} of sound bank {e.bank}")]
    return CardBody(title=written(e.ref), subtitle=subtitle(sfx, e),
                    facts=facts, extended=extended,
                    proven=[SOUND_PLAY, "sound_effect_play (0x80024514)",
                            "sound_area_load (0x80023F78)"])


def played_ref(model, n: int, map_number: int) -> Ref | None:
    """The reference of the sound number n plays on map `map_number` (an
    entrance's, a tile change's): `sound effect 13`, or the place's own
    `sound effect 300/131`; None when it plays nothing there. Without the
    program's tables, the number alone."""
    try:
        sfx = sound_effects(model)
    except Exception:
        return ref("sound-effect", n)
    e = sfx.played(n, map_number)
    return e.ref if e is not None else None


@links.edges(kept=True)
def sound_effect_edges(model):
    """Each label (or script) -> the sound effects it plays, listed once
    under the places that run it; each monster -> its sounds; each sound
    effect -> the sequence it plays."""
    sfx = sound_effects(model)
    for e in sfx.listed():
        where = (f"on {sfx.places(e.maps)[0]}" if e.group == PLACE and e.maps
                 else HEADINGS[e.group][0].lower())
        yield Edge(e.ref, ref("sequence", e.bank, e.sequence),
                   "Plays from", "Sound effects", where, SOUND_PLAY)
        for u in e.uses:
            if u.by is not None and u.by.kind == "monster":
                yield Edge(u.by, e.ref, "Sounds", "Played by monsters", u.what, u.proof)
    found = []
    for e in sfx.effects.values():
        for u in e.uses:
            if u.by is not None and u.by.kind in ("label", "script"):
                note = _scene_note(u.by) + (
                    "; refused here, it plays the common bank's second sound" if u.refused
                    else "")
                found.append((tuple(u.maps), (u.by, e.ref, note)))
    for heading, every, (by, to, note) in by_places(sfx, found):
        yield Edge(by, to, "Sound effects", scene_heading(heading), note + _at(heading, every),
                   SCRIPT_SOUND)
    # the pieces whose code holds a command 0x31, on the maps their script runs on
    from decoders.plugins.SLUS_006_28.records import sound_effects as se
    for p in sfx.sound_pieces:
        maps = sfx.script_maps.get(p.script, ()) or (
            (sfx.field_map,) if p.number < se.FIRST_SLOT1_NUMBER else ())
        played = [sfx.played(p.number, m) for m in maps]
        for to in dict.fromkeys(e.ref for e in played if e is not None):
            yield Edge(_scene_ref(p), to, "Sound effects", scenes.HELD_IN, HOLDS, SCRIPT_SOUND)


@links.edges(kept=True)
def song_scene_edges(model):
    """Each label (or script) -> the songs its command 0x30 plays, listed
    once under the places that run it."""
    from decoders.plugins.SLUS_006_28.records import music
    sfx = sound_effects(model)
    image = model.need_names().binary.code
    found = []
    for s in sfx.songs:
        if music.bgm(image, s.number).kind == "none":
            continue                    # MusicPlay plays nothing for it
        by = _scene_ref(s)
        note = _scene_note(by) + ("; faded in" if s.time else "")
        found.append((sfx.scene_maps(s), (by, s.number, note)))
    for heading, every, (by, n, note) in by_places(sfx, found):
        yield Edge(by, ref("song", n), "Music", scene_heading(heading), note + _at(heading, every),
                   SCRIPT_MUSIC)
    for p in sfx.song_pieces:
        if music.bgm(image, p.number).kind != "none":
            yield Edge(_scene_ref(p), ref("song", p.number), "Music", scenes.HELD_IN,
                       HOLDS + ("; faded in" if p.time else ""), SCRIPT_MUSIC)


def _scene_ref(s: Scene) -> Ref:
    if s.label is None:
        return ref("script", s.script)
    return ref("label", s.scene_script, s.label)


# -- songs and sound effects told apart --------------------------------------------

SONG, SOUND_EFFECT = "song", "sound-effect"


def song_words(names, numbers: list[int]) -> str:
    """"song 12 · ‹title›", "songs 12, 40 · ‹title› / ‹title›": the songs a
    score plays, by number then title."""
    if not numbers:
        return ""
    title = names.titles(numbers) if names is not None else None
    said = (f"song {numbers[0]}" if len(numbers) == 1
            else "songs " + ", ".join(str(n) for n in numbers))
    return f"{said} · {title}" if title else said


def sound_effect_words(numbers: list, bank: int | None = None) -> str:
    """"sound effect 9", "sound effects 9 and 11"; a place's own, by the
    bank they are of: "sound effect 300/131"."""
    if not numbers:
        return ""
    said = [f"{bank}/{n}" if bank is not None else str(n) for n in numbers]
    if len(said) == 1:
        return f"sound effect {said[0]}"
    return "sound effects " + ", ".join(said[:-1]) + f" and {said[-1]}"


def sequence_is(model, bank: int, index: int | None = None) -> tuple[str | None, str, list[int]]:
    """What a bank (index None) or one of its sequences plays: (SONG, its
    words, the songs), (SOUND_EFFECT, its words, the sound effects' numbers)
    or (None, "", []) for a bank of neither. A music bank's first score is
    its songs' (records.music); a bank of slot 0 or 1 holds sound effects,
    and a sequence of one is the numbers SoundPlay plays it for."""
    from decoders.plugins.SLUS_006_28.formats import resources as rs
    from decoders.plugins.SLUS_006_28.formats import sound_banks as sb
    reg = rs.region(bank)
    if reg is None:
        return None, "", []
    names = model.names
    if reg.key == "sound-music":
        numbers = (names.bgm_numbers_for_bank(bank) if names is not None and index in (None, 0)
                   else [])
        return SONG, song_words(names, numbers), numbers
    if reg.key not in sb.SFX_REGIONS:
        return None, "", []
    if names is None:
        return SOUND_EFFECT, "", []
    try:
        sfx = sound_effects(model)
    except Exception:                   # the tables cannot be read: still a sound effect
        return SOUND_EFFECT, "", []
    mine = [e for e in sfx.effects.values() if e.bank == bank and (
        index is None or e.sequence == index)]
    numbers = sorted({e.number for e in mine})
    own = bank if any(e.group == PLACE for e in mine) else None
    return SOUND_EFFECT, sound_effect_words(numbers, own) if index is not None else "", numbers


def bank_words(model, bank: int) -> str:
    """What a bank of sound effects is, in plain words: "the common sound
    effects", "the battle's sound effects", "‹place›'s sound effects"."""
    from decoders.plugins.SLUS_006_28.formats import resources as rs
    reg = rs.region(bank)
    if reg is None:
        return ""
    if reg.key == "sound-common":
        return "the common sound effects"
    if reg.key == "sound-battle":
        return "the battle's sound effects"
    if reg.key != "sound-area":
        return ""
    try:
        sfx = sound_effects(model)
    except Exception:
        return "an area's sound effects"
    maps = sfx.bank_maps.get(bank, [])
    if not maps:
        return "an area's sound effects, of no map"
    return f"the sound effects of {_listed(sfx.places(maps))}"
