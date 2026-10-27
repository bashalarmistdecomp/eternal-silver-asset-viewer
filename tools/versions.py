"""The app's version moved with what it ships (docs/development.md, "Versions").

The version is app/package.json's; Tauri reads it from there
(tauri.conf.json says "../package.json"), and app/package-lock.json
(twice), app/src-tauri/Cargo.toml, app/src-tauri/Cargo.lock (the app's
own crate) and backend/server.py (VERSION, what /api/status answers)
copy it. Work that changes what the app ships moves it one patch step,
0.2.0 to 0.2.1; a minor step, as 0.2.0 was, is the owner's word.

This holds it: against the version the work left main with (or another
ref's, --base), a file the app ships changed with the version the same
fails, naming the files and what the version is to be; so does a copy
that disagrees, and a version that went back.

  python3 tools/versions.py                  the check
  python3 tools/versions.py --move           the step it asks for, written in every place
  python3 tools/versions.py --set <version>  a version the owner gave, written in every place

Standard library only; it runs from any directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "app/package.json"
LOCK = "app/package-lock.json"
#: The app's own crate, in Cargo.lock among its dependencies.
CRATE = "eternal-silver-asset-viewer"

#: What the app's builds are made from, by path from the repository's top: a
#: folder's files (a trailing /) or one file. The page (Vite: index.html,
#: src/, public/, its config) inside the Tauri shell (src-tauri/), the
#: backend beside it, and the script that freezes the backend for the
#: standalone build. package.json and its lock file ship in part
#: (`shipped_changes`).
SHIPPED = ("app/index.html", "app/src/", "app/public/", "app/vite.config.ts",
           "app/tsconfig.json", "app/tsconfig.app.json", "app/src-tauri/",
           "app/scripts/", "backend/")
#: Under those, what no build carries: the backend's tests and what only they
#: read. A tests/ folder, a test_*.py, a conftest.py, a document or a
#: .gitignore anywhere is not shipped either (`ships`).
NOT_SHIPPED = ("backend/pytest.ini", "backend/requirements-dev.txt",
               "backend/decoders/testing.py")


@dataclass(frozen=True)
class Place:
    """Where the version is written: a file, and a pattern found in it
    exactly once whose one group is the version. `fixed` is what a place
    that names the version's source, not the version, says."""
    file: str
    what: str
    pattern: re.Pattern
    fixed: str | None = None


PLACES = (
    Place(PACKAGE, "its version", re.compile(r'^  "version": "([^"]*)"', re.M)),
    Place(LOCK, "its version", re.compile(r'^  "version": "([^"]*)"', re.M)),
    Place(LOCK, "the app's own entry",
          re.compile(r'^    "": \{\n(?:      .*\n)*?      "version": "([^"]*)"', re.M)),
    Place("app/src-tauri/Cargo.toml", "[package]",
          re.compile(r'^\[package\]\n(?:[^\[\n].*\n|\n)*?version = "([^"]*)"', re.M)),
    Place("app/src-tauri/Cargo.lock", f"the {CRATE} crate",
          re.compile(rf'^name = "{CRATE}"\nversion = "([^"]*)"', re.M)),
    Place("backend/server.py", "VERSION", re.compile(r'^VERSION = "([^"]*)"', re.M)),
    Place("app/src-tauri/tauri.conf.json", "its version",
          re.compile(r'^  "version": "([^"]*)"', re.M), fixed="../package.json"),
)

SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


class Refused(Exception):
    """What the check cannot go on from, said in words."""


def parse(text: str) -> tuple[int, int, int]:
    m = SEMVER.fullmatch(text)
    if not m:
        raise Refused(f"{text!r} is not a version: major.minor.patch, as 0.2.1")
    return int(m[1]), int(m[2]), int(m[3])


def show(version: tuple[int, int, int]) -> str:
    return ".".join(map(str, version))


def git(root: Path, *args: str) -> str:
    # a git hook's environment pins the repository it ran in; -C names this one
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    run = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                         encoding="utf-8", env=env)
    if run.returncode:
        raise Refused(f"git {' '.join(args)}: {run.stderr.strip()}")
    return run.stdout


def at_base(root: Path, base: str, path: str) -> str | None:
    """`path` as the work found it at `base`; None where it was not there."""
    try:
        return git(root, "show", f"{base}:{path}")
    except Refused:
        return None


def ships(path: str) -> bool:
    folders, _, name = path.rpartition("/")
    if (path in NOT_SHIPPED or "tests" in folders.split("/") or name == "conftest.py"
            or name.startswith("test_") or name.endswith(".md") or name == ".gitignore"):
        return False
    return any(path.startswith(s) if s.endswith("/") else path == s for s in SHIPPED)


def _needs(entry: dict) -> list[str]:
    return [name for field in ("dependencies", "optionalDependencies", "peerDependencies")
            for name in entry.get(field, {})]


def carried(package: dict, lock: dict) -> dict[str, str]:
    """The lock file's entries for the packages the app carries: its
    dependencies, theirs, and on, each found as npm finds it, in the
    node_modules/ beside the package needing it and then further up."""
    packages = lock.get("packages", {})

    def find(at: str, name: str) -> str | None:
        while True:
            path = f"{at}/node_modules/{name}" if at else f"node_modules/{name}"
            if path in packages:
                return path
            if not at:
                return None             # an optional one not installed
            at = at.rpartition("/node_modules/")[0]

    out: dict[str, str] = {}
    todo = [("", name) for name in _needs(package)]
    while todo:
        path = find(*todo.pop())
        if path is None or path in out:
            continue
        out[path] = json.dumps(packages[path], sort_keys=True)
        todo += [(path, name) for name in _needs(packages[path])]
    return out


def shipped_changes(root: Path, base: str) -> list[str]:
    """What the app ships that changed since `base`, the work not yet
    committed with it: its files, package.json where its dependencies
    changed, and the lock file where a package they reach did."""
    changed = set(git(root, "diff", "--no-renames", "--name-only", "-z", base).split("\0"))
    changed |= set(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    changed.discard("")
    out = sorted(p for p in changed if ships(p))

    def now(path: str) -> dict:
        return json.loads((root / path).read_text(encoding="utf-8"))

    def then(path: str) -> dict:
        text = at_base(root, base, path)
        return json.loads(text) if text is not None else {}

    def deps(package: dict) -> dict:
        return {f: package.get(f, {}) for f in ("dependencies", "optionalDependencies")}

    if PACKAGE in changed and deps(now(PACKAGE)) != deps(then(PACKAGE)):
        out.append(f"{PACKAGE} (its dependencies)")
    if LOCK in changed and carried(now(PACKAGE), now(LOCK)) != carried(then(PACKAGE), then(LOCK)):
        out.append(f"{LOCK} (the packages the app carries)")
    return out


def read(root: Path) -> list[tuple[Place, str]]:
    """Each place and what it says."""
    out = []
    for place in PLACES:
        found = place.pattern.findall((root / place.file).read_text(encoding="utf-8"))
        if len(found) != 1:
            raise Refused(f"{place.file}: {place.what} is not where it is written"
                          f" ({len(found)} found, not 1)")
        out.append((place, found[0]))
    return out


def write(root: Path, version: str) -> None:
    """`version` written in every place (and each fixed place's own words)."""
    for file in dict.fromkeys(p.file for p in PLACES):
        path = root / file
        text = path.read_text(encoding="utf-8")
        for place in (p for p in PLACES if p.file == file):
            m = place.pattern.search(text)
            if m is None:
                raise Refused(f"{file}: {place.what} is not where it is written")
            text = text[:m.start(1)] + (place.fixed or version) + text[m.end(1):]
        path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(prog="tools/versions.py",
                                 description="The app's version moved with what it ships.")
    ap.add_argument("--base", default="main",
                    help="the ref the work left (default main): its version and files are the ones before")
    act = ap.add_mutually_exclusive_group()
    act.add_argument("--move", action="store_true",
                     help="write the step the check asks for, in every place")
    act.add_argument("--set", metavar="VERSION",
                     help="write a version the owner gave, in every place")
    args = ap.parse_args(argv)
    try:
        base = git(root, "merge-base", "HEAD", args.base).strip()
        before_text = at_base(root, base, PACKAGE)
        if before_text is None:
            raise Refused(f"{args.base} has no {PACKAGE}")
        before = parse(json.loads(before_text)["version"])
        shipped = shipped_changes(root, base)
        if args.set or args.move:
            if args.set:
                target = parse(args.set)
                if target < before:
                    raise Refused(f"{args.set} is before {show(before)}, {args.base}'s")
            else:
                said = read(root)[0][1]
                now = parse(said) if SEMVER.fullmatch(said) else before
                target = now if now > before else (before[0], before[1], before[2] + 1) if shipped else before
            write(root, show(target))
            print(f"{show(target)}: written in every place")
        problems = check(read(root), before, shipped, args.base)
    except Refused as ex:
        print(f"versions: {ex}", file=sys.stderr)
        return 2
    for line in problems:
        print(line)
    return 1 if problems else 0


def check(said: list[tuple[Place, str]], before: tuple[int, int, int],
          shipped: list[str], base: str) -> list[str]:
    """What is wrong, in words; nothing, and a line that says how it stands,
    when all is well."""
    source = said[0][1]
    problems = []
    for place, value in said[1:]:
        want = place.fixed or source
        if value != want:
            problems.append(f"{place.file}: {place.what} says {value!r}, not {want!r}")
    try:
        now = parse(source)
    except Refused as ex:
        return [f"{PACKAGE}: {ex}"] + problems
    remedy = "`python3 tools/versions.py --move` writes it"
    if now < before:
        problems.append(f"the version went back: {show(now)}, and {base} has {show(before)}")
    elif shipped and now == before:
        listed = ", ".join(shipped[:8]) + (f" and {len(shipped) - 8} more" if len(shipped) > 8 else "")
        problems.append(f"what the app ships changed since {base} ({listed}), and its version"
                        f" did not: it is to be {show((before[0], before[1], before[2] + 1))};"
                        f" {remedy}")
    if problems:
        return problems
    print(f"version {show(now)}: " + (f"{base} has {show(before)}" if now != before
                                      else f"nothing the app ships changed since {base}"))
    return []


if __name__ == "__main__":
    sys.exit(main())
