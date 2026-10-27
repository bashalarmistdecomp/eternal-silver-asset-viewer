"""The voices: the spoken lines the game streams from `_AUDIO.XA`, and where
each one lies in the file.

A voice is a number. The scripts play one with command 0x52
(ScriptCommandVoiceSet (0x8005E9FC) -> VoiceSet (0x80055470)) and 0x53
(ScriptCommandVoiceStart (0x8005EA44) -> VoiceStart (0x800554C4)); a
bromide plays one from g_PictureVoices (PictureXaPlay (0x800247AC)); a
battle plays some of its own. All of them find the voice the same way,
`xa_voice_get (0x800238BC)`:

    v = g_XaVoices[n]     channel = v >> 12        start = (v & 0xFFF) << 4
    w = g_XaVoices[n + 1] on the same channel:     end = ((w & 0xFFF) - k) << 4
                          on another:              end = (g_XaChannelEnds[channel] - k) << 4
    k = 3 when D_800AF62C[n] is not 0, else 4

`start` and `end` are sectors of `_AUDIO.XA` (g_SystemAudioXaFileName
(0x80011508)), counted from its first: VoiceStart hands them to
xa_play_start (0x800235C0) and xa_end_set (0x80023630), which add the
file's first sector (g_XaFile). The drive reads from `start` with its
filter on file 1 and the voice's channel (xa_read_start (0x80023674):
CdlSetfilter), so it plays only that channel's sectors, and VoiceStep
(0x80055524) stops it once the drive is at `end` (xa_end_check
(0x80023820)). The file interleaves sixteen channels a sector each, so a
unit of the table (16 sectors) is one sector of each channel, and a voice
lasts (end - start) / 150 seconds at double speed.

Voice 0 is no voice (VoiceStart plays nothing for it); voice n needs entry
n + 1 for its end, so the table's 105 entries (0xD2 bytes to
g_XaChannelEnds) give voices 1 to 103, and D_800AF62C has a byte for each
of voices 0 to 103.

**SLPS_013.97.** The Japanese program keeps g_XaVoices and g_XaChannelEnds
elsewhere (records.programs) and its xa_voice_get (SLPS_013.97 0x80026338)
takes 2 off every voice's end: it reads no byte for it.

**The sectors.** The audio is Form 2, which a file extracted from the disc
has lost (decoders.psx.formats.xa_adpcm): `decode` takes the file's RAW
sectors from the disc image.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from decoders.psx.formats import xa_adpcm

from ..records import programs
from ..records.programs import EXE_BASE

VOICES_ADDR = 0x800ADFF2        # g_XaVoices: u16 per voice
CHANNEL_ENDS_ADDR = 0x800AE0C4  # g_XaChannelEnds: u16 per channel
END_LESS_ADDR = 0x800AF62C      # D_800AF62C: u8 per voice, 3 or 4 off its end

#: g_XaVoices' entries: 0xD2 bytes to g_XaChannelEnds.
ENTRIES = 0xD2 // 2
#: The voices: voice n needs entry n + 1 for its end.
FIRST = 1
LAST = ENTRIES - 2
CHANNELS = 16
#: Sectors of the file in a unit of the table: one of each channel.
UNIT = 16
#: The file VoiceSet's voices are read from (g_SystemAudioXaFileName).
FILE_NAME = "_AUDIO.XA"
#: The file number xa_read_start's filter passes (CdlSetfilter: file 1).
XA_FILE = 1
#: Sectors a double-speed drive reads a second (g_XaMode 0xC8).
SECTORS_PER_SECOND = 150
#: What SLPS_013.97's xa_voice_get (0x80026338) takes off every end.
JP_END_LESS = 2

VOICE_GET = "xa_voice_get (0x800238BC)"
JP_VOICE_GET = "xa_voice_get (0x800238BC; SLPS_013.97 0x80026338)"


@dataclass(frozen=True)
class Voice:
    """Where voice `number` lies in `_AUDIO.XA` (xa_voice_get)."""
    number: int
    channel: int
    #: the file's sectors the drive reads: [start, end)
    start: int
    end: int
    #: its entry of g_XaVoices, as stored
    entry: int
    #: units taken off its end (3 or 4; 2 in SLPS_013.97)
    less: int
    #: True when its end comes from the next entry, False from g_XaChannelEnds
    by_next: bool

    @property
    def sectors(self) -> int:
        return max(0, self.end - self.start)

    @property
    def channel_sectors(self) -> int:
        """Sectors of its own channel inside its span."""
        return self.sectors // UNIT

    @property
    def seconds(self) -> float:
        return self.sectors / SECTORS_PER_SECOND


def _u16s(image: bytes, addr: int, count: int) -> tuple[int, ...]:
    at = addr - EXE_BASE
    if at < 0 or at + 2 * count > len(image):
        raise ValueError(f"the table at {addr:#010x} is not in the image")
    return struct.unpack_from(f"<{count}H", image, at)


def table(image: bytes) -> tuple[int, ...]:
    """g_XaVoices as stored: `ENTRIES` u16s. `image` is the program's image
    from 0x80011000."""
    return _u16s(image, programs.address(image, "g_XaVoices", VOICES_ADDR), ENTRIES)


def channel_ends(image: bytes) -> tuple[int, ...]:
    """g_XaChannelEnds: the end of each channel's last voice, in units."""
    return _u16s(image, programs.address(image, "g_XaChannelEnds", CHANNEL_ENDS_ADDR),
                 CHANNELS)


def end_less(image: bytes, n: int) -> int:
    """The units xa_voice_get takes off voice n's end: 3 when D_800AF62C[n]
    is not 0, else 4; 2 for every voice in SLPS_013.97."""
    if programs.program_of(image) == programs.JP:
        return JP_END_LESS
    at = END_LESS_ADDR - EXE_BASE + n
    if not 0 <= at < len(image):
        raise ValueError(f"no byte for voice {n} at D_800AF62C")
    return 3 if image[at] else 4


def voice(image: bytes, n: int) -> Voice:
    """xa_voice_get (0x800238BC) for voice `n` (1 to 103)."""
    if not FIRST <= n <= LAST:
        raise ValueError(f"voice {n}: the game's voices are {FIRST} to {LAST}")
    t = table(image)
    v, w = t[n], t[n + 1]
    channel = v >> 12
    k = end_less(image, n)
    by_next = (w >> 12) == channel
    end_units = (w & 0xFFF) if by_next else channel_ends(image)[channel]
    return Voice(n, channel, (v & 0xFFF) << 4, (end_units - k) << 4, v, k, by_next)


def voices(image: bytes) -> list[Voice]:
    """Every voice, 1 to 103."""
    return [voice(image, n) for n in range(FIRST, LAST + 1)]


def proof(image: bytes) -> str:
    """The function that places a voice, in `image`'s program."""
    return JP_VOICE_GET if programs.program_of(image) == programs.JP else VOICE_GET


# -- the sound ---------------------------------------------------------------

def decode(raw: bytes, v: Voice) -> tuple[bytes, xa_adpcm.XaFormat | None]:
    """Voice `v` as 16-bit PCM, from the file's raw 2352-byte sectors
    `v.start` to `v.end` (`raw` holds exactly those): the audio sectors of
    file 1 and the voice's channel, the drive's filter, decoded in order
    with one filter history. (b"", None) when none is there."""
    size = xa_adpcm.RAW_SECTOR_SIZE
    fmt = None
    states: list = []
    out = []
    for off in range(0, len(raw) - size + 1, size):
        sub = xa_adpcm.parse_subheader(raw, off)
        if not (sub.is_form2 and sub.is_audio) or sub.file != XA_FILE or sub.channel != v.channel:
            continue
        if fmt is None:
            fmt = xa_adpcm.XaFormat.of(sub)
            states = xa_adpcm.new_states(fmt)
        out.append(xa_adpcm.decode_sector(raw[off:off + size], fmt, states))
    return b"".join(out), fmt


def wav(raw: bytes, v: Voice) -> bytes:
    """`decode` as a WAV file; empty bytes when the span holds no audio."""
    pcm, fmt = decode(raw, v)
    return xa_adpcm.to_wav(pcm, fmt) if fmt is not None else b""
