from __future__ import annotations

import json
import struct
import zlib

from conditioning_layers.integrations.comfyui_panel import UploadedField
from conditioning_layers.integrations.comfyui_panel.models import PNG_MIME_TYPE


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def grayscale_png(left_value: int, right_value: int) -> bytes:
    row = bytes([left_value] * 64 + [right_value] * 64)
    header = struct.pack(">IIBBBBB", 128, 128, 8, 0, 0, 0, 0)
    scanlines = b"".join(b"\x00" + row for _ in range(128))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + _chunk(b"IEND", b"")
    )


def metadata(rows, *, base_prompt="Base", key="request-1") -> bytes:
    return json.dumps(
        {
            "base_prompt": base_prompt,
            "idempotency_key": key,
            "document_id": None,
            "document_key": None,
            "layers": rows,
        }
    ).encode("utf-8")


def row(
    row_id: str,
    *,
    name: str | None = None,
    prompt: str | None = None,
    strength=1.0,
    active=True,
):
    return {
        "row_id": row_id,
        "layer_id": None,
        "name": name or f"Layer {row_id}",
        "prompt_text": prompt or f"Prompt {row_id}",
        "strength": strength,
        "active": active,
        "field_part": f"field-{row_id}",
        "retained_field": False,
    }


def upload(row_id: str, data: bytes | None = None, mime=PNG_MIME_TYPE):
    return UploadedField(
        part_name=f"field-{row_id}",
        content_type=mime,
        data=data or grayscale_png(255, 0),
    )
