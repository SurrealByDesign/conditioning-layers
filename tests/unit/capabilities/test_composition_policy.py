"""P3B policy representation cannot grant retained execution or admission."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing import (
    FieldAssetProfile, FieldChannelProfile, FieldValueKind,
    translate_prediction_mixing,
)
from conditioning_layers.capabilities import evaluate_prediction_mixing
from conditioning_layers.capabilities.multi_layer import (
    EXACT_THREE_ELIGIBILITY, MULTI_LAYER_CONTRACT_IDENTIFIER,
    ORDINARY_V1_CONTRACT_IDENTIFIER, POLICY_BOUND_EXACT_THREE,
    PRODUCT_ADMITTED_ENTRIES, REGISTERED_ELIGIBILITY_ENTRIES,
    evaluate_multi_layer_eligibility, fingerprint_eligibility_entry,
    fingerprint_policy_bound_eligibility, product_supported_cardinalities,
    route_prediction_mixing, select_policy_bound_eligibility,
    verify_policy_bound_eligibility,
)
from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, CURRENT_PROTOTYPE_VERSION,
    NORMALIZED_BLEND, PREDICTION_MIXING_ADAPTER_ID, REQUIRE_NO_OVERLAP,
    CompositionPolicyReference, ConditioningDocument,
    InfluenceFieldAssetReference, PromptLayer, PrototypeDocumentVersion,
)


def document(count: int, *, policy=None) -> ConditioningDocument:
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION if policy is None else COMPOSITION_POLICY_PROTOTYPE_VERSION,
        document_id="p3b-capability", base_prompt="A quiet studio",
        layers=tuple(PromptLayer(
            layer_id=str(index), name=f"Layer {index}", prompt_text=f"Prompt {index}",
            influence_field=InfluenceFieldAssetReference(f"fields/{index}.png", "a" * 64),
        ) for index in range(count)),
        selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID,
        composition_policy=policy,
    )


def codes(findings):
    return {finding.code for finding in findings}


class CompositionEligibilityTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target in (
            "socket.socket", "socket.create_connection", "socket.getaddrinfo",
            "urllib.request.urlopen", "http.client.HTTPConnection.connect",
            "subprocess.Popen", "webbrowser.open",
        ):
            stack.enter_context(patch(target, side_effect=AssertionError("P3B is offline")))

    def test_current_product_routes_and_admission_are_unchanged(self):
        self.assertEqual(product_supported_cardinalities(), (1, 2, 3))
        self.assertEqual(REGISTERED_ELIGIBILITY_ENTRIES, (EXACT_THREE_ELIGIBILITY,))
        self.assertEqual(len(PRODUCT_ADMITTED_ENTRIES), 2)
        for count, expected in ((1, ORDINARY_V1_CONTRACT_IDENTIFIER),
                                (2, ORDINARY_V1_CONTRACT_IDENTIFIER),
                                (3, MULTI_LAYER_CONTRACT_IDENTIFIER)):
            with self.subTest(count=count):
                route = route_prediction_mixing(document(count))
                self.assertTrue(route.compatible)
                self.assertEqual(route.contract_identifier, expected)
        self.assertFalse(route_prediction_mixing(document(4)).compatible)

    def test_frozen_exact_three_entry_keeps_content_and_fingerprint(self):
        self.assertEqual(EXACT_THREE_ELIGIBILITY.fingerprint, "fc1c0d96a8de733ebcb71f08b2db3123a588da8afcf046bd70c92852cd9b6c55")
        self.assertEqual(fingerprint_eligibility_entry(EXACT_THREE_ELIGIBILITY), EXACT_THREE_ELIGIBILITY.fingerprint)
        self.assertEqual(EXACT_THREE_ELIGIBILITY.overlap_policy, "require_no_overlap")

    def test_policy_binding_is_frozen_canonical_and_references_retained_authority(self):
        binding = POLICY_BOUND_EXACT_THREE
        self.assertEqual(binding.format_identifier, "prediction-mixing.policy-bound-eligibility.v1")
        self.assertEqual(binding.eligibility_entry_identifier, EXACT_THREE_ELIGIBILITY.identifier)
        self.assertEqual(binding.eligibility_entry_fingerprint, EXACT_THREE_ELIGIBILITY.fingerprint)
        self.assertEqual(binding.composition_policy, REQUIRE_NO_OVERLAP.reference)
        self.assertEqual(binding.relationship_constraint, "mutually-exclusive-positive-stored-samples")
        self.assertEqual(fingerprint_policy_bound_eligibility(binding), binding.fingerprint)
        self.assertEqual(verify_policy_bound_eligibility(binding), ())
        with self.assertRaises(FrozenInstanceError):
            binding.exact_cardinality = 4

    def test_policy_binding_cannot_self_register_changed_semantics(self):
        for change in (
            {"format_version": True}, {"contract_version": True},
            {"format_version": 1.0}, {"contract_version": 1.0},
            {"exact_cardinality": True}, {"exact_cardinality": 4},
            {"exact_cardinality": 3.0},
            {"relationship_constraint": "allow-overlap"},
            {"composition_policy": NORMALIZED_BLEND.reference},
            {"composition_policy": CompositionPolicyReference(REQUIRE_NO_OVERLAP.identifier, True)},
            {"composition_policy": {"policy_identifier": REQUIRE_NO_OVERLAP.identifier, "policy_version": 1}},
            {"eligibility_entry_fingerprint": "0" * 64},
        ):
            with self.subTest(change=change):
                forged = replace(POLICY_BOUND_EXACT_THREE, **change)
                forged = replace(forged, fingerprint=fingerprint_policy_bound_eligibility(forged))
                self.assertTrue(verify_policy_bound_eligibility(forged))

    def test_binding_rejects_missing_retained_authority_and_untrusted_fingerprint(self):
        self.assertTrue(verify_policy_bound_eligibility(None))
        self.assertTrue(verify_policy_bound_eligibility(replace(POLICY_BOUND_EXACT_THREE, fingerprint="0" * 64)))
        with patch("conditioning_layers.capabilities.multi_layer.REGISTERED_ELIGIBILITY_ENTRIES", ()):
            self.assertTrue(verify_policy_bound_eligibility(POLICY_BOUND_EXACT_THREE))

    def test_binding_subtypes_are_not_reviewed_canonical_records(self):
        class BindingSubtype(type(POLICY_BOUND_EXACT_THREE)):
            pass

        from dataclasses import fields
        forged = BindingSubtype(**{item.name: getattr(POLICY_BOUND_EXACT_THREE, item.name) for item in fields(POLICY_BOUND_EXACT_THREE)})
        self.assertTrue(verify_policy_bound_eligibility(forged))

    def test_selection_binds_policy_separately_from_relationship_and_cardinality(self):
        for intent in (document(3), document(3, policy=REQUIRE_NO_OVERLAP.reference)):
            self.assertEqual(select_policy_bound_eligibility(intent), POLICY_BOUND_EXACT_THREE)
        for intent in (document(2), document(4), document(3, policy=NORMALIZED_BLEND.reference)):
            with self.subTest(intent=intent), self.assertRaises(ValueError):
                select_policy_bound_eligibility(intent)
        for intent in (
            replace(document(3), selected_adapter_id="unsupported.adapter"),
            replace(document(3), adapter_settings={"setting": True}),
        ):
            with self.subTest(intent=intent), self.assertRaises(ValueError):
                select_policy_bound_eligibility(intent)
        for change in ({"relationship_constraint": "overlapping"},
                       {"contract_identifier": "unknown"}, {"contract_version": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                select_policy_bound_eligibility(document(3), **change)

    def test_blend_cannot_select_any_product_or_qualification_route(self):
        for count in (1, 2, 3, 4):
            for qualification in (None, EXACT_THREE_ELIGIBILITY):
                with self.subTest(count=count, qualification=qualification):
                    route = route_prediction_mixing(
                        document(count, policy=NORMALIZED_BLEND.reference),
                        qualification_entry=qualification,
                    )
                    self.assertFalse(route.compatible)
                    self.assertIsNone(route.contract_identifier)
                    self.assertIsNone(route.eligibility_entry)
                    self.assertIn("capability.composition_policy_not_realizable", codes(route.errors))

    def test_successor_no_overlap_is_persistable_not_retained_executable_format(self):
        for count in (1, 2, 3):
            with self.subTest(count=count):
                intent = document(count, policy=REQUIRE_NO_OVERLAP.reference)
                self.assertIn("capability.document_execution_format_unsupported", codes(route_prediction_mixing(intent).errors))
                self.assertFalse(evaluate_prediction_mixing(intent).compatible)
        self.assertIn("capability.document_execution_format_unsupported", codes(evaluate_multi_layer_eligibility(document(3, policy=REQUIRE_NO_OVERLAP.reference))))

    def test_direct_ordinary_translation_rejects_blend_with_valid_field_metadata(self):
        intent = document(1, policy=NORMALIZED_BLEND.reference)
        profile = FieldAssetProfile(
            layer_id="0", relative_path="fields/0.png", checksum="a" * 64,
            width=128, height=128, channel_count=1,
            channel_profile=FieldChannelProfile.GRAYSCALE_8,
            minimum_normalized_value=0.0, maximum_normalized_value=1.0,
            finite_values=True, value_kind=FieldValueKind.CONTINUOUS,
        )
        result = translate_prediction_mixing(intent, (profile,))
        self.assertIsNone(result.plan)
        self.assertIn("capability.composition_policy_not_realizable", codes(result.capability_evaluation.errors))

    def test_direct_exact_three_eligibility_rejects_blend(self):
        findings = evaluate_multi_layer_eligibility(document(3, policy=NORMALIZED_BLEND.reference))
        self.assertIn("capability.composition_policy_not_realizable", codes(findings))

    def test_invalid_or_legacy_explicit_policy_cannot_reach_retained_execution(self):
        for intent in (
            replace(document(3), composition_policy=NORMALIZED_BLEND.reference),
            replace(document(3), composition_policy=REQUIRE_NO_OVERLAP.reference),
            document(3, policy=CompositionPolicyReference("unknown", 1)),
            document(3, policy=CompositionPolicyReference(NORMALIZED_BLEND.identifier, 2)),
            document(3, policy={"policy_identifier": NORMALIZED_BLEND.identifier, "policy_version": 1}),
        ):
            with self.subTest(intent=intent):
                self.assertFalse(route_prediction_mixing(intent).compatible)
                self.assertFalse(evaluate_prediction_mixing(intent).compatible)
                self.assertTrue(evaluate_multi_layer_eligibility(intent))

    def test_zero_strength_does_not_change_current_selection_or_count(self):
        intent = document(3)
        intent = replace(intent, layers=tuple(replace(layer, strength=0.0) for layer in intent.layers))
        self.assertEqual(select_policy_bound_eligibility(intent), POLICY_BOUND_EXACT_THREE)
        self.assertTrue(route_prediction_mixing(intent).compatible)
        self.assertEqual(route_prediction_mixing(intent).active_layer_count, 3)

    def test_historical_newer_minor_ordinary_evaluation_remains_warning_only(self):
        intent = replace(document(1), version=PrototypeDocumentVersion(1, 1))
        evaluation = evaluate_prediction_mixing(intent)
        self.assertTrue(evaluation.compatible)
        self.assertEqual(evaluation.errors, ())
        self.assertIn("document.version.newer_minor", codes(evaluation.warnings))
        self.assertEqual(route_prediction_mixing(intent).ordinary_evaluation, evaluation)

    def test_preexisting_invalid_versions_keep_their_original_validation_findings(self):
        for version in ("invalid", PrototypeDocumentVersion(-1, 0), PrototypeDocumentVersion(3, 0)):
            with self.subTest(version=version):
                evaluation = evaluate_prediction_mixing(replace(document(1), version=version))
                self.assertFalse(evaluation.compatible)
                self.assertFalse(any(code.startswith("capability.composition_policy") for code in codes(evaluation.errors)))


if __name__ == "__main__":
    unittest.main()
