from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION,
    CURRENT_PROTOTYPE_VERSION,
    NORMALIZED_BLEND,
    REQUIRE_NO_OVERLAP,
    CompositionPolicyReference,
    ConditioningDocument,
    PromptLayer,
    get_effective_composition_policy,
)
from conditioning_layers.persistence import (
    COMPOSITION_POLICY_FORMAT_VERSION,
    CURRENT_FORMAT_VERSION,
    DocumentEncodeError,
    decode_document,
    encode_document,
    load_document,
    save_document,
)
from conditioning_layers.persistence.migrations import PrototypeFormatVersion, dispatch_migration


def legacy_document():
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="policy-document",
        base_prompt="A coherent studio scene",
        layers=(PromptLayer("one", "One", "Blue vase"),),
    )


def successor_document(policy=NORMALIZED_BLEND):
    return replace(
        legacy_document(),
        version=COMPOSITION_POLICY_PROTOTYPE_VERSION,
        composition_policy=policy.reference,
    )


class CompositionPolicyPersistenceTests(unittest.TestCase):
    def assert_rejected(self, payload, code):
        result = decode_document(json.dumps(payload))
        self.assertFalse(result.ok)
        self.assertIsNone(result.document)
        self.assertIn(code, {finding.code for finding in result.persistence_findings})
        return result

    def test_dispatch_supports_only_retained_1_0_and_explicit_successor_2_0(self):
        self.assertEqual(CURRENT_FORMAT_VERSION, PrototypeFormatVersion(1, 0))
        self.assertEqual(COMPOSITION_POLICY_FORMAT_VERSION, PrototypeFormatVersion(2, 0))
        self.assertTrue(dispatch_migration(CURRENT_FORMAT_VERSION).supported)
        self.assertTrue(dispatch_migration(COMPOSITION_POLICY_FORMAT_VERSION).supported)
        for version, relation in ((PrototypeFormatVersion(0, 9), "older"), (PrototypeFormatVersion(1, 1), "newer"), (PrototypeFormatVersion(2, 1), "newer"), (PrototypeFormatVersion(3, 0), "newer")):
            with self.subTest(version=version):
                decision = dispatch_migration(version)
                self.assertFalse(decision.supported)
                self.assertEqual(decision.findings[0].code, f"format.version.unsupported_{relation}")

    def test_legacy_round_trip_remains_implicit_and_byte_stable(self):
        encoded = encode_document(legacy_document())
        result = decode_document(encoded)
        self.assertTrue(result.ok, result.findings)
        self.assertEqual(encode_document(result.document), encoded)
        self.assertNotIn("composition_policy", encoded)
        self.assertIsNone(result.document.composition_policy)
        self.assertIs(get_effective_composition_policy(result.document), REQUIRE_NO_OVERLAP)

    def test_successor_explicit_no_overlap_round_trip(self):
        self.assert_policy_round_trip(REQUIRE_NO_OVERLAP)

    def test_successor_explicit_blend_round_trip(self):
        self.assert_policy_round_trip(NORMALIZED_BLEND)

    def assert_policy_round_trip(self, policy):
        document = successor_document(policy)
        encoded = encode_document(document)
        result = decode_document(encoded)
        self.assertTrue(result.ok, result.findings)
        self.assertEqual(result.document, document)
        self.assertEqual(encode_document(result.document), encoded)
        payload = json.loads(encoded)
        self.assertEqual(payload["format_version"], {"major": 2, "minor": 0})
        self.assertEqual(payload["document"]["version"], {"major": 2, "minor": 0})
        self.assertEqual(payload["document"]["composition_policy"], {"policy_identifier": policy.identifier, "policy_version": policy.version})
        self.assertEqual(payload["document"]["adapter"]["settings"], {})
        self.assertEqual(set(payload["document"]["composition_policy"]), {"policy_identifier", "policy_version"})

    def test_successor_missing_policy_rejects_without_default_projection(self):
        payload = json.loads(encode_document(successor_document()))
        del payload["document"]["composition_policy"]
        result = self.assert_rejected(payload, "composition_policy.required")
        self.assertEqual(result.persistence_findings[0].json_path, "$.document.composition_policy")

    def test_successor_unknown_policy_identifier_rejects(self):
        payload = json.loads(encode_document(successor_document()))
        payload["document"]["composition_policy"]["policy_identifier"] = "unknown"
        self.assert_rejected(payload, "composition_policy.identifier.unknown")

    def test_successor_unknown_policy_version_rejects(self):
        for version in (-1, 0, 2):
            with self.subTest(version=version):
                payload = json.loads(encode_document(successor_document()))
                payload["document"]["composition_policy"]["policy_version"] = version
                self.assert_rejected(payload, "composition_policy.version.unsupported")

    def test_successor_wrong_typed_version_rejects(self):
        for version in (True, False, 1.0, "1", None, []):
            with self.subTest(version=version):
                payload = json.loads(encode_document(successor_document()))
                payload["document"]["composition_policy"]["policy_version"] = version
                self.assert_rejected(payload, "composition_policy.version.invalid_type")

    def test_successor_unsupported_policy_shapes_reject(self):
        valid = {"policy_identifier": NORMALIZED_BLEND.identifier, "policy_version": 1}
        for policy in (None, "Blend", [], {}, {"policy_identifier": NORMALIZED_BLEND.identifier}, {"policy_version": 1}, {**valid, "parameters": {}}, {**valid, "epsilon": 0}, {**valid, "scope": "document"}):
            with self.subTest(policy=policy):
                payload = json.loads(encode_document(successor_document()))
                payload["document"]["composition_policy"] = policy
                self.assert_rejected(payload, "composition_policy.invalid_representation")

    def test_duplicate_policy_identifier_json_key_rejects(self):
        encoded = encode_document(successor_document())
        encoded = encoded.replace('"policy_version": 1', '"policy_version": 1, "policy_version": 1')
        result = decode_document(encoded)
        self.assertIsNone(result.document)
        self.assertIn("json.duplicate_key", {finding.code for finding in result.persistence_findings})

    def test_legacy_explicit_policy_cannot_be_warned_away(self):
        for policy in (None, {}, {"policy_identifier": REQUIRE_NO_OVERLAP.identifier, "policy_version": 1}, {"policy_identifier": NORMALIZED_BLEND.identifier, "policy_version": 1}):
            with self.subTest(policy=policy):
                payload = json.loads(encode_document(legacy_document()))
                payload["document"]["composition_policy"] = policy
                self.assert_rejected(payload, "composition_policy.legacy_explicit")

    def test_misplaced_policy_cannot_be_discarded_or_used_as_adapter_settings(self):
        for location in ("root", "layer", "field", "adapter", "settings", "version"):
            with self.subTest(location=location):
                payload = json.loads(encode_document(successor_document(REQUIRE_NO_OVERLAP)))
                layer = payload["document"]["layers"][0]
                layer["influence_field"] = {"path": "fields/one.png", "sha256": None}
                targets = {
                    "root": payload,
                    "layer": layer,
                    "field": layer["influence_field"],
                    "adapter": payload["document"]["adapter"],
                    "settings": payload["document"]["adapter"]["settings"],
                    "version": payload["document"]["version"],
                }
                targets[location]["composition_policy"] = {
                    "policy_identifier": NORMALIZED_BLEND.identifier,
                    "policy_version": 1,
                }
                self.assert_rejected(payload, "composition_policy.invalid_location")

    def test_document_and_envelope_successor_versions_must_match(self):
        for envelope, domain in ((1, 2), (2, 1), (2, 3)):
            with self.subTest(envelope=envelope, domain=domain):
                payload = json.loads(encode_document(successor_document()))
                payload["format_version"]["major"] = envelope
                payload["document"]["version"]["major"] = domain
                if envelope == 1:
                    del payload["document"]["composition_policy"]
                self.assert_rejected(payload, "composition_policy.document_version.mismatch")

    def test_unsupported_newer_envelope_keeps_existing_fail_closed_diagnostic(self):
        payload = json.loads(encode_document(successor_document()))
        payload["format_version"]["major"] = 3
        self.assert_rejected(payload, "format.version.unsupported_newer")

    def test_encode_rejects_missing_unknown_or_legacy_explicit_policy(self):
        for document in (
            replace(successor_document(), composition_policy=None),
            replace(successor_document(), composition_policy=CompositionPolicyReference("unknown", 1)),
            replace(legacy_document(), composition_policy=NORMALIZED_BLEND.reference),
        ):
            with self.subTest(document=document), self.assertRaises(DocumentEncodeError):
                encode_document(document)

    def test_open_legacy_bytes_never_rewrites_file(self):
        raw = json.dumps(json.loads(encode_document(legacy_document())), indent=4).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.conditioning.json"
            path.write_bytes(raw)
            before = path.stat().st_mtime_ns
            loaded = load_document(path)
            self.assertTrue(loaded.ok, loaded.findings)
            self.assertIs(get_effective_composition_policy(loaded.document), REQUIRE_NO_OVERLAP)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_file_save_open_and_save_as_preserve_each_policy(self):
        for policy in (REQUIRE_NO_OVERLAP, NORMALIZED_BLEND):
            with self.subTest(policy=policy.identifier), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "original.conditioning.json"
                destination = Path(temporary) / "copy.conditioning.json"
                document = successor_document(policy)
                save_document(document, path)
                original_bytes = path.read_bytes()
                loaded = load_document(path)
                self.assertTrue(loaded.ok, loaded.findings)
                self.assertEqual(loaded.document.composition_policy, policy.reference)
                save_document(loaded.document, destination)
                reopened = load_document(destination)
                self.assertTrue(reopened.ok, reopened.findings)
                self.assertEqual(reopened.document.composition_policy, policy.reference)
                self.assertEqual(destination.read_bytes(), original_bytes)
                self.assertEqual(path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
