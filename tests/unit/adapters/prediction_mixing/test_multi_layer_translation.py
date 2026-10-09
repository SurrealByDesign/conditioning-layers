from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from conditioning_layers.adapters.prediction_mixing import PREDICTION_MIXING_EXECUTION_PROFILE, translate_prediction_mixing
from conditioning_layers.adapters.prediction_mixing.multi_layer import (
    MULTI_LAYER_EXECUTION_PROFILE, fingerprint_execution_profile, fingerprint_translation_plan_v3,
    serialize_translation_plan_v3, translate_prediction_mixing_multi_layer, verify_translation_plan,
)
from conditioning_layers.adapters.prediction_mixing.v2.models import TranslationStatus
from conditioning_layers.assets import (
    FieldRelationshipInput, PartitionClassification, fingerprint_field_relationship_certificate,
    inspect_field_relationships, to_field_asset_profile,
)
from conditioning_layers.capabilities.multi_layer import EXACT_THREE_ELIGIBILITY, fingerprint_eligibility_entry
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION, PREDICTION_MIXING_ADAPTER_ID, ConditioningDocument,
    InfluenceFieldAssetReference, PromptLayer,
)


ROOT = Path(__file__).resolve().parents[4]


def png(samples: bytes, rgb: bool = False) -> bytes:
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    if rgb:
        samples = b"".join(bytes((value, value, value)) for value in samples)
    stride = 128 * (3 if rgb else 1)
    rows = b"".join(b"\0" + samples[index:index + stride] for index in range(0, len(samples), stride))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 2 if rgb else 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class MultiLayerTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # All implementation work remains offline, with no child process or HTTP.
        for target in ("socket.socket", "urllib.request.urlopen", "http.client.HTTPConnection", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("offline translation test attempted external activity"))
            guard.start()
            self.addCleanup(guard.stop)

    def case(self, *, family="vertical-thirds", strengths=(1.0, 1.0, 1.0), samples=None, rgb=False):
        layers = []
        for ordinal, letter in enumerate("abc"):
            contents = (ROOT / "influence-field-library" / "v1" / "three-layer" / family / f"field-{letter}.png").read_bytes() if samples is None else png(samples[ordinal], rgb)
            relative = f"fields/{letter}.png"
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
            layers.append(PromptLayer(letter, f"Layer {letter}", ("red ceramic sphere", "green woven cube", "blue glass vessel")[ordinal],
                          strength=strengths[ordinal], influence_field=InfluenceFieldAssetReference(relative, hashlib.sha256(contents).hexdigest())))
        document = ConditioningDocument(CURRENT_PROTOTYPE_VERSION, "three-layer-fixture", "Three distinct objects in a calm studio", tuple(layers), PREDICTION_MIXING_ADAPTER_ID)
        return self.inspect(document)

    def inspect(self, document):
        inspection = inspect_field_relationships(self.root, tuple(FieldRelationshipInput(item, index)
                        for index, item in enumerate(document.layers) if item.visible is True))
        profiles = tuple(to_field_asset_profile(item) for item in inspection.fields)
        return document, inspection.certificate, profiles

    def translate(self, case, **kwargs):
        return translate_prediction_mixing_multi_layer(*case, **kwargs)

    def translated(self, case):
        result = self.translate(case)
        self.assertEqual(result.status, TranslationStatus.TRANSLATED, result.findings)
        self.assertIsNotNone(result.plan)
        self.assertEqual(verify_translation_plan(result.plan), ())
        return result.plan

    def rehash_certificate(self, certificate):
        return replace(certificate, fingerprint=fingerprint_field_relationship_certificate(certificate))

    def test_vertical_and_horizontal_thirds_succeed_with_exact_ordered_fold(self):
        for family in ("vertical-thirds", "horizontal-thirds"):
            with self.subTest(family=family):
                plan = self.translated(self.case(family=family))
                self.assertEqual(plan.exact_admitted_cardinality, 3)
                self.assertEqual(tuple(item.layer_id for item in plan.regional_conditions), tuple("abc"))
                self.assertEqual(tuple((item.left_operand, item.right_condition, item.result) for item in plan.fold_schedule),
                                 (("condition:0", "condition:1", "fold:0"), ("fold:0", "condition:2", "fold:1")))
                self.assertEqual(len(plan.certificate.pairwise_evidence), 3)

    def test_repeated_plan_and_serialization_are_identical(self):
        case = self.case()
        first = self.translated(case)
        second = self.translated(case)
        self.assertEqual(first, second)
        self.assertEqual(serialize_translation_plan_v3(first), serialize_translation_plan_v3(second))
        self.assertEqual(first.fingerprint, fingerprint_translation_plan_v3(first))

    def test_plan_identity_excludes_registry_growth_and_product_admission(self):
        case = self.case()
        first = self.translated(case)
        fixture_only = replace(EXACT_THREE_ELIGIBILITY, identifier="fixture.unselected", exact_cardinality=4)
        with patch("conditioning_layers.capabilities.multi_layer.REGISTERED_ELIGIBILITY_ENTRIES", (EXACT_THREE_ELIGIBILITY, fixture_only)), \
             patch("conditioning_layers.capabilities.multi_layer.PRODUCT_ADMITTED_ENTRIES", (EXACT_THREE_ELIGIBILITY.identifier,)):
            second = self.translated(case)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(serialize_translation_plan_v3(first), serialize_translation_plan_v3(second))

    def test_profile_is_count_free_new_and_frozen(self):
        self.assertEqual(MULTI_LAYER_EXECUTION_PROFILE.profile_identifier, "krea2-turbo-bf16-1024.v2")
        self.assertEqual(fingerprint_execution_profile(MULTI_LAYER_EXECUTION_PROFILE), MULTI_LAYER_EXECUTION_PROFILE.fingerprint)
        self.assertFalse(hasattr(MULTI_LAYER_EXECUTION_PROFILE, "maximum_active_layers"))
        self.assertEqual(PREDICTION_MIXING_EXECUTION_PROFILE.profile_identifier, "krea2-turbo-bf16-1024.v1")
        self.assertEqual(PREDICTION_MIXING_EXECUTION_PROFILE.maximum_active_layers, 2)
        with self.assertRaises(FrozenInstanceError):
            MULTI_LAYER_EXECUTION_PROFILE.profile_version = 3

    def test_distinct_strengths_bind_each_condition_and_identity(self):
        ordinary = self.translated(self.case())
        plan = self.translated(self.case(strengths=(0.5, 1.0, 0.75)))
        self.assertEqual(tuple(item.requested_strength for item in plan.regional_conditions), (0.5, 1.0, 0.75))
        self.assertNotEqual(ordinary.fingerprint, plan.fingerprint)
        for index in range(3):
            strengths = [0.5, 1.0, 0.75]
            strengths[index] = 0.25
            self.assertNotEqual(plan.fingerprint, self.translated(self.case(strengths=tuple(strengths))).fingerprint)

    def test_one_and_all_zero_strength_layers_remain_in_plan_and_certificate(self):
        for strengths in ((0.0, 1.0, 1.0), (0.0, 0.0, 0.0)):
            plan = self.translated(self.case(strengths=strengths))
            self.assertEqual(len(plan.regional_conditions), 3)
            self.assertEqual(len(plan.certificate.ordered_fields), 3)
            self.assertEqual(tuple(item.requested_strength for item in plan.regional_conditions), strengths)

    def test_signed_zero_has_one_canonical_plan_and_condition_strength(self):
        negative = self.translated(self.case(strengths=(-0.0, 1.0, 1.0)))
        positive = self.translated(self.case(strengths=(0.0, 1.0, 1.0)))
        self.assertEqual(negative.fingerprint, positive.fingerprint)
        self.assertEqual(serialize_translation_plan_v3(negative), serialize_translation_plan_v3(positive))
        self.assertEqual(math.copysign(1.0, negative.regional_conditions[0].requested_strength), 1.0)
        forged = replace(positive, regional_conditions=(replace(positive.regional_conditions[0], requested_strength=-0.0),)
                         + positive.regional_conditions[1:])
        self.assertEqual(fingerprint_translation_plan_v3(forged), positive.fingerprint)
        self.assertTrue(verify_translation_plan(forged))

    def test_disjoint_continuous_with_gaps_succeeds(self):
        samples = tuple(bytes(64 + x % 128 if ordinal * 40 <= x < ordinal * 40 + 20 else 0 for y in range(128) for x in range(128)) for ordinal in range(3))
        plan = self.translated(self.case(samples=samples))
        self.assertEqual(plan.certificate.partition_classification, PartitionClassification.DISJOINT_WITH_GAPS)
        self.assertTrue(all(item.field_profile.value_kind.value == "continuous" for item in plan.regional_conditions))

    def test_disjoint_continuous_full_coverage_below_one_succeeds(self):
        samples = tuple(bytes(128 if min(x * 3 // 128, 2) == ordinal else 0 for y in range(128) for x in range(128)) for ordinal in range(3))
        plan = self.translated(self.case(samples=samples))
        self.assertEqual(plan.certificate.partition_classification, PartitionClassification.MIXED_NON_PARTITION)
        self.assertTrue(plan.certificate.whole_set_evidence.complete_coverage)
        self.assertLess(plan.certificate.whole_set_evidence.maximum_normalized_total_sum, 1.0)

    def test_identical_rgb_encoding_remains_supported(self):
        samples = tuple(bytes(255 if min(x * 3 // 128, 2) == ordinal else 0 for y in range(128) for x in range(128)) for ordinal in range(3))
        plan = self.translated(self.case(samples=samples, rgb=True))
        self.assertTrue(all(item.field_profile.channel_count == 3 for item in plan.regional_conditions))

    def test_each_pair_overlap_rejects_including_zero_strength(self):
        for first, second in ((0, 1), (0, 2), (1, 2)):
            for zero in (False, True):
                with self.subTest(pair=(first, second), zero=zero):
                    samples = [bytearray(255 if min(x * 3 // 128, 2) == ordinal else 0 for y in range(128) for x in range(128)) for ordinal in range(3)]
                    shared = next(index for index, value in enumerate(samples[first]) if value)
                    samples[second][shared] = 1  # One positive stored sample, with no tolerance.
                    strengths = tuple(0.0 if zero and index == second else 1.0 for index in range(3))
                    result = self.translate(self.case(samples=tuple(bytes(item) for item in samples), strengths=strengths))
                    self.assertEqual(result.status, TranslationStatus.REJECTED, result.findings)
                    self.assertIsNone(result.plan)
                    self.assertIn("translation.overlap_present", {item.code for item in result.errors})

    def test_document_reorder_requires_new_certificate_and_changes_identity(self):
        case = self.case()
        first = self.translated(case)
        reordered = case[0].move_layer("c", 0)
        self.assertEqual(self.translate((reordered, case[1], case[2])).status, TranslationStatus.INVALID)
        second = self.translated(self.inspect(reordered))
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(tuple(item.layer_id for item in second.regional_conditions), ("c", "a", "b"))

    def test_display_names_disabled_content_and_document_id_are_not_plan_identity(self):
        case = self.case()
        first = self.translated(case)
        renamed = replace(case[0], document_id="other", layers=tuple(replace(item, name="Renamed") for item in case[0].layers))
        self.assertEqual(first.fingerprint, self.translated((renamed, case[1], case[2])).fingerprint)
        disabled = PromptLayer("disabled", "Disabled", "unexecuted", visible=False)
        appended = replace(renamed, layers=renamed.layers + (disabled,))
        self.assertEqual(first.fingerprint, self.translated((appended, case[1], case[2])).fingerprint)

    def test_disabled_rows_require_actual_indexes(self):
        case = self.case()
        changed = replace(case[0], layers=(PromptLayer("disabled", "Disabled", "unexecuted", visible=False),) + case[0].layers)
        self.assertEqual(self.translate((changed, case[1], case[2])).status, TranslationStatus.INVALID)
        self.assertNotEqual(self.translated(case).fingerprint, self.translated(self.inspect(changed)).fingerprint)

    def test_wrong_contract_cardinality_profile_and_ordinary_route_reject(self):
        case = self.case()
        self.assertEqual(self.translate(case, contract_identifier="unknown").status, TranslationStatus.REJECTED)
        for count in (1, 2):
            reduced = replace(case[0], layers=case[0].layers[:count])
            self.assertEqual(self.translate(self.inspect(reduced)).status, TranslationStatus.REJECTED)
        ordinary = translate_prediction_mixing(case[0], case[2])
        self.assertFalse(ordinary.translated)
        unsupported = replace(MULTI_LAYER_EXECUTION_PROFILE, profile_identifier="unknown")
        unsupported = replace(unsupported, fingerprint=fingerprint_execution_profile(unsupported))
        self.assertEqual(self.translate(case, execution_profile=unsupported).status, TranslationStatus.REJECTED)
        widened = replace(EXACT_THREE_ELIGIBILITY, exact_cardinality=4)
        widened = replace(widened, fingerprint=fingerprint_eligibility_entry(widened))
        self.assertEqual(self.translate(case, eligibility_entry=widened).status, TranslationStatus.INVALID)

    def test_malformed_missing_and_checksum_changed_field_fail_closed(self):
        for mutation in ("missing", "malformed", "checksum"):
            with self.subTest(mutation=mutation):
                case = self.case()
                field = self.root / "fields" / "c.png"
                if mutation == "missing":
                    field.unlink()
                elif mutation == "malformed":
                    field.write_bytes(b"not a PNG")
                else:
                    field.write_bytes(field.read_bytes() + b"changed")
                result = self.translate(self.inspect(case[0]))
                self.assertEqual(result.status, TranslationStatus.INVALID)
                self.assertIsNone(result.plan)

    def test_invalid_strengths_fail_without_partial_plan(self):
        case = self.case()
        for strength in (-0.1, 1.1, float("nan"), float("inf"), True):
            document = replace(case[0], layers=(replace(case[0].layers[0], strength=strength),) + case[0].layers[1:])
            result = self.translate((document, case[1], case[2]))
            self.assertIsNone(result.plan)
            self.assertEqual(result.status, TranslationStatus.INVALID)

    def test_forged_reordered_stale_and_inconsistent_certificate_fail_closed(self):
        document, certificate, profiles = self.case()
        forged_field = replace(certificate.ordered_fields[1], source_sha256="0" * 64)
        candidates = (
            replace(certificate, fingerprint="0" * 64),
            self.rehash_certificate(replace(certificate, ordered_fields=tuple(reversed(certificate.ordered_fields)))),
            self.rehash_certificate(replace(certificate, ordered_fields=(certificate.ordered_fields[0], forged_field, certificate.ordered_fields[2]))),
            self.rehash_certificate(replace(certificate, pairwise_evidence=certificate.pairwise_evidence[:2])),
            self.rehash_certificate(replace(certificate, pairwise_evidence=tuple(reversed(certificate.pairwise_evidence)))),
            self.rehash_certificate(replace(certificate, whole_set_evidence=replace(certificate.whole_set_evidence, gap_pixel_count=1))),
            self.rehash_certificate(replace(certificate, shared_raster=replace(certificate.shared_raster, positive_sample_threshold_normalized=0.001))),
        )
        for candidate in candidates:
            result = self.translate((document, candidate, profiles))
            self.assertEqual(result.status, TranslationStatus.INVALID, result.findings)
            self.assertIsNone(result.plan)

    def test_invalid_evidence_precedes_unsupported_contract(self):
        document, certificate, profiles = self.case()
        result = self.translate((document, replace(certificate, fingerprint="0" * 64), profiles), contract_identifier="unknown")
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIsNone(result.plan)

    def test_plan_rehash_cannot_hide_derived_condition_or_cardinality_forgery(self):
        plan = self.translated(self.case())
        candidates = (
            replace(plan, regional_conditions=plan.regional_conditions[:2]),
            replace(plan, regional_conditions=(replace(plan.regional_conditions[0], requested_strength=0.5),) + plan.regional_conditions[1:]),
            replace(plan, fold_schedule=tuple(reversed(plan.fold_schedule))),
            replace(plan, format_version=True),
        )
        for candidate in candidates:
            candidate = replace(candidate, fingerprint=fingerprint_translation_plan_v3(candidate))
            self.assertTrue(verify_translation_plan(candidate))


if __name__ == "__main__":
    unittest.main()
