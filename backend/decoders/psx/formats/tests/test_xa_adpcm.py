"""Tier-1 tests for CD-XA ADPCM — synthetic sectors only.

The load-bearing ones are `test_block_b_reads_parameter_byte_4_plus_b` and
`test_blocks_run_in_lane_order_low_nibble_first`. Reading the wrong header
bytes or nibble order is a silent corruption rather than an error, and it
shipped twice (see the decoder's comment): the layout is ffmpeg's adpcm_xa,
and the voice clips were checked sample for sample against ffmpeg itself.
"""

import struct

import pytest

from decoders.psx.formats import xa_adpcm as X


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _group(params, fill=0x11):
    """One 128-byte sound group. `params` is 8 bytes, blocks 0..7.

    Block b takes byte 4 + b, with bytes 0..3 copying 4..7 and 12..15
    copying 8..11.
    """
    head = bytearray(16)
    for blk, par in enumerate(params):
        head[4 + blk] = par
    head[0:4] = head[4:8]
    head[12:16] = head[8:12]
    return bytes(head) + bytes([fill]) * 112


def _sector(groups, submode=0x24, coding=0x00, channel=1, file_no=1):
    sub = bytes([file_no, channel, submode, coding]) * 2
    data = b"".join(groups).ljust(X.FORM2_DATA_SIZE, b"\x00")
    return b"\x00" * 16 + sub + data[:X.FORM2_DATA_SIZE] + b"\x00" * 4


def _samples(pcm):
    return struct.unpack(f"<{len(pcm) // 2}h", pcm)


# ---------------------------------------------------------------------------
# Subheader
# ---------------------------------------------------------------------------

def test_subheader_identifies_a_form2_audio_sector():
    sub = X.parse_subheader(_sector([_group([0] * 8)]))
    assert sub.is_form2 and sub.is_audio
    assert (sub.file, sub.channel) == (1, 1)


def test_form1_sector_is_not_audio():
    sub = X.parse_subheader(_sector([_group([0] * 8)], submode=0x08))
    assert not sub.is_form2 and sub.is_data


@pytest.mark.parametrize("coding,channels,rate,bits", [
    (0x00, 1, 37800, 4),
    (0x01, 2, 37800, 4),
    (0x04, 1, 18900, 4),
    (0x10, 1, 37800, 8),
    (0x05, 2, 18900, 4),
])
def test_coding_info_decodes(coding, channels, rate, bits):
    sub = X.parse_subheader(_sector([_group([0] * 8)], coding=coding))
    assert (sub.channels, sub.sample_rate, sub.bits_per_sample) == (
        channels, rate, bits)


def test_short_sector_is_an_error():
    with pytest.raises(X.XaError):
        X.parse_subheader(b"\x00" * 8)


# ---------------------------------------------------------------------------
# Sector selection
# ---------------------------------------------------------------------------

def test_iter_skips_non_audio_sectors():
    data = (_sector([_group([0] * 8)], submode=0x08)
            + _sector([_group([0] * 8)])
            + _sector([_group([0] * 8)], submode=0x08))
    assert [off for off, _ in X.iter_xa_sectors(data)] == [X.RAW_SECTOR_SIZE]


def test_iter_filters_by_channel():
    data = (_sector([_group([0] * 8)], channel=1)
            + _sector([_group([0] * 8)], channel=2))
    assert len(list(X.iter_xa_sectors(data, channel=2))) == 1
    assert len(list(X.iter_xa_sectors(data))) == 2


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def test_silence_decodes_to_zero():
    """Shift 12, filter 0, all-zero nibbles: the movie's lead-in."""
    sector = _sector([_group([0x0C] * 8, fill=0x00)] * X.SOUND_GROUPS)
    fmt = X.XaFormat(1, 37800, 4)
    pcm = X.decode_sector(sector, fmt, X.new_states(fmt))
    assert set(_samples(pcm)) == {0}


def test_shift_scales_the_nibble():
    """filter 0 has no feedback, so each sample is just nibble << 12 >> shift."""
    sector = _sector([_group([0x00] * 8, fill=0x11)])
    fmt = X.XaFormat(1, 37800, 4)
    pcm = X.decode_sector(sector, fmt, X.new_states(fmt))
    assert _samples(pcm)[:X.BLOCK_SAMPLES] == (4096,) * X.BLOCK_SAMPLES


def test_block_b_reads_parameter_byte_4_plus_b():
    """Loud parameters (shift 0) for blocks 0-3, quiet (shift 12) for 4-7.

    Block b reads header byte 4 + b, so the first 4 blocks (bytes 4..7)
    are loud and the last 4 (bytes 8..11) quiet. A table that reads the
    parameters out of order (the first one here, (0,1,2,3,8,9,10,11)
    with a nibble per half) keeps this test green only by luck of the
    fill; the nibble-order test below separates them.
    """
    params = [0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C, 0x0C, 0x0C]
    sector = _sector([_group(params, fill=0x11)])
    fmt = X.XaFormat(1, 37800, 4)
    values = _samples(X.decode_sector(sector, fmt, X.new_states(fmt)))

    first_four = values[:4 * X.BLOCK_SAMPLES]
    last_four = values[4 * X.BLOCK_SAMPLES:8 * X.BLOCK_SAMPLES]
    assert set(first_four) == {4096}         # shift 0
    assert set(last_four) == {1}             # shift 12


def test_blocks_run_in_lane_order_low_nibble_first():
    """Data byte 0x21: low nibble 1, high nibble 2. Time order is
    lane0-low, lane0-high, lane1-low, ... so with shift 12 / no filter
    the blocks alternate 1, 2, 1, 2 — not 1, 1, 1, 1, 2, 2, 2, 2."""
    params = [0x0C] * 8
    sector = _sector([_group(params, fill=0x21)])
    fmt = X.XaFormat(1, 37800, 4)
    values = _samples(X.decode_sector(sector, fmt, X.new_states(fmt)))
    per_block = [set(values[b * X.BLOCK_SAMPLES:(b + 1) * X.BLOCK_SAMPLES])
                 for b in range(8)]
    assert per_block == [{1}, {2}, {1}, {2}, {1}, {2}, {1}, {2}]


def test_filter_history_carries_across_sectors():
    """ADPCM is recursive: a fresh state per sector clicks every 106 ms."""
    fmt = X.XaFormat(1, 37800, 4)
    sector = _sector([_group([0x21] * 8, fill=0x11)] * X.SOUND_GROUPS)
    shared = X.new_states(fmt)
    first = _samples(X.decode_sector(sector, fmt, shared))
    second = _samples(X.decode_sector(sector, fmt, shared))
    fresh = _samples(X.decode_sector(sector, fmt, X.new_states(fmt)))
    assert second != fresh                  # history changed the outcome
    assert first == fresh                   # ...and the first one had none


def test_samples_are_clamped_to_16_bit():
    sector = _sector([_group([0x00] * 8, fill=0x77)] * X.SOUND_GROUPS)
    fmt = X.XaFormat(1, 37800, 4)
    values = _samples(X.decode_sector(sector, fmt, X.new_states(fmt)))
    assert min(values) >= -32768 and max(values) <= 32767


def test_stereo_interleaves_block_pairs():
    fmt = X.XaFormat(2, 37800, 4)
    params = [0x00, 0x0C, 0x00, 0x0C, 0x00, 0x0C, 0x00, 0x0C]
    sector = _sector([_group(params, fill=0x11)], coding=0x01)
    values = _samples(X.decode_sector(sector, fmt, X.new_states(fmt)))
    assert values[0] == 4096 and values[1] == 1      # L loud, R quiet
    assert values[2] == 4096 and values[3] == 1


# ---------------------------------------------------------------------------
# Stream-level
# ---------------------------------------------------------------------------

def test_samples_per_sector_is_the_audio_clock():
    """18 groups x 8 blocks x 28 samples — 0.1067 s at 37800 Hz, which is
    exactly 16 sectors of disc time at 150 sectors/s."""
    assert X.samples_per_sector(X.XaFormat(1, 37800, 4)) == 4032
    assert X.samples_per_sector(X.XaFormat(2, 37800, 4)) == 2016
    assert X.samples_per_sector(X.XaFormat(1, 37800, 8)) == 2016


def test_decode_stream_returns_no_format_without_audio():
    data = _sector([_group([0] * 8)], submode=0x08)
    pcm, fmt = X.decode_stream(data)
    assert pcm == b"" and fmt is None


def test_decode_stream_concatenates_sectors():
    data = _sector([_group([0x0C] * 8, fill=0)] * X.SOUND_GROUPS) * 3
    pcm, fmt = X.decode_stream(data)
    assert fmt == X.XaFormat(1, 37800, 4)
    assert len(pcm) == 3 * 4032 * 2


def test_wav_header_describes_the_pcm():
    fmt = X.XaFormat(2, 37800, 4)
    wav = X.to_wav(b"\x00\x00" * 100, fmt)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    channels, rate = struct.unpack_from("<HI", wav, 22)
    assert (channels, rate) == (2, 37800)
    assert struct.unpack_from("<I", wav, 40)[0] == 200
