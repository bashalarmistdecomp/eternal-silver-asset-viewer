"""Plugin SLUS_006.28 — Lunar: Silver Star Story Complete.

Everything this program group's discs need beyond the generic psx/ core:
container formats (the LUNADATA.FIL archive, the resource sector table,
sprite pages, MAP files, the sound-bank convention) and, under
`records/`, the layouts transcribed out of the program's executable image.

The distinction that matters here: `formats/` is TITLE-scoped — it reads
files that ship on the disc, and any disc of this game will do —
while `records/` is PROGRAM-scoped and says so with a `PROGRAM`
declaration, because an address is meaningless against another EXE.
"""

#: The serial that keys this plugin, spelled exactly as the library's
#: folders spell it (<library>/<serial>/): the program serial shared by
#: every disc of the title. The package
#: directory carries the MANGLED form (see decoders.plugins.mangle
#: — '.' is not legal in a module name); this declaration is the real
#: spelling, and the plugins' tests cross-check all three: declaration,
#: directory name, and gamedb.
SERIAL: str = "SLUS_006.28"

#: Backward-compatible alias for the pre-plugins spelling
#: (lunarlib.sssc.TITLE_KEY). Same value, same meaning.
TITLE_KEY: str = SERIAL
