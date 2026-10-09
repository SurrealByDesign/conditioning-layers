"""Slice A positive/negative Plan v4 matrix; no generalized graph construction."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import conditioning_layers.adapters.prediction_mixing.blend.translate as tr
from conditioning_layers.adapters.prediction_mixing.v2.models import TranslationStatus
from conditioning_layers.assets import fingerprint_field_relationship_certificate
from conditioning_layers.capabilities import blend
from conditioning_layers.domain import CURRENT_PROTOTYPE_VERSION, REQUIRE_NO_OVERLAP
from conditioning_layers.domain.execution_projection import fingerprint_document_execution_projection

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tooling"))
from bounded_blend_fixture import bounded_plan


class BoundedBlendTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_positive_matrix_exact_authority_pairs_bins_folds_and_order(self):
        for count in (4, 5, 6, 7, 8, 9):
            with self.subTest(count=count):
                document, inspection, profiles, result = bounded_plan(self.temporary.name, count)
                plan = result.plan
                self.assertIs(result.status, TranslationStatus.TRANSLATED)
                self.assertEqual(plan.format_identifier, "prediction-mixing.translation-plan.v4")
                self.assertEqual(plan.contract_identifier, "prediction-mixing.multi-layer.v2")
                self.assertEqual(plan.eligibility_entry.identifier,
                                 f"prediction-mixing.multi-layer.exact-{count}.normalized-blend.v1")
                self.assertEqual(plan.active_layer_count, count)
                self.assertEqual(len(plan.certificate.pairwise_evidence), count * (count - 1) // 2)
                self.assertEqual(len(plan.certificate.whole_set_evidence.simultaneous_active_count_histogram), count + 1)
                self.assertEqual(len(plan.fold_schedule), count - 1)
                self.assertEqual(tuple((p.first_ordinal, p.second_ordinal) for p in plan.certificate.pairwise_evidence),
                                 tuple((a, b) for a in range(count) for b in range(a + 1, count)))
                self.assertEqual(tuple(c.layer_id for c in plan.regional_conditions), tuple(l.layer_id for l in document.active_layers))
                self.assertEqual(tuple(c.requested_strength for c in plan.regional_conditions), tuple(l.strength for l in document.active_layers))
                self.assertEqual(tuple(c.active_ordinal for c in plan.regional_conditions), tuple(range(count)))
                for index, step in enumerate(plan.fold_schedule):
                    self.assertEqual((step.step_ordinal, step.left_operand, step.right_condition, step.result),
                                     (index, "condition:0" if index == 0 else f"fold:{index - 1}",
                                      f"condition:{index + 1}", f"fold:{index}"))
                self.assertTrue(all(c.combined_prompt_text == document.base_prompt + "\n\n" + c.regional_prompt_text
                                    for c in plan.regional_conditions))
                self.assertEqual(tr.verify_translation_plan(plan), ())
                repeated = tr.translate_prediction_mixing_blend(document, inspection.certificate, profiles,
                                                               eligibility_entry=plan.eligibility_entry)
                self.assertEqual(result, repeated)
                self.assertEqual(tr.serialize_translation_plan_v4(plan), tr.serialize_translation_plan_v4(repeated.plan))

    def test_reordered_active_and_disabled_rows_preserve_active_associations(self):
        for count in (4, 5, 6, 7, 8, 9):
            order = tuple(reversed(range(count)))
            with self.subTest(count=count):
                _, _, _, baseline = bounded_plan(self.temporary.name, count, order=order)
                document, _, _, result = bounded_plan(self.temporary.name, count, order=order, disabled=True)
                plan = result.plan
                self.assertEqual(tuple(c.layer_id for c in plan.regional_conditions), tuple(f"layer-{i}" for i in order))
                self.assertEqual(tuple(c.document_index for c in plan.regional_conditions), tuple(2 * i + 1 for i in range(count)))
                self.assertEqual(tuple(c.document_index for c in plan.regional_conditions),
                                 tuple(i for i, layer in enumerate(document.layers) if layer.visible is True))
                self.assertEqual(plan.document_projection, baseline.plan.document_projection)
                self.assertEqual(plan.fold_schedule, baseline.plan.fold_schedule)
                self.assertEqual(tuple(replace(c, document_index=i) for i, c in enumerate(plan.regional_conditions)),
                                 baseline.plan.regional_conditions)
                self.assertNotEqual(plan.fingerprint, baseline.plan.fingerprint)  # Actual certificate indexes are evidence.
                self.assertEqual(tr.verify_translation_plan(plan), ())

    def test_invalid_supplied_authority_stops_before_plan_construction(self):
        for count in (4, 5, 6, 7, 8, 9):
            document, inspection, profiles, accepted = bounded_plan(self.temporary.name, count)
            entry = accepted.plan.eligibility_entry
            for changes in ({"identifier": "unknown.blend.authority"}, {"relationship_constraint": "forged"},
                            {"exact_cardinality": count + 1}, {"composition_policy": REQUIRE_NO_OVERLAP.reference},
                            {"fingerprint": "0" * 64}):
                invalid = replace(entry, **changes)
                if "fingerprint" not in changes:
                    invalid = replace(invalid, fingerprint=blend.fingerprint_blend_eligibility(invalid))
                with self.subTest(count=count, changes=changes), patch.object(
                    tr, "verify_translation_plan", side_effect=AssertionError("invalid authority reached plan construction"),
                ):
                    result = tr.translate_prediction_mixing_blend(document, inspection.certificate, profiles, eligibility_entry=invalid)
                    self.assertIs(result.status, TranslationStatus.REJECTED)
                    self.assertIsNone(result.plan)
                    self.assertEqual(tuple(f.code for f in result.errors), ("blend.eligibility.invalid",))
                    self.assertEqual(result.warnings, ())

    def test_defaults_wrong_count_wrong_policy_and_format_one_reject_before_plan(self):
        for count in (4, 5, 6, 7, 8, 9):
            document, inspection, profiles, accepted = bounded_plan(self.temporary.name, count)
            entry = accepted.plan.eligibility_entry
            cases = (
                (document, {}, "blend.cardinality.unsupported"),
                (replace(document, layers=document.layers[:-1]), {"eligibility_entry": entry}, "blend.cardinality.unsupported"),
                (replace(document, composition_policy=REQUIRE_NO_OVERLAP.reference), {"eligibility_entry": entry}, "blend.policy.unsupported"),
                (replace(document, version=CURRENT_PROTOTYPE_VERSION, composition_policy=None), {"eligibility_entry": entry}, "blend.policy.unsupported"),
            )
            for changed, kwargs, code in cases:
                with self.subTest(count=count, code=code), patch.object(
                    tr, "verify_translation_plan", side_effect=AssertionError("unsupported document reached plan construction"),
                ):
                    result = tr.translate_prediction_mixing_blend(changed, inspection.certificate, profiles, **kwargs)
                    self.assertIs(result.status, TranslationStatus.REJECTED)
                    self.assertEqual(tuple(f.code for f in result.errors), (code,))
                    self.assertIsNone(result.plan)

    def test_truncated_and_reordered_fields_projections_certificates_and_folds_fail(self):
        for count in (4, 5, 6, 7, 8, 9):
            document, inspection, profiles, result = bounded_plan(self.temporary.name, count)
            plan = result.plan
            for changed in (profiles[:-1], tuple(reversed(profiles))):
                with self.subTest(count=count, source="profiles"):
                    invalid = tr.translate_prediction_mixing_blend(document, inspection.certificate, changed,
                                                                   eligibility_entry=plan.eligibility_entry)
                    self.assertIs(invalid.status, TranslationStatus.INVALID)
                    self.assertIsNone(invalid.plan)
                    self.assertEqual(tuple(f.code for f in invalid.errors), ("translation.certificate_mismatch",))
            projection = plan.document_projection
            for layers, code in (
                (projection.active_layers[:-1], "blend.plan.invalid"),
                (tuple(reversed(projection.active_layers)), "blend.plan.invalid"),
                (tuple(replace(layer, active_ordinal=i) for i, layer in enumerate(reversed(projection.active_layers))),
                 "translation.certificate_mismatch"),
            ):
                changed = replace(projection, active_layers=layers)
                changed = replace(changed, fingerprint=fingerprint_document_execution_projection(changed))
                self.assertBadPlan(replace(plan, document_projection=changed), code)
            for changes in (
                {"ordered_fields": plan.certificate.ordered_fields[:-1]},
                {"ordered_fields": tuple(reversed(plan.certificate.ordered_fields))},
                {"pairwise_evidence": plan.certificate.pairwise_evidence[:-1]},
                {"pairwise_evidence": tuple(reversed(plan.certificate.pairwise_evidence))},
                {"whole_set_evidence": replace(plan.certificate.whole_set_evidence,
                    simultaneous_active_count_histogram=plan.certificate.whole_set_evidence.simultaneous_active_count_histogram[:-1])},
            ):
                certificate = replace(plan.certificate, **changes)
                certificate = replace(certificate, fingerprint=fingerprint_field_relationship_certificate(certificate))
                self.assertBadPlan(replace(plan, certificate=certificate), "translation.certificate_mismatch")
            for schedule in (plan.fold_schedule[:-1], tuple(reversed(plan.fold_schedule))):
                self.assertBadPlan(replace(plan, fold_schedule=schedule), "blend.plan.invalid")
            wrong_entry = blend.EXACT_FIVE_BLEND_ELIGIBILITY if count == 4 else blend.EXACT_FOUR_BLEND_ELIGIBILITY
            self.assertBadPlan(replace(plan, eligibility_entry=wrong_entry), "blend.plan.invalid")

    def assertBadPlan(self, plan, code):
        plan = replace(plan, fingerprint=tr.fingerprint_translation_plan_v4(plan))
        self.assertEqual(tuple(f.code for f in tr.verify_translation_plan(plan)), (code,))

    def test_fresh_processes_reproduce_all_six_exact_entries_and_canonical_plans(self):
        source = '''
import json
import tempfile
from bounded_blend_fixture import bounded_plan
from conditioning_layers.adapters.prediction_mixing.blend import serialize_translation_plan_v4
records = []
with tempfile.TemporaryDirectory() as root:
    for count in (4, 5, 6, 7, 8, 9):
        plan = bounded_plan(root, count, order=tuple(reversed(range(count))), disabled=True)[3].plan
        records.append([plan.eligibility_entry.identifier, plan.eligibility_entry.fingerprint,
                        plan.fingerprint, serialize_translation_plan_v4(plan).decode("utf-8")])
print(json.dumps(records))
'''
        outputs = []
        for seed in ("1", "97"):
            result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                    env={**os.environ, "PYTHONHASHSEED": seed}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            outputs.append(json.loads(result.stdout))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(len(outputs[0]), 6)


if __name__ == "__main__":
    unittest.main()
