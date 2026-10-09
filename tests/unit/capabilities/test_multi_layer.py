from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import PREDICTION_MIXING_CAPABILITY, evaluate_prediction_mixing
from conditioning_layers.capabilities.multi_layer import (
    EXACT_THREE_ELIGIBILITY, MULTI_LAYER_CONTRACT_IDENTIFIER, ORDINARY_PRODUCT_ENTRY_IDENTIFIER,
    ORDINARY_V1_CONTRACT_IDENTIFIER, PRODUCT_ADMITTED_ENTRIES, REGISTERED_ELIGIBILITY_ENTRIES,
    fingerprint_eligibility_entry, product_supported_cardinalities, route_prediction_mixing,
    verify_eligibility_entry,
)
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION, PREDICTION_MIXING_ADAPTER_ID, ConditioningDocument,
    InfluenceFieldAssetReference, PromptLayer,
)


def document(count: int) -> ConditioningDocument:
    return ConditioningDocument(CURRENT_PROTOTYPE_VERSION, "route", "Base", tuple(
        PromptLayer(str(index), f"Layer {index}", f"Prompt {index}",
                    influence_field=InfluenceFieldAssetReference(f"fields/{index}.png", "a" * 64))
        for index in range(count)), PREDICTION_MIXING_ADAPTER_ID)


class MultiLayerAuthorityTests(unittest.TestCase):
    def test_registered_and_product_admitted_sets_are_distinct(self):
        self.assertEqual(tuple(entry.exact_cardinality for entry in REGISTERED_ELIGIBILITY_ENTRIES), (3,))
        self.assertEqual(PRODUCT_ADMITTED_ENTRIES, (ORDINARY_PRODUCT_ENTRY_IDENTIFIER, EXACT_THREE_ELIGIBILITY.identifier))
        self.assertEqual(product_supported_cardinalities(), (1, 2, 3))
        self.assertEqual(product_supported_cardinalities((ORDINARY_PRODUCT_ENTRY_IDENTIFIER,)), (1, 2))
        self.assertEqual(product_supported_cardinalities((EXACT_THREE_ELIGIBILITY.identifier,)), (3,))
        self.assertEqual(PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers, 2)

    def test_entry_is_frozen_and_recomputed(self):
        self.assertEqual(EXACT_THREE_ELIGIBILITY.identifier, "prediction-mixing.multi-layer.exact-3.v1")
        self.assertEqual(EXACT_THREE_ELIGIBILITY.contract_identifier, "prediction-mixing.multi-layer.v1")
        self.assertEqual(EXACT_THREE_ELIGIBILITY.contract_version, 1)
        self.assertEqual(EXACT_THREE_ELIGIBILITY.fingerprint, "fc1c0d96a8de733ebcb71f08b2db3123a588da8afcf046bd70c92852cd9b6c55")
        self.assertEqual(EXACT_THREE_ELIGIBILITY.overlap_policy, "require_no_overlap")
        self.assertEqual(verify_eligibility_entry(EXACT_THREE_ELIGIBILITY), ())
        self.assertEqual(fingerprint_eligibility_entry(EXACT_THREE_ELIGIBILITY), EXACT_THREE_ELIGIBILITY.fingerprint)
        with self.assertRaises(FrozenInstanceError):
            EXACT_THREE_ELIGIBILITY.exact_cardinality = 4

    def test_entry_widening_cannot_register_itself(self):
        for change in ({"exact_cardinality": 4}, {"exact_cardinality": True}, {"strength_maximum": 2.0}, {"complete_coverage_required": True}):
            with self.subTest(change=change):
                entry = replace(EXACT_THREE_ELIGIBILITY, **change)
                entry = replace(entry, fingerprint=fingerprint_eligibility_entry(entry))
                self.assertTrue(verify_eligibility_entry(entry, registry=(entry,)))

    def test_selected_identity_excludes_unselected_registry(self):
        # Fixture data is deliberately not registered executable authority.
        unrelated = replace(EXACT_THREE_ELIGIBILITY, identifier="fixture.unselected", exact_cardinality=4)
        self.assertFalse(verify_eligibility_entry(EXACT_THREE_ELIGIBILITY, registry=(EXACT_THREE_ELIGIBILITY, unrelated)))
        self.assertEqual(fingerprint_eligibility_entry(EXACT_THREE_ELIGIBILITY), EXACT_THREE_ELIGIBILITY.fingerprint)
        self.assertTrue(verify_eligibility_entry(unrelated, registry=(EXACT_THREE_ELIGIBILITY, unrelated)))

    def test_missing_shadowed_and_forged_authority_rejects(self):
        self.assertTrue(verify_eligibility_entry(EXACT_THREE_ELIGIBILITY, registry=()))
        self.assertTrue(verify_eligibility_entry(EXACT_THREE_ELIGIBILITY, registry=(EXACT_THREE_ELIGIBILITY,) * 2))
        self.assertTrue(verify_eligibility_entry(replace(EXACT_THREE_ELIGIBILITY, fingerprint="0" * 64)))

    def test_router_ordinary_outcomes_delegate_exactly(self):
        for count in (0, 1, 2):
            with self.subTest(count=count):
                intent = document(count)
                route = route_prediction_mixing(intent)
                ordinary = evaluate_prediction_mixing(intent)
                self.assertEqual(route.ordinary_evaluation, ordinary)
                self.assertEqual(route.errors, ordinary.errors)
                self.assertEqual(route.warnings, ordinary.warnings)
                self.assertEqual(route.compatible, count in (1, 2))
                self.assertEqual(route.contract_identifier, ORDINARY_V1_CONTRACT_IDENTIFIER if count else None)

    def test_normal_three_and_qualification_three_select_same_exact_entry(self):
        normal = route_prediction_mixing(document(3))
        self.assertTrue(normal.compatible)
        self.assertFalse(normal.qualification_selected)
        self.assertEqual(normal.contract_identifier, MULTI_LAYER_CONTRACT_IDENTIFIER)
        self.assertEqual(normal.eligibility_entry, EXACT_THREE_ELIGIBILITY)
        self.assertIsNone(normal.ordinary_evaluation)
        internal = route_prediction_mixing(document(3), qualification_entry=EXACT_THREE_ELIGIBILITY)
        self.assertTrue(internal.compatible)
        self.assertTrue(internal.qualification_selected)
        self.assertEqual(replace(internal, qualification_selected=False), normal)

    def test_closed_admission_fixture_rejects_normal_three_without_changing_authority(self):
        closed = (ORDINARY_PRODUCT_ENTRY_IDENTIFIER,)
        rejected = route_prediction_mixing(document(3), product_admitted_entries=closed)
        self.assertFalse(rejected.compatible)
        self.assertIn("capability.product_not_admitted", {item.code for item in rejected.errors})
        internal = route_prediction_mixing(document(3), qualification_entry=EXACT_THREE_ELIGIBILITY,
                                          product_admitted_entries=closed)
        self.assertTrue(internal.compatible)
        self.assertEqual(rejected.eligibility_entry, internal.eligibility_entry)
        self.assertEqual(route_prediction_mixing(document(3)).eligibility_entry, internal.eligibility_entry)

    def test_four_plus_has_no_route_even_when_qualification_requested(self):
        for count in (4, 5):
            for entry in (None, EXACT_THREE_ELIGIBILITY):
                with self.subTest(count=count, qualification=entry is not None):
                    route = route_prediction_mixing(document(count), qualification_entry=entry)
                    self.assertFalse(route.compatible)
                    self.assertIsNone(route.contract_identifier)
                    self.assertIsNone(route.eligibility_entry)
                    self.assertIn("capability.active_layer_limit", {item.code for item in route.errors})

    def test_unreviewed_sparse_admission_cannot_enable_four(self):
        unreviewed = replace(EXACT_THREE_ELIGIBILITY, identifier="fixture.unselected", exact_cardinality=4)
        unreviewed = replace(unreviewed, fingerprint=fingerprint_eligibility_entry(unreviewed))
        with patch("conditioning_layers.capabilities.multi_layer.REGISTERED_ELIGIBILITY_ENTRIES",
                   (EXACT_THREE_ELIGIBILITY, unreviewed)):
            with self.assertRaises(ValueError):
                product_supported_cardinalities(PRODUCT_ADMITTED_ENTRIES + (unreviewed.identifier,))
            for entry in (None, unreviewed):
                route = route_prediction_mixing(document(4), qualification_entry=entry,
                                               product_admitted_entries=PRODUCT_ADMITTED_ENTRIES + (unreviewed.identifier,))
                self.assertFalse(route.compatible)
                self.assertIsNone(route.contract_identifier)

    def test_qualification_one_two_and_missing_registry_fail_closed(self):
        for count in (0, 1, 2):
            self.assertFalse(route_prediction_mixing(document(count), qualification_entry=EXACT_THREE_ELIGIBILITY).compatible)
        with patch("conditioning_layers.capabilities.multi_layer.REGISTERED_ELIGIBILITY_ENTRIES", ()):
            self.assertFalse(route_prediction_mixing(document(3)).compatible)
            self.assertFalse(route_prediction_mixing(document(3), qualification_entry=EXACT_THREE_ELIGIBILITY).compatible)

    def test_zero_strength_stays_active_disabled_rows_do_not_count(self):
        intent = document(3)
        intent = replace(intent, layers=tuple(replace(item, strength=0.0) for item in intent.layers))
        self.assertTrue(route_prediction_mixing(intent, qualification_entry=EXACT_THREE_ELIGIBILITY).compatible)
        self.assertTrue(route_prediction_mixing(intent).compatible)
        self.assertEqual(route_prediction_mixing(intent).active_layer_count, 3)
        self.assertEqual(route_prediction_mixing(intent.toggle_visibility("2")).contract_identifier, ORDINARY_V1_CONTRACT_IDENTIFIER)

    def test_invalid_strength_adapter_settings_and_field_reject(self):
        intent = document(3)
        bad = (replace(intent, selected_adapter_id="unknown"), replace(intent, adapter_settings={"contract": "x"}),
               replace(intent, layers=(replace(intent.layers[0], influence_field=None),) + intent.layers[1:]),
               replace(intent, layers=(replace(intent.layers[0], strength=float("nan")),) + intent.layers[1:]))
        for candidate in bad:
            for entry in (None, EXACT_THREE_ELIGIBILITY):
                with self.subTest(candidate=candidate, qualification=entry is not None):
                    self.assertFalse(route_prediction_mixing(candidate, qualification_entry=entry).compatible)


if __name__ == "__main__":
    unittest.main()
