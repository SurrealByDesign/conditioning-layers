"""Node System Phase 1 layer nodes with the real pinned Torch runtime; host lane.

The retained exact-3 and N-generic preparation nodes are the references: on the
same fields, prompts and Strength, Compose must return their CONDITIONING bit
for bit. The retained graph path is emulated with the host's own semantics for
ConditioningSetMask (node_helpers.conditioning_set_values) and the ordered
ConditioningCombine left fold (list concatenation). `comfy.model_management` is
an in-memory stub, as in the retained component tests; no ComfyUI checkout,
model, host, network or submission is used.
"""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.assets.models import DEFAULT_INSPECTION_LIMITS
from conditioning_layers.assets.png_inspector import inspect_png_bytes
from conditioning_layers.comfyui.prediction_mixing.blend_node import ConditioningLayersNormalizedBlend
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import round_ratio_to_binary32
from conditioning_layers.comfyui.prediction_mixing.generalized_blend_node import (
    ConditioningLayersGeneralizedNormalizedBlend,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersAddLayer, ConditioningLayersCompose, ConditioningLayersLayer, compose_field_codes, LayerMode,
)


ROOT = Path(__file__).resolve().parents[4]
FIELDS = ROOT / "node-workflows/phase1/fields"
RGB = [round_ratio_to_binary32(code, 255) for code in range(256)]
GRAY = [round_ratio_to_binary32(code * 256, 65535) for code in range(256)]
VASE3 = tuple(f"cl-phase1-vase3-{letter}.png" for letter in "abc")
VASE9 = tuple(f"cl-phase1-vase9-cell-{index}.png" for index in range(1, 10))


def codes_of(path):
    return inspect_png_bytes(path, layer_id="field", relative_reference=path.name,
                             limits=DEFAULT_INSPECTION_LIMITS).values


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        import torch

        self.torch = torch
        self.intermediate = torch.float32
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.intermediate)
        context = patch.dict("sys.modules", {"comfy": comfy})
        context.start()
        self.addCleanup(context.stop)

    def mask(self, codes, codebook=RGB):
        return self.torch.tensor([codebook[code] for code in codes], dtype=self.torch.float32).reshape(1, 128, 128)

    def conditioning(self, ordinal, **extra):
        prompt = self.torch.arange(24, dtype=self.torch.float32).reshape(1, 3, 8) + ordinal
        return [[prompt, {"pooled_output": self.torch.full((1, 4), float(ordinal)), **extra}]]

    def retained_input(self, conditionings, masks, strengths):
        """ConditioningSetMask(default area) per layer, then the ordered ConditioningCombine fold."""
        combined = []
        for conditioning, mask, strength in zip(conditionings, masks, strengths, strict=True):
            for prompt, metadata in conditioning:
                entry = [prompt, metadata.copy()]
                for key, value in {"mask": mask, "set_area_to_bounds": False, "mask_strength": strength}.items():
                    entry[1][key] = value
                combined = combined + [entry]
        return combined

    def layer(self, conditioning, mask, strength=1.0, mode="BLENDED", enabled=True, unique_id="1"):
        return ConditioningLayersLayer().create(conditioning, mask, strength, mode, enabled, unique_id=unique_id)[0]

    def stack(self, layers):
        stack = None
        for layer in layers:
            (stack,) = ConditioningLayersAddLayer().add(layer, stack)
        return stack

    def compose(self, conditionings, masks, strengths, modes=None, enabled=None):
        count = len(conditionings)
        modes, enabled = modes or ("BLENDED",) * count, enabled or (True,) * count
        return ConditioningLayersCompose().compose(self.stack(
            self.layer(c, m, s, mode, on, str(100 + index))
            for index, (c, m, s, mode, on) in enumerate(zip(conditionings, masks, strengths, modes, enabled))))[0]

    def bits(self, conditioning):
        return tuple(tuple(entry[1]["mask"].view(self.torch.int32).reshape(-1).tolist()) for entry in conditioning)

    def assertSameConditioning(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for (prompt, metadata), (reference_prompt, reference) in zip(actual, expected):
            self.assertIs(prompt, reference_prompt)
            self.assertEqual(list(metadata), list(reference))
            self.assertIs(metadata["pooled_output"], reference["pooled_output"])
            self.assertEqual((metadata["mask_strength"], metadata["set_area_to_bounds"]), (1.0, False))
            self.assertEqual((reference["mask_strength"], reference["set_area_to_bounds"]), (1.0, False))
            mask = metadata["mask"]
            self.assertEqual((mask.dtype, tuple(mask.shape), mask.device.type), (self.torch.float32, (1, 128, 128), "cpu"))
            self.assertTrue(self.torch.equal(mask.view(self.torch.int32), reference["mask"].view(self.torch.int32)))


class RetainedEquivalenceTests(RuntimeTestCase):
    def test_exact_three_vase_equals_both_retained_preparation_nodes(self):
        codes = [codes_of(FIELDS / name) for name in VASE3]
        for codebook in (RGB, GRAY):
            for strengths in ((1.0, 1.0, 1.0), (1.0, 0.1, 5e-324)):
                with self.subTest(gray=codebook is GRAY, strengths=strengths):
                    conditionings = [self.conditioning(index) for index in range(3)]
                    masks = [self.mask(plane, codebook) for plane in codes]
                    retained = self.retained_input(conditionings, masks, strengths)
                    node = self.compose(conditionings, masks, strengths)
                    self.assertSameConditioning(node, ConditioningLayersNormalizedBlend().prepare(retained)[0])
                    self.assertSameConditioning(
                        node, ConditioningLayersGeneralizedNormalizedBlend().prepare(retained, 3)[0])

    def test_nine_region_vase_equals_the_retained_n_generic_node(self):
        codes = [codes_of(FIELDS / name) for name in VASE9]
        for strengths in ((1.0,) * 9, (0.35, 1.0, 0.0, 0.5, 1.0, 2**-30, 1.0, 0.75, 0.1)):
            with self.subTest(strengths=strengths):
                conditionings = [self.conditioning(index) for index in range(9)]
                masks = [self.mask(plane) for plane in codes]
                retained = self.retained_input(conditionings, masks, strengths)
                self.assertSameConditioning(self.compose(conditionings, masks, strengths),
                                            ConditioningLayersGeneralizedNormalizedBlend().prepare(retained, 9)[0])

    def test_counts_outside_three_to_nine_equal_the_retained_n_generic_node(self):
        for count in (1, 2, 12):
            with self.subTest(count=count):
                codes = [tuple(((index + 1) * (pixel % 23) + 7 * index) % 256 for pixel in range(16384))
                         for index in range(count)]
                strengths = tuple((1.0, 0.5, 0.1)[index % 3] for index in range(count))
                conditionings = [self.conditioning(index) for index in range(count)]
                masks = [self.mask(plane) for plane in codes]
                retained = self.retained_input(conditionings, masks, strengths)
                self.assertSameConditioning(self.compose(conditionings, masks, strengths),
                                            ConditioningLayersGeneralizedNormalizedBlend().prepare(retained, count)[0])

    def test_repeated_prompts_and_fields_stay_distinct_layers(self):
        conditioning, mask = self.conditioning(0), self.mask(codes_of(FIELDS / VASE3[0]))
        retained = self.retained_input([conditioning, conditioning], [mask, mask], (1.0, 1.0))
        node = self.compose([conditioning, conditioning], [mask, mask], (1.0, 1.0))
        self.assertEqual(len(node), 2)
        self.assertSameConditioning(node, ConditioningLayersGeneralizedNormalizedBlend().prepare(retained, 2)[0])


class ModeRuntimeTests(RuntimeTestCase):
    def test_mixed_modes_equal_the_pure_composition(self):
        codes = [codes_of(FIELDS / name) for name in VASE9]
        modes = tuple("FIXED" if index in (0, 2, 6, 8) else "BLENDED" for index in range(9))
        strengths = (1.0, 0.5, 1.0, 0.25, 1.0, 1.0, 0.0, 1.0, 1.0)
        node = self.compose([self.conditioning(index) for index in range(9)],
                            [self.mask(plane) for plane in codes], strengths, modes)
        expected = compose_field_codes(codes, strengths, tuple(LayerMode(mode) for mode in modes))
        self.assertTrue(self.bits(node) == expected, "prepared bits differ from the pure composition")

    def test_disjoint_fixed_layers_equal_blended_and_retained_preparation(self):
        root = ROOT / "influence-field-library/v1/three-layer/vertical-thirds"
        codes = [codes_of(root / f"field-{letter}.png") for letter in "abc"]
        conditionings = [self.conditioning(index) for index in range(3)]
        masks = [self.mask(plane) for plane in codes]
        fixed = self.compose(conditionings, masks, (1.0, 1.0, 1.0), ("FIXED",) * 3)
        self.assertSameConditioning(fixed, self.compose(conditionings, masks, (1.0, 1.0, 1.0)))
        self.assertSameConditioning(fixed, ConditioningLayersNormalizedBlend().prepare(
            self.retained_input(conditionings, masks, (1.0, 1.0, 1.0)))[0])

    def test_overlapping_fixed_layers_fail_at_compose_with_their_node_ids(self):
        codes = [codes_of(FIELDS / name) for name in VASE3]
        with self.assertRaisesRegex(ValueError, "layers 100 and 101 share"):
            self.compose([self.conditioning(index) for index in range(3)], [self.mask(plane) for plane in codes],
                         (1.0, 0.0, 1.0), ("FIXED", "FIXED", "BLENDED"))

    def test_disabled_layers_are_excluded_even_with_unusable_inputs(self):
        codes = [codes_of(FIELDS / name) for name in VASE3]
        conditionings = [self.conditioning(index) for index in range(3)]
        masks = [self.mask(plane) for plane in codes]
        layers = [self.layer(conditionings[0], masks[0], unique_id="1"),
                  self.layer(object(), object(), 0.5, "FIXED", False, unique_id="2"),
                  self.layer(conditionings[2], masks[2], unique_id="3")]
        composed = ConditioningLayersCompose().compose(self.stack(layers))[0]
        self.assertSameConditioning(composed, self.compose([conditionings[0], conditionings[2]], [masks[0], masks[2]], (1.0, 1.0)))
        with self.assertRaisesRegex(ValueError, "no enabled layer"):
            ConditioningLayersCompose().compose(self.stack([layers[1]]))


class ValidationTests(RuntimeTestCase):
    def setUp(self):
        super().setUp()
        self.good_mask = self.mask(codes_of(FIELDS / VASE3[0]))

    def test_layer_rejects_non_plain_conditioning_at_its_own_node(self):
        torch = self.torch
        prompt = torch.zeros((1, 3, 8))
        bad = (
            [], self.conditioning(0) + self.conditioning(1), [[prompt]], [[prompt, []]],
            [[torch.zeros((2, 3, 8)), {}]], [[torch.zeros((3, 8)), {}]],
            [[torch.full((1, 3, 8), float("nan")), {}]],
        )
        for conditioning in bad:
            with self.subTest(conditioning=conditioning), self.assertRaisesRegex(ValueError, "Layer node 42"):
                self.layer(conditioning, self.good_mask, unique_id="42")
        for key in ("mask", "mask_strength", "set_area_to_bounds", "hooks", "start_percent", "end_percent",
                    "area", "strength", "control", "gligen", "clip_start_percent"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "unsupported conditioning metadata"):
                self.layer(self.conditioning(0, **{key: 0.0}), self.good_mask)
        self.layer(self.conditioning(0, attention_mask=torch.ones((1, 3))), self.good_mask)

    def test_layer_rejects_fields_outside_the_retained_field_contract(self):
        torch = self.torch
        codes = codes_of(FIELDS / VASE3[0])
        not_codebook = self.good_mask.clone()
        not_codebook[0, 0, 0] = 0.3
        for mask in (self.good_mask.to(torch.float16), self.mask(codes)[:, :64, :64].contiguous(),
                     torch.cat([self.good_mask, self.good_mask]), not_codebook, object()):
            with self.subTest(shape=getattr(mask, "shape", None)), self.assertRaises(ValueError):
                self.layer(self.conditioning(0), mask)
        conditioning = self.conditioning(0)
        two_d = self.compose([conditioning], [self.good_mask.reshape(128, 128)], (1.0,))
        self.assertSameConditioning(two_d, self.compose([conditioning], [self.good_mask], (1.0,)))

    def test_compose_fails_closed_on_empty_fields_dtype_and_tampered_descriptors(self):
        empty = self.mask((0,) * 16384)
        with self.assertRaisesRegex(ValueError, "no positive sample"):
            self.compose([self.conditioning(0), self.conditioning(1)], [empty, self.good_mask], (1.0, 1.0))
        layer = self.layer(self.conditioning(0), self.good_mask)
        self.intermediate = self.torch.float16
        with self.assertRaisesRegex(ValueError, "binary32"):
            ConditioningLayersCompose().compose(self.stack([layer]))
        self.intermediate = self.torch.float32
        for field, value in (("mask", self.good_mask.to(self.torch.float16)), ("strength", 2.0),
                             ("conditioning", self.conditioning(0, hooks=None))):
            tampered = self.layer(self.conditioning(0), self.good_mask)
            object.__setattr__(tampered, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                ConditioningLayersCompose().compose(self.stack([tampered]))


class InteroperabilityTests(RuntimeTestCase):
    def test_any_branch_conditioning_passes_through_untouched(self):
        # Per-branch prompt tensors, e.g. from different LoRA-patched CLIP chains, are opaque inputs.
        torch = self.torch
        branches = [[[torch.randn((1, 5 + index, 8), generator=torch.Generator().manual_seed(index)),
                      {"pooled_output": None, "attention_mask": torch.ones((1, 5 + index))}]] for index in range(3)]
        originals = [dict(branch[0][1]) for branch in branches]
        masks = [self.mask(codes_of(FIELDS / name)) for name in VASE3]
        composed = self.compose(branches, masks, (1.0, 1.0, 1.0))
        for branch, original, (prompt, metadata) in zip(branches, originals, composed):
            self.assertIs(prompt, branch[0][0])
            self.assertEqual(branch[0][1].keys(), original.keys())
            self.assertIs(metadata["attention_mask"], original["attention_mask"])
        retained = self.retained_input(branches, masks, (1.0, 1.0, 1.0))
        self.assertTrue(self.bits(composed) == self.bits(ConditioningLayersNormalizedBlend().prepare(retained)[0]),
                        "prepared bits differ from the retained exact-3 node")

    def test_hook_scheduled_model_lora_conditioning_is_rejected_not_imitated(self):
        with self.assertRaisesRegex(ValueError, "hooks"):
            self.layer(self.conditioning(0, hooks=object()), self.mask(codes_of(FIELDS / VASE3[0])))


if __name__ == "__main__":
    unittest.main()
