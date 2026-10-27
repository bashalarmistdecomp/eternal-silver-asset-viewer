"""What the viewer knows of one disc, read once and shared.

The links and the cards (viewer_tabs.links) read the game through this,
and so can the tabs: a part is read the first time it is asked for and
kept for as long as the disc is open, so the maps and their objects, every
script's commands and what starts each fight are read once per disc, not
once per tab that wants them.

Two discs of one game can carry the same program and LUNADATA.FIL byte
for byte (a game's discs often do). What is read from those two files
alone is read once for both: the model of the first such disc opened is
the other's twin (GameModel.twin), and the parts are the twin's.

A part the disc cannot give (no LUNADATA, a program the decoders do not
know) raises, and the caller says so where it shows it.

The models live as long as the process: `forget` drops a disc's when its
dump is replaced (re-extracted), with its names and its voices' file.
"""

from __future__ import annotations

import threading
from functools import cached_property
from pathlib import Path

from viewer_tabs.names import PROGRAMS, GameNames, UnknownProgram

_UNREAD = object()


class part:
    """A part of the model: read the first time it is asked for, then kept
    on the model. The read is made under the model's lock and the part
    looked for again once the lock is held, so callers that race (the
    links' warm-up and a click) wait for the one read and get its result.
    (functools.cached_property takes no lock since Python 3.12: two
    callers each read the part, and each kept its own.)"""

    def __init__(self, read):
        self.read = read
        self.__doc__ = read.__doc__

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, model, owner=None):
        if model is None:
            return self
        got = model.__dict__.get(self.name, _UNREAD)
        if got is _UNREAD:
            with model.lock:
                got = model.__dict__.get(self.name, _UNREAD)
                if got is _UNREAD:
                    got = model.__dict__[self.name] = self.read(model)
        return got


class GameModel:
    _cache: dict[Path, "GameModel"] = {}
    #: (program, its digest, LUNADATA.FIL's digest) -> the first model read from them
    _twins: dict[tuple, "GameModel"] = {}
    _cache_lock = threading.Lock()

    def __init__(self, ctx):
        self.ctx = ctx
        #: held while a part is read (`part`, `kept`); a part read through
        #: the twin takes the twin's lock too, always after this one
        self.lock = threading.RLock()

    @classmethod
    def for_ctx(cls, ctx) -> "GameModel":
        """The disc's model, one per extracted disc."""
        key = Path(ctx.data_dir)
        with cls._cache_lock:
            model = cls._cache.get(key)
            if model is None:
                model = cls._cache[key] = cls(ctx)
            return model

    @cached_property
    def twin(self) -> "GameModel":
        """The first disc's model opened with this disc's program and
        LUNADATA.FIL, byte for byte: itself, or another disc of the game.
        What is read from those two files alone is kept on the twin."""
        from viewer_tabs.identity import file_digest
        try:
            key = (self.ctx.program, file_digest(Path(self.ctx.exe_path)),
                   file_digest(Path(self.ctx.path("LUNADATA.FIL"))))
        except Exception:
            return self                         # no such file: nothing to share
        with GameModel._cache_lock:
            return GameModel._twins.setdefault(key, self)

    def kept(self, key: str, build):
        """`build(twin)`, made once and kept on the twin: a part read from
        the program and LUNADATA.FIL alone."""
        twin = self.twin
        got = twin.__dict__.get(key)
        if got is None:
            with twin.lock:
                got = twin.__dict__.get(key)
                if got is None:
                    got = twin.__dict__[key] = build(twin)
        return got

    # -- the parts ----------------------------------------------------------

    @part
    def names(self) -> GameNames | None:
        """The game's names (viewer_tabs.names); None off the programs the
        decoders know."""
        if self.twin is not self:
            return self.twin.names
        return GameNames.for_ctx(self.ctx)

    def need_names(self) -> GameNames:
        if self.names is None:
            why = UnknownProgram if self.ctx.program not in PROGRAMS else LookupError
            raise why(f"no names for {self.ctx.program}: "
                      f"{GameNames.why_none(self.twin.ctx)}")
        return self.names

    @part
    def field(self):
        """Every map, its ways in, object sets and scripts (field_view.FieldMaps)."""
        from viewer_tabs.field_view import FieldMaps
        if self.twin is not self:
            return self.twin.field
        return FieldMaps(self.need_names())

    @part
    def fights(self):
        """What starts each battle (battle_music.Fights)."""
        from viewer_tabs import battle_music as bm
        if self.twin is not self:
            return self.twin.fights
        return bm.fights(self.field)

    @part
    def messages(self) -> "Messages":
        """Every script's messages and the portraits they put up."""
        if self.twin is not self:
            return self.twin.messages
        return Messages(self.need_names())


def forget(data_dir) -> None:
    """Drop what the process keeps of the disc extracted at `data_dir`:
    its model, every model whose parts are its (their twin), its names and
    its voices' file. The next to ask reads the dump as it is then."""
    from viewer_tabs.voice_audio import VoiceFile
    here = Path(data_dir).resolve()

    def at(path) -> bool:
        return Path(path).resolve() == here

    with GameModel._cache_lock:
        gone = [m for key, m in GameModel._cache.items() if at(key)]
        gone += [m for m in GameModel._cache.values()
                 if m not in gone and any(m.__dict__.get("twin") is g for g in gone)]
        for table in (GameModel._cache, GameModel._twins):
            for key in [k for k, m in table.items() if any(m is g for g in gone)]:
                del table[key]
    for table in (GameNames._cache, GameNames._errors):
        for key in [k for k in table if at(Path(k[1]).parent)]:
            table.pop(key, None)
    with VoiceFile._cache_lock:
        for key in [k for k in VoiceFile._cache if at(k)]:
            del VoiceFile._cache[key]


class Messages:
    """Every script's messages, read as the Dialogue tab reads them
    (message_window.script_messages, through one window, not drawn), by the
    resource the script is read from (g_ScriptResourcePairs (0x800AF268)).

    A message's portraits are its `said` runs' faces: 0xFAnn on the left,
    0xFBnn on the right (MessageFaceSet (0x8005B36C)); whose each is,
    viewer_tabs.whose says."""

    def __init__(self, names: GameNames):
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from decoders.plugins.SLUS_006_28.formats import message_window as mw
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        from viewer_tabs import system_font
        image = names.binary.code
        kanji = system_font.find()
        words, commands = ss.words_of(image), es.command_count(image)
        chars, table = ss.exe_char_table(image), ss.block(names.read_resource(ss.RESOURCE))
        font = mw.Font(image, rom_font=kanji and kanji.pattern)
        self._names, self._words, self._commands = names, words, commands
        self._chars, self._table, self._font = chars, table, font
        #: resource -> (bytes, commands by offset), read when a label is walked
        self._code: dict[int, tuple] = {}
        #: resource -> its messages drawn, the last few asked for
        self._drawn: dict[int, list] = {}
        #: script -> its text messages in order (message n is [n - 1])
        self._numbered: dict[int, list] = {}
        #: script id -> the resource it is read from
        self.resource_of: dict[int, int] = dict(es.script_resources(image))
        #: resource -> its messages, in the order of its code
        self.by_resource: dict[int, list] = {}
        #: resource -> why it could not be read
        self.errors: dict[int, str] = {}
        for res in sorted(set(self.resource_of.values())):
            try:
                self.by_resource[res] = mw.script_messages(
                    names.read_resource(res), words, chars, table, font, False, commands)
            except Exception as ex:
                self.errors[res] = f"{type(ex).__name__}: {ex}"

    #: Scripts' drawn messages kept.
    KEEP_DRAWN = 4

    def of_script(self, sid: int) -> list:
        return self.by_resource.get(self.resource_of.get(sid, -1), [])

    def numbered(self, sid: int) -> list:
        """Script `sid`'s text messages in the order of its code: message
        n (`message sid/n`) is [n - 1]. A question's answers (command 0x07)
        belong to the message before them and take no number."""
        if sid not in self._numbered:
            self._numbered[sid] = [m for m in self.of_script(sid) if m.answers is None]
        return self._numbered[sid]

    def drawn(self, sid: int) -> list:
        """Script `sid`'s messages with their screens drawn (slower than
        reading them; the last few scripts asked for are kept)."""
        from decoders.plugins.SLUS_006_28.formats import message_window as mw
        res = self.resource_of.get(sid)
        if res is None or res not in self.by_resource:
            return []
        if res not in self._drawn:
            while len(self._drawn) >= self.KEEP_DRAWN:
                self._drawn.pop(next(iter(self._drawn)))
            self._drawn[res] = mw.script_messages(
                self._names.read_resource(res), self._words, self._chars, self._table,
                self._font, True, self._commands)
        return self._drawn[res]

    def _code_of(self, sid: int):
        """Script `sid`'s bytes and commands by offset, or None for a script
        that is not read."""
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        res = self.resource_of.get(sid)
        if res is None or res not in self.by_resource:
            return None
        if res not in self._code:
            buf = self._names.read_resource(res)
            cmds, _gaps = es.script_code(buf, self._words, self._commands)
            self._code[res] = (buf, {c.offset: c for c in cmds})
        return self._code[res]

    def labels(self, sid: int) -> dict[int, int]:
        """Script `sid`'s labels: label n -> its offset (event_script.labels)."""
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        code = self._code_of(sid)
        return es.labels(code[0]) if code else {}

    def walk(self, sid: int, label: int):
        """What running `label` of script `sid` can reach
        (event_script.walk_label), or None for a script that is not read."""
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        code = self._code_of(sid)
        return es.walk_label(*code, label, sid) if code else None

    def of_label(self, sid: int, label: int) -> list:
        """The messages running `label` of script `sid` can show, every way
        its tests can go, in the order the walk meets them."""
        walk = self.walk(sid, label)
        if walk is None:
            return []
        at = {m.offset: m for m in self.of_script(sid)}
        return [at[o] for o in walk.reached if o in at]

    @staticmethod
    def portraits(message) -> list[int]:
        """The portraits a message puts up, in the order they come up, each once."""
        return list(dict.fromkeys(f for said in message.said for _place, f in said.faces))

