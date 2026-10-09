"""Original-library selection and isolated native registration; developer lane."""

import builtins
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import pattern_field_source as patterns
from conditioning_layers.comfyui import influence_field_sources as fields
from conditioning_layers.comfyui.field_transform import FIELD_TRANSFORM_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_repeat import FIELD_REPEAT_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_remap import FIELD_REMAP_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_blur import FIELD_BLUR_NODE_CLASS_NAMES
from conditioning_layers.comfyui.procedural_field_sources import PROCEDURAL_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_fade import FIELD_FADE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.prediction_mixing import blend_component, layer_nodes
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes


ROOT = Path(__file__).resolve().parents[4]
STEMS = ("checkerboard-coarse", "grid-3x3-center-corners", "grid-3x3-cross",
         "horizontal-stripes", "diagonal-split", "concentric-rings",
         "scattered-islands", "soft-radial-gradient")
ASSETS = tuple(stem + suffix + ".png" for stem in STEMS for suffix in ("", "-inverse"))


class PatternContractTests(unittest.TestCase):
    def test_exact_manifest_order_and_only_intended_fields(self):
        with patch.object(Path, "iterdir", side_effect=AssertionError("no directory discovery")), \
                patch.object(Path, "glob", side_effect=AssertionError("no glob discovery")):
            registry = patterns.pattern_registry()
            self.assertEqual(tuple(registry), ASSETS)
            self.assertEqual(patterns.ConditioningLayersPatternField.INPUT_TYPES()["required"]["asset"][0],
                             list(ASSETS))
        self.assertEqual({path.name for path in patterns.REFERENCE_FIELD_ROOT.iterdir()},
                         set(ASSETS) | {"README.md", "pairs.json"})
        registry.clear()
        self.assertEqual(tuple(patterns.pattern_registry()), ASSETS)

    def test_registration_contract_and_fresh_mappings(self):
        mappings, names = patterns.initialize_pattern_field_node_registration()
        self.assertEqual(tuple(mappings), patterns.PATTERN_FIELD_NODE_CLASS_NAMES)
        self.assertEqual(names, {"ConditioningLayersPatternField": "Pattern Field"})
        node = mappings["ConditioningLayersPatternField"]
        self.assertEqual(node.RETURN_TYPES, ("MASK",))
        self.assertEqual(node.RETURN_NAMES, ("mask",))
        self.assertEqual(node.FUNCTION, "load")
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        mappings.clear()
        self.assertTrue(patterns.initialize_pattern_field_node_registration()[0])

    def test_missing_malformed_and_incompatible_manifest(self):
        original = json.loads((patterns.REFERENCE_FIELD_ROOT / "pairs.json").read_text())
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(patterns, "REFERENCE_FIELD_ROOT", Path(directory)):
            manifest = Path(directory) / "pairs.json"
            with self.assertRaisesRegex(ValueError, "manifest is missing or invalid"):
                patterns.pattern_registry()
            for text in ("{", "null", "[]", "{}"):
                manifest.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "manifest is missing or invalid"):
                    patterns.pattern_registry()
            for key, value in (("source_filename", "../outside.png"),
                               ("source_filename", "preview.jpg"), ("source_sha256", "bad"),
                               ("dimensions", {"width": 256, "height": 128}),
                               ("image_mode", "rgba-8"),
                               ("inverse_filename", "checkerboard-coarse.png")):
                candidate = json.loads(json.dumps(original))
                candidate["pairs"][0][key] = value
                manifest.write_text(json.dumps(candidate), encoding="utf-8")
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "manifest is missing or invalid"):
                    patterns.pattern_registry()

    def test_unknown_assets_rejected_before_io(self):
        for asset in ("README.md", "pairs.json", "preview.png", "../checkerboard-coarse.png", None, []):
            with self.subTest(asset=asset), \
                    patch.object(patterns, "inspect_png_bytes", side_effect=AssertionError("unexpected read")), \
                    self.assertRaisesRegex(ValueError, "unknown library asset"):
                patterns.ConditioningLayersPatternField().load(asset)

    def load_root(self, *, failure=None, initialization=None, upstream_failure=False):
        namespace = {"__file__": str(ROOT / "__init__.py"), "__name__": "_pattern_root"}
        original = builtins.__import__

        def controlled(name, *args, **kwargs):
            if failure and name == patterns.__name__:
                raise ImportError("offline pattern import failure")
            return original(name, *args, **kwargs)

        with patch.dict("os.environ", {}, clear=True), patch("builtins.__import__", side_effect=controlled), \
                patch.object(routes, "register_routes") as register, \
                patch.object(blend_readiness, "register_readiness_route") as readiness, \
                patch.object(blend_component, "initialize_blend_node_registration",
                             return_value=({"ConditioningLayersNormalizedBlend": object}, None),
                             side_effect=ImportError("offline") if upstream_failure else None), \
                patch.object(layer_nodes, "initialize_layer_node_registration",
                             wraps=layer_nodes.initialize_layer_node_registration,
                             side_effect=ImportError("offline") if upstream_failure else None), \
                patch.object(fields, "initialize_field_source_node_registration",
                             wraps=fields.initialize_field_source_node_registration,
                             side_effect=ImportError("offline") if upstream_failure else None), \
                patch.object(patterns, "initialize_pattern_field_node_registration",
                             **(initialization or {"wraps": patterns.initialize_pattern_field_node_registration})), \
                patch.object(patterns, "pattern_registry", side_effect=AssertionError("registration reads no assets")):
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), namespace)
        register.assert_called_once_with()
        readiness.assert_called_once_with(None)
        return namespace

    def test_registration_is_independent_and_reads_no_library(self):
        prefix = (("ConditioningLayersNormalizedBlend",) + layer_nodes.LAYER_NODE_CLASS_NAMES
                  + fields.FIELD_SOURCE_NODE_CLASS_NAMES)
        for failed in (False, True):
            result = self.load_root(upstream_failure=failed)
            expected = (() if failed else prefix) + patterns.PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
            self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), expected)
            self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
            self.assertIsNone(result["PATTERN_FIELD_REGISTRATION_ERROR"])

    def test_import_initialization_and_collision_failure_preserve_existing_nodes(self):
        expected = (("ConditioningLayersNormalizedBlend",) + layer_nodes.LAYER_NODE_CLASS_NAMES
                    + fields.FIELD_SOURCE_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
        for case in ({"failure": True}, {"initialization": {"side_effect": RuntimeError("offline")}},
                     {"initialization": {"return_value": ({"ConditioningLayersLayer": object}, {})}}):
            with self.subTest(case=case):
                result = self.load_root(**case)
                self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), expected)
                self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
                self.assertIsNotNone(result["PATTERN_FIELD_REGISTRATION_ERROR"])
                self.assertIsNone(result["FIELD_SOURCE_REGISTRATION_ERROR"])
                self.assertIsNone(result["LAYER_NODE_REGISTRATION_ERROR"])

    def test_fresh_import_and_selector_need_no_runtime_or_admission(self):
        source = '''
import sys
from conditioning_layers.comfyui.pattern_field_source import (
    initialize_pattern_field_node_registration, ConditioningLayersPatternField)
assert initialize_pattern_field_node_registration()[0]
assert len(ConditioningLayersPatternField.INPUT_TYPES()['required']['asset'][0]) == 16
for name in ('torch', 'numpy', 'PIL', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
assert not [name for name in sys.modules if 'layer_nodes' in name or 'generalized_blend' in name
            or 'comfyui_panel' in name or name.endswith('capabilities.product')]
'''
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
