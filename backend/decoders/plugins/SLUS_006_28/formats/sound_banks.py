"""Lunar's sound banks — the VAB + SEQ region of LUNADATA.FIL.

Resource sector-table entries **232–358** are 127 contiguous sound banks
occupying sectors 4568–12670 (16.6 MB, the archive's largest single region).
Each one is an ordinary engine command list — the same `[u32 type][u32 size]`
stream that `resource_command_run (0x800202FC)` walks for map data — carrying three command types
that had not been identified before:

    13  VAB header (VH)   -> sound_vab_head_open (0x80024314), "SsVabOpenHead : failed !!!"
    14  VAB body   (VB)   -> sound_vab_body_transfer (0x800243D0), "SsVabTransBody : failed !!!"
    15  SEQ sequence      -> sound_seq_add (0x80024464)

so a bank is `[13 VH][14 VB][15 SEQ]...` terminated by a zero word.

What a bank is for follows from the bank slot the code loads it into
(formats.resources): 232, the common sound effects, into slot 0; 233–293,
the music, one score each, into slot 2; an area's bank, 294–357, or in
battle 358, into slot 1. The music plays from slot 2 alone, the sound
effects from slots 0 and 1 (`is_sfx`). 79 banks carry one long sequence:
the 61 music banks and 18 of the areas'. Resource 232 has 23 sequences,
358 has 96, the other areas' banks 2–9.

Every bank's numbers agree internally: the chunk-13 size equals the VH size
its own `ps` field implies, the chunk-14 size equals the sum of the VAG size
table, and the parsed VAG count equals the header's declared `vs` for all
127. All 412 SEQ chunks in the archive live inside these banks.

See docs/spec/sound.md.
"""

from __future__ import annotations

import hashlib
import struct
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path

from decoders.config import SECTOR_SIZE
from decoders.plugins.SLUS_006_28.formats.resources import region
from decoders.psx.formats.seq import Seq, parse_seq
from decoders.psx.formats.vab import Vab, parse_vab

#: Resource indices holding sound banks (inclusive).
BANK_RESOURCES = range(232, 359)

CMD_VAB_HEAD = 13
CMD_VAB_BODY = 14
CMD_SEQ = 15

#: The banks the sound effects play from, by their region (formats.resources):
#: the ones loaded into bank slots 0 and 1. Slot 0 holds 232 (sound_common_load
#: (0x80023E00)), slot 1 an area's bank or, in battle, 358 (sound_area_load
#: (0x80023F78), by g_SoundAreaBankPairs (0x800AF694)), and only
#: sound_effect_play (0x80024514) plays those two slots. The music is slot 2,
#: the banks sound_music_load (0x80023E9C) loads, and sound_music_play
#: (0x80023D0C) plays nothing else. Both go through sound_seq_play
#: (0x80023B24), the program's one caller of SsSeqOpen; its third caller,
#: sound_seq_rotate_play (0x80023CEC), is called by nothing.
SFX_REGIONS = frozenset({"sound-common", "sound-area", "sound-battle"})


@dataclass
class Chunk:
    kind: int
    offset: int             # byte offset within the resource
    size: int               # payload bytes, excluding the 8-byte header

    @property
    def payload_offset(self) -> int:
        return self.offset + 8


@dataclass
class SoundBank:
    """One bank: its VAB, its sequences, and where they came from."""

    resource: int
    sector: int
    size: int               # bytes of the resource span
    chunks: list[Chunk] = field(default_factory=list)
    vab: Vab | None = None
    seqs: list[Seq] = field(default_factory=list)
    seq_data: list[bytes] = field(default_factory=list)

    @property
    def is_sfx(self) -> bool:
        """A bank of sound effects, not of music (SFX_REGIONS)."""
        r = region(self.resource)
        return r is not None and r.key in SFX_REGIONS

    @property
    def label(self) -> str:
        kind = "sound effects" if self.is_sfx else "music"
        vags = len(self.vab.vags) if self.vab else 0
        return (f"sound bank {self.resource}  {kind}  {vags} sample{'s' if vags != 1 else ''}"
                f"  {len(self.seqs)} sequence{'s' if len(self.seqs) != 1 else ''}")

    @property
    def used_bytes(self) -> int:
        return sum(c.size + 8 for c in self.chunks)


def walk_chunks(data: bytes) -> list[Chunk]:
    """Split a resource's command list into chunks.

    `resource_command_run (0x800202FC)` reads `advance = (word1 & ~3) + 8`, so a size is rounded
    down to a word before the header is added; sizes here are recorded as the
    engine would consume them. A zero type ends the list, and the tail of the
    last sector is padding.
    """
    out: list[Chunk] = []
    pos = 0
    while pos + 8 <= len(data):
        kind, size = struct.unpack_from("<II", data, pos)
        kind &= 0xFF
        size &= 0xFFFFFFFC
        if kind == 0 or size == 0 or pos + 8 + size > len(data):
            break
        out.append(Chunk(kind=kind, offset=pos, size=size))
        pos += 8 + size
    return out


def parse_bank(data: bytes, resource: int, sector: int) -> SoundBank:
    """Parse one sound-bank resource span."""
    bank = SoundBank(resource=resource, sector=sector, size=len(data),
                     chunks=walk_chunks(data))

    vh = vb = b""
    for chunk in bank.chunks:
        blob = data[chunk.payload_offset:chunk.payload_offset + chunk.size]
        if chunk.kind == CMD_VAB_HEAD:
            vh = blob
        elif chunk.kind == CMD_VAB_BODY:
            vb = blob
        elif chunk.kind == CMD_SEQ:
            bank.seq_data.append(blob)

    if vh:
        try:
            bank.vab = parse_vab(vh, vb)
        except ValueError:
            bank.vab = None

    for blob in bank.seq_data:
        try:
            bank.seqs.append(parse_seq(blob))
        except ValueError:
            pass

    return bank


#: The banks parsed, by resource, sector and the sha1 of their bytes, for
#: as long as something holds them: the tabs that play a bank, and the
#: discs of a game that carry the same one, share one parse (`load_bank`).
#: A bank is not changed once parsed.
_parsed: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_parsed_lock = threading.Lock()


def load_bank(archive_path: Path | str, resource, sector: int | None = None,
              size_sectors: int | None = None) -> SoundBank:
    """Read and parse one bank: a bank of the same bytes parsed before, and
    still held, is that one (`_parsed`).

    `resource` may be a `Resource` from `decoders.plugins.SLUS_006_28.formats.resource_table`, in
    which case the sector span comes from it.
    """
    if hasattr(resource, "start_sector"):
        sector = resource.start_sector
        size_sectors = resource.size_sectors
        index = resource.index
    else:
        index = resource
    if sector is None or size_sectors is None:
        raise ValueError("need a Resource or an explicit sector span")

    with open(archive_path, "rb") as f:
        f.seek(sector * SECTOR_SIZE)
        data = f.read(size_sectors * SECTOR_SIZE)
    key = (index, sector, hashlib.sha1(data).digest())
    with _parsed_lock:
        bank = _parsed.get(key)
    if bank is None:
        bank = parse_bank(data, index, sector)
        with _parsed_lock:
            bank = _parsed.setdefault(key, bank)
    return bank


def find_banks(archive_path: Path | str, resources) -> list[SoundBank]:
    """Parse every sound bank reachable through the resource sector table."""
    banks = []
    for res in resources:
        if res.index not in BANK_RESOURCES:
            continue
        try:
            bank = load_bank(archive_path, res)
        except (OSError, ValueError):
            continue
        if bank.vab or bank.seqs:
            banks.append(bank)
    return banks
