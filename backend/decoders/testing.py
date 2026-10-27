"""Byte-stream builders for the decoders' tests.

The tests build their inputs by hand, so no game bytes are ever committed.
That has a limit worth stating once: a hand-built fixture tests a decoder
against OUR MODEL of the format, not against the format. It catches
regressions; it cannot catch a misunderstanding, because we wrote both
sides. A test that needs a real disc reads it from the library and skips
when the disc is not there.
"""


def u8(*vals: int) -> bytes:
    return bytes(vals)


def u16(*vals: int) -> bytes:
    """Little-endian halfwords — the PS1's native order."""
    return b"".join(v.to_bytes(2, "little") for v in vals)


def u32(*vals: int) -> bytes:
    return b"".join(v.to_bytes(4, "little") for v in vals)


def be16(*vals: int) -> bytes:
    """Big-endian halfwords — SEQ and other Sony sequence formats."""
    return b"".join(v.to_bytes(2, "big") for v in vals)


def be32(*vals: int) -> bytes:
    return b"".join(v.to_bytes(4, "big") for v in vals)


def rgb555(r: int, g: int, b: int, stp: int = 0) -> int:
    """Pack 5-bit components into the PS1's ABGR1555 halfword."""
    return (stp << 15) | ((b & 0x1F) << 10) | ((g & 0x1F) << 5) | (r & 0x1F)


# -- disc images ---------------------------------------------------------------

#: Where a made-up disc image (`iso_image`) keeps its root directory, and
#: where its files begin.
ISO_ROOT_LBA = 18
ISO_FIRST_FILE_LBA = 20


def _iso_both(n: int) -> bytes:
    """A 32-bit field as ISO 9660 writes it: little-endian, then big."""
    return u32(n) + n.to_bytes(4, "big")


def _iso_record(name: bytes, lba: int, size: int, flags: int = 0) -> bytes:
    body = (b"\0" + _iso_both(lba) + _iso_both(size) + bytes(7) + bytes([flags])
            + bytes(6) + bytes([len(name)]) + name)
    body += b"\0" * ((len(body) + 1) % 2)      # a record's length is even
    return bytes([len(body) + 1]) + body


def iso_image(files: dict[bytes, bytes], volume_id: bytes = b"") -> bytes:
    """A plain 2048-byte-sector image whose root directory holds `files`
    (name -> bytes), each in sectors of its own, after the "." and ".."
    records."""
    from decoders.config import SECTOR_SIZE
    sectors: dict[int, bytes] = {}
    records = [_iso_record(b"\0", ISO_ROOT_LBA, SECTOR_SIZE, 2),
               _iso_record(b"\1", ISO_ROOT_LBA, SECTOR_SIZE, 2)]
    lba = ISO_FIRST_FILE_LBA
    for name, data in files.items():
        records.append(_iso_record(name, lba, len(data)))
        sectors[lba] = data
        lba += max(1, -(-len(data) // SECTOR_SIZE))
    pvd = bytearray(SECTOR_SIZE)
    pvd[0:6] = b"\1CD001"
    pvd[40:72] = volume_id.ljust(32)[:32]
    pvd[156:156 + 34] = _iso_record(b"\0", ISO_ROOT_LBA, SECTOR_SIZE, 2)
    sectors[16] = bytes(pvd)
    sectors[ISO_ROOT_LBA] = b"".join(records)
    out = bytearray(lba * SECTOR_SIZE)
    for at, data in sectors.items():
        out[at * SECTOR_SIZE:at * SECTOR_SIZE + len(data)] = data
    return bytes(out)


def raw_sectors(image: bytes) -> bytes:
    """A 2048-byte-sector image as a raw (2352-byte, Mode 2) track: each
    sector's user data where a .bin rip holds it."""
    from decoders.config import MODE2_DATA_OFFSET, RAW_SECTOR_SIZE, SECTOR_SIZE
    out = bytearray()
    for at in range(0, len(image), SECTOR_SIZE):
        raw = bytearray(RAW_SECTOR_SIZE)
        raw[MODE2_DATA_OFFSET:MODE2_DATA_OFFSET + SECTOR_SIZE] = image[at:at + SECTOR_SIZE]
        out += raw
    return bytes(out)
