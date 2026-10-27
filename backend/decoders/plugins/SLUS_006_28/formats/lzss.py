"""LZSS decompressor for Lunar SSSC PS1 executable.

Reverse-engineered from SLUS_006.28 at 0x80100000.
The PS1 executable contains ~1KB bootstrap + ~347KB LZSS-compressed game engine.
Decompresses to ~690KB of MIPS code + data.

Algorithm:
  - Reads a control byte, processes 8 bits per control byte (LSB first)
  - Bit=1: LITERAL — copy 1 byte from input to output
  - Bit=0 + Bit=1: SHORT reference — 1 byte: top 2 bits = (length-2), bottom 6 bits = negative offset
  - Bit=0 + Bit=0: LONG reference — 2 bytes big-endian: top 4 bits = length, bottom 12 bits = negative offset
    - If length=0: read 1 more byte as length (+2). If that byte=0: END OF STREAM.
"""


def decompress(src: bytes) -> bytes:
    """Decompress LZSS data. Returns decompressed bytes.

    The loop keeps the control bits in locals and copies a reference by
    slices: the same reads, in the same order, as taking a bit at a time
    and copying a byte at a time. A reference that runs into the bytes it
    is writing repeats them; one reaching behind the output's start reads
    zeros."""
    output = bytearray()
    size = len(src)
    si = 0
    bits_left = 0
    flags = 0

    while si < size:
        if not bits_left:
            flags = src[si]
            si += 1
            bits_left = 8
        bit = flags & 1
        flags >>= 1
        bits_left -= 1
        if bit:
            # LITERAL
            output.append(src[si])
            si += 1
            continue
        if not bits_left:
            flags = src[si]
            si += 1
            bits_left = 8
        bit = flags & 1
        flags >>= 1
        bits_left -= 1
        if bit:
            # SHORT reference: 1 byte, offset -64..-1
            b = src[si]
            si += 1
            length = (b >> 6) + 2
            distance = 0x40 - (b & 0x3F)
        else:
            # LONG reference: 2 bytes big-endian, offset -4096..-1
            hi = src[si]
            si += 1
            lo = src[si]
            si += 1
            word = (hi << 8) | lo
            length = word >> 12
            distance = 0x1000 - (word & 0xFFF)
            if length == 0:
                length = src[si]
                si += 1
                if length == 0:
                    break  # END OF STREAM
            length += 2

        start = len(output) - distance
        if start < 0:
            for at in range(start, start + length):
                output.append(output[at] if at >= 0 else 0)
        elif distance >= length:
            output += output[start:start + length]
        else:
            output += (output[start:] * (length // distance + 1))[:length]

    return bytes(output)


def decompress_exe(exe_path: str, out_path: str | None = None) -> bytes:
    """Decompress the Lunar SSSC PS1 executable.

    The compressed data starts at file offset 0x1000 (RAM 0x80100800).
    Decompresses to ~690KB including a PS-X EXE header + game engine code.
    """
    with open(exe_path, "rb") as f:
        exe = f.read()

    compressed = exe[0x1000:]
    result = decompress(compressed)

    if out_path:
        with open(out_path, "wb") as f:
            f.write(result)

    return result
