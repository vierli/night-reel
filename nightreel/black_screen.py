"""Generate the tiny black image used to keep VLC's video output open."""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def ensure_black_frame(path: Path, width: int = 64, height: int = 36) -> Path:
    path = Path(path)
    if path.is_file() and path.read_bytes()[:8] == PNG_SIGNATURE:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    raw_rows = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    payload = PNG_SIGNATURE
    payload += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += _chunk(b"IDAT", zlib.compress(raw_rows, level=9))
    payload += _chunk(b"IEND", b"")

    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
    return path


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

