"""The HTTP layer over a real socket: the server on a free port, a client on
one kept-alive connection — a made-up open game, no disc.

What this CAN catch: a reply sent before the request's body was read
leaving the body on the connection, where it is read as the next request;
a caller without the token being read from at all; a Content-Length that
is negative (which blocked a thread on read(-1)) or not a number (a 500);
a HEAD that runs a GET with an effect, such as playing a piece of a music
stream.

What it CANNOT catch: the routes' own answers, which their tests and the
running app cover.
"""

import http.client
import json
import socket
import threading
from pathlib import Path

import pytest

from viewer_server.routes import make_server

TOKEN = "made-up-token"


class _Stream:
    """A music stream that counts the pieces it played."""

    def __init__(self):
        self.played = 0

    def pcm(self, start, frames):
        self.played += 1
        return b"\0\0\0\0", {"at": start}


class _Session:
    def __init__(self):
        self.stream = _Stream()

    def music_stream(self, rid, reopen=False, keep=None):
        return self.stream


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, TOKEN, "test")
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _connect(server) -> http.client.HTTPConnection:
    return http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)


def _ask(conn, method, path, body=None, token=TOKEN, headers=None):
    head = {"X-Viewer-Token": token, **(headers or {})}
    if body is not None:
        head.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=body, headers=head)
    resp = conn.getresponse()
    return resp, resp.read()


def test_an_early_error_leaves_no_body_behind(server):
    conn = _connect(server)
    body = json.dumps({"view": "Maps", "item": 3}).encode()
    resp, _ = _ask(conn, "POST", "/api/sessions/abc123/tabs/0/select", body)
    assert resp.status == 404                       # no such game open
    sock = conn.sock
    resp, data = _ask(conn, "GET", "/api/status")
    assert conn.sock is sock                        # the same connection
    assert resp.status == 200 and json.loads(data)["version"] == "test"


def test_a_picture_for_a_closed_game_leaves_no_body_behind(server):
    conn = _connect(server)
    resp, _ = _ask(conn, "POST", "/api/sessions/abc123/save?result=r", b"\x89PNG made up",
                   headers={"Content-Type": "image/png"})
    assert resp.status in (400, 404)
    resp, data = _ask(conn, "GET", "/api/status")
    assert resp.status == 200 and json.loads(data)["version"] == "test"


def test_without_the_token_nothing_is_read_and_the_connection_closes(server):
    conn = _connect(server)
    resp, _ = _ask(conn, "POST", "/api/sessions", b'{"key": "made-up"}', token="wrong")
    assert resp.status == 401
    assert resp.getheader("Connection") == "close"
    resp, data = _ask(conn, "GET", "/api/status")   # http.client opens a new one
    assert resp.status == 200


def _raw(server, request: bytes) -> bytes:
    """Send `request` as it is and read until the server closes."""
    with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=5) as s:
        s.sendall(request)
        out = b""
        while chunk := s.recv(65536):
            out += chunk
        return out


@pytest.mark.parametrize("length", [b"-1", b"twelve"])
def test_a_bad_content_length_is_a_400_at_once(server, length):
    got = _raw(server, b"POST /api/sessions HTTP/1.1\r\nHost: x\r\nX-Viewer-Token: "
               + TOKEN.encode() + b"\r\nContent-Length: " + length + b"\r\n\r\n{}")
    assert got.startswith(b"HTTP/1.1 400"), got[:80]


def test_head_is_answered_where_a_get_changes_nothing(server):
    conn = _connect(server)
    resp, data = _ask(conn, "HEAD", "/api/status")
    assert resp.status == 200 and data == b""
    assert int(resp.getheader("Content-Length")) > 0


def test_head_does_not_play_a_piece_of_the_music(server):
    from viewer_server.routes import Handler
    session = _Session()
    Handler.backend.sessions["abc123"] = session
    conn = _connect(server)
    path = "/api/sessions/abc123/music/def456/pcm?from=0&frames=1"
    resp, _ = _ask(conn, "HEAD", path)
    assert resp.status == 405 and session.stream.played == 0
    resp, data = _ask(conn, "GET", path)
    assert resp.status == 200 and data == b"\0\0\0\0" and session.stream.played == 1


def test_a_second_extraction_waits_for_the_first(server, monkeypatch, tmp_path):
    from viewer_server import library
    go = threading.Event()

    def extract(job, image):
        go.wait(5)
        return {"key": None, "discId": "made-up", "dir": str(tmp_path / "made-up-disc"),
                "recognized": True, "files": 0, "tag": "", "game": None, "gameTitle": ""}

    monkeypatch.setattr(library, "extract", extract)
    monkeypatch.setattr(library, "scan", lambda path: [library._batch_row(Path(path), None, "waiting")])
    for name in ("one.cue", "two.cue"):
        (tmp_path / name).write_text("made up")
    one, two = (json.dumps({"path": str(tmp_path / n)}).encode() for n in ("one.cue", "two.cue"))
    conn = _connect(server)

    def ended(job):
        for _ in range(500):
            resp, data = _ask(conn, "GET", f"/api/jobs/{job}")
            if json.loads(data)["state"] != "running":
                return json.loads(data)["state"]
            threading.Event().wait(0.01)

    first, data = _ask(conn, "POST", "/api/import", one)
    assert first.status == 200
    second, answer = _ask(conn, "POST", "/api/import", two)
    assert second.status == 409, answer
    go.set()
    assert ended(json.loads(data)["id"]) == "done"
    third, data = _ask(conn, "POST", "/api/import", two)
    assert third.status == 200 and ended(json.loads(data)["id"]) == "done"


def test_an_import_of_nothing_there_is_refused(server, tmp_path):
    conn = _connect(server)
    resp, answer = _ask(conn, "POST", "/api/import",
                        json.dumps({"path": str(tmp_path / "gone")}).encode())
    assert resp.status == 404, answer
