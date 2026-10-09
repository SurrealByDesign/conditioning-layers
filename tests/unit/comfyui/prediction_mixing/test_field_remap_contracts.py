"""Field Remap node surface and failure isolation; developer lane."""

import builtins
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import field_remap as remaps
from conditioning_layers.comfyui.field_blur import FIELD_BLUR_NODE_CLASS_NAMES
from conditioning_layers.comfyui.procedural_field_sources import PROCEDURAL_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_fade import FIELD_FADE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui import field_repeat as repeats
from conditioning_layers.comfyui import field_transform as transforms
from conditioning_layers.comfyui import influence_field_sources as fields
from conditioning_layers.comfyui import pattern_field_source as patterns
from conditioning_layers.comfyui.prediction_mixing import blend_component, layer_nodes
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes


ROOT = Path(__file__).resolve().parents[4]
PREFIX = (("ConditioningLayersNormalizedBlend",) + layer_nodes.LAYER_NODE_CLASS_NAMES
          + fields.FIELD_SOURCE_NODE_CLASS_NAMES + patterns.PATTERN_FIELD_NODE_CLASS_NAMES
          + transforms.FIELD_TRANSFORM_NODE_CLASS_NAMES + repeats.FIELD_REPEAT_NODE_CLASS_NAMES)


class RemapContractTests(unittest.TestCase):
    def test_node_contract_defaults_bounds_and_fresh_mappings(self):
        mappings, names = remaps.initialize_field_remap_node_registration()
        self.assertEqual(tuple(mappings), remaps.FIELD_REMAP_NODE_CLASS_NAMES)
        self.assertEqual(names, {"ConditioningLayersFieldRemap": "Field Remap"})
        node = mappings["ConditioningLayersFieldRemap"]
        self.assertEqual(node.RETURN_TYPES, ("MASK",))
        self.assertEqual(node.RETURN_NAMES, ("mask",))
        self.assertEqual(node.FUNCTION, "remap")
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        inputs = node.INPUT_TYPES()["required"]
        self.assertEqual(tuple(inputs), ("mask", "input_low", "input_high", "output_low", "output_high"))
        self.assertEqual(inputs["mask"][0], "MASK")
        for name, default in (("input_low", 0), ("input_high", 255), ("output_low", 0), ("output_high", 255)):
            self.assertEqual(inputs[name][0], "INT")
            self.assertEqual([inputs[name][1][key] for key in ("default", "min", "max", "step")],
                             [default, 0, 255, 1])
        mappings.clear()
        names.clear()
        self.assertTrue(remaps.initialize_field_remap_node_registration()[0])

    def load_root(self, *, import_failure=False, initialization=None, upstream_failures=False):
        namespace = {"__file__": str(ROOT / "__init__.py"), "__name__": "_remap_root"}
        original = builtins.__import__

        def controlled(name, *args, **kwargs):
            if import_failure and name == remaps.__name__:
                raise ImportError("offline remap import failure")
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
                                         (transforms, "initialize_field_transform_node_registration"),
                                         (repeats, "initialize_field_repeat_node_registration"),
                                         (layer_nodes, "initialize_layer_node_registration")):
                    stack.enter_context(patch.object(module, function, side_effect=ImportError("offline")))
            stack.enter_context(patch.object(remaps, "initialize_field_remap_node_registration",
                                            **(initialization or {"wraps": remaps.initialize_field_remap_node_registration})))
            stack.enter_context(patch.object(patterns, "pattern_registry", side_effect=AssertionError("no assets")))
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), namespace)
        register.assert_called_once_with()
        readiness.assert_called_once_with(None)
        return namespace

    def test_remap_registers_when_spatial_source_and_consumer_registration_fail(self):
        for failed in (False, True):
            result = self.load_root(upstream_failures=failed)
            expected = (() if failed else PREFIX) + remaps.FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
            self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), expected)
            self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
            self.assertIsNone(result["FIELD_REMAP_REGISTRATION_ERROR"])

    def test_remap_import_initialization_and_collision_failures_are_isolated(self):
        for case in ({"import_failure": True}, {"initialization": {"side_effect": RuntimeError("offline")}},
                     {"initialization": {"return_value": ({"ConditioningLayersFieldRepeat": object}, {})}}):
            with self.subTest(case=case):
                result = self.load_root(**case)
                self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), PREFIX + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), PREFIX + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertIsNotNone(result["FIELD_REMAP_REGISTRATION_ERROR"])
                for name in ("FIELD_REPEAT", "FIELD_TRANSFORM", "PATTERN_FIELD", "FIELD_SOURCE", "LAYER_NODE", "BLEND"):
                    self.assertIsNone(result[name + "_REGISTRATION_ERROR"])

    def test_fresh_import_and_controls_need_no_runtime_assets_spatial_nodes_or_admission(self):
        source = '''
import sys
from unittest.mock import patch
from pathlib import Path
with patch.object(Path, 'read_bytes', side_effect=AssertionError('no assets')), \\
     patch.object(Path, 'read_text', side_effect=AssertionError('no assets')):
    from conditioning_layers.comfyui.field_remap import (
        initialize_field_remap_node_registration, ConditioningLayersFieldRemap)
    assert initialize_field_remap_node_registration()[0]
    assert ConditioningLayersFieldRemap.INPUT_TYPES()['required']['mask'][0] == 'MASK'
for name in ('torch', 'numpy', 'PIL', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
assert not [name for name in sys.modules if 'layer_nodes' in name or 'generalized_blend' in name
            or 'comfyui_panel' in name or 'pattern_field_source' in name or 'field_transform' in name
            or 'field_repeat' in name or name.endswith('capabilities.product')]
'''
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
