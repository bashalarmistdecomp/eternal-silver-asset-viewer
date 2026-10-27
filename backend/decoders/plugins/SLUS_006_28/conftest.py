"""Shared test help: a made-up image the readers take for SLPS_013.97.

programs.STAMPS gains a made-up stamp for the Japanese program for the
test's length; an image beginning with it is read as that program, so a
reader takes the Japanese rows' addresses. No game bytes.
"""

import pytest

from decoders.plugins.SLUS_006_28.records import programs

JP_STAMP = b"made-up stamp for the Japanese program"


@pytest.fixture
def jp_image(monkeypatch):
    """make(size) -> a zeroed bytearray of `size` bytes that begins with a
    stamp read as SLPS_013.97."""
    monkeypatch.setattr(programs, "STAMPS",
                        {**programs.STAMPS, programs.stamp_digest(JP_STAMP): programs.JP})

    def make(size: int) -> bytearray:
        img = bytearray(max(size, len(JP_STAMP) + 1))
        img[:len(JP_STAMP)] = JP_STAMP
        return img

    return make
