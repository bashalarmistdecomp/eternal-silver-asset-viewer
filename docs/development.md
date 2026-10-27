# For developers

How the viewer is built, how to run it from source, the checks every change
passes, and how the code is laid out. Using the app is in the
[README](../README.md) and [the user guide](guide.md).

## How it fits together

- **The desktop shell** (`app/src-tauri/`, Rust, [Tauri](https://tauri.app))
  opens the window, starts the backend and hands the page its address and
  a token.
- **The page** (`app/src/`, React and TypeScript) is everything in the
  window.
- **The backend** (`backend/`, Python) reads the discs: it extracts them
  into the library, decodes their formats, and answers the page over HTTP
  on 127.0.0.1, every request carrying the token. Nothing listens beyond
  this computer.

A release carries the backend frozen with PyInstaller, so it runs without
Python.

## Running it from source

You need Python 3 (tested with 3.14), Node.js (tested with 24) and Rust with
[Tauri's prerequisites](https://tauri.app/start/prerequisites/) for your
system. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python3 -m pip install -r backend/requirements-dev.txt
cd app
npm install
npm run app          # builds and opens the desktop app
```

On Windows the venv's Python is `.venv\Scripts\python` (and `python`, not
`python3`, makes the venv): read it for `.venv/bin/python3` here and under
[Checks](#checks).

The app starts its backend (`backend/server.py`, under `.venv`) itself.

### Developing the page in a browser

```sh
cd app
npm run backend      # backend on 127.0.0.1:8765, token "dev"
npm run dev          # in another shell
# open http://localhost:1421/?backend=http://127.0.0.1:8765&token=dev
```

`npm run backend` uses the default library; pass `--library <folder>` to
`backend/server.py` for another. On Windows, start it with the venv's Python
instead: `..\.venv\Scripts\python ..\backend\server.py --port 8765 --token dev`.

## The library on disk

One folder holds everything the viewer writes:

```
<library>/discs/                  optional: disc images kept here
<library>/<program>/raw/<disc>/   an extracted disc
<library>/<program>/index/        what the viewer keeps of each disc's reading
<library>/<program>/exports/      what Export writes
```

Discs are filed by the program they boot, so both discs of *Silver Star
Story Complete* (one byte-identical program) share a folder. Where the
library is by default is in the [user guide](guide.md#the-library-folder);
`ASSET_VIEWER_LIBRARY` names another, as the folder button on the Library
does.

A game (gamedb's `GAMES`, `backend/decoders/psx/gamedb/`) is its own
program and every program related to it: its other regions' versions, its
demos and its bonus discs. Its slot on the Library lists every disc of all
of them, and opening it opens every extracted one at once. A disc is
identified by the sha256 of its data track, else by the serial its
`SYSTEM.CNF` names; a disc gamedb does not know is not extracted.

## Checks

```sh
cd backend
../.venv/bin/python3 -m pytest                    # the decoders and the viewer
../.venv/bin/python3 -m pyflakes .
../.venv/bin/python3 -m decoders.inventory --check
cd ../app
npm run build && npm run lint
(cd src-tauri && cargo clippy && cargo fmt --check)
cd ..
.venv/bin/python3 tools/versions.py               # the version moved with the work (Versions)
.venv/bin/python3 -m pytest tools
```

The tests build their own bytes (`backend/decoders/testing.py`); the few
that need a real disc read it from the library and are skipped when it is
not there. Those are marked `disc` (`-m "not disc"` leaves them out), and
every skip says why. Set `ASSET_VIEWER_LIBRARY` to run them against another
library. After a merge, on a machine whose library holds the discs, run
them with `ASSET_VIEWER_REQUIRE_DISCS=1 ../.venv/bin/python3 -m pytest`: a
disc test the library cannot serve then fails instead of skipping.

### The hooks

`git config core.hooksPath .githooks`, once per clone, points git at the
repository's hooks:

- **pre-commit** runs the checks of the parts a commit changes: for
  `backend/` its tests (not the disc tests), pyflakes and the inventory;
  for `tools/` theirs; for the page its type check and lint; for the shell
  rustfmt and Clippy. A commit of docs alone runs nothing.
- **pre-push** lets only `main` and the `v<version>` tags go to GitHub,
  never a force push or a deletion. It checks that the version moved with
  what `main` ships, that a tag names a commit on `main` with that version,
  and, on a machine that has them, runs the public-safety scans.

CI runs every check on every push and pull request, whatever the hooks did.

**Nothing of the games goes in the repository**: no disc image, no file of
a disc, no bytes copied out of one, no text of the games. A test makes the
bytes it reads; a comment or a doc says what a format is, not what a disc
holds. `NOTICE.md` says why.

## Versions

The app's version is `app/package.json`'s, and the Library shows it at its
bottom right. Tauri reads it from there; `app/package-lock.json`,
`app/src-tauri/Cargo.toml`, its `Cargo.lock` and `backend/server.py` (the
version `/api/status` answers) copy it.

It moves with the work: a change that lands in `main` and changes what the
app ships moves it one patch step, 0.2.0 to 0.2.1 and on. A minor step, as
0.2.0 was, is the owner's word. What ships is what the builds are made
from: the page (`app/index.html`, `app/src/`, `app/public/`, its Vite and
TypeScript settings), the Tauri shell (`app/src-tauri/`), the backend but
for its tests, the script that freezes it, `app/package.json`'s
dependencies and the packages of the lock file they reach. Documents, tests
and `tools/` move nothing; the pictures `tools/brand/` draws ship, and move
it.

`tools/versions.py` holds it. Against the version the work left `main`
with, it fails when a file the app ships changed and the version did not,
naming the files and what the version is to be; so does a copy that
disagrees, and a version that went back. `--move` writes the step it asks
for in every place, and `--set <version>` a version the owner gave.

## A release build

`npm run bundle` (in `app/`) makes the installers this machine makes: it
freezes the backend with PyInstaller (`scripts/build-sidecar.mjs`), so the
app runs without Python, writes the third-party notices
(`tools/notices.py`), and bundles both with the app. The releases are built
on Linux, Windows and macOS by GitHub Actions
(`.github/workflows/build.yml`); [Releases](release.md) says how one is
made.

## How the code is laid out

```
app/                    the desktop app: React page (src/), Tauri shell (src-tauri/)
backend/server.py       the backend's entry point: HTTP on 127.0.0.1
backend/viewer_server/  routes, sessions, the library, extraction jobs, export
backend/viewer_tabs/    one provider per tab: what each tab lists and shows
backend/decoders/       the decoders: psx/ for any PlayStation disc,
                        plugins/<program>/ for one game's own formats
tools/brand/            the logo and the icon, drawn a pixel at a time
tools/notices.py        a release's third-party notices, and the check of their licences
tools/smoke.py          a release's frozen backend, run once as the app runs it
tools/versions.py       the version check (Versions)
.github/workflows/      the builds for Linux, Windows and macOS (docs/release.md)
```

The words the code and the app use for each kind of thing, and how each is
numbered and linked, are in [Names](taxonomy.md).

## The decoders and the decompilation

`python3 -m decoders.inventory` (from `backend/`) lists every decoder: what
it reads, where its format is written up and how it is tested.

The game's own formats were proven by reading its program in
eternal-silver-sssc-decomp, the matching decompilation of *Lunar: Silver
Star Story Complete*. A `docs/spec/…` path in the code is a page of that
decompilation's specification, and the game's functions and data are
called what its symbol register calls them, with the address:
`BtlActionRowRun (0x80031ABC)`. A name that is still an address
(`func_80026AB0`) is one the register leaves unnamed.
