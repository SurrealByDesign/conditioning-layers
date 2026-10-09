from __future__ import annotations

import binascii
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[3]
LIBRARY_ROOT = ROOT / "influence-field-library" / "v1"
GENERATOR_PATH = LIBRARY_ROOT / "generators" / "generate_library.py"
SCHEMA_PATH = ROOT / "schemas" / "influence-field-family-manifest.v1.schema.json"
FAMILY_ID_PATTERN = re.compile(r"^(two|three)-layer\.[a-z0-9-]+\.v1$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def load_generator():
    spec = importlib.util.spec_from_file_location("influence_field_library_v1_generator", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Influence Field Library generator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_catalog(root: Path = LIBRARY_ROOT) -> dict:
    return json.loads((root / "library-manifest.json").read_text(encoding="utf-8"))


def load_manifests(root: Path = LIBRARY_ROOT) -> list[dict]:
    catalog = load_catalog(root)
    return [
        json.loads((root / record["manifest_filename"]).read_text(encoding="utf-8"))
        for record in catalog["families"]
    ]


def referenced_generated_files(root: Path) -> set[Path]:
    relative = {Path("library-manifest.json")}
    catalog = load_catalog(root)
    for record in catalog["families"]:
        manifest_relative = Path(record["manifest_filename"])
        relative.add(manifest_relative)
        manifest = json.loads((root / manifest_relative).read_text(encoding="utf-8"))
        for entry in (
            manifest["fields"]
            + manifest["pixel_complements"]
            + [manifest["preview"]]
            + manifest["compatible_workflows"]
        ):
            relative.add(Path(entry["filename"]))
    return relative


def decode_grayscale8(path: Path) -> tuple[int, int, bytes, tuple[str, ...]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"not a PNG: {path}")
    offset = 8
    chunks: list[str] = []
    idat = bytearray()
    width = height = 0
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])[0]
        if binascii.crc32(chunk_type + payload) != crc:
            raise AssertionError(f"bad PNG CRC: {path}")
        name = chunk_type.decode("ascii")
        chunks.append(name)
        if name == "IHDR":
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (bit_depth, color_type, compression, filtering, interlace) != (8, 0, 0, 0, 0):
                raise AssertionError(f"unexpected PNG profile: {path}")
        elif name == "IDAT":
            idat.extend(payload)
        elif name == "IEND":
            break
        offset += 12 + length
    scanlines = zlib.decompress(bytes(idat))
    row_size = width + 1
    rows = []
    for y in range(height):
        row = scanlines[y * row_size : (y + 1) * row_size]
        if not row or row[0] != 0:
            raise AssertionError(f"PNG does not use deterministic filter 0: {path}")
        rows.append(row[1:])
    return width, height, b"".join(rows), tuple(chunks)


class InfluenceFieldLibraryTests(unittest.TestCase):
    def test_pixel_geometry_matches_documented_orientation_and_support(self) -> None:
        # Independent pixel-coordinate expectations, not generator output.
        for manifest in load_manifests():
            family = manifest["pattern_family_id"]
            fields = [decode_grayscale8(LIBRARY_ROOT / f["filename"])[2] for f in manifest["fields"]]
            counts = [0] * len(fields)
            for y in range(128):
                for x in range(128):
                    if family == "two-layer.left-right.v1":
                        owner = int(x >= 64)
                    elif family == "two-layer.top-bottom.v1":
                        owner = int(y >= 64)
                    elif family == "three-layer.vertical-thirds.v1":
                        owner = int(x >= 43) + int(x >= 85)
                    elif family == "three-layer.horizontal-thirds.v1":
                        owner = int(y >= 43) + int(y >= 85)
                    elif family == "three-layer.center-ring-outer.v1":
                        distance_squared = (2 * x - 127) ** 2 + (2 * y - 127) ** 2
                        owner = int(distance_squared >= 48 ** 2) + int(distance_squared >= 96 ** 2)
                    else:
                        self.fail(f"Unqualified family geometry: {family}")
                    counts[owner] += 1
                    self.assertEqual(tuple(field[y * 128 + x] for field in fields),
                                     tuple(255 if i == owner else 0 for i in range(len(fields))),
                                     (family, x, y))
            expected_counts = ([8192, 8192] if len(fields) == 2 else
                               [1804, 5428, 9152] if "center-ring-outer" in family else
                               [5504, 5376, 5504])
            self.assertEqual(counts, expected_counts, family)

    def test_catalog_and_manifest_schema_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = set(schema["required"])
        self.assertEqual(schema["properties"]["schema_id"]["const"], "conditioning-layers.influence-field-family-manifest")
        catalog = load_catalog()
        self.assertEqual(catalog["library_version"], 1)
        self.assertEqual(len(catalog["families"]), 5)
        self.assertEqual(catalog["manifest_schema"]["filename"], "schemas/influence-field-family-manifest.v1.schema.json")
        self.assertEqual(catalog["manifest_schema"]["sha256"], sha256(SCHEMA_PATH))
        ids = set()
        for record, manifest in zip(catalog["families"], load_manifests(), strict=True):
            self.assertTrue(FAMILY_ID_PATTERN.fullmatch(record["pattern_family_id"]))
            self.assertNotIn(record["pattern_family_id"], ids)
            ids.add(record["pattern_family_id"])
            manifest_path = LIBRARY_ROOT / record["manifest_filename"]
            self.assertEqual(sha256(manifest_path), record["manifest_sha256"])
            self.assertTrue(required <= set(manifest))
            self.assertEqual(manifest["schema_id"], "conditioning-layers.influence-field-family-manifest")
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["pattern_family_id"], record["pattern_family_id"])
            self.assertEqual(manifest["support_status"], record["support_status"])
            self.assertEqual(manifest["support_status"], "validated-product-asset")
            self.assertEqual(len(manifest["fields"]), manifest["layer_count"])
            self.assertEqual(len(manifest["pixel_complements"]), manifest["layer_count"])
            self.assertIn(manifest["support_status"], {"validated-product-asset", "research-only", "illustrative", "unsupported"})

    def test_partition_and_exact_complement_properties(self) -> None:
        for manifest in load_manifests():
            with self.subTest(family=manifest["pattern_family_id"]):
                fields = {}
                for entry in manifest["fields"]:
                    width, height, pixels, chunks = decode_grayscale8(LIBRARY_ROOT / entry["filename"])
                    self.assertEqual((width, height), (128, 128))
                    self.assertEqual(chunks, ("IHDR", "IDAT", "IEND"))
                    self.assertLessEqual(set(pixels), {0, 255})
                    self.assertEqual(sha256(LIBRARY_ROOT / entry["filename"]), entry["sha256"])
                    fields[entry["asset_id"]] = pixels
                overlap = unassigned = 0
                for values in zip(*(fields[field_id] for field_id in fields), strict=True):
                    overlap += int(sum(value > 0 for value in values) > 1)
                    unassigned += int(all(value == 0 for value in values))
                    self.assertEqual(sum(values), 255)
                self.assertEqual(overlap, 0)
                self.assertEqual(unassigned, 0)
                relationship = manifest["partition_relationship"]
                self.assertEqual(relationship["overlap_pixel_count"], 0)
                self.assertEqual(relationship["unassigned_pixel_count"], 0)
                self.assertTrue(relationship["complete_coverage"])
                for entry in manifest["pixel_complements"]:
                    _width, _height, complement, chunks = decode_grayscale8(LIBRARY_ROOT / entry["filename"])
                    self.assertEqual((_width, _height), (128, 128))
                    self.assertEqual(len(complement), 128 * 128)
                    self.assertEqual(chunks, ("IHDR", "IDAT", "IEND"))
                    source = fields[entry["source_field_id"]]
                    expected_inverse = bytes(255 - value for value in source)
                    expected_sum = bytes(
                        sum(fields[field_id][index] for field_id in entry["equivalent_partition_sum"])
                        for index in range(128 * 128)
                    )
                    self.assertEqual(complement, expected_inverse)
                    self.assertEqual(complement, expected_sum)
                    self.assertEqual(sha256(LIBRARY_ROOT / entry["filename"]), entry["sha256"])

    def test_permutations_and_geometric_relationships_are_explicit(self) -> None:
        family_ids = {manifest["pattern_family_id"] for manifest in load_manifests()}
        for manifest in load_manifests():
            field_ids = tuple(entry["asset_id"] for entry in manifest["fields"])
            expected = {"".join(values) for values in itertools.permutations(field_ids)}
            observed = {entry["permutation_id"] for entry in manifest["assignment_permutations"]}
            self.assertEqual(observed, expected)
            for variant in manifest["geometric_variants"]:
                self.assertIn(variant["target_pattern_family_id"], family_ids)
                self.assertEqual(set(variant["source_to_target_field_mapping"]), set(field_ids))
                self.assertEqual(set(variant["source_to_target_field_mapping"].values()), set(field_ids))

    def test_previews_are_deterministic_non_field_grayscale_pngs(self) -> None:
        for manifest in load_manifests():
            entry = manifest["preview"]
            width, height, pixels, chunks = decode_grayscale8(LIBRARY_ROOT / entry["filename"])
            self.assertEqual((width, height), (128, 128))
            self.assertEqual(chunks, ("IHDR", "IDAT", "IEND"))
            expected_values = {80, 208} if manifest["layer_count"] == 2 else {64, 144, 224}
            self.assertEqual(set(pixels), expected_values)
            self.assertEqual(entry["role"], "composite-preview")
            self.assertEqual(sha256(LIBRARY_ROOT / entry["filename"]), entry["sha256"])

    def test_workflows_parse_are_portable_and_do_not_generate(self) -> None:
        forbidden = {"UNETLoader", "CLIPLoader", "CLIPTextEncode", "KSampler", "VAELoader", "VAEDecode", "SaveImage"}
        for manifest in load_manifests():
            workflow_entry = manifest["compatible_workflows"][0]
            workflow_path = LIBRARY_ROOT / workflow_entry["filename"]
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            self.assertEqual(sha256(workflow_path), workflow_entry["sha256"])
            node_types = {node["type"] for node in workflow["nodes"]}
            self.assertLessEqual(node_types, {"Note", "LoadImage", "PreviewImage"})
            self.assertFalse(node_types & forbidden)
            self.assertEqual(len(workflow["links"]), manifest["layer_count"])
            metadata = workflow["extra"]["conditioning_layers_library"]
            self.assertEqual(metadata["pattern_family_id"], manifest["pattern_family_id"])
            if manifest["layer_count"] == 3:
                self.assertEqual(metadata["classification"], "expected-rejection")
                self.assertEqual(metadata["execution_status"], "not-authorized")
            text = workflow_path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"[A-Za-z]:[\\/]")
            self.assertNotIn("/" + "Users/", text)
            self.assertNotIn("/" + "home/", text)

    def test_regeneration_is_byte_deterministic(self) -> None:
        generator = load_generator()
        expected_files = referenced_generated_files(LIBRARY_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            generated_root = Path(temporary) / "v1"
            generator.generate(generated_root)
            self.assertEqual(referenced_generated_files(generated_root), expected_files)
            # The retained generator reproduces the pre-P1A governance baseline.
            # Only these reviewed metadata edits may differ; all PNGs, workflows,
            # generator provenance and other manifest content remain byte-exact.
            catalog_path = generated_root / "library-manifest.json"
            catalog = load_catalog(generated_root)
            for record in catalog["families"][1:]:
                path = generated_root / record["manifest_filename"]
                raw = path.read_bytes().replace(
                    b'"support_status": "research-only"',
                    b'"support_status": "validated-product-asset"',
                )
                if record["pattern_family_id"] == "two-layer.top-bottom.v1":
                    raw = raw.replace(
                        b"This exact asset family has not completed product-path validation.",
                        b"P1A validates the exact partition assets through offline product staging, not rendered image quality.",
                    )
                path.write_bytes(raw)
                record["support_status"] = "validated-product-asset"
                record["manifest_sha256"] = sha256(path)
            catalog_path.write_bytes((json.dumps(catalog, indent=2, sort_keys=True) + "\n").encode())
            for relative in expected_files:
                self.assertEqual(
                    (generated_root / relative).read_bytes(),
                    (LIBRARY_ROOT / relative).read_bytes(),
                    relative.as_posix(),
                )

    def test_validated_left_right_asset_identities_match_existing_reference(self) -> None:
        self.assertEqual(
            sha256(LIBRARY_ROOT / "two-layer" / "left-right" / "field-a.png"),
            "0c519e60efdffbfebbbe2c60235a0f03fb10af8f33d1d3f59c900739ae0fd3e0",
        )
        self.assertEqual(
            sha256(LIBRARY_ROOT / "two-layer" / "left-right" / "field-b.png"),
            "b649d32ce6f7481291adaa4b7e68988ade1d9ec53e9624bbf52dd92be628ee4d",
        )

    def test_all_referenced_paths_and_hashes_are_portable(self) -> None:
        for root in (LIBRARY_ROOT,):
            for relative in referenced_generated_files(root):
                path_text = relative.as_posix()
                self.assertFalse(Path(path_text).is_absolute())
                self.assertNotIn("..", Path(path_text).parts)
                self.assertTrue((root / relative).is_file())
        for manifest in load_manifests():
            self.assertTrue(SHA256_PATTERN.fullmatch(manifest["generator"]["source_sha256"]))


if __name__ == "__main__":
    unittest.main()
