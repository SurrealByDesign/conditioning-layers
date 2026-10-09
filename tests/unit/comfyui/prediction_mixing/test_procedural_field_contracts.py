"""Procedural node surface, pure import boundary and optional registration."""

import ast
import builtins
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import procedural_field_sources as scatter
from conditioning_layers.comfyui.field_fade import FIELD_FADE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui import field_blur as blurs
from conditioning_layers.comfyui import field_remap as remaps
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
          + transforms.FIELD_TRANSFORM_NODE_CLASS_NAMES + repeats.FIELD_REPEAT_NODE_CLASS_NAMES
          + remaps.FIELD_REMAP_NODE_CLASS_NAMES + blurs.FIELD_BLUR_NODE_CLASS_NAMES)


class ProceduralContractTests(unittest.TestCase):
    def test_node_surface(self):
        node = scatter.ConditioningLayersScatterField
        self.assertEqual(node.RETURN_TYPES, ("MASK",))
        self.assertEqual(node.RETURN_NAMES, ("mask",))
        self.assertEqual(node.FUNCTION, "generate")
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        declaration = node.INPUT_TYPES()
        self.assertEqual(tuple(declaration), ("required",))
        inputs = declaration["required"]
        expected = (("seed", "INT", 0, 0, 4294967295), ("grid", "INT", 8, 1, 32),
                    ("density_percent", "INT", 50, 0, 100), ("jitter_percent", "INT", 75, 0, 100),
                    ("radius", "FLOAT", 5.0, .5, 32.0),
                    ("radius_variation_percent", "INT", 25, 0, 100))
        self.assertEqual(tuple(inputs), tuple(item[0] for item in expected) + ("shape",))
        for name, kind, default, low, high in expected:
            self.assertEqual(inputs[name][0], kind)
            self.assertEqual([inputs[name][1][key] for key in ("default", "min", "max")],
                             [default, low, high])
        self.assertEqual(inputs["seed"][1]["step"], 1)
        self.assertIs(inputs["seed"][1]["control_after_generate"], False)
        self.assertEqual(inputs["radius"][1]["step"], .5)
        self.assertEqual(inputs["shape"][0], ["disk", "square", "diamond"])
        self.assertEqual(inputs["shape"][1]["default"], "disk")
        self.assertTrue(all(item[1]["tooltip"] for item in inputs.values()))
        for term in ("stratified lattice", "exactly", "seeded", "Wraparound", "seamless",
                     "binary union", "Invert", "FIXED", "Blur", "BLENDED"):
            self.assertIn(term, node.DESCRIPTION)

    def test_fresh_registration_mappings(self):
        first, names = scatter.initialize_procedural_field_node_registration()
        second, more_names = scatter.initialize_procedural_field_node_registration()
        self.assertEqual(tuple(first), ("ConditioningLayersScatterField",
                                       "ConditioningLayersCyclicPartitionField",
                                       "ConditioningLayersVoronoiPartitionField",
                                       "ConditioningLayersNoiseField",
                                       "ConditioningLayersPolarPartitionField"))
        self.assertEqual(tuple(first), scatter.PROCEDURAL_FIELD_NODE_CLASS_NAMES)
        self.assertIs(first["ConditioningLayersScatterField"], scatter.ConditioningLayersScatterField)
        self.assertIs(first["ConditioningLayersCyclicPartitionField"],
                      scatter.ConditioningLayersCyclicPartitionField)
        self.assertIs(first["ConditioningLayersVoronoiPartitionField"],
                      scatter.ConditioningLayersVoronoiPartitionField)
        self.assertIs(first["ConditioningLayersNoiseField"], scatter.ConditioningLayersNoiseField)
        self.assertIs(first["ConditioningLayersPolarPartitionField"], scatter.ConditioningLayersPolarPartitionField)
        self.assertEqual(names, {"ConditioningLayersScatterField": "Scatter Field",
                                 "ConditioningLayersCyclicPartitionField": "Cyclic Partition Field",
                                 "ConditioningLayersVoronoiPartitionField": "Voronoi Partition Field",
                                 "ConditioningLayersNoiseField": "Noise Field",
                                 "ConditioningLayersPolarPartitionField": "Polar Partition Field"})
        self.assertIsNot(first, second)
        self.assertIsNot(names, more_names)
        first.clear()
        names.clear()
        self.assertTrue(second)
        self.assertTrue(more_names)

    def load_root(self, *, import_failure=False, initialization=None, upstream_failures=False):
        namespace = {"__file__": str(ROOT / "__init__.py"), "__name__": "_scatter_root"}
        original = builtins.__import__

        def controlled(name, *args, **kwargs):
            if import_failure and name == scatter.__name__:
                raise ImportError("offline scatter import failure")
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
                                         (remaps, "initialize_field_remap_node_registration"),
                                         (blurs, "initialize_field_blur_node_registration"),
                                         (layer_nodes, "initialize_layer_node_registration")):
                    stack.enter_context(patch.object(module, function, side_effect=ImportError("offline")))
            stack.enter_context(patch.object(scatter, "initialize_procedural_field_node_registration",
                                            **(initialization or {"wraps": scatter.initialize_procedural_field_node_registration})))
            stack.enter_context(patch.object(patterns, "pattern_registry", side_effect=AssertionError("no assets")))
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), namespace)
        register.assert_called_once_with()
        readiness.assert_called_once_with(None)
        return namespace

    def test_registers_after_blur_even_when_all_upstream_nodes_fail(self):
        for failed in (False, True):
            result = self.load_root(upstream_failures=failed)
            expected = (() if failed else PREFIX) + scatter.PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
            self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), expected)
            self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
            self.assertIsNone(result["PROCEDURAL_FIELD_REGISTRATION_ERROR"])

    def test_import_initialization_and_collision_failure_isolation(self):
        for case in ({"import_failure": True}, {"initialization": {"side_effect": RuntimeError("offline")}},
                     {"initialization": {"return_value": ({"ConditioningLayersFieldBlur": object}, {})}}):
            with self.subTest(case=case):
                result = self.load_root(**case)
                self.assertEqual(tuple(result["NODE_CLASS_MAPPINGS"]), PREFIX + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertEqual(tuple(result["NODE_DISPLAY_NAME_MAPPINGS"]), PREFIX + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertIsNotNone(result["PROCEDURAL_FIELD_REGISTRATION_ERROR"])
                for name in ("FIELD_BLUR", "FIELD_REMAP", "FIELD_REPEAT", "FIELD_TRANSFORM",
                             "PATTERN_FIELD", "FIELD_SOURCE", "LAYER_NODE", "BLEND", "BLEND_READINESS"):
                    self.assertIsNone(result[name + "_REGISTRATION_ERROR"])

    def test_fresh_process_import_registration_controls_and_codes_read_no_files(self):
        source = '''
import sys
from unittest.mock import patch
from contextlib import ExitStack
from pathlib import Path
with ExitStack() as stack:
    for target in ('builtins.open', 'io.open', 'os.open'):
        stack.enter_context(patch(target, side_effect=AssertionError('no file I/O')))
    for method in ('read_bytes', 'read_text'):
        stack.enter_context(patch.object(Path, method, side_effect=AssertionError('no assets')))
    from conditioning_layers.comfyui.procedural_field_sources import (
        initialize_procedural_field_node_registration, ConditioningLayersScatterField, scatter_field_codes,
        ConditioningLayersCyclicPartitionField, cyclic_partition_field_codes,
        ConditioningLayersVoronoiPartitionField, voronoi_partition_field_codes,
        ConditioningLayersNoiseField, noise_field_codes,
        ConditioningLayersPolarPartitionField, polar_partition_field_codes)
    assert initialize_procedural_field_node_registration()[0]
    assert ConditioningLayersScatterField.INPUT_TYPES()['required']['seed'][1]['control_after_generate'] is False
    assert len(scatter_field_codes(0, 8, 50, 75, 5, 25, 'disk')) == 16384
    assert ConditioningLayersCyclicPartitionField.INPUT_TYPES()['required']['columns'][1]['display'] == 'number'
    assert len(cyclic_partition_field_codes(8, 8, 3, 1)) == 4
    assert ConditioningLayersVoronoiPartitionField.INPUT_TYPES()['required']['grid'][1]['max'] == 16
    assert len(voronoi_partition_field_codes(0, 6, 100, 2, 'cyclic', 0)) == 4
    assert ConditioningLayersNoiseField.INPUT_TYPES()['required']['frequency'][1]['display'] == 'number'
    assert len(noise_field_codes(0, 4.0, 4, .5, 0.0, 0.0)) == 16384
    assert ConditioningLayersPolarPartitionField.INPUT_TYPES()['required']['center_x'][1]['display'] == 'number'
    assert len(polar_partition_field_codes(.5, .5, 4, 8, 2, 0, 0, 'spiral')) == 4
for name in ('torch', 'numpy', 'PIL', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
for fragment in ('layer_nodes', 'generalized_blend', 'comfyui_panel', 'pattern_field_source',
                 'field_transform', 'field_repeat', 'field_remap', 'field_blur', 'capabilities.product',
                 'admission'):
    assert not [name for name in sys.modules if fragment in name], fragment
'''
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ast_import_contract(self):
        tree = ast.parse(Path(scatter.__file__).read_text(encoding="utf-8"))
        roots = set()
        imports_from = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                roots.add(node.module.split(".")[0])
                imports_from.append((node.module, tuple(alias.name for alias in node.names)))
        self.assertLessEqual(roots, {"conditioning_layers", "hashlib", "math"})
        self.assertEqual(imports_from, [("conditioning_layers.comfyui.influence_field_sources", ("codes_to_mask",))])


if __name__ == "__main__":
    unittest.main()
