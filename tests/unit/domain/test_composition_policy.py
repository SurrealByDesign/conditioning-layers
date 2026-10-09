from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import unittest

from conditioning_layers.domain import (
    COMPOSITION_POLICY_FAMILY_ID,
    COMPOSITION_POLICY_PROTOTYPE_VERSION,
    CURRENT_PROTOTYPE_VERSION,
    NORMALIZED_BLEND,
    REGISTERED_COMPOSITION_POLICIES,
    REQUIRE_NO_OVERLAP,
    CompositionPolicyError,
    CompositionPolicyRecord,
    CompositionPolicyReference,
    ConditioningDocument,
    PromptLayer,
    PrototypeDocumentVersion,
    get_effective_composition_policy,
    resolve_composition_policy,
    validate_document,
)


def document(policy=None, *, version=CURRENT_PROTOTYPE_VERSION):
    return ConditioningDocument(
        version=version,
        document_id="policy-document",
        base_prompt="A coherent studio scene",
        layers=(PromptLayer("one", "One", "Blue vase", strength=0.5),),
        composition_policy=policy,
    )


class CompositionPolicyAuthorityTests(unittest.TestCase):
    def test_closed_policy_family_has_exactly_two_unique_reviewed_identities(self):
        self.assertEqual(
            COMPOSITION_POLICY_FAMILY_ID, "conditioning-layers.composition-policy.v1"
        )
        self.assertEqual(
            tuple((policy.identifier, policy.version) for policy in REGISTERED_COMPOSITION_POLICIES),
            (
                ("conditioning-layers.composition-policy.require-no-overlap.v1", 1),
                ("conditioning-layers.composition-policy.normalized-blend.v1", 1),
            ),
        )
        self.assertEqual(len({policy.identifier for policy in REGISTERED_COMPOSITION_POLICIES}), 2)
        self.assertIsInstance(REGISTERED_COMPOSITION_POLICIES, tuple)

    def test_both_known_references_resolve_to_reviewed_authority(self):
        for policy in REGISTERED_COMPOSITION_POLICIES:
            with self.subTest(policy=policy.identifier):
                self.assertIs(resolve_composition_policy(policy.reference), policy)
        self.assertEqual(NORMALIZED_BLEND.display_name, "Blend")

    def test_authority_and_reference_are_immutable(self):
        for value, field, replacement in (
            (REQUIRE_NO_OVERLAP, "version", 2),
            (NORMALIZED_BLEND, "description", "Different semantics"),
            (NORMALIZED_BLEND.reference, "policy_version", 2),
        ):
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(value, field, replacement)

    def test_parameter_free_record_and_reference_have_no_execution_state(self):
        self.assertEqual(
            {field.name for field in fields(CompositionPolicyRecord)},
            {"identifier", "version", "semantic_kind", "display_name", "description", "order_independent"},
        )
        self.assertEqual(
            {field.name for field in fields(CompositionPolicyReference)},
            {"policy_identifier", "policy_version"},
        )
        with self.assertRaises(TypeError):
            CompositionPolicyReference(NORMALIZED_BLEND.identifier, 1, parameters={})

    def test_unknown_identifier_has_no_default_fallback(self):
        with self.assertRaises(CompositionPolicyError) as raised:
            resolve_composition_policy(CompositionPolicyReference("unknown-policy", 1))
        self.assertEqual(raised.exception.code, "composition_policy.identifier.unknown")

    def test_unknown_version_has_no_nearest_version_fallback(self):
        for version in (0, -1, 2):
            with self.subTest(version=version), self.assertRaises(CompositionPolicyError) as raised:
                resolve_composition_policy(CompositionPolicyReference(NORMALIZED_BLEND.identifier, version))
            self.assertEqual(raised.exception.code, "composition_policy.version.unsupported")

    def test_boolean_float_string_and_null_versions_are_not_integer_identity(self):
        for version in (True, False, 1.0, "1", None):
            with self.subTest(version=version), self.assertRaises(CompositionPolicyError) as raised:
                resolve_composition_policy(CompositionPolicyReference(NORMALIZED_BLEND.identifier, version))
            self.assertEqual(raised.exception.code, "composition_policy.version.invalid_type")

    def test_forged_record_or_untyped_reference_cannot_supply_authority(self):
        for value in (
            replace(NORMALIZED_BLEND, semantic_kind="priority"),
            {"policy_identifier": NORMALIZED_BLEND.identifier, "policy_version": 1},
            None,
        ):
            with self.subTest(value=value), self.assertRaises(CompositionPolicyError):
                resolve_composition_policy(value)

    def test_layer_order_is_not_priority_for_either_policy(self):
        self.assertTrue(REQUIRE_NO_OVERLAP.order_independent)
        self.assertTrue(NORMALIZED_BLEND.order_independent)


class DocumentCompositionPolicyTests(unittest.TestCase):
    def test_legacy_default_projects_without_mutating_document(self):
        legacy = document()
        self.assertIs(get_effective_composition_policy(legacy), REQUIRE_NO_OVERLAP)
        self.assertIsNone(legacy.composition_policy)
        self.assertEqual(legacy.version, CURRENT_PROTOTYPE_VERSION)

    def test_successor_requires_explicit_policy_even_for_no_overlap(self):
        successor = document(version=COMPOSITION_POLICY_PROTOTYPE_VERSION)
        self.assertIn("composition_policy.required", {finding.code for finding in validate_document(successor)})
        with self.assertRaises(CompositionPolicyError):
            get_effective_composition_policy(successor)

    def test_successor_policies_are_intrinsically_valid_authored_intent(self):
        for policy in REGISTERED_COMPOSITION_POLICIES:
            with self.subTest(policy=policy.identifier):
                successor = document(policy.reference, version=COMPOSITION_POLICY_PROTOTYPE_VERSION)
                self.assertEqual(validate_document(successor), ())
                self.assertIs(get_effective_composition_policy(successor), policy)

    def test_policy_owned_by_document_not_layer_or_adapter_settings(self):
        successor = document(NORMALIZED_BLEND.reference, version=COMPOSITION_POLICY_PROTOTYPE_VERSION)
        self.assertNotIn("composition_policy", {field.name for field in fields(PromptLayer)})
        self.assertEqual(dict(successor.adapter_settings), {})
        self.assertIsNone(successor.selected_adapter_id)
        self.assertEqual(successor.composition_policy, NORMALIZED_BLEND.reference)

    def test_explicit_policy_cannot_be_attached_to_legacy_document(self):
        for policy in REGISTERED_COMPOSITION_POLICIES:
            with self.subTest(policy=policy.identifier):
                findings = validate_document(document(policy.reference))
                self.assertIn("composition_policy.legacy_explicit", {finding.code for finding in findings})

    def test_unknown_domain_policy_is_a_structured_error(self):
        successor = document(CompositionPolicyReference("unknown", 1), version=COMPOSITION_POLICY_PROTOTYPE_VERSION)
        findings = validate_document(successor)
        self.assertEqual(findings[0].code, "composition_policy.identifier.unknown")
        self.assertEqual(findings[0].field_path, "composition_policy")

    def test_unknown_document_version_cannot_project_an_implicit_policy(self):
        for version in (
            PrototypeDocumentVersion(1, 1), PrototypeDocumentVersion(3, 0),
            PrototypeDocumentVersion(True, 0), PrototypeDocumentVersion(1, False),
            PrototypeDocumentVersion(1.0, 0), None,
        ):
            with self.subTest(version=version), self.assertRaises(CompositionPolicyError):
                get_effective_composition_policy(document(version=version))

    def test_policy_in_adapter_settings_is_rejected(self):
        misplaced = replace(document(), adapter_settings={"composition_policy": {}})
        self.assertIn(
            "composition_policy.invalid_location",
            {finding.code for finding in validate_document(misplaced)},
        )

    def test_legacy_absent_policy_keeps_malformed_and_newer_minor_findings(self):
        for version, code in (
            (PrototypeDocumentVersion(True, 0), "document.version.invalid"),
            (PrototypeDocumentVersion(1, False), "document.version.invalid"),
            (PrototypeDocumentVersion(1.0, 0), "document.version.invalid"),
            (PrototypeDocumentVersion(1, 1), "document.version.newer_minor"),
            (None, "document.version.invalid_type"),
        ):
            with self.subTest(version=version):
                self.assertEqual(
                    tuple(finding.code for finding in validate_document(document(version=version))),
                    (code,),
                )

    def test_successor_version_cannot_be_forged_with_subclass_equality(self):
        class VersionSubclass(PrototypeDocumentVersion):
            pass

        class IntegerSubclass(int):
            pass

        for version in (VersionSubclass(2, 0), PrototypeDocumentVersion(2, IntegerSubclass(0))):
            with self.subTest(version=version):
                self.assertIn(
                    "document.version.unsupported_major",
                    {finding.code for finding in validate_document(document(version=version))},
                )

    def test_document_edits_preserve_policy_base_prompt_and_strength_values(self):
        successor = document(NORMALIZED_BLEND.reference, version=COMPOSITION_POLICY_PROTOTYPE_VERSION)
        edited = successor.duplicate_layer("one", "two").move_layer("two", 0).update_strength("one", 0)
        self.assertEqual(edited.composition_policy, NORMALIZED_BLEND.reference)
        self.assertEqual(edited.base_prompt, successor.base_prompt)
        self.assertEqual([layer.strength for layer in edited.layers], [0.5, 0])
        self.assertEqual(len(edited.active_layers), 2)


if __name__ == "__main__":
    unittest.main()
