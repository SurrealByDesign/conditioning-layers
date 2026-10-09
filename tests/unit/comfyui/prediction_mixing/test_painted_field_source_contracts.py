"""Painted Field metadata, isolated registration and fresh import; pure lane."""
import ast
import builtins
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import painted_field_source as painted, preset_field_source, field_fade
from conditioning_layers.comfyui.prediction_mixing import blend_component
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes
from test_field_fade_contracts import PREFIX, REGISTRATIONS

ROOT = Path(__file__).resolve().parents[4]
EARLIER = PREFIX + field_fade.FIELD_FADE_NODE_CLASS_NAMES + preset_field_source.PRESET_FIELD_NODE_CLASS_NAMES


class PaintedContracts(unittest.TestCase):
    def test_exact_metadata_and_fresh_mappings(self):
        node = painted.ConditioningLayersPaintedField
        self.assertEqual((node.CATEGORY, node.FUNCTION, node.RETURN_TYPES, node.RETURN_NAMES),
                         ("conditioning/conditioning_layers/fields", "load", ("MASK",), ("mask",)))
        spec = node.INPUT_TYPES()
        self.assertEqual(set(spec), {"required"})
        self.assertEqual(set(spec["required"]), {"field"})
        kind, options = spec["required"]["field"]
        self.assertEqual(kind, "STRING")
        self.assertTrue(options["tooltip"])
        self.assertEqual({k: v for k, v in options.items() if k != "tooltip"},
                         {"default": "", "widgetType": "CONDITIONING_LAYERS_PAINTED_FIELD", "socketless": True})
        mappings, names = painted.initialize_painted_field_node_registration()
        self.assertEqual(names, {"ConditioningLayersPaintedField": "Painted Field"})
        self.assertEqual(mappings, {"ConditioningLayersPaintedField": node})
        mappings.clear(); names.clear()
        self.assertTrue(painted.initialize_painted_field_node_registration()[0])

    def load_root(self, failure=None, upstream=False):
        ns = {"__file__": str(ROOT / "__init__.py"), "__name__": "_painted_root"}
        original = builtins.__import__
        def controlled(name, *args, **kwargs):
            if failure == "import" and name == painted.__name__: raise ImportError("offline")
            return original(name, *args, **kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.dict("os.environ", {}, clear=True))
            stack.enter_context(patch("builtins.__import__", side_effect=controlled))
            register = stack.enter_context(patch.object(routes, "register_routes"))
            ready = stack.enter_context(patch.object(blend_readiness, "register_readiness_route"))
            stack.enter_context(patch.object(blend_component, "initialize_blend_node_registration",
                return_value=({"ConditioningLayersNormalizedBlend": object}, None),
                side_effect=ImportError("offline") if upstream else None))
            if upstream:
                for module, function, _ in REGISTRATIONS + (
                        (field_fade, "initialize_field_fade_node_registration", ()),
                        (preset_field_source, "initialize_preset_field_node_registration", ())):
                    stack.enter_context(patch.object(module, function, side_effect=ImportError("offline")))
            if failure == "init":
                stack.enter_context(patch.object(painted, "initialize_painted_field_node_registration", side_effect=RuntimeError("offline")))
            if failure == "collision":
                stack.enter_context(patch.object(painted, "initialize_painted_field_node_registration",
                    return_value=({"ConditioningLayersPresetField": object}, {})))
            stack.enter_context(patch.object(painted, "decode_field_data_url", side_effect=AssertionError("no decode at registration")))
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), ns)
        register.assert_called_once_with(); ready.assert_called_once_with(None)
        return ns

    def test_import_initialization_collision_failures_preserve_all_earlier_components(self):
        for failure in ("import", "init", "collision"):
            ns = self.load_root(failure=failure)
            self.assertEqual(tuple(ns["NODE_CLASS_MAPPINGS"]), EARLIER)
            self.assertEqual(tuple(ns["NODE_DISPLAY_NAME_MAPPINGS"]), EARLIER)
            self.assertIsNotNone(ns["PAINTED_FIELD_REGISTRATION_ERROR"])

    def test_registration_survives_every_upstream_failure(self):
        for upstream in (False, True):
            ns = self.load_root(upstream=upstream)
            expected = (() if upstream else EARLIER) + painted.PAINTED_FIELD_NODE_CLASS_NAMES
            self.assertEqual(tuple(ns["NODE_CLASS_MAPPINGS"]), expected)
            self.assertEqual(tuple(ns["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
            self.assertIsNone(ns["PAINTED_FIELD_REGISTRATION_ERROR"])

    def test_invalid_input_fails_before_mask_conversion(self):
        with patch.object(painted, "codes_to_mask", side_effect=AssertionError("no runtime")):
            for value in (None, 42, "bad", "data:image/png;base64,AA=="):
                with self.assertRaisesRegex(ValueError, "grayscale-8"):
                    painted.ConditioningLayersPaintedField().load(value)

    def test_import_surface_and_fresh_process_need_no_host_runtime_or_files(self):
        tree = ast.parse(Path(painted.__file__).read_text())
        roots = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(roots, {"conditioning_layers.assets.field_png", "conditioning_layers.comfyui.influence_field_sources"})
        source = '''
import sys
from unittest.mock import patch
with patch('pathlib.Path.read_bytes', side_effect=AssertionError('no files')):
    from conditioning_layers.comfyui.painted_field_source import ConditioningLayersPaintedField, initialize_painted_field_node_registration
    assert initialize_painted_field_node_registration()[0]
    assert ConditioningLayersPaintedField.INPUT_TYPES()['required']['field'][1]['socketless']
for name in ('torch', 'numpy', 'PIL', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
assert not [n for n in sys.modules if 'layer_nodes' in n or 'comfyui_panel' in n or n.endswith('capabilities.product')]
'''
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
