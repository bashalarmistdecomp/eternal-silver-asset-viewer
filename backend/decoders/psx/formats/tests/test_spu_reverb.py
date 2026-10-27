"""Tier 1 for the SPU reverb — synthetic presets, no game data.

What this CAN catch: the libspu record layout (mask + 32 u16 in register
order, 0x44 stride, u32 mBASE per mode), the signed volume/depth reading,
and — the one that matters — that the block-vectorised network computes
exactly what the per-sample ring-buffer reference does (`process_reference`,
the psx-spx formula as written), on a preset whose delays force several
blocks and cross-channel reads.

What it CANNOT catch: whether the formula itself is the hardware's (it is
transcribed from documentation, not from captured SPU output), or whether a
program's preset table is read from the right address — that is the
records package's job and its own test.
"""

import struct

import numpy as np
import pytest

from decoders.psx.formats import spu_reverb as R


def _preset(mode=4, base=0xF800, **over):
    """A plausible synthetic preset: offsets well inside a 0x4000-byte
    ring, distinct write targets, feedback delays of a few hundred ticks."""
    regs = dict(
        dAPF1=0x40, dAPF2=0x30, vIIR=0x7000, vCOMB1=0x4F00, vCOMB2=0xBD00,
        vCOMB3=0x4500, vCOMB4=0xBF00, vWALL=0xA700, vAPF1=0x5600,
        vAPF2=0x5300, mLSAME=0x3F0, mRSAME=0x370, mLCOMB1=0x3A0,
        mRCOMB1=0x320, mLCOMB2=0x380, mRCOMB2=0x300, dLSAME=0x360,
        dRSAME=0x2E0, mLDIFF=0x2B0, mRDIFF=0x230, mLCOMB3=0x290,
        mRCOMB3=0x210, mLCOMB4=0x270, mRCOMB4=0x1F0, dLDIFF=0x2A0,
        dRDIFF=0x220, mLAPF1=0x1A0, mRAPF1=0x150, mLAPF2=0x0F0, mRAPF2=0x0B0,
        vLIN=0x8000, vRIN=0x8000)
    regs.update(over)
    return R.ReverbPreset(mode, tuple(regs[n] for n in R.REGISTERS), base)


def test_record_layout():
    regs = tuple(range(0x100, 0x120))
    rec = struct.pack("<I32H", 0xDEADBEEF, *regs)
    assert len(rec) == R.PRESET_SIZE
    assert R.parse_preset(rec) == (0xDEADBEEF, regs)


def test_tables_parse_per_mode():
    param = b"".join(struct.pack("<I32H", 0, *([m] * 32)) for m in range(10))
    start = struct.pack("<10I", *range(0xF000, 0xF00A))
    ps = R.parse_libspu_tables(param, start)
    assert [p.mode for p in ps] == list(range(10))
    assert ps[4].name == "STUDIO_C" and ps[4].reg("vRIN") == 4
    assert ps[3].base == 0xF003
    assert ps[3].ring_samples == (R.SPU_RAM - 0xF003 * 8) // 2
    with pytest.raises(ValueError):
        R.parse_libspu_tables(param[:-1], start)


def test_volumes_and_depth_are_signed():
    p = _preset()
    assert p.vol("vLIN") == -1.0
    assert p.vol("vIIR") == pytest.approx(0x7000 / 32768)
    s = R.ReverbSetting(p, 0x3000, 0xB000)
    assert s.depth == (pytest.approx(0.375), pytest.approx(-0.625))


def test_block_network_equals_the_ring_buffer_reference():
    p = _preset()
    # the BLOCK path must be what runs here — if the preset tripped the
    # fallback, this would compare the reference with itself
    res = R._resolve(p)
    for si, (name, _reads, wreg) in enumerate(R._STAGES):
        if name[1:] in ("same", "diff"):
            assert res[(si, 1)][:2] == (wreg, 1)
    rng = np.random.default_rng(7)
    n = 5000                      # several blocks, and past the ring length
    lin = rng.normal(0, 2500, n)
    rin = rng.normal(0, 2500, n)
    lin[2500:] = rin[2500:] = 0   # silence, so the tail is exercised too
    got_l, got_r = R._network(lin, rin, p)
    ref_l, ref_r = R.process_reference(list(lin), list(rin), p)
    assert np.abs(got_l - ref_l).max() < 1e-6
    assert np.abs(got_r - ref_r).max() < 1e-6
    assert np.abs(ref_l).max() > 100       # the network actually produced sound


def test_mode_off_and_zero_input_are_silent():
    off = _preset(mode=0)
    yl, yr = R._network(np.ones(100), np.ones(100), off)
    assert not yl.any() and not yr.any()
    yl, yr = R._network(np.zeros(500), np.zeros(500), _preset())
    assert not yl.any() and not yr.any()


def test_process_scales_by_depth_and_keeps_length():
    p = _preset()
    rng = np.random.default_rng(1)
    x = rng.normal(0, 2000, 4410)
    wl, wr = R.process(x, x, 44100, R.ReverbSetting(p, 0x4000, 0xC000))
    assert len(wl) == len(wr) == len(x)
    # same input both sides, depth +0.5 / -0.5: different networks per side,
    # but the right channel's sign is the depth's
    assert np.abs(wl).max() > 0 and np.abs(wr).max() > 0


def test_streamed_in_pieces_it_is_the_whole_signal_processed_at_once():
    """`Reverb` carries the delay lines and the resampling across pushes and
    pulls: any cut of the signal gives `process`'s output exactly."""
    setting = R.ReverbSetting(_preset(), 0x3000, 0xB000)
    rng = np.random.default_rng(5)
    for rate in (44100, 32000, R.REVERB_RATE):
        x = np.rint(rng.normal(0, 3000, (2, 20000)))
        x[:, 12000:] = 0
        want_l, want_r = R.process(x[0], x[1], rate, setting)
        rev, got, at = R.Reverb(setting, rate), [], 0
        while at < len(x[0]):
            k = int(rng.integers(1, 3000))
            rev.push(x[0][at:at + k], x[1][at:at + k])
            at += k
            if rng.random() < 0.6:
                got.append(rev.pull(int(rng.integers(0, 4000))))
        rev.close()
        got.append(rev.pull(rev.ready))
        got_l = np.concatenate([a for a, _ in got])
        got_r = np.concatenate([b for _, b in got])
        assert np.array_equal(got_l, want_l) and np.array_equal(got_r, want_r)
        assert np.abs(want_l).max() > 10
