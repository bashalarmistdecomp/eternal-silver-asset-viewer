"""PS1 16-bit word inflate decompressor.

Reimplementation of inflate_block_dynamic (0x80021DD8) from the Lunar SSSC game engine.
This is a standard DEFLATE algorithm (RFC 1951) but reads the input
bitstream as 16-bit LE words instead of individual bytes.

This makes it incompatible with standard zlib — we must reimplement
the bit reader and Huffman table builder from the decompiled source.
"""

import hashlib
import struct
import threading
from collections import OrderedDict

#: The latest streams inflated, by the sha1 of their bytes, up to this many
#: bytes of output: a map's pages, a face file or the string block is read
#: again by each tab that shows it, and on each disc of a game that carries
#: it, and is inflated once while it is kept (`decompress`).
KEEP_BYTES = 32 << 20
#: The most a stream can inflate to: the console's 2 MB of main memory,
#: which the game inflates into. Past its end the bit reader reads zeros,
#: as the game's reads whatever follows; a stream that is not one can turn
#: those zeros into copies without end, so more than this is refused.
MAX_OUTPUT = 2 << 20
_kept: OrderedDict[bytes, bytes] = OrderedDict()
_kept_bytes = 0
_kept_lock = threading.Lock()


def decompress(data: bytes) -> bytes:
    """Decompress data using the PS1 16-bit word inflate algorithm.

    Args:
        data: Compressed input bytes (must be 16-bit aligned).

    Returns:
        Decompressed bytes: `inflate`'s, kept for the same input bytes
        (KEEP_BYTES).
    """
    global _kept_bytes
    key = hashlib.sha1(data).digest()
    with _kept_lock:
        out = _kept.get(key)
        if out is not None:
            _kept.move_to_end(key)
            return out
    out = inflate(data)
    with _kept_lock:
        if key not in _kept and len(out) <= KEEP_BYTES:
            _kept[key] = out
            _kept_bytes += len(out)
            while _kept_bytes > KEEP_BYTES:
                _key, gone = _kept.popitem(last=False)
                _kept_bytes -= len(gone)
    return out


def inflate(data: bytes) -> bytes:
    """`decompress`, read from the bytes every time."""
    ctx = _Context(data)

    max_blocks = 100  # Safety limit
    for _block in range(max_blocks):
        bfinal = ctx.read_bits(1)
        btype = ctx.read_bits(2)

        if btype == 3:
            # Invalid block type — might be corrupt or misaligned
            break

        if btype == 0:
            # Stored block (no compression)
            ctx.align_to_word()
            length = ctx.read_bits(16)
            ctx.read_bits(16)               # NLEN, LEN's complement: unchecked
            for _ in range(length):
                ctx.output_byte(ctx.read_bits(8))

        elif btype == 1:
            # Fixed Huffman codes
            lit_tree, dist_tree = _fixed_trees()
            _inflate_codes(ctx, lit_tree, dist_tree)

        elif btype == 2:
            # Dynamic Huffman codes
            hlit = ctx.read_bits(5) + 257
            hdist = ctx.read_bits(5) + 1
            hclen = ctx.read_bits(4) + 4

            # Read code length code lengths
            cl_order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
            cl_lengths = [0] * 19
            for i in range(hclen):
                cl_lengths[cl_order[i]] = ctx.read_bits(3)

            cl_tree = _build_huffman_tree(cl_lengths)

            # Read literal/length and distance code lengths
            all_lengths = []
            while len(all_lengths) < hlit + hdist:
                sym = _decode_symbol(ctx, cl_tree)
                if sym < 16:
                    all_lengths.append(sym)
                elif sym == 16:
                    repeat = ctx.read_bits(2) + 3
                    last = all_lengths[-1] if all_lengths else 0
                    all_lengths.extend([last] * repeat)
                elif sym == 17:
                    repeat = ctx.read_bits(3) + 3
                    all_lengths.extend([0] * repeat)
                elif sym == 18:
                    repeat = ctx.read_bits(7) + 11
                    all_lengths.extend([0] * repeat)

            lit_lengths = all_lengths[:hlit]
            dist_lengths = all_lengths[hlit:hlit + hdist]

            # Check if this is a sentinel block (all zeros = no codes)
            if not any(lit_lengths):
                # Empty block — no data. The game loops and retries.
                continue

            lit_tree = _build_huffman_tree(lit_lengths)
            dist_tree = _build_huffman_tree(dist_lengths) if any(dist_lengths) else _fixed_trees()[1]

            _inflate_codes(ctx, lit_tree, dist_tree)

        else:
            raise ValueError(f"Invalid block type: {btype}")

        if len(ctx.output) > MAX_OUTPUT:
            raise ValueError(f"inflate16: over {MAX_OUTPUT} bytes out: not a stream")
        if bfinal and len(ctx.output) > 0:
            break

        # If bfinal but no output, keep trying (sentinel block pattern)
        if bfinal and len(ctx.output) == 0 and ctx.pos < len(ctx.data) - 2:
            continue

        if bfinal:
            break

    return bytes(ctx.output)


class _Context:
    """Bit reader that reads 16-bit LE words from the input stream."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0           # Byte position in input
        self.bits = 0          # Bit buffer
        self.bits_left = 0     # Number of valid bits in buffer
        # Everything written stays in `output`, so it is also the game's
        # 32 KB ring buffer: a distance reaches at most 32768 bytes back.
        self.output = bytearray()

    def read_bits(self, n: int) -> int:
        """Read n bits from the input stream (LSB first, 16-bit word refill)."""
        while self.bits_left < n:
            if self.pos + 2 <= len(self.data):
                word = struct.unpack_from("<H", self.data, self.pos)[0]
                self.pos += 2
            else:
                word = 0
            self.bits |= word << self.bits_left
            self.bits_left += 16

        result = self.bits & ((1 << n) - 1)
        self.bits >>= n
        self.bits_left -= n
        return result

    def align_to_word(self):
        """Discard remaining bits to align to the next 16-bit word boundary."""
        self.bits = 0
        self.bits_left = 0

    def output_byte(self, b: int):
        """Write a byte to the output (and so to the ring buffer)."""
        self.output.append(b & 0xFF)

    def copy_from_window(self, distance: int, length: int):
        """Copy `length` bytes from `distance` back in the ring buffer.

        The ring starts as 32 KB of zeros, so a byte from before the
        stream's start is 0; any other is the output's, `distance` back
        from where it is written (a copy may run into its own bytes)."""
        out = self.output
        start = len(out) - distance
        if start >= 0 and distance >= length:
            out += out[start:start + length]
        elif start >= 0:
            run = out[start:]
            out += (run * (length // distance + 1))[:length]
        else:
            for j in range(length):
                at = start + j
                out.append(out[at] if at >= 0 else 0)


def _inflate_codes(ctx: _Context, lit_tree, dist_tree):
    """Decompress a block using the given Huffman trees."""
    LENGTH_BASES = [
        3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
        35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258,
    ]
    LENGTH_EXTRA = [
        0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
        3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
    ]
    DIST_BASES = [
        1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
        257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
        8193, 12289, 16385, 24577,
    ]
    DIST_EXTRA = [
        0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
        7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
    ]

    # The loop keeps the bit reader in locals: the same reads, in the same
    # order, as `_decode_symbol` and `_Context.read_bits`.
    data, size, out = ctx.data, len(ctx.data), ctx.output
    bits, left, pos = ctx.bits, ctx.bits_left, ctx.pos
    lookup, lit_len = lit_tree
    lit_mask = (1 << lit_len) - 1
    dist_lookup, dist_len = dist_tree if dist_tree else ((), 0)
    dist_mask = (1 << dist_len) - 1
    copy = ctx.copy_from_window

    while True:
        if len(out) > MAX_OUTPUT:
            raise ValueError(f"inflate16: over {MAX_OUTPUT} bytes out: not a stream")
        while left < lit_len:
            if pos + 2 <= size:
                bits |= (data[pos] | data[pos + 1] << 8) << left
                pos += 2
            left += 16
        sym, n = lookup[bits & lit_mask]
        bits >>= n
        left -= n

        if sym < 256:
            out.append(sym & 0xFF)
        elif sym == 256:
            break  # End of block
        else:
            # Length/distance pair
            length_idx = sym - 257
            if length_idx >= len(LENGTH_BASES):
                raise ValueError(f"inflate16: length symbol {sym}: not a stream")
            extra = LENGTH_EXTRA[length_idx]
            while left < extra:
                if pos + 2 <= size:
                    bits |= (data[pos] | data[pos + 1] << 8) << left
                    pos += 2
                left += 16
            length = LENGTH_BASES[length_idx] + (bits & ((1 << extra) - 1))
            bits >>= extra
            left -= extra

            dist_sym = 0
            if dist_tree:
                while left < dist_len:
                    if pos + 2 <= size:
                        bits |= (data[pos] | data[pos + 1] << 8) << left
                        pos += 2
                    left += 16
                dist_sym, n = dist_lookup[bits & dist_mask]
                bits >>= n
                left -= n
            if dist_sym >= len(DIST_BASES):
                raise ValueError(f"inflate16: distance symbol {dist_sym}: not a stream")
            extra = DIST_EXTRA[dist_sym]
            while left < extra:
                if pos + 2 <= size:
                    bits |= (data[pos] | data[pos + 1] << 8) << left
                    pos += 2
                left += 16
            distance = DIST_BASES[dist_sym] + (bits & ((1 << extra) - 1))
            bits >>= extra
            left -= extra

            start = len(out) - distance
            if start >= 0 and distance >= length:
                out += out[start:start + length]       # copy_from_window's first case
            else:
                copy(distance, length)
    ctx.bits, ctx.bits_left, ctx.pos = bits, left, pos


def _decode_symbol(ctx: _Context, tree) -> int:
    """Decode one Huffman symbol using table lookup."""
    # tree is now a (bits, values, max_len) tuple from _build_huffman_tree
    lookup, max_len = tree
    # Peek max_len bits
    while ctx.bits_left < max_len:
        if ctx.pos + 2 <= len(ctx.data):
            word = struct.unpack_from("<H", ctx.data, ctx.pos)[0]
            ctx.pos += 2
        else:
            word = 0
        ctx.bits |= word << ctx.bits_left
        ctx.bits_left += 16

    index = ctx.bits & ((1 << max_len) - 1)
    sym, length = lookup[index]
    ctx.bits >>= length
    ctx.bits_left -= length
    return sym


def _build_huffman_tree(lengths: list[int]):
    """Build a fast lookup table from Huffman code lengths.

    Returns (lookup_table, max_code_length) where lookup_table[i] = (symbol, code_length).
    The table is indexed by the reversed (LSB-first) bit pattern.
    """
    max_len = max(lengths) if lengths else 0
    if max_len == 0:
        return ([( 0, 1)] * 2, 1)

    # Clamp to reasonable size
    if max_len > 15:
        max_len = 15

    # Count codes of each length
    bl_count = [0] * (max_len + 1)
    for ln in lengths:
        if 0 < ln <= max_len:
            bl_count[ln] += 1

    # Compute first code for each length (standard deflate canonical)
    code = 0
    next_code = [0] * (max_len + 1)
    for bits in range(1, max_len + 1):
        code = (code + bl_count[bits - 1]) << 1
        next_code[bits] = code

    # Build lookup table: for each possible bit pattern (up to max_len bits),
    # store (symbol, actual_code_length)
    table_size = 1 << max_len
    lookup = [(0, max_len)] * table_size  # default

    for sym, ln in enumerate(lengths):
        if ln == 0 or ln > max_len:
            continue
        c = next_code[ln]
        next_code[ln] += 1

        # Reverse the code's low `ln` bits (deflate reads LSB-first)
        reversed_code = int(format(c & ((1 << ln) - 1), f"0{ln}b")[::-1], 2)

        # Fill all table entries that match this code in the low `ln` bits
        step = 1 << ln
        lookup[reversed_code::step] = [(sym, ln)] * len(range(reversed_code, table_size, step))

    return (lookup, max_len)


_fixed: tuple | None = None


def _fixed_trees():
    """(literal tree, distance tree) of the fixed codes, built once (a
    tree is only read)."""
    global _fixed
    if _fixed is None:
        _fixed = (_build_fixed_literal_tree(), _build_fixed_distance_tree())
    return _fixed


def _build_fixed_literal_tree():
    """Build the fixed Huffman tree for literal/length codes."""
    lengths = []
    for i in range(288):
        if i < 144:
            lengths.append(8)
        elif i < 256:
            lengths.append(9)
        elif i < 280:
            lengths.append(7)
        else:
            lengths.append(8)
    return _build_huffman_tree(lengths)


def _build_fixed_distance_tree():
    """Build the fixed Huffman tree for distance codes."""
    return _build_huffman_tree([5] * 32)
