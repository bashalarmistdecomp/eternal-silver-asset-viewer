"""Facts about decoded audio the server needs. Playback is the app's own."""

from __future__ import annotations

import struct


def wav_duration(wav: bytes) -> float:
    """Seconds of audio in a RIFF/WAVE blob, from its own header.

    Parsed rather than assumed, because the viewer plays WAVs at three
    different rates (per-tone sample rates, the 44.1 kHz render, CD audio).
    """
    if len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        return 0.0
    pos, rate, block = 12, 0, 0
    while pos + 8 <= len(wav):
        cid = wav[pos:pos + 4]
        (size,) = struct.unpack_from("<I", wav, pos + 4)
        body = pos + 8
        if cid == b"fmt " and size >= 16:
            _fmt, ch, rate, _bps, block, bits = struct.unpack_from(
                "<HHIIHH", wav, body)
            block = block or max(1, ch * bits // 8)
        elif cid == b"data":
            return size / (rate * block) if rate and block else 0.0
        pos = body + size + (size & 1)
    return 0.0
