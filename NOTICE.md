# Notices — Eternal Silver Asset Viewer

Eternal Silver Asset Viewer is a desktop app that opens your own PlayStation
discs of the Lunar games and shows what is on them. This repository — the
app, its backend, its decoders and its docs — is MIT-licensed (`LICENSE`),
© 2026 Bash Alarmist. This page says what that licence covers and credits
what the work stands on.

## The games

*Lunar: Silver Star Story Complete* is its owners': © 1992–1998 GAME ARTS;
© 1996–1998 Kadokawa Shoten / ESP / JAM; English translation © 1999 Working
Designs — as the original's title screen prints it. The other Lunar titles
the viewer's disc table names (the Japanese original, the bonus discs, the
demos, *Lunar 2: Eternal Blue Complete*) are likewise their owners'.

This repository holds none of the games' files: no disc image, no file of a
disc, no program image. The person using the viewer supplies their own
discs; the viewer extracts them into a library folder of that person's
choosing, outside the repository. The tests build their inputs by hand
(`backend/decoders/testing.py`); a test that needs a real disc reads it
from the library and skips when it is not there. What the disc table
(`backend/decoders/psx/gamedb/`) holds about each disc — its serial, title,
volume id and the sha256 of its data track — are facts measured from the
discs, not data of them.

## What the licence covers

The MIT licence is its author's grant, and covers what is its author's to
grant: the app, the backend, the decoders' code and every page of prose.

It does not cover the games' programs. Some decoders transcribe rules read
out of the program of *Lunar: Silver Star Story Complete* (SLUS_006.28) —
how it lays out its tables, decodes its strings, steps its animations — and
derive from that program. The rights in it stay its owners', and the
licence grants nothing in it.

## The decompilation

The formats the decoders read were proven by reading the game's program in
eternal-silver-sssc-decomp, the matching decompilation of *Lunar: Silver
Star Story Complete* by the same author. Each decoder's
registry entry (`backend/decoders/inventory.py`) names the page of that
decompilation's specification (`docs/spec/…`) where its format is written
up, and, for the game's own formats, the functions whose reading proved it.
Those functions are cited by the names the decompilation's symbol register
gives them, with their addresses (`MusicPlay (0x80054F2C)`); one the register
leaves unnamed, by its address alone (`func_80026AB0`).

## Other sources

- [psx-spx](https://problemkaputt.de/psx-spx.htm) (Martin Korth, "nocash"):
  the SPU's reverb network (`spu_reverb.py`) and sample interpolation
  (`vab.py`) follow its description of the hardware.
- Sony's *File Formats* reference from the PlayStation SDK: the STR sector
  layout (`str_stream.py`). Where the decoder departs from it, the departure
  was measured and is noted in the code.
- [psyz](https://github.com/Xeeynamo/psyz) (Xeeynamo): `vab.py`'s pitch table
  is checked entry by entry against psyz's decompiled libsnd table, when a
  psyz checkout is given to the test (`PSYZ_CHECKOUT`). None of its text is
  in this repository.

## Files of others in this repository

None. The logo and the app's icon — `app/src/brand/`, `app/public/favicon.png`,
`docs/img/logo.png` and `app/src-tauri/icons/` — are this repository's own,
drawn a pixel at a time by `tools/brand/`, not the games' art. The logo is
Eternal Silver's, by the same author, with the viewer's name under it.

## Libraries

Every dependency keeps its own licence.

| the app's page | licence |
|---|---|
| [React](https://react.dev) and React DOM (Meta) | MIT |
| [Lucide](https://lucide.dev) icons, `lucide-react` | ISC |
| [class-variance-authority](https://github.com/joe-bell/cva) (Joe Bell) | Apache-2.0 |
| [clsx](https://github.com/lukeed/clsx) (Luke Edwards) | MIT |
| [tailwind-merge](https://github.com/dcastil/tailwind-merge) (Dany Castillo) | MIT |
| [Tailwind CSS](https://tailwindcss.com), in the built stylesheet (Tailwind Labs) | MIT |
| [Tauri](https://tauri.app)'s `@tauri-apps/api` and `@tauri-apps/plugin-dialog` | Apache-2.0 OR MIT |

| the backend | licence |
|---|---|
| [Pillow](https://python-pillow.org) (Jeffrey A. Clark and contributors) | MIT-CMU |
| [NumPy](https://numpy.org) (NumPy Developers) | BSD-3-Clause, with bundled parts under 0BSD, MIT, Zlib and CC0-1.0 |

The desktop shell is built from Tauri and its plugins (Apache-2.0 OR MIT)
and, on Linux, 288 crates in all: permissive licences (MIT, Apache-2.0,
BSD-3-Clause, ISC, Zlib, Unicode-3.0, Unlicense, 0BSD, CC0-1.0) and five
under MPL-2.0 (cssparser, cssparser-macros, dtoa-short, option-ext,
selectors), used unmodified; their source is at
[crates.io](https://crates.io). The released app also carries a Python
interpreter (PSF License) frozen by [PyInstaller](https://pyinstaller.org),
whose bootloader is GPL-2.0 with an exception that allows this use. Each
release names every package it carries, with its version, licence and
source, and their licence texts, in `THIRD-PARTY-NOTICES.txt` beside the
app (`tools/notices.py`, which also refuses a release whose packages'
licences would not let the app stay MIT).
