from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.assets import (
    DEFAULT_FIELD_RELATIONSHIP_POLICY,
    FIELD_RELATIONSHIP_CERTIFICATE_FORMAT,
    ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER,
    FieldOrientation,
    FieldPolarity,
    FieldRelationshipCertificationStatus,
    FieldRelationshipInput,
    FieldRelationshipPolicy,
    PartitionClassification,
    fingerprint_field_relationship_certificate,
    inspect_field_pair,
    inspect_field_relationships,
    serialize_field_relationship_certificate,
    to_overlap_assessment,
)
from conditioning_layers.adapters.prediction_mixing import OverlapAssessment

from test_inspection import layer, png_bytes, profile_for, write_png


def finding_codes(findings: tuple[object, ...]) -> set[str]:
    return {finding.code for finding in findings}  # type: ignore[attr-defined]


class RelationshipTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def inputs(
        self,
        samples: tuple[bytes, ...],
        *,
        width: int,
        height: int,
        ids: tuple[str, ...] | None = None,
        references: tuple[str, ...] | None = None,
        indexes: tuple[int | None, ...] | None = None,
    ) -> tuple[FieldRelationshipInput, ...]:
        ids = ids or tuple(chr(ord("a") + index) for index in range(len(samples)))
        references = references or tuple(f"fields/{item}.png" for item in ids)
        indexes = indexes or tuple(range(len(samples)))
        result: list[FieldRelationshipInput] = []
        for values, layer_id, reference, document_index in zip(
            samples, ids, references, indexes, strict=True
        ):
            _, checksum = write_png(
                self.root, reference, width, height, values
            )
            result.append(
                FieldRelationshipInput(
                    layer(
                        reference,
                        checksum=checksum,
                        layer_id=layer_id,
                    ),
                    document_index=document_index,
                )
            )
        return tuple(result)

    def inspect(
        self,
        inputs: tuple[FieldRelationshipInput, ...],
        width: int,
        height: int,
        *,
        policy: FieldRelationshipPolicy = DEFAULT_FIELD_RELATIONSHIP_POLICY,
    ):
        return inspect_field_relationships(
            self.root,
            inputs,
            execution_profile=profile_for(width, height),
            policy=policy,
        )


class DeterminismAndOrderingTests(RelationshipTestCase):
    def test_repeated_inspection_and_canonical_serialization_are_identical(self) -> None:
        inputs = self.inputs(
            (b"\xff\x00\x00", b"\x00\xff\x00", b"\x00\x00\xff"),
            width=3,
            height=1,
        )

        first = self.inspect(inputs, 3, 1)
        second = self.inspect(inputs, 3, 1)
        first_json = serialize_field_relationship_certificate(first.certificate)
        second_json = serialize_field_relationship_certificate(second.certificate)

        self.assertEqual(first, second)
        self.assertEqual(first_json, second_json)
        self.assertEqual(first.certificate.format_identifier, FIELD_RELATIONSHIP_CERTIFICATE_FORMAT)
        self.assertEqual(
            first.certificate.relationship_policy_identifier,
            ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER,
        )
        self.assertEqual(len(first.certificate.fingerprint), 64)
        self.assertEqual(
            first.certificate.fingerprint,
            fingerprint_field_relationship_certificate(first.certificate),
        )
        self.assertTrue(first_json.endswith("\n"))
        self.assertEqual(json.loads(first_json)["fingerprint"], first.certificate.fingerprint)
        self.assertNotIn(str(self.root), first_json)
        self.assertNotIn("timestamp", first_json.lower())
        self.assertNotIn("temporary", first_json.lower())
        self.assertEqual(first.certificate.shared_raster.width, 3)
        self.assertEqual(first.certificate.shared_raster.height, 1)
        self.assertEqual(first.certificate.shared_raster.pixel_count, 3)
        self.assertEqual(first.certificate.shared_raster.bit_depth, 8)
        self.assertEqual(
            first.certificate.shared_raster.positive_sample_threshold_normalized,
            0.0,
        )
        self.assertTrue(first.certificate.shared_raster.all_fields_satisfy)
        self.assertTrue(
            all(len(item.digest) == 64 for item in first.certificate.pairwise_evidence)
        )
        self.assertTrue(
            all(item.bit_depth == 8 for item in first.certificate.ordered_fields)
        )
        with self.assertRaises(FrozenInstanceError):
            first.certificate.status = FieldRelationshipCertificationStatus.UNCERTIFIED  # type: ignore[misc]

    def test_order_is_never_replaced_by_identity_or_hash_sorting(self) -> None:
        inputs = self.inputs(
            (b"\xff\x00\x00", b"\x00\xff\x00", b"\x00\x00\xff"),
            width=3,
            height=1,
            ids=("z-layer", "a-layer", "m-layer"),
            indexes=(9, 2, 5),
        )
        original = self.inspect(inputs, 3, 1)
        reordered = self.inspect((inputs[2], inputs[0], inputs[1]), 3, 1)

        self.assertEqual(
            tuple(item.layer_id for item in original.certificate.ordered_fields),
            ("z-layer", "a-layer", "m-layer"),
        )
        self.assertEqual(
            tuple(item.document_index for item in original.certificate.ordered_fields),
            (9, 2, 5),
        )
        self.assertEqual(
            tuple(
                (item.first_ordinal, item.second_ordinal)
                for item in original.certificate.pairwise_evidence
            ),
            ((0, 1), (0, 2), (1, 2)),
        )
        self.assertNotEqual(
            original.certificate.fingerprint,
            reordered.certificate.fingerprint,
        )

    def test_duplicate_grouping_is_deterministic_despite_mapping_construction(self) -> None:
        values = b"\xff\x00"
        _, checksum = write_png(self.root, "fields/shared.png", 2, 1, values)
        inputs = (
            FieldRelationshipInput(
                layer("fields/shared.png", checksum=checksum, layer_id="z"), 4
            ),
            FieldRelationshipInput(
                layer("fields/shared.png", checksum=checksum, layer_id="a"), 1
            ),
        )

        first = self.inspect(inputs, 2, 1)
        second = self.inspect(inputs, 2, 1)
        whole = first.certificate.whole_set_evidence

        self.assertEqual(first.certificate.fingerprint, second.certificate.fingerprint)
        self.assertEqual(whole.duplicate_hash_ordinal_groups, ((0, 1),))
        self.assertEqual(whole.duplicate_reference_ordinal_groups, ((0, 1),))


class OneAndTwoFieldTests(RelationshipTestCase):
    def test_one_field_records_gaps_histogram_and_no_pairs(self) -> None:
        inputs = self.inputs((b"\xff\x00\xff\x00",), width=4, height=1)

        result = self.inspect(inputs, 4, 1)
        whole = result.certificate.whole_set_evidence

        self.assertIs(result.certificate.status, FieldRelationshipCertificationStatus.CERTIFIED)
        self.assertEqual(result.certificate.pairwise_evidence, ())
        self.assertEqual(whole.gap_pixel_count, 2)
        self.assertEqual(whole.gap_fraction, 0.5)
        self.assertEqual(whole.simultaneous_active_count_histogram, (2, 2))
        self.assertEqual(whole.maximum_simultaneous_active_field_count, 1)
        self.assertIs(
            result.certificate.partition_classification,
            PartitionClassification.DISJOINT_WITH_GAPS,
        )

    def test_one_full_field_is_an_exact_complete_partition(self) -> None:
        result = self.inspect(
            self.inputs((b"\xff\xff",), width=2, height=1), 2, 1
        )

        self.assertTrue(result.certificate.whole_set_evidence.complete_coverage)
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION,
        )

    def test_two_exact_complements_match_historical_pair_projection(self) -> None:
        inputs = self.inputs(
            (b"\xff\xff\x00\x00", b"\x00\x00\xff\xff"),
            width=4,
            height=1,
        )
        certificate = self.inspect(inputs, 4, 1)
        pair = inspect_field_pair(
            self.root,
            inputs[0].layer,
            inputs[1].layer,
            execution_profile=profile_for(4, 1),
        )
        new_pair = certificate.certificate.pairwise_evidence[0]
        old_pair = pair.overlap.evidence

        self.assertTrue(new_pair.certified)
        self.assertEqual(new_pair.simultaneous_positive_pixel_count, old_pair.overlap_pixel_count)  # type: ignore[union-attr]
        self.assertEqual(new_pair.overlap_fraction, old_pair.overlap_fraction)  # type: ignore[union-attr]
        self.assertEqual(new_pair.minimum_normalized_pairwise_sum, old_pair.minimum_pairwise_sum)  # type: ignore[union-attr]
        self.assertEqual(new_pair.maximum_normalized_pairwise_sum, old_pair.maximum_pairwise_sum)  # type: ignore[union-attr]
        self.assertEqual(new_pair.exact_complements, old_pair.exact_complements)  # type: ignore[union-attr]
        self.assertIs(to_overlap_assessment(pair.overlap), OverlapAssessment.NO_OVERLAP)
        self.assertEqual(
            certificate.certificate.partition_classification,
            PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION,
        )

    def test_two_disjoint_fields_with_gaps_remain_distinct_from_partition(self) -> None:
        result = self.inspect(
            self.inputs((b"\xff\x00\x00", b"\x00\x00\xff"), width=3, height=1),
            3,
            1,
        )

        self.assertTrue(result.certificate.whole_set_evidence.mutual_exclusion)
        self.assertFalse(result.certificate.whole_set_evidence.complete_coverage)
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.DISJOINT_WITH_GAPS,
        )

    def test_two_overlapping_continuous_fields_record_exact_sums(self) -> None:
        result = self.inspect(
            self.inputs((bytes([128, 64]), bytes([128, 200])), width=2, height=1),
            2,
            1,
        )
        pair = result.certificate.pairwise_evidence[0]
        whole = result.certificate.whole_set_evidence

        self.assertEqual(pair.simultaneous_positive_pixel_count, 2)
        self.assertEqual(pair.minimum_normalized_pairwise_sum, 256 / 255)
        self.assertEqual(pair.maximum_normalized_pairwise_sum, 264 / 255)
        self.assertEqual(whole.sum_exceeds_policy_pixel_count, 2)
        self.assertEqual(whole.normalized_sum_policy_threshold, 1.0)
        self.assertEqual(whole.minimum_normalized_total_sum, 256 / 255)
        self.assertEqual(whole.maximum_normalized_total_sum, 264 / 255)
        self.assertEqual(whole.partition_sum_normalized_value, 1.0)
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.OVERLAPPING,
        )

    def test_complete_disjoint_continuous_fields_can_be_mixed_non_partition(self) -> None:
        result = self.inspect(
            self.inputs((bytes([128, 0]), bytes([0, 128])), width=2, height=1),
            2,
            1,
        )

        self.assertTrue(result.certificate.whole_set_evidence.complete_coverage)
        self.assertTrue(result.certificate.whole_set_evidence.mutual_exclusion)
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.MIXED_NON_PARTITION,
        )


class ThreeAndFourFieldTests(RelationshipTestCase):
    def test_exact_vertical_or_horizontal_three_way_partition(self) -> None:
        result = self.inspect(
            self.inputs(
                (
                    bytes([255, 0, 0, 255, 0, 0]),
                    bytes([0, 255, 0, 0, 255, 0]),
                    bytes([0, 0, 255, 0, 0, 255]),
                ),
                width=3,
                height=2,
            ),
            3,
            2,
        )

        self.assertEqual(result.certificate.status, FieldRelationshipCertificationStatus.CERTIFIED)
        self.assertEqual(
            result.certificate.whole_set_evidence.simultaneous_active_count_histogram,
            (0, 6, 0, 0),
        )
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION,
        )

    def test_center_ring_outer_three_way_partition(self) -> None:
        center = bytes([0, 0, 0, 0, 255, 0, 0, 0, 0])
        ring = bytes([0, 255, 0, 255, 0, 255, 0, 255, 0])
        outer = bytes([255, 0, 255, 0, 0, 0, 255, 0, 255])

        result = self.inspect(
            self.inputs((center, ring, outer), width=3, height=3), 3, 3
        )

        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION,
        )
        self.assertEqual(result.certificate.whole_set_evidence.partition_sum_pixel_count, 9)

    def test_three_way_gaps_and_incomplete_coverage(self) -> None:
        result = self.inspect(
            self.inputs(
                (b"\xff\x00\x00\x00", b"\x00\xff\x00\x00", b"\x00\x00\xff\x00"),
                width=4,
                height=1,
            ),
            4,
            1,
        )

        self.assertEqual(result.certificate.whole_set_evidence.gap_pixel_count, 1)
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.DISJOINT_WITH_GAPS,
        )

    def test_one_multiple_and_triple_overlap_are_distinguished_by_pair_matrix(self) -> None:
        cases = (
            (
                (b"\xff\x00", b"\xff\x00", b"\x00\xff"),
                (1, 0, 0),
                2,
            ),
            (
                (b"\xff\xff\x00", b"\xff\x00\xff", b"\x00\xff\xff"),
                (1, 1, 1),
                2,
            ),
            (
                (b"\xff", b"\xff", b"\xff"),
                (1, 1, 1),
                3,
            ),
        )
        for index, (samples, expected_pairs, expected_maximum) in enumerate(cases):
            with self.subTest(index=index):
                width = len(samples[0])
                inputs = self.inputs(
                    samples,
                    width=width,
                    height=1,
                    ids=(f"a{index}", f"b{index}", f"c{index}"),
                )
                result = self.inspect(inputs, width, 1)
                self.assertEqual(
                    tuple(
                        item.simultaneous_positive_pixel_count
                        for item in result.certificate.pairwise_evidence
                    ),
                    expected_pairs,
                )
                self.assertEqual(
                    result.certificate.whole_set_evidence.maximum_simultaneous_active_field_count,
                    expected_maximum,
                )
                self.assertEqual(
                    result.certificate.partition_classification,
                    PartitionClassification.OVERLAPPING,
                )

    def test_duplicate_bytes_are_reported_without_preventing_measurement(self) -> None:
        result = self.inspect(
            self.inputs((b"\xff\x00", b"\xff\x00", b"\x00\xff"), width=2, height=1),
            2,
            1,
        )

        self.assertEqual(
            result.certificate.whole_set_evidence.duplicate_hash_ordinal_groups,
            ((0, 1),),
        )
        self.assertIn("field_relationship.duplicate_hash", finding_codes(result.warnings))

    def test_mismatched_dimensions_and_invalid_encoding_fail_closed(self) -> None:
        _, checksum_a = write_png(self.root, "fields/a.png", 2, 1, b"\xff\x00")
        _, checksum_b = write_png(self.root, "fields/b.png", 3, 1, b"\x00\xff\x00")
        invalid_data = png_bytes(2, 1, b"\xff\x00\x00\xff\x00\x00\xff\xff", color_type=6)
        invalid_path = self.root / "fields" / "invalid.png"
        invalid_path.write_bytes(invalid_data)
        checksum_invalid = hashlib.sha256(invalid_data).hexdigest()
        inputs = (
            FieldRelationshipInput(layer("fields/a.png", checksum=checksum_a, layer_id="a"), 0),
            FieldRelationshipInput(layer("fields/b.png", checksum=checksum_b, layer_id="b"), 1),
            FieldRelationshipInput(layer("fields/invalid.png", checksum=checksum_invalid, layer_id="c"), 2),
        )

        result = self.inspect(inputs, 2, 1)

        self.assertEqual(result.certificate.status, FieldRelationshipCertificationStatus.UNCERTIFIED)
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.UNABLE_TO_CERTIFY,
        )
        self.assertEqual(len(result.certificate.pairwise_evidence), 3)
        self.assertIn("asset.unsupported_mode", finding_codes(result.errors))

    def test_four_field_partition_exposes_no_three_only_logic(self) -> None:
        result = self.inspect(
            self.inputs(
                (
                    b"\xff\x00\x00\x00",
                    b"\x00\xff\x00\x00",
                    b"\x00\x00\xff\x00",
                    b"\x00\x00\x00\xff",
                ),
                width=4,
                height=1,
            ),
            4,
            1,
        )

        self.assertEqual(len(result.certificate.ordered_fields), 4)
        self.assertEqual(len(result.certificate.pairwise_evidence), 6)
        self.assertEqual(
            result.certificate.whole_set_evidence.simultaneous_active_count_histogram,
            (0, 4, 0, 0, 0),
        )
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION,
        )


class IdentityMutationAndFailureTests(RelationshipTestCase):
    def test_source_byte_change_at_same_identity_changes_fingerprint(self) -> None:
        inputs = self.inputs((b"\xff\x00",), width=2, height=1)
        baseline = self.inspect(inputs, 2, 1).certificate.fingerprint
        _, checksum = write_png(self.root, "fields/a.png", 2, 1, b"\xff\x01")
        changed = (
            FieldRelationshipInput(
                replace(
                    inputs[0].layer,
                    influence_field=replace(
                        inputs[0].layer.influence_field,  # type: ignore[arg-type]
                        checksum=checksum,
                    ),
                ),
                document_index=0,
            ),
        )

        mutated = self.inspect(changed, 2, 1).certificate.fingerprint

        self.assertNotEqual(mutated, baseline)

    def test_field_identity_order_and_relationship_mutations_change_fingerprint(self) -> None:
        base_inputs = self.inputs(
            (b"\xff\x00\x00", b"\x00\xff\x00", b"\x00\x00\xff"),
            width=3,
            height=1,
        )
        baseline = self.inspect(base_inputs, 3, 1).certificate.fingerprint

        _, mutated_checksum = write_png(
            self.root, "fields/mutated.png", 3, 1, b"\xff\x00\xff"
        )
        source_mutation = base_inputs[:2] + (
            FieldRelationshipInput(
                layer("fields/mutated.png", checksum=mutated_checksum, layer_id="c"),
                2,
            ),
        )
        identity_mutation = (
            replace(base_inputs[0], layer=replace(base_inputs[0].layer, layer_id="renamed")),
            *base_inputs[1:],
        )
        index_mutation = (replace(base_inputs[0], document_index=10), *base_inputs[1:])
        _, copied_checksum = write_png(
            self.root, "fields/copied.png", 3, 1, b"\xff\x00\x00"
        )
        reference_mutation = (
            FieldRelationshipInput(
                layer("fields/copied.png", checksum=copied_checksum, layer_id="a"), 0
            ),
            *base_inputs[1:],
        )
        variants = (
            self.inspect(source_mutation, 3, 1).certificate.fingerprint,
            self.inspect((base_inputs[1], base_inputs[0], base_inputs[2]), 3, 1).certificate.fingerprint,
            self.inspect(identity_mutation, 3, 1).certificate.fingerprint,
            self.inspect(index_mutation, 3, 1).certificate.fingerprint,
            self.inspect(reference_mutation, 3, 1).certificate.fingerprint,
        )

        self.assertTrue(all(item != baseline for item in variants))
        self.assertEqual(len(set(variants)), len(variants))

    def test_policy_polarity_orientation_and_coverage_are_fingerprint_material(self) -> None:
        inputs = self.inputs((b"\xff\x00", b"\x00\xff"), width=2, height=1)
        certificate = self.inspect(inputs, 2, 1).certificate
        mutations = (
            replace(certificate, relationship_policy_version=2),
            replace(certificate, polarity=FieldPolarity(inverted=True)),
            replace(certificate, orientation=FieldOrientation(origin="bottom_left")),
            replace(
                certificate,
                whole_set_evidence=replace(
                    certificate.whole_set_evidence,
                    complete_coverage=False,
                    gap_pixel_count=1,
                    gap_fraction=0.5,
                ),
            ),
            replace(
                certificate,
                pairwise_evidence=(
                    replace(
                        certificate.pairwise_evidence[0],
                        simultaneous_positive_pixel_count=1,
                    ),
                ),
            ),
        )

        self.assertTrue(
            all(
                fingerprint_field_relationship_certificate(item)
                != certificate.fingerprint
                for item in mutations
            )
        )

    def test_empty_malformed_and_duplicate_identity_inputs_are_structured(self) -> None:
        empty = inspect_field_relationships(
            self.root,
            (),
            execution_profile=profile_for(1, 1),
        )
        malformed = inspect_field_relationships(
            self.root,
            (object(),),  # type: ignore[arg-type]
            execution_profile=profile_for(1, 1),
        )
        valid = self.inputs(
            (b"\xff", b"\x00"),
            width=1,
            height=1,
            ids=("same", "same"),
        )
        duplicate = self.inspect(valid, 1, 1)

        self.assertIn("field_relationship.inputs.empty", finding_codes(empty.errors))
        self.assertIn("field_relationship.input.invalid", finding_codes(malformed.errors))
        self.assertIn(
            "field_relationship.layer_id.duplicate",
            finding_codes(duplicate.errors),
        )
        self.assertEqual(empty.certificate.status, FieldRelationshipCertificationStatus.UNCERTIFIED)
        self.assertEqual(malformed.certificate.status, FieldRelationshipCertificationStatus.UNCERTIFIED)
        self.assertEqual(duplicate.certificate.status, FieldRelationshipCertificationStatus.UNCERTIFIED)

    def test_safe_measurements_survive_document_checksum_failure(self) -> None:
        inputs = self.inputs((b"\xff\x00", b"\x00\xff"), width=2, height=1)
        mismatched = (
            replace(
                inputs[0],
                layer=replace(
                    inputs[0].layer,
                    influence_field=replace(
                        inputs[0].layer.influence_field,  # type: ignore[arg-type]
                        checksum="0" * 64,
                    ),
                ),
            ),
            inputs[1],
        )

        result = self.inspect(mismatched, 2, 1)

        self.assertEqual(result.certificate.status, FieldRelationshipCertificationStatus.UNCERTIFIED)
        self.assertFalse(result.certificate.whole_set_evidence.certified)
        self.assertEqual(result.certificate.whole_set_evidence.gap_pixel_count, 0)
        self.assertEqual(result.certificate.whole_set_evidence.partition_sum_pixel_count, 2)
        self.assertEqual(
            result.certificate.partition_classification,
            PartitionClassification.UNABLE_TO_CERTIFY,
        )

    def test_frozen_policy_records_exact_polarity_and_orientation(self) -> None:
        result = self.inspect(
            self.inputs((b"\xff",), width=1, height=1), 1, 1
        )
        certificate = result.certificate

        self.assertEqual(certificate.polarity, DEFAULT_FIELD_RELATIONSHIP_POLICY.polarity)
        self.assertEqual(certificate.polarity.no_influence_sample, 0)
        self.assertEqual(certificate.polarity.full_influence_sample, 255)
        self.assertFalse(certificate.polarity.inverted)
        self.assertEqual(certificate.orientation.origin, "top_left")
        self.assertEqual(certificate.orientation.positive_x, "right")
        self.assertEqual(certificate.orientation.positive_y, "down")
        self.assertEqual(certificate.orientation.rotation_degrees, 0)
        self.assertFalse(certificate.orientation.mirrored_x)
        self.assertFalse(certificate.orientation.mirrored_y)
        self.assertEqual(certificate.orientation.resizing, "none")
        self.assertEqual(certificate.orientation.interpolation, "none")
        self.assertEqual(certificate.orientation.transformation, "none")


class NonDefaultPolicyTests(RelationshipTestCase):
    def test_nonzero_positive_threshold_changes_boundary_evidence_deterministically(self) -> None:
        inputs = self.inputs(
            (bytes([128, 127, 0]), bytes([0, 128, 127])),
            width=3,
            height=1,
        )
        policy = replace(
            DEFAULT_FIELD_RELATIONSHIP_POLICY,
            positive_sample_threshold=127,
        )

        default = self.inspect(inputs, 3, 1)
        first = self.inspect(inputs, 3, 1, policy=policy)
        second = self.inspect(inputs, 3, 1, policy=policy)

        self.assertEqual(
            default.certificate.partition_classification,
            PartitionClassification.OVERLAPPING,
        )
        self.assertEqual(
            default.certificate.whole_set_evidence.simultaneous_active_count_histogram,
            (0, 2, 1),
        )
        self.assertEqual(
            first.certificate.partition_classification,
            PartitionClassification.DISJOINT_WITH_GAPS,
        )
        self.assertEqual(
            first.certificate.whole_set_evidence.simultaneous_active_count_histogram,
            (1, 2, 0),
        )
        self.assertEqual(first.certificate.whole_set_evidence.gap_pixel_count, 1)
        self.assertEqual(
            first.certificate.shared_raster.positive_sample_threshold_normalized,
            127 / 255,
        )
        self.assertNotEqual(
            default.certificate.fingerprint,
            first.certificate.fingerprint,
        )
        self.assertEqual(first.certificate.fingerprint, second.certificate.fingerprint)

    def test_nondefault_normalized_partition_target_changes_classification_and_identity(self) -> None:
        inputs = self.inputs(
            (bytes([128, 0]), bytes([0, 128])),
            width=2,
            height=1,
        )
        policy = replace(
            DEFAULT_FIELD_RELATIONSHIP_POLICY,
            partition_sum_sample=128,
        )

        default = self.inspect(inputs, 2, 1)
        first = self.inspect(inputs, 2, 1, policy=policy)
        second = self.inspect(inputs, 2, 1, policy=policy)

        self.assertEqual(
            default.certificate.partition_classification,
            PartitionClassification.MIXED_NON_PARTITION,
        )
        self.assertEqual(
            first.certificate.partition_classification,
            PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION,
        )
        self.assertEqual(
            first.certificate.whole_set_evidence.partition_sum_normalized_value,
            128 / 255,
        )
        self.assertEqual(
            first.certificate.whole_set_evidence.partition_sum_pixel_count,
            2,
        )
        self.assertNotEqual(
            default.certificate.fingerprint,
            first.certificate.fingerprint,
        )
        self.assertEqual(first.certificate.fingerprint, second.certificate.fingerprint)


if __name__ == "__main__":
    unittest.main()
