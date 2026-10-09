"""Binary preset asset qualification and independent structural oracles; pure lane."""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import unittest
import zlib

from conditioning_layers.comfyui import preset_field_source as presets


ROOT = Path(__file__).resolve().parents[4]
LIBRARY = ROOT / "influence-field-library/preset-fields/v1"
IDS = ("qr-code-dark", "qr-code-light", "upc-000000000000-dark", "upc-000000000000-light")
LABELS = ("QR Code  Dark", "QR Code  Light", "UPC  Dark", "UPC  Light")
PAYLOAD = "https://github.com/SurrealByDesign/conditioning-layers"
MATRIX_HASH = "c75cd03c5b0abc22dca51649f26c7e776b7d3090a5027855530bef78ce1ad90b"
UPC_ORACLE = ("101" "0001101" "0001101" "0001101" "0001101" "0001101" "0001101"
              "01010" "1110010" "1110010" "1110010" "1110010" "1110010" "1110010" "101")
ASSET_HASHES = {
    "qr-code-dark": "164da40d5bdf703f784d7288d42f1d2ebc6e53abfcf5a7a27f6b68cc3c07aba0",
    "qr-code-light": "8a238e24a766666bc4b33710bb057a9a7d5594635c7800f51da2f0d7cf831beb",
    "upc-000000000000-dark": "c905feac4478e90b9538dabbf9210c3f50af7f3f57655fb436abc89384a0d446",
    "upc-000000000000-light": "8c3d71b9f3378bcc48613b4d632eef77de7c6fa18de1b8434c8be221f52adafa",
}


def manifest():
    return json.loads((LIBRARY / "preset-fields-manifest.json").read_text(encoding="utf-8"))


def generator():
    spec = importlib.util.spec_from_file_location("preset_generator", LIBRARY / "generator/generate_presets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png_codes(data):
    """Independent restricted PNG parser; no production decoder/generator used."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, offset = [], 8
    while offset < len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        assert zlib.crc32(kind + payload) == int.from_bytes(data[offset + 8 + length:offset + 12 + length], "big")
        chunks.append((kind, payload))
        offset += length + 12
    assert offset == len(data)
    assert [c[0] for c in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    assert struct.unpack(">IIBBBBB", chunks[0][1]) == (128, 128, 8, 0, 0, 0, 0)
    assert chunks[-1][1] == b""
    raw = zlib.decompress(chunks[1][1])
    assert len(raw) == 128 * 129
    assert all(raw[y * 129] == 0 for y in range(128))
    return b"".join(raw[y * 129 + 1:(y + 1) * 129] for y in range(128))


class PresetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = manifest()
        self.qr, self.upc = self.manifest["presets"]
        self.matrix = json.loads((LIBRARY / self.qr["matrix"]["path"]).read_text())
        self.rows = self.matrix["rows"]

    def codes(self, preset, polarity="dark"):
        return png_codes((LIBRARY / preset["assets"][polarity]["path"]).read_bytes())

    def test_manifest_order_ids_paths_and_profiles(self):
        registry = presets.preset_registry()
        self.assertEqual(tuple(p["preset_id"] for p in self.manifest["presets"]), ("qr-code", "upc-000000000000"))
        self.assertEqual(tuple(p["display_name"] for p in self.manifest["presets"]), ("QR Code", "UPC"))
        self.assertEqual(tuple(registry), LABELS)
        self.assertEqual(tuple(a["id"] for a in registry.values()), IDS)
        self.assertEqual(len({a["path"] for a in registry.values()}), 4)
        for p in self.manifest["presets"]:
            self.assertEqual((p["field_type"], p["width"], p["height"], p["bit_depth"],
                              p["channel_mode"], p["alpha"], p["support_status"], p["version"]),
                             ("binary", 128, 128, 8, "grayscale-8", False, "illustrative", 1))
            for a in p["assets"].values():
                self.assertEqual(a["sha256"], ASSET_HASHES[a["id"]])
                self.assertTrue((LIBRARY / a["path"]).resolve().is_relative_to(LIBRARY.resolve()))
                self.assertEqual(hashlib.sha256((LIBRARY / a["path"]).read_bytes()).hexdigest(), a["sha256"])

    def test_minimal_png_binary_contract_and_exact_complements(self):
        for p in self.manifest["presets"]:
            dark, light = self.codes(p), self.codes(p, "light")
            self.assertEqual(set(dark), {0, 255})
            self.assertEqual(set(light), {0, 255})
            self.assertEqual(light, bytes(255 - c for c in dark))

    def test_stdlib_regeneration_matches_exact_png_bytes_and_hashes(self):
        generated = generator().generated_assets()
        self.assertEqual(len(generated), 4)
        self.assertEqual(tuple(generated), tuple(a["path"] for a in presets.preset_registry().values()))
        for p in self.manifest["presets"]:
            for a in p["assets"].values():
                self.assertEqual(generated[a["path"]], (LIBRARY / a["path"]).read_bytes())
                self.assertEqual(hashlib.sha256(generated[a["path"]]).hexdigest(), a["sha256"])

    def test_qr_payload_matrix_and_pinned_hashes(self):
        self.assertEqual(self.qr["payload"], PAYLOAD)
        self.assertEqual(self.matrix["payload"], PAYLOAD)
        self.assertEqual((self.matrix["model"], self.matrix["qr_version"], self.matrix["ecc"],
                          self.matrix["mode"], self.matrix["mask_pattern"]), (2, 4, "M", "byte", 2))
        self.assertEqual(len(self.rows), 33)
        self.assertTrue(all(len(r) == 33 and set(r) <= {"0", "1"} for r in self.rows))
        self.assertEqual(hashlib.sha256(bytes(int(c) for r in self.rows for c in r)).hexdigest(), MATRIX_HASH)
        self.assertEqual(self.qr["matrix"]["module_bytes_sha256"], MATRIX_HASH)
        self.assertEqual(hashlib.sha256((LIBRARY / self.qr["matrix"]["path"]).read_bytes()).hexdigest(),
                         self.qr["matrix"]["sha256"])

    def test_qr_exact_pitch_full_canvas_and_quiet_zone(self):
        codes = self.codes(self.qr)
        self.assertEqual((33 + 8) * 3, 123)
        self.assertEqual((128 - 123) // 2 + 4 * 3, 14)
        for y in range(128):
            for x in range(128):
                expected = int(self.rows[(y - 14) // 3][(x - 14) // 3]) * 255 if (
                    14 <= x < 113 and 14 <= y < 113) else 0
                self.assertEqual(codes[y * 128 + x], expected)
        g = self.qr["geometry"]
        self.assertEqual(g["symbol_x"], [14, 113])
        self.assertEqual(g["symbol_y"], [14, 113])
        self.assertEqual(g["canvas_margins"], dict(left=14, top=14, right=15, bottom=15))
        self.assertGreaterEqual(min(g["canvas_margins"].values()), 4 * 3)

    def test_qr_finders_and_white_separators(self):
        for ox, oy in ((0, 0), (26, 0), (0, 26)):
            for y in range(-1, 8):
                for x in range(-1, 8):
                    if not (0 <= ox + x < 33 and 0 <= oy + y < 33):
                        continue
                    dark = (0 <= x <= 6 and 0 <= y <= 6 and
                            (x in (0, 6) or y in (0, 6) or (2 <= x <= 4 and 2 <= y <= 4)))
                    self.assertEqual(int(self.rows[oy + y][ox + x]), int(dark))

    def test_qr_timing_alignment_and_required_dark_module(self):
        for i in range(8, 25):
            self.assertEqual(int(self.rows[6][i]), int(i % 2 == 0))
            self.assertEqual(int(self.rows[i][6]), int(i % 2 == 0))
        for y in range(24, 29):
            for x in range(24, 29):
                self.assertEqual(int(self.rows[y][x]), int(max(abs(x - 26), abs(y - 26)) != 1))
        self.assertEqual(self.rows[4 * 4 + 9][8], "1")

    def test_qr_both_bch_format_copies_and_version_size(self):
        # ECC M = 00, mask 010. Independently divide by BCH generator 0x537.
        data = (0b00 << 3) | 2
        remainder = data << 10
        for shift in range(14, 9, -1):
            if remainder & (1 << shift):
                remainder ^= 0x537 << (shift - 10)
        expected = ((data << 10) | remainder) ^ 0x5412
        a = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14-i, 8) for i in range(9, 15)]
        b = [(32-i, 8) for i in range(8)] + [(8, 18+i) for i in range(8, 15)]
        for coords in (a, b):
            self.assertEqual(sum(int(self.rows[y][x]) << i for i, (x, y) in enumerate(coords)), expected)
        self.assertEqual((len(self.rows) - 17) // 4, 4)
        self.assertIn("No separate version-information blocks", self.qr["geometry"]["version_information"])

    def test_qr_retained_independent_decoder_evidence(self):
        ref = self.qr["verification"]
        data = (LIBRARY / ref["evidence_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), ref["evidence_sha256"])
        evidence = json.loads(data)
        self.assertEqual(evidence["result"], "PASS")
        self.assertEqual(evidence["decoded_payload"], PAYLOAD)
        self.assertEqual(evidence["encoder"]["version"], "1.8.0")
        self.assertEqual(evidence["decoder"]["version"], "4.13.0")
        self.assertEqual(evidence["verification_date"], "2026-10-08")
        self.assertFalse(evidence["resampling"])
        self.assertFalse(evidence["network_access"])
        self.assertEqual(evidence["input_size"], [128, 128])
        self.assertEqual(evidence["asset"], self.qr["assets"]["light"]["path"])
        self.assertEqual(evidence["asset_sha256"], self.qr["assets"]["light"]["sha256"])

    def test_upc_check_digit_and_independent_digit_encoding(self):
        digits = self.upc["upc"]
        self.assertEqual(digits, "000000000000")
        self.assertEqual(self.upc["verification"]["check_digit"], 0)
        self.assertEqual(self.upc["verification"]["weighted_sum_first_11"], 0)
        self.assertEqual(set(self.upc["provenance"]), {"kind", "source", "encoding_reference"})
        self.assertEqual(self.upc["provenance"]["kind"], "synthetic/demo barcode")
        odd = sum(map(int, digits[:11:2]))
        even = sum(map(int, digits[1:11:2]))
        self.assertEqual(odd * 3 + even, 0)
        self.assertEqual((10 - (odd * 3 + even) % 10) % 10, 0)
        # Independent run-width table, alternating space/bar on left, bar/space on right.
        widths = ("3211", "2221", "2122", "1411", "1132", "1231", "1114", "1312", "1213", "3112")
        def encode(c, right=False):
            return "".join(str((i + int(right)) % 2) * int(n) for i, n in enumerate(widths[int(c)]))
        expected = "101" + "".join(encode(c) for c in digits[:6]) + "01010" + "".join(encode(c, True) for c in digits[6:]) + "101"
        self.assertEqual(expected, UPC_ORACLE)
        self.assertEqual(self.upc["modules"], expected)
        self.assertEqual(generator().upc_modules(digits), expected)
        self.assertEqual(len(expected), 95)
        self.assertEqual((expected[:3], expected[45:50], expected[-3:]), ("101", "01010", "101"))

    def test_upc_full_canvas_quiet_zones_and_extended_first_last_digits(self):
        actual = self.codes(self.upc)
        for y in range(128):
            for x in range(128):
                m = x - 16
                extended = m < 10 or 45 <= m < 50 or m >= 85
                expected = 255 if (0 <= m < 95 and UPC_ORACLE[m] == "1" and
                                   27 <= y < (101 if extended else 96)) else 0
                self.assertEqual(actual[y * 128 + x], expected)
        self.assertEqual(actual[50 * 128 + 16:50 * 128 + 111], bytes(int(c) * 255 for c in UPC_ORACLE))
        self.assertFalse(any(actual[101 * 128:]))  # no human-readable digit raster
        self.assertEqual(self.upc["geometry"]["quiet_zone_cells_left"], 16)
        self.assertEqual(self.upc["geometry"]["quiet_zone_cells_right"], 17)

    def test_upc_invalid_digits_fail_generation(self):
        for bad in ("000000000001", "00000000000", "0000000000000", "x00000000000", None):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                generator().upc_modules(bad)

    def test_original_sixteen_match_retained_authority(self):
        root = ROOT / "studies/STUDY-0001/reference-fields"
        pairs = json.loads((root / "pairs.json").read_text())["pairs"]
        count = 0
        for pair in pairs:
            for kind in ("source", "inverse"):
                self.assertEqual(hashlib.sha256((root / pair[kind + "_filename"]).read_bytes()).hexdigest(),
                                 pair[kind + "_sha256"])
                count += 1
        self.assertEqual(count, 16)


if __name__ == "__main__":
    unittest.main()
