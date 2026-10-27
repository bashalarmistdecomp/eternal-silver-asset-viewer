"""What the viewer knows about the disc it currently has open.

The viewer began as a Lunar-1-disc-1 tool: every tab reached straight for
`LUNADATA.FIL` and for `decoders.plugins.SLUS_006_28`, and every path it
wrote resolved through one DEFAULT serial. That is fine while one disc
exists and silently wrong the moment a second one does — a Lunar 2 export
would land in Lunar 1's export folder, and a tab opened on one disc would
keep showing the previous disc's contents.

`DiscContext` is the one object that answers, for the disc on screen:

    who is it        identity, resolved through gamedb (InstalledGame)
    where is it      the dump directory, the EXE, the disc image
    whose bytes      the PROGRAM every library folder is keyed by
    what can read it the plugin serving that program, if one exists

Tabs receive it instead of a bare `data_dir`, so a tab cannot accidentally
read one disc and write another's root.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from decoders import config
from decoders.plugins import plugin_for
from decoders.psx.gamedb.database import InstalledGame, read_meta
from decoders.psx.gamedb.known_games import related_to


@dataclass(frozen=True)
class DiscContext:
    """One opened disc dump: its identity, its paths, its decoders."""

    game: InstalledGame

    # -- identity ---------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        """<library>/<program>/raw/<disc> — where this dump's files are."""
        return self.game.path

    @property
    def disc_serial(self) -> str:
        return self.game.disc_id

    @property
    def program(self) -> str:
        """The serial of the PROGRAM this disc boots.

        Every library folder keys by this, never by the disc: both SSSC
        discs boot one byte-identical EXE, so both write to SLUS_006.28/.
        """
        return self.game.program

    @property
    def label(self) -> str:
        return self.game.label

    @property
    def related(self) -> tuple[tuple[str, str], ...]:
        """(relationship, other serial) — e.g. a making-of's ('bonus-for', …)."""
        return related_to(self.program)

    # -- files on the dump -------------------------------------------------

    @cached_property
    def files(self) -> tuple[str, ...]:
        """Extracted filenames, excluding the viewer's own bookkeeping."""
        if not self.data_dir.is_dir():
            return ()
        return tuple(sorted(
            p.name for p in self.data_dir.iterdir()
            if p.is_file() and p.name != "meta.json" and not p.name.startswith(".")
        ))

    def has(self, *names: str) -> bool:
        """True when EVERY named file is present in the dump."""
        present = set(self.files)
        return all(n in present for n in names)

    def path(self, name: str) -> Path:
        return self.data_dir / name

    @property
    def exe_path(self) -> Path:
        """The boot executable inside the dump — named for the disc serial."""
        return self.data_dir / self.disc_serial

    @property
    def source(self) -> Path | None:
        """The .cue/.bin this dump came from, re-resolved if the repo moved.

        Needed for anything that is not a file: CD-DA tracks live in the
        image's own track layout, not in the extracted filesystem.
        """
        return self.game.source

    @cached_property
    def image_name(self) -> str:
        """The disc image's file name without its suffix, "Lunar - Silver
        Star Story Complete (USA) (Disc 1)": the image found, else the one
        recorded at extraction, else the disc's label."""
        if self.source is not None:
            return self.source.stem
        recorded = read_meta(self.data_dir).get("source")
        return Path(recorded).stem if isinstance(recorded, str) and recorded else self.label

    # -- decoders ----------------------------------------------------------

    @cached_property
    def plugin(self):
        """The decoders plugin serving this program, or None.

        None is not an error — it means this program has no per-program
        decoders yet and only the generic psx/ ones apply. Tabs declare
        which programs they serve; see tab_providers.applies_to.
        """
        return plugin_for(self.program)

    @property
    def has_plugin(self) -> bool:
        return self.plugin is not None

    # -- library roots, ALWAYS keyed by this disc's program -----------------

    def exports_dir(self) -> Path:
        return config.exports_dir(self.program)

    @classmethod
    def for_game(cls, game: InstalledGame) -> "DiscContext":
        return cls(game=game)
