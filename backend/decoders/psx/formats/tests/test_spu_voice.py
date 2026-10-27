"""The SPU voice: envelope runs against the plain definition, and a voice's
life from key-on to silence."""

import random
from array import array

from decoders.psx.formats import spu_voice as sv


def _stepped(adsr1, adsr2, hold, total):
    """The envelope by its definition, one sample at a time: output the
    level, count the sample, and step when the counter reaches a multiple
    of the rate's denominator."""
    env = sv.Envelope(adsr1, adsr2)
    out = []
    for t in range(total):
        if t == hold:
            env.key_off()
        if env.state == sv.OFF:
            out.append(0)
            continue
        out.append(env.level)
        env.ctr += 1
        rate = env._rate()
        if env.ctr % sv._denominator(rate) == 0:
            env._step(rate)
    return array("i", out)


def test_envelope_runs_match_stepping_one_sample_at_a_time():
    rng = random.Random(7)
    for _ in range(150):
        adsr1, adsr2 = rng.randrange(1 << 16), rng.randrange(1 << 16)
        hold = rng.choice([0, 1, 7, 300, 2500])
        assert sv.envelope(adsr1, adsr2, hold, 4000) == \
            _stepped(adsr1, adsr2, hold, 4000), (hex(adsr1), hex(adsr2), hold)


def test_envelope_in_runs_matches_one_pass():
    for adsr1, adsr2, hold in ((0x000F, 0x0000, 500), (0x8F3A, 0x5FC7, 3000),
                               (0x2A04, 0x1E0A, 7000), (0x80FF, 0xDFE7, 900)):
        whole = sv.envelope(adsr1, adsr2, hold, 20_000)
        env = sv.Envelope(adsr1, adsr2)
        parts = array("i")
        while len(parts) < 20_000 and not env.done:
            if len(parts) >= hold:
                env.key_off()
            parts += env.take(min(737, hold - len(parts))
                              if len(parts) < hold else 737)
        parts += array("i", bytes(4 * (20_000 - len(parts))))
        assert parts[:20_000] == whole


def test_new_rates_keep_the_level_reached():
    env = sv.Envelope(0x000F, 0x0000)           # attack at once, hold max
    assert env.take(10)[-1] == sv.ENV_MAX
    env.set_adsr(0x000F, 0x4000 | (40 << 6))    # sustain now falls
    run = env.take(4000)
    assert run[0] == sv.ENV_MAX and run[-1] < sv.ENV_MAX


class _Mix:
    def __init__(self):
        self.runs = []

    def mix(self, play, env):
        self.runs.append((play.mixed, len(env), play.step, play.vol))
        return play.pos + play.step * len(env)


def test_a_one_shot_falls_silent_where_its_sample_ends():
    mixer = _Mix()
    # 100 samples, no loop, read at twice their rate
    play = sv.Play(mixer, 1000, (list(range(101)), 100, None),
                   (0x000F, 0x0000), 2 << 16, (0x3FFF, 0x3FFF), False)
    play.advance(1030)
    assert play.ended is None and play.level == sv.ENV_MAX
    play.advance(1100)
    assert play.ended == 1050 and play.level == 0
    assert sum(n for _, n, _, _ in mixer.runs) == 50


def test_a_voice_mixes_in_runs_of_constant_pitch_and_volume():
    mixer = _Mix()
    play = sv.Play(mixer, 0, (list(range(29)), 28, 0), (0x000F, 0x0000),
                   1 << 16, (100, 100), False)
    play.advance(300)
    play.set(1 << 16, (50, 50), False)          # a new volume at 300
    play.advance(500)
    play.env.key_off()
    play.advance(10_000)                        # released at once: ends
    assert [(at, n, v) for at, n, _, v in mixer.runs] == \
        [(0, 300, (100, 100)), (300, play.ended - 300, (50, 50))]
    assert 500 <= play.ended <= 503
