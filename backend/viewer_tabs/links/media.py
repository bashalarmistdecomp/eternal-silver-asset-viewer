"""Media and the disc: movies, bromides, images, resources, CD tracks, sound
banks, sequences, samples and the disc's files.

MoviePlay (0x800232D4) shows number n (records.events). It first sets
story flag n + 340, the flag the theater lists movie n by; then for n from
55 to 67 PictureShow (0x80024A7C) shows bromide n - 55, the two pictures
of resource 586 + k panned down while the voice g_PictureVoices
(0x800AF844) gives it plays; any other n is a movie, which MENU.BIN's
movie_play (0x80196B54) plays from the file "_B%03d.STR" % n. A bromide
item names its bromide in its row (MenuUsePictureRun (0x8007690C)).

The game reads LUNADATA.FIL by resource number only
(formats.resource_table), and what a resource holds is what the code that
reads it makes of it (formats.resources). The links to a resource are those
readers: a map's, a script's, a sound bank, a portrait file, a portrait
list, the party's starting records, a bromide and the pictures a resource
keeps. A bank's sequences and samples are the ones its command list adds.

Two kinds have numbers the code does not give:

- an image is its resource and its number there: a kept picture's own
  (resource_tim_add (0x800208A0) counts them 0, 1, ...); a picture sent to
  video memory at once has none, and is numbered after the kept ones, in
  list order (`image_numbers`).
- a disc file is its place in the disc's list of files, by name, from 0
  (DiscContext.files): ISO 9660 names a file, and a reference is a number.
"""

from __future__ import annotations

from viewer_tabs import links
from viewer_tabs.links import CardBody, Edge, sound_effects
from viewer_tabs.refs import ref, written

MOVIE_PLAY = "MoviePlay (0x800232D4)"
MOVIE_FILE_PLAY = "movie_play (0x80196B54)"         # MENU.BIN, the movie player
DISC_WAIT = "overlay_disc_wait (0x80023184)"
THEATER = "MenuUseMovieListSet (0x800776CC)"
STORY_FLAG_SET = "StoryBitSet (0x800576EC)"
PICTURE_SHOW = "PictureShow (0x80024A7C)"
PICTURE_STEP = "PictureStep (0x800249B0)"
PICTURE_DRAW = "PictureDraw (0x80024950)"
PICTURE_BAND = "PictureBandDraw (0x8002484C)"
SCREEN_FADE = "screen_fade_step (0x8001C0F0)"
FRAME_END = "frame_end (0x8001F30C)"
PICTURE_VOICE = "PictureXaPlay (0x800247AC)"
PICTURE_ITEM = "MenuUsePictureRun (0x8007690C)"
TIM_ADD = "resource_tim_add (0x800208A0)"
TIM_LOAD = "resource_tim_load (0x80020950)"
RESOURCE_LOAD = "resource_load (0x80020230)"
MAP_LOAD = "MapResourceLoad (0x80020D70)"
SCRIPT_LOAD = "ScriptResourceLoad (0x80020D20)"
BANK_LOAD = "sound_bank_load (0x80024138)"
VAB_HEAD = "sound_vab_head_open (0x80024314)"
VAB_BODY = "sound_vab_body_transfer (0x800243D0)"
SEQ_ADD = "sound_seq_add (0x80024464)"
FACE_FILE = "FaceDataLoad (0x8001B1C0)"
FACE_LIST = "FaceSlot6Load (0x8001B50C)"
PARTY_RESET = "ChrRecordsReset (0x80063B30)"

#: MenuUseRun (0x80076444): the entry of its table an item's use byte
#: (+0x07, low four bits) picks; entry 4 is MenuUsePictureRun (0x8007690C),
#: which shows the bromide in the high four bits.
PICTURE_USE = 4


# -- what the disc gives, read once per disc --------------------------------

def _names(model):
    """The game's names; None on a disc of a program these decoders do not
    serve (it has none of these links), an error on one they serve that
    cannot be read."""
    from decoders.plugins.SLUS_006_28.records.programs import PROGRAMS
    if model.ctx.program not in PROGRAMS:
        return None
    return model.need_names()


def _cached(model, key: str, make):
    """A part of the disc this module reads, kept on the model."""
    found = model.__dict__.get(key)
    if found is None:
        with model.lock:
            found = model.__dict__.get(key)
            if found is None:
                found = model.__dict__[key] = make()
    return found


def image_numbers(cmds) -> dict[int, tuple[int, int | None]]:
    """Each picture of a resource's command list, by the offset of its
    command: (its image number, its kept number or None)."""
    from decoders.plugins.SLUS_006_28.formats import command_list as cl
    found = cl.pictures(cmds)
    kept = sum(1 for _c, n in found if n is not None)
    out, sent = {}, 0
    for c, n in found:
        if n is None:
            out[c.offset] = (kept + sent, None)
            sent += 1
        else:
            out[c.offset] = (n, n)
    return out


def _image_index(model) -> dict[int, list[tuple[int, int | None]]]:
    """Every resource that holds pictures: [(image number, kept number)].
    Only the command lists are walked; no picture is unpacked."""
    from decoders.plugins.SLUS_006_28.formats import command_list as cl
    from decoders.plugins.SLUS_006_28.formats import resources as rs

    def make():
        names = model.need_names()
        out = {}
        with open(model.ctx.path("LUNADATA.FIL"), "rb") as f:
            for res in names.resources():
                if not rs.is_command_list(res.index):
                    continue
                f.seek(res.offset)
                numbers = image_numbers(cl.commands(f.read(res.size)))
                if numbers:
                    out[res.index] = sorted(numbers.values())
        return out
    return _cached(model, "_media_images", make)


def _resource_pictures(model, resource: int) -> dict:
    """Resource `resource`'s pictures, unpacked: image number -> Picture."""
    from decoders.plugins.SLUS_006_28.formats import command_list as cl
    from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
    cache = model.__dict__.setdefault("_media_pictures", {})
    found = cache.get(resource)
    if found is None:
        names = model.need_names()
        if names.resource_entry(resource) is None:
            raise LookupError(f"the resource table has no resource {resource}")
        buf = names.read_resource(resource)
        numbers = image_numbers(cl.commands(buf))
        found = cache[resource] = {numbers[p.offset][0]: p for p in rp.pictures(buf, resource)}
    return found


def _image(model, r):
    """The picture image `r` is."""
    resource, n = r.id
    p = _resource_pictures(model, resource).get(n)
    if p is None:
        raise LookupError(f"resource {resource} keeps no image {n}")
    return p


def _banks(model) -> dict:
    """Every sound bank, by its resource (formats.sound_banks)."""
    def make():
        from decoders.plugins.SLUS_006_28.formats.sound_banks import find_banks
        names = model.need_names()
        return {b.resource: b for b in find_banks(model.ctx.path("LUNADATA.FIL"),
                                                  names.resources())}
    return _cached(model, "_media_banks", make)


def _bank(model, resource: int):
    b = _banks(model).get(resource)
    if b is None:
        raise LookupError(f"resource {resource} is not a sound bank")
    return b


def _end_frames(model) -> list[int] | None:
    """movie_play (0x80196B54)'s last frame of each movie (0 for none), from
    the overlay on this disc; None when the disc has no overlay."""
    def make():
        from decoders.plugins.SLUS_006_28.formats import disc_files as df
        from decoders.plugins.SLUS_006_28.records import events as ev
        path = model.ctx.path(df.overlay_file_name(model.need_names().binary))
        return (ev.end_frames(path.read_bytes()),) if path.is_file() else (None,)
    return _cached(model, "_media_end_frames", make)[0]


def _movie(model, n: int):
    """records.events' Event for movie n; raises when the game has none."""
    from decoders.plugins.SLUS_006_28.records import events as ev
    if ev.BROMIDE_FIRST <= n < ev.BROMIDE_FIRST + ev.BROMIDE_COUNT:
        raise LookupError(f"MoviePlay shows {n} as bromide {n - ev.BROMIDE_FIRST}, not a movie")
    if not 0 <= n < ev.MOVIE_COUNT:
        raise LookupError(f"the game's movies are numbered 0 to {ev.MOVIE_COUNT - 1}")
    frames = _end_frames(model)
    if frames is not None and not frames[n]:
        raise LookupError(f"the game has no movie {n}: movie_play's table gives it no frames")
    return ev.event(n)


def _file_numbers(ctx) -> dict[str, int]:
    """Each file of the disc, by name: its disc file number."""
    return {name: i for i, name in enumerate(ctx.files)}


def _voices(model) -> list[int]:
    from decoders.plugins.SLUS_006_28.records import events as ev
    return _cached(model, "_media_voices",
                   lambda: ev.picture_voices(model.need_names().binary.code))


def _cd_tracks(model) -> tuple[list, str]:
    """The disc's audio tracks, and why there are none when there are none
    (CdTracksProvider reads them)."""
    def make():
        from viewer_tabs.tab_providers import CdTracksProvider
        p = CdTracksProvider()
        p._ensure_loaded(model.ctx)
        return (p._tracks, p._reason)
    return _cached(model, "_media_cd_tracks", make)


# -- words ------------------------------------------------------------------

def _length(seconds: float) -> str:
    """"1 min 17 s", "4.2 s", "0.35 s"."""
    if seconds < 1:
        return f"{seconds:.2f} s"
    if seconds < 10:
        return f"{seconds:.1f} s"
    s = round(seconds)
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def _size(n: int) -> str:
    from viewer_tabs.tab_providers import size_text
    return size_text(n)


def _flag_words(n: int) -> str:
    return f"story flag {n} (0x{n:04X})"


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


# -- edges ------------------------------------------------------------------

@links.edges
def movie_edges(model):
    """Each movie -> the file it plays from and the story flag it sets."""
    from decoders.plugins.SLUS_006_28.records import events as ev
    if _names(model) is None:
        return
    frames = _end_frames(model)
    files = _file_numbers(model.ctx)
    for n in range(ev.MOVIE_COUNT):
        e = ev.event(n)
        here = e.movie in files
        # without the overlay's table, only a movie whose file is here is known
        known = frames[n] != 0 if frames is not None else here
        if not known:
            continue
        m = ref("movie", n)
        if here:
            yield Edge(m, ref("disc-file", files[e.movie]), "Stored in", "Holds",
                       "the movie's file", MOVIE_FILE_PLAY)
        yield Edge(m, ref("story-flag", n + ev.EVENT_FLAG_BASE), "Story flag", "Set by",
                   "set when it is seen; the theater lists it from then on", MOVIE_PLAY)


@links.edges
def bromide_edges(model):
    """Each bromide -> its resource, its two pictures and the story flag it
    sets."""
    from decoders.plugins.SLUS_006_28.records import events as ev
    names = _names(model)
    if names is None:
        return
    images = _image_index(model)
    for k in range(ev.BROMIDE_COUNT):
        b = ref("bromide", k)
        resource = ev.BROMIDE_RESOURCE_BASE + k
        if names.resource_entry(resource) is not None:
            yield Edge(b, ref("resource", resource), "Stored in", "Holds",
                       "read when it is shown", PICTURE_SHOW)
        for n, kept in images.get(resource, []):
            if kept in (0, 1):
                yield Edge(b, ref("image", resource, n), "Pictures", "Bromide",
                           "the top" if kept == 0 else "the bottom", PICTURE_SHOW)
        yield Edge(b, ref("story-flag", ev.BROMIDE_FIRST + k + ev.EVENT_FLAG_BASE),
                   "Story flag", "Set by", "set when it is shown", MOVIE_PLAY)


@links.edges
def bromide_voice_edges(model):
    """Each bromide -> the voice that plays while it is shown."""
    if _names(model) is None:
        return
    for k, voice in enumerate(_voices(model)):
        yield Edge(ref("bromide", k), ref("voice", voice), "Voice", "Played with bromides",
                   "played while it is shown", PICTURE_VOICE)


@links.edges
def bromide_item_edges(model):
    """Each bromide item -> the bromide it shows."""
    from decoders.plugins.SLUS_006_28.records import events as ev
    from decoders.plugins.SLUS_006_28.records import items
    names = _names(model)
    if names is None:
        return
    for row in items.read_from_exe(names.binary.code):
        use = row.values["use_picture"]
        if use & 0xF == PICTURE_USE and (use >> 4) < ev.BROMIDE_COUNT:
            yield Edge(ref("item", row.item_id), ref("bromide", use >> 4), "Shows", "Shown by",
                       "used from the menu", PICTURE_ITEM)


@links.edges
def resource_edges(model):
    """What the code reads from each resource: maps, scripts, portrait
    files and lists, and the party's starting records."""
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    from decoders.plugins.SLUS_006_28.formats import party_init as pi
    from decoders.plugins.SLUS_006_28.formats import resources as rs
    names = _names(model)
    if names is None:
        return

    def there(n: int) -> bool:
        return names.resource_entry(n) is not None

    for m in names.maps():
        yield Edge(ref("map", m.map_id), ref("resource", m.resource), "Stored in", "Holds",
                   "read when the map is entered", MAP_LOAD)
    for res in names.resources():
        reg = rs.region(res.index)
        if reg is not None and reg.key == "scripts":
            for sid in names.script_ids_for_resource(res.index):
                yield Edge(ref("script", sid), ref("resource", res.index), "Stored in", "Holds",
                           "read when a map runs it", SCRIPT_LOAD)
    for face in range(1, fb.FACES + 1):
        file, _picture = fb.face_file(face)
        if there(fb.file_resource(file)):
            yield Edge(ref("portrait", face), ref("resource", fb.file_resource(file)),
                       "Stored in", "Holds", f"portrait file {file}, five portraits", FACE_FILE)
    for n in range(1, fb.SCENE_LIMIT):
        if there(fb.scene_resource(n)):
            yield Edge(ref("portrait-list", n), ref("resource", fb.scene_resource(n)),
                       "Stored in", "Holds", "read when a scene asks for it", FACE_LIST)
    if there(pi.RESOURCE):
        for c in range(pi.CHAR_FIRST, pi.CHAR_LAST + 1):
            yield Edge(ref("character", c), ref("resource", pi.RESOURCE), "Starting record",
                       "Starting records", "their record at a new game", PARTY_RESET)


@links.edges
def image_edges(model):
    """Each image -> the resource that keeps it."""
    if _names(model) is None:
        return
    for resource, found in _image_index(model).items():
        for n, _kept in found:
            yield Edge(ref("image", resource, n), ref("resource", resource), "Stored in", "Holds",
                       "", TIM_ADD)


@links.edges
def bank_edges(model):
    """Each sound bank -> its resource; each of its sequences and samples
    -> the bank."""
    if _names(model) is None:
        return
    for b in _banks(model).values():
        bank = ref("sound-bank", b.resource)
        yield Edge(bank, ref("resource", b.resource), "Stored in", "Holds",
                   "read when the game loads the bank", BANK_LOAD)
        for i in range(len(b.seqs)):
            yield Edge(ref("sequence", b.resource, i), bank, "In bank", "Sequences",
                       "played through the bank's samples", SEQ_ADD)
        for v in (b.vab.vags if b.vab else ()):
            yield Edge(ref("sample", b.resource, v.index), bank, "In bank", "Samples",
                       "", VAB_BODY)


# -- titles (cheap: called once a link) -----------------------------------------

@links.title("movie")
def movie_title(model, r) -> str | None:
    names = model.names
    return names.movie(r.id[0]) if names else None


@links.title("bromide")
def bromide_title(model, r) -> str | None:
    names = model.names
    return names.bromide(r.id[0]) if names else None


@links.title("image")
def image_title(model, r) -> str | None:
    """As the Screens tab titles it."""
    from viewer_tabs.tab_providers import ScreensProvider
    names = model.names
    return ScreensProvider.title(names, _image(model, r)) if names else None


@links.title("disc-file")
def disc_file_title(model, r) -> str | None:
    files = model.ctx.files
    return files[r.id[0]] if 0 <= r.id[0] < len(files) else None


# -- cards ------------------------------------------------------------------

@links.card("movie")
def movie_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.records import events as ev
    from viewer_tabs.movie import SECTORS_PER_SECOND
    from viewer_tabs.tab_providers import MoviesProvider
    names = model.need_names()
    n = r.id[0]
    e = _movie(model, n)
    facts = [("Disc", f"disc {e.disc}")]
    extended = [
        ("File", f"{e.movie}: movie_play builds \"_B%03d.STR\" from the number"),
        ("Disc", f"{DISC_WAIT} asks for disc 1 for movies below {ev.DISC2_FIRST}, disc 2 "
                 f"from {ev.DISC2_FIRST} on, unless the disc in the drive holds the file"),
    ]
    picture, note = None, ""
    if e.movie in model.ctx.files:
        player = MoviesProvider()
        path = model.ctx.path(e.movie)
        info = player._probe(path)
        if info is not None:
            facts.append(("Length", "about " + _length(info["sectors"] / SECTORS_PER_SECOND)))
            if info["mdec"]:
                picture, frame = _movie_frame(player, model.ctx, path, info)
                if picture is not None:
                    extended.append(("Picture", f"frame {frame}, a quarter of the way in, "
                                                f"in the shape a TV shows it"))
    else:
        note = f"Its file is on disc {e.disc}, not on this one."
    facts.append(("In the theater", "yes, once it has been seen"))
    frames = _end_frames(model)
    if frames is not None:
        extended.append(("Frames played", f"0 to {frames[n] - 5}: movie_play passes the last "
                                          f"frame its table gives ({frames[n]}, D_8019769C) less 5"))
    flag = n + ev.EVENT_FLAG_BASE
    extended += [
        ("Story flag", f"{_flag_words(flag)}: {STORY_FLAG_SET} in MoviePlay, before it plays"),
        ("Theater", f"entry {n + 1}: {THEATER} lists it once {_flag_words(flag)} is set"),
    ]
    return CardBody(title=names.movie(n) or written(r), subtitle="a movie", picture=picture,
                    facts=facts, note=note, extended=extended,
                    proven=[MOVIE_PLAY, MOVIE_FILE_PLAY, DISC_WAIT, THEATER])


def _movie_frame(player, ctx, path, info):
    """A frame a quarter of the way into the movie, as wide as a TV shows
    it, and its number; (None, None) when none there decodes."""
    from PIL import Image
    decoded = player._decode_window(path, 1)
    if not decoded:
        return None, None
    frame, first = decoded[0]
    img = player._image(first)
    aspect, _note = player._shape(ctx, info)
    if aspect:
        w = round(img.width * aspect[0] / aspect[1])
        img = img.resize((w, img.height), Image.BICUBIC)
    return img, frame.frame_no


@links.card("bromide")
def bromide_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
    from decoders.plugins.SLUS_006_28.formats import system_strings as ss
    from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
    from decoders.plugins.SLUS_006_28.records import events as ev
    from decoders.plugins.SLUS_006_28.records.programs import Unmapped
    from viewer_tabs.tab_providers import BromidesProvider
    names = model.need_names()
    k = r.id[0]
    if not 0 <= k < ev.BROMIDE_COUNT:
        raise LookupError(f"the game's bromides are numbered 0 to {ev.BROMIDE_COUNT - 1}")
    resource = ev.BROMIDE_RESOURCE_BASE + k
    if names.resource_entry(resource) is None:
        raise LookupError(f"the resource table has no resource {resource}")
    picture, drawn = rp.bromide_image(names.read_resource(resource), resource)
    show = rp.bromide_show()
    rows = [f.row for f in show]
    hz = BromidesProvider.HZ
    facts = [("On screen", f"{len(show) / hz:.1f} s: the screen looks down the picture and "
                           f"back up, coming in from black and going out to black"),
             ("Picture", f"{picture.width} × {picture.height} pixels, two pictures one "
                         f"under the other")]
    extended = [
        ("Movie number", f"{ev.BROMIDE_FIRST + k}: {MOVIE_PLAY} shows it with PictureShow({k})"),
        ("Resource", f"{resource} (0x{resource:03X}): PictureShow reads it, and {TIM_LOAD} "
                     f"loads its kept pictures 0 and 1"),
    ]
    extended += [(f"Picture {p.picture}",
                  f"command 2 at {p.offset:#x}, sub-number {p.sub}: {p.width} × {p.height} at "
                  f"({p.vram_x}, {p.vram_y}) in video memory; {colours}")
                 for p, colours in drawn]
    top = max(rows)
    extended += [
        ("Drawn", f"{PICTURE_DRAW}: the {rp.SCREEN_H} rows from the pan's row y of the "
                  f"column at x {rp.BROMIDE_PAGE_X}, rows y to 255 of texture page 5 and the "
                  f"first y - 32 of page 0x15, three sprites a band ({PICTURE_BAND}): rows 0 "
                  f"to {picture.height - 1} are ever on the screen"),
        ("Pan", f"{PICTURE_STEP}: from (0, 0x8000), a += b / 120 and b -= the old a / 120; "
                f"y = 0x7C - (b >> 8), held between 0 and 255: 0, down to {top} at frame "
                f"{rows.index(top)}, and back"),
        ("Frames", f"{rp.BROMIDE_SHOWN} (0x{rp.BROMIDE_SHOWN:X}), the first {rp.BROMIDE_FADE} "
                   f"fading in, and {rp.BROMIDE_FADE} more fading out ({SCREEN_FADE}); one a "
                   f"vertical blank ({FRAME_END} waits on VSync(0)); then the screen is off "
                   f"until the voice has ended, {rp.BROMIDE_VOICE_WAIT} frames at most"),
    ]
    try:
        voice = _voices(model)[k]
        row = {v.number: v for v in xv.voices(names.binary.code)}.get(voice)
        facts.append(("Its voice", "a voice line" + (f", {row.seconds:.1f} s" if row else "")
                      + ", from the moment it comes in"))
        extended.append(("Voice", f"voice {voice}: byte {k} of g_PictureVoices (0x800AF844), "
                                  f"which {PICTURE_VOICE} plays before the first frame"))
    except Unmapped as ex:
        extended.append(("Voice", f"not read: {ex}"))
    flag = ev.BROMIDE_FIRST + k + ev.EVENT_FLAG_BASE
    extended += [
        ("Story flag", f"{_flag_words(flag)}: {STORY_FLAG_SET} in MoviePlay"),
        ("Title", f"string 0x{ss.string_id('bromide', k):03X}: the string table's bromide "
                  f"titles, placed by its layout; no code that prints them was found"),
    ]
    return CardBody(title=names.bromide(k) or written(r), subtitle="a bromide",
                    picture=picture, facts=facts, extended=extended,
                    proven=[MOVIE_PLAY, PICTURE_SHOW, PICTURE_STEP, PICTURE_DRAW, PICTURE_BAND,
                            PICTURE_VOICE])


@links.card("image")
def image_card(model, r) -> CardBody:
    from decoders.psx.formats.tim import MODE_4BIT, MODE_8BIT, MODE_NAMES
    from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
    from viewer_tabs.tab_providers import ScreensProvider
    names = model.need_names()
    p = _image(model, r)
    img, colours = rp.image(names.read_resource(p.resource), p)
    role = rp.role(p, ScreensProvider._program(names))
    facts = [("Size", f"{p.width} × {p.height} pixels"),
             ("Colours", {MODE_4BIT: "16", MODE_8BIT: "256"}.get(p.mode, "its own, in each pixel"))]
    kept = (f"kept picture {p.picture}: {TIM_LOAD} loads it by that number" if p.picture is not None
            else "sent to video memory as the list is read; the code keeps no number for it, "
                 "so it is numbered after the kept pictures")
    extended = [
        ("Command", f"command 2 at {p.offset:#x} of resource {p.resource}, sub-number {p.sub}"),
        ("Its number", kept),
        ("Shown by", role.shown_by),
        ("TIM", f"{MODE_NAMES.get(p.mode, p.mode)}, at ({p.vram_x}, {p.vram_y}) in video memory"),
        ("Colours", colours),
    ]
    return CardBody(title=ScreensProvider.title(names, p),
                    subtitle=f"an image kept in resource {p.resource}", picture=img,
                    facts=facts, extended=extended,
                    proven=list(dict.fromkeys([TIM_ADD, *_decoder_proof(ScreensProvider.PRODUCER)])))


def _decoder_proof(producer: str) -> list[str]:
    from decoders import inventory
    dec = inventory.get(producer)
    return list(dec.proven_by) if dec and dec.proven_by else []


@links.card("resource")
def resource_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import command_list as cl
    from decoders.plugins.SLUS_006_28.formats import resources as rs
    names = model.need_names()
    n = r.id[0]
    res = names.resource_entry(n)
    if res is None:
        raise LookupError(f"the resource table has no resource {n}")
    reg = rs.region(n)
    facts = [("Holds", reg.what if reg else "nothing the code reads"),
             ("Size", _size(res.size))]
    extended = [("Sectors", f"{res.start_sector} to {res.start_sector + res.size_sectors - 1} "
                            f"of LUNADATA.FIL, at {res.offset:#x}"),
                ("Read by", f"{RESOURCE_LOAD}, by g_ResourceSectorPairs (0x800AE904)")]
    proven = [RESOURCE_LOAD]
    if reg is not None:
        facts.append(("Read", "as a list of commands, each loading one part" if reg.commands
                      else "whole, as it lies"))
        extended.append(("Region", f"resources {reg.first} to {reg.last}, read by {reg.reader}"))
        if rs.number_in_region(n):
            extended.append(("The code's number", rs.number_in_region(n)))
        if reg.commands:
            extended.append(("Commands", cl.summary(cl.commands(names.read_resource(n)))))
        proven.append(reg.reader)
    return CardBody(title=written(r), subtitle=reg.what if reg else "a resource",
                    facts=facts, extended=extended, proven=proven)


def _plays(model, resource: int, index: int | None = None):
    """What a bank or its score plays (links.sound_effects.sequence_is);
    nothing said when that cannot be read: the card stands without it."""
    try:
        return sound_effects.sequence_is(model, resource, index)
    except Exception:
        return None, "", []


@links.card("sound-bank")
def sound_bank_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import resources as rs
    b = _bank(model, r.id[0])
    reg = rs.region(b.resource)
    vags = len(b.vab.vags) if b.vab else 0
    facts = [("Holds", f"{_count(vags, 'sample', 'samples')} and "
                       f"{_count(len(b.seqs), 'sequence', 'sequences')}"),
             ("Size", _size(b.used_bytes))]
    extended = [("Resource", f"{b.resource}, from sector {b.sector} of LUNADATA.FIL")]
    if b.vab:
        v = b.vab
        extended.append(("VAB", f"version {v.version}, {v.ps} programs, {v.ts} tones, "
                                f"{v.vs} samples: {VAB_HEAD}, {VAB_BODY}"))
    extended.append(("Sequences", f"{len(b.seqs)}, each added by {SEQ_ADD}"))
    if reg is not None:
        extended.append(("Loaded by", reg.reader))
    subtitle = reg.what if reg else "a sound bank"
    plays, _words, numbers = _plays(model, b.resource)
    if plays == sound_effects.SONG:
        subtitle = "a bank of the music"
        if numbers:
            facts.insert(0, ("Plays", sound_effects.song_words(model.names, numbers)))
    elif plays == sound_effects.SOUND_EFFECT:
        subtitle = "a bank of sound effects"
        said = sound_effects.bank_words(model, b.resource)
        if said:
            facts.insert(0, ("Holds", said))
    return CardBody(title=written(r), subtitle=subtitle,
                    facts=facts, extended=extended,
                    proven=[BANK_LOAD, VAB_HEAD, VAB_BODY, SEQ_ADD])


@links.card("sequence")
def sequence_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.records.sound_setting import game_setting
    from decoders.psx.formats.seq_synth import walk
    from decoders.psx.formats.vab import SPU_BASE_RATE
    resource, i = r.id
    b = _bank(model, resource)
    if not 0 <= i < len(b.seqs):
        raise LookupError(f"sound bank {resource} has {_count(len(b.seqs), 'sequence', 'sequences')}")
    seq = b.seqs[i]
    facts = []
    if b.vab is not None:
        setting = game_setting(model.need_names().binary)
        # two passes, as Sound banks walks it: the second measures the loop
        stats = walk(seq, b.vab, passes=2, tick_hz=setting.tick_hz,
                     vblank_minus=setting.vblank_minus)
        if stats.loop:
            start, end = (x / SPU_BASE_RATE for x in stats.loop)
            facts.append(("Length", f"{_length(start)}, then a {_length(end - start)} loop "
                                    f"for ever"))
        else:
            facts.append(("Length", _length(stats.seconds)))
    facts += [("Notes", f"{seq.notes:,}"), ("Channels", str(len(seq.channels)))]
    extended = [("Score", f"{seq.size:,} bytes, version {seq.version}, {seq.resolution} ticks "
                          f"a quarter note, {seq.bpm:.1f} beats a minute"),
                ("Added by", f"{SEQ_ADD}: command 15 of the bank's list")]
    subtitle = f"a score of sound bank {resource}"
    plays, words, _numbers = _plays(model, resource, i)
    if plays == sound_effects.SONG and words:
        subtitle = "a song's score"
        facts.insert(0, ("Plays", words))
    elif plays == sound_effects.SOUND_EFFECT:
        subtitle = "a sound effect's score"
        facts.insert(0, ("Plays", words or "no sound effect: no number SoundPlay is given "
                                           "plays it"))
    return CardBody(title=written(r), subtitle=subtitle,
                    facts=facts, extended=extended, proven=[SEQ_ADD, BANK_LOAD])


@links.card("sample")
def sample_card(model, r) -> CardBody:
    resource, i = r.id
    b = _bank(model, resource)
    vag = next((v for v in (b.vab.vags if b.vab else ()) if v.index == i), None)
    if vag is None:
        raise LookupError(f"sound bank {resource} has no sample {i}")
    pcm, loop = vag.decode()
    rate = b.vab.vag_rate(i)
    users = b.vab.tones_using(i)
    facts = [("Length", _length(len(pcm) / rate)),
             ("Plays", "once" if loop is None else "in a loop, for as long as it is held"),
             ("Rate", f"{rate:,} Hz")]
    extended = [("Stored", f"{vag.size:,} bytes of SPU-ADPCM at +{vag.offset:#x} of the bank's "
                           f"VAB body: {VAB_BODY}")]
    if users:
        extended.append(("Played by", ", ".join(f"program {t.program} tone {t.index}"
                                                for t in users[:6])
                         + (f" and {len(users) - 6} more" if len(users) > 6 else "")))
    else:
        extended.append(("Played by", "no tone of the bank uses it"))
    return CardBody(title=written(r), subtitle=f"a sample of sound bank {resource}",
                    facts=facts, extended=extended, proven=[VAB_BODY, BANK_LOAD])


@links.card("cd-track")
def cd_track_card(model, r) -> CardBody:
    tracks, reason = _cd_tracks(model)
    t = next((t for t in tracks if t.number == r.id[0]), None)
    if t is None:
        raise LookupError(reason or f"the disc has no audio track {r.id[0]}")
    facts = [("Length", _length(t.seconds)), ("Sound", "CD audio, 44.1 kHz stereo")]
    extended = [("Size", f"{t.size:,} bytes of 16-bit samples ({_size(t.size)})"),
                ("Read from", f"the disc image's cue sheet, {model.ctx.source.name}")]
    return CardBody(title=written(r), subtitle="an audio track of the disc",
                    facts=facts, extended=extended)


@links.card("disc-file")
def disc_file_card(model, r) -> CardBody:
    from viewer_tabs.tab_providers import DiscFilesProvider
    files = model.ctx.files
    i = r.id[0]
    if not 0 <= i < len(files):
        raise LookupError(f"the disc has {len(files)} files, numbered 0 to {len(files) - 1}")
    name = files[i]
    path = model.ctx.path(name)
    size = path.stat().st_size
    facts = [("Size", _size(size)), ("Type", DiscFilesProvider()._kind(path))]
    extended = [("Numbered by", f"its place in this disc's list of files, by name, from 0: "
                                f"file {i + 1} of {len(files)}"),
                ("Size", f"{size:,} bytes")]
    subtitle, proven = "a file of the disc", []
    from decoders.plugins.SLUS_006_28.records.programs import PROGRAMS
    if model.ctx.program in PROGRAMS:
        from decoders.plugins.SLUS_006_28.formats import disc_files as df
        role = df.role(name)
        if role is not None:
            subtitle = "a movie's file" if role is df.MOVIE_ROLE else role.what
            extended.append(("What it is", role.what))
            if role.reader:
                extended.append(("Read by", role.reader))
                proven.append(role.reader)
    return CardBody(title=name, subtitle=subtitle, facts=facts, extended=extended,
                    proven=proven)
