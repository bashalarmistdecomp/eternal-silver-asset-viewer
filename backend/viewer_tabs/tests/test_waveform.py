"""A waveform drawn as its PCM arrives is the one drawn of the whole."""

import random
import struct

import pytest

from viewer_tabs.waveform import StreamEnvelope, pcm_envelope


@pytest.mark.parametrize("frames,width", [(10_000, 1200), (999, 1200),
                                          (123_457, 300), (1, 5)])
def test_pieces_draw_the_envelope_of_the_whole(frames, width):
    pytest.importorskip("numpy")
    rng = random.Random(frames)
    pcm = struct.pack(f"<{2 * frames}h",
                      *(rng.randint(-32768, 32767) for _ in range(2 * frames)))
    env = StreamEnvelope(frames, 2, width)
    at = 0
    while at < frames:
        n = rng.choice([1, 7, 512, 4096, 30_000])
        env.add(pcm[4 * at:4 * (at + n)])
        at += n
        assert len(env.lo) <= env.columns
    env.close()
    assert (env.lo, env.hi) == pcm_envelope(pcm, 2, width)
