"""One opened game: every disc of it, each with its own providers.

A game opens whole (viewer_server.library.game_members): both US discs,
the Japanese ones, the demo and the making-of disc are its MEMBERS. Each
member keeps its own DiscContext and FRESH providers (`providers_for`),
because a provider caches its parse with no key and sharing them is how
one disc came to show another's contents. A tab is every member's tab of
that name, its items put together by viewer_server.merge: each row tagged
with the discs that hold it, one version per distinct content.

Providers are not thread-safe and the HTTP server is, so every call into
one goes through the session's lock. That serialises a slow selection
behind nothing but its own game.

A disc the library has indexed (viewer_server.index) lists its tabs from
its index, not by reading the disc: each row's data is then a `Kept`, its
row as the app shows it, and the provider's item is read again when it is
wanted (`_data`): when it is selected, and when a link looks for its home.
A disc whose index is missing or stale, or a tab its index does not hold,
is read as before.

A thing of the game (viewer_tabs.refs) has a card and links
(viewer_tabs.links), read from the disc it was met on; `locate` finds the
row of the tab that is its home, for a link's *Open in*.

Music plays live (viewer_server.music): a selected score opens a stream,
and the next selection closes it unless it is the transport's track
(`keep`), which also stays held however many selections follow. A stream
renders under its own lock, never the session's, so music plays on while
a slow selection decodes.
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict

from decoders.plugins.SLUS_006_28.formats.lunadata import LunaDataArchive
from decoders.psx.gamedb.database import InstalledGame
from decoders.psx.gamedb.known_games import disc_tag, version_group

from viewer_tabs import links as tab_links
from viewer_tabs.context import DiscContext
from viewer_tabs.identity import tab_sources
from viewer_tabs.model import GameModel
from viewer_tabs.refs import Ref, written, written_hex
from viewer_tabs.tab_providers import PROVIDER_CLASSES, providers_for

from viewer_server import exporting
from viewer_server import index as library_index
from viewer_server.index import AGAIN, Kept
from viewer_server.library import _disc_row, partial
from viewer_server.merge import Listing, Row, merge
from viewer_server.music import MusicStream
from viewer_server.present import item_rows, present, tab_meta
from viewer_server.video import VideoStream

#: Selections kept for Export. The UI only ever exports what is on screen;
#: a few spare covers a click that lands just after the next selection.
KEEP_RESULTS = 12
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
#: The most a saved picture is blown up.
MAX_SCALE = 8


def tab_key(cls) -> str:
    """A tab's stable key: its provider's `key`, or else its class name."""
    return getattr(cls, "key", cls.__name__)


def _held(rows, m: int, holds) -> tuple[int, int] | None:
    """(row, version) of the first of disc m's items `holds` claims
    (`holds(entry)`)."""
    for item, row in enumerate(rows):
        for v, version in enumerate(row.versions):
            entry = next((e for e in version.entries if m in e.holders), None)
            if entry is not None and entry.data is not None and holds(entry):
                return item, v
    return None


class Unkept(Exception):
    """A disc's index lists an item its provider no longer gives as listed:
    the tab is read from the discs instead."""


class Member:
    """One disc of the open game."""

    def __init__(self, game: InstalledGame):
        self.game = game
        self.ctx = DiscContext.for_game(game)
        self.tag = disc_tag(game.disc_id)
        self.group = version_group(game.program)
        self.providers = {tab_key(type(p)): p for p in providers_for(self.ctx)}
        self.archive: LunaDataArchive | None = None
        #: the library's index of this disc, when there is to be one
        self.index = library_index.of_ctx(self.ctx) if library_index.enabled() else None

    def start(self):
        """Open LUNADATA's table of contents if this disc has one."""
        lunadata = self.ctx.path("LUNADATA.FIL")
        if lunadata.exists():
            self.archive = LunaDataArchive(lunadata)


class Tab:
    """One tab of the game: the members that have it."""

    def __init__(self, cls, members: list[int]):
        self.cls = cls
        self.key = tab_key(cls)
        self.members = members


class GameSession:
    def __init__(self, key: str, title: str, games: list[InstalledGame],
                 store):
        self.id = secrets.token_hex(6)
        self.key = key
        self.title = title
        self.members = [Member(g) for g in games]
        self.store = store
        self.lock = threading.RLock()
        self.tabs = [Tab(cls, [m for m, member in enumerate(self.members)
                               if tab_key(cls) in member.providers])
                     for cls in PROVIDER_CLASSES]
        self.tabs = [t for t in self.tabs if t.members]
        self._items: dict[int, tuple[str | None, list[Row]]] = {}
        #: (tab, disc) -> its provider's items in the tab's view, read
        #: for a row its index lists (`_data`); dropped with the tab's rows
        self._live: dict[tuple[int, int], list] = {}
        #: tabs read from the discs whatever their indexes hold (`Unkept`)
        self._unkept: set[str] = set()
        self._results: OrderedDict[str, dict] = OrderedDict()
        self.videos: dict[str, VideoStream] = {}
        #: result id -> its score playing live; under `music_lock`
        self.music: dict[str, MusicStream] = {}
        self.music_lock = threading.Lock()
        self._latest: str | None = None     # the latest selection's id
        self._warmed = False                # the first disc's links are being built

    def start(self):
        for member in self.members:
            member.start()

    def _warm_links(self):
        """Build the first disc's links in the background once its first
        list is out, so the first selection does not wait for all of them.
        Read from the disc's index they are quickly there, and nothing
        else is read on the way; then the maps are read (GameModel.field),
        which every map's page and the first link followed want."""
        if self._warmed or not self.members:
            return
        self._warmed = True

        def build():
            try:
                model = self.model(0)
                index = tab_links.LinkIndex.of(model)
                if index.kept is not None:
                    model.field
            except Exception:
                pass                # the selection that needs them says why
        threading.Thread(target=build, daemon=True, name="links-warm").start()

    @property
    def games(self) -> list[InstalledGame]:
        return [m.game for m in self.members]

    # -- description ------------------------------------------------------

    def describe(self) -> dict:
        tabs = []
        for i, tab in enumerate(self.tabs):
            meta = tab_meta(i, self._provider(tab, tab.members[0]))
            meta["views"] = self._views(tab)
            meta["discs"] = [self.members[m].tag for m in tab.members]
            tabs.append(meta)
        first = self.members[0] if self.members else None
        return {
            "id": self.id,
            "key": self.key,
            "label": self.title,
            "title": self.title,
            "status": "",
            "members": [{"tag": m.tag, "disc": _disc_row(m.game)}
                        for m in self.members],
            "program": first.ctx.program if first else "",
            "plugin": any(m.ctx.has_plugin for m in self.members),
            "partial": partial(self.key),
            "exportsDir": str(first.ctx.exports_dir()) if first else "",
            "tabs": tabs,
        }

    # -- tabs -------------------------------------------------------------

    def _tab(self, index: int) -> Tab:
        if not 0 <= index < len(self.tabs):
            raise KeyError(f"no tab {index}")
        return self.tabs[index]

    def _provider(self, tab: Tab, member: int):
        return self.members[member].providers[tab.key]

    def _views(self, tab: Tab) -> list[str]:
        views: list[str] = []
        for m in tab.members:
            prov = self._provider(tab, m)
            for v in getattr(prov, "get_views", lambda: [])():
                if v not in views:
                    views.append(v)
        return views

    def _set_view(self, tab: Tab, view: str | None) -> str | None:
        views = self._views(tab)
        if not views:
            return None
        if view not in views:
            current = getattr(self._provider(tab, tab.members[0]), "view", None)
            view = current if current in views else views[0]
        for m in tab.members:
            prov = self._provider(tab, m)
            if view in getattr(prov, "get_views", lambda: [])():
                prov.view = view
        return view

    def _listings(self, tab: Tab, view: str | None) -> list[Listing]:
        """Each member's items, members whose sources match listed once."""
        shared: dict[tuple, int] = {}
        holders: dict[int, list[int]] = {}
        for m in tab.members:
            prov = self._provider(tab, m)
            if view is not None and view not in getattr(prov, "get_views", lambda: [])():
                continue
            member = self.members[m]
            sources = (None if hasattr(prov, "item_identity")
                       else tab_sources(prov, member.ctx))
            if sources is not None:
                at = shared.setdefault((member.group, sources), m)
                if at != m:
                    holders[at].append(m)
                    continue
            holders[m] = [m]
        out = []
        for m, held in holders.items():
            member = self.members[m]
            kept = (None if tab.key in self._unkept or getattr(member, "index", None) is None
                    else member.index.listed(tab.key, view))
            if kept is not None:
                out.append(Listing(tuple(held), member.group, kept))
                continue
            prov = self._provider(tab, m)
            items = prov.get_items({}, member.archive, member.ctx, None)
            identify = getattr(prov, "item_identity", None)
            out.append(Listing(
                tuple(held), member.group,
                [(label, data,
                  identify(label, data, member.ctx) if identify and data is not None
                  else None)
                 for label, data in items]))
        return out

    def _rows(self, index: int, view: str | None) -> tuple[str | None, list[Row]]:
        tab = self._tab(index)
        view = self._set_view(tab, view)
        held = self._items.get(index)
        if held is not None and held[0] == view:
            return held
        rows = merge(self._listings(tab, view))
        self._items[index] = (view, rows)
        for key in [k for k in self._live if k[0] == index]:
            del self._live[key]
        return view, rows

    def _data(self, index: int, entry, check: bool = True):
        """The provider's item for a row's entry. One the index lists is
        the item it holds where it holds it (plain data), else read again
        from its disc's provider, by its place in the list (which the
        tab's view is set to): the list must be the one the index holds,
        label by label, and with `check` the item must be the one it
        lists, its identity and digest. Unkept when it is not."""
        data = entry.data
        if not isinstance(data, Kept):
            return data
        if data.item is not AGAIN:
            return data.item
        tab, m = self._tab(index), entry.holders[0]
        member = self.members[m]
        prov = self._provider(tab, m)
        live = self._live.get((index, m))
        if live is None:
            live = prov.get_items({}, member.archive, member.ctx, None)
            kept = member.index.listed(tab.key, self._items[index][0]) or []
            if [label for label, _data in live] != [label for label, _kept, _ident in kept]:
                raise Unkept(f"{tab.key}: disc {member.tag} lists other items than its index")
            self._live[(index, m)] = live
        label, item = live[entry.item]
        if check and entry.identity is not None:
            ident = prov.item_identity(label, item, member.ctx)
            if (ident.key != entry.identity.key or ident.size != entry.identity.size
                    or (ident.digest is None) != (entry.identity.digest is None)
                    or (ident.digest is not None and ident.digest() != entry.identity.digest())):
                raise Unkept(f"{tab.key}: {label!r} on disc {member.tag} is not the item its index lists")
        return item

    def _read_live(self, index: int, why: Unkept):
        """Read tab `index` from the discs from now on (Unkept)."""
        import sys
        print(f"index: {why}; read from the discs instead", file=sys.stderr)
        self._unkept.add(self._tab(index).key)
        self._items.pop(index, None)

    def _tags(self, holders) -> list[str]:
        return [self.members[m].tag for m in holders]

    def items(self, index: int, view: str | None) -> dict:
        with self.lock:
            tab = self._tab(index)
            view, rows = self._rows(index, view)
            first = self._provider(tab, tab.members[0])
            shown = [self._shown(first, r.versions[0].first) for r in rows]
            for out, row in zip(shown, rows):
                out["tags"] = self._tags(row.holders)
                if len(row.versions) > 1:
                    out["versions"] = [self._tags(v.holders) for v in row.versions]
                fan = self._fan_row(tab, row.versions[0].first)
                if fan:
                    out["fan"] = fan
            self._warm_links()
            return {"tab": index, "view": view,
                    "layerOptions": len(first.get_layer_options())
                    if first.supports_layers else 0,
                    "discs": [self.members[m].tag for m in tab.members],
                    "rows": shown}

    @staticmethod
    def _shown(first, entry) -> dict:
        """A row as the app shows it (present.item_rows): as the index
        holds it, or made from the provider's item."""
        if isinstance(entry.data, Kept):
            return dict(entry.data.row)
        return item_rows(first, [(entry.label, entry.data)])[0]

    def _fan_row(self, tab: Tab, entry) -> dict | None:
        """How Fan mode words a row, where its tab says (a provider's
        `fan_row(label, data, ctx)`: {"title", "sub"}, either left out to
        keep the row's own), asked of the disc that holds it."""
        if isinstance(entry.data, Kept):
            return entry.data.fan
        m = entry.holders[0]
        fan = getattr(self._provider(tab, m), "fan_row", None)
        if fan is None or entry.data is None:
            return None
        try:
            return fan(entry.label, entry.data, self.members[m].ctx)
        except Exception:
            return None                     # the row as written

    def select(self, index: int, view: str | None, item: int,
               version: int = 0, keep: str | None = None) -> dict:
        """`keep`: the result the transport has loaded. Its stream stays
        open and it stays held, past KEEP_RESULTS newer ones."""
        self._music_only(keep)
        with self.lock:
            tab = self._tab(index)
            view, rows = self._rows(index, view)
            if not 0 <= item < len(rows):
                raise KeyError(f"no item {item} in tab {index}")
            row = rows[item]
            version = max(0, min(version, len(row.versions) - 1))
            entry = row.versions[version].first
            try:
                data = self._data(index, entry)
            except Unkept as why:
                self._read_live(index, why)
                view, rows = self._rows(index, view)
                if not 0 <= item < len(rows):
                    raise KeyError(f"no item {item} in tab {index}")
                row = rows[item]
                version = max(0, min(version, len(row.versions) - 1))
                entry = row.versions[version].first
                data = entry.data
            m = entry.holders[0]
            member = self.members[m]
            prov = self._provider(tab, m)
            result = prov.on_select(data, {}, member.archive, member.ctx)

            vm, layers = present(result, prov, self.store)
            if result.movie is not None:
                vm["video"] = self._open_video(result.movie)

            rid = secrets.token_hex(5)
            self._latest = rid
            if keep in self._results:
                self._results.move_to_end(keep)
            self._results[rid] = {"result": result, "label": entry.label,
                                  "layers": layers, "member": m}
            while len(self._results) > KEEP_RESULTS:
                self._results.popitem(last=False)
            if result.music is not None:
                stream = self._music_only(rid, keep, source=result.music)
                vm["audio"]["live"] = stream.describe()
            if result.ref is not None:
                vm["ref"] = result.ref.json()
                vm["links"] = self._links(m, result.ref)
                vm.update(self._named(m, result.ref))
            vm["id"] = rid
            vm["label"] = entry.label
            vm["disc"] = member.tag
            vm["tags"] = self._tags(row.versions[version].holders)
            vm["version"] = version
            vm["versions"] = [self._tags(v.holders) for v in row.versions]
            # the disc it came from: Export writes to that program's folder
            vm["program"] = member.ctx.program
            vm["exportsDir"] = str(member.ctx.exports_dir())
            return vm

    def save(self, rid: str, name: str, data: bytes, scale: int = 1) -> str:
        """A picture the app drew of result `rid` (a map as shown, an area,
        a layer): <exports>/<the item>/<name>.png, `scale` times as big,
        each pixel a block (the app draws at 1x: a 4x map is more than a
        webview's canvas holds)."""
        held = self._results.get(rid)
        if held is None:
            raise KeyError("that selection is no longer held — select it again")
        if not data.startswith(PNG_MAGIC):
            raise ValueError("only PNG pictures are saved")
        if not 1 <= scale <= MAX_SCALE:
            raise ValueError(f"scale {scale}: 1 to {MAX_SCALE}")
        out_dir = self.members[held["member"]].ctx.exports_dir() / exporting.stem_of(held["label"])
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{exporting.stem_of(name)}.png"
        if scale == 1:
            path.write_bytes(data)
        else:
            import io
            from PIL import Image
            with Image.open(io.BytesIO(data)) as img:
                img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(path)
        return str(path)

    # -- links ------------------------------------------------------------

    def member_of(self, disc: str | None = None, result: str | None = None) -> int:
        """The disc a request means: by its tag, or the one result `result`
        came from; the first disc when it names neither."""
        if result:
            held = self._results.get(result)
            if held is None:
                raise KeyError("that selection is no longer held — select it again")
            return held["member"]
        if disc:
            for m, member in enumerate(self.members):
                if member.tag == disc:
                    return m
            raise KeyError(f"no disc {disc!r} in this game")
        return 0

    def model(self, m: int) -> GameModel:
        return GameModel.for_ctx(self.members[m].ctx)

    def _links(self, m: int, r: Ref) -> list[dict]:
        """`r`'s links on disc m, grouped as its card groups them; empty
        when the disc's links cannot be read."""
        try:
            model = self.model(m)
            return tab_links.groups(model, tab_links.LinkIndex.of(model), r)
        except Exception:
            return []

    def _named(self, m: int, r: Ref) -> dict:
        """What the Inspector heads a thing with: its title, as a link to
        it shows it, and its reference, in decimal and in hex."""
        out = {"written": written(r), "hex": written_hex(r)}
        try:
            out["title"] = tab_links.title_of(self.model(m), r)
        except Exception:
            out["title"] = written(r)
        return out

    def locate(self, r: Ref, m: int) -> dict | None:
        """The row that is `r`'s home on disc m: the first tab whose
        provider lists its kind (`homes`) and claims one of that disc's
        items (`holds`), looked for in the view the tab is on when that is
        one of the kind's views (else the first). None when no tab lists it."""
        with self.lock:
            return next(self._homes(r, m), None)

    def homes(self, r: Ref, m: int) -> list[dict]:
        """Every tab's row that is `r`'s home on disc m, in the tabs' order
        (a chest's: its map, and the Items tab's Treasure)."""
        with self.lock:
            return list(self._homes(r, m))

    def _homes(self, r: Ref, m: int):
        ctx = self.members[m].ctx
        for index, tab in enumerate(self.tabs):
            views = getattr(tab.cls, "homes", {}).get(r.kind)
            if views is None or m not in tab.members:
                continue
            prov = self._provider(tab, m)
            current = getattr(prov, "view", None)
            view, rows = self._rows(index, current if current in views else views[0])

            def holds(entry):
                return prov.holds(self._data(index, entry, check=False), r, ctx)
            try:
                found = _held(rows, m, holds)
            except Unkept as why:
                self._read_live(index, why)
                view, rows = self._rows(index, view)
                found = _held(rows, m, holds)
            if found is not None:
                yield {"tab": index, "key": tab.key, "name": tab.cls.name,
                       "view": view, "item": found[0], "version": found[1]}

    def card(self, r: Ref, m: int) -> dict:
        """`r`'s card as disc m knows it, with its homes: the first is its
        "Open in"."""
        with self.lock:
            out = tab_links.build_card(self.model(m), r, self.store.put_image)
        out["homes"] = self.homes(r, m)
        out["home"] = out["homes"][0] if out["homes"] else None
        out["disc"] = self.members[m].tag
        return out

    # -- export -----------------------------------------------------------

    def export(self, rid: str, kind: str, layer: int | None,
               every: bool, passes: int | None = None) -> list[str]:
        """A score's WAV is rendered here, whole: its endless loop played
        `passes` times (the map's by default), then its ending."""
        held = self._results.get(rid)
        if held is None:
            raise KeyError("that selection is no longer held — select it again")
        out_dir = self.members[held["member"]].ctx.exports_dir()
        result = held["result"]
        if kind == "png":
            paths = exporting.export_png(out_dir, held["label"], result,
                                         held["layers"], layer, every)
        elif kind in ("wav", "midi"):
            audio = dict(result.audio or {})
            if kind == "wav" and audio.get("render_wav"):
                audio["wav"] = audio["render_wav"](int(passes) if passes
                                                   else None)
                if passes and audio.get("passes"):
                    audio["name"] = (f"{audio.get('name', 'clip')}"
                                     f"_x{int(passes)}")
            paths = [exporting.export_audio(out_dir, audio, kind)]
        else:
            raise ValueError(f"unknown export kind {kind!r}")
        return [str(p) for p in paths]

    # -- music ------------------------------------------------------------

    def _music_only(self, *keep: str | None, source=None) -> MusicStream | None:
        """Close every stream but those of `keep`; with `source`, the first
        of them plays it (opened if it was not)."""
        with self.music_lock:
            closing = [self.music.pop(rid) for rid in list(self.music)
                       if rid not in keep]
            stream = None
            if source is not None:
                stream = self.music.get(keep[0])
                if stream is None:
                    stream = self.music[keep[0]] = MusicStream(source)
        for old in closing:
            old.close()
        return stream

    def music_stream(self, rid: str, reopen: bool = False,
                     keep: str | None = None) -> MusicStream:
        """The open stream of result `rid`. With `reopen`, a selection
        still held plays again, the transport asked it to (closing the
        rest but the latest selection's and `keep`'s)."""
        with self.music_lock:
            stream = self.music.get(rid)
        if stream is not None or not reopen:
            if stream is None:
                raise KeyError("that music is no longer playing")
            return stream
        held = self._results.get(rid)
        source = held and held["result"].music
        if source is None:
            raise KeyError("that selection is no longer held — select it again")
        return self._music_only(rid, keep, self._latest, source=source)

    # -- video ------------------------------------------------------------

    def _open_video(self, movie) -> dict:
        # One movie at a time per game: a stream holds the image open.
        for vid in list(self.videos):
            self.videos.pop(vid).close()
        stream = VideoStream(movie)
        vid = secrets.token_hex(5)
        self.videos[vid] = stream
        return {"id": vid, **stream.describe()}

    def close(self):
        for stream in self.videos.values():
            stream.close()
        self.videos.clear()
        self._music_only()
