from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from conditioning_layers.adapters.prediction_mixing import (
    PREDICTION_MIXING_EXECUTION_PROFILE,
)
from conditioning_layers.assets import (
    InspectionLimits,
    InspectedChannelProfile,
    InspectedValueKind,
    inspect_document_field,
    inspect_field_asset,
    to_field_asset_profile,
)
from conditioning_layers.domain import InfluenceFieldAssetReference, PromptLayer


def chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png_bytes(
    width: int,
    height: int,
    samples: bytes,
    *,
    color_type: int = 0,
    bit_depth: int = 8,
    before_idat: tuple[tuple[bytes, bytes], ...] = (),
    interlace: int = 0,
) -> bytes:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    sample_bytes = 2 if bit_depth == 16 else 1
    row_size = width * channels * sample_bytes
    assert len(samples) == row_size * height
    raw = b"".join(
        b"\x00" + samples[offset : offset + row_size]
        for offset in range(0, len(samples), row_size)
    )
    header = struct.pack(
        ">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + b"".join(chunk(kind, data) for kind, data in before_idat)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def filtered_grayscale_png(filter_type: int) -> bytes:
    width = 3
    rows = (bytes([10, 20, 30]), bytes([40, 50, 60]))
    previous = bytes(width)
    encoded_rows: list[bytes] = []
    for row in rows:
        encoded = bytearray(width)
        for index, value in enumerate(row):
            left = row[index - 1] if index else 0
            above = previous[index]
            upper_left = previous[index - 1] if index else 0
            if filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            else:
                estimate = left + above - upper_left
                distances = (
                    abs(estimate - left),
                    abs(estimate - above),
                    abs(estimate - upper_left),
                )
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            encoded[index] = (value - predictor) & 0xFF
        encoded_rows.append(bytes([filter_type]) + encoded)
        previous = row
    header = struct.pack(">IIBBBBB", width, 2, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(encoded_rows)))
        + chunk(b"IEND", b"")
    )
def write_png(
    root: Path,
    relative: str,
    width: int,
    height: int,
    samples: bytes,
    **kwargs: object,
) -> tuple[Path, str]:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    data = png_bytes(width, height, samples, **kwargs)  # type: ignore[arg-type]
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def layer(
    relative: str = "fields/field.png",
    *,
    checksum: str | None = None,
    visible: bool = True,
    layer_id: str = "field",
) -> PromptLayer:
    return PromptLayer(
        layer_id=layer_id,
        name=layer_id,
        prompt_text=f"Prompt {layer_id}",
        visible=visible,
        strength=1.0,
        influence_field=InfluenceFieldAssetReference(relative, checksum),
    )


def profile_for(width: int, height: int):
    return replace(
        PREDICTION_MIXING_EXECUTION_PROFILE,
        expected_field_width=width,
        expected_field_height=height,
    )


def codes(findings: tuple[object, ...]) -> set[str]:
    return {finding.code for finding in findings}  # type: ignore[attr-defined]


class AcceptedAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def inspect(self, samples: bytes, **png_options: object):
        _, checksum = write_png(
            self.root, "fields/field.png", 2, 2, samples, **png_options
        )
        return inspect_field_asset(
            self.root,
            layer(checksum=checksum),
            execution_profile=profile_for(2, 2),
        )

    def test_binary_grayscale_measurements_and_exact_checksum(self) -> None:
        result = self.inspect(bytes([0, 255, 0, 255]))

        self.assertTrue(result.successful)
        self.assertTrue(result.certified, result.errors)
        self.assertEqual(result.profile.checksum, result.checksum)  # type: ignore[union-attr]
        self.assertEqual(result.profile.channel_count, 1)  # type: ignore[union-attr]
        self.assertIs(  # type: ignore[union-attr]
            result.profile.channel_profile, InspectedChannelProfile.GRAYSCALE_8
        )
        self.assertIs(result.profile.value_kind, InspectedValueKind.BINARY)  # type: ignore[union-attr]
        self.assertEqual(result.profile.minimum_normalized_value, 0.0)  # type: ignore[union-attr]
        self.assertEqual(result.profile.maximum_normalized_value, 1.0)  # type: ignore[union-attr]
        self.assertEqual(result.profile.distinct_value_count, 2)  # type: ignore[union-attr]
        self.assertEqual(result.profile.zero_value_count, 2)  # type: ignore[union-attr]
        self.assertEqual(result.profile.full_value_count, 2)  # type: ignore[union-attr]
        self.assertEqual(result.profile.nonzero_value_count, 2)  # type: ignore[union-attr]
        self.assertIn("asset.inspected", codes(result.information))

    def test_continuous_grayscale_uses_exact_value_over_255(self) -> None:
        result = self.inspect(bytes([0, 64, 128, 255]))

        self.assertIs(result.profile.value_kind, InspectedValueKind.CONTINUOUS)  # type: ignore[union-attr]
        self.assertEqual(result.profile.minimum_normalized_value, 0 / 255)  # type: ignore[union-attr]
        self.assertEqual(result.profile.maximum_normalized_value, 255 / 255)  # type: ignore[union-attr]
        self.assertEqual(result.profile.distinct_value_count, 4)  # type: ignore[union-attr]

    def test_binary_identical_rgb_is_accepted_without_channel_conversion(self) -> None:
        values = bytes([0, 0, 0, 255, 255, 255, 0, 0, 0, 255, 255, 255])
        result = self.inspect(values, color_type=2)

        self.assertEqual(result.profile.channel_count, 3)  # type: ignore[union-attr]
        self.assertIs(  # type: ignore[union-attr]
            result.profile.channel_profile, InspectedChannelProfile.RGB_IDENTICAL_8
        )
        self.assertIs(result.profile.value_kind, InspectedValueKind.BINARY)  # type: ignore[union-attr]

    def test_continuous_identical_rgb_is_accepted(self) -> None:
        values = bytes(component for value in (0, 1, 128, 255) for component in (value,) * 3)
        result = self.inspect(values, color_type=2)

        self.assertTrue(result.certified)
        self.assertIs(result.profile.value_kind, InspectedValueKind.CONTINUOUS)  # type: ignore[union-attr]
        self.assertEqual(result.profile.distinct_value_count, 4)  # type: ignore[union-attr]

    def test_all_standard_row_filters_decode_to_original_values(self) -> None:
        path = self.root / "fields" / "field.png"
        path.parent.mkdir()
        for filter_type in (1, 2, 3, 4):
            with self.subTest(filter_type=filter_type):
                data = filtered_grayscale_png(filter_type)
                path.write_bytes(data)
                result = inspect_field_asset(
                    self.root,
                    layer(checksum=hashlib.sha256(data).hexdigest()),
                    execution_profile=profile_for(3, 2),
                )
                self.assertTrue(result.certified, result.errors)
                self.assertEqual(result.profile.minimum_normalized_value, 10 / 255)  # type: ignore[union-attr]
                self.assertEqual(result.profile.maximum_normalized_value, 60 / 255)  # type: ignore[union-attr]

    def test_rgb_with_valid_optional_palette_is_accepted(self) -> None:
        values = bytes(component for value in (0, 64, 128, 255) for component in (value,) * 3)
        result = self.inspect(
            values,
            color_type=2,
            before_idat=((b"PLTE", b"\x00\x00\x00\xff\xff\xff"),),
        )
        self.assertTrue(result.certified, result.errors)

    def test_constant_zero_and_one_are_binary_with_warning(self) -> None:
        for value in (0, 255):
            with self.subTest(value=value):
                result = self.inspect(bytes([value] * 4))
                self.assertTrue(result.certified)
                self.assertIs(result.profile.value_kind, InspectedValueKind.BINARY)  # type: ignore[union-attr]
                self.assertIn("asset.constant_field", codes(result.warnings))

    def test_result_models_are_immutable_and_deterministic(self) -> None:
        _, checksum = write_png(
            self.root, "fields/field.png", 2, 2, bytes([0, 64, 128, 255])
        )
        field = layer(checksum=checksum)
        first = inspect_field_asset(
            self.root, field, execution_profile=profile_for(2, 2)
        )
        second = inspect_field_asset(
            self.root, field, execution_profile=profile_for(2, 2)
        )

        self.assertEqual(first, second)
        with self.assertRaises(FrozenInstanceError):
            first.certified = False  # type: ignore[misc]

    def test_document_path_uses_persistence_owned_asset_root(self) -> None:
        document = self.root / "scene.conditioning.json"
        asset_root = self.root / "scene.conditioning.assets"
        _, checksum = write_png(
            asset_root, "fields/field.png", 2, 2, bytes([0, 64, 128, 255])
        )

        result = inspect_document_field(
            document,
            layer(checksum=checksum),
            execution_profile=profile_for(2, 2),
        )

        self.assertTrue(result.certified, result.errors)


class RejectedAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_rejected(self, expected: str, field: PromptLayer | None = None) -> None:
        result = inspect_field_asset(
            self.root,
            field or layer(checksum=None),
            execution_profile=profile_for(1, 1),
        )
        self.assertFalse(result.certified)
        self.assertIn(expected, codes(result.errors))

    def test_missing_file(self) -> None:
        self.assert_rejected("asset.not_found")

    def test_directory(self) -> None:
        (self.root / "fields" / "field.png").mkdir(parents=True)
        self.assert_rejected("asset.not_file")

    def test_malformed_and_truncated_png(self) -> None:
        path = self.root / "fields" / "field.png"
        path.parent.mkdir()
        for data in (b"not png", png_bytes(1, 1, b"\x00")[:-5]):
            with self.subTest(data=data[:8]):
                path.write_bytes(data)
                self.assert_rejected("asset.invalid_png")

    def test_chunk_crc_mismatch_is_invalid(self) -> None:
        data = bytearray(png_bytes(1, 1, b"\x00"))
        data[-1] ^= 1
        path = self.root / "fields" / "field.png"
        path.parent.mkdir()
        path.write_bytes(data)
        self.assert_rejected("asset.invalid_png")

    def test_palette_rgba_grayscale_alpha_and_16bit_are_rejected(self) -> None:
        cases = (
            (3, 8, b"\x00", ((b"PLTE", b"\x00\x00\x00"),)),
            (6, 8, bytes(4), ()),
            (4, 8, bytes(2), ()),
            (0, 16, bytes(2), ()),
        )
        path = self.root / "fields" / "field.png"
        path.parent.mkdir()
        for color_type, bit_depth, samples, extra in cases:
            with self.subTest(color_type=color_type, bit_depth=bit_depth):
                path.write_bytes(
                    png_bytes(
                        1,
                        1,
                        samples,
                        color_type=color_type,
                        bit_depth=bit_depth,
                        before_idat=extra,
                    )
                )
                self.assert_rejected("asset.unsupported_mode")

    def test_nonidentical_rgb_is_rejected(self) -> None:
        write_png(
            self.root,
            "fields/field.png",
            1,
            1,
            bytes([1, 2, 1]),
            color_type=2,
        )
        self.assert_rejected("asset.rgb_channels_differ")

    def test_animated_interlaced_and_orientation_metadata_are_rejected(self) -> None:
        cases = (
            png_bytes(
                1,
                1,
                b"\x00",
                before_idat=((b"acTL", struct.pack(">II", 1, 0)),),
            ),
            png_bytes(1, 1, b"\x00", interlace=1),
            png_bytes(1, 1, b"\x00", before_idat=((b"eXIf", b"orientation"),)),
        )
        path = self.root / "fields" / "field.png"
        path.parent.mkdir()
        for data in cases:
            with self.subTest(data_length=len(data)):
                path.write_bytes(data)
                self.assert_rejected("asset.unsupported_mode")

    def test_unsupported_extension(self) -> None:
        path = self.root / "fields" / "field.jpg"
        path.parent.mkdir()
        path.write_bytes(b"data")
        self.assert_rejected(
            "asset.unsupported_format", layer("fields/field.jpg", checksum=None)
        )

    def test_unsafe_paths(self) -> None:
        for reference in ("../field.png", "C:/field.png", "/field.png"):
            with self.subTest(reference=reference):
                self.assert_rejected(
                    "asset.path_escape", layer(reference, checksum=None)
                )

    def test_symlink_escape_where_supported(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside.png"
        outside.write_bytes(png_bytes(1, 1, b"\x00"))
        link = self.root / "fields" / "field.png"
        link.parent.mkdir()
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        finally:
            self.addCleanup(outside.unlink, missing_ok=True)
        self.assert_rejected("asset.symlink_escape")

    def test_file_and_dimension_resource_limits(self) -> None:
        path = self.root / "fields" / "field.png"
        path.parent.mkdir()
        path.write_bytes(png_bytes(1, 1, b"\x00"))
        tiny_file_limit = InspectionLimits(maximum_file_bytes=10)
        result = inspect_field_asset(
            self.root,
            layer(checksum=None),
            execution_profile=profile_for(1, 1),
            limits=tiny_file_limit,
        )
        self.assertIn("asset.resource_limit", codes(result.errors))

        path.write_bytes(png_bytes(2, 1, b"\x00\xff"))
        dimension_limit = InspectionLimits(maximum_width=1)
        result = inspect_field_asset(
            self.root,
            layer(checksum=None),
            execution_profile=profile_for(2, 1),
            limits=dimension_limit,
        )
        self.assertIn("asset.resource_limit", codes(result.errors))

    def test_checksum_mismatch_blocks_certification_but_retains_measurements(self) -> None:
        write_png(self.root, "fields/field.png", 1, 1, b"\x00")
        result = inspect_field_asset(
            self.root,
            layer(checksum="f" * 64),
            execution_profile=profile_for(1, 1),
        )

        self.assertTrue(result.successful)
        self.assertFalse(result.certified)
        self.assertIsNotNone(result.profile)
        self.assertIn("asset.checksum_mismatch", codes(result.errors))

    def test_malformed_document_checksum_is_structured(self) -> None:
        write_png(self.root, "fields/field.png", 1, 1, b"\x00")
        result = inspect_field_asset(
            self.root,
            layer(checksum="bad"),
            execution_profile=profile_for(1, 1),
        )
        self.assertFalse(result.certified)
        self.assertIn("asset.checksum_invalid", codes(result.errors))


class DimensionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_128_by_128_matches(self) -> None:
        _, checksum = write_png(
            self.root, "fields/field.png", 128, 128, bytes(128 * 128)
        )
        result = inspect_field_asset(self.root, layer(checksum=checksum))

        self.assertTrue(result.dimension_validation.matches)  # type: ignore[union-attr]
        self.assertTrue(result.certified)

    def test_wrong_width_and_height_report_expected_and_observed(self) -> None:
        for width, height in ((127, 128), (128, 127)):
            with self.subTest(width=width, height=height):
                _, checksum = write_png(
                    self.root,
                    "fields/field.png",
                    width,
                    height,
                    bytes(width * height),
                )
                result = inspect_field_asset(self.root, layer(checksum=checksum))
                validation = result.dimension_validation
                self.assertFalse(validation.matches)  # type: ignore[union-attr]
                self.assertEqual((validation.expected_width, validation.expected_height), (128, 128))  # type: ignore[union-attr]
                self.assertEqual((validation.observed_width, validation.observed_height), (width, height))  # type: ignore[union-attr]
                self.assertIn("asset.dimensions", codes(result.errors))
                self.assertIsNone(to_field_asset_profile(result))


if __name__ == "__main__":
    unittest.main()
