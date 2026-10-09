from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing.blend import (
    BLEND_EXECUTION_PROFILE, fingerprint_execution_profile, fingerprint_translation_plan_v4,
    serialize_translation_plan_v4, translate_prediction_mixing_blend, verify_translation_plan,
)
from conditioning_layers.adapters.prediction_mixing.multi_layer import translate_prediction_mixing_multi_layer
from conditioning_layers.assets import fingerprint_field_relationship_certificate
from conditioning_layers.capabilities.blend import (
    EXACT_THREE_BLEND_ELIGIBILITY, fingerprint_blend_eligibility,
)
from conditioning_layers.domain import CURRENT_PROTOTYPE_VERSION, REQUIRE_NO_OVERLAP
from conditioning_layers.domain.execution_projection import fingerprint_document_execution_projection
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tooling"))
from blend_fixture import blend_fixture


class BlendTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        for target in ("socket.socket", "urllib.request.urlopen", "http.client.HTTPConnection", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("P3C is offline only"))
            guard.start()
            self.addCleanup(guard.stop)
        self.data = blend_fixture(self.temporary.name)

    def test_overlap_and_gaps_are_measurements_not_rejections(self):
        document, inspected, profiles, plan, *_ = self.data
        self.assertFalse(inspected.certificate.whole_set_evidence.mutual_exclusion)
        self.assertGreater(inspected.certificate.whole_set_evidence.gap_pixel_count, 0)
        self.assertEqual(verify_translation_plan(plan), ())
        self.assertEqual(plan.format_identifier, "prediction-mixing.translation-plan.v4")
        self.assertEqual(plan.document_projection.format_identifier, "conditioning-layers.document-execution-projection.v2")
        self.assertEqual(plan.certificate.relationship_policy_identifier, "prediction-mixing.ordered-n-way-no-overlap.v1")
        self.assertEqual(plan.certificate.fingerprint, fingerprint_field_relationship_certificate(inspected.certificate))
        repeated = translate_prediction_mixing_blend(document, inspected.certificate, profiles).plan
        self.assertEqual(serialize_translation_plan_v4(plan), serialize_translation_plan_v4(repeated))
        legacy = replace(document, version=CURRENT_PROTOTYPE_VERSION, composition_policy=None)
        self.assertFalse(translate_prediction_mixing_multi_layer(legacy, inspected.certificate, profiles).translated)

    def test_full_strength_domain_base_and_order_preserved(self):
        for strengths in ((0.0, 0.0, 0.0), (1e-37, 1e-37, 1e-37), (5e-324, 1.0, 0.0)):
            document, _, _, plan, *_ = blend_fixture(self.temporary.name, strengths=strengths, order=(2, 0, 1))
            self.assertEqual(tuple(item.layer_id for item in plan.regional_conditions), ("c", "a", "b"))
            self.assertEqual(tuple(item.requested_strength for item in plan.regional_conditions), tuple(strengths[i] for i in (2, 0, 1)))
            self.assertEqual(len(plan.regional_conditions), 3)
            self.assertTrue(all(item.combined_prompt_text == document.base_prompt + "\n\n" + item.regional_prompt_text
                                for item in plan.regional_conditions))
            self.assertEqual(len(plan.fold_schedule), 2)
            self.assertEqual(verify_translation_plan(plan), ())

    def test_profile_and_eligibility_cannot_be_rehashed_into_new_authority(self):
        document, inspection, profiles, plan, *_ = self.data
        for field, value in (("exact_cardinality", 4), ("exact_cardinality", 3.0),
                             ("complete_coverage_required", True), ("relationship_constraint", "invented")):
            entry = replace(EXACT_THREE_BLEND_ELIGIBILITY, **{field: value})
            entry = replace(entry, fingerprint=fingerprint_blend_eligibility(entry))
            self.assertFalse(translate_prediction_mixing_blend(document, inspection.certificate, profiles, eligibility_entry=entry).translated)
        self.assertFalse(hasattr(BLEND_EXECUTION_PROFILE, "maximum_active_layers"))
        profile = replace(BLEND_EXECUTION_PROFILE, numerical_realization="float64 products")
        profile = replace(profile, fingerprint=fingerprint_execution_profile(profile))
        self.assertFalse(translate_prediction_mixing_blend(document, inspection.certificate, profiles, execution_profile=profile).translated)

    def test_rehashed_plan_cannot_change_policy_sources_or_fold(self):
        plan = self.data[3]
        altered_condition = replace(plan.regional_conditions[0], combined_prompt_text="forged prompt")
        altered_field = replace(plan.regional_conditions[0].field_profile, checksum="0" * 64)
        policy_projection = replace(plan.document_projection, composition_policy=REQUIRE_NO_OVERLAP.reference)
        policy_projection = replace(policy_projection, fingerprint=fingerprint_document_execution_projection(policy_projection))
        for changed in (
            replace(plan, regional_conditions=(altered_condition,) + plan.regional_conditions[1:]),
            replace(plan, regional_conditions=(replace(plan.regional_conditions[0], field_profile=altered_field),) + plan.regional_conditions[1:]),
            replace(plan, regional_conditions=tuple(reversed(plan.regional_conditions))),
            replace(plan, fold_schedule=tuple(reversed(plan.fold_schedule))),
            replace(plan, document_projection=policy_projection),
            replace(plan, format_version=4.0),
        ):
            changed = replace(changed, fingerprint=fingerprint_translation_plan_v4(changed))
            self.assertTrue(verify_translation_plan(changed))

    def test_bad_certificate_fails_closed_and_rgb_path_is_accepted(self):
        document, inspection, profiles, *_ = self.data
        changed = replace(inspection.certificate, whole_set_evidence=replace(
            inspection.certificate.whole_set_evidence, mutual_exclusion=True))
        changed = replace(changed, fingerprint=fingerprint_field_relationship_certificate(changed))
        self.assertFalse(translate_prediction_mixing_blend(document, changed, profiles).translated)
        self.assertEqual(verify_translation_plan(blend_fixture(self.temporary.name, rgb=True)[3]), ())


if __name__ == "__main__":
    unittest.main()
