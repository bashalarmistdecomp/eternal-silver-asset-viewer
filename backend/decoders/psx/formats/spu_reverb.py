"""SPU reverb: libspu's preset record and the hardware reverb network.

Two things live here, both Sony/PS1 facts with no game knowledge in them:

* **libspu's preset tables.** `SpuSetReverbModeType(mode)` (libspu
  s_srmt.o) indexes two static tables:

      _spu_rev_startaddr[mode]   u32, the work-area start in SPU RAM, in
                                 8-byte units — written as-is to the
                                 `mBASE` register (_spu_FsetRXX(0xD1, ...))
      _spu_rev_param[mode]       0x44 bytes: a u32 attribute mask, then the
                                 32 reverb registers as u16, in hardware
                                 order (SPU +0x1C0 dAPF1 .. +0x1FE vRIN)

  copies the 0x44-byte record to the stack, zeroes its mask ("set every
  field") and hands it to `_spu_setReverbAttr`, which writes each field to
  `_spu_RXX + 0x1C0 + 2*i`. `parse_libspu_tables` reads those two tables;
  WHERE they sit is a property of one executable image, so the addresses
  live in the program's records package, never here.

* **The reverb network** the SPU runs over those registers — the formula
  documented in nocash's psx-spx ("SPU Reverb Formula"): input volume,
  same-side and different-side reflections (a one-pole IIR each), four
  comb taps, two all-pass filters, output volume, all reading and writing
  a ring buffer in SPU RAM that advances one sample per 22.05 kHz tick.

`process` runs it over a reverb-send signal. Every read in the network is
at a fixed offset from a moving write pointer, so each read is EXACTLY a
fixed delay of one write target's output (whichever target wrote that
ring position most recently — `_resolve`). That turns the network into
delay lines, which numpy can run in blocks as long as the shortest
feedback delay; the reflections' one-sample recursion is the only thing
shorter, and it is solved per block in closed form. `Reverb` runs the
same blocks as a stream, for a signal mixed a piece at a time, and gives
what `process` gives. `process_reference` is the same network one sample
at a time — slow, kept as the test oracle for the block version.

What is approximate (and stated where the audio is shown, via
`seq_synth.FIDELITY`): arithmetic is float with int16 saturation on every
ring write, not the hardware's 16-bit fixed-point products; the 22.05 kHz
resampling is linear, not the hardware's 39-tap FIR.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:                                   # pragma: no cover
    np = None

#: The 32 reverb registers, in SPU address order from +0x1C0 (rev00..rev1F).
REGISTERS = (
    "dAPF1", "dAPF2", "vIIR", "vCOMB1", "vCOMB2", "vCOMB3", "vCOMB4", "vWALL",
    "vAPF1", "vAPF2", "mLSAME", "mRSAME", "mLCOMB1", "mRCOMB1", "mLCOMB2",
    "mRCOMB2", "dLSAME", "dRSAME", "mLDIFF", "mRDIFF", "mLCOMB3", "mRCOMB3",
    "mLCOMB4", "mRCOMB4", "dLDIFF", "dRDIFF", "mLAPF1", "mRAPF1", "mLAPF2",
    "mRAPF2", "vLIN", "vRIN",
)
REG_BASE = 0x1C0            # SPU register offset of rev00 (dAPF1)
PRESET_SIZE = 0x44          # u32 mask + 32 x u16
SPU_RAM = 0x80000           # bytes; the work area runs from mBASE*8 to here
REVERB_RATE = 22050         # the reverb unit's own rate

#: libspu's SPU_REV_MODE_* numbering (libspu.h), index = mode.
MODE_NAMES = ("OFF", "ROOM", "STUDIO_A", "STUDIO_B", "STUDIO_C", "HALL",
              "SPACE", "ECHO", "DELAY", "PIPE")


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


@dataclass(frozen=True)
class ReverbPreset:
    """One libspu reverb mode: the 32 register values and its work area."""

    mode: int
    regs: tuple             # 32 raw u16, REGISTERS order
    base: int               # mBASE, in 8-byte units

    @property
    def name(self) -> str:
        return MODE_NAMES[self.mode] if self.mode < len(MODE_NAMES) \
            else f"mode{self.mode}"

    def reg(self, name: str) -> int:
        return self.regs[REGISTERS.index(name)]

    def vol(self, name: str) -> float:
        """A volume register as a signed fraction of full scale."""
        return _s16(self.reg(name)) / 32768.0

    @property
    def ring_samples(self) -> int:
        """Work-area length in 16-bit samples."""
        return max(0, (SPU_RAM - self.base * 8) // 2)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "name": self.name, "mBASE": self.base,
                "work_area_bytes": self.ring_samples * 2,
                "registers": {n: v for n, v in zip(REGISTERS, self.regs)}}


@dataclass(frozen=True)
class ReverbSetting:
    """What a program configures: a preset plus the output depth pair
    (`SpuSetReverbModeDepth` writes them raw to vLOUT/vROUT, SPU +0x184 /
    +0x186 — signed 16-bit, so a set top bit is a phase-inverted channel)."""

    preset: ReverbPreset
    vlout: int              # raw u16 register value
    vrout: int

    @property
    def depth(self) -> tuple[float, float]:
        return _s16(self.vlout) / 32768.0, _s16(self.vrout) / 32768.0


def parse_preset(buf: bytes) -> tuple[int, tuple]:
    """One `_spu_rev_param` record -> (mask, 32 u16 register values)."""
    if len(buf) < PRESET_SIZE:
        raise ValueError(f"need {PRESET_SIZE:#x} bytes, got {len(buf):#x}")
    mask = struct.unpack_from("<I", buf, 0)[0]
    return mask, struct.unpack_from("<32H", buf, 4)


def parse_libspu_tables(param: bytes, startaddr: bytes,
                        count: int = len(MODE_NAMES)) -> list[ReverbPreset]:
    """`_spu_rev_param` + `_spu_rev_startaddr` -> one preset per mode."""
    if len(param) < count * PRESET_SIZE or len(startaddr) < count * 4:
        raise ValueError("tables shorter than the mode count")
    bases = struct.unpack_from(f"<{count}I", startaddr, 0)
    return [ReverbPreset(m, parse_preset(param[m * PRESET_SIZE:])[1],
                         bases[m] & 0xFFFF)
            for m in range(count)]


# ---------------------------------------------------------------------------
# The network
# ---------------------------------------------------------------------------

#: Stages in tick order: (name, reads, write). The left chain runs, then the
#: right (the SPU computes them on alternating 44.1 kHz cycles); the buffer
#: address advances after both. Each read is (register, sample adjustment)
#: — `-1` is psx-spx's "[mXXX-2]", one 16-bit sample back.
_STAGES = (
    ("Lsame", (("dLSAME", 0), ("mLSAME", -1)), "mLSAME"),
    ("Ldiff", (("dRDIFF", 0), ("mLDIFF", -1)), "mLDIFF"),
    ("Lcomb", (("mLCOMB1", 0), ("mLCOMB2", 0), ("mLCOMB3", 0),
               ("mLCOMB4", 0)), None),
    ("Lapf1", (("mLAPF1", "dAPF1"),), "mLAPF1"),
    ("Lapf2", (("mLAPF2", "dAPF2"),), "mLAPF2"),
    ("Rsame", (("dRSAME", 0), ("mRSAME", -1)), "mRSAME"),
    ("Rdiff", (("dLDIFF", 0), ("mRDIFF", -1)), "mRDIFF"),
    ("Rcomb", (("mRCOMB1", 0), ("mRCOMB2", 0), ("mRCOMB3", 0),
               ("mRCOMB4", 0)), None),
    ("Rapf1", (("mRAPF1", "dAPF1"),), "mRAPF1"),
    ("Rapf2", (("mRAPF2", "dAPF2"),), "mRAPF2"),
)


def _offset(p: ReverbPreset, reg: str, adj) -> int:
    """A read/write address as a ring offset in samples (8-byte units -> 4
    samples each)."""
    off = p.reg(reg) * 4
    if isinstance(adj, str):                  # [mXAPFn - dAPFn]
        off -= p.reg(adj) * 4
    else:
        off += adj
    return off % p.ring_samples


def _resolve(p: ReverbPreset) -> dict:
    """{(stage, read#): (write register, delay in ticks)} — which target
    last wrote the position a read sees, and how long ago. A target that
    writes the SAME position in the same tick counts only if its stage
    runs before the read's; otherwise it is the previous lap (delay L)."""
    L = p.ring_samples
    writes = [(si, st[2], _offset(p, st[2], 0))
              for si, st in enumerate(_STAGES) if st[2]]
    out = {}
    for si, (_n, reads, _w) in enumerate(_STAGES):
        for ri, (reg, adj) in enumerate(reads):
            r = _offset(p, reg, adj)
            best = None
            for wsi, wreg, woff in writes:
                d = (woff - r) % L
                if d == 0 and wsi >= si:
                    d = L
                if best is None or d < best[1]:
                    best = (wreg, d, wsi)
            out[(si, ri)] = best
    return out


def process(send_l, send_r, rate: int, setting: ReverbSetting):
    """Run the reverb over a send signal at `rate` -> (wet_l, wet_r) float
    arrays the length of the input, at `rate`, already scaled by the output
    depth. Needs numpy. The whole signal at once: `Reverb` gives the same,
    a piece at a time."""
    rev = Reverb(setting, rate)
    rev.push(send_l, send_r)
    rev.close()
    return rev.pull(rev.ready)


class Reverb:
    """`process` as a stream: `push` the send as it is mixed, `close` it at
    its end, and `pull` the wet output as far as `ready` says the network
    has run. However the signal is cut into pushes and pulls, the output is
    the one `process` gives for the whole of it, sample for sample: the
    resampling to and from REVERB_RATE is linear interpolation at the same
    points with the same arithmetic, the network runs on the same blocks,
    and its delay lines carry over from one block to the next. Holds only
    the network's longest delay and a block or two of signal."""

    def __init__(self, setting: ReverbSetting, rate: int):
        if np is None:                                # pragma: no cover
            raise RuntimeError("spu_reverb.Reverb needs numpy")
        self.depth = setting.depth
        self.rate = rate
        self.net = _Network(setting.preset)
        self.same = rate == REVERB_RATE
        self.r_in = rate / REVERB_RATE              # input samples a tick
        self.r_out = REVERB_RATE / rate             # ticks an output sample
        self.x = (np.zeros(0), np.zeros(0))         # input from xbase
        self.xbase = 0
        self.n_in = 0                               # input pushed
        self.n = None                               # ticks in all, once closed
        self.k = 0                                  # ticks resampled
        self.lin: list = []                         # resampled, not yet run
        self.lin_n = 0
        self.y = (np.zeros(0), np.zeros(0))         # network output from ybase
        self.ybase = 0
        self.ny = 0                                 # ticks run
        self.out = 0                                # output pulled
        self.ready = 0                              # output that can be

    @property
    def closed(self) -> bool:
        return self.n is not None

    def push(self, send_l, send_r) -> None:
        if self.closed:
            raise ValueError("pushed after close")
        self.x = (np.concatenate((self.x[0], np.asarray(send_l, np.float64))),
                  np.concatenate((self.x[1], np.asarray(send_r, np.float64))))
        self.n_in += len(send_l)
        self._run()

    def close(self) -> None:
        """No more input: run the network to the signal's end."""
        if self.closed:
            return
        self.n = (self.n_in if self.same
                  else int(math.ceil(self.n_in * REVERB_RATE / self.rate)) + 1)
        self._run()

    def input_for(self, out: int) -> int:
        """Input samples to push before the output reaches `out` (until the
        close, the run reaches whole blocks past what is pushed)."""
        tick = int(out * self.r_out) + 2
        block = self.net.block
        tick = -(-tick // block) * block
        return int(tick * self.r_in) + 3

    def _run(self) -> None:
        # 1. resample what the input reaches
        if self.same:
            upto = self.n_in
        elif self.closed:
            upto = self.n
        else:
            # a tick between two pushed samples, never the last one pushed
            upto = int(max(0, self.n_in - 2) / self.r_in) + 2
            while upto > self.k and int((upto - 1) * self.r_in) + 1 > \
                    self.n_in - 1:
                upto -= 1
        if upto > self.k and self.n_in:
            ks = np.arange(self.k, upto)
            if self.same:
                got = tuple(x[ks - self.xbase] for x in self.x)
            else:
                t = ks * self.r_in - self.xbase
                grid = np.arange(len(self.x[0]))
                got = tuple(np.interp(t, grid, x) for x in self.x)
            self.lin.append(got)
            self.lin_n += upto - self.k
            self.k = upto
            keep = (self.k if self.same else int(self.k * self.r_in)) - 1
            self._trim_x(keep)
        # 2. run whole blocks; the last one short, at the end
        block = self.net.block
        last = self.closed and self.k == self.n
        if self.lin_n >= block or (last and self.lin_n):
            lin = np.concatenate([a for a, _ in self.lin])
            rin = np.concatenate([b for _, b in self.lin])
            ran, at = [], 0
            while self.lin_n - at >= block or (last and self.lin_n > at):
                m = min(block, self.lin_n - at)
                ran.append(self.net.run(lin[at:at + m], rin[at:at + m]))
                at += m
            self.lin = [(lin[at:], rin[at:])] if at < self.lin_n else []
            self.lin_n -= at
            self.y = (np.concatenate([self.y[0]] + [a for a, _ in ran]),
                      np.concatenate([self.y[1]] + [b for _, b in ran]))
            self.ny += at
        # 3. the output those ticks reach
        if last and not self.lin_n:
            self.ready = self.n_in
        elif self.same:
            self.ready = min(self.ny, self.n_in)
        else:
            ready = int(max(0, self.ny - 2) / self.r_out) + 2
            while ready > self.out and int((ready - 1) * self.r_out) + 1 > \
                    self.ny - 1:
                ready -= 1
            self.ready = max(self.out, min(ready, self.n_in))

    def _trim_x(self, keep: int) -> None:
        cut = keep - self.xbase
        if cut > 4096:
            self.x = (self.x[0][cut:], self.x[1][cut:])
            self.xbase += cut

    def pull(self, count: int):
        """The next `count` output samples (no more than `ready`) ->
        (wet_l, wet_r), scaled by the depth."""
        count = max(0, min(count, self.ready - self.out))
        ks = np.arange(self.out, self.out + count)
        if self.same:
            wet = tuple(np.asarray(y[ks - self.ybase], np.float64)
                        for y in self.y)
        else:
            t = ks * self.r_out - self.ybase
            grid = np.arange(len(self.y[0]))
            wet = tuple(np.interp(t, grid, y, right=0.0) if len(y)
                        else np.zeros(count) for y in self.y)
        self.out += count
        cut = (self.out if self.same else int(self.out * self.r_out)) \
            - 1 - self.ybase
        if cut > 4096:
            self.y = (self.y[0][cut:], self.y[1][cut:])
            self.ybase += cut
        dl, dr = self.depth
        return wet[0] * dl, wet[1] * dr


def _network(lin, rin, p: ReverbPreset):
    """The block-vectorised network at REVERB_RATE -> (Lout, Rout) before
    the output depth, over the whole signal at once."""
    net = _Network(p)
    n = len(lin)
    lin, rin = np.asarray(lin, np.float64), np.asarray(rin, np.float64)
    if not n:
        return np.zeros(0), np.zeros(0)
    parts = [net.run(lin[s:s + net.block], rin[s:s + net.block])
             for s in range(0, n, net.block)]
    return (np.concatenate([a for a, _ in parts]),
            np.concatenate([b for _, b in parts]))


class _Network:
    """The network run a block at a time: `run(lin, rin)` takes the next
    `block` ticks of input (the last block may be shorter) and returns
    their output before the depth, the delay lines carried over between
    blocks.

    Every read in the network is at a fixed offset from a moving write
    pointer, so each read is EXACTLY a fixed delay of one write target's
    output (whichever target wrote that ring position most recently —
    `_resolve`). That turns the network into delay lines, which numpy runs
    in blocks as long as the shortest feedback delay; the reflections'
    one-sample recursion is the only thing shorter, and it is solved per
    block in closed form. Each target keeps only as much of its past as
    the longest read reaches back."""

    def __init__(self, p: ReverbPreset):
        self.p = p
        self.s = 0                      # ticks run
        self.ref = None
        self.silent = p.mode == 0 or p.ring_samples < 8
        self.block = 4096
        if self.silent:
            return
        res = _resolve(p)
        # The closed-form reflection step assumes each "[mXXX-2]" read sees
        # its OWN write one tick earlier. A preset whose offsets put another
        # target there is outside that model: run the reference instead of
        # guessing.
        for si, (name, _reads, wreg) in enumerate(_STAGES):
            if name[1:] in ("same", "diff") and res[(si, 1)][:2] != (wreg, 1):
                self.ref = _Reference(p)
                return
        # Block length: every read whose source is computed at the same or
        # a later stage must reach at least a block back — except the
        # reflections' own previous sample, which is solved in closed form.
        feedback = []
        for (si, ri), (wreg, d, wsi) in res.items():
            reg, adj = _STAGES[si][1][ri]
            self_iir = (adj == -1 and wreg == _STAGES[si][2] and d == 1)
            if wsi >= si and not self_iir:
                feedback.append(d)
        B = max(1, min(feedback) if feedback else 1024)
        self.block = B = min(B, 4096)
        self.res = res
        self.back = max(d for _w, d, _s in res.values())
        self.hbase = 0                  # tick of each history's index 0
        self.hist = {st[2]: np.zeros(self.back + 2 * B)
                     for st in _STAGES if st[2]}
        self.v_in = {"L": p.vol("vLIN"), "R": p.vol("vRIN")}
        iir = p.vol("vIIR")
        self.wall = p.vol("vWALL")
        self.combs = [p.vol(f"vCOMB{i}") for i in range(1, 5)]
        self.apf = {"apf1": p.vol("vAPF1"), "apf2": p.vol("vAPF2")}
        # one-pole IIR y = a*x + (1-a)*y[-1], truncated kernel + exact
        # history
        keep = 1.0 - iir
        K = 1 if keep == 0 else max(1, min(256, int(
            math.ceil(math.log(1e-12) / math.log(abs(keep)))) if abs(keep) < 1
            else 256))
        self.kern = iir * keep ** np.arange(K)
        self.pows = keep ** np.arange(1, B + 1)

    def _read(self, si: int, ri: int, s: int, e: int):
        wreg, d, _ = self.res[(si, ri)]
        lo, hi = s - d, e - d
        buf = self.hist[wreg]
        if hi <= 0:
            return np.zeros(e - s)
        if lo >= 0:
            return buf[lo - self.hbase:hi - self.hbase]
        return np.concatenate((np.zeros(-lo), buf[:hi - self.hbase]))

    def run(self, lin, rin):
        m = len(lin)
        s, e = self.s, self.s + m
        self.s = e
        if self.silent:
            return np.zeros(m), np.zeros(m)
        if self.ref is not None:
            yl, yr = self.ref.run(lin, rin)
            return np.asarray(yl, np.float64), np.asarray(yr, np.float64)
        size = len(self.hist["mLSAME"])
        if e - self.hbase > size:       # move the histories along
            base = s - self.back
            cut = base - self.hbase
            for buf in self.hist.values():
                buf[:size - cut] = buf[cut:]
                buf[size - cut:] = 0.0
            self.hbase = base
        hb = self.hbase
        acc = {}
        for si, (name, reads, wreg) in enumerate(_STAGES):
            side, kind = name[0], name[1:]
            src = lin if side == "L" else rin
            if kind in ("same", "diff"):
                x = self.v_in[side] * src + self._read(si, 0, s, e) * self.wall
                y0 = self.hist[wreg][s - 1 - hb] if s else 0.0
                y = np.convolve(x, self.kern)[:m] + y0 * self.pows[:m]
                self.hist[wreg][s - hb:e - hb] = np.clip(y, -32768, 32767)
            elif kind == "comb":
                acc[side] = sum(c * self._read(si, i, s, e)
                                for i, c in enumerate(self.combs))
            else:                                     # apf1 / apf2
                v = self.apf[kind]
                r = self._read(si, 0, s, e)
                u = np.clip(acc[side] - v * r, -32768, 32767)
                self.hist[wreg][s - hb:e - hb] = u
                acc[side] = u * v + r
        return acc["L"], acc["R"]


def process_reference(lin, rin, p: ReverbPreset):
    """The same network one tick at a time over an actual ring buffer — the
    psx-spx formula as written, float arithmetic, int16 saturation on ring
    writes. Slow; the test oracle for `_network` (same inputs: signals
    already at REVERB_RATE, output before depth)."""
    return _Reference(p).run(lin, rin)


class _Reference:
    """`process_reference`'s ring buffer, kept between calls of `run`."""

    def __init__(self, p: ReverbPreset):
        self.L = p.ring_samples
        self.ring = [0.0] * self.L
        self.ba = 0
        self.v = {r: p.vol(r) for r in REGISTERS if r[0] == "v"}
        self.off = {}
        for _n, reads, w in _STAGES:
            for reg, adj in reads:
                self.off[(reg, adj)] = _offset(p, reg, adj)
            if w:
                self.off[(w, 0)] = _offset(p, w, 0)

    def run(self, lin, rin):
        L, ring, v, off = self.L, self.ring, self.v, self.off
        clip = lambda x: -32768.0 if x < -32768 else (32767.0 if x > 32767 else x)
        out_l, out_r = [], []
        ba = self.ba
        for t in range(len(lin)):
            at = lambda key: ring[(ba + off[key]) % L]

            def put(reg, val):
                ring[(ba + off[(reg, 0)]) % L] = clip(val)
            res = {}
            for side, src, same_d, diff_d in (("L", lin, "dLSAME", "dRDIFF"),
                                              ("R", rin, "dRSAME", "dLDIFF")):
                x_in = v[f"v{side}IN"] * src[t]
                prev = at((f"m{side}SAME", -1))
                put(f"m{side}SAME", (x_in + at((same_d, 0)) * v["vWALL"] - prev)
                    * v["vIIR"] + prev)
                prev = at((f"m{side}DIFF", -1))
                put(f"m{side}DIFF", (x_in + at((diff_d, 0)) * v["vWALL"] - prev)
                    * v["vIIR"] + prev)
                o = sum(v[f"vCOMB{i}"] * at((f"m{side}COMB{i}", 0))
                        for i in range(1, 5))
                for k in ("1", "2"):
                    r = at((f"m{side}APF{k}", f"dAPF{k}"))
                    o = clip(o - v[f"vAPF{k}"] * r)
                    put(f"m{side}APF{k}", o)
                    o = o * v[f"vAPF{k}"] + r
                res[side] = o
            out_l.append(res["L"])
            out_r.append(res["R"])
            ba = (ba + 1) % L
        self.ba = ba
        return out_l, out_r
