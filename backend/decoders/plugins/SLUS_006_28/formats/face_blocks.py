"""Portraits BY FACE NUMBER — which face data and which picture a face is,
as face.c works it out, and the face data's own header.

A message window, the menus and the battle's window name a portrait by a
FACE NUMBER and hand it to one function, FaceCellSet (0x8001B3DC):

    face 0                 the cell is cleared
    FaceSlot6Find (0x8001B5C4)(face) >= 0
                           the face is one of the ten listed in the face
                           data in slot 6 (a scene block): that picture
    otherwise              five faces a file: file (face - 1) / 5 + 1,
                           picture (face - 1) % 5; FaceSlotGet (0x8001B200)
                           loads the file with FaceDataLoad (0x8001B1C0):
                           resource file + 0xA2, or file + 0x8E from file
                           0x20 on
    FaceImageLoad (0x8001B310)
                           inflate_buffer (0x80021D6C) from the face data
                           + 0x20, then
                           picture * 0x1000: 64 x 64 at 8 bits

FaceSlot6Load (0x8001B50C)(n) reads scene block n, resource n + 0xBA, into
slot 6 for n below 0x2B; FaceListLoad (0x8007601C) and
ScriptCommandFaceListSet (0x8005E610) call it with byte 6 of the face list.

The face data's head, FaceDataHead (include/face.h):

    +0x00  the mark "FACE"                      FaceDataCheck (0x8001B54C)
    +0x04  the packed pictures' length, 1..0x4E1F
    +0x08  the sum of length / 4 words from +0x20: in slot 6, data that
           fails it lists no face (FaceSlot6Find); for a file FaceSlotGet
           calls assert_fail (0x8001B050), which does nothing
    +0x10  u8[10] the face numbers of its pictures, picture i = entry i,
           0 = none                              FaceSlot6Find
    +0x20  the packed pictures                   FaceImageLoad

Files 1 to 24 are the resources from 0xA3 up to the first scene block's,
0xBB: faces 1 to 120. Nothing in the code bounds a face number; a face
above 120 reads a scene block as its file (and from file 0x20 on, the file
0x14 lower).

WHOSE. A party member's face is (id - 1) * 5 + 1: ShopFaceSet
(0x80054C0C) and BtlMenuActingFaceSet (0x80049D60) show it, and
FaceListByteLoad (0x80076094) loads its file, file id, for a member of the
face list, whose ids FaceListPartySet (0x80075EFC) keeps below 0xD.

This module reads bytes and returns bytes: 8-bit texels, not colours. The
palette is row 503 (FaceCellDraw (0x8001B4B0) draws with 0x7DC0), which
`system_dat.palette_rows` reads from resource 1; `image` applies it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from decoders.plugins.SLUS_006_28.formats import inflate16

#: "FACE" as FaceDataCheck compares it (0x45434146, little-endian)
MAGIC = b"FACE"
#: where the packed pictures start (FaceImageLoad: face data + 0x20)
STREAM = 0x20
#: the ten face numbers FaceSlot6Find scans
LIST_AT = 0x10
LIST_LEN = 10
#: FaceDataCheck: (u32)(length - 1) < 0x4E1F
MAX_SIZE = 0x4E1F
#: one picture: FaceImageLoad steps picture << 12 and sends 32 x 64 words
PICTURE_BYTES = 0x1000
SIDE = 64
#: FaceCellSet: five faces a file
PER_FILE = 5
#: FaceDataLoad: file + 0xA2, or file + 0x8E from file 0x20
FILE_BASE = 0xA2
FILE_BASE_HIGH = 0x8E
FILE_HIGH_FROM = 0x20
#: FaceSlot6Load: n + 0xBA while n < 0x2B (unsigned)
SCENE_BASE = 0xBA
SCENE_LIMIT = 0x2B
#: the files below the first scene block (resource SCENE_BASE + 1)
FILES = SCENE_BASE - FILE_BASE
FACES = FILES * PER_FILE
#: FaceCellDraw: palette 0x7DC0 = video-memory row 503
CLUT_ROW = 503
#: FaceListPartySet: a face-list member's id is below 0xD
MEMBER_LIMIT = 0xD


@dataclass(frozen=True)
class FaceBlock:
    """One face data, head read and pictures unpacked."""
    size: int                      # +0x04
    checksum: int                  # +0x08
    faces: tuple                   # +0x10, ten face numbers (0 = none)
    images: tuple                  # 0x1000-byte pictures, 8-bit texels
    valid: bool                    # FaceDataCheck's answer

    def index_of(self, face: int) -> int:
        """FaceSlot6Find: the picture holding `face`, or -1 -- also -1 for
        every face when the data is not valid."""
        return scene_index(self.faces, face) if self.valid else -1


def checksum(raw: bytes) -> int:
    """The sum FaceDataCheck forms: length / 4 words from +0x20, 32 bits."""
    size = struct.unpack_from("<i", raw, 4)[0]
    words = (size + 3 if size < 0 else size) >> 2
    return sum(struct.unpack_from(f"<{words}I", raw, STREAM)) & 0xFFFFFFFF


def is_valid(raw: bytes) -> bool:
    """FaceDataCheck: the mark, a length of 1..0x4E1F, and the sum."""
    if len(raw) < STREAM or raw[:4] != MAGIC:
        return False
    size = struct.unpack_from("<I", raw, 4)[0]
    if not (size - 1) & 0xFFFFFFFF < MAX_SIZE:
        return False
    if len(raw) < STREAM + (size >> 2) * 4:
        return False
    return checksum(raw) == struct.unpack_from("<I", raw, 8)[0]


def parse(raw: bytes) -> FaceBlock:
    """A face data's head and its pictures. Raises ValueError when the
    bytes are not a face data at all; data that only fails the sum is
    returned with valid = False, as the game would see it."""
    if len(raw) < STREAM or raw[:4] != MAGIC:
        raise ValueError("not a face data")
    size, check = struct.unpack_from("<II", raw, 4)
    pixels = inflate16.decompress(raw[STREAM:STREAM + size + (size & 1)])
    images = tuple(pixels[i:i + PICTURE_BYTES]
                   for i in range(0, len(pixels) - PICTURE_BYTES + 1, PICTURE_BYTES))
    return FaceBlock(size, check, tuple(raw[LIST_AT:LIST_AT + LIST_LEN]),
                     images, is_valid(raw))


def scene_index(faces, face: int) -> int:
    """FaceSlot6Find's scan: the first of the ten entries equal to `face`."""
    for i in range(LIST_LEN):
        if i < len(faces) and faces[i] == face:
            return i
    return -1


def face_file(face: int) -> tuple:
    """FaceCellSet's file path: (file, picture) = ((face - 1) / 5 + 1,
    (face - 1) % 5). Face 0 is "no face" and has neither."""
    if face <= 0:
        raise ValueError("face 0 clears the cell; it has no file")
    return (face - 1) // PER_FILE + 1, (face - 1) % PER_FILE


def file_resource(file: int) -> int:
    """FaceDataLoad: the LUNADATA resource read for a file."""
    return file + (FILE_BASE_HIGH if file >= FILE_HIGH_FROM else FILE_BASE)


def scene_resource(n: int) -> int | None:
    """FaceSlot6Load: the resource of scene block n, None when the function
    loads nothing (n >= 0x2B as an unsigned number)."""
    return n + SCENE_BASE if 0 <= n < SCENE_LIMIT else None


def own_file(face: int) -> bool:
    """Whether the face's file is one of the FILES below the first scene
    block (faces 1..FACES)."""
    return 1 <= face <= FACES


def member_face(chr_id: int) -> int:
    """The face shown for party member `chr_id`: (id - 1) * 5 + 1
    (ShopFaceSet, BtlMenuActingFaceSet), the first of file id's five."""
    return (chr_id - 1) * PER_FILE + 1


def face_source(face: int, scene_faces=None) -> tuple:
    """Where FaceCellSet takes `face` from: ("scene", picture) when the
    valid data in slot 6 lists it (pass that data's ten faces), else
    ("file", resource, picture)."""
    if scene_faces is not None:
        i = scene_index(scene_faces, face)
        if i >= 0:
            return ("scene", i)
    file, picture = face_file(face)
    return ("file", file_resource(file), picture)


def face_pixels(read_resource, face: int) -> bytes:
    """The 64 x 64 8-bit picture of `face` by the file path. `read_resource`
    is resource number -> bytes (resource_table). Raises LookupError when
    the data does not hold that picture or fails FaceDataCheck: the game
    then draws whatever the load buffer holds (FaceSlotGet's assert_fail
    does nothing), which no disc byte says."""
    _, resource, picture = face_source(face)
    block = parse(read_resource(resource))
    if not block.valid or picture >= len(block.images):
        raise LookupError(f"face {face}: resource {resource:#x} has no valid picture {picture}")
    return block.images[picture]


def image(pixels: bytes, colours):
    """A picture as an RGBA PIL image under 256 RGBA `colours` (row 503 by
    `system_dat.colours`)."""
    from PIL import Image

    pic = Image.frombytes("P", (SIDE, SIDE), bytes(pixels[:SIDE * SIDE]).ljust(SIDE * SIDE, b"\0"))
    pal = list(colours)[:256] + [(0, 0, 0, 0)] * (256 - len(colours))
    pic.putpalette(b"".join(bytes(c) for c in pal), rawmode="RGBA")
    return pic.convert("RGBA")
