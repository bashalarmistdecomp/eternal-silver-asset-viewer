"""Tier 1 for the face data by face number — synthetic bytes.

What this CAN catch: the head offsets FaceDataCheck (0x8001B54C) and
FaceSlot6Find (0x8001B5C4) read (length +4, sum +8, the ten faces +0x10,
the pictures +0x20), the sum's word count and its bounds, the 0x1000-byte
picture stride, the five-to-a-file arithmetic of FaceCellSet (0x8001B3DC),
FaceDataLoad (0x8001B1C0)'s two bases and FaceSlot6Load (0x8001B50C)'s
limit, a member's face, and that data failing the sum answers no face.

What it CANNOT catch: whether those are the functions' rules, or whether
the resources hold face data; only re-reading face.c does the first, and
the disc the second. See decoders/testing.py.
"""

import struct
import zlib

import pytest

from decoders import config
from decoders.plugins.SLUS_006_28.formats import face_blocks as fb


def _block(images: list[bytes], faces=(), bad_sum=False, magic=b"FACE") -> bytes:
    """Face data around zlib's raw deflate of the pictures (Huffman blocks
    are bit-identical under the 16-bit reader; test_inflate16.py)."""
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    stream = co.compress(b"".join(images)) + co.flush()
    stream += b"\0" * (-len(stream) % 4)
    total = sum(struct.unpack(f"<{len(stream) // 4}I", stream)) & 0xFFFFFFFF
    head = magic + struct.pack("<II", len(stream), total ^ (1 if bad_sum else 0))
    head += b"\0" * 4 + bytes(faces).ljust(fb.LIST_LEN, b"\0") + b"\0" * 6
    assert len(head) == fb.STREAM
    return head + stream


def _image(seed: int) -> bytes:
    return bytes((seed * 7 + i * 13 + (i >> 6)) & 0xFF for i in range(fb.PICTURE_BYTES))


def test_parse_reads_the_head_and_cuts_pictures_of_0x1000():
    imgs = [_image(k) for k in range(5)]
    block = fb.parse(_block(imgs, faces=(26, 27, 28, 29, 30)))
    assert block.valid
    assert block.faces == (26, 27, 28, 29, 30, 0, 0, 0, 0, 0)
    assert list(block.images) == imgs
    assert len(block.images[0]) == fb.SIDE * fb.SIDE


def test_a_scene_block_keeps_all_ten_pictures():
    imgs = [_image(k) for k in range(10)]
    block = fb.parse(_block(imgs, faces=(66, 71, 75, 80, 84, 101, 106, 112, 118, 119)))
    assert len(block.images) == 10
    assert block.index_of(112) == 7 and block.images[7] == imgs[7]
    assert block.index_of(1) == -1


def test_checksum_is_the_sum_of_length_over_4_words_from_0x20():
    raw = _block([_image(3)], faces=(1,))
    size = struct.unpack_from("<I", raw, 4)[0]
    assert fb.checksum(raw) == sum(struct.unpack_from(f"<{size // 4}I", raw, 0x20)) & 0xFFFFFFFF
    assert fb.is_valid(raw)


def test_data_that_fails_the_sum_holds_no_face():
    raw = _block([_image(1), _image(2)], faces=(5, 6), bad_sum=True)
    block = fb.parse(raw)
    assert not fb.is_valid(raw) and not block.valid
    assert block.faces[:2] == (5, 6) and block.index_of(5) == -1
    with pytest.raises(LookupError):
        fb.face_pixels(lambda res: raw, 5)


def test_validity_bounds_of_face_data_check():
    raw = bytearray(_block([_image(1)], faces=(1,)))
    assert fb.is_valid(bytes(raw))
    assert not fb.is_valid(b"FACX" + bytes(raw[4:]))
    zero = bytearray(raw)
    struct.pack_into("<I", zero, 4, 0)             # (u32)(0 - 1) is not < 0x4E1F
    assert not fb.is_valid(bytes(zero))
    big = bytearray(raw) + b"\0" * 0x5000
    struct.pack_into("<I", big, 4, fb.MAX_SIZE + 1)  # 0x4E20: one past the bound
    assert not fb.is_valid(bytes(big))
    with pytest.raises(ValueError):
        fb.parse(b"TIM\0" + bytes(raw[4:]))


def test_face_file_is_five_to_a_file_from_one():
    assert fb.face_file(1) == (1, 0)
    assert fb.face_file(5) == (1, 4)
    assert fb.face_file(6) == (2, 0)
    assert fb.face_file(120) == (24, 4)
    with pytest.raises(ValueError):
        fb.face_file(0)


def test_a_members_face_is_the_first_of_its_file():
    assert fb.member_face(1) == 1
    assert fb.member_face(6) == 26
    assert fb.face_file(fb.member_face(12)) == (12, 0)


def test_file_resource_has_two_bases():
    assert fb.file_resource(1) == 0xA3
    assert fb.file_resource(6) == 0xA8
    assert fb.file_resource(0x1F) == 0xC1
    assert fb.file_resource(0x20) == 0xAE          # NOT 0xC2: the base drops 0x14
    assert fb.face_source(156) == ("file", 0xAE, 0)
    assert fb.face_source(56) == ("file", 0xAE, 0)  # ... which is face 56's file


def test_scene_resource_stops_at_0x2b():
    assert fb.scene_resource(0) == 0xBA            # the last file
    assert fb.scene_resource(1) == 0xBB
    assert fb.scene_resource(0x2A) == 0xE4
    assert fb.scene_resource(0x2B) is None


def test_the_files_are_the_resources_below_the_first_scene_block():
    assert fb.FILES == 24 and fb.FACES == 120
    assert fb.file_resource(fb.FILES) + 1 == fb.scene_resource(1)
    assert fb.own_file(1) and fb.own_file(120)
    assert not fb.own_file(0) and not fb.own_file(121)


def test_face_source_prefers_the_scene_block():
    listing = (9, 26, 0, 0, 0, 0, 0, 0, 0, 0)
    assert fb.face_source(26, listing) == ("scene", 1)
    assert fb.face_source(27, listing) == ("file", 0xA8, 1)
    assert fb.scene_index(listing, 0) == 2         # 0 matches the first empty entry,
    #                                                but FaceCellSet never asks for face 0


def test_face_pixels_goes_through_the_resource_the_code_reads():
    imgs = [_image(k) for k in range(5)]
    asked = []

    def read(resource):
        asked.append(resource)
        return _block(imgs, faces=(26, 27, 28, 29, 30))

    assert fb.face_pixels(read, 28) == imgs[2]
    assert asked == [0xA8]


def test_image_draws_each_texel_with_its_colour():
    colours = [(0, 0, 0, 0), (0, 0, 0, 255)] + [(k, 0, 0, 255) for k in range(254)]
    pixels = bytes([0, 1, 2] * (fb.PICTURE_BYTES // 3 + 1))[:fb.PICTURE_BYTES]
    pic = fb.image(pixels, colours)
    assert pic.size == (fb.SIDE, fb.SIDE) and pic.mode == "RGBA"
    assert pic.getpixel((0, 0))[3] == 0            # colour 0: not drawn
    assert pic.getpixel((1, 0)) == (0, 0, 0, 255)  # colour 1: black, drawn


# -- the disc, when the library holds it ----------------------------------
_RAW = config.raw_dir("SLUS_006.28")
_ON_DISC = pytest.mark.skipif(
    not ((_RAW / "SLUS_006.28").is_file() and (_RAW / "LUNADATA.FIL").is_file()),
    reason="no SSSC disc in the library")


def _disc_reader():
    from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
    from decoders.psx.analysis.exe_loader import load_exe

    table = {r.index: r for r in load_resource_table(load_exe(_RAW / "SLUS_006.28"))}
    return lambda n: table[n].read(_RAW / "LUNADATA.FIL")


@pytest.mark.disc
@_ON_DISC
def test_on_the_disc_each_file_lists_its_own_five_faces():
    read = _disc_reader()
    for file in range(1, fb.FILES + 1):
        block = fb.parse(read(fb.file_resource(file)))
        first = (file - 1) * fb.PER_FILE + 1
        assert block.valid
        assert block.faces[:fb.PER_FILE] == tuple(range(first, first + fb.PER_FILE))
        assert len(block.images) == fb.PER_FILE


@pytest.mark.disc
@_ON_DISC
def test_on_the_disc_a_scene_block_holds_copies_of_the_faces_it_lists():
    read = _disc_reader()
    files = {}
    for n in range(1, fb.SCENE_LIMIT):
        block = fb.parse(read(fb.scene_resource(n)))
        assert block.valid and len(block.images) == fb.LIST_LEN
        for i, face in enumerate(block.faces):
            if face:
                file, picture = fb.face_file(face)
                if file not in files:
                    files[file] = fb.parse(read(fb.file_resource(file)))
                assert block.images[i] == files[file].images[picture]
