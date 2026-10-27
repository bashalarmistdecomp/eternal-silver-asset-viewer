"""STR streaming-container parsing (Sony's ``STR: Streaming (Movie) Data``).

Scope: the CONTAINER only — sector headers, frame reassembly, and the
MDEC-animation frame attributes. This module deliberately does NOT decode
the MDEC bitstream into pixels; that is `decoders.psx.formats.mdec` (VLC +
IDCT + YCbCr). What you get here is each frame's raw bitstream plus its
declared width/height, which is what that decoder consumes.

Layout is Sony's, from the SDK's own *File Formats* reference, Chapter 1.
An STR file is a flat run of
2048-byte sectors; each is a 32-byte header followed by 2016 bytes of
payload, and a frame's sectors are contiguous with the frame starting on a
sector boundary.

Sector header, all little-endian::

    +0x00  u16  StSTATUS          format id + version
    +0x02  u16  StTYPE            MSB set => system-defined; 0x8001 = MDEC
    +0x04  u16  StSECTOR_OFFSET   sector index within the frame
    +0x06  u16  StSECTOR_SIZE     sectors in this frame
    +0x08  u32  StFRAME_NO        frame number, STARTS AT 1
    +0x0C  u32  StFRAME_SIZE      frame size: long words by Sony's text, bytes on disc
    +0x10  u16  StMOVIE_WIDTH     ) type 0x8001 only; for user-defined
    +0x12  u16  StMOVIE_HEIGHT    ) types +0x10..+0x1F is StUSER
    +0x14  u32  StMOVIE_HEADM     reserved for system
    +0x18  u32  StMOVIE_HEADV     reserved for system
    +0x1C  u32  (reserved)

Three traps this module exists to hold:

* ``StFRAME_NO`` starts at **1**, not 0. Indexing an array with it
  off-by-ones the whole stream.
* **A .STR file contains sectors that are not STR sectors.** Streaming
  with audio INTERLEAVES XA-ADPCM sectors between the data sectors
  (Sony, Figure 6/7). They carry no STR header — in SLUS_009.21's
  ``_B000.STR`` sector 15 reads ``status=0x0C0C`` with a zeroed header.
  A grouper that trusts every sector loses the frame it was accumulating,
  so :func:`looks_like_str_sector` gates the walk.
* **``StFRAME_SIZE`` is in BYTES, against the documentation.** Sony's text
  says "Frame size (in long words)"; measured on ``_B000.STR``, frames
  declare 6100 / 13452 / 17676 against payloads of 20160 / 18144 / 20160.
  Read as bytes every value fits its frame; read as long words every one
  overruns. The bytes win (the ``CdControlF`` precedent), and this module
  reads bytes — but the field keeps Sony's NAME so the discrepancy stays
  visible rather than being quietly renamed away.
"""

import struct
from dataclasses import dataclass
from typing import Iterator

SECTOR_SIZE = 2048
HEADER_SIZE = 32
PAYLOAD_SIZE = SECTOR_SIZE - HEADER_SIZE      # 2016

#: StTYPE for system-defined MDEC animation frames.
TYPE_MDEC = 0x8001


@dataclass(frozen=True)
class StrSectorHeader:
    """One sector's 32-byte header, fields exactly as Sony names them."""

    status: int
    type: int
    sector_offset: int
    sector_size: int
    frame_no: int
    frame_size_words: int
    width: int
    height: int
    headm: int
    headv: int

    @property
    def is_system_defined(self) -> bool:
        return bool(self.type & 0x8000)

    @property
    def is_mdec(self) -> bool:
        # The low bits of StTYPE carry the channel number for
        # multi-channel streaming; ordinary streaming uses channel 0.
        return self.is_system_defined and (self.type & 0x7FFF) == (
            TYPE_MDEC & 0x7FFF)

    @property
    def frame_size_bytes(self) -> int:
        """Frame size in bytes.

        Sony documents StFRAME_SIZE as long words; the shipped streams
        disagree and this returns the raw value. See module docstring.
        """
        return self.frame_size_words


@dataclass(frozen=True)
class StrFrame:
    """One reassembled frame: its attributes and its raw payload."""

    frame_no: int
    width: int
    height: int
    sector_count: int
    declared_size_bytes: int
    data: bytes           # concatenated sector payloads, uncropped

    @property
    def bitstream(self) -> bytes:
        """Payload cropped to the declared frame size.

        Sectors are padded to the 2048-byte boundary, so the tail of the
        last sector is filler; ``declared_size_bytes`` is where the real
        data ends.
        """
        n = self.declared_size_bytes
        return self.data[:n] if 0 < n <= len(self.data) else self.data


def parse_sector_header(buf: bytes, offset: int = 0) -> StrSectorHeader:
    """Decode one 32-byte sector header."""
    if len(buf) - offset < HEADER_SIZE:
        raise ValueError(
            f"need {HEADER_SIZE} bytes for an STR sector header, "
            f"got {len(buf) - offset}")
    (status, type_, sec_off, sec_size, frame_no, frame_words,
     width, height, headm, headv) = struct.unpack_from(
        "<HHHHIIHHII", buf, offset)
    return StrSectorHeader(status, type_, sec_off, sec_size, frame_no,
                           frame_words, width, height, headm, headv)


def looks_like_str_sector(h: StrSectorHeader) -> bool:
    """Structural plausibility test for one decoded header.

    Exists because a .STR file legitimately contains interleaved
    XA-ADPCM sectors with no STR header at all — see module docstring.
    Deliberately structural (no magic-value allowlist) so it does not
    silently reject a stream from another title.
    """
    return (h.is_system_defined
            and 0 < h.sector_size <= 255
            and h.sector_offset < h.sector_size
            and h.frame_no > 0)


def iter_sectors(data: bytes) -> Iterator[StrSectorHeader]:
    """Yield every sector header in an STR image, in file order."""
    for off in range(0, len(data) - HEADER_SIZE + 1, SECTOR_SIZE):
        yield parse_sector_header(data, off)


def iter_str_sectors(data: bytes) -> Iterator[tuple[int, StrSectorHeader]]:
    """Yield ``(byte_offset, header)`` for sectors that ARE STR sectors."""
    for off in range(0, len(data) - HEADER_SIZE + 1, SECTOR_SIZE):
        h = parse_sector_header(data, off)
        if looks_like_str_sector(h):
            yield off, h


def iter_frames(data: bytes) -> Iterator[StrFrame]:
    """Reassemble frames from an STR image.

    Sectors are grouped by ``StFRAME_NO``; a frame is emitted once its
    ``StSECTOR_SIZE`` sectors have been seen, so a truncated trailing
    frame is dropped rather than emitted short.
    """
    pending: list[bytes] = []
    head: StrSectorHeader | None = None

    for i, h in iter_str_sectors(data):
        if head is None or h.frame_no != head.frame_no:
            head, pending = h, []
        pending.append(data[i + HEADER_SIZE:i + SECTOR_SIZE])
        if len(pending) == h.sector_size:
            yield StrFrame(
                frame_no=h.frame_no, width=h.width, height=h.height,
                sector_count=h.sector_size,
                declared_size_bytes=h.frame_size_bytes,
                data=b"".join(pending))
            head, pending = None, []


def probe(data: bytes) -> dict:
    """Summarise a stream without reassembling every frame.

    Reads the first sector for the attributes and counts sectors, which
    is enough for an index entry on a multi-hundred-megabyte file.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("not an STR image: shorter than one sector header")
    h = parse_sector_header(data, 0)
    sectors = len(data) // SECTOR_SIZE
    return {
        "sectors": sectors,
        "sector_size": SECTOR_SIZE,
        "type": h.type,
        "mdec": h.is_mdec,
        "width": h.width if h.is_mdec else None,
        "height": h.height if h.is_mdec else None,
        "sectors_per_frame": h.sector_size,
        "frames": sectors // h.sector_size if h.sector_size else 0,
    }
