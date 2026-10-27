"""A release's backend run once, as the app runs it (docs/release.md).

The frozen backend is the one part of a bundle the checks do not run
otherwise, and what PyInstaller left out of it shows only when it runs. So
this starts it as the app does (--watch-stdin, a library folder of its
own: an empty one in a temporary folder), and asks it what the app asks
first:

  its READY line     within START_TIMEOUT, its version package.json's
  /api/status        the same version
  /api/library       the games gamedb knows, none extracted
  /api/import        a made-up disc image (decoders.testing, no game's
                     bytes) read for its program and skipped, as one the
                     viewer does not know: the disc readers, the import job

then closes its stdin and waits for it to go.

  python3 tools/smoke.py <the backend's executable> [its arguments …]
  python3 tools/smoke.py python3 backend/server.py      the source, the same way
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: As long as the app waits (src-tauri/src/backend.rs, START_TIMEOUT): a
#: one-file freeze unpacks itself first.
START_TIMEOUT = 90
UNKNOWN = "SLUS_999.99"


def _made_up_disc(folder: Path) -> Path:
    sys.path.insert(0, str(ROOT / "backend"))
    from decoders.testing import iso_image
    cnf = f"BOOT = cdrom:\\{UNKNOWN};1\r\nTCB = 4\r\n".encode()
    path = folder / "made-up.iso"
    path.write_bytes(iso_image({b"SYSTEM.CNF;1": cnf}, b"MADE_UP"))
    return path


def main(command: list[str]) -> int:
    version = json.loads((ROOT / "app" / "package.json").read_text(encoding="utf-8"))["version"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        disc = _made_up_disc(tmp)
        proc = subprocess.Popen([*command, "--watch-stdin", "--library", str(tmp / "library")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
        lines: queue.Queue[str] = queue.Queue()

        def pump():
            for line in proc.stdout:
                lines.put(line)

        threading.Thread(target=pump, daemon=True).start()
        try:
            started = time.monotonic()
            ready = None
            while ready is None:
                left = START_TIMEOUT - (time.monotonic() - started)
                if left <= 0 or proc.poll() is not None:
                    raise SystemExit(f"smoke: no READY line ({'exited ' + str(proc.returncode) if proc.poll() is not None else 'timed out'})")
                try:
                    line = lines.get(timeout=min(left, 1))
                except queue.Empty:
                    continue
                print(f"  backend: {line.rstrip()}")
                if line.startswith("{"):
                    ready = json.loads(line)
            print(f"smoke: ready in {time.monotonic() - started:.1f} s")
            base = f"http://127.0.0.1:{ready['port']}"

            def call(path: str, body: dict | None = None) -> dict:
                sep = "&" if "?" in path else "?"
                req = urllib.request.Request(f"{base}{path}{sep}token={ready['token']}",
                                             data=json.dumps(body).encode() if body else None,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as reply:
                    return json.loads(reply.read())

            assert ready["version"] == version, f"READY says {ready['version']}, package.json {version}"
            assert call("/api/status")["version"] == version
            games = call("/api/library")["games"]
            assert games and all(g["present"] == 0 for g in games), games
            job = call("/api/import", {"path": str(disc)})
            while job["state"] == "running":
                time.sleep(0.2)
                job = call(f"/api/jobs/{job['id']}")
            assert job["state"] == "done", job
            rows = job["result"]["discs"]
            assert [(r["serial"], r["state"]) for r in rows] == [(UNKNOWN, "skipped")], rows
            print(f"smoke: {version}, {len(games)} games known, a made-up disc read and skipped:"
                  f" {rows[0]['why']}")
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise SystemExit("smoke: the backend did not go when its stdin closed")
    print("smoke: ok")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1:]))
