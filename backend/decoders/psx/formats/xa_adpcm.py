"""CD-XA ADPCM: the audio interleaved into a PS1 STR movie (and .XA files).

`str_stream` reassembles the video sectors of a movie and steps over
everything else. The "everything else" is this: CD-XA Form 2 sectors
carrying ADPCM audio, interleaved with the video so a double-speed drive
delivers both in real time. Decoding them is what turns a silent picture
into a movie.

**These sectors do not survive normal file extraction.** A Form 2 sector
carries 2324 bytes of user data; an ISO extractor reads the 2048 bytes of
a Form 1 sector, so every audio sector in an extracted `.STR` is truncated
and its subheader — which is where the sample rate, channel count and bit
depth live — is gone entirely. Audio therefore has to be read from the
DISC IMAGE, at raw 2352-byte sectors. `iter_xa_sectors` takes raw sectors
for exactly that reason.

    raw sector      2352 B: 12 sync + 4 header + 8 subheader + 2324 data + 4 EDC
    subheader       file, channel, submode (Form 1 vs 2), coding info
    coding info     mono/stereo, 37800/18900 Hz, 4/8-bit
    user data       18 sound groups x 128 B
    sound group     16 B of parameters (each stored twice) + 112 B of samples
    block           28 samples, one shift/filter parameter
    filter          out = s + (K0[f]*prev1 + K1[f]*prev2 + 32) >> 6

Spec: docs/spec/formats/xa-adpcm.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator

RAW_SECTOR_SIZE = 2352
SUBHEADER_OFFSET = 16
USER_DATA_OFFSET = 24
FORM2_DATA_SIZE = 2324

SOUND_GROUPS = 18
GROUP_SIZE = 128
GROUP_HEADER = 16
BLOCK_SAMPLES = 28

#: ADPCM filter coefficients, pre-scaled by 64 (the shift the decoder applies).
#: Four filters; index with the top nibble of a block's sound parameter.
FILTER_POS = (0, 60, 115, 98)
FILTER_NEG = (0, 0, -52, -55)


class XaError(ValueError):
    """The sector is not decodable CD-XA ADPCM."""


@dataclass(frozen=True)
class Subheader:
    """A raw sector's 8-byte subheader, as CD-XA defines it."""

    file: int
    channel: int
    submode: int
    coding: int

    @property
    def is_form2(self) -> bool:
        """Form 2 = 2324 bytes of user data, no ECC. Audio rides in these."""
        return bool(self.submode & 0x20)

    @property
    def is_audio(self) -> bool:
        return bool(self.submode & 0x04)

    @property
    def is_data(self) -> bool:
        return bool(self.submode & 0x08)

    @property
    def is_eof(self) -> bool:
        return bool(self.submode & 0x80)

    # -- coding info -------------------------------------------------------

    @property
    def stereo(self) -> bool:
        return bool(self.coding & 0x03)

    @property
    def channels(self) -> int:
        return 2 if self.stereo else 1

    @property
    def sample_rate(self) -> int:
        return 18900 if (self.coding & 0x0C) else 37800

    @property
    def bits_per_sample(self) -> int:
        return 8 if (self.coding & 0x30) else 4

    @property
    def emphasis(self) -> bool:
        return bool(self.coding & 0x40)

    def describe(self) -> str:
        return (f"{'stereo' if self.stereo else 'mono'} "
                f"{self.sample_rate} Hz {self.bits_per_sample}-bit")


@dataclass
class XaFormat:
    """The audio format one stream is in."""

    channels: int
    sample_rate: int
    bits_per_sample: int

    @classmethod
    def of(cls, sub: Subheader) -> "XaFormat":
        return cls(sub.channels, sub.sample_rate, sub.bits_per_sample)

    def describe(self) -> str:
        return (f"{'stereo' if self.channels == 2 else 'mono'} "
                f"{self.sample_rate} Hz {self.bits_per_sample}-bit")


def parse_subheader(sector: bytes, offset: int = 0) -> Subheader:
    """Decode the 8-byte subheader of one raw 2352-byte sector.

    The subheader is stored TWICE, back to back, for error resilience; the
    first copy is used and the second ignored, which is what the hardware
    does when they agree.
    """
    at = offset + SUBHEADER_OFFSET
    if len(sector) < at + 4:
        raise XaError(f"sector too short for a subheader ({len(sector)} bytes)")
    file_no, channel, submode, coding = sector[at:at + 4]
    return Subheader(file_no, channel, submode, coding)


def iter_xa_sectors(data: bytes, channel: int | None = None
                    ) -> Iterator[tuple[int, Subheader]]:
    """Yield (offset, subheader) for the Form 2 AUDIO sectors in raw data.

    `channel` filters to one XA channel — a disc can interleave several
    audio streams (languages, or per-scene tracks) in one file, and mixing
    them produces stutter rather than an error.
    """
    for off in range(0, len(data) - RAW_SECTOR_SIZE + 1, RAW_SECTOR_SIZE):
        sub = parse_subheader(data, off)
        if not (sub.is_form2 and sub.is_audio):
            continue
        if channel is not None and sub.channel != channel:
            continue
        yield off, sub


class _AdpcmState:
    """Per-channel filter history. ADPCM is recursive: it must persist
    across blocks, groups AND sectors, or every sector boundary clicks."""

    __slots__ = ("prev1", "prev2")

    def __init__(self):
        self.prev1 = 0
        self.prev2 = 0


def _clamp16(value: int) -> int:
    if value < -32768:
        return -32768
    if value > 32767:
        return 32767
    return value


def _decode_block(data: memoryview, group_off: int, block: int,
                  parameter: int, bits: int, state: _AdpcmState) -> list[int]:
    """One block of 28 samples out of a 128-byte sound group."""
    shift = parameter & 0x0F
    filt = (parameter >> 4) & 0x03
    pos, neg = FILTER_POS[filt], FILTER_NEG[filt]

    # A shift above 12 is not meaningful; the hardware treats it as 9.
    if shift > 12:
        shift = 9

    out = []
    base = group_off + GROUP_HEADER
    for i in range(BLOCK_SAMPLES):
        if bits == 4:
            # block b is the LOW nibble (even b) or HIGH nibble (odd b) of
            # lane b >> 1: the blocks run in time order lane0-low,
            # lane0-high, lane1-low, ...
            byte = data[base + i * 4 + (block >> 1)]
            nibble = (byte >> 4) if (block & 1) else (byte & 0x0F)
            raw = (nibble << 12) & 0xFFFF
        else:
            byte = data[base + i * 4 + block]
            raw = (byte << 8) & 0xFFFF
        if raw & 0x8000:
            raw -= 0x10000
        sample = raw >> shift

        sample += (state.prev1 * pos + state.prev2 * neg + 32) >> 6
        sample = _clamp16(sample)
        state.prev2 = state.prev1
        state.prev1 = sample
        out.append(sample)
    return out


def decode_sector(sector: bytes, fmt: XaFormat,
                  states: list[_AdpcmState]) -> bytes:
    """One Form 2 sector -> interleaved signed 16-bit little-endian PCM.

    `states` is one `_AdpcmState` per channel and is MUTATED: the filter
    history has to carry across sectors. Call `new_states()` once per
    stream, not once per sector.
    """
    data = memoryview(sector)[USER_DATA_OFFSET:USER_DATA_OFFSET + FORM2_DATA_SIZE]
    blocks = 8 if fmt.bits_per_sample == 4 else 4
    samples: list[int] = []

    for group in range(SOUND_GROUPS):
        off = group * GROUP_SIZE
        if off + GROUP_SIZE > len(data):
            break
        if fmt.channels == 1:
            for block in range(blocks):
                samples.extend(_decode_block(
                    data, off, block, data[off + _param_index(block, blocks)],
                    fmt.bits_per_sample, states[0]))
        else:
            # Blocks pair up L, R — decode both and interleave the 28 frames.
            for pair in range(blocks // 2):
                left = _decode_block(
                    data, off, pair * 2,
                    data[off + _param_index(pair * 2, blocks)],
                    fmt.bits_per_sample, states[0])
                right = _decode_block(
                    data, off, pair * 2 + 1,
                    data[off + _param_index(pair * 2 + 1, blocks)],
                    fmt.bits_per_sample, states[1])
                for l, r in zip(left, right):
                    samples.append(l)
                    samples.append(r)

    return struct.pack(f"<{len(samples)}h", *samples)


#: Where each block's sound parameter sits in the 16-byte group header, and
#: which nibble of which data byte the block's samples are.
#:
#: The eight blocks of a group play in TIME order 0..7. Block b takes its
#: parameter from header byte 4 + b, and its 28 samples are the LOW (even b)
#: or HIGH (odd b) nibble of data byte `16 + (b >> 1) + 4*i`, i = 0..27 — so
#: the data is interleaved in lanes of two blocks, and the filter history
#: runs through the blocks in time order. This is ffmpeg's adpcm_xa (checked
#: sample for sample against it on the _AUDIO.XA voice clips). Bytes 0..3
#: and 12..15 are redundant copies of 4..7 and 8..11 (measured over 4,018
#: non-silent groups of SSSC's _B000.STR: bytes 0..3 == 4..7 in 100%).
#:
#: HISTORY, because it cost two wrong turns: the first table here took
#: params (0,1,2,3,8,9,10,11) and nibble = block >> 2, which passed the
#: copy measurement but read the blocks out of time order and with other
#: blocks' gains — heard as crushed voices; a first "fix" changed only the
#: parameter bytes and was still wrong. Ranking layouts by loudness jitter
#: or clipping is not evidence; an independent decoder is.
#:
#: 8-bit streams have four blocks and the first four parameters (4..7).
#: None of the discs here ship one, so that half is unverified.
_PARAM_INDEX_4BIT = (4, 5, 6, 7, 8, 9, 10, 11)


def _param_index(block: int, blocks: int) -> int:
    if blocks == 8:
        return _PARAM_INDEX_4BIT[block]
    return 4 + block


def new_states(fmt: XaFormat) -> list[_AdpcmState]:
    return [_AdpcmState() for _ in range(fmt.channels)]


def decode_stream(data: bytes, channel: int | None = None
                  ) -> tuple[bytes, XaFormat | None]:
    """Decode every audio sector in raw disc data -> (PCM, format).

    Returns `(b"", None)` when there are no audio sectors, which is the
    normal answer for a video-only stream rather than an error.
    """
    fmt = None
    states: list[_AdpcmState] = []
    chunks = []
    for off, sub in iter_xa_sectors(data, channel):
        if fmt is None:
            fmt = XaFormat.of(sub)
            states = new_states(fmt)
        chunks.append(decode_sector(data[off:off + RAW_SECTOR_SIZE],
                                    fmt, states))
    return b"".join(chunks), fmt


def samples_per_sector(fmt: XaFormat) -> int:
    """PCM frames one Form 2 sector yields — the audio clock's tick.

    18 groups x (8 or 4) blocks x 28 samples, divided by the channel count
    because stereo spends two samples per frame.
    """
    blocks = 8 if fmt.bits_per_sample == 4 else 4
    return SOUND_GROUPS * blocks * BLOCK_SAMPLES // fmt.channels


def wav_header(fmt: XaFormat, pcm_bytes: int) -> bytes:
    """A RIFF/WAVE header for decoded PCM (16-bit, `fmt.channels`)."""
    block_align = fmt.channels * 2
    return (b"RIFF" + struct.pack("<I", 36 + pcm_bytes) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, fmt.channels, fmt.sample_rate,
                          fmt.sample_rate * block_align, block_align, 16)
            + b"data" + struct.pack("<I", pcm_bytes))


def to_wav(pcm: bytes, fmt: XaFormat) -> bytes:
    return wav_header(fmt, len(pcm)) + pcm
