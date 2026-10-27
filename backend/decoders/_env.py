"""Run under the repo's own venv, whichever `python3` started us.

pyenv shims shadow `source .venv/bin/activate`: `python3` still resolves to
the shim, which ignores the venv and loses its packages (Pillow, numpy).
Entry points call ensure_venv() before importing anything heavy; if the
repo's venv exists and we are not running inside it, the process re-execs
itself under the venv's python. Missing dependencies after that are a hard
error, never a silent degrade.
"""
import os
import sys

#: backend/decoders/_env.py -> the repository root
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VENV = os.path.join(ROOT, ".venv")
VENV_PY = (os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt"
           else os.path.join(VENV, "bin", "python3"))
#: Set for the re-exec'd child, so a broken venv cannot loop.
_GUARD = "_ASSET_VIEWER_VENV_REEXEC"


def in_venv():
    # sys.prefix, not sys.executable: the venv python is a symlink to the
    # system interpreter, so executable paths compare equal even outside
    # the venv. sys.prefix is the truth.
    return os.path.realpath(sys.prefix) == os.path.realpath(VENV)


def ensure_venv(need=()):
    if in_venv():
        # Healed. Drop the guard: the environment is inherited by every
        # child process, and a leftover guard would stop theirs.
        os.environ.pop(_GUARD, None)
    # Re-exec only for script invocations: under `python -c` argv[0] is
    # "-c" and the command string can't be reconstructed — fall through
    # to the dependency check instead.
    elif (os.path.exists(VENV_PY)
            and os.environ.get(_GUARD) != "1"
            and os.path.isfile(sys.argv[0])):
        os.environ[_GUARD] = "1"
        os.execv(VENV_PY, [VENV_PY] + sys.argv)

    for mod in need:
        try:
            __import__(mod)
        except ImportError:
            sys.exit(
                f"FATAL: {mod} is not importable from {sys.executable}.\n"
                "The venv is missing or broken — recreate it from the "
                "repository root with:\n"
                "  python3 -m venv .venv && "
                ".venv/bin/python3 -m pip install -r backend/requirements.txt")


def system_env() -> dict[str, str] | None:
    """The environment for a program of the system's own (fc-list,
    xdg-open), or None to inherit ours.

    A frozen build's bootloader points LD_LIBRARY_PATH at the libraries it
    unpacked, built on another system: a system program that loads them may
    fail. It keeps the user's own value in LD_LIBRARY_PATH_ORIG, which goes
    back for the program."""
    if not getattr(sys, "frozen", False):
        return None
    env = dict(os.environ)
    mine = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if mine is None:
        env.pop("LD_LIBRARY_PATH", None)
    else:
        env["LD_LIBRARY_PATH"] = mine
    return env
