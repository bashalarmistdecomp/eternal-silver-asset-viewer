"""STR movies for the desktop app: decoded in chunks the UI pulls.

The app has its own audio clock (Web Audio), so the demux runs in PULL
form: the UI asks for the next ~second of sectors, gets that second's
frames and PCM back, and schedules both against its clock.

The rules are facts about the stream rather than choices about playback:

  * the disc is the clock — sector N plays at N/150 s, for both tracks;
  * audio lives in Form 2 sectors, so real playback reads the DISC IMAGE
    (raw 2352-byte sectors), and an extracted .STR is video-only;
  * only the first XA channel seen is played (mixing a second stutters);
  * a frame is shown only if its decode passes `mdec.check_frame`.

Nothing here decodes anything itself: `str_stream` frames the video,
`mdec` turns a frame into pixels, `xa_adpcm` turns sectors into PCM.
"""

from __future__ import annotations

import base64
import io
import threading

from PIL import Image

from decoders.psx.disc.iso_reader import DiscImage
from decoders.psx.formats import mdec, xa_adpcm
from decoders.psx.formats.str_stream import (
    HEADER_SIZE, SECTOR_SIZE, looks_like_str_sector, parse_sector_header,
)

from viewer_tabs.movie import SECTORS_PER_SECOND, MovieSource

RAW_SECTOR_SIZE = xa_adpcm.RAW_SECTOR_SIZE
USER_DATA_OFFSET = xa_adpcm.USER_DATA_OFFSET

#: Largest chunk one request may ask for: ~4 s.
MAX_CHUNK = 600

#: Frames go to the app losslessly. A JPEG of an MDEC frame compresses it a
#: second time and its ringing shows at any zoom; PNG at this level costs
#: under 2 ms a frame, small beside the decode.
PNG_COMPRESS_LEVEL = 3


class VideoStream:
    """One movie, decodable from any sector, sequentially fastest."""

    def __init__(self, movie: MovieSource):
        self.label = movie.label
        self.duration = movie.duration
        self._image_path = movie.image_path
        self._fallback = movie.fallback
        self._lba = movie.lba
        self._sectors = movie.sectors
        self._pixel_aspect = movie.pixel_aspect
        self._shape_note = movie.shape_note
        self._raw = movie.image_path is not None
        self._source = None
        self._lock = threading.Lock()
        self._reset(0)

    # -- description ------------------------------------------------------

    def describe(self) -> dict:
        return {
            "duration": self.duration,
            "sectors": self._sectors,
            "sectorsPerSecond": SECTORS_PER_SECOND,
            "fromImage": self._raw,
            "pixelAspect": (list(self._pixel_aspect)
                            if self._pixel_aspect else None),
            "shapeNote": self._shape_note,
            "note": ("reading raw sectors from the disc image" if self._raw
                     else "video only — no disc image, and an extracted .STR "
                          "has its audio sectors truncated"),
        }

    # -- decoding ---------------------------------------------------------

    def _reset(self, sector: int):
        self._cursor = sector
        self._head = None
        self._pending: list[bytes] = []
        self._channel = None
        self._fmt = None
        self._states = None

    def _open(self):
        if self._source is None:
            self._source = (DiscImage(self._image_path) if self._raw
                            else open(self._fallback, "rb"))
        return self._source

    def _read(self, sector: int, count: int) -> bytes:
        source = self._open()
        if self._raw:
            return source.sectors(self._lba + sector, count)
        source.seek(sector * SECTOR_SIZE)
        return source.read(SECTOR_SIZE * count)

    def chunk(self, start: int, count: int) -> dict:
        """Frames and PCM for sectors [start, start + count).

        A request that continues where the last one ended keeps the frame
        assembly and the ADPCM filter history; any other start is a seek and
        begins fresh.
        """
        count = max(1, min(MAX_CHUNK, count))
        with self._lock:
            start = max(0, min(start, self._sectors))
            if start != self._cursor:
                self._reset(start)
            count = min(count, self._sectors - start)
            stride = RAW_SECTOR_SIZE if self._raw else SECTOR_SIZE
            data = self._read(start, count) if count > 0 else b""

            frames: list[dict] = []
            pcm = bytearray()
            n = len(data) // stride
            for i in range(n):
                body = data[i * stride:(i + 1) * stride]
                index = start + i
                if self._raw:
                    sub = xa_adpcm.parse_subheader(body)
                    if sub.is_form2 and sub.is_audio:
                        pcm += self._audio(body, sub)
                        continue
                    user = body[USER_DATA_OFFSET:USER_DATA_OFFSET + SECTOR_SIZE]
                else:
                    user = body
                frame = self._video(user, index)
                if frame is not None:
                    frames.append(frame)

            self._cursor = start + n
            done = self._cursor >= self._sectors or n == 0
            out = {"start": start, "next": self._cursor, "done": done,
                   "frames": frames, "audio": None}
            if self._fmt is not None and pcm:
                out["audio"] = {"rate": self._fmt.sample_rate,
                                "channels": self._fmt.channels,
                                "pcm": base64.b64encode(bytes(pcm)).decode()}
            return out

    def _audio(self, sector: bytes, sub) -> bytes:
        if self._channel is None:
            self._channel = sub.channel
        elif sub.channel != self._channel:
            return b""
        if self._fmt is None:
            self._fmt = xa_adpcm.XaFormat.of(sub)
            self._states = xa_adpcm.new_states(self._fmt)
        return xa_adpcm.decode_sector(sector, self._fmt, self._states)

    def _video(self, user: bytes, index: int) -> dict | None:
        try:
            h = parse_sector_header(user)
        except ValueError:
            return None
        if not looks_like_str_sector(h):
            return None
        if self._head is None or h.frame_no != self._head.frame_no:
            self._head, self._pending = h, []
        self._pending.append(user[HEADER_SIZE:SECTOR_SIZE])
        if len(self._pending) < h.sector_size:
            return None

        payload = b"".join(self._pending)
        self._head, self._pending = None, []
        size = h.frame_size_bytes
        bitstream = payload[:size] if 0 < size <= len(payload) else payload
        try:
            decoded = mdec.decode_frame(bitstream, h.width, h.height)
        except mdec.MdecError:
            return None
        if mdec.check_frame(decoded):
            return None
        image = Image.frombytes("RGB", (decoded.width, decoded.height),
                                decoded.rgb)
        buf = io.BytesIO()
        image.save(buf, "PNG", compress_level=PNG_COMPRESS_LEVEL)
        return {"t": index / SECTORS_PER_SECOND,
                "w": decoded.width, "h": decoded.height,
                "png": base64.b64encode(buf.getvalue()).decode()}

    def close(self):
        with self._lock:
            if self._source is not None:
                try:
                    self._source.close()
                except Exception:
                    pass
                self._source = None
