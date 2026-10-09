"""One shared Python/Node reader corpus, generated without a production encoder."""

import base64
import struct
import zlib


PREFIX = "data:image/png;base64,"
CODES = bytes((i * 73 + i // 128 * 19) % 256 for i in range(16384))


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def png(*, filter_type=0, header=(128, 128, 8, 0, 0, 0, 0), extra=b"", suffix=b"",
        raw_suffix=b"", compressed_suffix=b"", codes=CODES, split=False):
    raw = bytearray()
    for y in range(128):
        raw.append(filter_type)
        for x in range(128):
            i = y * 128 + x
            left, above, upper = codes[i - 1] if x else 0, codes[i - 128] if y else 0, codes[i - 129] if x and y else 0
            p = left + above - upper
            distances = [abs(p - v) for v in (left, above, upper)]
            paeth = (left, above, upper)[distances.index(min(distances))]
            predictor = [0, left, above, (left + above) // 2, paeth][filter_type] if filter_type <= 4 else 0
            raw.append((codes[i] - predictor) % 256)
    compressed = zlib.compress(bytes(raw) + raw_suffix) + compressed_suffix
    data = (chunk(b"IDAT", compressed[:7]) + chunk(b"IDAT", compressed[7:])) if split else chunk(b"IDAT", compressed)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", *header))
            + extra + data + chunk(b"IEND", b"") + suffix)


def url(data):
    return PREFIX + base64.b64encode(data).decode("ascii")


def fixtures():
    cases = [{"name": "empty", "value": "", "codes": list(bytes(16384))}]
    def add(name, data, valid=False, codes=CODES):
        cases.append({"name": name, "value": url(data), "codes": list(codes) if valid else None})
    for f in range(5):
        add(f"filter-{f}", png(filter_type=f), True)
    add("ancillary", png(extra=chunk(b"gAMA", struct.pack(">I", 45455)) + chunk(b"tEXt", b"test\0raw codes")), True)
    add("split-idat", png(split=True), True)
    add("zero-png", png(codes=bytes(16384)), True, bytes(16384))
    for name, data in (
        ("signature", b"bad"), ("truncated", png()[:-5]), ("bad-crc", png()[:-1] + b"x"),
        ("after-iend", png(suffix=b"x")), ("decoded-tail", png(raw_suffix=b"x")),
        ("zlib-tail", png(compressed_suffix=b"x")), ("second-zlib", png(compressed_suffix=zlib.compress(b"x"))),
        ("filter-5", png(filter_type=5)), ("wrong-width", png(header=(127, 128, 8, 0, 0, 0, 0))),
        ("oversize-dimensions", png(header=(129, 128, 8, 0, 0, 0, 0))),
        ("rgb", png(header=(128, 128, 8, 2, 0, 0, 0))),
        ("rgba", png(header=(128, 128, 8, 6, 0, 0, 0))),
        ("gray-alpha", png(header=(128, 128, 8, 4, 0, 0, 0))),
        ("palette", png(header=(128, 128, 8, 3, 0, 0, 0))),
        ("depth16", png(header=(128, 128, 16, 0, 0, 0, 0))),
        ("interlace", png(header=(128, 128, 8, 0, 0, 0, 1))),
        ("animation", png(extra=chunk(b"acTL", bytes(8)))),
        ("orientation", png(extra=chunk(b"eXIf", b"metadata"))),
        ("critical", png(extra=chunk(b"ABCD", b""))),
        ("reserved-bit", png(extra=chunk(b"abcd", b""))),
        ("plte", png(extra=chunk(b"PLTE", bytes(3)))),
        ("oversize-bytes", png(extra=chunk(b"tEXt", bytes(65536)))),
    ): add(name, data)
    # A padded reference is guaranteed for missing/excess-padding cases.
    padded = url(png())
    for count in range(3):
        if padded.endswith("="): break
        padded = url(png(extra=chunk(b"tEXt", b"x" * count)))
    assert padded.endswith("=")
    for name, value in (("wrong-prefix", "data:image/jpeg;base64,AA=="), ("space", padded + "\n"),
                        ("missing-padding", padded.rstrip("=")), ("excess-padding", padded + "="),
                        ("bad-base64", PREFIX + "?"), ("oversize-text", PREFIX + "A" * 100000),
                        ("null", None), ("number", 3)):
        cases.append({"name": name, "value": value, "codes": None})
    return cases
