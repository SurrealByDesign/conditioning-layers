"""P3B checks against retained P2B identities, never regenerated goldens."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing.multi_layer import (
    translate_prediction_mixing_multi_layer,
)
from conditioning_layers.assets import (
    FieldRelationshipInput, inspect_field_relationships, to_field_asset_profile,
)
from conditioning_layers.domain import COMPOSITION_POLICY_PROTOTYPE_VERSION, NORMALIZED_BLEND, REQUIRE_NO_OVERLAP
from conditioning_layers.integrations.comfyui_panel.application import materialize_document

from test_multi_layer_application import (
    EXECUTION_ID, FAMILIES, FENCES, canonical_snapshot, fixture_request,
    no_live_activity, synthetic_fields,
)


# Exact retained values from docs/P2B_IMPLEMENTATION_REPORT.md's canonical
# offline identity table. These assertions must never be refreshed for P3B.
RETAINED_IDENTITIES = (
    (
        "102e2827cf1f54f6fe429aa95cbffa85e99fa62f330b45073f38f5c966e83dcd",
        "d8a3acb58843e6a2a0c12759a124815c219fbfd79e318e1bb2efe20759864b17",
        "90b5dc3894c5e5637b6673b70ea1746afd329acd60b5d922feff83c55efcc412",
        "0adeed88bd18eb0b9583eec935d534e2c587f8363142a3381fede556fed08c7a",
        "0b620ff9c9e3b8e05dce508642f58c13e94939f6d4e985cb1aa4338e71a0fbaf",
    ),
    (
        "be628382d56ead68fb47edadaa4e006450868e0e66a5af877c781bc87e443886",
        "f61d14e1b22e03d81f33f4e49ac303e5a40a06c8a7c4bc558dbd2b4348bb4514",
        "571046cb4b092f0e76f86e38c289e5cdd6d790bfa466ad81e74320e93783bb68",
        "e32ab84a49f4b398157cc5dfd570fc665af401b45b3646b14a6b749b980fc4bf",
        "c44e10a5c38c539e2a2d0a80cfc910951febc8a14fe4f8169dd472250c9ffe00",
    ),
)


class P3BHistoricalPreservationTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=no_live_activity, create=True))

    def test_both_retained_exact_three_identity_chains_remain_exact(self):
        for family, expected in zip(FAMILIES, RETAINED_IDENTITIES, strict=True):
            with self.subTest(family=family):
                snapshot = canonical_snapshot(family)
                self.assertEqual(tuple(snapshot[key] for key in (
                    "plan_fingerprint", "graph_fingerprint", "bundle_fingerprint",
                    "runtime_provenance_fingerprint", "not_submitted_provenance_fingerprint",
                )), expected)
                self.assertEqual(snapshot["entry_fingerprint"],
                    "fc1c0d96a8de733ebcb71f08b2db3123a588da8afcf046bd70c92852cd9b6c55")
                self.assertEqual(snapshot["profile_fingerprint"],
                    "22730d46ab017bb58cf6a427e28b758cad8ec3c4ec45f64fb90ce16e13902862")
                self.assertEqual(snapshot["binding_fingerprint"],
                    "1374a3b76426b10e69d4cd2f4510b7ee2801035dbee850e6c4698bfd6ca684c6")

    def test_relationship_measurements_are_policy_independent_and_blend_cannot_translate(self):
        # Synthetic overlap remains test-only and is never a product preset.
        request = fixture_request(field_data=synthetic_fields(overlap_pair=(0, 2)),
                                  strengths=(1.0, 0.5, 0.0))
        with tempfile.TemporaryDirectory(prefix="p3b-certificate-") as temporary:
            materialized = materialize_document(request, EXECUTION_ID, Path(temporary))
            source = materialized.document
            documents = (source, *(replace(
                source, version=COMPOSITION_POLICY_PROTOTYPE_VERSION,
                composition_policy=policy.reference,
            ) for policy in (REQUIRE_NO_OVERLAP, NORMALIZED_BLEND)))
            inspections = tuple(inspect_field_relationships(
                materialized.asset_root,
                tuple(FieldRelationshipInput(layer, index)
                      for index, layer in enumerate(intent.layers) if layer.visible),
            ) for intent in documents)
            certificate = inspections[0].certificate
            self.assertTrue(all(item.certificate == certificate for item in inspections))
            self.assertEqual(certificate.format_identifier, "conditioning-layers.field-relationship-certificate.v1")
            self.assertEqual(certificate.relationship_policy_identifier, "prediction-mixing.ordered-n-way-no-overlap.v1")
            self.assertFalse(certificate.whole_set_evidence.mutual_exclusion)
            profiles = tuple(to_field_asset_profile(item) for item in inspections[0].fields)
            retained = translate_prediction_mixing_multi_layer(source, certificate, profiles)
            self.assertIsNone(retained.plan)
            self.assertIn("translation.overlap_present", {item.code for item in retained.findings})
            blend = translate_prediction_mixing_multi_layer(documents[2], certificate, profiles)
            self.assertIsNone(blend.plan)
            self.assertIn("capability.composition_policy_not_realizable", {item.code for item in blend.findings})


if __name__ == "__main__":
    unittest.main()
