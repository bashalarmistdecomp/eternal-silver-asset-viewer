"""The third-party notices a release bundle carries, and the check of their
licences (docs/release.md).

A bundle (`npm run bundle`, which runs this through
app/scripts/build-sidecar.mjs) holds others' work beside this
repository's:

  the page      the npm packages app/package.json's dependencies reach in
                app/package-lock.json, read from app/node_modules
  the shell     the Rust crates the app's crate builds into its binary for
                the target (`cargo metadata --filter-platform`): its normal
                dependencies and theirs; a procedural macro's crates, and a
                build script's, run while it is built and are not shipped
  the backend   Python itself, the packages backend/requirements.txt names
                and those they need, as the interpreter running this has
                them (the freeze's venv), and PyInstaller's bootloader,
                which starts the frozen backend

Each is named with its version, its licence and where its source is, and
the licence and notice files it ships follow, each text once. One that
ships none gets its licence's text with its authors' names (the MIT
licence's is LICENSE's, this repository's own), choosing among licences
offered one there is a text for; a licence that names no one (WHOLE)
has its text from another package that ships it.

The check: every licence is one that lets the app stay MIT (ALLOWED, read
as SPDX: OR any, AND all), or, for one package, the exception it is
granted (GRANTED). A licence that is not, or none at all, fails, and so
does a package that ships no text whose licence has none here. Nothing is
written then.

  python3 tools/notices.py --target <triple> --out <file>
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

#: The licences a shipped package may be under: permissive, or (MPL-2.0)
#: copyleft for its own files only, which the app does not change.
ALLOWED = {
    "0BSD", "Apache-2.0", "Apache-2.0 WITH LLVM-exception", "BlueOak-1.0.0",
    "BSD-2-Clause", "BSD-3-Clause", "BSL-1.0", "CC0-1.0", "ISC", "MIT", "MIT-0",
    "MIT-CMU", "MPL-2.0", "PSF-2.0", "Python-2.0", "Unicode-3.0", "Unicode-DFS-2016",
    "Unlicense", "Zlib",
}
#: Licences granted to one package only, and why.
GRANTED = {
    ("pyinstaller-bootloader", "GPL-2.0-or-later WITH Bootloader-exception"):
        "the exception lets a frozen program carry the bootloader under the program's own licence",
}
#: Python's own licence; its text is the interpreter's LICENSE.txt.
PYTHON_LICENCE = "PSF-2.0"

BSD_3 = """\
Copyright (c) {holders}

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from this
   software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""

#: Licences whose text names no one, so one package's copy serves another
#: that ships none: each known by how its text begins.
WHOLE = {"Apache-2.0": "Apache License", "MPL-2.0": "Mozilla Public License Version 2.0"}

#: A licence or notice file, by its name.
_TEXT_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice|unlicense|copyright)([-._].*)?$")


@dataclass
class Package:
    """One piece of others' work the bundle ships."""
    name: str
    version: str
    licence: str            # an SPDX expression, "" where none is declared
    source: str             # where its source is
    texts: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SPDX expressions
# ---------------------------------------------------------------------------

def _tokens(expression: str) -> list[str]:
    # Cargo's older "MIT/Apache-2.0" is "MIT OR Apache-2.0"
    return re.findall(r"\(|\)|[^\s()]+", expression.replace("/", " OR "))


def _parse(tokens: list[str]):
    """An expression as nested ("OR"|"AND", [terms]) and licence ids (a
    WITH kept with its licence: "Apache-2.0 WITH LLVM-exception")."""
    def either(at):
        terms, at = both(at)
        out = [terms]
        while at < len(tokens) and tokens[at].upper() == "OR":
            term, at = both(at + 1)
            out.append(term)
        return (out[0] if len(out) == 1 else ("OR", out)), at

    def both(at):
        term, at = one(at)
        out = [term]
        while at < len(tokens) and tokens[at].upper() == "AND":
            term, at = one(at + 1)
            out.append(term)
        return (out[0] if len(out) == 1 else ("AND", out)), at

    def one(at):
        if at >= len(tokens):
            raise ValueError("an expression that ends too soon")
        if tokens[at] == "(":
            inner, at = either(at + 1)
            if at >= len(tokens) or tokens[at] != ")":
                raise ValueError("a bracket left open")
            return inner, at + 1
        ident = tokens[at]
        if at + 2 < len(tokens) and tokens[at + 1].upper() == "WITH":
            return f"{ident} WITH {tokens[at + 2]}", at + 3
        return ident, at + 1

    tree, at = either(0)
    if at != len(tokens):
        raise ValueError(f"{' '.join(tokens[at:])!r} left over")
    return tree


def allowed(expression: str, granted: set[str] = frozenset()) -> bool:
    """`expression` lets the app stay MIT: any of an OR, all of an AND."""
    def ok(tree):
        if isinstance(tree, str):
            return tree in ALLOWED or tree in granted
        kind, terms = tree
        return (any if kind == "OR" else all)(ok(t) for t in terms)
    try:
        return bool(expression.strip()) and ok(_parse(_tokens(expression)))
    except ValueError:
        return False


def elect(expression: str, have: set[str]) -> list[str] | None:
    """The licences to give a package under, choosing among those an OR
    offers one allowed whose text is here (`have`), MIT first; None when
    there is no such choice."""
    def pick(tree):
        if isinstance(tree, str):
            return [tree] if tree in ALLOWED and tree in have else None
        kind, terms = tree
        if kind == "AND":
            got = [pick(t) for t in terms]
            return None if None in got else [x for g in got for x in g]
        for t in sorted(terms, key=lambda t: t != "MIT"):
            got = pick(t)
            if got is not None:
                return got
        return None
    try:
        return pick(_parse(_tokens(expression)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# What ships, by where it comes from
# ---------------------------------------------------------------------------

def _texts(folder: Path, named: list[str] = ()) -> list[str]:
    """The licence and notice files in `folder` (and the ones `named`)."""
    paths = {folder / n for n in named if n}
    if folder.is_dir():
        paths |= {p for p in folder.iterdir() if p.is_file() and _TEXT_FILE.match(p.name)}
    return [p.read_text(encoding="utf-8", errors="replace").strip() + "\n"
            for p in sorted(paths) if p.is_file()]


def npm_packages(app: Path = APP) -> list[Package]:
    """The page's: the packages app/package.json's dependencies reach in its
    lock file, each found as npm finds it."""
    package = json.loads((app / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((app / "package-lock.json").read_text(encoding="utf-8")).get("packages", {})

    def needs(entry: dict) -> list[str]:
        return [n for f in ("dependencies", "optionalDependencies", "peerDependencies")
                for n in entry.get(f, {})]

    def find(at: str, name: str) -> str | None:
        while True:
            path = f"{at}/node_modules/{name}" if at else f"node_modules/{name}"
            if path in lock:
                return path
            if not at:
                return None
            at = at.rpartition("/node_modules/")[0]

    seen: dict[str, Package] = {}
    todo = [("", n) for n in needs(package)]
    while todo:
        path = find(*todo.pop())
        if path is None or path in seen:
            continue
        entry = lock[path]
        name = path.rpartition("node_modules/")[2]
        own = app / path / "package.json"
        meta = json.loads(own.read_text(encoding="utf-8")) if own.is_file() else {}
        licence = meta.get("license") or entry.get("license") or ""
        if isinstance(licence, dict):
            licence = licence.get("type", "")
        author = meta.get("author")
        seen[path] = Package(
            name, entry.get("version", ""), licence,
            f"https://www.npmjs.com/package/{name}/v/{entry.get('version', '')}",
            _texts(app / path),
            [author if isinstance(author, str) else author.get("name", "")] if author else [])
        todo += [(path, n) for n in needs(entry)]
    return sorted(seen.values(), key=lambda p: (p.name, p.version))


def cargo_metadata(manifest: Path, target: str) -> dict:
    run = subprocess.run(["cargo", "metadata", "--locked", "--format-version", "1",
                          "--filter-platform", target, "--manifest-path", str(manifest)],
                         capture_output=True, encoding="utf-8")
    if run.returncode:
        raise SystemExit(f"notices: cargo metadata: {run.stderr.strip()}")
    return json.loads(run.stdout)


def cargo_packages(meta: dict) -> list[Package]:
    """The shell's: every crate the root crate's normal dependencies reach,
    but through a procedural macro (its crates run in the compiler)."""
    packages = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    root = meta["resolve"]["root"]
    seen, todo = set(), [root]
    while todo:
        at = todo.pop()
        if at in seen:
            continue
        seen.add(at)
        for dep in nodes[at]["deps"]:
            if not any(k["kind"] is None for k in dep["dep_kinds"]):
                continue                    # a build script's or a test's
            p = packages[dep["pkg"]]
            if any("proc-macro" in t["kind"] for t in p["targets"]):
                continue
            todo.append(dep["pkg"])
    seen.discard(root)
    out = []
    for at in seen:
        p = packages[at]
        folder = Path(p["manifest_path"]).parent
        out.append(Package(
            p["name"], p["version"], p.get("license") or "",
            f"https://crates.io/crates/{p['name']}/{p['version']}",
            _texts(folder, [p.get("license_file") or ""]),
            [re.sub(r"\s*<[^>]*>", "", a) for a in p.get("authors", [])]))
    return sorted(out, key=lambda p: (p.name, p.version))


def _requirements(path: Path) -> list[str]:
    return [re.split(r"[<>=!~;\[ ]", line.strip(), maxsplit=1)[0]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))]


def _dist_texts(dist: metadata.Distribution) -> list[str]:
    """The licence and notice files a distribution's metadata folder holds."""
    return [Path(f.locate()).read_text(encoding="utf-8", errors="replace").strip() + "\n"
            for f in (dist.files or [])
            if _TEXT_FILE.match(f.name) and ".dist-info" in str(f)]


def python_packages(names: list[str]) -> list[Package]:
    """The backend's: Python, the distributions `names` and what they
    require, as this interpreter has them, and PyInstaller's bootloader."""
    out = []
    python = ".".join(map(str, sys.version_info[:3]))
    found = [Path(sys.base_prefix) / "LICENSE.txt",
             Path(sys.base_prefix) / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "LICENSE.txt"]
    out.append(Package("Python", python, PYTHON_LICENCE, "https://www.python.org/downloads/source/",
                       [p.read_text(encoding="utf-8", errors="replace") for p in found if p.is_file()][:1]))
    seen, todo = set(), [n.lower() for n in names]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        dist = metadata.distribution(name)
        meta = dist.metadata
        licence = meta.get("License-Expression") or ""
        texts = _dist_texts(dist)
        out.append(Package(meta["Name"], dist.version, licence,
                           f"https://pypi.org/project/{meta['Name']}/{dist.version}/", texts,
                           [meta.get("Author") or meta.get("Author-email") or ""]))
        for req in dist.requires or []:
            if ";" not in req or "extra" not in req.split(";", 1)[1]:
                todo.append(re.split(r"[<>=!~;\[ (]", req, maxsplit=1)[0].lower())
    try:
        pyi = metadata.distribution("pyinstaller")
    except metadata.PackageNotFoundError:
        return out
    texts = _dist_texts(pyi)
    out.append(Package("pyinstaller-bootloader", pyi.version,
                       "GPL-2.0-or-later WITH Bootloader-exception",
                       f"https://github.com/pyinstaller/pyinstaller/tree/v{pyi.version}/bootloader",
                       texts))
    return out


# ---------------------------------------------------------------------------
# The notices
# ---------------------------------------------------------------------------

def standard_texts(root: Path = ROOT) -> dict[str, str]:
    """The licences' texts given a package that ships none, `{holders}`
    where its authors go: the MIT licence's is this repository's LICENSE."""
    mit = (root / "LICENSE").read_text(encoding="utf-8")
    mit = re.sub(r"(?m)^Copyright.*$", "Copyright (c) {holders}", mit, count=1)
    return {"MIT": mit, "BSD-3-Clause": BSD_3}


def render(title: str, groups: list[tuple[str, list[Package]]],
           standards: dict[str, str]) -> tuple[str, list[str]]:
    """The notices file, and what fails the check."""
    standards = dict(standards)
    for p in (p for _, ps in groups for p in ps):
        for text in p.texts if p.licence in WHOLE else ():
            if text.lstrip().startswith(WHOLE[p.licence]):
                standards.setdefault(p.licence, text)
    problems = []
    texts: dict[str, int] = {}          # a text, its number
    users: dict[int, list[str]] = {}
    lines = [title, "",
             "The app includes others' work, each under its own licence: below, each",
             "piece with its version, its licence and where its source is, then the",
             "licence texts, each once, numbered. The app's own licence is LICENSE,",
             "and NOTICE.md says what it covers.", ""]
    for heading, packages in groups:
        lines += [f"== {heading} ==", ""]
        for p in packages:
            granted = {lic for (who, lic) in GRANTED if who == p.name}
            if not p.licence:
                problems.append(f"{p.name} {p.version}: no licence declared")
            elif not allowed(p.licence, granted):
                problems.append(f"{p.name} {p.version}: {p.licence} is not a licence the app may ship")
            own = p.texts
            if not own and p.licence:
                chosen = elect(p.licence, set(standards))
                if chosen is None:
                    problems.append(f"{p.name} {p.version}: ships no licence text, and {p.licence}"
                                    " has none here")
                else:
                    holders = ", ".join(a for a in p.authors if a) or f"the {p.name} authors"
                    own = [standards[c].replace("{holders}", holders) for c in chosen]
            numbers = []
            for text in own:
                n = texts.setdefault(text, len(texts) + 1)
                users.setdefault(n, []).append(f"{p.name} {p.version}")
                numbers.append(str(n))
            lines.append(f"{p.name} {p.version} — {p.licence or '(none)'} — {p.source}"
                         + (f" — text {', '.join(numbers)}" if numbers else ""))
        lines.append("")
    lines += ["== Licence texts ==", ""]
    for text, n in texts.items():
        who = users[n]
        lines += [f"--- {n}: {', '.join(who[:6])}" + (f" and {len(who) - 6} more" if len(who) > 6 else ""),
                  "", text.rstrip(), ""]
    return "\n".join(lines) + "\n", problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/notices.py", description=__doc__.split("\n")[0])
    ap.add_argument("--target", required=True, help="the Rust target triple the bundle is for")
    ap.add_argument("--out", required=True, type=Path, help="the notices file to write")
    args = ap.parse_args(argv)
    version = json.loads((APP / "package.json").read_text(encoding="utf-8"))["version"]
    groups = [
        ("The page: npm packages", npm_packages()),
        ("The shell: Rust crates", cargo_packages(
            cargo_metadata(APP / "src-tauri" / "Cargo.toml", args.target))),
        ("The backend: Python and its packages", python_packages(
            _requirements(ROOT / "backend" / "requirements.txt"))),
    ]
    text, problems = render(f"Eternal Silver Asset Viewer {version} for {args.target}:"
                            " third-party notices", groups, standard_texts())
    for line in problems:
        print(f"notices: {line}", file=sys.stderr)
    if problems:
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    shipped = sum(len(ps) for _, ps in groups)
    print(f"notices: {shipped} packages, {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
