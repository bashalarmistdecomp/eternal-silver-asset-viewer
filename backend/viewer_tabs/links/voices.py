"""Voices: the lines the game streams from `_AUDIO.XA`, where the scripts
play them, and the messages they go with.

A voice is a number (formats.xa_voices): xa_voice_get (0x800238BC) gives
its channel and sectors from g_XaVoices. A script keeps one with command
0x52 (ScriptCommandVoiceSet (0x8005E9FC) -> VoiceSet (0x80055470)) and
starts it with 0x53 (ScriptCommandVoiceStart (0x8005EA44)); a bromide
plays one of its own (links.media). No table ties a voice to a message:
what goes with one is what the message window shows while it plays, which
formats.script_voices reads from the commands around it.

A battle plays voices of its own (records.battle_voices): a spell's or a
monster attack's show keeps the voice its effect row names (BtlShowOpen
(0x8007B7C8)), four set battles play one before their first monster's own
shows (BtlActingShowRun (0x8003A158)), and slot 5 plays one as it brings a
fallen party member back (BtlSlot5Revive (0x80028E5C)). A voice nothing
plays is said to be so: VoiceSet's only callers are the scripts, the
bromides and these.

A voice's speakers are who the portraits its messages put up name
(MessageFaceSet (0x8005B36C), viewer_tabs.whose) and who a battle plays it
for as they act: the characters who cast the spell (the spells they keep,
the ones they pick acting by themselves), the monsters whose rows or
planners use the attack, a set battle's monster, the one who revives
(records.battle_voices). It has one speaker when they are all one, or all
have one name in the string table (two characters may share a name, and a
monster may have a character's); otherwise it has several.

Message n of a script is its n-th text command, a question's answers
(command 0x07) taking no number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from viewer_tabs import links, whose
from viewer_tabs.links import CardBody, Edge
from viewer_tabs.refs import Ref, ref

VOICE_SET = "ScriptCommandVoiceSet (0x8005E9FC)"
VOICE_START = "ScriptCommandVoiceStart (0x8005EA44)"
VOICE_SET_FN = "VoiceSet (0x80055470)"
MESSAGE_FACE_SET = "MessageFaceSet (0x8005B36C)"
PICTURE_VOICE = "PictureXaPlay (0x800247AC)"

#: What the voice card's battle links are grouped under, by what plays it.
BATTLE_BACK = {"spell": "Played by spells", "monster-attack": "Played by monster attacks",
               "battle": "Played in battles", "character": "Played by"}
#: The acting ids BtlShowOpen keeps an effect's other voice for, in words:
#: a party slot holds a character's number, a monster slot a monster's.
OTHER_IDS = "character 11 or monster 11, 124 or 125"

#: How a message goes with a voice, in plain words.
WHEN = {"shown": "up as it starts", "during": "comes up while it plays"}
#: The first words of a message a title quotes.
QUOTE = 32


@dataclass(frozen=True)
class Said:
    """A message a voice goes with."""
    script: int
    number: int                 # message n of the script
    offset: int
    when: str                   # "shown" or "during"
    #: the portraits up as the voice meets it: its last words' for "shown",
    #: its first words' for "during"
    portraits: tuple[int, ...]
    #: who those portraits name (whose.speaker), each once
    speakers: tuple[Ref, ...]
    #: the words the voice meets (the same run), and all its words, as the
    #: Dialogue tab reads them
    text: str
    whole: str


@dataclass
class Played:
    """One place a script starts a voice (formats.script_voices.Play)."""
    script: int
    play: object
    said: list[Said] = field(default_factory=list)


@dataclass(frozen=True)
class InBattle:
    """One way a battle plays a voice."""
    #: the spell, monster attack, battle or character it plays for
    by: Ref
    #: how, in plain words
    how: str
    proof: str
    #: who it plays for: the characters or monsters that cast it so
    casters: tuple[Ref, ...] = ()
    #: what they do as it plays, in words ("casting ‹spell›")
    act: str = ""


@dataclass
class Use:
    """Everything that plays one voice on a disc."""
    voice: int
    plays: list[Played] = field(default_factory=list)
    #: (script, label) whose run reaches a 0x52 of it
    labels: list[tuple[int, int]] = field(default_factory=list)
    #: the bromides that play it (g_PictureVoices)
    bromides: list[int] = field(default_factory=list)
    #: what plays it in a battle
    battle: list[InBattle] = field(default_factory=list)

    @property
    def said(self) -> list[Said]:
        out: list[Said] = []
        for p in self.plays:
            out += [s for s in p.said if (s.script, s.number) not in
                    {(o.script, o.number) for o in out}]
        return out

    @property
    def said_speakers(self) -> list[Ref]:
        """Who the portraits its messages put up name, each once."""
        return list(dict.fromkeys(c for s in self.said for c in s.speakers))

    @property
    def casters(self) -> list[Ref]:
        """Who it plays for in battle, each once."""
        return list(dict.fromkeys(c for b in self.battle for c in b.casters))

    @property
    def speakers(self) -> list[Ref]:
        """Its speakers: who its messages' portraits name, then who casts it."""
        return list(dict.fromkeys(self.said_speakers + self.casters))

    @property
    def speaker(self) -> Ref | None:
        """The one speaker its messages and its battles name, or None."""
        found = self.speakers
        return found[0] if len(found) == 1 else None

    @property
    def portraits(self) -> list[int]:
        return list(dict.fromkeys(p for s in self.said for p in s.portraits))


class Voices:
    """The disc's voices and what plays them, read once per disc."""

    def __init__(self, model):
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from decoders.plugins.SLUS_006_28.formats import script_voices as sv
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
        from decoders.plugins.SLUS_006_28.records import events as ev
        names = model.need_names()
        image = names.binary.code
        self.table = {v.number: v for v in xv.voices(image)}
        self.proof = xv.proof(image)
        self.uses: dict[int, Use] = {}
        #: why a script's voices could not be read, by script
        self.errors: dict[int, str] = {}
        msgs = model.messages
        words = msgs._words
        chars = ss.exe_char_table(image)
        strings = ss.block(names.read_resource(ss.RESOURCE))
        self._speaker = lambda f: whose.speaker(model, f)
        for sid in sorted(msgs.resource_of):
            try:
                self._script(msgs, sid, words, chars, strings, es, sv)
            except Exception as ex:          # one script failing leaves the rest
                self.errors[sid] = f"{type(ex).__name__}: {ex}"
        try:
            for k, v in enumerate(ev.picture_voices(image)):
                self.use(v).bromides.append(k)
        except LookupError as ex:
            self.errors[-1] = f"the bromides' voices: {ex}"
        try:
            self._battles(model, image)
        except LookupError as ex:
            self.errors[-2] = f"the battles' voices: {ex}"

    def use(self, voice: int) -> Use:
        if voice not in self.uses:
            self.uses[voice] = Use(voice)
        return self.uses[voice]

    def _battles(self, model, image) -> None:
        """The voices the battles play, and who each plays for
        (records.battle_voices)."""
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from decoders.plugins.SLUS_006_28.records import battle_voices as bv
        from viewer_tabs.links import battle
        shows = bv.show_voices(image)
        t = battle._tables(model)
        owners = {n: (rec.values["level"], rec.values["chr_id"]) for n, rec in t.spells.items()}
        # a spell or a monster attack -> the slot ids that can use it
        who: dict[Ref, set[int]] = {}
        for n, ids in bv.level_spells(owners).items():
            who.setdefault(ref("spell", n), set()).update(ids)
        msgs = model.messages
        for sid in sorted(msgs.resource_of):
            code = msgs._code_of(sid)
            if code is None:
                continue
            buf, cmds = code
            for i, n in es.spells_given(buf, cmds.values()):
                if n in owners and bv.script_spell_ok(i, owners[n][1]):
                    who.setdefault(ref("spell", n), set()).add(i)
        for i, spells in bv.PICKED_SPELLS.items():
            for n in spells:
                who.setdefault(ref("spell", n), set()).add(i)
        for m, rec in t.monsters.items():
            if rec.is_empty:
                continue
            v = rec.values
            for a in (v["attack_number"], v["kind7_number"], *bv.planned_attacks(m)):
                if a:
                    who.setdefault(ref("monster-attack", a), set()).add(m)
        users = [(ref("spell", n), rec.values["show_number"])
                 for n, rec in sorted(t.spells.items())]
        users += [(ref("monster-attack", n), rec.values["spell_id"])
                  for n, rec in sorted(t.attacks.items()) if not rec.is_empty]
        for by, show in users:
            row = shows.get(show)
            if row is None:
                continue
            kind, verb = ("character", "casting") if by.kind == "spell" else ("monster", "using")
            ids = sorted(who.get(by, ()))
            if row.other_voice == row.voice:
                ways = [(row.voice, ids, f"its show, {show}: effect {show}'s row names it")]
            else:
                ways = [(row.voice, [i for i in ids if not bv.other_voice(i)],
                         f"its show, {show}, cast by anyone but {OTHER_IDS}"),
                        (row.other_voice, [i for i in ids if bv.other_voice(i)],
                         f"its show, {show}, cast by {OTHER_IDS}")]
            act = f"{verb} {links.title_of(model, by)}"
            for voice, casters, how in ways:
                if voice and casters:           # a voice no one casts it with plays for no one
                    self.use(voice).battle.append(InBattle(
                        by, how, bv.SHOW_OPEN, tuple(ref(kind, i) for i in casters), act))
        for b, voice in sorted(bv.SET_BATTLE_VOICES.items()):
            if b not in t.battles:
                continue
            ids = t.monster_ids(b)
            first = (ref("monster", ids[0]),) if ids else ()
            self.use(voice).battle.append(InBattle(
                ref("battle", b), f"before the monster in slot {bv.SET_BATTLE_SLOT}, the first "
                                  "of its group, acts with a show of its own (0x97 and up)",
                bv.ACTING_SHOW_RUN, first, f"before its own shows in battle {b}"))
        self.use(bv.REVIVE_VOICE).battle.append(InBattle(
            ref("character", bv.REVIVER_ID), "as they bring a fallen party member back "
                                             "from slot 5", bv.REVIVE,
            (ref("character", bv.REVIVER_ID),), "bringing a fallen party member back"))

    def _script(self, msgs, sid, words, chars, strings, es, sv) -> None:
        code = msgs._code_of(sid)
        if code is None:
            return
        buf, cmds = code
        if not sv.voice_sets(buf, cmds):
            return
        ends = {o: sv.text_end(buf, o, words, chars, strings)
                for o, c in cmds.items() if c.id == es.TEXT}
        numbered = msgs.numbered(sid)
        number = {m.offset: n for n, m in enumerate(numbered, start=1)}
        at = {m.offset: m for m in numbered}
        walked = sv.script_voices(buf, cmds, ends, sid)
        for p in walked.plays:
            played = Played(sid, p)
            for when, offsets in (("shown", p.shown), ("during", p.during)):
                for o in offsets:
                    m = at.get(o)
                    if m is None or o not in number:
                        continue
                    run = (m.said[-1] if when == "shown" else m.said[0]) if m.said else None
                    faces = tuple(dict.fromkeys(f for _place, f in run.faces)) if run else ()
                    played.said.append(Said(
                        sid, number[o], o, when, faces,
                        tuple(dict.fromkeys(self._speaker(f) for f in faces)),
                        run.text if run else "", "\n".join(s.text for s in m.said)))
            self.use(p.voice).plays.append(played)
        # the labels whose run can reach a 0x52, taking every way their
        # tests go (as event_script.walk_label takes them)
        for k in walked.kept:
            u = self.use(k.voice)
            u.labels += [(sid, label) for label in k.labels if (sid, label) not in u.labels]


def voices(model) -> Voices:
    """The disc's voices, kept for as long as the disc is open (and shared
    with its twin: GameModel.kept)."""
    return model.kept("_voices", Voices)


@links.unread
def voices_unread(model) -> list[str]:
    """The scripts whose voices could not be read, and the bromides' or the
    battles' when theirs could not."""
    return [f"script {sid}'s voices: {e}" if sid >= 0 else e
            for sid, e in sorted(voices(model).errors.items())]


# -- words ---------------------------------------------------------------------

def _speaker_word(model, r: Ref) -> str:
    """A speaker by name, else "character n", "monster n" or "portrait n"."""
    if r.kind == "monster":
        names = model.names
        return (names.enemy(r.id[0]) if names is not None else None) or f"monster {r.id[0]}"
    return whose.word(model, r)


def _speaker_name(model, r: Ref) -> str | None:
    """A character's or a monster's name from the string table; None for a
    portrait or a number with no name."""
    if r.kind == "character":
        return whose.name(model, r.id[0])
    if r.kind == "monster":
        names = model.names
        return names.enemy(r.id[0]) if names is not None else None
    return None


def speaker_name(model, u: Use) -> str | None:
    """The one name all of a voice's speakers have, or None: characters of
    one name (two numbers may share it) and a monster the string table
    names as a character is named are one speaker by that name."""
    found = {_speaker_name(model, r) for r in u.speakers}
    return found.pop() if len(found) == 1 and None not in found else None


def speaker_words(model, u: Use) -> str:
    """A voice's speakers in words, a name said once however many numbers
    have it."""
    return ", ".join(dict.fromkeys(_speaker_word(model, c) for c in u.speakers))


def speaker_note(u: Use) -> str:
    """Why a voice's speakers are theirs, in words."""
    said, cast = bool(u.said_speakers), bool(u.casters)
    if said and cast:
        return "the portrait its messages show, and who casts it in battle"
    return "who casts it in battle" if cast else "the portrait its messages show"


def acts(u: Use, caster: Ref) -> list[str]:
    """What a caster does as the voice plays, each once."""
    return list(dict.fromkeys(b.act for b in u.battle if caster in b.casters and b.act))


def quote(text: str, n: int = QUOTE) -> str:
    """A message's first words, on one line: “...”."""
    line = " ".join(text.split())
    return f"“{line[:n].rstrip()}…”" if len(line) > n else f"“{line}”"


def battle_word(model, u: Use) -> str:
    """What plays a voice in battle, in words: the first of them and how
    many more."""
    found = list(dict.fromkeys(b.by for b in u.battle))
    if not found:
        return ""
    more = len(found) - 1
    first = links.title_of(model, found[0])
    if found[0].kind == "character":         # what they do, not who says it
        first = f"{first}'s revive"
    return first + (f" and {more} more" if more else "")


def title(model, n: int) -> str:
    """A voice's title: its speaker's name, else its first message's
    words, else what plays it in battle, with its number."""
    u = voices(model).uses.get(n)
    name = speaker_name(model, u) if u is not None else None
    if name:
        return f"{name} · voice {n}"
    if u is not None and u.said:
        return f"{quote(u.said[0].text)} · voice {n}"
    if u is not None and u.battle:
        return f"{battle_word(model, u)} · voice {n}"
    return f"voice {n}"


def heading(model, n: int) -> tuple[str, str]:
    """The group a voice is listed under, and what the group means."""
    u = voices(model).uses.get(n)
    if u is not None and u.speakers:
        name = speaker_name(model, u)
        if name:
            return name, speaker_note(u)
        if u.speaker is not None:
            return _speaker_word(model, u.speaker), speaker_note(u)
        return "More than one speaker", ("its messages show, or its casters are, several "
                                         "people")
    if u is not None and u.plays:
        if u.said:
            return "No portrait", "the messages it goes with show no portrait"
        return "Over a scene", "it plays while no message is up"
    if u is not None and u.bromides:
        return "With the bromides", "a bromide plays it while it is shown"
    if u is not None and u.battle:
        return "In battle", ("a battle plays it: a spell's or a monster attack's show, a set "
                             "battle, or a revive (records.battle_voices)")
    return "Not played", ("nothing plays it: VoiceSet (0x80055470) is called by the scripts, "
                          "the bromides and the battles, and none of them names it")


# -- the links -----------------------------------------------------------------

@links.title("voice")
def voice_title(model, r) -> str | None:
    if model.names is None:
        return None
    return title(model, r.id[0])


@links.edges(kept=True)
def voice_edges(model):
    """Each label -> the voices its run can set; each voice -> the messages
    it goes with, and its speaker where they all show one."""
    v = voices(model)
    for n, u in sorted(v.uses.items()):
        for sid, label in u.labels:
            yield Edge(ref("label", sid, label), ref("voice", n), "Voices", "Played by labels",
                       "command 0x52", VOICE_SET)
        for s in u.said:
            yield Edge(ref("voice", n), ref("message", s.script, s.number), "Messages",
                       "Voices", WHEN[s.when], VOICE_START)
        said = u.said_speakers
        if len(said) == 1:
            yield Edge(ref("voice", n), said[0], "Speaker", "Voices",
                       "the portrait its messages show", MESSAGE_FACE_SET)
        for c in u.casters:
            if c not in said:
                yield Edge(ref("voice", n), c, "Speaker", "Voices", _listed(acts(u, c)),
                           next(b.proof for b in u.battle if c in b.casters))
        for b in u.battle:
            yield Edge(b.by, ref("voice", n), "Voices", BATTLE_BACK[b.by.kind], b.how, b.proof)


def _face(model, u: Use) -> int | None:
    """The portrait a voice's card shows: the first its messages put up,
    else the first character caster's own, the one the battle menu shows
    for them (BtlMenuActingFaceSet (0x80049D60))."""
    if u.portraits:
        return u.portraits[0]
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    for c in u.casters:
        if c.kind == "character" and 1 <= c.id[0] <= whose.PARTY_LAST:
            return fb.member_face(c.id[0])
    return None


def _listed(words: list[str], n: int = 3) -> str:
    more = len(words) - n
    return ", ".join(words[:n]) + (f" and {more} more" if more > 0 else "")


@links.card("voice")
def voice_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
    from viewer_tabs.links import battle
    n = r.id[0]
    v = voices(model)
    voice = v.table.get(n)
    if voice is None:
        raise LookupError(f"there is no voice {n}: the game's voices are {xv.FIRST} to {xv.LAST}")
    u = v.uses.get(n) or Use(n)
    facts = [("Lasts", f"{voice.seconds:.1f} seconds")]
    name = speaker_name(model, u)
    if name or u.speaker is not None:
        facts.append(("Said by", name or _speaker_word(model, u.speaker)))
    elif u.speakers:
        facts.append(("Said by", "not one speaker: " + speaker_words(model, u)))
    if u.said:
        first = u.said[0]
        facts.append(("Goes with", f"{quote(first.text, 80)} (message {first.script}/"
                                   f"{first.number}, {WHEN[first.when]})"))
    elif u.plays:
        facts.append(("Goes with", "no message: it plays over the scene"))
    plays = len(u.plays)
    if plays:
        scripts = sorted({p.script for p in u.plays})
        facts.append(("Played", f"{plays} time{'s' if plays != 1 else ''} in "
                                f"{len(scripts)} script{'s' if len(scripts) != 1 else ''}"))
    if u.bromides:
        facts.append(("With", "a bromide, while it is shown"))
    if u.battle:
        facts.append(("In battle", battle_word(model, u)))
    if not plays and not u.bromides and not u.battle:
        facts.append(("Played", "by nothing: no script, bromide or battle names it"))
    picture = None
    face = _face(model, u) if name or u.speaker is not None else None
    if face is not None:
        from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
        faces = battle._faces(model)
        got = faces.portraits.get(face)
        if got is not None and any(got[2]):
            picture = fb.image(got[2], faces.colours)
    extended = [
        ("Channel", f"{voice.channel} of _AUDIO.XA's 16"),
        ("Sectors", f"{voice.start} to {voice.end} of the file ({voice.sectors} sectors, "
                    f"{voice.channel_sectors} of its channel)"),
        ("Table row", f"g_XaVoices + {n} × 2: {voice.entry:#06x} (channel {voice.channel}, "
                      f"start {voice.entry & 0xFFF:#x} × 16)"),
        ("End", f"{'the next row' if voice.by_next else 'g_XaChannelEnds'} less {voice.less}"
                f", × 16"),
    ]
    for p in u.plays[:8]:
        extended.append((f"Script {p.script}", f"0x52 at {p.play.set_at:#06x}, 0x53 at "
                                               f"{p.play.start_at:#06x}"))
    for b in u.battle[:8]:
        extended.append((links.title_of(model, b.by), b.how))
    proven = [v.proof, VOICE_SET_FN, VOICE_SET, VOICE_START, "ScriptVoiceStep (0x8005A328)"]
    if u.said_speakers:
        proven.append(MESSAGE_FACE_SET)
    if u.bromides:
        proven.append(PICTURE_VOICE)
    proven += list(dict.fromkeys(b.proof for b in u.battle))
    note = ""
    if u.plays and not u.said:
        note = ("No message is up while it plays: the script starts it with no message "
                "open and none comes up before it can have ended.")
    return CardBody(title=title(model, n), subtitle="a voice line", picture=picture,
                    facts=facts, note=note, extended=extended, proven=proven)
