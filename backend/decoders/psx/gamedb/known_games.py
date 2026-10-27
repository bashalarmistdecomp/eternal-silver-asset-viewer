"""Static database of known PS1 game disc images."""

from dataclasses import dataclass


@dataclass
class GameInfo:
    disc_id: str
    title: str
    region: str
    disc_number: int = 1
    disc_label: str = ""
    #: What the PROGRAM on this disc is: "game" (the title itself), "bonus"
    #: (a bundled extra with its own EXE, e.g. a making-of), or "demo".
    role: str = "game"


# SHA-256 of data track .bin -> GameInfo. Every entry here is MEASURED:
# the image was hashed and its SYSTEM.CNF BOOT line read. Extracting a
# disc records the same two facts in its meta.json.
KNOWN_CHECKSUMS: dict[str, GameInfo] = {
    # BOOT=SLUS_006.28, volume LUNAR_THE_SILVER_STAR_STORY_1
    "d223a400ad8ff09c93e64c14c325ca4cfb92a338853794d04d0595c72daa13ff": GameInfo(
        "SLUS_006.28",
        "Lunar: Silver Star Story Complete",
        "USA", 1,
        "LUNAR_THE_SILVER_STAR_STORY_1",
    ),
    # BOOT=SLUS_008.99, volume LUNAR_THE_SILVER_STAR_STORY_2
    "b074d5b8a00258d1849c6f997fae437c9a22e4501f4c5f0d60768fa4deba7709": GameInfo(
        "SLUS_008.99",
        "Lunar: Silver Star Story Complete",
        "USA", 2,
        "LUNAR_THE_SILVER_STAR_STORY_2",
    ),
    # BOOT=SLUS_009.21, volume THE_MAKING_OF_LUNAR_TSSS: the MAKING-OF
    # bonus disc bundled with SSSC (video + hidden minigame). Its own
    # program (own EXE); 5 files, reusing the game's LUNAR_DA.PCM /
    # BLANK_DA.PCM names.
    "4f824aa5df69916c4499add3b62d29ccccbd5d9d954e8b28cb0d214207305b66": GameInfo(
        "SLUS_009.21",
        "Lunar: Silver Star Story Complete — The Making of (bonus disc)",
        "USA", 1,
        "THE_MAKING_OF_LUNAR_TSSS",
        role="bonus",
    ),
    # BOOT=SLUS_900.83, volume id empty (all Lunar 2
    # discs ship blank volume ids). Demo-range serial (SLUS-9xxxx). Same
    # DATA.IDX/DATA.PAK/DATA.UPD engine layout as retail Lunar 2.
    "1983cac471807be61ec0b3ad9d558bd04c441fd4cf08819a685e58bca0f7aabe": GameInfo(
        "SLUS_900.83",
        "Lunar 2: Eternal Blue Complete (Demo)",
        "USA", 1,
        "",
        role="demo",
    ),
    # BOOT=SLUS_010.71 / SLUS_012.39 / SLUS_012.40 —
    # the three retail Lunar 2 game discs. Engine layout differs completely
    # from SSSC: DATA.IDX/DATA.PAK/DATA.UPD archive + DISKTYPE.DAT +
    # MOVIE.EXE + per-scene S*.STR, no LUNADATA.FIL.
    "7721307705ead0589ad318896a05ec08b3a97dcb00e7b5981e6d20cb74bb459a": GameInfo(
        "SLUS_010.71",
        "Lunar 2: Eternal Blue Complete",
        "USA", 1,
        "",
    ),
    "bc7662bc001b01237be06001b6e29f2af9ec42113adeec86eb4556077386afd6": GameInfo(
        "SLUS_012.39",
        "Lunar 2: Eternal Blue Complete",
        "USA", 2,
        "",
    ),
    "412924e4073e26a4bb903221203a2acc50f7f24484983d77d862aa5c8f6bf37f": GameInfo(
        "SLUS_012.40",
        "Lunar 2: Eternal Blue Complete",
        "USA", 3,
        "",
    ),
    # BOOT=SLUS_012.57 — Lunar 2's making-of bonus
    # disc (LUNAR2_*.STR videos + TIM title screens).
    "a0608fa7797fdb755d6b9ec9273758fe00a09f2edb6ac1913712e47af29acbf1": GameInfo(
        "SLUS_012.57",
        "Lunar 2: Eternal Blue Complete — The Making of (bonus disc)",
        "USA", 1,
        "",
        role="bonus",
    ),
    # BOOT=SLUS_900.55, volume LUNAR_SILVER_STAR_STORY_DEMO.
    # The SSSC US demo: a 99-03-29 build of the retail program (retail is
    # 99-04-19), same container, own serial.
    "750ef70c365c21e8b357363989f2da224a35510c4c8ca7b28b136d2e6fa44cdb": GameInfo(
        "SLUS_900.55",
        "Lunar: Silver Star Story Complete (Demo)",
        "USA", 1,
        "LUNAR_SILVER_STAR_STORY_DEMO",
        role="demo",
    ),
    # BOOT=SLPS_013.97, volume id BLANK. The Japanese PS1 original, disc 1
    # — a 98-04-17 GCC 2.7.2 build of the same source.
    "7583bce4413001b94053f69c9dcd9571714b1dd13e9d412d2a2be577acf53afd": GameInfo(
        "SLPS_013.97",
        "Lunar: Silver Star Story",
        "Japan", 1,
        "",
    ),
    # BOOT=SLPS_013.98, volume id BLANK. Disc 2 of the Japanese original:
    # its EXE is byte-identical to disc 1's (cmp = 0), as are LUNADATA.FIL,
    # MENU.BIN, both .PCM files, _AUDIO.XA and _B000.STR; its other movies
    # are its own.
    "62011fbd18b487c30e64554360bf15e9e5b12a7ee00cddf4c190d3ae749b7499": GameInfo(
        "SLPS_013.98",
        "Lunar: Silver Star Story",
        "Japan", 2,
        "",
    ),
}

# Disc ID (from SYSTEM.CNF BOOT line) -> GameInfo
DISC_ID_LOOKUP: dict[str, GameInfo] = {
    "SLUS_006.28": GameInfo(
        "SLUS_006.28",
        "Lunar: Silver Star Story Complete",
        "USA", 1,
        "LUNAR_THE_SILVER_STAR_STORY_1",
    ),
    # Disc 2 of the US release is SLUS_008.99, read from the disc's own
    # SYSTEM.CNF (`BOOT=cdrom:\SLUS_008.99;1`, volume id
    # LUNAR_THE_SILVER_STAR_STORY_2). The disc names itself; a catalogue
    # does not outrank it.
    "SLUS_008.99": GameInfo(
        "SLUS_008.99",
        "Lunar: Silver Star Story Complete",
        "USA", 2,
        "LUNAR_THE_SILVER_STAR_STORY_2",
    ),
    # SYSTEM.CNF says BOOT=SLUS_009.21, volume THE_MAKING_OF_LUNAR_TSSS:
    # the MAKING-OF bonus disc (see KNOWN_CHECKSUMS).
    "SLUS_009.21": GameInfo(
        "SLUS_009.21",
        "Lunar: Silver Star Story Complete — The Making of (bonus disc)",
        "USA", 1,
        "THE_MAKING_OF_LUNAR_TSSS",
        role="bonus",
    ),
    # measured (see KNOWN_CHECKSUMS): the disc names itself SLPS_013.97,
    # the 1998 "Silver Star Story" (no "Complete").
    "SLPS_013.97": GameInfo(
        "SLPS_013.97",
        "Lunar: Silver Star Story",
        "Japan", 1,
        "",
    ),
    # measured (see KNOWN_CHECKSUMS): SYSTEM.CNF `BOOT = cdrom:\SLPS_013.98;1`
    "SLPS_013.98": GameInfo(
        "SLPS_013.98",
        "Lunar: Silver Star Story",
        "Japan", 2,
        "",
    ),
    # measured (see KNOWN_CHECKSUMS)
    "SLUS_900.55": GameInfo(
        "SLUS_900.55",
        "Lunar: Silver Star Story Complete (Demo)",
        "USA", 1,
        "LUNAR_SILVER_STAR_STORY_DEMO",
        role="demo",
    ),
    # measured (see KNOWN_CHECKSUMS)
    "SLUS_010.71": GameInfo(
        "SLUS_010.71",
        "Lunar 2: Eternal Blue Complete",
        "USA", 1,
        "",
    ),
    "SLUS_012.39": GameInfo(
        "SLUS_012.39",
        "Lunar 2: Eternal Blue Complete",
        "USA", 2,
        "",
    ),
    "SLUS_012.40": GameInfo(
        "SLUS_012.40",
        "Lunar 2: Eternal Blue Complete",
        "USA", 3,
        "",
    ),
    "SLUS_900.83": GameInfo(
        "SLUS_900.83",
        "Lunar 2: Eternal Blue Complete (Demo)",
        "USA", 1,
        "",
        role="demo",
    ),
    "SLUS_012.57": GameInfo(
        "SLUS_012.57",
        "Lunar 2: Eternal Blue Complete — The Making of (bonus disc)",
        "USA", 1,
        "",
        role="bonus",
    ),
}

#: PROGRAMS AND THE MEDIA THEY SHIP ON — the two-axis reading of the library.
#:
#: A game root `<library>/<serial>/` is keyed by the serial of the PROGRAM it
#: holds; `raw/<serial>/` inside it is keyed by the DISC the bytes shipped
#: on. Sony names a program after its first disc's boot file (the EXE
#: filename IS the serial), so for a multi-disc title the outer key equals
#: disc 1's serial — a coincidence of Sony's naming, not a "lead disc"
#: standing in for a set. `SLUS_006.28/raw/SLUS_008.99/` reads:
#: program SLUS_006.28, as shipped on disc SLUS_008.99.
#:
#: The membership test is checkable, not curated: discs map to one program
#: iff they boot that program (SSSC disc 2's EXE is byte-identical to
#: disc 1's — measured, cmp = 0). Bonus and demo discs boot their OWN
#: programs, so they get their own roots; their relationship to the game
#: they shipped beside is metadata (RELATED below), never layout.
#:
#: A wrong row here is not cosmetic: it files a disc under the wrong
#: program. (SLUS_009.21 — actually the SSSC making-of — sat in
#: this table as "disc 2" from a catalogue until the discs themselves were
#: read. The disc names itself; a catalogue does not outrank it.)
PROGRAM_DISCS: dict[str, tuple[str, ...]] = {
    # Lunar: SSSC (US): one program, two discs, both measured from
    # SYSTEM.CNF; disc 2 boots a byte-identical EXE under its own filename.
    "SLUS_006.28": ("SLUS_006.28", "SLUS_008.99"),
    # Lunar: SSS (Japan): one program, two discs, both measured; disc 2
    # boots a byte-identical EXE under its own filename, as in the US set.
    "SLPS_013.97": ("SLPS_013.97", "SLPS_013.98"),
    # Lunar 2: EBC (US): one program, three discs, all on hand and all
    # measured. (EXE identity across the three discs not yet cmp-verified —
    # do so at first extraction and record the result in the spec.)
    "SLUS_010.71": ("SLUS_010.71", "SLUS_012.39", "SLUS_012.40"),
}

#: Cross-program relationships — pure metadata for humans and the viewer
#: library. NEVER consulted by identity validation or path resolution:
#: a bonus disc's bytes do not become the game's bytes by association.
#: Rows: (program serial, relationship, target program serial).
RELATED: tuple[tuple[str, str, str], ...] = (
    ("SLUS_009.21", "bonus-for", "SLUS_006.28"),   # SSSC making-of
    ("SLUS_012.57", "bonus-for", "SLUS_010.71"),   # L2 making-of
    ("SLUS_900.83", "demo-of", "SLUS_010.71"),     # L2 demo
    ("SLUS_900.55", "demo-of", "SLUS_006.28"),     # SSSC demo (99-03-29 build)
    ("SLPS_013.97", "regional-version-of", "SLUS_006.28"),  # JP original, 1998, GCC 2.7.2
)


#: Relationships whose source is ANOTHER BUILD of its target: their items
#: are versions of the target's (a Japanese movie is the same movie as the
#: US one; the demo's sprites are retail's). A bonus disc's are its own.
VERSION_RELATIONS = frozenset({"regional-version-of", "demo-of"})


@dataclass(frozen=True)
class Game:
    """One game the viewer opens whole: every disc of every version of it.

    `program` is the one the others relate to (RELATED): its regional
    versions, its demos and its bonus discs belong to the game too.
    """
    key: str
    title: str
    program: str


#: The games, each a slot on the library page.
GAMES: tuple[Game, ...] = (
    Game("lunar-1", "Lunar: Silver Star Story", "SLUS_006.28"),
    Game("lunar-2", "Lunar 2: Eternal Blue", "SLUS_010.71"),
)


def game_programs(game: Game) -> tuple[str, ...]:
    """The game's programs: its own first, then its versions, demos and
    bonus discs (RELATED's order within each)."""
    related = [(rel, a) for a, rel, b in RELATED if b == game.program]
    order = {"regional-version-of": 0, "demo-of": 1, "bonus-for": 2}
    related.sort(key=lambda r: order.get(r[0], 3))
    return (game.program, *(a for _rel, a in related))


def game_of(program: str) -> Game | None:
    """The game a program belongs to, or None."""
    for game in GAMES:
        if program in game_programs(game):
            return game
    return None


def version_group(program: str) -> str:
    """The program whose items this program's items are versions of: the
    game's own for a regional version or a demo, itself otherwise."""
    for a, rel, b in RELATED:
        if a == program and rel in VERSION_RELATIONS:
            return b
    return program


#: Short region names for disc tags.
_REGION_TAG = {"USA": "US", "Japan": "JP", "Europe": "EU"}


def disc_tag(disc_serial: str) -> str:
    """A disc's short tag where its items are listed: "US 1", "JP 1",
    "Demo", "Making-of". A disc gamedb cannot place is its serial."""
    info = DISC_ID_LOOKUP.get(disc_serial)
    if info is None:
        return disc_serial
    if info.role == "bonus":
        return "Making-of" if "Making of" in info.title else "Bonus"
    if info.role == "demo":
        return "Demo"
    region = _REGION_TAG.get(info.region, info.region)
    return f"{region} {info.disc_number}"


def program_of(disc_serial: str) -> str:
    """The serial of the program a disc ships (identity for a disc that is
    not in PROGRAM_DISCS — a single-disc program ships itself)."""
    for program, discs in PROGRAM_DISCS.items():
        if disc_serial in discs:
            return program
    return disc_serial


def discs_of(program: str) -> tuple[str, ...]:
    """All disc serials shipping a program (a 1-tuple for single-disc)."""
    return PROGRAM_DISCS.get(program, (program,))


def disc_position(disc_serial: str) -> tuple[int, int]:
    """(this disc's number, discs in its program's set).

    The NUMBER comes from the catalogue row — measured from the disc's own
    SYSTEM.CNF/volume id — and the COUNT from PROGRAM_DISCS. They answer
    different questions and must not be derived from each other: a disc
    absent from a multi-disc row is 1 of 1, which is a fact, not a gap.
    """
    info = DISC_ID_LOOKUP.get(disc_serial)
    number = info.disc_number if info else 1
    count = len(discs_of(program_of(disc_serial)))
    return number, count


def disc_display(disc_serial: str) -> str:
    """One disc's human label: title, its place in the set, its serial.

        Lunar: Silver Star Story Complete - Disc 2 of 2 (SLUS_008.99)

    Bonus and demo discs boot their OWN program, so they are not numbered
    within the game's set — they carry their role (already in the title)
    and their serial alone. A disc gamedb cannot place says so out loud
    rather than borrowing a neighbour's name.
    """
    info = DISC_ID_LOOKUP.get(disc_serial)
    if info is None:
        return f"(unidentified disc) ({disc_serial})"
    number, count = disc_position(disc_serial)
    if info.role == "game" and count > 1:
        return f"{info.title} - Disc {number} of {count} ({disc_serial})"
    return f"{info.title} ({disc_serial})"


def related_to(serial: str) -> tuple[tuple[str, str], ...]:
    """(relationship, other-serial) pairs touching `serial`, both
    directions — e.g. the SSSC root reports ('bonus-for', …) inverse rows."""
    out: list[tuple[str, str]] = []
    for a, rel, b in RELATED:
        if a == serial:
            out.append((rel, b))
        elif b == serial:
            out.append((f"has-{rel.split('-')[0]}", a))
    return tuple(out)


def program_meta(serial: str) -> dict:
    """The self-description of one game root, written to
    `<library>/<serial>/program.json` so the folder reads without gamedb
    in hand. Generated from this module ONLY."""
    info = DISC_ID_LOOKUP.get(serial)
    return {
        "version": 1,
        "serial": serial,
        "title": info.title if info else "(unknown to gamedb)",
        "region": info.region if info else "",
        "role": info.role if info else "",
        "discs": list(discs_of(serial)),
        "related": [{"relation": rel, "serial": s}
                    for rel, s in related_to(serial)],
    }


def check_consistency() -> list[str]:
    """Cross-check the three tables. -> list of problems (empty = healthy).

    They can drift silently, and the drift is expensive: a disc missing
    from PROGRAM_DISCS is filed under no program, and the failure reads as
    a bug in the viewer rather than a gap in a table.
    """
    problems = []
    for sha, info in KNOWN_CHECKSUMS.items():
        if info.disc_id not in DISC_ID_LOOKUP:
            problems.append(
                f"KNOWN_CHECKSUMS[{sha[:12]}…] is {info.disc_id}, which "
                f"DISC_ID_LOOKUP does not list")
    for program, discs in PROGRAM_DISCS.items():
        if program not in discs:
            problems.append(
                f"PROGRAM_DISCS[{program}] does not include the program's "
                f"own boot disc")
        for d in discs:
            if d not in DISC_ID_LOOKUP:
                problems.append(
                    f"PROGRAM_DISCS[{program}] disc {d} is not in "
                    f"DISC_ID_LOOKUP")
        for other, others in PROGRAM_DISCS.items():
            if other != program and set(discs) & set(others):
                problems.append(
                    f"PROGRAM_DISCS[{program}] and PROGRAM_DISCS[{other}] "
                    f"share a disc — one disc cannot ship two programs' "
                    f"roots")
    for game in GAMES:
        if game.program not in DISC_ID_LOOKUP:
            problems.append(f"GAMES row {game.key} names {game.program}, "
                            f"which DISC_ID_LOOKUP does not list")
    for a, rel, b in RELATED:
        for s in (a, b):
            if s not in DISC_ID_LOOKUP:
                problems.append(
                    f"RELATED row ({a}, {rel}, {b}) names {s}, which "
                    f"DISC_ID_LOOKUP does not list")

    # A multi-disc title whose discs are catalogued but never mapped to
    # their program is the SSSC-disc-2 bug waiting to happen again.
    by_title: dict[tuple[str, str], list[str]] = {}
    for serial, info in DISC_ID_LOOKUP.items():
        if info.disc_number >= 1 and info.role == "game":
            by_title.setdefault((info.title, info.region), []).append(serial)
    mapped = {d for ds in PROGRAM_DISCS.values() for d in ds}
    for (title, region), serials in by_title.items():
        numbered = [s for s in serials
                    if DISC_ID_LOOKUP[s].disc_number > 1]
        if numbered and not set(serials) & mapped:
            problems.append(
                f"{title} ({region}) has disc {sorted(numbered)} but no "
                f"PROGRAM_DISCS row — artifacts from it would fail identity")
    return problems
