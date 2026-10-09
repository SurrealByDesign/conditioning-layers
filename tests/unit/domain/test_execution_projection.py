from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import unittest

from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)
from conditioning_layers.domain.composition_policy import (
    CompositionPolicyReference,
    NORMALIZED_BLEND,
    REQUIRE_NO_OVERLAP,
)
from conditioning_layers.domain.models import COMPOSITION_POLICY_PROTOTYPE_VERSION
from conditioning_layers.domain.canonical import CanonicalizationError, canonical_json_bytes
from conditioning_layers.domain.execution_projection import (
    DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
    build_document_execution_projection,
    fingerprint_document_execution_projection,
    serialize_document_execution_projection,
    verify_document_execution_projection,
)


def document(*, legacy=False, policy=REQUIRE_NO_OVERLAP):
    return ConditioningDocument(
        version=(CURRENT_PROTOTYPE_VERSION if legacy else COMPOSITION_POLICY_PROTOTYPE_VERSION),
        document_id="document-p3b",
        base_prompt="Exact Base Prompt\nwith context",
        selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID,
        layers=tuple(PromptLayer(
            layer_id=f"layer-{index}", name=f"Layer {index}",
            prompt_text=f"Prompt {index}", strength=strength,
            influence_field=InfluenceFieldAssetReference(
                relative_path=f"fields/{index}.png", checksum=str(index) * 64,
            ),
        ) for index, strength in enumerate((1.0, 0.5, 0.0))),
        composition_policy=None if legacy else policy.reference,
    )


class PolicyProjectionTests(unittest.TestCase):
    def test_policy_identity_is_explicit_and_distinct(self):
        no_overlap = build_document_execution_projection(document())
        blend = build_document_execution_projection(document(policy=NORMALIZED_BLEND))
        self.assertEqual(no_overlap.format_identifier, DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER)
        self.assertEqual(no_overlap.format_version, 2)
        self.assertEqual(no_overlap.composition_policy, REQUIRE_NO_OVERLAP.reference)
        self.assertEqual(blend.composition_policy, NORMALIZED_BLEND.reference)
        self.assertNotEqual(no_overlap.fingerprint, blend.fingerprint)
        self.assertEqual(no_overlap.active_layers, blend.active_layers)

    def test_legacy_default_can_be_projected_explicitly_without_mutation(self):
        source = document(legacy=True)
        projection = build_document_execution_projection(source)
        self.assertEqual(projection.composition_policy, REQUIRE_NO_OVERLAP.reference)
        self.assertIsNone(source.composition_policy)
        self.assertEqual(source.version, CURRENT_PROTOTYPE_VERSION)

    def test_deterministic_canonical_identity_and_verification(self):
        source = document(policy=NORMALIZED_BLEND)
        projection = build_document_execution_projection(source)
        self.assertEqual(projection, build_document_execution_projection(source))
        encoded = serialize_document_execution_projection(projection)
        self.assertFalse(encoded.endswith(b"\n"))
        self.assertFalse(encoded.startswith(b"\xef\xbb\xbf"))
        material = json.loads(encoded)
        material.pop("fingerprint")
        self.assertEqual(hashlib.sha256(canonical_json_bytes(material)).hexdigest(), projection.fingerprint)
        verify_document_execution_projection(projection, source)

    def test_save_open_retains_successor_projection_identity(self):
        from conditioning_layers.persistence import decode_document, encode_document
        for policy in (REQUIRE_NO_OVERLAP, NORMALIZED_BLEND):
            with self.subTest(policy=policy.identifier):
                source = document(policy=policy)
                reopened = decode_document(encode_document(source)).document
                self.assertEqual(build_document_execution_projection(source),
                                 build_document_execution_projection(reopened))

    def test_authoring_labels_and_disabled_content_are_excluded(self):
        source = document()
        disabled = replace(source.layers[0], layer_id="disabled", visible=False)
        changed = replace(source, document_id="another-id", layers=(
            disabled, *(replace(layer, name="Renamed") for layer in source.layers)
        ))
        self.assertEqual(build_document_execution_projection(source),
                         build_document_execution_projection(changed))

    def test_order_strength_and_base_prompt_remain_identity_bearing(self):
        source = document(policy=NORMALIZED_BLEND)
        initial = build_document_execution_projection(source)
        variants = (
            replace(source, layers=tuple(reversed(source.layers))),
            source.update_strength("layer-1", 0.25),
            source.update_base_prompt("Different exact context"),
        )
        for changed in variants:
            self.assertNotEqual(initial.fingerprint,
                                build_document_execution_projection(changed).fingerprint)
        self.assertEqual(len(initial.active_layers), 3)
        self.assertEqual(initial.active_layers[2].requested_strength, 0.0)
        self.assertEqual(tuple(layer.layer_id for layer in initial.active_layers),
                         ("layer-0", "layer-1", "layer-2"))

    def test_reference_paths_checksums_and_numeric_spellings_are_canonical(self):
        source = document()
        changed = replace(source, layers=tuple(replace(layer,
            strength=int(layer.strength) if layer.strength in (0, 1) else layer.strength,
            influence_field=replace(layer.influence_field,
                relative_path=layer.influence_field.relative_path.replace("/", "\\"),
                checksum=layer.influence_field.checksum.upper(),
            ),
        ) for layer in source.layers))
        self.assertEqual(build_document_execution_projection(source),
                         build_document_execution_projection(changed))

    def test_projection_and_nested_layers_are_immutable(self):
        projection = build_document_execution_projection(document())
        with self.assertRaises(FrozenInstanceError):
            projection.composition_policy = NORMALIZED_BLEND.reference
        with self.assertRaises(FrozenInstanceError):
            projection.active_layers[0].requested_strength = 0.1

    def test_forged_digest_policy_and_scalar_aliases_do_not_verify(self):
        source = document()
        projection = build_document_execution_projection(source)
        variants = (
            replace(projection, fingerprint="0" * 64),
            replace(projection, composition_policy=NORMALIZED_BLEND.reference),
            replace(projection, format_version=2.0),
            replace(projection, composition_policy=CompositionPolicyReference(
                REQUIRE_NO_OVERLAP.identifier, True)),
            replace(projection, active_layers=(replace(
                projection.active_layers[0], active_ordinal=False
            ), *projection.active_layers[1:])),
        )
        for forged in variants:
            with self.subTest(forged=forged):
                with self.assertRaises(ValueError):
                    verify_document_execution_projection(forged, source)
                if forged.fingerprint == projection.fingerprint:
                    rehashed = replace(forged, fingerprint=fingerprint_document_execution_projection(forged))
                    with self.assertRaises(ValueError):
                        verify_document_execution_projection(rehashed, source)

    def test_invalid_or_missing_policy_and_missing_active_field_reject(self):
        source = document()
        variants = (
            replace(source, composition_policy=None),
            replace(source, composition_policy=CompositionPolicyReference("unknown", 1)),
            replace(source, layers=(replace(source.layers[0], influence_field=None),)),
            source.update_strength("layer-0", float("nan")),
        )
        for changed in variants:
            with self.assertRaises(ValueError):
                build_document_execution_projection(changed)


class NeutralCanonicalTests(unittest.TestCase):
    def test_retained_numeric_and_unicode_rules(self):
        self.assertEqual(canonical_json_bytes({"x": -0.0, "y": 1.0, "z": 1e-7}),
                         b'{"x":0,"y":1,"z":1e-7}')
        self.assertEqual(canonical_json_bytes({"\ue000": 1, "\U00010000": 2}),
                         '{"\U00010000":2,"\ue000":1}'.encode("utf-8"))
        self.assertNotEqual(canonical_json_bytes("e\u0301"), canonical_json_bytes("\u00e9"))

    def test_nonportable_numeric_and_unicode_values_reject(self):
        for value in (float("nan"), float("inf"), (1 << 53), "\ud800", {1: "key"}):
            with self.subTest(value=repr(value)), self.assertRaises(CanonicalizationError):
                canonical_json_bytes(value)


if __name__ == "__main__":
    unittest.main()
