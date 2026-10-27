"""Compute SHA-256 checksums for disc identification."""

import hashlib
from pathlib import Path

CHUNK_SIZE = 65536


def sha256_file(path: Path, start: int = 0, end: int | None = None) -> str:
    """Compute SHA-256 of a file, or of its bytes `start`..`end`, using
    chunked reads."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(start)
        left = None if end is None else max(0, end - start)
        while left is None or left > 0:
            chunk = f.read(CHUNK_SIZE if left is None else min(CHUNK_SIZE, left))
            if not chunk:
                break
            h.update(chunk)
            if left is not None:
                left -= len(chunk)
    return h.hexdigest()
