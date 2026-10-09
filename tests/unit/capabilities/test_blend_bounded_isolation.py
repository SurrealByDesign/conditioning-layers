"""Bounded backend authority must remain absent from product selection/imports."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import _bounded_blend, blend, multi_layer, product
from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, CURRENT_PROTOTYPE_VERSION, NORMALIZED_BLEND, REQUIRE_NO_OVERLAP,
)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/tooling"))
from bounded_blend_fixture import bounded_document


class BoundedBlendProductIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_product_support_defaults_admission_and_no_overlap_remain_exact(self):
        self.assertEqual(product.product_supported_cardinalities(), (1, 2, 3))
        self.assertEqual(product.product_policy_cardinalities(), {
            REQUIRE_NO_OVERLAP.identifier: (1, 2, 3), NORMALIZED_BLEND.identifier: (3,),
        })
        self.assertTrue(blend.BLEND_LIVE_QUALIFIED)
        self.assertTrue(blend.BLEND_PRODUCT_ADMITTED)
        for count in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
            document = bounded_document(self.temporary.name, count)
            with self.subTest(count=count), patch.object(
                _bounded_blend, "select_bounded_blend_eligibility", side_effect=AssertionError("product reached offline selector"),
            ) as selector:
                route = product.route_product_prediction_mixing(document)
                self.assertEqual(route.compatible, count == 3)
                if count != 3:
                    self.assertEqual(tuple(f.code for f in route.errors), ("blend.cardinality.unsupported",))
                    self.assertEqual(route.errors[0].message,
                                     "The sole Blend eligibility entry requires exactly three Active Prompt Layers.")
                    with self.assertRaises(ValueError):
                        blend.select_blend_eligibility(document)
                else:
                    self.assertIs(route.eligibility_entry, blend.EXACT_THREE_BLEND_ELIGIBILITY)
                    self.assertIs(blend.select_blend_eligibility(document), blend.EXACT_THREE_BLEND_ELIGIBILITY)
                for policy in (None, REQUIRE_NO_OVERLAP.reference):
                    version = CURRENT_PROTOTYPE_VERSION if policy is None else COMPOSITION_POLICY_PROTOTYPE_VERSION
                    legacy = replace(document, version=version, composition_policy=policy)
                    old = multi_layer.route_prediction_mixing(legacy)
                    new = product.route_product_prediction_mixing(legacy)
                    self.assertEqual((new.contract_identifier, new.eligibility_entry, new.errors, new.warnings),
                                     (old.contract_identifier, old.eligibility_entry, old.errors, old.warnings))
                    if policy is None:
                        self.assertEqual(new.compatible, count in (1, 2, 3))
                selector.assert_not_called()

    def test_offline_entries_cannot_enter_product_through_admission_qualification_settings_or_env(self):
        admitted = product.product_admitted_entries()
        for entry in blend.REGISTERED_BLEND_ELIGIBILITY_ENTRIES[1:]:
            document = bounded_document(self.temporary.name, entry.exact_cardinality)
            with self.subTest(count=entry.exact_cardinality), patch.dict(os.environ, {
                "BLEND_PRODUCT_ADMITTED": "true", "BLEND_LIVE_QUALIFIED": "true",
                "PRODUCT_ADMITTED_ENTRIES": entry.identifier, "BLEND_ELIGIBILITY_ENTRY": entry.identifier,
            }), patch.object(_bounded_blend, "select_bounded_blend_eligibility",
                             side_effect=AssertionError("product reached offline selector")) as selector:
                self.assertEqual(product.product_admitted_entries(), admitted)
                self.assertFalse(product.route_product_prediction_mixing(document).compatible)
                self.assertFalse(product.route_product_prediction_mixing(document, qualification_entry=entry).compatible)
                configured = replace(document, adapter_settings={"eligibility_entry": entry.identifier})
                self.assertFalse(product.route_product_prediction_mixing(configured).compatible)
                with patch.object(product, "PRODUCT_ADMITTED_ENTRIES", admitted + (entry.identifier,)):
                    self.assertEqual(tuple(f.code for f in product.route_product_prediction_mixing(document).errors),
                                     ("capability.product_admission_invalid",))
                selector.assert_not_called()

    def test_no_production_ui_route_or_root_source_references_internal_selector(self):
        selector = ROOT / "src/conditioning_layers/capabilities/_bounded_blend.py"
        paths = [ROOT / "__init__.py", *sorted((ROOT / "src").rglob("*.py")), *sorted((ROOT / "web").rglob("*.js"))]
        for path in paths:
            if path != selector:
                with self.subTest(path=path.relative_to(ROOT)):
                    source = path.read_text(encoding="utf-8")
                    self.assertNotIn("_bounded_blend", source)
                    self.assertNotIn("select_bounded_blend_eligibility", source)
        source = selector.read_text(encoding="utf-8")
        for forbidden in ("os.environ", "getenv", "importlib", "comfyui_panel", "capabilities.product", "MAX_LAYERS"):
            self.assertNotIn(forbidden, source)

    def test_fresh_product_and_root_imports_never_attempt_selector_import(self):
        probe = '''
import importlib
import importlib.abc
import sys
from pathlib import Path
from unittest.mock import patch
attempts = []
class RejectSelector(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "conditioning_layers.capabilities._bounded_blend":
            attempts.append(fullname)
            raise AssertionError("Product imported bounded-N selector")
sys.meta_path.insert(0, RejectSelector())
'''
        for module in (
            "conditioning_layers.capabilities.product",
            "conditioning_layers.integrations.comfyui_panel.application",
            "conditioning_layers.integrations.comfyui_panel.blend_application",
            "conditioning_layers.integrations.comfyui_panel.routes",
        ):
            source = probe + f"importlib.import_module({module!r})\nassert attempts == []\n"
            source += 'assert "conditioning_layers.capabilities._bounded_blend" not in sys.modules\n'
            self.assertProbe(source)
        source = probe + f'''
from conditioning_layers.integrations.comfyui_panel import routes
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.comfyui.prediction_mixing import blend_component
from conditioning_layers.comfyui.influence_field_sources import FIELD_SOURCE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import LAYER_NODE_CLASS_NAMES
root = Path({str(ROOT)!r})
for available in (False, True):
    namespace = {{"__file__": str(root / "__init__.py"), "__name__": "_offline_slice_a_root"}}
    with patch.dict("os.environ", {{}}, clear=True), patch.object(routes, "register_routes") as routes_call, \
         patch.object(blend_readiness, "register_readiness_route"), \
         patch.object(blend_component, "initialize_blend_node_registration",
                      return_value=({{"ConditioningLayersNormalizedBlend": object}}, None),
                      side_effect=None if available else ImportError("offline unavailable")):
        exec(compile((root / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), namespace)
    routes_call.assert_called_once_with()
    # Node System Phase 1 registers its layer nodes separately from Blend.
    expected_prefix = (("ConditioningLayersNormalizedBlend",) if available else ()) + LAYER_NODE_CLASS_NAMES + FIELD_SOURCE_NODE_CLASS_NAMES
    assert tuple(namespace["NODE_CLASS_MAPPINGS"])[:len(expected_prefix)] == expected_prefix
    assert "ConditioningLayersGeneralizedNormalizedBlend" not in namespace["NODE_CLASS_MAPPINGS"]
assert attempts == []
assert "conditioning_layers.capabilities._bounded_blend" not in sys.modules
'''
        self.assertProbe(source)

    def assertProbe(self, source):
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
