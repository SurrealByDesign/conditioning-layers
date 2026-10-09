"""The new product boundary cannot mutate or infer retained backend identity."""

from dataclasses import replace
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import multi_layer, product
from conditioning_layers.capabilities.blend import EXACT_THREE_BLEND_ELIGIBILITY as BLEND_ENTRY
from conditioning_layers.comfyui.prediction_mixing.blend.authority import EXACT_THREE_BLEND_REALIZATION
from conditioning_layers.comfyui.prediction_mixing.blend_component import blend_component_identity
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION, REQUIRE_NO_OVERLAP, CompositionPolicyReference,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tooling"))
from blend_fixture import blend_fixture


class ProductRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.document = blend_fixture(temporary.name)[0]

    def test_default_admitted_legacy_routes_and_counts_preserved(self):
        self.assertIsNone(product.PRODUCT_ADMITTED_ENTRIES)
        self.assertEqual(multi_layer.PRODUCT_ADMITTED_ENTRIES, (
            multi_layer.ORDINARY_PRODUCT_ENTRY_IDENTIFIER, multi_layer.EXACT_THREE_ELIGIBILITY.identifier,
        ))
        self.assertEqual(product.product_admitted_entries(), multi_layer.PRODUCT_ADMITTED_ENTRIES + (BLEND_ENTRY.identifier,))
        self.assertTrue(product.route_product_prediction_mixing(self.document).compatible)
        self.assertEqual(product.product_supported_cardinalities(), (1, 2, 3))
        for count in (0, 1, 2, 3, 4, 9):
            layers = tuple(replace(self.document.layers[i % 3], layer_id=f"layer-{i}") for i in range(count))
            document = replace(self.document, version=CURRENT_PROTOTYPE_VERSION, composition_policy=None, layers=layers)
            new, old = product.route_product_prediction_mixing(document), multi_layer.route_prediction_mixing(document)
            self.assertEqual((new.contract_identifier, new.eligibility_entry, new.errors, new.warnings),
                             (old.contract_identifier, old.eligibility_entry, old.errors, old.warnings))
            self.assertEqual(new.compatible, count in (1, 2, 3))

    def test_admitted_blend_has_no_count_or_policy_fallback(self):
        route = product.route_product_prediction_mixing(self.document)
        self.assertTrue(route.compatible, route.errors)
        self.assertEqual(route.eligibility_entry, BLEND_ENTRY)
        for count in (0, 1, 2, 4, 9):
            layers = tuple(replace(self.document.layers[i % 3], layer_id=f"layer-{i}") for i in range(count))
            self.assertFalse(product.route_product_prediction_mixing(replace(self.document, layers=layers)).compatible)
        for changes in (
            {"composition_policy": REQUIRE_NO_OVERLAP.reference},
            {"composition_policy": CompositionPolicyReference("unknown", 1)},
            {"composition_policy": CompositionPolicyReference(BLEND_ENTRY.composition_policy.policy_identifier, 2)},
            {"version": CURRENT_PROTOTYPE_VERSION}, {"adapter_settings": {"blend": True}},
            {"adapter_settings": {"product_admitted": True}}, {"selected_adapter_id": "unknown"},
        ):
            self.assertFalse(product.route_product_prediction_mixing(replace(self.document, **changes)).compatible)
        self.assertFalse(product.route_product_prediction_mixing(self.document, qualification_entry=multi_layer.EXACT_THREE_ELIGIBILITY).compatible)

    def test_call_time_legacy_flags_survive_default_blend_admission(self):
        with patch.object(multi_layer, "PRODUCT_ADMITTED_ENTRIES", (multi_layer.ORDINARY_PRODUCT_ENTRY_IDENTIFIER,)):
            legacy = replace(self.document, version=CURRENT_PROTOTYPE_VERSION, composition_policy=None)
            self.assertFalse(product.route_product_prediction_mixing(legacy).compatible)
            self.assertTrue(product.route_product_prediction_mixing(self.document).compatible)
            self.assertEqual(product.product_policy_cardinalities()[REQUIRE_NO_OVERLAP.identifier], (1, 2))
        with patch.object(multi_layer, "PRODUCT_ADMITTED_ENTRIES", ()):
            self.assertEqual(product.product_admitted_entries(), (BLEND_ENTRY.identifier,))
            self.assertEqual(product.product_policy_cardinalities()[REQUIRE_NO_OVERLAP.identifier], ())
            self.assertEqual(product.product_supported_cardinalities(), (3,))
            ordinary = replace(self.document, version=CURRENT_PROTOTYPE_VERSION, composition_policy=None, layers=self.document.layers[:1])
            self.assertFalse(product.route_product_prediction_mixing(ordinary).compatible)

    def test_environment_and_status_cannot_change_admission_and_old_table_fails_closed(self):
        with patch.dict(os.environ, {"BLEND_PRODUCT_ADMITTED": "false", "BLEND_LIVE_QUALIFIED": "false", "PRODUCT_ADMITTED_ENTRIES": ""}), patch("conditioning_layers.capabilities.blend.BLEND_PRODUCT_ADMITTED", False), patch("conditioning_layers.capabilities.blend.BLEND_LIVE_QUALIFIED", False):
            self.assertTrue(product.route_product_prediction_mixing(self.document).compatible)
        with patch.object(product, "PRODUCT_ADMITTED_ENTRIES", multi_layer.PRODUCT_ADMITTED_ENTRIES):
            with patch.dict(os.environ, {"BLEND_PRODUCT_ADMITTED": "true", "BLEND_LIVE_QUALIFIED": "true", "PRODUCT_ADMITTED_ENTRIES": BLEND_ENTRY.identifier}):
                self.assertFalse(product.route_product_prediction_mixing(self.document).compatible)
        with patch.object(multi_layer, "PRODUCT_ADMITTED_ENTRIES", multi_layer.PRODUCT_ADMITTED_ENTRIES + (BLEND_ENTRY.identifier,)):
            self.assertFalse(product.route_product_prediction_mixing(self.document).compatible)

    def test_literal_retained_identity_pins(self):
        self.assertEqual(blend_component_identity().implementation_fingerprint,
                         "46e33564c8b1327fae767099e008cf7a1f98b2b8a02c992d67f5a3fba0fd7e31")
        self.assertEqual(BLEND_ENTRY.fingerprint,
                         "aeefb8a4c0697056f42bcd7078236838df4ef15defe68f05309c993666bcda22")
        self.assertEqual(EXACT_THREE_BLEND_REALIZATION.fingerprint,
                         "8264274afbcbb7db30f3389fd03289618bfa4b99e104d0d71405f620cec3f781")

    def test_fresh_product_imports_do_not_load_blend_runtime_or_qualification_tooling(self):
        source = """
import sys
from conditioning_layers.capabilities import product
from conditioning_layers.integrations.comfyui_panel import application, routes
for name in ('torch', 'numpy', 'av', 'comfy', 'nodes', 'server',
             'conditioning_layers.integrations.comfyui_panel.blend_application'):
    assert name not in sys.modules, name
assert not any(name.startswith('tests.tooling') or name.startswith('p3d_blend_') for name in sys.modules)
assert product.product_supported_cardinalities() == (1, 2, 3)
"""
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
