"""SelectResult -> the JSON the desktop app renders.

The providers were first written for a view that showed one thing per
selection: an image, OR a text pane, OR a summary. The app can show all of a
result at once, so this hands over every part that is present and lets the
UI lay them out — the "proven by" lines next to a decoded PNG, say.

Item lists get the same treatment. A provider's labels are column-padded
for a monospace listbox ("sample 232/3   1.23s   4.5K"); a row here is a
title, a muted subtitle and an optional badge, derived from the label and,
where the provider's own item data says more, from that.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

from PIL import Image

from decoders.psx.formats.renderer import composite_layers

from viewer_tabs.audio import wav_duration
from viewer_tabs.tab_providers import SelectResult, size_text
from viewer_tabs.waveform import wav_envelope

#: Source kinds that are the disc's own bytes, or read straight from them.
#: Anything else on a Data tables row would be badged as a warning.
SHIPPABLE_KINDS = {"lunadata", "disc-file", "exe-image", "transcribed"}

WAVEFORM_COLUMNS = 1200


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def tab_meta(index: int, provider) -> dict:
    cls = type(provider)
    doc = cls.__dict__.get("__doc__")
    views = list(getattr(provider, "get_views", lambda: [])())
    return {
        "index": index,
        "key": getattr(cls, "key", cls.__name__),
        "name": provider.name,
        "views": views,
        "view": getattr(provider, "view", views[0] if views else None),
        "technicalView": getattr(cls, "technical_view", None),
        "viewsChangeItems": bool(getattr(provider, "views_change_items", False)),
        "supportsZoom": bool(provider.supports_zoom),
        "supportsGrid": bool(provider.supports_grid),
        "supportsLayers": bool(provider.supports_layers),
        "about": inspect.cleandoc(doc) if doc else "",
        # what Fan mode says of the tab, in a fan's words (the provider's
        # `fan_about`); the docstring is how it is done
        "fanAbout": inspect.cleandoc(getattr(cls, "fan_about", "") or ""),
    }


# ---------------------------------------------------------------------------
# Item rows
# ---------------------------------------------------------------------------

_PAREN = re.compile(r"^\((.*)\)$")
_TRAILING_PAREN = re.compile(r"^(.*\S)\s+\(([^()]*)\)$")


def _generic(label: str) -> dict:
    stripped = label.lstrip(" ")
    indent = min(3, (len(label) - len(stripped)) // 2)
    parts = [p for p in re.split(r"\s{2,}", stripped.strip()) if p]
    title = parts[0] if parts else label
    rest = [(_PAREN.match(p).group(1) if _PAREN.match(p) else p)
            for p in parts[1:]]
    m = _TRAILING_PAREN.match(title)
    if m:
        title, rest = m.group(1), [m.group(2)] + rest
    return {"title": title, "sub": " · ".join(rest), "indent": indent}


#: The Sound banks' two groups: a bank, or its score, plays songs or sound
#: effects (SoundItem.plays).
SOUND_GROUPS = {
    "song": ("Songs", "the music banks: a bank's first score is its songs' "
                      "(MusicPlay (0x80054F2C))"),
    "sound-effect": ("Sound effects", "the banks of bank slots 0 and 1: the common sounds, "
                                      "each place's own, the battle's (SoundPlay "
                                      "(0x800555F0))"),
}
#: A row's badge: what it plays.
SOUND_BADGES = {("seq", "song"): ("song", "info"), ("seq", "sound-effect"): ("sound effect", "ok"),
                ("bank", "song"): ("songs", "info"), ("bank", "sound-effect"): ("sound effects", "ok")}


def _sound_row(label: str, data) -> dict | None:
    """A Sound banks row, by its reference (`sample 232/3`, `sequence
    232/0`, `sound bank 232`); a score by what the game plays it as first
    ("song 12 · ‹title›", "sound effect 9"), under Songs or Sound effects
    with a badge saying which."""
    kind = data[0]
    if kind == "vag":
        bank, idx = data[1], data[2]
        vag = next(v for v in bank.vab.vags if v.index == idx)
        secs = vag.frames / bank.vab.vag_rate(idx)
        size = (f"{vag.size / 1024:.1f} KB" if vag.size >= 1024
                else f"{vag.size} B")
        return {"title": f"sample {bank.resource}/{idx}",
                "sub": f"{secs:.2f}s · {size}", "mono": True}
    words = getattr(data, "bgm", None)      # SoundItem: what it plays, in words
    plays = getattr(data, "plays", None)
    row = None
    if kind == "seq":
        bank, i = data[1], data[2]
        seq = bank.seqs[i]
        stats = (f"{seq.seconds:.1f}s · {seq.notes:,} notes · "
                 f"{len(seq.channels)} ch")
        if words:
            row = {"title": words, "sub": f"sequence {bank.resource}/{i} · {stats}"}
        else:
            none = (" · no sound effect number plays it" if plays == "sound-effect" else "")
            row = {"title": f"sequence {bank.resource}/{i}", "sub": stats + none, "mono": True}
    elif kind == "bank":
        bank = data[1]
        sub = (f"{len(bank.vab.vags)} samples · {len(bank.seqs)} "
               f"sequences · sector {bank.sector}")
        row = {"title": f"sound bank {bank.resource}" + (f" · {words}" if words else ""),
               "sub": sub}
    if row is None:
        return None
    if plays in SOUND_GROUPS:
        row["group"], row["groupNote"] = SOUND_GROUPS[plays]
        row["badge"], row["tone"] = SOUND_BADGES[kind, plays]
    return row


def _sound_effect_row(label: str, data) -> dict | None:
    """A sound effect: its number, then where it plays, under its kind
    (heard everywhere, in battle, each place its own)."""
    row = _generic(label)
    row["group"], row["groupNote"] = data.group, data.note
    return row


def _music_row(label: str, item) -> dict | None:
    """A song: its title, or its number where the game gives it none; then
    what MusicProvider says of it, two spaces apart."""
    title, *rest = label.split("  ")
    return {"title": title, "sub": " · ".join(p for p in rest if p)}


def _disc_row(label: str, data) -> dict | None:
    """A disc: its image's whole name, on two lines; the end of it ("(Disc
    1)", "(Japan)") is what tells the discs apart."""
    return {"title": label, "sub": "", "wrap": True}


def _disc_files_row(label: str, data) -> dict | None:
    """A file: its name; what it is (on a disc the spec covers) and size;
    its probed type as the badge."""
    name, path, role = data
    parts = re.split(r"\s{2,}", label.strip())
    kind = parts[-1] if len(parts) > 1 else ""
    size = size_text(path.stat().st_size)
    return {"title": name, "sub": f"{role.what} · {size}" if role else f"{kind} · {size}",
            "badge": kind, "tone": "muted", "mono": True}


def _all_files_row(label: str, row) -> dict | None:
    """A resource: its number and role; sectors, size, reader, commands; the
    tab that shows it as the badge."""
    res = row.resource
    sub = [f"{res.size_sectors} sectors", size_text(res.size)]
    if row.region is not None:
        sub.append(row.region.reader.split(" (")[0])
    if row.commands:
        sub.append(f"commands {row.commands}")
    if row.toc_name:
        sub.append(row.toc_name)
    out = {"title": f"{res.index}  {row.role}", "sub": " · ".join(sub)}
    if row.tabs:
        from viewer_tabs.tab_providers import PROVIDER_CLASSES
        names = {cls.key: cls.name for cls in PROVIDER_CLASSES}
        out.update(badge=names.get(row.tabs[0], row.tabs[0]), tone="info")
    else:
        out.update(badge="no tab", tone="muted")
    return out


def _sprite_pages_row(label: str, data) -> dict | None:
    """A look: who wears it, then where, under its heading (Party, Story
    characters …); the rest the generic row, badged."""
    if data[0] == "look":
        from viewer_tabs.looks import GROUP_NOTES
        title, _gap, sub = label.partition("  ")
        return {"title": title, "sub": sub.strip(), "indent": 0,
                "group": data[3], "groupNote": GROUP_NOTES.get(data[3], "")}
    row = _generic(label)
    if data[0] in ("party", "set"):
        row.update(badge="party" if data[0] == "party" else "object set", tone="info")
    elif data[0] == "data" and row["sub"].startswith("nothing found"):
        row.update(badge="not drawn", tone="muted")
    elif data[0] == "bparty":
        row.update(badge="party", tone="info")
    elif data[0] == "bset" and data[2] == 3:
        row.update(badge="fallback", tone="muted")
    return row


def _battle_row(label: str, path) -> dict | None:
    m = re.match(r"(\S+)\s+(?:(\d+) rec\s+)?\[(.+)\]$", label)
    if not m:
        return None
    stem, count, kind = m.groups()
    return {"title": stem, "sub": f"{count} records" if count else "document",
            "badge": kind, "tone": "ok" if kind in SHIPPABLE_KINDS else "warn",
            "mono": True}


def _battle_gfx_row(label: str, data) -> dict | None:
    parts = [p for p in re.split(r"\s{2,}", label.strip()) if p]
    row = {"title": parts[0], "sub": " · ".join(parts[1:]), "mono": True}
    if data[0] == "enc" and data[2]:             # the provider's boss-class flag
        row.update(badge="boss", tone="warn")
    elif data[0] == "enc" and parts[1:2] and parts[1].startswith("empty"):
        row.update(badge="empty", tone="muted")
    return row


def _world_map_row(label: str, m) -> dict | None:
    """A map: the generic row, under its type's heading (the area
    record's party kind)."""
    from viewer_tabs.field_view import MAP_TYPE_NOTES, MAP_TYPES
    kind = m.area.party_kind
    row = _generic(label)
    row["group"] = MAP_TYPES.get(kind, f"Party kind {kind}")
    row["groupNote"] = MAP_TYPE_NOTES.get(kind, f"party kind {kind}")
    return row


def _portrait_row(label: str, data) -> dict | None:
    """A portrait under whose it is (PortraitsProvider: the item carries its
    heading and the heading's note); a portrait list, the generic row."""
    row = _generic(label)
    if data[0] in ("face", "atlas") and len(data) >= 3:
        row["group"], row["groupNote"] = data[-2], data[-1]
    return row


def _voice_row(label: str, data) -> dict | None:
    """A voice: what it says and its number, under its speaker (or why it
    has none: VoicesProvider)."""
    row = _generic(label)
    row["group"], row["groupNote"] = data[2], data[3]
    return row


def _listed_row(label: str, data) -> dict | None:
    """A thing of Items, Magic, Monsters or Story flags
    (viewer_tabs.adventure.Listed): the generic row, under its group where
    its list is grouped."""
    row = _generic(label)
    if data.group:
        row["group"], row["groupNote"] = data.group, data.note
    return row


def _screen_row(label: str, data) -> dict | None:
    """A picture under its heading: a screen's, or its resource's in All
    images (ScreensProvider)."""
    row = _generic(label)
    row["group"], row["groupNote"] = data.group, data.note
    return row


#: tab key -> how its rows are laid out
_ROWS = {
    "maps": _world_map_row,
    "music": _music_row,
    "sound-banks": _sound_row,
    "disc": _disc_row,
    "disc-files": _disc_files_row,
    "resources": _all_files_row,
    "sprites": _sprite_pages_row,
    "data-tables": _battle_row,
    "battles": _battle_gfx_row,
    "portraits": _portrait_row,
    "voices": _voice_row,
    "sound-effects": _sound_effect_row,
    "items": _listed_row,
    "magic": _listed_row,
    "monsters": _listed_row,
    "story-flags": _listed_row,
    "screens": _screen_row,
}


def item_rows(provider, items: list[tuple[str, Any]]) -> list[dict]:
    fn = _ROWS.get(getattr(provider, "key", ""))
    out = []
    for label, data in items:
        row = None
        if fn is not None and data is not None:
            try:
                row = fn(label, data)
            except Exception:
                row = None              # fall back to the label as written
        row = row or _generic(label)
        row["label"] = label            # the filter matches the full label
        row["empty"] = data is None
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Selections
# ---------------------------------------------------------------------------

def _composite(images: list[Image.Image]) -> Image.Image:
    """composite_layers, onto opaque black — even for a single image.

    Every "composite" is shown this way, and a lone image is a
    one-layer composite. It matters for the art, not just the backdrop:
    palette entry 0x0000 decodes as transparent (the GPU never draws it),
    and the face portraits draw their black line art with exactly that
    entry. Passed through with its alpha, a portrait's outlines showed
    whatever the UI put behind them — white on a light backdrop.

    Falls back to the first image when the layers cannot stack (mixed
    sizes), rather than failing the selection.
    """
    try:
        return composite_layers([im.convert("RGBA") for im in images])
    except ValueError:
        return images[0]


def resolve_layers(result: SelectResult, provider) -> list[tuple[str, Image.Image]]:
    """[(label, image)] — what the layer picker offers, in its order.

    A tab with layer options offers
    them (composite, a numbered layer); a tab without shows the
    composite of whatever it returned. An option the selection cannot honour
    (layer 2 of a two-layer map) is left out rather than shown as a copy of
    the composite.
    """
    images = [im for im in result.images if im is not None]
    if not images:
        return []
    opts = provider.get_layer_options() if provider.supports_layers else []
    if not opts:
        return [("Image", _composite(images))]
    labels = list(getattr(provider, "get_layer_labels", lambda: [])())
    out = []
    for opt in opts:
        if opt == "composite":
            out.append(("Composite", _composite(images)))
        else:
            try:
                i = int(opt)
            except ValueError:
                continue
            if 0 <= i < len(images):
                out.append((labels[i] if i < len(labels) else f"Layer {i}",
                            images[i]))
    return out or [("Image", _composite(images))]


def _arrangement(arr) -> dict | None:
    if arr is None or not getattr(arr, "resolution", 0):
        return None
    lanes: dict[int, list] = {ch: [] for ch in arr.lanes}
    for ch, tick, dur, note, vel in arr.notes:
        lanes.setdefault(ch, []).append([tick, dur, note, vel])
    return {
        "resolution": arr.resolution,
        "ticks": arr.ticks,
        "seconds": arr.total_seconds,
        "beatsPerBar": 4,
        "tempo": [[s, t] for s, t in arr.tempo_ticks],
        "lanes": [{"channel": ch, "label": arr.lane_labels.get(ch, ""),
                   "notes": notes} for ch, notes in lanes.items()],
    }


def _scene(scene: dict, store) -> dict:
    """viewer_tabs.scene's dict -> JSON: images become blobs, keys camelCase."""
    bg = scene.get("background")
    return {
        "w": scene["w"], "h": scene["h"],
        "background": store.put_image(bg) if bg is not None else None,
        "sheets": [{"blob": store.put_image(sh["image"]),
                    "w": sh["image"].width, "h": sh["image"].height,
                    "cellW": sh["cell_w"], "cellH": sh["cell_h"],
                    "anchorX": sh["anchor_x"], "anchorY": sh["anchor_y"],
                    "columns": sh["columns"], "poses": sh["poses"],
                    "label": sh["label"], "anims": sh["anims"],
                    **({"pieces": sh["pieces"], "drawn": sh["drawn"]} if "pieces" in sh else {})}
                   for sh in scene["sheets"]],
        "actors": scene["actors"],
        "depth": scene.get("depth", "order"),
        "labels": bool(scene.get("labels")),
        "tickHz": scene["tick_hz"],
        "tickNote": scene.get("tick_note", ""),
        **({"field": _field(scene["field"], store)} if scene.get("field") else {}),
    }


def _reach(r: dict | None, store) -> dict | None:
    """The In game view's mask becomes a blob; its numbers stay."""
    if r is None:
        return None
    return {"mask": store.put_image(r["mask"]), "scale": r["scale"], "bbox": r["bbox"],
            "areas": r.get("areas", [])}


def _field(f: dict, store) -> dict:
    """A field scene's extras (viewer_tabs.field_view.played): the ground's
    bytes become a blob, the tileset's pages stay layer numbers (export
    writes them)."""
    g = f["ground"]
    return {
        "ticks": f["ticks"],
        "ground": {
            "blob": store.put_bytes(g["blob"], "application/octet-stream"),
            "parts": g["parts"], "pages": g["pages"], "columns": g["columns"],
            "rows": g["rows"], "cover": g["cover"], "blend": g["blend"],
            "layer2": g["layer2"], "tiles": g["tiles"], "palette": g["palette"],
        },
        "reach": _reach(f.get("reach"), store),
        "groups": f["groups"],
        "objects": f["objects"],
        "story": f["story"],
        "tileset": f.get("tileset", []),
    }


def _sheet(sheet: dict, store) -> dict:
    """A provider's page as the app takes it: its picture (a PIL image,
    shown by its title) and a section's pictures, {"image": PIL image,
    "caption", "ref"}, put in the store as blobs."""
    picture = sheet.get("picture")
    if picture is not None:
        sheet = {**sheet, "picture": {"blob": store.put_image(picture), "w": picture.width,
                                      "h": picture.height}}
    elif "picture" in sheet:
        sheet = {k: v for k, v in sheet.items() if k != "picture"}
    if not any(s.get("pictures") for s in sheet.get("sections", ())):
        return sheet
    sections = []
    for s in sheet["sections"]:
        if s.get("pictures"):
            s = {**s, "pictures": [
                {"blob": store.put_image(p["image"]), "w": p["image"].width,
                 "h": p["image"].height, "caption": p.get("caption") or None,
                 "ref": p["ref"].json() if p.get("ref") else None}
                for p in s["pictures"]]}
        sections.append(s)
    return {**sheet, "sections": sections}


def present(result: SelectResult, provider, store) -> tuple[dict, list]:
    """-> (view model, [(label, PIL image)] of its layers, for export)."""
    vm: dict[str, Any] = {"info": result.info or ""}

    arrangement = _arrangement(result.timeline)
    layers: list[tuple[str, Image.Image]] = []
    # A waveform or a timeline the UI draws itself replaces the bitmap the
    # provider rendered of the same thing.
    if not result.waveform and not arrangement:
        layers = resolve_layers(result, provider)
    if layers:
        vm["layers"] = [{"label": label, "blob": store.put_image(img),
                         "w": img.width, "h": img.height}
                        for label, img in layers]

    if result.scene:
        vm["scene"] = _scene(result.scene, store)
    elif result.frames:
        # (A scene supersedes its frames: those are export's fallback.)
        frames = [f for f in result.frames if f is not None]
        vm["frames"] = {
            "blobs": [store.put_image(f) for f in frames],
            "w": max(f.width for f in frames),
            "h": max(f.height for f in frames),
            "intervalMs": result.frame_interval_ms or 150,
        }

    if arrangement:
        vm["arrangement"] = arrangement

    audio = result.audio or {}
    wav = audio.get("wav")
    music = result.music
    if result.waveform:
        vm["waveform"] = result.waveform
    elif music is not None and not layers and not result.frames:
        # Drawn as the server plays the map in the background
        # (viewer_server.music): the columns come in as it goes.
        seconds = music.seconds
        loop = audio.get("loop")
        vm["waveform"] = {"lo": [], "hi": [], "seconds": seconds,
                          "columns": WAVEFORM_COLUMNS, "pending": True,
                          "loop": loop[0] / seconds if loop else None,
                          "loopEnd": loop[1] / seconds if loop else None}
    elif wav and not layers and not result.frames:
        env = wav_envelope(wav, WAVEFORM_COLUMNS)
        if env:
            loop = audio.get("loop") if env[2] else None
            vm["waveform"] = {"lo": env[0], "hi": env[1], "seconds": env[2],
                              "loop": loop[0] / env[2] if loop else None,
                              "loopEnd": loop[1] / env[2] if loop else None}

    if result.summary:
        vm["summary"] = {"title": result.summary.get("title", ""),
                         "fields": [[str(k), str(v)]
                                    for k, v in result.summary.get("fields", [])]}
    if result.table:
        vm["table"] = result.table
    if result.sheet:
        vm["sheet"] = _sheet(result.sheet, store)
    if result.text is not None:
        vm["text"] = result.text
        vm["textWrap"] = bool(result.text_wrap)
        if result.fan_text is not None:
            vm["fanText"] = result.fan_text
    if result.page:
        vm["page"] = result.page
    if result.pan:
        pan = result.pan
        img = pan["image"]
        vm["pan"] = {"blob": store.put_image(img), "w": img.width, "h": img.height,
                     "screenW": pan["screen"][0], "screenH": pan["screen"][1],
                     "hz": pan["hz"], "rows": list(pan["rows"]), "dark": list(pan["dark"])}

    if audio:
        vm["audio"] = {
            "name": audio.get("name", "clip"),
            "wav": store.put_bytes(wav, "audio/wav") if wav else None,
            "midi": (store.put_bytes(audio["midi"], "audio/midi")
                     if audio.get("midi") else None),
            "seconds": (wav_duration(wav) if wav
                        else music.seconds if music is not None else None),
            # [start, end] seconds of a loop the game repeats for ever, and
            # how many times the map plays it (an export can choose others)
            "loop": list(audio["loop"]) if audio.get("loop") else None,
            "passes": audio.get("passes") if audio.get("render_wav")
            else None,
            # the songs the game plays it for; its title, as the game
            # gives a song's, or as its row is titled (a voice's words)
            "songs": list(audio.get("songs") or []) or None,
            "title": audio.get("title") or None,
            # what it is: "song", "sound-effect" (a reference's kind)
            "kind": audio.get("kind") or None,
        }
    return vm, layers
