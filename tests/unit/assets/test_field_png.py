"""Strict shared PNG acceptance and byte-exact inline field round trips."""
import base64
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.assets.field_png import decode_field_data_url, encode_field_png, PREFIX
from conditioning_layers.assets.models import InspectionLimits
from conditioning_layers.assets.png_inspector import inspect_png_data, inspect_png_bytes
from field_png_fixtures import CODES, fixtures


class FieldPngTests(unittest.TestCase):
    def test_shared_reader_corpus(self):
        for case in fixtures():
            with self.subTest(name=case["name"]):
                if case["codes"] is None:
                    with self.assertRaisesRegex(ValueError, "128x128.*grayscale-8"):
                        decode_field_data_url(case["value"])
                else:
                    self.assertEqual(decode_field_data_url(case["value"]), bytes(case["codes"]))

    def test_all_codes_round_trip_and_minimal_deterministic_writer(self):
        for codes in (CODES, bytes(range(256)) * 64, bytes(16384), bytes([255]) * 16384):
            data = encode_field_png(codes)
            self.assertEqual(data, encode_field_png(codes))
            self.assertEqual(decode_field_data_url(PREFIX + base64.b64encode(data).decode()), codes)
            at, kinds = 8, []
            while at < len(data):
                length = int.from_bytes(data[at:at + 4], "big")
                kinds.append(data[at + 4:at + 8]); at += length + 12
            self.assertEqual(kinds, [b"IHDR", b"IDAT", b"IEND"])

    def test_file_and_memory_inspection_are_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "field.png"
            data = encode_field_png(CODES); path.write_bytes(data)
            args = dict(layer_id="field", relative_reference="field.png", limits=InspectionLimits())
            self.assertEqual(inspect_png_data(data, **args), inspect_png_bytes(path, **args))

    def test_writer_does_not_coerce_invalid_codes(self):
        for value in ([], bytes(16383), bytes(16385), None):
            with self.assertRaises(ValueError): encode_field_png(value)
