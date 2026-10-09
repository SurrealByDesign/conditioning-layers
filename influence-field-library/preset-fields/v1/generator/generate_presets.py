"""Render retained binary presets using only the standard library.

The verified QR matrix is data, not a new QR encoder. UPC-A is encoded from
digits. Manifest hashes are assertions; this tool never rewrites authority.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


ROOT = Path(__file__).resolve().parents[1]
UPC = "000000000000"
LEFT = ("0001101", "0011001", "0010011", "0111101", "0100011",
        "0110001", "0101111", "0111011", "0110111", "0001011")


def upc_modules(digits=UPC):
    if (not isinstance(digits, str) or len(digits) != 12
            or any(c not in "0123456789" for c in digits)):
        raise ValueError("UPC-A requires twelve ASCII digits")
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(digits[:11]))
    if (-total) % 10 != int(digits[-1]):
        raise ValueError("UPC-A check digit mismatch")
    right = tuple(s.translate(str.maketrans("01", "10")) for s in LEFT)
    return "101" + "".join(LEFT[int(c)] for c in digits[:6]) + "01010" + "".join(
        right[int(c)] for c in digits[6:]) + "101"


def qr_codes():
    rows = json.loads((ROOT / "qr/qr-code-matrix.json").read_text(encoding="utf-8"))["rows"]
    if len(rows) != 33 or any(len(row) != 33 or set(row) - {"0", "1"} for row in rows):
        raise ValueError("Expected a binary 33x33 QR matrix")
    return bytes(255 * int(rows[(y - 14) // 3][(x - 14) // 3])
                 if 14 <= x < 113 and 14 <= y < 113 else 0
                 for y in range(128) for x in range(128))


def upc_codes():
    modules = upc_modules()
    # GS1: extend guards AND first/last symbol characters by 5X.
    extended = set(range(0, 10)) | set(range(45, 50)) | set(range(85, 95))
    return bytes(255 if 16 <= x < 111 and modules[x - 16] == "1"
                 and 27 <= y < (101 if x - 16 in extended else 96) else 0
                 for y in range(128) for x in range(128))


def png_bytes(codes):
    if len(codes) != 16384 or set(codes) != {0, 255}:
        raise ValueError("Expected a nonconstant binary 128x128 field")

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    scanlines = b"".join(b"\0" + codes[y * 128:(y + 1) * 128] for y in range(128))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanlines, level=9)) + chunk(b"IEND", b""))


def generated_assets():
    result = {}
    for stem, directory, codes in (("qr-code", "qr", qr_codes()),
                                    ("upc-" + UPC, "barcode", upc_codes())):
        result[f"{directory}/{stem}-dark.png"] = png_bytes(codes)
        result[f"{directory}/{stem}-light.png"] = png_bytes(bytes(255 - c for c in codes))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="Compare bytes without writing")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "preset-fields-manifest.json").read_text(encoding="utf-8"))
    expected = {asset["path"]: asset["sha256"] for preset in manifest["presets"]
                for asset in preset["assets"].values()}
    assets = generated_assets()
    if set(assets) != set(expected):
        raise ValueError("Generated inventory differs from manifest")
    for name, data in assets.items():
        if hashlib.sha256(data).hexdigest() != expected[name]:
            raise ValueError(f"Generated checksum differs: {name}")
    for name, data in assets.items():
        path = args.output / name
        if args.check:
            if path.read_bytes() != data:
                raise ValueError(f"Retained bytes differ: {name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    print(f"{'Verified' if args.check else 'Generated'} {len(assets)} exact PNGs")


if __name__ == "__main__":
    main()
