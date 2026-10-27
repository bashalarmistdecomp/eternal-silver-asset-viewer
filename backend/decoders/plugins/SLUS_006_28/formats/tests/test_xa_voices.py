"""Tier 1 for the voices' table (formats.xa_voices) — a made-up program
image and made-up sectors, no game data.

What this CAN catch: xa_voice_get's arithmetic as the module transcribes
it (the channel and start, an end from the next entry on the same channel
or from g_XaChannelEnds, 3 or 4 units off by D_800AF62C), the voices'
range, and that the sound keeps only file 1's audio of the voice's
channel, with one filter history across its sectors.

What it CANNOT catch: that the tables are where the module reads them, or
that the drive plays what `decode` keeps — the on-disc tests measure that.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
from decoders.plugins.SLUS_006_28.records.programs import EXE_BASE
from decoders.psx.formats import xa_adpcm as X


def image(entries: dict[int, int], ends: dict[int, int], three: set[int] = frozenset()) -> bytes:
    """A program image from EXE_BASE holding g_XaVoices, g_XaChannelEnds and
    D_800AF62C: `entries` by voice (the rest 0), `ends` by channel, the
    voices in `three` taking 3 units off their end."""
    img = bytearray(xv.END_LESS_ADDR - EXE_BASE + 0x100)
    for n, v in entries.items():
        struct.pack_into("<H", img, xv.VOICES_ADDR - EXE_BASE + 2 * n, v)
    for c, e in ends.items():
        struct.pack_into("<H", img, xv.CHANNEL_ENDS_ADDR - EXE_BASE + 2 * c, e)
    for n in three:
        img[xv.END_LESS_ADDR - EXE_BASE + n] = 1
    return bytes(img)


#: voices 1 and 2 on channel 2, voice 3 on channel 5, voice 4 on channel 2
IMG = image({0: 0xFFFF, 1: 0x2010, 2: 0x2030, 3: 0x5008, 4: 0x2050},
            {2: 0x070, 5: 0x020}, three={2})


def test_the_end_is_the_next_entry_of_the_same_channel_less_four():
    v = xv.voice(IMG, 1)
    assert (v.channel, v.start, v.end, v.less, v.by_next) == (2, 0x10 << 4, (0x30 - 4) << 4, 4, True)
    assert v.sectors == (0x30 - 4 - 0x10) * 16 and v.channel_sectors == 0x30 - 4 - 0x10
    assert v.seconds == pytest.approx(v.sectors / 150)


def test_a_marked_voice_takes_three_off():
    v = xv.voice(IMG, 2)
    # the next entry is channel 5's: the end comes from g_XaChannelEnds[2]
    assert (v.end, v.less, v.by_next) == ((0x070 - 3) << 4, 3, False)


def test_a_voice_whose_next_entry_is_another_channel_ends_at_its_channel_end():
    v = xv.voice(IMG, 3)
    assert (v.channel, v.start, v.end, v.by_next) == (5, 0x8 << 4, (0x020 - 4) << 4, False)


def test_the_voices_run_from_one_to_the_entry_before_the_last():
    assert (xv.FIRST, xv.LAST) == (1, 103)
    assert [v.number for v in xv.voices(IMG)] == list(range(1, 104))
    for n in (0, 104):
        with pytest.raises(ValueError):
            xv.voice(IMG, n)


def test_the_us_program_is_proven_by_its_own_function():
    assert xv.proof(IMG) == xv.VOICE_GET


# -- the sound ---------------------------------------------------------------

def _group(par: int, fill: int) -> bytes:
    head = bytes([par]) * 16
    return head + bytes([fill]) * (X.GROUP_SIZE - X.GROUP_HEADER)


def sector(channel: int, file_no: int = 1, submode: int = 0x64, fill: int = 0x11,
           par: int = 0x10) -> bytes:
    sub = bytes([file_no, channel, submode, 0x00]) * 2      # coding 0: mono 37800 Hz 4-bit
    data = (_group(par, fill) * X.SOUND_GROUPS).ljust(X.FORM2_DATA_SIZE, b"\x00")
    return b"\x00" * 16 + sub + data[:X.FORM2_DATA_SIZE] + b"\x00" * 4


V = xv.Voice(1, 2, 0, 16, 0x2000, 4, True)


def test_decode_keeps_only_file_one_audio_of_its_channel():
    mine = [sector(2, fill=0x12), sector(2, fill=0x34, par=0x21)]
    raw = (mine[0] + sector(3) + sector(2, file_no=2) + sector(2, submode=0x08)
           + mine[1] + sector(2, submode=0x00))
    pcm, fmt = xv.decode(raw, V)
    assert fmt is not None and (fmt.channels, fmt.sample_rate, fmt.bits_per_sample) == (1, 37800, 4)
    states = X.new_states(fmt)
    want = b"".join(X.decode_sector(s, fmt, states) for s in mine)
    assert pcm == want
    assert len(pcm) == 2 * 2 * X.samples_per_sector(fmt)


def test_a_span_with_none_of_its_audio_gives_no_wav():
    assert xv.decode(sector(3) + sector(2, file_no=2), V) == (b"", None)
    assert xv.wav(sector(3), V) == b""
    got = xv.wav(sector(2), V)
    assert got[:4] == b"RIFF" and got[8:12] == b"WAVE"
