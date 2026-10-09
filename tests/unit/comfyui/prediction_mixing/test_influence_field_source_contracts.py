"""Field source node contracts and isolated registration; developer lane."""

import builtins
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import influence_field_sources as fields
from conditioning_layers.comfyui.field_transform import FIELD_TRANSFORM_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_repeat import FIELD_REPEAT_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_remap import FIELD_REMAP_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_blur import FIELD_BLUR_NODE_CLASS_NAMES
from conditioning_layers.comfyui.procedural_field_sources import PROCEDURAL_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_fade import FIELD_FADE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.pattern_field_source import PATTERN_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.prediction_mixing import blend_component, layer_nodes
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes


ROOT = Path(__file__).resolve().parents[4]


class SourceContractTests(unittest.TestCase):
    def test_node_contracts_and_fresh_mappings(self):
        mappings, names = fields.initialize_field_source_node_registration()
        self.assertEqual(tuple(mappings), fields.FIELD_SOURCE_NODE_CLASS_NAMES)
        self.assertEqual(tuple(names.values()), ("Solid Field", "Rectangle Field", "Ellipse Field",
                                                "Linear Gradient Field", "Radial Gradient Field", "Invert Field"))
        for node in mappings.values():
            self.assertEqual(node.RETURN_TYPES, ("MASK",))
            self.assertEqual(node.RETURN_NAMES, ("mask",))
            self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
            self.assertTrue(callable(getattr(node(), node.FUNCTION)))
            self.assertTrue(node.DESCRIPTION)
            self.assertEqual(set(node.INPUT_TYPES()), {"required"})
        mappings.clear()
        names.clear()
        self.assertEqual(tuple(fields.initialize_field_source_node_registration()[0]),
                         fields.FIELD_SOURCE_NODE_CLASS_NAMES)

    def test_invert_mask_socket_and_registered_function(self):
        mappings, names = fields.initialize_field_source_node_registration()
        node = mappings["ConditioningLayersInvertField"]
        self.assertIs(node, fields.ConditioningLayersInvertField)
        self.assertEqual(names["ConditioningLayersInvertField"], "Invert Field")
        self.assertEqual(tuple(node.INPUT_TYPES()["required"]), ("mask",))
        self.assertEqual(node.INPUT_TYPES()["required"]["mask"][0], "MASK")
        self.assertEqual(node.FUNCTION, "invert")

    def load_root(self, source_patch=None, *, failed_dependencies=False, import_failure=False):
        namespace = {"__file__": str(ROOT / "__init__.py"), "__name__": "_field_sources_root"}
        original = builtins.__import__

        def controlled_import(name, *args, **kwargs):
            if import_failure and name == fields.__name__:
                raise ImportError("offline source import failure")
            return original(name, *args, **kwargs)

        with patch.dict("os.environ", {}, clear=True), patch.object(routes, "register_routes") as register, \
                patch.object(blend_readiness, "register_readiness_route") as readiness, \
                patch.object(blend_component, "initialize_blend_node_registration",
                             return_value=({"ConditioningLayersNormalizedBlend": object}, None),
                             side_effect=ImportError("offline Blend") if failed_dependencies else None), \
                patch.object(layer_nodes, "initialize_layer_node_registration",
                             wraps=None if failed_dependencies else layer_nodes.initialize_layer_node_registration,
                             side_effect=ImportError("offline Layer") if failed_dependencies else None), \
                patch.object(fields, "initialize_field_source_node_registration",
                             **(source_patch or {"wraps": fields.initialize_field_source_node_registration})), \
                patch("builtins.__import__", side_effect=controlled_import):
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), namespace)
        register.assert_called_once_with()
        readiness.assert_called_once_with(None)
        return namespace

    def test_sources_register_even_if_layer_and_blend_fail(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                result = self.load_root(failed_dependencies=failed)
                prefix = () if failed else ("ConditioningLayersNormalizedBlend",) + layer_nodes.LAYER_NODE_CLASS_NAMES
                expected = prefix + fields.FIELD_SOURCE_NODE_CLASS_NAMES + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
                self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), expected)
                self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
                self.assertIsNone(result["FIELD_SOURCE_REGISTRATION_ERROR"])

    def test_source_import_initialization_and_collision_failures_are_isolated(self):
        cases = ({"import_failure": True},
                 {"source_patch": {"side_effect": RuntimeError("offline initialization")}},
                 {"source_patch": {"return_value": ({"ConditioningLayersLayer": object}, {})}})
        for case in cases:
            with self.subTest(case=case):
                result = self.load_root(**case)
                self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]),
                                 ("ConditioningLayersNormalizedBlend",) + layer_nodes.LAYER_NODE_CLASS_NAMES
                                 + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), tuple(result["NODE_CLASS_MAPPINGS"]))
                self.assertIsNotNone(result["FIELD_SOURCE_REGISTRATION_ERROR"])
                self.assertIsNone(result["LAYER_NODE_REGISTRATION_ERROR"])
                self.assertIsNone(result["BLEND_REGISTRATION_ERROR"])

    def test_fresh_import_needs_no_runtime_or_admission_or_layer_nodes(self):
        source = """
import sys
from conditioning_layers.comfyui.influence_field_sources import initialize_field_source_node_registration
assert initialize_field_source_node_registration()[0]
for name in ('torch', 'numpy', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
assert not [name for name in sys.modules if 'layer_nodes' in name or 'generalized_blend' in name
            or 'comfyui_panel' in name or name.endswith('capabilities.product')]
"""
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
