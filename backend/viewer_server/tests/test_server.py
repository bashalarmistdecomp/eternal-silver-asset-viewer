"""The backend's entry point (server.py): what it writes, and how.

What this CAN catch: stdout or stderr left in the system's code page
(cp1252 on a Windows pipe), whose bytes past ASCII the app's UTF-8 line
reader cannot read.

What it CANNOT catch: the app's side of the pipe.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def test_its_output_is_utf8_whatever_the_code_page():
    code = ("import sys, server; server._utf8_output(); "
            "print('caf\\u00e9 \\u3042'); print('\\u00e9 \\u3042', file=sys.stderr)")
    done = subprocess.run([sys.executable, "-B", "-c", code], cwd=BACKEND, capture_output=True,
                          env={**os.environ, "PYTHONIOENCODING": "cp1252"}, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.decode("utf-8").splitlines() == ["café あ"]
    assert done.stderr.decode("utf-8").splitlines() == ["é あ"]
