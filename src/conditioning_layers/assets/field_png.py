"""ADR-0031 inline Painted Field values; no filesystem or runtime dependency."""

import base64
import re
import struct
import zlib

from .errors import AssetInspectionError
from .models import InspectionLimits
from .png_inspector import inspect_png_data


PREFIX = "data:image/png;base64,"
FORMAT_ERROR = ('Painted Field requires "" or a data:image/png;base64, value '
                'containing a 128x128 non-interlaced grayscale-8 PNG '
                '(at most 65,536 PNG bytes / 100,000 text characters).')
_LIMITS = InspectionLimits(maximum_file_bytes=65536, maximum_width=128,
                           maximum_height=128, maximum_pixels=16384,
                           maximum_decoded_bytes=128 * 129)


def decode_field_data_url(text: str) -> bytes:
    """Recover raw codes, retaining inspector acceptance of ancillary chunks/filters."""
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError(FORMAT_ERROR)
    if text == "":
        return bytes(16384)
    if not text.startswith(PREFIX):
        raise ValueError(FORMAT_ERROR)
    payload = text[len(PREFIX):]
    # Pin strict padding across Python versions (b64decode differs on excess '=').
    if not re.fullmatch(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?", payload):
        raise ValueError(FORMAT_ERROR)
    try:
        data = base64.b64decode(payload, validate=True)
        decoded = inspect_png_data(data, layer_id="painted-field",
                                   relative_reference="inline", limits=_LIMITS)
        if (decoded.profile.width, decoded.profile.height,
                decoded.profile.channel_count) != (128, 128, 1):
            raise ValueError(FORMAT_ERROR)
    except (ValueError, AssetInspectionError) as error:
        raise ValueError(FORMAT_ERROR) from error
    return decoded.values


def encode_field_png(codes: bytes) -> bytes:
    """Minimal reference writer. Cross-language authority is decoded codes."""
    if not isinstance(codes, bytes) or len(codes) != 16384:
        raise ValueError("Expected exactly 16,384 byte codes")

    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload)))

    rows = b"".join(b"\0" + codes[y:y + 128] for y in range(0, 16384, 128))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))
