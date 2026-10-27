"""The PS-X EXE container's header, and SLUS_006.28's program unpacked:
the disc's EXE is a small stub whose LZSS payload, from file offset 0x1000,
is the real program with a header of its own (`load_exe`). That unwrap is
the program's quirk and belongs in its plugin; it lives here as a declared
seam. `LoadedBinary` maps an image's RAM addresses to its bytes, per
instance (`load_base`).
"""

import hashlib
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from decoders.plugins.SLUS_006_28.formats.lzss import decompress


# PS-X EXE magic: "PS-X EXE" followed by padding
PSX_EXE_MAGIC = b"PS-X EXE"

#: The container header is exactly one CD sector; the body follows it.
PSX_HEADER_SIZE = 0x800

# SLUS_006.28's container, not PS1 facts: the LZSS payload's place in the
# outer file, and where the unpacked image (its header first) is mapped
COMPRESSED_DATA_OFFSET = 0x1000
INNER_HEADER_LOAD = 0x80010800


@dataclass
class LoadedBinary:
    """A decompressed PS1 binary loaded into a virtual address space."""

    raw: bytes
    """Full decompressed data (PS-X EXE header + code + data)."""

    text_start: int
    """RAM address where code begins."""

    text_size: int
    """Size of the code/data region in bytes."""

    entry_point: int
    """RAM address of the entry point."""

    name: str = ""
    """Identifier (e.g. 'SLUS_006.28')."""

    load_base: int = 0
    """RAM address of raw[0]. For a headered EXE this is
    `text_start - PSX_HEADER_SIZE` (the header rides just below the
    body, the fiction INNER_HEADER_LOAD encodes for SSSC); for headerless
    code it equals text_start. 0 means "unset" and is normalized to
    text_start in __post_init__. Address translation is per-instance
    state, never a module constant."""

    def __post_init__(self):
        if self.load_base == 0:
            self.load_base = self.text_start

    def ram_to_offset(self, addr: int) -> int:
        """Convert a RAM address to a byte offset into self.raw."""
        offset = addr - self.load_base
        if offset < 0 or offset >= len(self.raw):
            raise ValueError(
                f"Address 0x{addr:08X} out of range "
                f"(0x{self.load_base:08X}-0x{self.load_base + len(self.raw):08X})"
            )
        return offset

    def offset_to_ram(self, offset: int) -> int:
        """Convert a byte offset in the raw blob to a RAM address."""
        return offset + self.load_base

    def read_u32(self, addr: int) -> int:
        """Read a little-endian 32-bit unsigned integer at a RAM address."""
        off = self.ram_to_offset(addr)
        return struct.unpack_from("<I", self.raw, off)[0]

    def read_u16(self, addr: int) -> int:
        """Read a little-endian 16-bit unsigned integer at a RAM address."""
        off = self.ram_to_offset(addr)
        return struct.unpack_from("<H", self.raw, off)[0]

    def read_bytes(self, addr: int, count: int) -> bytes:
        """Read `count` bytes starting at a RAM address."""
        off = self.ram_to_offset(addr)
        return self.raw[off : off + count]

    @property
    def code(self) -> bytes:
        """Just the code/data region (excluding any PS-X EXE header)."""
        header_size = self.text_start - self.load_base
        return self.raw[header_size : header_size + self.text_size]

    @property
    def code_end(self) -> int:
        """RAM address one past the last byte of the code region."""
        return self.text_start + self.text_size


def _parse_psx_header(data: bytes) -> dict:
    """Parse a PS-X EXE header (2048 bytes): its addresses and sizes."""
    if not data[:8] == PSX_EXE_MAGIC:
        raise ValueError("Not a PS-X EXE: bad magic")

    u32 = lambda off: struct.unpack_from("<I", data, off)[0]
    return {
        "entry_point": u32(0x10),
        "gp": u32(0x14),
        "text_start": u32(0x18),
        "text_size": u32(0x1C),
        "d_addr": u32(0x20),
        "d_size": u32(0x24),
        "b_addr": u32(0x28),
        "b_size": u32(0x2C),
        "s_addr": u32(0x30),
        "s_size": u32(0x34),
    }


#: The last few programs `load_exe` decompressed, by the sha1 of the file's
#: bytes: each tab of a disc loads its program, and the discs of a game
#: often carry the same one; each gets its own LoadedBinary of the one
#: decompressed image.
KEEP_UNPACKED = 4
_UNPACKED: OrderedDict[bytes, bytes] = OrderedDict()
_unpacked_lock = threading.Lock()


def load_exe(exe_path: str | Path) -> LoadedBinary:
    """Load and decompress the Lunar SSSC PS1 executable.

    Reads the outer EXE, decompresses the LZSS payload starting at
    file offset 0x1000, and parses the inner PS-X EXE header.
    """
    exe_path = Path(exe_path)
    with open(exe_path, "rb") as f:
        outer = f.read()

    # Verify outer header
    _parse_psx_header(outer)

    # Decompress the LZSS payload, or take it from a file of the same bytes
    # read before (_UNPACKED)
    key = hashlib.sha1(outer).digest()
    with _unpacked_lock:
        raw = _UNPACKED.get(key)
        if raw is not None:
            _UNPACKED.move_to_end(key)
    if raw is None:
        raw = decompress(outer[COMPRESSED_DATA_OFFSET:])
        with _unpacked_lock:
            _UNPACKED[key] = raw
            while len(_UNPACKED) > KEEP_UNPACKED:
                _UNPACKED.popitem(last=False)

    # Parse the inner PS-X EXE header
    inner = _parse_psx_header(raw)

    return LoadedBinary(
        raw=raw,
        text_start=inner["text_start"],
        text_size=inner["text_size"],
        entry_point=inner["entry_point"],
        name=exe_path.stem,
        load_base=INNER_HEADER_LOAD,
    )


def find_exe(data_dir: Path) -> Path:
    """Locate the extracted PS1 executable in a game root's raw stage.

    `data_dir` is the directory holding per-disc dumps —
    `<library>/<program>/raw/` — because the executable is named after the
    disc that carried it (`SLUS_006.28/SLUS_006.28`).
    """

    # Look for a per-disc dir whose executable is named after it
    for disc_dir in sorted(data_dir.iterdir()):
        exe = disc_dir / disc_dir.name
        if exe.exists() and exe.stat().st_size > 100_000:
            return exe

    raise FileNotFoundError(
        f"No PS1 executable found in {data_dir}. "
        "Import a disc image first using the viewer."
    )
