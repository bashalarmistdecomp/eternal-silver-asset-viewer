"""User-initiated output: <library>/<program>/exports/.

It is written only by a person pressing Export and read by nothing, which
is why it does not sit in raw/ (see decoders.config). Keyed by the OPEN
disc's program: an unkeyed export folder once wrote every disc's output
into the default game's root.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image


def stem_of(label: str) -> str:
    """An export file stem from an item label, sanitised so a label like
    `sequence 232/0` or `sprites/a.png` is a legal filename on every platform."""
    name = label.strip().split(" (")[0].replace(".BIN", "").replace(" [H]", "")
    name = "_".join(name.split())
    return re.sub(r"[^\w.\-]+", "_", name).strip("_") or "export"


def export_png(out_dir: Path, label: str, result, layers, layer: int | None,
               every: bool) -> list[Path]:
    """Write the shown layer (or every layer, or an animation's frames)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    name = stem_of(label)
    frames = [f for f in (result.frames or []) if f is not None]
    if frames:
        # An animated result has no layer stack, so write the frames plus a
        # strip sheet — PNG, not GIF: the frames carry alpha a GIF flattens.
        paths = []
        for i, frame in enumerate(frames):
            path = out_dir / f"{name}_f{i}.png"
            frame.save(path)
            paths.append(path)
        cw = max(f.size[0] for f in frames)
        ch = max(f.size[1] for f in frames)
        strip = Image.new("RGBA", (cw * len(frames), ch), (0, 0, 0, 0))
        for i, frame in enumerate(frames):
            strip.paste(frame, (i * cw, 0))
        path = out_dir / f"{name}_strip.png"
        strip.save(path)
        return paths + [path]

    if not layers:
        raise ValueError("this selection has no image to export")
    chosen = (list(enumerate(layers)) if every
              else [(layer or 0, layers[min(layer or 0, len(layers) - 1)])])
    paths = []
    for i, (layer_label, img) in chosen:
        suffix = re.sub(r"[^\w]+", "_", layer_label.lower()).strip("_")
        path = out_dir / (f"{name}.png" if len(layers) == 1
                          else f"{name}_{suffix or i}.png")
        img.save(path)
        paths.append(path)
    return paths


def export_audio(out_dir: Path, audio: dict, kind: str) -> Path:
    blob = audio.get(kind)
    if not blob:
        raise ValueError(f"this selection has no {kind.upper()} to export")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem_of(audio.get('name', 'clip'))}.{'wav' if kind == 'wav' else 'mid'}"
    path.write_bytes(blob)
    return path
