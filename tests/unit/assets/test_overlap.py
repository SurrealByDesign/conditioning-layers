from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from conditioning_layers.adapters.prediction_mixing import (
    OverlapAssessment,
    translate_prediction_mixing,
)
from conditioning_layers.assets import (
    CertifiedOverlap,
    inspect_document_pair,
    inspect_field_pair,
    to_field_asset_profile,
    to_overlap_assessment,
)
from conditioning_layers.capabilities import PREDICTION_MIXING_CAPABILITY
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
)

from test_inspection import codes, layer, profile_for, write_png


class OverlapAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def pair(self, first: bytes, second: bytes):
        _, checksum_a = write_png(
            self.root, "fields/a.png", len(first), 1, first
        )
        _, checksum_b = write_png(
            self.root, "fields/b.png", len(second), 1, second
        )
        return inspect_field_pair(
            self.root,
            layer("fields/a.png", checksum=checksum_a, layer_id="a"),
            layer("fields/b.png", checksum=checksum_b, layer_id="b"),
            execution_profile=profile_for(len(first), 1),
        )

    def test_exact_hard_complements_have_no_overlap(self) -> None:
        result = self.pair(bytes([255, 255, 0, 0]), bytes([0, 0, 255, 255]))
        evidence = result.overlap.evidence

        self.assertTrue(result.overlap.certified)
        self.assertIs(evidence.assessment, CertifiedOverlap.NO_OVERLAP)  # type: ignore[union-attr]
        self.assertEqual(evidence.overlap_pixel_count, 0)  # type: ignore[union-attr]
        self.assertEqual(evidence.overlap_fraction, 0.0)  # type: ignore[union-attr]
        self.assertEqual(evidence.minimum_pairwise_sum, 1.0)  # type: ignore[union-attr]
        self.assertEqual(evidence.maximum_pairwise_sum, 1.0)  # type: ignore[union-attr]
        self.assertTrue(evidence.exact_complements)  # type: ignore[union-attr]
        self.assertFalse(evidence.has_unassigned_pixels)  # type: ignore[union-attr]
        self.assertFalse(evidence.sums_exceed_one)  # type: ignore[union-attr]
        self.assertIn("overlap.none", codes(result.overlap.information))
        self.assertIn("overlap.exact_complements", codes(result.overlap.information))

    def test_nonoverlapping_gap_records_unassigned_pixels(self) -> None:
        result = self.pair(bytes([255, 0, 0]), bytes([0, 0, 255]))

        self.assertIs(result.overlap.evidence.assessment, CertifiedOverlap.NO_OVERLAP)  # type: ignore[union-attr]
        self.assertTrue(result.overlap.evidence.has_unassigned_pixels)  # type: ignore[union-attr]
        self.assertFalse(result.overlap.evidence.exact_complements)  # type: ignore[union-attr]
        self.assertIn("overlap.unassigned", codes(result.overlap.warnings))

    def test_one_pixel_overlap_is_exactly_counted(self) -> None:
        result = self.pair(bytes([255, 255, 0]), bytes([255, 0, 0]))

        self.assertIs(result.overlap.evidence.assessment, CertifiedOverlap.OVERLAP_PRESENT)  # type: ignore[union-attr]
        self.assertEqual(result.overlap.evidence.overlap_pixel_count, 1)  # type: ignore[union-attr]
        self.assertEqual(result.overlap.evidence.overlap_fraction, 1 / 3)  # type: ignore[union-attr]
        self.assertIn("overlap.present", codes(result.overlap.warnings))

    def test_continuous_overlap_and_sum_greater_than_one(self) -> None:
        result = self.pair(bytes([128, 64]), bytes([128, 200]))

        evidence = result.overlap.evidence
        self.assertEqual(evidence.overlap_pixel_count, 2)  # type: ignore[union-attr]
        self.assertEqual(evidence.minimum_pairwise_sum, 256 / 255)  # type: ignore[union-attr]
        self.assertEqual(evidence.maximum_pairwise_sum, 264 / 255)  # type: ignore[union-attr]
        self.assertTrue(evidence.sums_exceed_one)  # type: ignore[union-attr]
        self.assertIn("overlap.sum_exceeds_one", codes(result.overlap.warnings))

    def test_no_overlap_does_not_imply_complements(self) -> None:
        result = self.pair(bytes([1, 0]), bytes([0, 2]))

        self.assertIs(result.overlap.evidence.assessment, CertifiedOverlap.NO_OVERLAP)  # type: ignore[union-attr]
        self.assertFalse(result.overlap.evidence.exact_complements)  # type: ignore[union-attr]
        self.assertFalse(result.overlap.evidence.has_unassigned_pixels)  # type: ignore[union-attr]

    def test_input_digest_and_result_are_deterministic(self) -> None:
        first = self.pair(bytes([255, 0]), bytes([0, 255]))
        second = self.pair(bytes([255, 0]), bytes([0, 255]))

        self.assertEqual(first, second)
        self.assertEqual(len(first.overlap.input_digest), 64)  # type: ignore[arg-type]

    def test_document_path_uses_owned_asset_root_for_pair(self) -> None:
        document = self.root / "scene.conditioning.json"
        asset_root = self.root / "scene.conditioning.assets"
        _, checksum_a = write_png(asset_root, "fields/a.png", 2, 1, b"\xff\x00")
        _, checksum_b = write_png(asset_root, "fields/b.png", 2, 1, b"\x00\xff")
        result = inspect_document_pair(
            document,
            layer("fields/a.png", checksum=checksum_a, layer_id="a"),
            layer("fields/b.png", checksum=checksum_b, layer_id="b"),
            execution_profile=profile_for(2, 1),
        )
        self.assertTrue(result.overlap.certified, result.overlap.errors)

    def test_mismatched_pair_dimensions_has_no_assessment(self) -> None:
        _, checksum_a = write_png(self.root, "fields/a.png", 2, 1, b"\x00\xff")
        _, checksum_b = write_png(self.root, "fields/b.png", 1, 1, b"\xff")
        result = inspect_field_pair(
            self.root,
            layer("fields/a.png", checksum=checksum_a, layer_id="a"),
            layer("fields/b.png", checksum=checksum_b, layer_id="b"),
            execution_profile=profile_for(2, 1),
        )

        self.assertFalse(result.overlap.certified)
        self.assertIsNone(result.overlap.evidence)
        self.assertIn("overlap.dimensions", codes(result.overlap.errors))

    def test_failed_field_prevents_certification(self) -> None:
        _, checksum_a = write_png(self.root, "fields/a.png", 1, 1, b"\xff")
        result = inspect_field_pair(
            self.root,
            layer("fields/a.png", checksum=checksum_a, layer_id="a"),
            layer("fields/missing.png", checksum=None, layer_id="b"),
            execution_profile=profile_for(1, 1),
        )

        self.assertFalse(result.overlap.certified)
        self.assertIsNone(to_overlap_assessment(result.overlap))
        self.assertIn("overlap.inspection_failed", codes(result.overlap.errors))


class AdapterConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def document_and_pair(self, second: bytes):
        first = bytes([255, 255, 0, 0])
        _, checksum_a = write_png(self.root, "fields/a.png", 4, 1, first)
        _, checksum_b = write_png(self.root, "fields/b.png", 4, 1, second)
        layers = (
            layer("fields/a.png", checksum=checksum_a, layer_id="a"),
            layer("fields/b.png", checksum=checksum_b, layer_id="b"),
        )
        document = ConditioningDocument(
            version=CURRENT_PROTOTYPE_VERSION,
            document_id="document",
            base_prompt="A coherent studio scene",
            layers=layers,
            selected_adapter_id=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
            adapter_settings={},
        )
        pair = inspect_field_pair(
            self.root, *layers, execution_profile=profile_for(4, 1)
        )
        profiles = tuple(to_field_asset_profile(item) for item in pair.fields)
        return document, pair, profiles

    def test_conversion_preserves_references_checksums_and_no_overlap(self) -> None:
        document, pair, profiles = self.document_and_pair(bytes([0, 0, 255, 255]))

        self.assertTrue(all(profile is not None for profile in profiles))
        self.assertEqual(
            tuple(profile.relative_path for profile in profiles),  # type: ignore[union-attr]
            ("fields/a.png", "fields/b.png"),
        )
        self.assertEqual(
            tuple(profile.checksum for profile in profiles),  # type: ignore[union-attr]
            pair.overlap.checksums,
        )
        assessment = to_overlap_assessment(pair.overlap)
        self.assertIs(assessment, OverlapAssessment.NO_OVERLAP)
        translated = translate_prediction_mixing(
            document,
            profiles,  # type: ignore[arg-type]
            execution_profile=profile_for(4, 1),
            overlap_assessment=assessment,
        )
        self.assertFalse(translated.translated)
        self.assertIn("translation.execution_profile", codes(translated.errors))

    def test_verified_inputs_translate_under_frozen_dimensions(self) -> None:
        first = bytes([255] * (128 * 64) + [0] * (128 * 64))
        second = bytes([0] * (128 * 64) + [255] * (128 * 64))
        _, checksum_a = write_png(self.root, "fields/a.png", 128, 128, first)
        _, checksum_b = write_png(self.root, "fields/b.png", 128, 128, second)
        layers = (
            layer("fields/a.png", checksum=checksum_a, layer_id="a"),
            layer("fields/b.png", checksum=checksum_b, layer_id="b"),
        )
        document = ConditioningDocument(
            version=CURRENT_PROTOTYPE_VERSION,
            document_id="document",
            base_prompt="A coherent studio scene",
            layers=layers,
            selected_adapter_id=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
            adapter_settings={},
        )
        pair = inspect_field_pair(self.root, *layers)
        profiles = tuple(to_field_asset_profile(item) for item in pair.fields)

        translated = translate_prediction_mixing(
            document,
            profiles,  # type: ignore[arg-type]
            overlap_assessment=to_overlap_assessment(pair.overlap),
        )
        self.assertTrue(translated.translated, translated.errors)

    def test_verified_overlap_converts_and_translation_rejects(self) -> None:
        size = 128 * 128
        first = bytes([255] + [0] * (size - 1))
        second = bytes([255] + [0] * (size - 2) + [255])
        _, checksum_a = write_png(self.root, "fields/a.png", 128, 128, first)
        _, checksum_b = write_png(self.root, "fields/b.png", 128, 128, second)
        layers = (
            layer("fields/a.png", checksum=checksum_a, layer_id="a"),
            layer("fields/b.png", checksum=checksum_b, layer_id="b"),
        )
        document = ConditioningDocument(
            version=CURRENT_PROTOTYPE_VERSION,
            document_id="document",
            base_prompt="A coherent studio scene",
            layers=layers,
            selected_adapter_id=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
            adapter_settings={},
        )
        pair = inspect_field_pair(self.root, *layers)
        profiles = tuple(to_field_asset_profile(item) for item in pair.fields)
        assessment = to_overlap_assessment(pair.overlap)

        self.assertIs(assessment, OverlapAssessment.OVERLAP_PRESENT)
        translated = translate_prediction_mixing(
            document,
            profiles,  # type: ignore[arg-type]
            overlap_assessment=assessment,
        )
        self.assertFalse(translated.translated)
        self.assertIn("translation.overlap_present", codes(translated.errors))


if __name__ == "__main__":
    unittest.main()
