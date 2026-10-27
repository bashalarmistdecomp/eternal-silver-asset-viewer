"""Animated actor scenes — what a tab hands over for the client to PLAY.

A pose sheet (`sprite_pages.pose_sheet`) plus its block's anim table is all
an actor needs: the client ticks the table the way the engine does and
draws the named cell. So a scene ships each sheet once and lets any number
of actors share it, instead of the server composing every frame of every
anim as images (the old "Animated" view cycled every pose in table order,
which is not an animation the game ever plays).

    {"w", "h", "background": Image | None,
     "sheets": [{"image": Image, "cell_w", "cell_h", "anchor_x", "anchor_y",
                 "columns", "poses", "label",
                 "anims": [{"index", "hold", "steps": [[pose, ticks]],
                            "name", "fanName", "proof"}]}],
     "actors": [{"sheet", "x", "y", "mirror", "anim", "label"}],
     "depth": "y" | "order", "labels": bool, "tick_hz", "tick_note"}

Actor (x, y) is the ANCHOR — the point slice offsets hang off — in scene
pixels. `mirror` is actor +0x0C bit 13: the cell drawn mirrored about the
anchor column (engine column c -> 2X-1-c). `depth` "y" is the battle's
Y-sorted OT depth for draw flags 0x2000 (sprite_draw (0x8001A528): 0x200 + 0xFF -
(Y + 0x20)), so lower on screen draws in front; at equal Y the actor listed
first (the lower slot) draws in front, because AddPrim (0x8008E9D8) makes
each packet the head of its OT entry and BtlAnimationStep (0x800272A8) lists
the slots in order (docs/spec/code/subsystems/battle.md §"The actor
renderer"). A "y" scene lists its actors in slot order. "order" is list
order.

viewer_server/present.py turns the images into blobs; PNG export writes
`still()`. Nothing here reads game bytes.
"""

from __future__ import annotations

from PIL import Image, ImageOps

#: BtlFrameStep (0x80038D2C) runs BtlAnimationStep (0x800272A8) once per frame — VSync(0), no frame
#: skip — so one anim tick is one NTSC field.
TICK_HZ = 59.94
BATTLE_TICK_NOTE = ("one tick per battle frame: BtlFrameStep (0x80038D2C) runs "
                    "BtlAnimationStep (0x800272A8) every VSync (59.94 Hz)")


#: What the battle census names an anim for (battle_gfx.ENEMY_ANIMS,
#: PARTY_ANIMS), in a fan's words: Fan mode's name for it; the census's,
#: with the status bits the code tests, is Advanced mode's.
FAN_ANIM_WORDS = {
    "idle": "idle",
    "move": "moving",
    "attack": "attacking",
    "special, queued": "readying a special move",
    "special, effect 95/97": "special move",
    "victory": "victory",
    "evade": "dodging",
    "hit": "hit",
    "defend": "defending",
    "KO": "knocked out",
    "confused, no action": "confused, doing nothing",
    "magic queued": "readying magic",
    "rest: status & 0x01 (poison)": "poisoned",
    "rest: status & 0x04 (paralysis)": "paralysed",
    "rest: status & 0x08 (sleep)": "asleep",
    "rest: status & 0x10 (stone, setting in)": "turning to stone",
    "rest: status & 0x20 (stone, setting in)": "turning to stone",
    "rest: status & 0x30 (stone)": "turned to stone",
    "rest: status == 0x30 (stone)": "turned to stone",
    "rest: status & 0x40 (confusion)": "confused",
    "rest: status & 0x80 (silence)": "silenced",
}


def sheet_entry(sheet, animations, label: str,
                names: dict[int, tuple[str, str]] | None = None) -> dict:
    """A scene sheet from a `PoseSheet` and its block's `Animation`s; an
    anim the census names carries that name, Fan mode's words for it
    (FAN_ANIM_WORDS) and the functions that play it."""
    names = names or {}
    return {
        "image": sheet.image,
        "cell_w": sheet.cell_w, "cell_h": sheet.cell_h,
        "anchor_x": sheet.anchor_x, "anchor_y": sheet.anchor_y,
        "columns": sheet.columns, "poses": len(sheet.cells),
        "cells": sheet.cells,
        "label": label,
        "anims": [{"index": a.index, "hold": a.hold,
                   "steps": [list(s) for s in a.steps],
                   "name": names.get(a.index, (None, None))[0],
                   "fanName": FAN_ANIM_WORDS.get(names.get(a.index, (None, None))[0] or ""),
                   "proof": names.get(a.index, (None, None))[1]}
                  for a in animations],
    }


def first_pose(sheet: dict, anim: int) -> int | None:
    """The pose an actor shows on the anim's first tick (BtlAnimationStart, 0x80027240)."""
    anims = sheet["anims"]
    if 0 <= anim < len(anims) and anims[anim]["steps"]:
        return anims[anim]["steps"][0][0]
    return None


def cell(sheet: dict, pose: int) -> Image.Image | None:
    if not 0 <= pose < sheet["poses"]:
        return None
    cw, ch, cols = sheet["cell_w"], sheet["cell_h"], sheet["columns"]
    x, y = (pose % cols) * cw, (pose // cols) * ch
    return sheet["image"].crop((x, y, x + cw, y + ch))


def draw_order(scene: dict) -> list[dict]:
    """The actors back to front, the order to paint them in.

    "y": by Y, and at equal Y the later actor (the higher slot) first, so
    the lower slot ends on top, as sprite_draw's AddPrim links leave it."""
    actors = list(scene["actors"])
    if scene.get("depth") == "y":
        return [a for _i, a in sorted(enumerate(actors), key=lambda p: (p[1]["y"], -p[0]))]
    return actors


def still(scene: dict) -> Image.Image:
    """Every actor on its anim's first step, as the scene opens.

    What PNG export writes, since a PNG cannot hold the animation."""
    img = Image.new("RGBA", (scene["w"], scene["h"]), (0, 0, 0, 0))
    if scene.get("background") is not None:
        img.paste(scene["background"].convert("RGBA"), (0, 0))
    for a in draw_order(scene):
        sh = scene["sheets"][a["sheet"]]
        pose = first_pose(sh, a["anim"])
        im = cell(sh, pose) if pose is not None else None
        if im is None:
            continue
        if a["mirror"]:
            im = ImageOps.mirror(im)
            left = a["x"] - sh["cell_w"] + sh["anchor_x"]
        else:
            left = a["x"] - sh["anchor_x"]
        # Composed pixels are opaque or clear (CLUT entry 0), so a masked
        # paste composites exactly — and, unlike alpha_composite, clips.
        img.paste(im, (left, a["y"] - sh["anchor_y"]), im)
    return img


def grid(sheet: dict, anims: list[int], label_h: int = 12, gap: int = 6,
         max_cols: int = 8) -> tuple[int, int, list[dict]]:
    """Lay one actor per anim on a grid of the sheet's cells.

    -> (w, h, actors). Each actor's label names its anim; the client draws
    labels under the cell."""
    cw, ch = sheet["cell_w"], sheet["cell_h"]
    cols = max(1, min(max_cols, len(anims)))
    rows = max(1, (len(anims) + cols - 1) // cols)
    pitch_x, pitch_y = cw + gap, ch + gap + label_h
    actors = []
    for i, a in enumerate(anims):
        r, c = divmod(i, cols)
        name = sheet["anims"][a]["name"]
        actors.append({"sheet": 0, "anim": a, "mirror": False,
                       "x": gap + c * pitch_x + sheet["anchor_x"],
                       "y": gap + r * pitch_y + sheet["anchor_y"],
                       "label": f"{a}: {name}" if name else f"anim {a}"})
    return gap + cols * pitch_x, gap + rows * pitch_y, actors


def anim_lines(sheet: dict, tick_hz: float = TICK_HZ) -> list[str]:
    """The anim table as text: id, loop/hold, steps (pose:ticks), length."""
    out = []
    for a in sheet["anims"]:
        ticks = sum(t for _p, t in a["steps"])
        kind = "hold" if a["hold"] else "loop"
        steps = " ".join(f"{p}:{t}" for p, t in a["steps"]) or "(no steps)"
        name = f"  {a['name']}" if a["name"] else ""
        out.append(f"  {a['index']:2d} {kind} {len(a['steps']):2d} steps "
                   f"{ticks:4d} t = {ticks / tick_hz:5.2f}s{name}")
        out.append(f"       pose:ticks {steps}")
        if a["proof"]:
            out.append(f"       played by {a['proof']}")
    return out


def held_poses(sheet: dict, label: str) -> dict:
    """The sheet again with one entry a pose, each holding its pose: what a
    page shows to put every pose on screen beside the animations. They are
    the viewer's, not anims the game plays; the sheet's own stay in
    `sheet`."""
    return dict(sheet, label=label, anims=[
        {"index": k, "hold": True, "steps": [[k, 1]], "name": None, "proof": None}
        for k in range(sheet["poses"])])


#: SceneView draws a label in screen pixels under its cell, in a 10 px
#: monospaced face: about this wide a character, plus its padding.
LABEL_CHAR_W, LABEL_PAD = 6, 10
#: The shape `stack` aims for, width over height: a stage is wider than tall,
#: and a stack that fits it unshrunk keeps its labels apart.
STACK_ASPECT = 1.4


def stack(sections: list[tuple[dict, list[tuple[int, str]]]], label_h: int = 12,
          gap: int = 6, max_cols: int | None = None, min_cols: int = 8
          ) -> tuple[int, int, list[dict], list[dict]]:
    """Grids one under another: each section is a sheet and the (anim,
    label) of each actor on it, laid out as `grid` lays one out, columns
    far enough apart that neighbouring labels do not meet. With no
    `max_cols`, each section takes as many columns (at least `min_cols`) as
    make the whole about STACK_ASPECT times as wide as it is tall.
    -> (w, h, sheets, actors)."""
    def room(a: str, b: str) -> int:
        return -(-(len(a) + len(b)) * LABEL_CHAR_W // 2) + LABEL_PAD

    sections = [(sheet, items) for sheet, items in sections if items]
    pitches = [(max([sheet["cell_w"] + gap] + [room(a, b) for (_x, a), (_y, b)
                                               in zip(items, items[1:])]),
                sheet["cell_h"] + gap + label_h) for sheet, items in sections]
    width = (STACK_ASPECT * sum(px * py * len(items) for (px, py), (_s, items)
                                in zip(pitches, sections))) ** 0.5
    sheets, actors, w, y = [], [], 0, 0
    for (sheet, items), (pitch_x, pitch_y) in zip(sections, pitches):
        i = len(sheets)
        sheets.append(sheet)
        cols = max_cols or max(min_cols, int(width // pitch_x))
        cols = max(1, min(cols, len(items)))
        rows = (len(items) + cols - 1) // cols
        for k, (anim, label) in enumerate(items):
            r, c = divmod(k, cols)
            actors.append({"sheet": i, "anim": anim, "mirror": False,
                           "x": gap + c * pitch_x + sheet["anchor_x"],
                           "y": y + gap + r * pitch_y + sheet["anchor_y"],
                           "label": label})
        w = max(w, gap + cols * pitch_x)
        y += gap + rows * pitch_y
    return w, y, sheets, actors
