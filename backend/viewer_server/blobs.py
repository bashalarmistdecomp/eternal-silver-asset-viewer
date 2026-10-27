"""Bytes the UI fetches by URL: rendered images, audio clips, video frames.

A provider hands back PIL images and WAV/MIDI blobs; the UI wants URLs it
can put in an `<img>` or an `<audio>`. The store keeps each object under an
opaque id and encodes an image to PNG only when it is first fetched — most
layers of a selection are never looked at.

Bounded by an approximate byte budget, oldest first: a CD track's WAV is
tens of megabytes, and a long session would otherwise keep every one.
"""

from __future__ import annotations

import io
import secrets
import threading
import weakref
from collections import OrderedDict

#: Roughly what the store may hold before evicting. Images count at their
#: RGBA size until encoded, then at their RGBA size plus their PNG.
DEFAULT_BUDGET = 768 << 20


class BlobStore:
    def __init__(self, budget: int = DEFAULT_BUDGET):
        self._lock = threading.Lock()
        self._items: OrderedDict[str, dict] = OrderedDict()
        # A tab that keeps its parse hands back the same PIL image on every
        # selection of an item; register it once so its PNG is encoded once.
        self._by_obj: dict[int, tuple[weakref.ref, str]] = {}
        self._bytes = 0
        self._budget = budget
        self._prefix = secrets.token_hex(3)
        self._n = 0

    def _new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}{self._n:x}"

    def put_image(self, img) -> str:
        with self._lock:
            hit = self._by_obj.get(id(img))
            if hit and hit[0]() is img and hit[1] in self._items:
                self._items.move_to_end(hit[1])
                return hit[1]
            bid = self._new_id()
            cost = img.width * img.height * 4
            self._items[bid] = {"image": img, "data": None,
                                "mime": "image/png", "cost": cost}
            try:
                self._by_obj[id(img)] = (weakref.ref(img), bid)
            except TypeError:
                pass
            self._bytes += cost
            self._evict()
            return bid

    def put_bytes(self, data: bytes, mime: str) -> str:
        with self._lock:
            bid = self._new_id()
            self._items[bid] = {"image": None, "data": data, "mime": mime,
                                "cost": len(data)}
            self._bytes += len(data)
            self._evict()
            return bid

    def image(self, bid: str):
        """The PIL image behind an id, or None (evicted, or not an image)."""
        with self._lock:
            item = self._items.get(bid)
            return item["image"] if item else None

    def get(self, bid: str) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._items.get(bid)
            if item is None:
                return None
            self._items.move_to_end(bid)
            if item["data"] is not None:
                return item["data"], item["mime"]
            img = item["image"]
        # Encode outside the lock: a 2048x2048 world map takes a while, and
        # every other request would queue behind it.
        buf = io.BytesIO()
        if img.mode not in ("RGBA", "RGB", "L", "LA", "P"):
            img = img.convert("RGBA")
        img.save(buf, "PNG", compress_level=1)
        data = buf.getvalue()
        with self._lock:
            item = self._items.get(bid)
            if item is not None and item["data"] is None:
                item["data"] = data
                item["cost"] += len(data)
                self._bytes += len(data)
        return data, "image/png"

    def _evict(self):
        while self._bytes > self._budget and len(self._items) > 1:
            _bid, item = self._items.popitem(last=False)
            self._bytes -= item["cost"]
