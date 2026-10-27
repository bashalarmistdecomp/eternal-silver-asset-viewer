"""The voices' sound: `_AUDIO.XA`'s raw sectors, read from the disc image.

A voice is Form 2 audio (formats.xa_voices), and an extracted file keeps
2048 bytes of each 2352-byte sector, its subheader gone: the sound can only
be read from the disc image, as a movie's is (viewer_tabs.movie). This
finds the file's first sector on the image the dump came from
(DiscContext.source: a cue sheet's data track, or a bare .bin, which is
one) and hands formats.xa_voices each voice's sectors. An .iso keeps
2048 bytes of each sector too, so its voices cannot be read.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

from viewer_tabs.movie import raw_track

#: Voices kept decoded: a long one is megabytes.
KEEP = 8


class VoiceFile:
    """`_AUDIO.XA` on one disc's image."""

    _cache: dict[Path, "VoiceFile"] = {}
    _cache_lock = threading.Lock()

    def __init__(self, ctx):
        from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
        self.image: Path | None = None
        self.lba = 0
        #: why the sound cannot be read, or "" when it can
        self.why = ""
        self._lock = threading.Lock()
        self._wavs: OrderedDict[int, bytes] = OrderedDict()
        track, why = raw_track(ctx.source)
        if track is None:
            self.why = f"{why}: a voice is Form 2 audio, which only the raw sectors keep"
            return
        try:
            from decoders.psx.disc.iso_reader import DiscImage, find_file
            with DiscImage(track) as image:
                entry = find_file(image, xv.FILE_NAME)
            if entry is None:
                self.why = f"the image has no {xv.FILE_NAME}"
                return
            self.image, self.lba = Path(track), entry.lba
        except (OSError, ValueError) as ex:
            self.why = f"the image could not be read: {ex}"

    @classmethod
    def for_ctx(cls, ctx) -> "VoiceFile":
        key = Path(ctx.data_dir)
        with cls._cache_lock:
            got = cls._cache.get(key)
            if got is None:
                got = cls._cache[key] = cls(ctx)
            return got

    def raw(self, voice) -> bytes:
        """Voice `voice`'s (xa_voices.Voice) sectors, raw."""
        from decoders.psx.disc.iso_reader import DiscImage
        if self.image is None:
            raise LookupError(self.why)
        with DiscImage(self.image) as image:
            return image.sectors(self.lba + voice.start, voice.sectors)

    def wav(self, voice) -> bytes:
        """Voice `voice` as a WAV file; the last few read are kept."""
        from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
        with self._lock:
            got = self._wavs.get(voice.number)
        if got is None:
            got = xv.wav(self.raw(voice), voice)
            with self._lock:
                self._wavs[voice.number] = got
                while len(self._wavs) > KEEP:
                    self._wavs.popitem(last=False)
        return got
