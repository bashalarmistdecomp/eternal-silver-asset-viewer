"""The HTTP API the desktop app calls. JSON in, JSON out, plus blobs.

Bound to 127.0.0.1 only, and every request must carry the token printed on
the READY line (`?token=` or an `X-Viewer-Token` header): a web page in the
user's browser can reach localhost too, and the token is what it lacks.
CORS is open because the token is the check — the app's own origin is
`tauri://localhost` (or `http://tauri.localhost`), never this server's.

    GET  /api/status                         the library folder + backend facts
    GET  /api/library                        extracted discs, grouped
    POST /api/import {path}                  -> job: extract an image, or every
                                             new disc in a folder
    POST /api/reextract {key[, path] | game} -> job: a disc's dump made again
                                             (or needsPath), or a game's
    GET  /api/jobs/<id>                      progress
    POST /api/sessions {key}                 open a game (a library slot)
    GET  /api/sessions/<sid>                 its tabs
    DELETE /api/sessions/<sid>
    GET  /api/sessions/<sid>/tabs/<i>/items?view=
    POST /api/sessions/<sid>/tabs/<i>/select {view, item, version, keep}
    POST /api/sessions/<sid>/export {result, kind, layer, all, passes}
    POST /api/sessions/<sid>/save?result=&name=&scale=  a PNG the app drew
    GET  /api/sessions/<sid>/locate?kind=&id=&disc=|result=
                                             where a thing is listed
    GET  /api/sessions/<sid>/card?kind=&id=&disc=|result=   a thing's card
    GET  /api/sessions/<sid>/videos/<vid>/chunk?start=&count=
    GET  /api/sessions/<sid>/music/<rid>/pcm?from=&frames=
                                             16-bit stereo; X-Music: where
    POST /api/sessions/<sid>/music/<rid>/seek {seconds, loop, keep}
    POST /api/sessions/<sid>/music/<rid>/loop {loop, at}
    GET  /api/sessions/<sid>/music/<rid>/overview?have=&wait=
    GET  /api/blob/<id>                      PNG / WAV / MIDI, Range-aware
    POST /api/reveal {path}                  show in the file manager

A request's body is read whole before it is routed, so a reply sent early
(a wrong token, a game no longer open) cannot leave it on the connection
to be read as the next request; a body that is not read (no token, no
usable length) closes the connection instead. HEAD is answered only where
a GET changes nothing (the blobs, the status): a HEAD on a music stream
would otherwise play a piece of it.
"""

from __future__ import annotations

import hmac
import json
import re
import sys
import threading
import traceback
from collections import OrderedDict
from collections.abc import Callable
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from viewer_server import index as library_index
from viewer_server import library
from viewer_server.blobs import BlobStore
from viewer_server.jobs import Busy, Job, Jobs
from viewer_server.music import Stale
from viewer_server.session import GameSession

#: Games kept open at once. Re-opening one of these is instant (its tabs'
#: parses are held); the oldest is closed past this.
KEEP_SESSIONS = 2
#: The largest picture the app may hand over to be saved (a 4x map is tens of
#: MB), and so the largest body any request may carry.
MAX_PICTURE = 512 * 1024 * 1024


class HttpError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


class Backend:
    """State shared by every request thread."""

    def __init__(self, token: str, version: str):
        self.token = token
        self.version = version
        self.blobs = BlobStore()
        self.jobs = Jobs()
        self.sessions: OrderedDict[str, GameSession] = OrderedDict()
        self.by_key: dict[str, str] = {}
        self.lock = threading.Lock()

    def session(self, sid: str) -> GameSession:
        with self.lock:
            s = self.sessions.get(sid)
            if s is None:
                raise HttpError(404, "that game is no longer open")
            self.sessions.move_to_end(sid)
            return s

    def open(self, key: str) -> GameSession:
        """Open a game: a library slot's key ("lunar-1"), or
        "program:<serial>" for a disc of no game."""
        try:
            title, games = library.game_members(key)
        except KeyError:
            raise HttpError(404, f"no game {key!r}")
        if not games:
            raise HttpError(404, f"{title}: no disc of it is extracted yet")
        with self.lock:
            sid = self.by_key.get(key)
            if sid and sid in self.sessions:
                held = self.sessions[sid]
                if [g.path for g in held.games] == [g.path for g in games]:
                    self.sessions.move_to_end(sid)
                    return held
                # A disc was added or removed since: open it afresh.
                self.sessions.pop(sid).close()
        s = GameSession(key, title, games, self.blobs)
        s.start()
        with self.lock:
            self.sessions[s.id] = s
            self.by_key[key] = s.id
            while len(self.sessions) > KEEP_SESSIONS:
                _sid, old = self.sessions.popitem(last=False)
                old.close()
        return s

    def close(self, sid: str):
        with self.lock:
            s = self.sessions.pop(sid, None)
            for key, value in list(self.by_key.items()):
                if value == sid:
                    del self.by_key[key]
        if s is not None:
            s.close()

    def forget(self, dump: Path):
        """The dump at `dump` (a disc's folder) is being replaced: close
        every game holding it, and drop what this process keeps of its
        reading (viewer_tabs.model.forget, and of its index), so the next
        reading is of the dump as it is then."""
        from viewer_tabs.model import forget
        dump = Path(dump).resolve()
        with self.lock:
            holding = [sid for sid, s in self.sessions.items()
                       if any(Path(g.path).resolve() == dump for g in s.games)]
        for sid in holding:
            self.close(sid)
        forget(dump)
        library_index.forget(dump)

    def extract(self, batch: Callable[[], list[dict]]) -> Job:
        """Start extracting a batch of disc images (library.scan,
        library.reextract_rows): a job whose result's `discs` are the
        batch's rows, each extracted in turn and said to be added or
        failed as it goes. One extraction job runs at a time (Busy
        otherwise): each holds its whole image. A dump replaced is
        forgotten (Backend.forget) before, is not indexed while it is
        replaced (Indexer.replacing), and every dump written is forgotten
        after. The job's last step indexes the discs added
        (viewer_server.index, stage "index"); another extraction may start
        meanwhile, and a disc opens read from its files until its index is
        made."""

        def work(job):
            job.progress("Looking for disc images…")
            rows = batch()
            job.result = {"discs": rows}
            added = []
            for n, row in enumerate(rows):
                if row["state"] != "waiting":
                    continue
                # a row is replaced whole, never changed, while the app reads them
                rows[n] = {**row, "state": "extracting"}
                job.progress("Starting…")
                try:
                    replaced = library.find_game(row["key"]) if row["key"] else None
                    if replaced is not None:
                        self.forget(replaced.path)   # a game holding it is closed
                    with (library_index.INDEXER.replacing(replaced.path) if replaced is not None
                          else nullcontext()):
                        result = library.extract(job, row["path"])
                    self.forget(Path(result["dir"]))
                except Exception as exc:
                    traceback.print_exc()
                    rows[n] = {**row, "state": "failed", "why": str(exc) or type(exc).__name__}
                    continue
                rows[n] = {**row, "state": "added", "key": result["key"],
                           "serial": result["discId"], "tag": result["tag"],
                           "game": result["game"], "gameTitle": result["gameTitle"],
                           "files": result["files"], "recognized": result["recognized"]}
                if result["key"]:
                    added.append(result["key"])
            games = [g for g in map(library.find_game, added) if g is not None]
            if games:
                job.let_go("index")
                job.progress("Indexing…")
                library_index.INDEXER.build_each(games, job.progress)
            return job.result

        return self.jobs.start("extract", work, alone=True)


ROUTES: list[tuple[str, re.Pattern, str, bool]] = []


def route(method: str, pattern: str, head: bool = False):
    """A route; `head`: a GET that changes nothing, so HEAD may ask it too."""
    def wrap(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn.__name__, head))
        return fn
    return wrap


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "EternalSilverAssetViewer"
    backend: Backend = None          # set by make_server
    verbose = False
    #: the request's body, read before it is routed (_read_body)
    raw_body: bytes = b""

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt, *args):
        if self.verbose:
            # Never the query string: it carries the token.
            line = (fmt % args).replace(self.path, urlparse(self.path).path)
            sys.stderr.write(f"{self.address_string()} {line}\n")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Viewer-Token, Range")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers",
                         "Content-Range, Accept-Ranges, Content-Length, "
                         "X-Music")

    def _send(self, status: int, body: bytes, mime: str, extra=(),
              cache: bool = False):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        # A blob id names one immutable object, so the webview may keep it
        # (an animation's frames are swapped many times a second); every
        # JSON reply is live state and must not be.
        self.send_header("Cache-Control", "private, max-age=86400, immutable"
                         if cache else "no-store")
        for k, v in extra:
            self.send_header(k, v)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        body = json.dumps(payload, separators=(",", ":"), default=str).encode()
        self._send(status, body, "application/json")

    def _read_body(self) -> bytes:
        """The request's body, all of it (see the module's docstring). A
        length that is not a number of bytes, or one past MAX_PICTURE, is
        refused unread, and the connection closes after the reply."""
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            raise HttpError(411, "a body must come with its Content-Length")
        given = self.headers.get("Content-Length")
        if given is None:
            return b""
        try:
            length = int(given)
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            raise HttpError(400, f"bad Content-Length: {given!r}")
        if length > MAX_PICTURE:
            self.close_connection = True
            raise HttpError(413, "the request is too large")
        return self.rfile.read(length) if length else b""

    def _body(self) -> dict:
        if not self.raw_body:
            return {}
        try:
            return json.loads(self.raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HttpError(400, f"bad JSON: {exc}")

    def _authorised(self, query) -> bool:
        given = (self.headers.get("X-Viewer-Token")
                 or (query.get("token") or [""])[0])
        return hmac.compare_digest(given.encode(), self.backend.token.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        self.raw_body = b""
        try:
            if not self._authorised(query):
                # Nothing is read for a caller without the token.
                self.close_connection = True
                raise HttpError(401, "missing or wrong token")
            self.raw_body = self._read_body()
            for m, pattern, name, head in ROUTES:
                match = pattern.match(url.path)
                if match and (m == method or (method == "HEAD" and m == "GET")):
                    if m != method and not head:
                        raise HttpError(405, f"no HEAD for {url.path}: ask with GET")
                    getattr(self, name)(query, *match.groups())
                    return
            raise HttpError(404, f"no route {method} {url.path}")
        except HttpError as exc:
            self._json({"error": str(exc), **exc.extra}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            traceback.print_exc()
            # What failed may have been the reading of the body.
            self.close_connection = True
            try:
                self._json({"error": f"{exc.__class__.__name__}: {exc}"}, 500)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # -- library ----------------------------------------------------------

    @route("GET", "/api/status", head=True)
    def status(self, query):
        self._json({"version": self.backend.version,
                    "folder": library.folder()})

    @route("GET", "/api/library")
    def get_library(self, query):
        self._json(library.library())

    def _extract(self, batch: Callable[[], list[dict]]) -> Job:
        try:
            return self.backend.extract(batch)
        except Busy:
            raise HttpError(409, "a disc is being extracted already: try "
                                 "again when it is done")

    @route("POST", "/api/import")
    def import_disc(self, query):
        """A disc image, or a folder: every disc image in it and its
        subfolders that the library does not hold yet (library.scan)."""
        path = (self._body().get("path") or "").strip()
        if not path or not Path(path).expanduser().exists():
            raise HttpError(404, f"not found: {path}")
        self._json(self._extract(lambda: library.scan(path)).describe())

    @route("POST", "/api/reextract")
    def reextract(self, query):
        """A disc's dump made again from its image (`key`; from `path`, an
        image the user found for it, when it moved), or every disc of a
        game's (`game`: a library slot)."""
        body = self._body()
        if body.get("game"):
            try:
                _title, games = library.game_members(body["game"])
            except KeyError:
                raise HttpError(404, "no such game")
            if not games:
                raise HttpError(404, "no disc of it is extracted")
            rows = library.reextract_rows(games)
        else:
            game = library.find_game(body.get("key", ""))
            if game is None:
                raise HttpError(404, "no such disc")
            if body.get("path"):
                try:
                    rows = library.reextract_rows([game], body["path"])
                except (OSError, ValueError) as exc:
                    raise HttpError(400, str(exc))
            elif game.source is None or not game.source.exists():
                raise HttpError(409, "the disc image this dump came from was not "
                                     "found — choose it again", needsPath=True)
            else:
                rows = library.reextract_rows([game])
        self._json(self._extract(lambda: rows).describe())

    @route("GET", "/api/jobs/([0-9a-f]+)")
    def job(self, query, job_id):
        job = self.backend.jobs.get(job_id)
        if job is None:
            raise HttpError(404, "no such job")
        self._json(job.describe())

    @route("POST", "/api/reveal")
    def reveal(self, query):
        try:
            library.reveal(self._body().get("path", ""))
        except PermissionError as exc:
            raise HttpError(403, str(exc))
        self._json({"ok": True})

    # -- sessions ---------------------------------------------------------

    @route("POST", "/api/sessions")
    def open_session(self, query):
        s = self.backend.open(self._body().get("key", ""))
        self._json(s.describe())

    @route("GET", "/api/sessions/([0-9a-f]+)")
    def get_session(self, query, sid):
        self._json(self.backend.session(sid).describe())

    @route("DELETE", "/api/sessions/([0-9a-f]+)")
    def delete_session(self, query, sid):
        self.backend.close(sid)
        self._json({"ok": True})

    @route("GET", r"/api/sessions/([0-9a-f]+)/tabs/(\d+)/items")
    def items(self, query, sid, tab):
        s = self.backend.session(sid)
        view = (query.get("view") or [None])[0]
        try:
            self._json(s.items(int(tab), view))
        except KeyError as exc:
            raise HttpError(404, str(exc))

    @route("POST", r"/api/sessions/([0-9a-f]+)/tabs/(\d+)/select")
    def select(self, query, sid, tab):
        s = self.backend.session(sid)
        body = self._body()
        try:
            self._json(s.select(int(tab), body.get("view"),
                                int(body.get("item", -1)),
                                int(body.get("version") or 0),
                                body.get("keep")))
        except KeyError as exc:
            raise HttpError(404, str(exc))

    @route("POST", "/api/sessions/([0-9a-f]+)/export")
    def export(self, query, sid):
        body = self._body()
        try:
            paths = self.backend.session(sid).export(
                body.get("result", ""), body.get("kind", "png"),
                body.get("layer"), bool(body.get("all")),
                body.get("passes"))
        except (KeyError, ValueError) as exc:
            raise HttpError(400, str(exc))
        self._json({"paths": paths})

    @route("POST", "/api/sessions/([0-9a-f]+)/save")
    def save(self, query, sid):
        data = self.raw_body
        if not data:
            raise HttpError(400, "no picture")
        try:
            path = self.backend.session(sid).save((query.get("result") or [""])[0],
                                                  (query.get("name") or ["picture"])[0], data,
                                                  int((query.get("scale") or ["1"])[0]))
        except (KeyError, ValueError) as exc:
            raise HttpError(400, exc.args[0] if exc.args else str(exc))
        self._json({"path": path})

    def _thing(self, query, sid):
        """The session, the reference (?kind=&id=) and the disc (?disc= or
        ?result=) of a links request."""
        from viewer_tabs.refs import parse
        session = self.backend.session(sid)
        try:
            r = parse((query.get("kind") or [""])[0], (query.get("id") or [""])[0])
            m = session.member_of((query.get("disc") or [None])[0],
                                  (query.get("result") or [None])[0])
        except KeyError as exc:
            raise HttpError(404, exc.args[0] if exc.args else str(exc))
        except ValueError as exc:
            raise HttpError(400, exc.args[0] if exc.args else str(exc))
        return session, r, m

    @route("GET", "/api/sessions/([0-9a-f]+)/locate")
    def locate(self, query, sid):
        """Where a thing is listed: {tab, key, name, view, item, version}."""
        session, r, m = self._thing(query, sid)
        found = session.locate(r, m)
        if found is None:
            from viewer_tabs.refs import written
            raise HttpError(404, f"no tab lists {written(r)}")
        self._json(found)

    @route("GET", "/api/sessions/([0-9a-f]+)/card")
    def card(self, query, sid):
        """A thing's card (viewer_tabs.links)."""
        session, r, m = self._thing(query, sid)
        self._json(session.card(r, m))

    @route("GET", "/api/sessions/([0-9a-f]+)/videos/([0-9a-f]+)/chunk")
    def video_chunk(self, query, sid, vid):
        stream = self.backend.session(sid).videos.get(vid)
        if stream is None:
            raise HttpError(404, "that movie is no longer open")
        start = int((query.get("start") or ["0"])[0])
        count = int((query.get("count") or ["150"])[0])
        self._json(stream.chunk(start, count))

    # -- music ------------------------------------------------------------

    def _music(self, sid: str, rid: str, reopen: bool = False,
               keep: str | None = None):
        try:
            return self.backend.session(sid).music_stream(rid, reopen, keep)
        except KeyError as exc:
            raise HttpError(404, exc.args[0] if exc.args else str(exc))

    @route("GET", "/api/sessions/([0-9a-f]+)/music/([0-9a-f]+)/pcm")
    def music_pcm(self, query, sid, rid):
        stream = self._music(sid, rid)
        start = int((query.get("from") or ["0"])[0])
        frames = int((query.get("frames") or ["44100"])[0])
        try:
            data, where = stream.pcm(start, frames)
        except Stale as exc:
            raise HttpError(409, str(exc))
        self._send(200, data, "application/octet-stream",
                   [("X-Music", json.dumps(where, separators=(",", ":")))])

    @route("POST", "/api/sessions/([0-9a-f]+)/music/([0-9a-f]+)/seek")
    def music_seek(self, query, sid, rid):
        body = self._body()
        stream = self._music(sid, rid, True, body.get("keep"))
        self._json(stream.seek(float(body.get("seconds") or 0),
                               bool(body.get("loop", True))))

    @route("POST", "/api/sessions/([0-9a-f]+)/music/([0-9a-f]+)/loop")
    def music_loop(self, query, sid, rid):
        body = self._body()
        stream = self._music(sid, rid)
        self._json(stream.set_loop(bool(body.get("loop")),
                                   int(body.get("at") or 0)))

    @route("GET", "/api/sessions/([0-9a-f]+)/music/([0-9a-f]+)/overview")
    def music_overview(self, query, sid, rid):
        stream = self._music(sid, rid)
        have = int((query.get("have") or ["0"])[0])
        wait = min(10.0, float((query.get("wait") or ["0"])[0]))
        self._json(stream.overview_state(have, wait))

    # -- blobs ------------------------------------------------------------

    @route("GET", "/api/blob/([0-9a-f]+)(?:\\.\\w+)?", head=True)
    def blob(self, query, bid):
        hit = self.backend.blobs.get(bid)
        if hit is None:
            raise HttpError(404, "expired — select the item again")
        data, mime = hit
        # WebKitGTK's media stack (GStreamer) seeks with Range requests,
        # and some builds will not play a clip it cannot seek in at all.
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if m and (m.group(1) or m.group(2)):
            size = len(data)
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start, end = max(0, size - int(m.group(2))), size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                self._send(416, b"", mime, [("Content-Range", f"bytes */{size}")])
                return
            self._send(206, data[start:end + 1], mime,
                       [("Content-Range", f"bytes {start}-{end}/{size}"),
                        ("Accept-Ranges", "bytes")], cache=True)
            return
        self._send(200, data, mime, [("Accept-Ranges", "bytes")], cache=True)


def make_server(host: str, port: int, token: str, version: str,
                verbose: bool = False) -> ThreadingHTTPServer:
    Handler.backend = Backend(token, version)
    Handler.verbose = verbose
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
