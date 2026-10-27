"""Tier-1 tests for the MDEC video codec — synthetic bitstreams only.

No game data: every frame here is built by `_frame()` below, so these run
without a library. What they CANNOT catch is a VLC table entry
that is self-consistently wrong — a table can be prefix-free, round-trip
its own encoder and still disagree with the hardware. That is what
`check_frame`'s bitstream-tail bound is for against real streams
(decoders/psx/formats/mdec.py).
"""

import struct

import pytest

from decoders.psx.formats import mdec as M


# ---------------------------------------------------------------------------
# A minimal encoder, so the tests state what they mean in MDEC terms
# ---------------------------------------------------------------------------

def _bits_to_bytes(bits: str) -> bytes:
    """Pack an MSB-first bit string, then swap to the stored word order."""
    bits += "0" * (-len(bits) % 16)
    raw = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
    return M._swap16(raw)


def _dc_bits(value: int) -> str:
    return format(value & 0x3FF, "010b")


def _frame(dc_values, q_scale=1, version=2, code_bound=32):
    """One frame: six DC-only blocks per macroblock, in Cr Cb Y1..Y4 order."""
    bits = "".join(_dc_bits(dc) + M.EOB_CODE for dc in dc_values)
    header = struct.pack("<HHhH", code_bound // 2, M.MAGIC, q_scale, version)
    return header + _bits_to_bytes(bits)


def _blocks_frame(ac_by_block, blocks=6, code_bound=32):
    """One macroblock with extra AC bits spliced into chosen blocks."""
    bits = "".join(_dc_bits(0) + ac_by_block.get(i, "") + M.EOB_CODE
                   for i in range(blocks))
    return (struct.pack("<HHhH", code_bound // 2, M.MAGIC, 1, 2)
            + _bits_to_bytes(bits))


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def test_header_fields():
    h = M.parse_frame_header(struct.pack("<HHhH", 1024, M.MAGIC, 3, 2))
    assert h.mdec_codes == 2048        # the field counts codes in PAIRS
    assert h.q_scale == 3 and h.version == 2
    assert h.looks_valid


def test_header_too_short_is_an_error():
    with pytest.raises(M.MdecError):
        M.parse_frame_header(b"\x00\x01\x02")


def test_wrong_magic_is_refused():
    frame = _frame([0] * 6)
    broken = frame[:2] + struct.pack("<H", 0x1234) + frame[4:]
    with pytest.raises(M.MdecError, match="magic"):
        M.decode_frame(broken, 16, 16)


def test_version_3_is_refused_loudly_not_guessed():
    """v3 codes DC differentially; decoding it as v2 would look plausible."""
    with pytest.raises(M.MdecError, match="version 3"):
        M.decode_frame(_frame([0] * 6, version=3), 16, 16)


# ---------------------------------------------------------------------------
# Bit order — the trap this module documents
# ---------------------------------------------------------------------------

def test_swap16_swaps_each_word():
    assert M._swap16(b"\x01\x02\x03\x04") == b"\x02\x01\x04\x03"


def test_swap16_pads_an_odd_length():
    assert M._swap16(b"\xAB") == b"\x00\xAB"


def test_bit_reader_is_msb_first():
    r = M._BitReader(b"\b\xA5")          # 1010 0101 in the second byte
    assert r.read(8) == 0x08
    assert [r.read_bit() for _ in range(8)] == [1, 0, 1, 0, 0, 1, 0, 1]
    with pytest.raises(M.MdecError, match="exhausted"):
        r.read_bit()


def test_signed_reads_twos_complement():
    assert M._signed(0x3FF, 10) == -1
    assert M._signed(0x200, 10) == -512
    assert M._signed(0x1FF, 10) == 511
    assert M._signed(0, 10) == 0


# ---------------------------------------------------------------------------
# The VLC table's own structure
# ---------------------------------------------------------------------------

def test_ac_table_is_prefix_free():
    """No code may be a prefix of another, or the decoder cannot be greedy."""
    codes = sorted(M.AC_VLC)
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            assert not b.startswith(a), f"{a!r} is a prefix of {b!r}"


def test_eob_and_escape_do_not_collide_with_the_table():
    for marker in (M.EOB_CODE, M.ESCAPE_CODE):
        assert marker not in M.AC_VLC
        for code in M.AC_VLC:
            assert not code.startswith(marker), f"{code!r} starts with {marker!r}"
            assert not marker.startswith(code), f"{marker!r} starts with {code!r}"


def test_zigzag_and_quant_table_are_complete():
    assert sorted(M.ZIGZAG) == list(range(64))
    assert len(M.QUANT_TABLE) == 64
    assert M.QUANT_TABLE[0] == 2


def test_quant_table_is_the_matrix_in_scan_order():
    # The MDEC weights the k-th coefficient of the scan by entry k, so entry k
    # is the matrix's weight at the place the scan puts that coefficient.
    for k in range(64):
        assert M.QUANT_TABLE[k] == M.MPEG1_INTRA_MATRIX[M.ZIGZAG[k]]
    assert M.QUANT_TABLE[:6] == (2, 16, 16, 19, 16, 19)


@pytest.mark.parametrize("scan, place, weight", [(2, 8, 16), (7, 10, 22), (9, 24, 22)])
def test_an_ac_coefficient_takes_the_weight_of_its_place(scan, place, weight):
    # A literal level 8 at q_scale 1 dequantizes to (8 * weight + 4) >> 3 =
    # weight, landing at the natural place the scan names.
    esc = M.ESCAPE_CODE + format(scan - 1, "06b") + format(8, "010b")
    bits = M._BitReader(M._swap16(_bits_to_bytes(_dc_bits(0) + esc + M.EOB_CODE)))
    coeffs, codes = M._read_block(bits, 1)
    assert codes == 3
    assert coeffs[place] == weight
    assert sum(1 for c in coeffs if c) == 1


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def test_all_zero_dc_decodes_to_neutral_grey():
    """DC 0 everywhere: luma 0 + the 128 offset, chroma neutral."""
    d = M.decode_frame(_frame([0] * 6), 16, 16)
    assert (d.width, d.height) == (16, 16)
    assert d.blocks == 6
    assert d.codes == 12                      # 6 blocks x (DC + EOB)
    assert set(d.rgb) == {128}


def test_luma_dc_sets_brightness_and_stays_grey():
    # DC dequantizes by QUANT_TABLE[0] (=2) and the IDCT scales by 1/8,
    # so a luma DC of 200 lands at 200*2/8 = 50 above the 128 offset.
    d = M.decode_frame(_frame([0, 0, 200, 200, 200, 200]), 16, 16)
    assert set(d.rgb) == {178}


def test_chroma_dc_tints_the_frame():
    """Block order is Cr, Cb, then the four luma quadrants."""
    d = M.decode_frame(_frame([100, 0, 0, 0, 0, 0]), 16, 16)
    r, g, b = d.rgb[0], d.rgb[1], d.rgb[2]
    assert r > b > g                       # +Cr pushes red up and green down
    assert b == 128                        # Cb is untouched
    assert (r, g) == (163, 110)


def test_ac_coefficient_breaks_the_flat_block():
    ac = "11" + "0"                        # (run 0, level 1), positive sign
    d = M.decode_frame(_blocks_frame({2: ac}), 16, 16)
    assert d.codes == 13                   # one extra code in one block
    assert len(set(d.rgb)) > 1             # no longer flat


def test_escape_code_carries_a_literal_run_and_level():
    run, level = 5, -300
    esc = M.ESCAPE_CODE + format(run, "06b") + format(level & 0x3FF, "010b")
    d = M.decode_frame(_blocks_frame({2: esc}), 16, 16)
    assert d.codes == 13
    assert len(set(d.rgb)) > 1


def test_unknown_vlc_prefix_is_an_error_not_silence():
    bits = _dc_bits(0) + "0" * 20          # no code is 20 zeroes
    frame = struct.pack("<HHhH", 16, M.MAGIC, 1, 2) + _bits_to_bytes(bits)
    with pytest.raises(M.MdecError):
        M.decode_frame(frame, 16, 16)


def test_run_past_the_end_of_a_block_is_an_error():
    esc = M.ESCAPE_CODE + format(63, "06b") + format(1, "010b")
    with pytest.raises(M.MdecError, match="overflows"):
        M.decode_frame(_blocks_frame({0: esc + esc}), 16, 16)


def test_geometry_rounds_up_to_whole_macroblocks():
    """A 24x24 frame is 2x2 macroblocks — 24 blocks — and crops on output."""
    d = M.decode_frame(_frame([0] * 24, code_bound=64), 24, 24)
    assert d.blocks == 24
    assert len(d.rgb) == 24 * 24 * 3


# ---------------------------------------------------------------------------
# The self-check
# ---------------------------------------------------------------------------

def test_check_frame_passes_a_consistent_decode():
    assert M.check_frame(M.decode_frame(_frame([0] * 6), 16, 16)) == []


def test_check_frame_flags_a_wrong_block_count():
    d = M.decode_frame(_frame([0] * 6), 16, 16)
    bad = M.DecodedFrame(width=32, height=32, rgb=d.rgb, header=d.header,
                         codes=d.codes, blocks=d.blocks,
                         bits_used=d.bits_used,
                         bits_available=d.bits_available)
    assert any("blocks" in p for p in M.check_frame(bad))


def test_check_frame_flags_a_code_count_outside_the_bound():
    d = M.decode_frame(_frame([0] * 6, code_bound=32), 16, 16)
    bad = M.DecodedFrame(width=16, height=16, rgb=d.rgb,
                         header=M.FrameHeader(mdec_codes=4096, magic=M.MAGIC,
                                              q_scale=1, version=2),
                         codes=d.codes, blocks=d.blocks,
                         bits_used=d.bits_used,
                         bits_available=d.bits_available)
    assert any("slack" in p for p in M.check_frame(bad))


def test_check_frame_flags_an_unconsumed_tail():
    """A desynced decode leaves the stream unread — the sharpest check."""
    d = M.decode_frame(_frame([0] * 6), 16, 16)
    bad = M.DecodedFrame(width=16, height=16, rgb=d.rgb, header=d.header,
                         codes=d.codes, blocks=d.blocks, bits_used=d.bits_used,
                         bits_available=d.bits_available + 4096)
    assert any("padding" in p for p in M.check_frame(bad))


# ---------------------------------------------------------------------------
# IDCT
# ---------------------------------------------------------------------------

def test_idct_of_a_dc_only_block_is_flat():
    coeffs = [0] * 64
    coeffs[0] = 8
    out = M.idct_8x8(coeffs)
    assert len(out) == 64
    assert all(abs(v - 1.0) < 1e-9 for v in out)


def test_numpy_and_fallback_reconstruction_agree(monkeypatch):
    """The vectorized path and the loop path must place pixels identically.

    They are separate implementations of macroblock placement, 4:2:0
    upsampling and the colour transform, so this is the test that keeps the
    fast path honest — the fallback is what documents the intent.
    """
    frame = _frame([100, -80, 200, -150, 60, 0])
    fast = M.decode_frame(frame, 16, 16).rgb
    monkeypatch.setattr(M, "_np", None)
    slow = M.decode_frame(frame, 16, 16).rgb
    assert fast == slow


def test_numpy_and_fallback_idct_agree(monkeypatch):
    coeffs = [((i * 37) % 61) - 30 for i in range(64)]
    fast = M.idct_8x8(coeffs)
    monkeypatch.setattr(M, "_np", None)
    slow = M.idct_8x8(coeffs)
    assert max(abs(a - b) for a, b in zip(fast, slow)) < 1e-9
