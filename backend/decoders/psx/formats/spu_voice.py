"""The SPU's voices, offline: ADSR envelope, sample playback and mixing.

A driver (libsnd's voice manager in `seq_synth`) writes a voice's registers
and keys it on and off at given output samples; this module plays what the
SPU would: the sample from its start at the pitch register's rate, shaped
by the envelope, at the voice's volume, mixed into stereo buffers (and the
reverb send for voices whose reverb bit is set).

What is the SPU's (psx-spx):

* the ADSR envelope: 15-bit level, one rate counter per voice running from
  the key-on, linear and exponential modes, the >= 0x6000 attack slowdown,
  decay ending when the level's top nibble reaches the sustain level;
* key-on restarts the voice (attack from level 0, the sample from its start
  address) with the registers as they stand; key-off sends the envelope to
  release from the level it has reached;
* register writes to a sounding voice take effect at once: volume, pitch
  and ADSR change from that sample on;
* a sample that ends without a loop silences the voice and zeroes its
  envelope level; one with a loop point repeats from it;
* the envelope level a program reads back (ENVX) is the level reached, or 0
  once the voice is silent.

What is not: interpolation is linear, not the SPU's 4-tap Gaussian.
"""

from __future__ import annotations

from array import array

try:
    import numpy as np
except ImportError:                                   # pragma: no cover
    np = None                                         # pure-Python fallback

#: Envelope level is 15-bit, as in the SPU.
ENV_MAX = 0x7FFF

#: The SPU's voices.
VOICES = 24

#: A voice's audio is mixed at most this many samples at a time, so a note
#: held for minutes costs no more memory than a short one.
CHUNK = 1 << 16


# ---------------------------------------------------------------------------
# ADSR
# ---------------------------------------------------------------------------

def _denominator(rate: int) -> int:
    """Samples between envelope steps at this rate."""
    return 1 if rate < 48 else 1 << ((rate >> 2) - 11)


def _increase(rate: int) -> int:
    return (7 - (rate & 3)) << (11 - (rate >> 2)) if rate < 48 \
        else (7 - (rate & 3))


def _decrease(rate: int) -> int:
    return (-8 + (rate & 3)) << (11 - (rate >> 2)) if rate < 48 \
        else (-8 + (rate & 3))


ATTACK, DECAY, SUSTAIN, RELEASE, OFF = range(5)


class Envelope:
    """The SPU envelope of one voice from its key-on, produced a run at a
    time.

    `take(n)` returns the next n 15-bit levels, or fewer once the release
    has reached zero (`done`). The level is constant between rate firings,
    so runs are filled whole rather than stepped sample by sample.
    `key_off()` starts the release from the next sample; `set_adsr` changes
    the rates and modes under a sounding voice, keeping its level, phase
    and counter."""

    def __init__(self, adsr1: int, adsr2: int):
        self.set_adsr(adsr1, adsr2)
        self.level, self.ctr, self.state = 0, 0, ATTACK

    def set_adsr(self, adsr1: int, adsr2: int) -> None:
        self.adsr = (adsr1, adsr2)
        self.attack_rate = (adsr1 >> 8) & 0x7F
        self.attack_exp = (adsr1 >> 15) & 1
        self.decay_rate = ((adsr1 >> 4) & 0x0F) * 4
        self.sustain_level = adsr1 & 0x0F
        self.sustain_rate = (adsr2 >> 6) & 0x7F
        self.sustain_dec = (adsr2 >> 14) & 1
        self.sustain_exp = (adsr2 >> 15) & 1
        self.release_rate = (adsr2 & 0x1F) * 4
        self.release_exp = (adsr2 >> 5) & 1

    @property
    def done(self) -> bool:
        return self.state == OFF

    def key_off(self) -> None:
        if self.state != OFF:
            self.state = RELEASE

    def _rate(self) -> int:
        state, level = self.state, self.level
        if state == ATTACK:
            return self.attack_rate + (
                8 if self.attack_exp and level >= 0x6000 else 0)
        if state == DECAY:
            return self.decay_rate
        if state == SUSTAIN:
            return self.sustain_rate + (
                8 if (not self.sustain_dec and self.sustain_exp
                      and level >= 0x6000) else 0)
        return self.release_rate

    def _step(self, rate: int) -> None:
        state, level = self.state, self.level
        if state == ATTACK:
            level += _increase(rate)
            if level >= ENV_MAX:
                level, state = ENV_MAX, DECAY
        elif state == DECAY:
            level += (_decrease(rate) * level) >> 15
            if level < 0:
                level = 0
            if ((level >> 11) & 0xF) <= self.sustain_level:
                state = SUSTAIN
        elif state == SUSTAIN:
            if not self.sustain_dec:
                level = min(ENV_MAX, level + _increase(rate))
            elif self.sustain_exp:
                level = max(0, level + ((_decrease(rate) * level) >> 15))
            else:
                level = max(0, level + _decrease(rate))
        else:
            if self.release_exp:
                level += (_decrease(rate) * level) >> 15
            else:
                level += _decrease(rate)
            if level <= 0:
                level, state = 0, OFF
        self.state, self.level = state, level

    def take(self, n: int) -> array:
        env = array("i", bytes(4 * n))
        one = array("i", [0])
        i = 0
        while i < n:
            if self.state == OFF:
                return env[:i]
            if self.state == SUSTAIN and self.level == (
                    0 if self.sustain_dec else ENV_MAX):
                # The level cannot move until the key-off: fill the rest at
                # once (the counter keeps its phase).
                end, rate = n, None
            else:
                rate = self._rate()
                den = _denominator(rate)
                if den == 1:
                    i = self._every_sample(env, i, n, rate)
                    continue
                # samples until the counter next reaches a multiple of `den`
                end = min(n, i + ((self.ctr // den) + 1) * den - self.ctr)
            if self.level:
                one[0] = self.level
                env[i:end] = one * (end - i)
            self.ctr += end - i
            i = end
            if rate is not None and not self.ctr % den:
                self._step(rate)
        return env

    def _every_sample(self, env: array, i: int, n: int, rate: int) -> int:
        """At a rate that steps every sample: fill from `i` until the rate
        or the state changes or `n`, all at once — a linear run as a
        progression, an exponential one from its cached trajectory. Same
        levels as stepping one sample at a time."""
        state, level, k = self.state, self.level, n - i
        if state == RELEASE or (state == SUSTAIN and self.sustain_dec):
            if (self.release_exp if state == RELEASE else self.sustain_exp):
                return self._trajectory(env, i, k, state, rate)
            dec = _decrease(rate)
            s = max(1, -(-level // -dec))       # steps to reach <= 0
            m = min(k, s)
            env[i:i + m] = array("i", range(level, level + m * dec, dec))
            level += m * dec
            if level <= 0:
                level = 0
                if state == RELEASE:
                    self.state = OFF
        elif state == DECAY:
            return self._trajectory(env, i, k, state, rate)
        else:                                   # attack, or sustain rising
            inc = _increase(rate)
            exp = self.attack_exp if state == ATTACK else self.sustain_exp
            limit = 0x6000 if exp and level < 0x6000 else ENV_MAX
            s = -(-(limit - level) // inc)      # steps to reach the limit
            m = min(k, s)
            env[i:i + m] = array("i", range(level, level + m * inc, inc))
            level += m * inc
            if level >= ENV_MAX:
                level = ENV_MAX
                if state == ATTACK:
                    self.state = DECAY
        self.level = level
        self.ctr += m
        return i + m

    def _trajectory(self, env: array, i: int, k: int, state: int,
                    rate: int) -> int:
        """An exponential run stepping every sample, until its state
        changes (decay reaching the sustain level, release reaching 0) or
        sustain reaches 0."""
        key = (state, rate, self.level,
               self.sustain_level if state == DECAY else 0)
        path = _TRAJECTORIES.get(key)
        if path is None:
            path = _exponential(state, _decrease(rate), self.level,
                                self.sustain_level)
            size = 4 * len(path[0])
            if _cached[0] + size <= TRAJECTORY_CACHE_BYTES:
                _TRAJECTORIES[key] = path
                _cached[0] += size
        levels, after = path
        m = min(k, len(levels))
        env[i:i + m] = levels[:m] if m < len(levels) else levels
        self.ctr += m
        if m < len(levels):
            self.level = levels[m]
        else:
            self.level = after
            if state == DECAY:
                self.state = SUSTAIN
            elif state == RELEASE:
                self.state = OFF
        return i + m


#: Exponential runs met so far: (state, rate, level, sustain level) ->
#: (the levels it outputs, the level it ends on). Songs release the same
#: instrument from the same level over and over.
_TRAJECTORIES: dict[tuple, tuple[array, int]] = {}
TRAJECTORY_CACHE_BYTES = 32 << 20
_cached = [0]


def _exponential(state: int, dec: int, level: int, sustain_level: int
                 ) -> tuple[array, int]:
    out = [level]
    while True:
        level += (dec * level) >> 15
        if state == DECAY:
            if level < 0:
                level = 0
            if ((level >> 11) & 0xF) <= sustain_level:
                break
        elif state == RELEASE:
            if level <= 0:
                level = 0
                break
        elif level <= 0:                        # sustain falling
            level = 0
            break
        out.append(level)
    return array("i", out), level


def envelope(adsr1: int, adsr2: int, hold: int, total: int) -> array:
    """The SPU envelope of a voice keyed off `hold` samples after its
    key-on, as `total` 15-bit levels (zeros once the release has ended)."""
    gen = Envelope(adsr1, adsr2)
    env = gen.take(min(hold, total))
    if len(env) == min(hold, total) < total:
        gen.key_off()
        env += gen.take(total - len(env))
    return env + array("i", bytes(4 * (total - len(env))))


# ---------------------------------------------------------------------------
# One sounding voice
# ---------------------------------------------------------------------------

class Play:
    """A voice from one key-on until it falls silent or is keyed on again.

    `advance(t)` runs its envelope (and its place in the sample) up to
    output sample `t`; the audio is mixed later, in runs of constant pitch,
    volume and reverb routing, when one of them changes, when the voice
    stops, or every CHUNK samples."""

    __slots__ = ("start", "src", "n_src", "loop", "env", "at", "spos",
                 "pending", "pending_n", "mixed", "pos", "step", "vol",
                 "rev", "ended", "level", "mixer")

    def __init__(self, mixer: "Mixer", start: int, sample, adsr, step: int,
                 vol: tuple[int, int], rev: bool):
        self.mixer = mixer
        self.start = start
        self.src, self.n_src, self.loop = sample
        self.env = Envelope(*adsr)
        self.at = self.mixed = start    # enveloped / mixed up to (output)
        self.spos = self.pos = 0        # 16.16 place in the sample at each
        self.pending: list = []
        self.pending_n = 0
        self.step, self.vol, self.rev = step, vol, rev
        self.ended: int | None = None   # where it fell silent for good
        self.level = 0                  # ENVX: the last level reached

    def _until_sample_end(self) -> int | None:
        """Samples from `at` until a sample without a loop runs out."""
        if self.loop is not None or not self.n_src:
            return None
        if self.step <= 0:
            return None
        left = (self.n_src << 16) - self.spos
        return max(0, -(-left // self.step))

    def advance(self, t: int) -> None:
        if self.ended is not None or t <= self.at:
            return
        n = t - self.at
        stop = self._until_sample_end()
        if stop is not None and stop < n:
            n = stop
        levels = self.env.take(n) if n else array("i")
        got = len(levels)
        if got:
            self.pending.append(levels)
            self.pending_n += got
            self.level = levels[-1]
        self.spos += self.step * got
        self.at += got
        if got < t - (self.at - got):       # envelope or sample ran out
            self.level = 0
            self.ended = self.at
            self.flush()
        elif self.pending_n >= CHUNK:
            self.flush()

    def flush(self) -> None:
        """Mix what has been enveloped and not yet mixed."""
        if not self.pending_n:
            return
        if len(self.pending) == 1:
            env = self.pending[0]
        else:
            env = array("i")
            for part in self.pending:
                env += part
        self.pos = self.mixer.mix(self, env)
        self.mixed += self.pending_n
        self.pending, self.pending_n = [], 0

    def set(self, step: int, vol: tuple[int, int], rev: bool) -> None:
        """New pitch, volume or routing from `at` on."""
        if (step, vol, rev) != (self.step, self.vol, self.rev):
            self.flush()
            self.step, self.vol, self.rev = step, vol, rev

    def cut(self) -> None:
        """Stop at `at` (a key-on restarting the voice)."""
        self.flush()
        self.ended = self.at
        self.level = 0


# ---------------------------------------------------------------------------
# Mixing
# ---------------------------------------------------------------------------

class Mixer:
    """The stereo mix, plus the reverb send while reverb is on, held as a
    window that moves along the output.

    Voices mix into it from `base`, the first output sample not yet taken,
    onwards; `take(end)` hands over everything before `end` and drops it,
    so a score of any length is mixed in the memory of a few chunks. A
    sample is final once every voice has been mixed past it, which is the
    driver's to know. `limit`: output samples from it on are not mixed at
    all (0: nothing, for a driver that only wants the register writes)."""

    def __init__(self, reverb: bool, limit: int | None = None):
        self.reverb = reverb
        self.limit = limit
        self.base = 0                   # output sample of index 0
        self.high = 0                   # one past the last sample mixed
        self.size = 0
        self.left = self.right = self.rev_l = self.rev_r = None
        self._resize(CHUNK)

    def _buffer(self, n: int):
        if np is not None:
            return np.zeros(n, dtype=np.int32)
        return array("i", bytes(4 * n))

    def _resize(self, size: int) -> None:
        names = ("left", "right") + (("rev_l", "rev_r") if self.reverb else ())
        used = self.high - self.base
        for name in names:
            new = self._buffer(size)
            old = getattr(self, name)
            if old is not None and used:
                new[:used] = old[:used]
            setattr(self, name, new)
        self.size = size

    def mix(self, play: Play, env: array) -> int:
        """Mix `env`'s run of `play` from `play.mixed`; returns the 16.16
        sample position after it."""
        at = play.mixed
        m = len(env) if self.limit is None else min(len(env), self.limit - at)
        if m <= 0 or not play.n_src:
            return play.pos + play.step * len(env)
        if at < self.base:
            raise ValueError(f"mixing at {at}, already taken to {self.base}")
        if at + m - self.base > self.size:
            self._resize(max(at + m - self.base, 2 * self.size))
        self.high = max(self.high, at + m)
        if self.reverb and play.rev:
            out_l, out_r = self.rev_l, self.rev_r
        else:
            out_l, out_r = self.left, self.right
        if np is not None:
            env = np.frombuffer(env, dtype=np.int32)[:m]
            mix = _mix_np
        else:
            env = env[:m]
            mix = _mix_py
        segs = [(0, m, play.step, play.vol[0], play.vol[1])]
        pos, _ = mix(out_l, out_r, at - self.base, play.src, play.n_src,
                     play.loop, play.pos, segs, env)
        return pos + play.step * (len(env) - m) if len(env) > m else pos

    def take(self, end: int) -> tuple:
        """The mix from `base` to `end` as (left, right, reverb left, reverb
        right) — the reverb pair None without reverb — and the window moved
        on to `end`."""
        n = max(0, end - self.base)
        if n > self.size:
            self._resize(n)
        names = ("left", "right") + (("rev_l", "rev_r") if self.reverb else ())
        out = []
        rest = max(0, self.high - end)
        for name in names:
            buf = getattr(self, name)
            out.append(buf[:n] if np is None else buf[:n].copy())
            if rest:
                buf[:rest] = buf[n:n + rest]
            gone = min(self.size, n + rest) - rest
            if gone > 0:
                buf[rest:rest + gone] = self._buffer(gone)
        self.base = max(self.base, end)
        self.high = max(self.high, self.base)
        if self.size > 2 * CHUNK and self.high - self.base <= CHUNK:
            self._resize(CHUNK)         # one long stretch made it grow
        if not self.reverb:
            out += [None, None]
        return tuple(out)

    def __getstate__(self):
        """A copy keeps the samples mixed and not yet taken, not the room
        for more."""
        state = self.__dict__.copy()
        used = self.high - self.base
        for name in ("left", "right", "rev_l", "rev_r"):
            if state[name] is not None:
                state[name] = state[name][:used]
        state["size"] = used
        return state


def _mix_np(out_l, out_r, at, src, n_src, loop, pos, segs, env):
    """Vectorised mixer — same arithmetic as `_mix_py`, whole-array at once.

    Returns the 16.16 sample position after the run, and whether a sample
    without a loop ended in it."""
    m = len(env)
    if len(segs) == 1:
        _, _, step, il, ir = segs[0]
        p = pos + np.arange(m, dtype=np.int64) * step
        next_pos = pos + m * step
    else:
        steps = np.empty(m, dtype=np.int64)
        il = np.empty(m, dtype=np.int64)
        ir = np.empty(m, dtype=np.int64)
        for a, b, step, vl, vr in segs:
            steps[a:b], il[a:b], ir[a:b] = step, vl, vr
        p = np.empty(m, dtype=np.int64)
        p[0] = pos
        np.cumsum(steps[:-1], out=p[1:])
        p[1:] += pos
        next_pos = int(p[-1] + steps[-1])

    idx = p >> 16
    ended = False
    if loop is not None:
        over = idx >= n_src
        if over.any():
            idx = np.where(over, loop + (idx - loop) % (n_src - loop), idx)
    else:
        keep = int(np.searchsorted(idx, n_src))
        if keep < m:                          # one-shot: stop at the end
            ended, m = True, keep
            idx, p, env = idx[:m], p[:m], env[:m]
            if not np.isscalar(il):
                il, ir = il[:m], ir[:m]
            if not m:
                return next_pos, ended

    a = src[idx]
    v = ((a + (((src[idx + 1] - a) * (p & 0xFFFF)) >> 16))
         * np.asarray(env, dtype=np.int64)) >> 15
    out_l[at:at + m] += (v * il) >> 14
    out_r[at:at + m] += (v * ir) >> 14
    return next_pos, ended


def _mix_py(out_l, out_r, at, src, n_src, loop, pos, segs, env):
    """Inner loop: resample, envelope, accumulate. Kept deliberately flat."""
    loop_len = n_src - loop if loop is not None else 0
    for a, b, step, vl, vr in segs:
        j = at + a
        for e in env[a:b]:
            idx = pos >> 16
            if idx >= n_src:
                if not loop_len:
                    return pos, True
                idx = loop + (idx - loop) % loop_len
                pos = (idx << 16) | (pos & 0xFFFF)
            s = src[idx]
            v = ((s + (((src[idx + 1] - s) * (pos & 0xFFFF)) >> 16)) * e) >> 15
            out_l[j] += (v * vl) >> 14
            out_r[j] += (v * vr) >> 14
            j += 1
            pos += step
    return pos, False
