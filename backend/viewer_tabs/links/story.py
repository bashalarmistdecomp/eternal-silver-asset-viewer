"""What the story's scripts say, and who says it.

Talking to an entity runs a label of the map's script: MapPartyTalkCheck
(0x80067D1C) hands ScriptLabelRun (0x80059FDC) the entity's definition
byte 0xB; touching a trigger does the same (MapObjectTouchRun (0x8007ACD8)).
A label can show the messages its walk reaches (event_script.walk_label):
every way its story-flag tests can go, so an entity's messages are all they
can ever say, not what they say at one moment. Message n of a script is the
n-th text command (0x02, ScriptCommandMessageDisp (0x8005AB1C)) of its code.

A message's portraits are its `said` runs' faces: 0xFAnn puts one up on the
left, 0xFBnn on the right (MessageFaceSet (0x8005B36C)). A portrait is one of
the characters' or no one's (viewer_tabs.whose), so a message's speakers are
characters, and portraits no character is, each a speaker of its own. A
speaker speaks in a script when one of their portraits comes up in its
messages; a message whose first run shows their portrait alone is one they
open. The messages are read once per disc (viewer_tabs.model.Messages).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from viewer_tabs import links, whose
from viewer_tabs.links import CardBody, Edge
from viewer_tabs.refs import Ref, ref

MESSAGE_FACE_SET = "MessageFaceSet (0x8005B36C)"
TALK_CHECK = "MapPartyTalkCheck (0x80067D1C)"
TOUCH_RUN = "MapObjectTouchRun (0x8007ACD8)"
LABEL_RUN = "ScriptLabelRun (0x80059FDC)"
MESSAGE_DISP = "ScriptCommandMessageDisp (0x8005AB1C)"
ANSWER_RUN = "ScriptAnswerRun (0x8005C198)"
#: what running an entity's or a trigger's label is, by object kind
RUN_BY = {"entity": ("Talk", "Run by talking to", TALK_CHECK),
          "trigger": ("Touch", "Run by touching", TOUCH_RUN)}
#: A message's title keeps this many characters of its first line.
TITLE_CHARS = 48


@dataclass
class Spoken:
    """What one speaker says, script by script."""
    #: script -> its messages that put up one of their portraits
    shown: Counter = field(default_factory=Counter)
    #: script -> its messages whose first run shows their portrait alone
    opens: Counter = field(default_factory=Counter)

    @property
    def messages(self) -> int:
        return sum(self.shown.values())


def count_spoken(messages, speaker_of) -> dict[Ref, Spoken]:
    """speaker -> Spoken, from {script: [message_window.Message]};
    `speaker_of` is portrait -> the speaker it names (whose.speaker)."""
    out: dict[Ref, Spoken] = {}
    for sid, ms in messages.items():
        for m in ms:
            faces = [f for said in m.said for _place, f in said.faces]
            for c in dict.fromkeys(speaker_of(f) for f in faces):
                out.setdefault(c, Spoken()).shown[sid] += 1
            first = m.said[0].faces if m.said else []
            if len(first) == 1:
                out.setdefault(speaker_of(first[0][1]), Spoken()).opens[sid] += 1
    return out


def spoken(model) -> dict[Ref, Spoken]:
    """speaker (a character or a portrait) -> what they say, kept for as
    long as the disc is open."""
    def build(model):
        msgs = model.messages
        return count_spoken({sid: msgs.of_script(sid) for sid in sorted(msgs.resource_of)},
                            lambda f: whose.speaker(model, f))
    return model.kept("_story_spoken", build)


@links.unread
def messages_unread(model) -> list[str]:
    """The scripts' resources whose messages could not be read (Messages)."""
    return [f"the messages of resource {res}: {e}"
            for res, e in sorted(model.messages.errors.items())]


def _messages(n: int) -> str:
    return f"{n} message{'s' if n != 1 else ''}"


@links.edges(kept=True)
def story_edges(model):
    """Each speaker -> the scripts their portraits come up in."""
    for who, said in sorted(spoken(model).items()):
        for sid, n in sorted(said.shown.items()):
            yield Edge(who, ref("script", sid), "Speaks in", "Speakers",
                       _messages(n), MESSAGE_FACE_SET)


# -- talk ----------------------------------------------------------------------

def _runs(model) -> dict:
    """(script, label) -> [(object ref, kind)]: the entities and triggers whose
    definition byte 0xB runs the label in a map's script, for every map
    their object set is entered on."""
    def build(model):
        from viewer_tabs.field_view import OBJECT_REF_KINDS
        from viewer_tabs.links import world
        w = world._world(model)
        out: dict = {}
        for s, maps in sorted(w.set_maps.items()):
            scripts = sorted({w.fm.maps[m].area.script for m in maps})
            for i, d in sorted(w.definitions(s).items()):
                kind = OBJECT_REF_KINDS.get(d.kind)
                if kind in RUN_BY and d.event:
                    for sid in scripts:
                        out.setdefault((sid, d.event), []).append((ref(kind, s, i), kind))
        return out
    return model.kept("_story_runs", build)


def said_by_label(model, sid: int, label: int) -> list[int]:
    """The numbers of the text messages running `label` of script `sid` can
    show, in the order its walk meets them."""
    msgs = model.messages
    numbers = {m.offset: n for n, m in enumerate(msgs.numbered(sid), start=1)}
    walk = msgs.walk(sid, label)
    return [numbers[o] for o in (walk.reached if walk else ()) if o in numbers]


@links.edges(kept=True)
def talk_edges(model):
    """Each entity or trigger -> the label it runs and the messages that
    label can show; each such label -> its messages; each message -> the
    speakers whose portraits it shows."""
    said: dict = {}
    for (sid, label), runners in sorted(_runs(model).items()):
        lab = ref("label", sid, label)
        if (sid, label) not in said:
            said[(sid, label)] = said_by_label(model, sid, label)
        numbers = said[(sid, label)]
        for obj, kind in runners:
            rel, back, proof = RUN_BY[kind]
            yield Edge(obj, lab, rel, back, "", proof)
            for n in numbers:
                yield Edge(obj, ref("message", sid, n), "Says", "Said by", "", LABEL_RUN)
        for n in numbers:
            yield Edge(lab, ref("message", sid, n), "Says", "Said when", "", LABEL_RUN)
    msgs = model.messages
    for sid in sorted(msgs.resource_of):
        for n, m in enumerate(msgs.numbered(sid), start=1):
            for who in _speakers(model, m):
                yield Edge(ref("message", sid, n), who, "Speakers", "Lines",
                           "", MESSAGE_FACE_SET)


def _speakers(model, m) -> list[Ref]:
    return list(dict.fromkeys(whose.speaker(model, p) for p in model.messages.portraits(m)))


# -- titles and cards ------------------------------------------------------------

def _message(model, r):
    sid, n = r.id
    msgs = model.messages
    if sid not in msgs.resource_of:
        raise LookupError(f"there is no script {sid}: g_ScriptResourcePairs names none")
    numbered = msgs.numbered(sid)
    if not 1 <= n <= len(numbered):
        raise LookupError(f"script {sid} has {len(numbered)} messages, not {n}")
    return numbered[n - 1]


def _first_words(m) -> str:
    for said in m.said:
        line = " ".join(said.text.split())
        if line:
            return line if len(line) <= TITLE_CHARS else line[:TITLE_CHARS - 1].rstrip() + "…"
    return ""


def _who(model, faces) -> str:
    """The speakers of a run: each character's name ("character n" without
    one), each portrait no character is as "portrait n"."""
    return " & ".join(dict.fromkeys(whose.word(model, whose.speaker(model, f))
                                    for _p, f in faces))


@links.title("message")
def message_title(model, r) -> str | None:
    try:
        m = _message(model, r)
    except LookupError:
        return None
    words = _first_words(m)
    if not words:
        return None
    who = _who(model, m.said[0].faces) if m.said else ""
    return f"{who}: {words}" if who else words


def _label_runners(model, r) -> list:
    return _runs(model).get(tuple(r.id), [])


@links.title("label")
def label_title(model, r) -> str | None:
    """A label by where it runs: talking to someone or touching something
    that runs it, or a square of the map stepped on or examined; else part
    of the scenes whose run reaches it (links.scenes.part_words); else a
    scene on the places
    whose maps run its script, by their records or a hand-over
    (flags._Flags.where), or in the debug room; its reference follows it
    in a link."""
    runners = _label_runners(model, r)
    if not runners:
        from viewer_tabs.links import flags, scenes
        # a square of the map that runs it, else the scenes that reach it
        part = scenes.scene_words(model, r.id) or scenes.part_words(model, *r.id)
        if part:
            return part[:1].upper() + part[1:]
        where = flags._flags(model).where(r.id[0])
        return f"a scene {where}" if where else None
    obj, kind = runners[0]
    what = links.title_of(model, obj)
    more = len({o for o, _k in runners}) - 1
    verb = "Talking to" if kind == "entity" else "Touching"
    return f"{verb} {what}" + (f" and {more} more" if more > 0 else "")


@links.card("label")
def label_card(model, r) -> CardBody:
    from viewer_tabs.links import world
    sid, label = r.id
    msgs = model.messages
    if sid not in msgs.resource_of:
        raise LookupError(f"there is no script {sid}: g_ScriptResourcePairs names none")
    labels = msgs.labels(sid)
    if label not in labels:
        raise LookupError(f"script {sid} has no label {label}: its label table names "
                          f"{len(labels)}")
    walk = msgs.walk(sid, label)
    numbers = said_by_label(model, sid, label)
    places = world._world(model).script_title(sid)
    facts = [("Script", f"script {sid}" + (f", run on {places}" if places else "")),
             ("Says", f"{len(numbers)} message{'s' if len(numbers) != 1 else ''}"
                      + (", every way its tests can go" if len(numbers) > 1 else ""))]
    if walk.handed_over:
        facts.append(("Then runs", ", ".join(f"label {lab} of script {s}"
                                             for s, lab in walk.handed_over)))
    extended = [("Label", f"{label} ({label:#x}) of script {sid} ({sid:#x}), at byte "
                          f"{labels[label]:#x} of resource {msgs.resource_of[sid]}"),
                ("Walked", f"{len(walk.reached)} commands, falling through before jumping "
                           "(event_script.walk_label)")]
    if walk.lost:
        extended.append(("Jumps to no label", ", ".join(map(str, walk.lost))))
    return CardBody(title=label_title(model, r) or f"label {sid}/{label}",
                    subtitle="where a script starts: talking to someone, touching something",
                    facts=facts, extended=extended, proven=[LABEL_RUN, TALK_CHECK, TOUCH_RUN])


def _window_picture(model, sid: int, m):
    """The message's first stop drawn as the game draws its window."""
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    from decoders.plugins.SLUS_006_28.formats import message_window as mw
    from decoders.plugins.SLUS_006_28.formats import system_dat as sd
    from viewer_tabs.links import battle
    drawn = next((d for d in model.messages.drawn(sid) if d.offset == m.offset), None)
    if drawn is None or not drawn.screens:
        return None
    names = model.need_names()
    text = sd.colours(sd.palette_rows(names.read_resource(sd.RESOURCE))[sd.TEXT_ROW])
    faces = battle._faces(model)

    def face(p):
        got = faces.portraits.get(p)
        return fb.image(got[2], faces.colours) if got else None
    return mw.draw(drawn.screens[0], text, face, layout=mw.layout_of(names.binary.code))


@links.card("message")
def message_card(model, r) -> CardBody:
    from viewer_tabs.links import world
    sid, n = r.id
    m = _message(model, r)
    msgs = model.messages
    facts = []
    for said in m.said:
        text = " ".join(said.text.split())
        if text:
            facts.append((_who(model, said.faces) or "Says", text))
    numbered = msgs.numbered(sid)
    following = msgs.of_script(sid)
    at = following.index(m)
    if at + 1 < len(following) and following[at + 1].answers is not None:
        facts.append(("Answers", " / ".join(following[at + 1].answers)))
    places = world._world(model).script_title(sid)
    facts.append(("Where", f"script {sid}" + (f", run on {places}" if places else "")))
    try:
        picture = _window_picture(model, sid, m)
    except (LookupError, ValueError) as ex:
        picture, facts = None, facts + [("Window", f"not drawn: {ex}")]
    return CardBody(
        title=message_title(model, r) or f"message {sid}/{n}",
        subtitle="a message in the game's window",
        picture=picture, facts=facts,
        extended=[("Message", f"{n} of {len(numbered)} in script {sid}: the text command at "
                              f"byte {m.offset:#x} of resource {msgs.resource_of[sid]}"),
                  ("Label", f"after label {m.label} in the code" if m.label is not None
                   else "before the script's first label")],
        proven=[MESSAGE_DISP, MESSAGE_FACE_SET, ANSWER_RUN])
