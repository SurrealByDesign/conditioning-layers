"""ADR-0023 exact registration, support firewall, and generation integrity."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from enum import Enum
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_0280_INVENTORY,
    CANONICAL_COMFYUI_INVENTORY,
    COMFYUI_0280_NODE_SNAPSHOT,
    COMFYUI_0280_SUPPORTED_PROFILE,
    COMFYUI_0280_HISTORICAL_PROFILE,
    DEFAULT_SUPPORTED_PROFILE,
    COMFYUI_0345_QUALIFICATION_PROFILE,
    COMFYUI_0346_QUALIFICATION_PROFILE,
    COMFYUI_0372_QUALIFICATION_PROFILE,
    COMFYUI_0374_QUALIFICATION_PROFILE,
    CompatibilityProfile,
    ProfileSupportStatus,
    REGISTERED_COMFYUI_PROFILES,
    canonical_inventory_for_profile,
    registered_inventory_for_profile,
    supported_inventory_for_profile,
)
from conditioning_layers.comfyui.prediction_mixing.qualification_profiles import (
    COMFYUI_0345_NODE_SNAPSHOT,
    COMFYUI_0345_QUALIFICATION_INVENTORY,
)

from test_graph import codes, make_plan
from test_validation import generate


class CompatibilityRegistryTests(unittest.TestCase):
    def test_status_vocabulary_and_record_fields_are_minimal(self) -> None:
        self.assertEqual(
            set(ProfileSupportStatus.__members__),
            {"SUPPORTED", "QUALIFICATION_ONLY"},
        )
        self.assertEqual(
            tuple(item.name for item in fields(CompatibilityProfile)),
            ("inventory", "node_snapshot", "status"),
        )

    def test_m2_record_retains_exact_supported_evidence_objects(self) -> None:
        profile = COMFYUI_0280_SUPPORTED_PROFILE
        self.assertIs(profile.inventory, CANONICAL_COMFYUI_0280_INVENTORY)
        self.assertIs(profile.node_snapshot, COMFYUI_0280_NODE_SNAPSHOT)
        self.assertIs(profile.status, ProfileSupportStatus.SUPPORTED)

    def test_candidate_record_retains_exact_qualification_evidence_objects(self) -> None:
        profile = COMFYUI_0345_QUALIFICATION_PROFILE
        self.assertIs(profile.inventory, COMFYUI_0345_QUALIFICATION_INVENTORY)
        self.assertIs(profile.node_snapshot, COMFYUI_0345_NODE_SNAPSHOT)
        self.assertIs(profile.status, ProfileSupportStatus.QUALIFICATION_ONLY)

    def test_complete_registry_has_m2_and_all_candidates_with_matching_pins(self) -> None:
        self.assertEqual(dict(REGISTERED_COMFYUI_PROFILES), {
            CANONICAL_COMFYUI_0280_INVENTORY.comfyui_profile_identifier:
                COMFYUI_0280_HISTORICAL_PROFILE,
            COMFYUI_0345_QUALIFICATION_INVENTORY.comfyui_profile_identifier:
                COMFYUI_0345_QUALIFICATION_PROFILE,
            COMFYUI_0346_QUALIFICATION_PROFILE.inventory.comfyui_profile_identifier:
                DEFAULT_SUPPORTED_PROFILE,
            COMFYUI_0372_QUALIFICATION_PROFILE.inventory.comfyui_profile_identifier:
                COMFYUI_0372_QUALIFICATION_PROFILE,
            COMFYUI_0374_QUALIFICATION_PROFILE.inventory.comfyui_profile_identifier:
                COMFYUI_0374_QUALIFICATION_PROFILE,
        })
        for identifier, profile in REGISTERED_COMFYUI_PROFILES.items():
            with self.subTest(identifier=identifier):
                self.assertEqual(identifier, profile.inventory.comfyui_profile_identifier)
                self.assertEqual(identifier, profile.node_snapshot.profile_identifier)
                self.assertEqual(profile.inventory.expected_comfyui_version, profile.node_snapshot.comfyui_version)
                self.assertEqual(profile.inventory.expected_comfyui_revision, profile.node_snapshot.comfyui_revision)

    def test_records_and_registry_cannot_be_mutated(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            COMFYUI_0345_QUALIFICATION_PROFILE.status = ProfileSupportStatus.SUPPORTED
        with self.assertRaises(TypeError):
            REGISTERED_COMFYUI_PROFILES["unknown"] = COMFYUI_0280_SUPPORTED_PROFILE

    def test_registration_and_current_product_support_are_separate(self) -> None:
        for profile in (COMFYUI_0280_SUPPORTED_PROFILE, COMFYUI_0345_QUALIFICATION_PROFILE):
            with self.subTest(status=profile.status):
                identifier = profile.inventory.comfyui_profile_identifier
                self.assertIs(registered_inventory_for_profile(identifier), profile.inventory)
        self.assertIsNone(supported_inventory_for_profile(
            CANONICAL_COMFYUI_0280_INVENTORY.comfyui_profile_identifier))
        self.assertIs(supported_inventory_for_profile(
            DEFAULT_SUPPORTED_PROFILE.inventory.comfyui_profile_identifier),
            DEFAULT_SUPPORTED_PROFILE.inventory)
        self.assertIs(COMFYUI_0280_HISTORICAL_PROFILE.inventory, CANONICAL_COMFYUI_0280_INVENTORY)
        self.assertIs(COMFYUI_0280_HISTORICAL_PROFILE.node_snapshot, COMFYUI_0280_NODE_SNAPSHOT)
        self.assertIs(COMFYUI_0280_HISTORICAL_PROFILE.status, ProfileSupportStatus.QUALIFICATION_ONLY)
        self.assertIsNone(supported_inventory_for_profile(COMFYUI_0345_QUALIFICATION_INVENTORY.comfyui_profile_identifier))

    def test_unknown_partial_or_normalized_identifiers_have_no_fallback(self) -> None:
        candidate = COMFYUI_0345_QUALIFICATION_INVENTORY.comfyui_profile_identifier
        for identifier in (
            "unknown", "", "0.34.5", "M2", "latest", "qualification_only",
            candidate + " ", " " + candidate, candidate.upper(), candidate + ".other",
            None, [], {},
        ):
            for resolver in (registered_inventory_for_profile, supported_inventory_for_profile):
                with self.subTest(identifier=identifier, resolver=resolver.__name__):
                    self.assertIsNone(resolver(identifier))

    def test_historical_inventory_is_retained_without_a_fabricated_profile(self) -> None:
        identifier = CANONICAL_COMFYUI_INVENTORY.comfyui_profile_identifier
        self.assertNotIn(identifier, REGISTERED_COMFYUI_PROFILES)
        self.assertIs(registered_inventory_for_profile(identifier), CANONICAL_COMFYUI_INVENTORY)
        self.assertIsNone(supported_inventory_for_profile(identifier))

    def test_canonical_wrapper_preserves_only_legacy_inventory_semantics(self) -> None:
        for inventory in (CANONICAL_COMFYUI_INVENTORY, CANONICAL_COMFYUI_0280_INVENTORY):
            self.assertIs(canonical_inventory_for_profile(inventory.comfyui_profile_identifier), inventory)
        self.assertIsNone(canonical_inventory_for_profile(COMFYUI_0345_QUALIFICATION_INVENTORY.comfyui_profile_identifier))
        self.assertIsNone(canonical_inventory_for_profile("unknown"))


class RegisteredInventoryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = make_plan()

    def test_m2_historical_and_exact_candidate_inventory_pins_pass(self) -> None:
        for inventory in (
            CANONICAL_COMFYUI_INVENTORY, CANONICAL_COMFYUI_0280_INVENTORY,
            COMFYUI_0345_QUALIFICATION_INVENTORY,
        ):
            with self.subTest(profile=inventory.comfyui_profile_identifier):
                result = generate(self.plan, inventory)
                self.assertEqual(result.errors, ())
                self.assertIsNotNone(result.artifact)

    def test_adhoc_candidate_identity_and_wrong_version_or_revision_fail(self) -> None:
        inventory = COMFYUI_0345_QUALIFICATION_INVENTORY
        for changed in (
            replace(inventory, comfyui_profile_identifier="comfyui-0.34.5.adhoc"),
            replace(inventory, expected_comfyui_version="0.34.6"),
            replace(inventory, expected_comfyui_revision="f" * 40),
            replace(inventory, expected_comfyui_revision=inventory.expected_comfyui_revision.upper()),
            replace(inventory, comfyui_profile_identifier=[]),
        ):
            with self.subTest(inventory=changed):
                result = generate(self.plan, changed)
                self.assertIsNone(result.artifact)
                self.assertIn("workflow.inventory_profile", codes(result.errors))

    def test_every_altered_registered_inventory_field_is_rejected(self) -> None:
        for inventory in (CANONICAL_COMFYUI_0280_INVENTORY, COMFYUI_0345_QUALIFICATION_INVENTORY):
            for item in fields(inventory):
                original = getattr(inventory, item.name)
                if isinstance(original, Enum):
                    altered = None
                elif isinstance(original, str):
                    altered = original + ".changed"
                elif isinstance(original, int | float):
                    altered = original + 1
                elif isinstance(original, tuple):
                    altered = original + ("changed",)
                else:
                    self.fail(f"Uncovered inventory field: {item.name}")
                with self.subTest(profile=inventory.comfyui_profile_identifier, field=item.name):
                    result = generate(self.plan, replace(inventory, **{item.name: altered}))
                    self.assertIsNone(result.artifact)
                    self.assertTrue({"workflow.inventory_profile", "workflow.component_inventory"} & codes(result.errors))

    def test_qualification_integrity_gate_never_calls_support_or_legacy_resolver(self) -> None:
        module = "conditioning_layers.comfyui.prediction_mixing.profiles"
        with patch(module + ".supported_inventory_for_profile", side_effect=AssertionError("support-policy gate")), \
             patch(module + ".canonical_inventory_for_profile", side_effect=AssertionError("legacy gate")):
            self.assertIsNotNone(generate(self.plan, COMFYUI_0345_QUALIFICATION_INVENTORY).artifact)


if __name__ == "__main__":
    unittest.main()
