"""PS1 MDEC video: the compressed bitstream inside an STR frame -> pixels.

`str_stream` is the CONTAINER — it reassembles a frame's sectors into one
bitstream and stops. This module is the codec that turns that bitstream
into an image, which is the step that was missing everywhere in this repo.

The MDEC is PlayStation hardware, so there is no game code to read for it:
a game DMAs the bitstream in and gets pixels back. That makes the pipeline
below a transcription of the hardware's documented behaviour rather than a
reading of any one program, and it is why this module is psx-generic. It
carries no game knowledge and works unchanged on every title tested.

    frame header      8 bytes: code count, 0x3800, q_scale, version
    bitstream         16-bit LITTLE-ENDIAN words, bits read MSB-first
    per block         DC (10-bit, v2) then AC run/level VLC pairs, EOB
    dequantize        MPEG-1 default intra matrix, scaled by q_scale
    IDCT              8x8, separable
    macroblock        Cr, Cb, Y1..Y4 — 4:2:0, 16x16 of luma per chroma pair
    frame             macroblocks in COLUMNS, top to bottom then rightwards
    colour            YCbCr -> RGB, luma offset +128

**The byte order is the classic trap.** The bitstream is a sequence of
little-endian 16-bit words and the bits within each word run MSB-first, so
reading the bytes in file order gives a stream that decodes for a while and
then desyncs. `_swap16` does that swap once per frame.

**Self-check, not eyeballing.** The frame header's first field is the count
of MDEC codes the bitstream expands to, divided by two, and every block
must end with an EOB code. `decode_frame` counts what it actually produced
and `check_frame` compares the two. A wrong VLC entry or a wrong bit order
desyncs the stream and the count stops matching — so correctness here is
falsifiable against the file itself, with no reference decoder and no
emulator capture involved.

Versions: v2 is what every stream measured in this repo uses (SSSC, The
Making of Lunar, all three Lunar 2 discs, the Lunar 2 demo and making-of).
v3's DC prediction is NOT implemented; `decode_frame` refuses it loudly
rather than producing a plausible wrong picture.

Spec: docs/spec/formats/mdec.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_SIZE = 8

#: Identifies an STR frame header. Sony's own name for the field is a magic
#: constant; it is 0x3800 in every version.
MAGIC = 0x3800

#: Frame-header versions this module decodes. v1 and v3 exist; v3 codes DC
#: differentially with its own VLC tables, which is a separate decoder.
SUPPORTED_VERSIONS = (2,)

#: MPEG-1's default intra quantizer matrix in NATURAL (row-major) order, as
#: ISO 11172-2 prints it, with 2 for the DC entry: the MDEC scales DC by the
#: table's first entry, and the PS1 library's table has 2 there.
MPEG1_INTRA_MATRIX = (
     2, 16, 19, 22, 26, 27, 29, 34,
    16, 16, 22, 24, 27, 29, 34, 37,
    19, 22, 26, 27, 29, 34, 34, 38,
    22, 22, 26, 27, 29, 34, 37, 40,
    22, 26, 27, 29, 32, 35, 40, 48,
    26, 27, 29, 32, 35, 40, 48, 58,
    26, 27, 29, 34, 38, 46, 56, 69,
    27, 29, 35, 38, 46, 56, 69, 83,
)

#: Zigzag scan order: ZIGZAG[k] is the natural 8x8 index of the k-th
#: coefficient in scan order.
ZIGZAG = (
     0,  1,  8, 16,  9,  2,  3, 10,
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
)

#: The table the MDEC reads: `MPEG1_INTRA_MATRIX` in ZIGZAG order. The
#: hardware weights the k-th coefficient of the scan by entry k, and the
#: table a game uploads is laid out that way: SSSC's movie player calls
#: DecDCTReset (libpress), which sends the library's built-in table, and that
#: table is this one entry for entry. Index it with the scan position.
QUANT_TABLE = tuple(MPEG1_INTRA_MATRIX[ZIGZAG[k]] for k in range(64))

#: End-of-block, and the escape that introduces a literal run/level pair.
EOB_CODE = "10"
ESCAPE_CODE = "000001"

#: The AC run/level variable-length codes — MPEG-1's Table B-14. Each code
#: is followed by one sign bit. `10` is end-of-block and `000001` escapes to
#: a literal 6-bit run + 10-bit signed level (the PS1 widens MPEG-1's level
#: field to 10 bits).
AC_VLC: dict[str, tuple[int, int]] = {
    "11": (0, 1),
    "011": (1, 1),
    "0100": (0, 2),
    "0101": (2, 1),
    "00101": (0, 3),
    "00110": (4, 1),
    "00111": (3, 1),
    "000100": (7, 1),
    "000101": (6, 1),
    "000110": (1, 2),
    "000111": (5, 1),
    "0000100": (2, 2),
    "0000101": (9, 1),
    "0000110": (0, 4),
    "0000111": (8, 1),
    "00100000": (13, 1),
    "00100001": (0, 6),
    "00100010": (12, 1),
    "00100011": (11, 1),
    "00100100": (3, 2),
    "00100101": (1, 3),
    "00100110": (0, 5),
    "00100111": (10, 1),
    "0000001000": (16, 1),
    "0000001001": (5, 2),
    "0000001010": (0, 7),
    "0000001011": (2, 3),
    "0000001100": (1, 4),
    "0000001101": (15, 1),
    "0000001110": (14, 1),
    "0000001111": (4, 2),
    "000000010000": (0, 11),
    "000000010001": (8, 2),
    "000000010010": (4, 3),
    "000000010011": (0, 10),
    "000000010100": (2, 4),
    "000000010101": (7, 2),
    "000000010110": (21, 1),
    "000000010111": (20, 1),
    "000000011000": (0, 9),
    "000000011001": (19, 1),
    "000000011010": (18, 1),
    "000000011011": (1, 5),
    "000000011100": (3, 3),
    "000000011101": (0, 8),
    "000000011110": (6, 2),
    "000000011111": (17, 1),
    "0000000010000": (10, 2),
    "0000000010001": (9, 2),
    "0000000010010": (5, 3),
    "0000000010011": (3, 4),
    "0000000010100": (2, 5),
    "0000000010101": (1, 7),
    "0000000010110": (1, 6),
    "0000000010111": (0, 15),
    "0000000011000": (0, 14),
    "0000000011001": (0, 13),
    "0000000011010": (0, 12),
    "0000000011011": (26, 1),
    "0000000011100": (25, 1),
    "0000000011101": (24, 1),
    "0000000011110": (23, 1),
    "0000000011111": (22, 1),
    "00000000010000": (0, 31),
    "00000000010001": (0, 30),
    "00000000010010": (0, 29),
    "00000000010011": (0, 28),
    "00000000010100": (0, 27),
    "00000000010101": (0, 26),
    "00000000010110": (0, 25),
    "00000000010111": (0, 24),
    "00000000011000": (0, 23),
    "00000000011001": (0, 22),
    "00000000011010": (0, 21),
    "00000000011011": (0, 20),
    "00000000011100": (0, 19),
    "00000000011101": (0, 18),
    "00000000011110": (0, 17),
    "00000000011111": (0, 16),
    "000000000010000": (0, 40),
    "000000000010001": (0, 39),
    "000000000010010": (0, 38),
    "000000000010011": (0, 37),
    "000000000010100": (0, 36),
    "000000000010101": (0, 35),
    "000000000010110": (0, 34),
    "000000000010111": (0, 33),
    "000000000011000": (0, 32),
    "000000000011001": (1, 14),
    "000000000011010": (1, 13),
    "000000000011011": (1, 12),
    "000000000011100": (1, 11),
    "000000000011101": (1, 10),
    "000000000011110": (1, 9),
    "000000000011111": (1, 8),
    "0000000000010000": (1, 18),
    "0000000000010001": (1, 17),
    "0000000000010010": (1, 16),
    "0000000000010011": (1, 15),
    "0000000000010100": (6, 3),
    "0000000000010101": (16, 2),
    "0000000000010110": (15, 2),
    "0000000000010111": (14, 2),
    "0000000000011000": (13, 2),
    "0000000000011001": (12, 2),
    "0000000000011010": (11, 2),
    "0000000000011011": (31, 1),
    "0000000000011100": (30, 1),
    "0000000000011101": (29, 1),
    "0000000000011110": (28, 1),
    "0000000000011111": (27, 1),
}

_MAX_CODE_BITS = max(len(c) for c in AC_VLC)


class MdecError(ValueError):
    """The bitstream is not decodable as MDEC — malformed or unsupported."""


@dataclass(frozen=True)
class FrameHeader:
    """An STR frame's 8-byte header, fields as Sony names them."""

    mdec_codes: int      # StMDEC_CODE_COUNT: the header field, doubled
    magic: int
    q_scale: int
    version: int

    @property
    def looks_valid(self) -> bool:
        return self.magic == MAGIC


@dataclass
class DecodedFrame:
    """One decoded frame plus what the decode actually consumed."""

    width: int
    height: int
    rgb: bytes             # width*height*3, 8-bit RGB
    header: FrameHeader
    codes: int             # MDEC codes produced (DC + ACs + EOB per block)
    blocks: int
    bits_used: int
    bits_available: int    # bits in the payload, for the tail check


# ---------------------------------------------------------------------------
# Bit access
# ---------------------------------------------------------------------------

def _swap16(payload: bytes) -> bytes:
    """Byte-swap 16-bit words so the bits read MSB-first in coding order."""
    if len(payload) % 2:
        payload = payload + b"\x00"
    buf = bytearray(payload)
    buf[0::2], buf[1::2] = payload[1::2], payload[0::2]
    return bytes(buf)


class _BitReader:
    """MSB-first bit reader over already byte-swapped data."""

    __slots__ = ("_data", "_pos", "_nbits")

    def __init__(self, data: bytes):
        self._data = data
        self._nbits = len(data) * 8
        self._pos = 0

    @property
    def pos(self) -> int:
        return self._pos

    def read(self, n: int) -> int:
        if self._pos + n > self._nbits:
            raise MdecError(
                f"bitstream exhausted: wanted {n} bits at {self._pos} of "
                f"{self._nbits}")
        value = 0
        pos = self._pos
        for _ in range(n):
            byte = self._data[pos >> 3]
            value = (value << 1) | ((byte >> (7 - (pos & 7))) & 1)
            pos += 1
        self._pos = pos
        return value

    def read_bit(self) -> int:
        if self._pos >= self._nbits:
            raise MdecError(f"bitstream exhausted at bit {self._pos}")
        byte = self._data[self._pos >> 3]
        bit = (byte >> (7 - (self._pos & 7))) & 1
        self._pos += 1
        return bit


def _signed(value: int, bits: int) -> int:
    """Interpret `bits` bits of `value` as two's complement."""
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def parse_frame_header(data: bytes) -> FrameHeader:
    """Decode the 8 bytes in front of a frame's bitstream.

    The first field counts MDEC codes in units of two — the bitstream
    expands to `mdec_codes` 16-bit codes, which is the invariant
    `check_frame` holds a decode to.
    """
    if len(data) < HEADER_SIZE:
        raise MdecError(f"need {HEADER_SIZE} bytes for a frame header, "
                        f"got {len(data)}")
    half, magic, q_scale, version = struct.unpack_from("<HHhH", data, 0)
    return FrameHeader(mdec_codes=half * 2, magic=magic,
                       q_scale=q_scale, version=version)


# ---------------------------------------------------------------------------
# Block decoding
# ---------------------------------------------------------------------------

def _read_block(bits: _BitReader, q_scale: int) -> tuple[list[int], int]:
    """One 8x8 block -> (64 dequantized coefficients, MDEC codes consumed).

    Natural (not zigzag) order out. The DC coefficient is scaled by the
    quantizer matrix alone; q_scale applies to the AC coefficients only,
    which is the hardware's rule and not a simplification.
    """
    coeffs = [0] * 64
    dc = _signed(bits.read(10), 10)
    coeffs[0] = dc * QUANT_TABLE[0]
    codes = 1

    index = 0
    while True:
        code = ""
        for _ in range(_MAX_CODE_BITS):
            code += "1" if bits.read_bit() else "0"
            if code == EOB_CODE:
                return coeffs, codes + 1        # EOB is itself an MDEC code
            if code == ESCAPE_CODE:
                run = bits.read(6)
                level = _signed(bits.read(10), 10)
                break
            hit = AC_VLC.get(code)
            if hit is not None:
                run, magnitude = hit
                level = -magnitude if bits.read_bit() else magnitude
                break
        else:
            raise MdecError(f"no VLC matches {code!r} at bit {bits.pos}")

        index += run + 1
        if index > 63:
            raise MdecError(f"run overflows the block: index {index} "
                            f"at bit {bits.pos}")
        zz = ZIGZAG[index]
        coeffs[zz] = (level * QUANT_TABLE[index] * q_scale + 4) >> 3
        codes += 1


# ---------------------------------------------------------------------------
# IDCT
# ---------------------------------------------------------------------------

def _idct_basis():
    """The 8x8 DCT-III basis, as a list of rows (pure-Python fallback)."""
    import math
    basis = []
    for x in range(8):
        row = []
        for u in range(8):
            c = (1 / math.sqrt(2)) if u == 0 else 1.0
            row.append(0.5 * c * math.cos((2 * x + 1) * u * math.pi / 16))
        basis.append(row)
    return basis


_BASIS = _idct_basis()

try:  # numpy is a declared dependency; the fallback keeps this importable
    import numpy as _np       # without it, exactly like seq_synth.
    _NP_BASIS = _np.array(_BASIS, dtype=_np.float64)
except ImportError:           # pragma: no cover - exercised only without numpy
    _np = None
    _NP_BASIS = None


def idct_8x8(coeffs) -> list[float]:
    """Inverse DCT of 64 coefficients in natural order -> 64 samples.

    Two paths that agree to well below the 8-bit output precision: numpy
    matrix products when it is installed, the same basis applied by hand
    when it is not.
    """
    if _np is not None:
        block = _np.asarray(coeffs, dtype=_np.float64).reshape(8, 8)
        return (_NP_BASIS @ block @ _NP_BASIS.T).reshape(64).tolist()

    tmp = [[0.0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            tmp[y][x] = sum(_BASIS[x][u] * coeffs[y * 8 + u] for u in range(8))
    out = [0.0] * 64
    for x in range(8):
        for y in range(8):
            out[y * 8 + x] = sum(_BASIS[y][v] * tmp[v][x] for v in range(8))
    return out


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------

def _clamp8(value: float) -> int:
    if value <= 0:
        return 0
    if value >= 255:
        return 255
    return int(value)


def _reconstruct(blocks, mb_cols, mb_rows, width, height) -> bytes:
    """Dequantized coefficient blocks -> packed 8-bit RGB.

    `blocks` is every 8x8 block of the frame in decode order: macroblocks
    down each column then rightwards, six blocks each (Cr, Cb, Y1..Y4).
    The luma quadrants tile the macroblock as Y1 Y2 over Y3 Y4, and the
    chroma pair covers all 16x16 of it — 4:2:0.
    """
    if _np is not None:
        spatial = _NP_BASIS @ _np.asarray(
            blocks, dtype=_np.float64).reshape(-1, 8, 8) @ _NP_BASIS.T
        spatial = spatial.reshape(mb_cols, mb_rows, 6, 8, 8)

        # (cols, rows, 8, 8) -> one chroma plane, quarter resolution.
        chroma = [spatial[:, :, i].transpose(1, 2, 0, 3)
                  .reshape(mb_rows * 8, mb_cols * 8) for i in (0, 1)]
        # qi 0..3 is (quadrant y, quadrant x) in that order.
        y = (spatial[:, :, 2:6].reshape(mb_cols, mb_rows, 2, 2, 8, 8)
             .transpose(1, 2, 4, 0, 3, 5)
             .reshape(mb_rows * 16, mb_cols * 16))

        luma = y[:height, :width] + 128.0
        cr, cb = (c.repeat(2, axis=0).repeat(2, axis=1)[:height, :width]
                  for c in chroma)
        planes = (luma + 1.402 * cr,
                  luma - 0.3437 * cb - 0.7143 * cr,
                  luma + 1.772 * cb)
        return (_np.stack(planes, axis=-1)
                .clip(0, 255).astype(_np.uint8).tobytes())

    # Fallback: same arithmetic, one block at a time.
    luma = [[0.0] * (mb_cols * 16) for _ in range(mb_rows * 16)]
    cb_p = [[0.0] * (mb_cols * 8) for _ in range(mb_rows * 8)]
    cr_p = [[0.0] * (mb_cols * 8) for _ in range(mb_rows * 8)]
    for index, coeffs in enumerate(blocks):
        mb, which = divmod(index, 6)
        mx, my = divmod(mb, mb_rows)
        block = idct_8x8(coeffs)
        if which < 2:
            plane = cr_p if which == 0 else cb_p
            for j in range(8):
                row = plane[my * 8 + j]
                for i in range(8):
                    row[mx * 8 + i] = block[j * 8 + i]
        else:
            qi = which - 2
            ox = mx * 16 + (qi & 1) * 8
            oy = my * 16 + (qi >> 1) * 8
            for j in range(8):
                row = luma[oy + j]
                for i in range(8):
                    row[ox + i] = block[j * 8 + i]

    out = bytearray(width * height * 3)
    pos = 0
    for y_i in range(height):
        crow, brow, rrow = cr_p[y_i >> 1], cb_p[y_i >> 1], luma[y_i]
        for x in range(width):
            luma_v = rrow[x] + 128.0
            cr_v, cb_v = crow[x >> 1], brow[x >> 1]
            out[pos] = _clamp8(luma_v + 1.402 * cr_v)
            out[pos + 1] = _clamp8(luma_v - 0.3437 * cb_v - 0.7143 * cr_v)
            out[pos + 2] = _clamp8(luma_v + 1.772 * cb_v)
            pos += 3
    return bytes(out)


def decode_frame(data: bytes, width: int, height: int) -> DecodedFrame:
    """Decode one reassembled STR frame to 8-bit RGB.

    `data` is the whole frame INCLUDING its 8-byte header — i.e. exactly
    what `str_stream.StrFrame.bitstream` returns — and `width`/`height` are
    the frame's own declared dimensions from the sector header.
    """
    header = parse_frame_header(data)
    if not header.looks_valid:
        raise MdecError(f"frame header magic is 0x{header.magic:04X}, "
                        f"expected 0x{MAGIC:04X} — not an MDEC frame")
    if header.version not in SUPPORTED_VERSIONS:
        raise MdecError(
            f"STR frame version {header.version} is not supported "
            f"(this decoder implements v{'/v'.join(map(str, SUPPORTED_VERSIONS))}; "
            f"v3 codes DC differentially and needs its own tables)")

    # Macroblocks are 16x16 and the frame is padded up to whole ones.
    mb_cols = (width + 15) // 16
    mb_rows = (height + 15) // 16
    bits = _BitReader(_swap16(data[HEADER_SIZE:]))

    # Entropy decode first, reconstruct after. Splitting the two lets the
    # IDCT run over every block of the frame at once, which is ~8x the
    # per-block form: a 1000-block frame is 2000 tiny 8x8 matrix products,
    # and at that size the per-call overhead dominates the arithmetic.
    coeffs_per_block = []
    codes = 0
    # COLUMN-major: the MDEC walks down a column of macroblocks, then right.
    for _mx in range(mb_cols):
        for _my in range(mb_rows):
            for _ in range(6):
                coeffs, used = _read_block(bits, header.q_scale)
                coeffs_per_block.append(coeffs)
                codes += used

    rgb = _reconstruct(coeffs_per_block, mb_cols, mb_rows, width, height)

    return DecodedFrame(width=width, height=height, rgb=rgb,
                        header=header, codes=codes,
                        blocks=len(coeffs_per_block),
                        bits_used=bits.pos,
                        bits_available=(len(data) - HEADER_SIZE) * 8)


#: The frame header's code count is an ALLOCATION size, not an exact count:
#: measured over 324 frames spanning SSSC, The Making of Lunar, Lunar 2 and
#: the Lunar 2 demo, it is always a multiple of 32, never below the number
#: of codes actually produced, and never more than 63 above it. Rounding it
#: to a multiple of 32 does NOT reproduce it (148/324), so the slack is the
#: encoder's own buffering and the honest invariant is the bound.
CODE_COUNT_SLACK = 64

#: Bits left unread at the end of a correct decode: the stream is padded out
#: to a word boundary. Measured range across the same 324 frames: 10..41.
TAIL_BITS_SLACK = 64


def check_frame(frame: DecodedFrame) -> list[str]:
    """-> list of invariant violations; empty means the decode is consistent.

    This is the falsifiable part, and it needs no reference decoder and no
    emulator capture — every bound below comes out of the file itself:

      * the geometry fixes how many 8x8 blocks the frame must contain;
      * the header declares an upper bound on the MDEC codes it expands to;
      * the bitstream must be consumed to within its trailing padding.

    The last one is the sharp one. A single wrong VLC entry, a swapped bit
    order or a wrong block order desyncs the stream, and a desynced stream
    does not land within a word of the end after a thousand blocks — it
    either runs off the end or leaves hundreds of bits unread.
    """
    problems = []
    expected_blocks = ((frame.width + 15) // 16) * ((frame.height + 15) // 16) * 6
    if frame.blocks != expected_blocks:
        problems.append(f"decoded {frame.blocks} blocks, geometry needs "
                        f"{expected_blocks}")

    slack = frame.header.mdec_codes - frame.codes
    if not 0 <= slack < CODE_COUNT_SLACK:
        problems.append(f"produced {frame.codes} MDEC codes against a header "
                        f"bound of {frame.header.mdec_codes} (slack {slack}, "
                        f"expected 0..{CODE_COUNT_SLACK - 1})")
    if frame.header.mdec_codes % 32:
        problems.append(f"header code count {frame.header.mdec_codes} is not "
                        f"a multiple of 32")

    tail = frame.bits_available - frame.bits_used
    if not 0 <= tail < TAIL_BITS_SLACK:
        problems.append(f"consumed {frame.bits_used} of "
                        f"{frame.bits_available} bits, leaving {tail} "
                        f"(expected 0..{TAIL_BITS_SLACK - 1} of padding)")
    return problems
