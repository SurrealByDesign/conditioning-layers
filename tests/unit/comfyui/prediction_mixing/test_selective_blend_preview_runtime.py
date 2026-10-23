"""E10 preview bits equal native Compose mask bits; real pinned Torch on CPU, no model."""
from dataclasses import replace

import test_layer_node_runtime as runtime
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersCompose, ConditioningLayersComposeGroups, ConditioningLayersLayer, LayerStack,
)
from conditioning_layers.integrations.composition_preview import (
    GROUPED_COMPOSE, LEGACY_COMPOSE, preview_composition,
)


class PreviewRuntimeTests(runtime.RuntimeTestCase):
    def stack(self, groups, strengths, modes=None, enabled=None):
        count = len(groups)
        modes, enabled = modes or ("BLENDED",) * count, enabled or (True,) * count
        planes = [tuple((p * (i + 1) + i + 1) % 256 for p in range(16384)) for i in range(count)]
        for i, mode in enumerate(modes):
            if mode == "FIXED":  # One owner on its own cells; BLENDED members keep local gaps there.
                planes = [tuple(255 if p % 97 == 0 else 0 for p in range(16384)) if j == i
                          else tuple(0 if p % 97 == 0 else c for p, c in enumerate(plane))
                          for j, plane in enumerate(planes)]
        layers = tuple(ConditioningLayersLayer().create(self.conditioning(i), self.mask(plane), strength, mode, on,
                                                        unique_id=f"n{i}", blend_group=group)[0]
                       for i, (plane, group, strength, mode, on)
                       in enumerate(zip(planes, groups, strengths, modes, enabled)))
        payload = [{"id": layer.layer_id, "strength": layer.strength, "mode": layer.mode.value,
                    "enabled": layer.enabled, "group": layer.blend_group, "codes": list(plane)}
                   for layer, plane in zip(layers, planes)]
        return layers, payload

    def assertPreviewMatchesNative(self, node, compose, layers, payload):
        native = iter(self.bits(node.compose(LayerStack(layers))[0]))
        for layer in payload:
            result = preview_composition({"compose": compose, "layers": payload, "selected": layer["id"]})
            expected = list(next(native)) if layer["enabled"] else [0] * 16384
            # Compare first: difflib over 16,384 samples is prohibitively slow.
            if result["bits"] != expected:
                first = next(i for i, (a, b) in enumerate(zip(result["bits"], expected)) if a != b)
                self.fail(f"Layer {layer['id']}: preview differs from native mask bits first at sample {first}")

    def test_grouped_preview_equals_native_compose_blend_groups_output(self):
        cases = (
            (("a", "a", "b"), (1.0, 0.5, 5e-324), None, None),
            (("", "", "", "D", "D"), (1.0,) * 5, None, None),
            (("x", "y", "x", "z", "y", "x"), (0.25, 1.0, 2**-149, 0.0, 0.75, 1e-37), None, None),
            (("A", "", "B", "B", "A"), (1.0, 0.3, 0.6, 0.9, 0.1), ("FIXED",) + ("BLENDED",) * 4,
             (True, True, True, False, True)),
            (("one",) * 4, (1.0, 0.5, 0.25, 0.125), None, None),
        )
        for groups, strengths, modes, enabled in cases:
            with self.subTest(groups=groups):
                layers, payload = self.stack(groups, strengths, modes, enabled)
                self.assertPreviewMatchesNative(ConditioningLayersComposeGroups(), GROUPED_COMPOSE, layers, payload)

    def test_legacy_preview_equals_native_compose_output(self):
        layers, payload = self.stack(("",) * 4, (1.0, 0.5, 5e-324, 0.0), ("BLENDED", "FIXED", "BLENDED", "BLENDED"))
        self.assertPreviewMatchesNative(ConditioningLayersCompose(), LEGACY_COMPOSE, layers, payload)

    def test_explicit_assignment_fails_in_native_legacy_and_its_preview(self):
        layers, payload = self.stack(("", "A"), (1.0, 1.0))
        for change in ({}, {"enabled": False}):
            stack = LayerStack((layers[0], replace(layers[1], **change)))
            entries = [payload[0], {**payload[1], **change}]
            with self.assertRaisesRegex(ValueError, "require Compose Blend Groups"):
                ConditioningLayersCompose().compose(stack)
            with self.assertRaisesRegex(ValueError, 'group "A" needs Compose Blend Groups'):
                preview_composition({"compose": LEGACY_COMPOSE, "layers": entries, "selected": "n0"})
