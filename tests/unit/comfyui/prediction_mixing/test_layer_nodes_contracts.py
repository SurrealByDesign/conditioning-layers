"""Node System Phase 1 values, node contracts, registration and boundaries; developer lane.

Torch is never imported here: only disabled layers are created, and the
runtime tensor paths belong to test_layer_node_runtime.py on the host lane.
"""

import ast
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.influence_field_sources import FIELD_SOURCE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_transform import FIELD_TRANSFORM_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_repeat import FIELD_REPEAT_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_remap import FIELD_REMAP_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_blur import FIELD_BLUR_NODE_CLASS_NAMES
from conditioning_layers.comfyui.procedural_field_sources import PROCEDURAL_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_fade import FIELD_FADE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.pattern_field_source import PATTERN_FIELD_NODE_CLASS_NAMES

from conditioning_layers.comfyui.prediction_mixing import blend_component, generalized_blend_component
from conditioning_layers.comfyui.prediction_mixing.blend_node import ConditioningLayersNormalizedBlend
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    FIELD_SHAPE, LAYER_NODE_CLASS_NAMES, LAYER_STACK_TYPE, LAYER_TYPE, UPSTREAM_METADATA,
    ConditioningLayersAddLayer, ConditioningLayersCompose, ConditioningLayersLayer,
    LayerDescriptor, LayerMode, LayerStack, initialize_layer_node_registration, nodes,
)
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes


ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "src/conditioning_layers/comfyui/prediction_mixing/layer_nodes"


def layer(layer_id="7", **overrides):
    values = {"conditioning": object(), "mask": object(), "strength": 1.0,
              "mode": LayerMode.BLENDED, "enabled": True, **overrides}
    return LayerDescriptor(layer_id, **values)


def disabled_layer(unique_id):
    return ConditioningLayersLayer().create(object(), object(), 0.5, "FIXED", False, unique_id=unique_id)[0]


class DescriptorTests(unittest.TestCase):
    def test_descriptor_normalizes_exact_authored_values(self):
        value = layer(strength=1, mode="FIXED")
        self.assertEqual((value.strength, type(value.strength), value.mode), (1.0, float, LayerMode.FIXED))
        self.assertEqual(str(layer(strength=-0.0).strength), "0.0")

    def test_descriptor_rejects_malformed_values(self):
        for overrides in ({"strength": float("nan")}, {"strength": float("inf")}, {"strength": -0.1},
                          {"strength": 1.01}, {"strength": True}, {"strength": "1"}, {"mode": "blended"},
                          {"mode": None}, {"mode": 1}, {"enabled": 1}, {"enabled": None}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                layer(**overrides)
        for layer_id in (None, "", "  ", 7):
            with self.subTest(layer_id=layer_id), self.assertRaises(ValueError):
                layer(layer_id)

    def test_identity_is_the_authoring_node_never_content(self):
        conditioning, mask = object(), object()
        first = layer("1", conditioning=conditioning, mask=mask)
        second = layer("2", conditioning=conditioning, mask=mask)
        self.assertNotEqual(first, second)
        self.assertEqual(len({first, second}), 2)
        self.assertEqual(LayerStack((first, second)).layers, (first, second))


class StackTests(unittest.TestCase):
    def test_append_keeps_authored_order_and_returns_a_new_stack(self):
        a, b, c = layer("a"), layer("b", enabled=False), layer("c")
        stack = LayerStack((a,))
        grown = stack.append(b).append(c)
        self.assertEqual(stack.layers, (a,))
        self.assertEqual(grown.layers, (a, b, c))
        self.assertEqual(grown.enabled_layers, (a, c))

    def test_stack_rejects_duplicates_and_malformed_members(self):
        a = layer("a")
        for layers in ((a, a), (a, layer("a")), (), [a], (a, object())):
            with self.subTest(layers=layers), self.assertRaises(ValueError):
                LayerStack(layers)
        with self.assertRaises(ValueError):
            LayerStack((a,)).append(a)


class NodeContractTests(unittest.TestCase):
    def test_registration_is_exactly_three_nodes_with_fresh_mappings(self):
        mappings, names = initialize_layer_node_registration()
        self.assertEqual(LAYER_NODE_CLASS_NAMES,
                         ("ConditioningLayersLayer", "ConditioningLayersAddLayer", "ConditioningLayersCompose"))
        self.assertEqual(tuple(mappings), LAYER_NODE_CLASS_NAMES)
        self.assertEqual(tuple(mappings.values()),
                         (ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose))
        self.assertEqual(names, {"ConditioningLayersLayer": "Conditioning Layer",
                                 "ConditioningLayersAddLayer": "Add Conditioning Layer",
                                 "ConditioningLayersCompose": "Compose Conditioning Layers"})
        mappings.clear()
        self.assertEqual(tuple(initialize_layer_node_registration()[0]), LAYER_NODE_CLASS_NAMES)

    def test_layer_node_contract(self):
        declared = ConditioningLayersLayer.INPUT_TYPES()
        required = declared["required"]
        self.assertEqual(tuple(required), ("conditioning", "mask", "strength", "mode", "enabled"))
        self.assertEqual((required["conditioning"][0], required["mask"][0]), ("CONDITIONING", "MASK"))
        self.assertEqual(required["strength"][0], "FLOAT")
        self.assertEqual({key: required["strength"][1][key] for key in ("default", "min", "max")},
                         {"default": 1.0, "min": 0.0, "max": 1.0})
        self.assertEqual(required["mode"][0], ["BLENDED", "FIXED"])
        self.assertEqual(required["mode"][1]["default"], "BLENDED")
        self.assertEqual((required["enabled"][0], required["enabled"][1]["default"]), ("BOOLEAN", True))
        self.assertEqual(declared["hidden"], {"unique_id": "UNIQUE_ID"})
        self.assertEqual(set(declared), {"required", "hidden"})
        self.assertEqual((ConditioningLayersLayer.RETURN_TYPES, ConditioningLayersLayer.FUNCTION),
                         ((LAYER_TYPE,), "create"))

    def test_stack_and_compose_contracts_have_no_numbered_sockets(self):
        add = ConditioningLayersAddLayer.INPUT_TYPES()
        self.assertEqual({key: tuple(value) for key, value in add.items()}, {"required": ("layer",), "optional": ("layers",)})
        self.assertEqual((add["required"]["layer"][0], add["optional"]["layers"][0]), (LAYER_TYPE, LAYER_STACK_TYPE))
        self.assertEqual(ConditioningLayersAddLayer.RETURN_TYPES, (LAYER_STACK_TYPE,))
        compose = ConditioningLayersCompose.INPUT_TYPES()
        self.assertEqual(tuple(compose["required"]), ("layers",))
        self.assertEqual(set(compose), {"required"})
        self.assertEqual((ConditioningLayersCompose.RETURN_TYPES, ConditioningLayersCompose.FUNCTION),
                         (("CONDITIONING",), "compose"))
        for node in (ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose):
            self.assertEqual(node.CATEGORY, ConditioningLayersNormalizedBlend.CATEGORY)
            self.assertTrue(node.DESCRIPTION)

    def test_field_and_metadata_contract_equal_both_retained_preparation_contracts(self):
        for contract in (blend_component.blend_node_contract(),
                         generalized_blend_component.generalized_blend_node_contract()):
            self.assertEqual(FIELD_SHAPE, contract["mask_shape"])
            self.assertEqual(set(UPSTREAM_METADATA) | set(nodes.LAYER_OWNED_METADATA),
                             set(contract["permitted_metadata"]))
            self.assertEqual((nodes.PREPARED_MASK_STRENGTH, nodes.PREPARED_SET_AREA_TO_BOUNDS),
                             (contract["mask_strength"], contract["set_area_to_bounds"]))
            self.assertEqual((contract["input_dtype"], contract["output_dtype"]), ("binary32", "binary32"))
        self.assertEqual(UPSTREAM_METADATA, ("pooled_output", "attention_mask"))


class StackRuntimeTests(unittest.TestCase):
    def test_add_chain_is_the_authored_order_and_carries_disabled_layers(self):
        a, b, c = disabled_layer("11"), disabled_layer("12"), disabled_layer("13")
        (stack,) = ConditioningLayersAddLayer().add(a)
        (stack,) = ConditioningLayersAddLayer().add(b, stack)
        (stack,) = ConditioningLayersAddLayer().add(c, layers=stack)
        self.assertEqual([item.layer_id for item in stack.layers], ["11", "12", "13"])
        self.assertEqual((stack.enabled_layers, a.mode, a.strength), ((), LayerMode.FIXED, 0.5))

    def test_add_rejects_repeated_layers_and_wrong_inputs(self):
        a = disabled_layer("21")
        (stack,) = ConditioningLayersAddLayer().add(a)
        with self.assertRaises(ValueError):
            ConditioningLayersAddLayer().add(a, stack)
        for bad in ((object(), None), (a, object()), (a, (a,))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ConditioningLayersAddLayer().add(*bad)

    def test_layer_requires_its_node_identity(self):
        with self.assertRaises(ValueError):
            ConditioningLayersLayer().create(object(), object(), 1.0, "BLENDED", False)

    def test_compose_rejects_non_stack_input_before_reading_tensors(self):
        compose = ConditioningLayersCompose()
        with patch("conditioning_layers.comfyui.prediction_mixing.layer_nodes.nodes._runtime_torch",
                   return_value=_FakeTorch), patch.dict("sys.modules", {"comfy": _FakeComfy}):
            for value in (None, (disabled_layer("31"),), [disabled_layer("32")]):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    compose.compose(value)
            (stack,) = ConditioningLayersAddLayer().add(disabled_layer("33"))
            with self.assertRaisesRegex(ValueError, "no enabled layer"):
                compose.compose(stack)

    def test_arbitrary_stack_length_has_no_maximum(self):
        stack = None
        for index in range(64):
            (stack,) = ConditioningLayersAddLayer().add(disabled_layer(str(index)), stack)
        self.assertEqual(len(stack.layers), 64)
        for path in PACKAGE.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("MAX_", source)
                self.assertNotIn("max_layers", source.lower())
                self.assertNotIn("max_count", source.lower())


class _FakeTorch:
    float32 = "float32"


class _FakeComfy:
    class model_management:
        @staticmethod
        def intermediate_dtype():
            return _FakeTorch.float32


class BoundaryTests(unittest.TestCase):
    ALLOWED_IMPORTS = {
        "__future__", "collections.abc", "dataclasses", "enum", "math",
        "conditioning_layers.adapters.prediction_mixing",
        "conditioning_layers.comfyui.prediction_mixing.blend_preparation",
        "conditioning_layers.comfyui.prediction_mixing.inventory",
        "conditioning_layers.comfyui.prediction_mixing.models",
        "conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical",
        "conditioning_layers.comfyui.prediction_mixing.validation",
    }

    def test_package_imports_only_the_retained_math_contracts_and_graph_helpers(self):
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                for node in tree.body:
                    if isinstance(node, ast.Import):
                        self.assertTrue({alias.name for alias in node.names} <= self.ALLOWED_IMPORTS)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        self.assertIn(node.module, self.ALLOWED_IMPORTS)
                local = {alias.name.split(".")[0] for function in ast.walk(tree)
                         if isinstance(function, ast.FunctionDef) for node in ast.walk(function)
                         if isinstance(node, (ast.Import, ast.ImportFrom))
                         for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])}
                self.assertLessEqual(local, {"torch", "comfy"} if path.name == "nodes.py" else set())

    def test_package_is_isolated_from_product_panel_admission_and_selectors(self):
        for path in sorted(PACKAGE.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for token in ("comfyui_panel", "capabilities.product", "PRODUCT_ADMITTED", "DEFAULT_SUPPORTED_PROFILE",
                              "REGISTERED_COMFYUI_PROFILES", "select_blend_realization", "select_realization_binding",
                              "eligibility", "localStorage", "PromptServer"):
                    self.assertNotIn(token, source)

    def test_fresh_imports_keep_runtime_product_and_node_system_apart(self):
        probe = """
import importlib, sys
import conditioning_layers.comfyui.prediction_mixing.layer_nodes
for name in ("torch", "numpy", "av", "comfy", "nodes", "server"):
    assert name not in sys.modules, name
loaded = sorted(name for name in sys.modules if "generalized_blend" in name or "_bounded_blend" in name
                or "comfyui_panel" in name or name.endswith("capabilities.product"))
assert loaded == [], loaded
"""
        product = """
import importlib, sys
for name in ("conditioning_layers.capabilities.product",
             "conditioning_layers.integrations.comfyui_panel.application",
             "conditioning_layers.integrations.comfyui_panel.routes", "conditioning_layers.integrations.blend_readiness"):
    importlib.import_module(name)
assert not [name for name in sys.modules if "layer_nodes" in name]
"""
        for source in (probe, product):
            result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                    capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RootRegistrationTests(unittest.TestCase):
    def load_root(self, blend_available=True, **layer_patch):
        namespace = {"__file__": str(ROOT / "__init__.py"), "__name__": "_node_system_offline_root"}
        from conditioning_layers.comfyui.prediction_mixing import layer_nodes
        blend = {"return_value": ({"ConditioningLayersNormalizedBlend": object}, None)} if blend_available else \
            {"side_effect": ImportError("offline Blend unavailable")}
        with patch.dict("os.environ", {}, clear=True), patch.object(routes, "register_routes") as register, \
                patch.object(blend_readiness, "register_readiness_route"), \
                patch.object(blend_component, "initialize_blend_node_registration", **blend), \
                patch.object(layer_nodes, "initialize_layer_node_registration",
                             **(layer_patch or {"wraps": initialize_layer_node_registration})):
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), namespace)
        register.assert_called_once_with()
        return namespace

    def test_layer_nodes_register_beside_blend_and_alone(self):
        for available, blend in ((True, ("ConditioningLayersNormalizedBlend",)), (False, ())):
            with self.subTest(blend_available=available):
                namespace = self.load_root(available)
                expected = blend + LAYER_NODE_CLASS_NAMES + FIELD_SOURCE_NODE_CLASS_NAMES + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
                self.assertEqual(tuple(namespace["NODE_CLASS_MAPPINGS"]), expected)
                self.assertEqual(tuple(namespace["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
                self.assertIs(namespace["NODE_CLASS_MAPPINGS"]["ConditioningLayersCompose"], ConditioningLayersCompose)
                self.assertIsNone(namespace["LAYER_NODE_REGISTRATION_ERROR"])
                self.assertEqual(namespace["BLEND_REGISTRATION_ERROR"] is None, available)

    def test_layer_node_failure_or_collision_leaves_blend_registration_intact(self):
        for layer_patch, message in (
                ({"side_effect": RuntimeError("offline layer failure")}, "RuntimeError: offline layer failure"),
                ({"return_value": ({"ConditioningLayersNormalizedBlend": object}, {})}, "RuntimeError: Layer node names collide")):
            with self.subTest(message=message):
                namespace = self.load_root(True, **layer_patch)
                self.assertEqual(tuple(namespace["NODE_CLASS_MAPPINGS"]), ("ConditioningLayersNormalizedBlend",)
                                 + FIELD_SOURCE_NODE_CLASS_NAMES + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
                self.assertIs(namespace["NODE_CLASS_MAPPINGS"]["ConditioningLayersNormalizedBlend"], object)
                self.assertTrue(namespace["LAYER_NODE_REGISTRATION_ERROR"].startswith(message))
                self.assertIsNone(namespace["BLEND_REGISTRATION_ERROR"])

    def test_registration_changes_no_product_admission_or_cardinality(self):
        from conditioning_layers.capabilities import blend, multi_layer
        from conditioning_layers.comfyui.prediction_mixing import DEFAULT_SUPPORTED_PROFILE
        before = (multi_layer.PRODUCT_ADMITTED_ENTRIES, multi_layer.product_supported_cardinalities(),
                  blend.BLEND_PRODUCT_ADMITTED, blend.REGISTERED_BLEND_ELIGIBILITY_ENTRIES, DEFAULT_SUPPORTED_PROFILE)
        self.load_root(True)
        after = (multi_layer.PRODUCT_ADMITTED_ENTRIES, multi_layer.product_supported_cardinalities(),
                 blend.BLEND_PRODUCT_ADMITTED, blend.REGISTERED_BLEND_ELIGIBILITY_ENTRIES, DEFAULT_SUPPORTED_PROFILE)
        self.assertEqual(after, before)
        self.assertEqual(after[1], (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
