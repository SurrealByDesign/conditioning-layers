"""Field Transform surface and registration isolation; developer lane."""

import builtins
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import field_transform as transforms
from conditioning_layers.comfyui.field_repeat import FIELD_REPEAT_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_remap import FIELD_REMAP_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_blur import FIELD_BLUR_NODE_CLASS_NAMES
from conditioning_layers.comfyui.procedural_field_sources import PROCEDURAL_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_fade import FIELD_FADE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui import influence_field_sources as fields
from conditioning_layers.comfyui import pattern_field_source as patterns
from conditioning_layers.comfyui.prediction_mixing import blend_component, layer_nodes
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes


ROOT = Path(__file__).resolve().parents[4]
PREFIX = (("ConditioningLayersNormalizedBlend",) + layer_nodes.LAYER_NODE_CLASS_NAMES
          + fields.FIELD_SOURCE_NODE_CLASS_NAMES + patterns.PATTERN_FIELD_NODE_CLASS_NAMES)


class TransformContractTests(unittest.TestCase):
    def test_node_contract_defaults_and_fresh_mappings(self):
        mappings, names = transforms.initialize_field_transform_node_registration()
        self.assertEqual(tuple(mappings), transforms.FIELD_TRANSFORM_NODE_CLASS_NAMES)
        self.assertEqual(names, {"ConditioningLayersFieldTransform": "Field Transform"})
        node = mappings["ConditioningLayersFieldTransform"]
        self.assertEqual(node.RETURN_TYPES, ("MASK",))
        self.assertEqual(node.RETURN_NAMES, ("mask",))
        self.assertEqual(node.FUNCTION, "transform")
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        inputs = node.INPUT_TYPES()["required"]
        self.assertEqual(tuple(inputs), ("mask", "uniform_scale", "scale_x", "scale_y", "rotation_degrees",
                                        "offset_x", "offset_y", "flip_horizontal", "flip_vertical"))
        self.assertEqual(inputs["mask"][0], "MASK")
        for name in ("uniform_scale", "scale_x", "scale_y"):
            self.assertEqual(inputs[name][0], "FLOAT")
            self.assertEqual(inputs[name][1]["default"], 1)
            self.assertLess(inputs[name][1]["min"], 1)
            self.assertGreater(inputs[name][1]["max"], 1)
        for name in ("rotation_degrees", "offset_x", "offset_y"):
            self.assertEqual(inputs[name][0], "FLOAT")
            self.assertEqual(inputs[name][1]["default"], 0)
        for name in ("flip_horizontal", "flip_vertical"):
            self.assertEqual(inputs[name][0], "BOOLEAN")
            self.assertIs(inputs[name][1]["default"], False)
        mappings.clear()
        names.clear()
        self.assertTrue(transforms.initialize_field_transform_node_registration()[0])

    def load_root(self, *, import_failure=False, initialization=None, upstream_failures=False):
        namespace = {"__file__": str(ROOT / "__init__.py"), "__name__": "_transform_root"}
        original = builtins.__import__

        def controlled(name, *args, **kwargs):
            if import_failure and name == transforms.__name__:
                raise ImportError("offline transform import failure")
            return original(name, *args, **kwargs)

        with ExitStack() as stack:
            stack.enter_context(patch.dict("os.environ", {}, clear=True))
            stack.enter_context(patch("builtins.__import__", side_effect=controlled))
            register = stack.enter_context(patch.object(routes, "register_routes"))
            readiness = stack.enter_context(patch.object(blend_readiness, "register_readiness_route"))
            stack.enter_context(patch.object(blend_component, "initialize_blend_node_registration",
                                            return_value=({"ConditioningLayersNormalizedBlend": object}, None),
                                            side_effect=ImportError("offline") if upstream_failures else None))
            if upstream_failures:
                for module, function in ((fields, "initialize_field_source_node_registration"),
                                         (patterns, "initialize_pattern_field_node_registration"),
                                         (layer_nodes, "initialize_layer_node_registration")):
                    stack.enter_context(patch.object(module, function, side_effect=ImportError("offline")))
            stack.enter_context(patch.object(transforms, "initialize_field_transform_node_registration",
                                            **(initialization or {"wraps": transforms.initialize_field_transform_node_registration})))
            stack.enter_context(patch.object(patterns, "pattern_registry", side_effect=AssertionError("no assets")))
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), namespace)
        register.assert_called_once_with()
        readiness.assert_called_once_with(None)
        return namespace

    def test_transform_registers_even_when_source_and_consumer_registration_fail(self):
        for failed in (False, True):
            result = self.load_root(upstream_failures=failed)
            expected = (() if failed else PREFIX) + transforms.FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
            self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), expected)
            self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
            self.assertIsNone(result["FIELD_TRANSFORM_REGISTRATION_ERROR"])

    def test_transform_import_initialization_and_collision_failures_are_isolated(self):
        for case in ({"import_failure": True}, {"initialization": {"side_effect": RuntimeError("offline")}},
                     {"initialization": {"return_value": ({"ConditioningLayersLayer": object}, {})}}):
            with self.subTest(case=case):
                result = self.load_root(**case)
                self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), PREFIX + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), PREFIX + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertIsNotNone(result["FIELD_TRANSFORM_REGISTRATION_ERROR"])
                for name in ("PATTERN_FIELD", "FIELD_SOURCE", "LAYER_NODE", "BLEND"):
                    self.assertIsNone(result[name + "_REGISTRATION_ERROR"])

    def test_fresh_import_and_controls_need_no_runtime_files_or_admission(self):
        source = '''
import sys
from unittest.mock import patch
from pathlib import Path
with patch.object(Path, 'read_bytes', side_effect=AssertionError('no assets')), \\
     patch.object(Path, 'read_text', side_effect=AssertionError('no assets')):
    from conditioning_layers.comfyui.field_transform import (
        initialize_field_transform_node_registration, ConditioningLayersFieldTransform)
    assert initialize_field_transform_node_registration()[0]
    assert ConditioningLayersFieldTransform.INPUT_TYPES()['required']['mask'][0] == 'MASK'
for name in ('torch', 'numpy', 'PIL', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
assert not [name for name in sys.modules if 'layer_nodes' in name or 'generalized_blend' in name
            or 'comfyui_panel' in name or 'pattern_field_source' in name or name.endswith('capabilities.product')]
'''
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
