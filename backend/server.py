#!/usr/bin/env python3
"""Eternal Silver Asset Viewer — the desktop app's backend.

The Tauri app (app/) starts this and talks to it over HTTP on 127.0.0.1.
It can also be run by hand, for developing the UI in a browser:

    python3 backend/server.py --port 8765 --token dev --library <folder>
    # then, in app/:  npm run dev
    # and open http://localhost:1421/?backend=http://127.0.0.1:8765&token=dev

On start it prints ONE line of JSON to stdout and nothing else there:

    {"ready": true, "port": 41234, "token": "...", "library": "...", "pid": ...}

Its logs go to stderr. Both are UTF-8 whatever the system's code page.

`--library` (or ASSET_VIEWER_LIBRARY) names the library folder: the discs
and everything extracted from them. It must be set before the decoders are
imported, because `decoders.config` resolves every path once, at import.
"""

import argparse
import json
import os
import secrets
import sys
import threading
from pathlib import Path

VERSION = "0.2.5"
FROZEN = getattr(sys, "frozen", False)     # a PyInstaller sidecar build


def _parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0,
                    help="0 (the default) picks a free port")
    ap.add_argument("--token", default=None,
                    help="request token (random when omitted)")
    ap.add_argument("--library", default=None,
                    help="the library folder (overrides ASSET_VIEWER_LIBRARY)")
    ap.add_argument("--watch-stdin", action="store_true",
                    help="exit when stdin closes — the app passes this so "
                         "the backend never outlives its window")
    ap.add_argument("--verbose", action="store_true",
                    default=bool(os.environ.get("VIEWER_VERBOSE")),
                    help="log every request (or set VIEWER_VERBOSE=1)")
    return ap.parse_args(argv)


def _utf8_output():
    """stdout and stderr in UTF-8, whatever the system's code page: the app
    reads both as UTF-8 lines, and a Windows pipe is otherwise in the
    code page (cp1252), whose bytes past ASCII are not UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv=None):
    _utf8_output()
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.library:
        os.environ["ASSET_VIEWER_LIBRARY"] = str(
            Path(args.library).expanduser().resolve())

    if not FROZEN:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from decoders._env import ensure_venv
        ensure_venv(need=("PIL", "numpy"))

    from decoders import config
    from viewer_server.index import INDEXER
    from viewer_server.routes import make_server

    token = args.token or secrets.token_urlsafe(24)
    server = make_server(args.host, args.port, token, VERSION, args.verbose)
    print(json.dumps({"ready": True, "port": server.server_address[1],
                      "token": token, "library": str(config.LIBRARY),
                      "pid": os.getpid(), "version": VERSION}), flush=True)

    # Every disc of the library whose index is missing or stale is indexed
    # in the background; until it is, it is read from its files.
    INDEXER.start()

    if args.watch_stdin:
        def watch():
            try:
                while sys.stdin.read(4096):
                    pass
            except (OSError, ValueError):
                pass
            os._exit(0)
        threading.Thread(target=watch, daemon=True, name="stdin-watch").start()

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
