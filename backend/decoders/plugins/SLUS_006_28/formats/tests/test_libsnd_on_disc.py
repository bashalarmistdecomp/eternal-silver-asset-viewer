"""Tier 2 for the sequence renderer — the program's own disc, when the
library holds it (skipped otherwise; nothing from the disc enters git).

What this CAN catch: pitch ratio tables that are not the ones libsnd reads
in this program (`SsPitchFromNote` (0x8009B71C): 12 semitone ratios at
D_800B7A10, 128 fine ratios at D_800B7A28), and a tone selection that does
not give the counts docs/spec/code/libsnd-map.md §"What the game's SEQ data
uses" measures over all 412 scores: 2,873 note-ons in the key range of two
tones, 482 in none.
"""

import pytest

from decoders import config
from decoders.psx.formats import seq_synth, vab

_RAW = config.raw_dir("SLUS_006.28")
_EXE = _RAW / "SLUS_006.28"

pytestmark = [pytest.mark.disc, pytest.mark.skipif(
    not (_EXE.exists() and (_RAW / "LUNADATA.FIL").exists()),
    reason="SLUS_006.28 is not extracted in the library")]

SEMITONE_ADDR = 0x800B7A10
FINE_ADDR = 0x800B7A28


@pytest.fixture(scope="module")
def binary():
    from decoders.psx.analysis.exe_loader import load_exe
    return load_exe(_EXE)


def test_pitch_tables_are_the_ones_the_program_reads(binary):
    semi = tuple(binary.read_u16(SEMITONE_ADDR + 2 * k) for k in range(12))
    fine = tuple(binary.read_u16(FINE_ADDR + 2 * k) for k in range(128))
    assert semi == vab.SEMITONE_RATIOS
    assert fine == vab.FINE_RATIOS


def test_tone_selection_over_every_score(binary):
    from decoders.plugins.SLUS_006_28.formats.resource_table import (
        load_resource_table)
    from decoders.plugins.SLUS_006_28.formats.sound_banks import find_banks
    banks = find_banks(_RAW / "LUNADATA.FIL", load_resource_table(binary))
    layered = dropped = scores = 0
    for bank in banks:
        for seq in bank.seqs:
            stats = seq_synth.walk(seq, bank.vab)
            layered += stats.layered
            dropped += stats.dropped
            scores += 1
    assert (scores, layered, dropped) == (412, 2873, 482)
