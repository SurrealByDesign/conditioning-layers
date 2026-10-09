"""Real CPU MASK encoding and unchanged native consumers, fenced host lane."""

import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.procedural_field_sources import ConditioningLayersNoiseField, noise_field_codes
from conditioning_layers.comfyui.influence_field_sources import ConditioningLayersInvertField
from conditioning_layers.comfyui.field_blur import ConditioningLayersFieldBlur
from conditioning_layers.comfyui.field_fade import ConditioningLayersFieldFade
from conditioning_layers.comfyui.field_remap import ConditioningLayersFieldRemap
from conditioning_layers.comfyui.field_repeat import ConditioningLayersFieldRepeat
from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code, round_ratio_to_binary32_bits,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose,
)
from test_noise_field_codes import DEFAULTS, GOLDENS


class NoiseFieldSourceTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersNoiseField()
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        host = patch.dict("sys.modules", {"comfy": comfy})
        host.start()
        self.addCleanup(host.stop)

    def mask(self):
        return self.node.generate(**DEFAULTS)[0]

    def codes(self, mask):
        return tuple(recover_sample_code(v) for v in mask.reshape(-1).tolist())

    def compose(self, masks, mode):
        stack = None
        for index, mask in enumerate(masks):
            layer = ConditioningLayersLayer().create(
                [[self.torch.ones((1, 2, 3)), {}]], mask, 1, mode, True, unique_id=str(index))[0]
            stack = ConditioningLayersAddLayer().add(layer, stack)[0]
        return ConditioningLayersCompose().compose(stack)[0]

    def assert_layer_support(self, mask):
        self.assertTrue(bool(mask.any()))
        self.codes(mask)  # Every operation still yields accepted codes.
        for mode in ("FIXED", "BLENDED"):
            self.assertTrue(self.torch.equal(self.compose((mask,), mode)[0][1]["mask"], (mask > 0).float()))

    def test_mask_contract_canonical_bits_and_fresh_storage(self):
        first, second = self.mask(), self.mask()
        for mask in (first, second):
            self.assertEqual(mask.device.type, "cpu")
            self.assertEqual(mask.dtype, self.torch.float32)
            self.assertEqual(tuple(mask.shape), (1, 128, 128))
            self.assertFalse(mask.requires_grad)
            bits = [round_ratio_to_binary32_bits(c, 255) for c in noise_field_codes(**DEFAULTS)]
            expected = self.torch.tensor(bits, dtype=self.torch.int32).reshape(1, 128, 128)
            self.assertTrue(self.torch.equal(mask.view(self.torch.int32), expected))
        self.assertNotEqual(first.data_ptr(), second.data_ptr())
        saved = second.clone()
        first.fill_(0)
        self.assertTrue(self.torch.equal(second, saved))

    def test_host_recovered_code_goldens_match_developer(self):
        for args, expected in GOLDENS:
            codes = self.codes(self.node.generate(*args)[0])
            self.assertEqual(codes, noise_field_codes(*args))
            self.assertEqual(hashlib.sha256(bytes(codes)).hexdigest(), expected)

    def test_host_rng_and_default_dtype_do_not_change_output(self):
        import numpy
        torch_state = self.torch.random.get_rng_state()
        numpy_state = numpy.random.get_state()
        dtype = self.torch.get_default_dtype()
        expected = self.mask()
        try:
            self.torch.set_default_dtype(self.torch.float64)
            for seed in (0, 1, 4294967295):
                # CPU generator only; no CUDA initialization or GPU work.
                self.torch.random.default_generator.manual_seed(seed)
                numpy.random.seed(seed)
                torch_before = self.torch.random.get_rng_state()
                numpy_before = numpy.random.get_state()
                self.assertTrue(self.torch.equal(self.mask(), expected))
                self.assertTrue(self.torch.equal(self.torch.random.get_rng_state(), torch_before))
                after = numpy.random.get_state()
                self.assertTrue(numpy.array_equal(numpy_before[1], after[1]))
                self.assertEqual(numpy_before[2:], after[2:])
        finally:
            self.torch.random.set_rng_state(torch_state)
            numpy.random.set_state(numpy_state)
            self.torch.set_default_dtype(dtype)

    def test_noise_then_layer(self):
        self.assert_layer_support(self.mask())

    def test_remap_then_layer(self):
        self.assert_layer_support(ConditioningLayersFieldRemap().remap(self.mask(), 40, 200, 0, 255)[0])

    def test_blur_then_layer(self):
        self.assert_layer_support(ConditioningLayersFieldBlur().blur(self.mask(), 3)[0])

    def test_fade_then_layer(self):
        self.assert_layer_support(ConditioningLayersFieldFade().apply(self.mask(), end_value=40)[0])

    def test_transform_then_layer(self):
        self.assert_layer_support(ConditioningLayersFieldTransform().transform(
            self.mask(), rotation_degrees=31, offset_x=3)[0])

    def test_repeat_then_layer(self):
        self.assert_layer_support(ConditioningLayersFieldRepeat().repeat(self.mask(), 3, 2, 7, 9)[0])

    def test_threshold_then_layer_and_invert_fixed_partition(self):
        original = self.mask()
        codes = self.codes(original)
        for threshold in (96, 128, 160):
            mask = ConditioningLayersFieldRemap().remap(original, threshold-1, threshold, 0, 255)[0]
            inverse = ConditioningLayersInvertField().invert(mask)[0]
            a, b = self.codes(mask), self.codes(inverse)
            self.assertEqual(set(a), {0, 255})
            self.assertEqual(a, tuple(255 if c >= threshold else 0 for c in codes))
            self.assertEqual(b, tuple(255-c for c in a))
            self.assert_layer_support(mask)
            self.assertTrue(self.torch.equal(mask + inverse, self.torch.ones_like(mask)))
            result = self.compose((mask, inverse), "FIXED")
            self.assertTrue(self.torch.equal(result[0][1]["mask"], mask))
            self.assertTrue(self.torch.equal(result[1][1]["mask"], inverse))
        self.assertEqual(self.codes(original), codes)

    def test_two_soft_fields_preserve_blended_normalization_and_fixed_rejection(self):
        a = self.mask()
        b = self.node.generate(**{**DEFAULTS, "seed": 1})[0]
        planes = (self.codes(a), self.codes(b))
        totals = tuple(map(sum, zip(*planes)))
        for codes, entry in zip(planes, self.compose((a, b), "BLENDED")):
            bits = [round_ratio_to_binary32_bits(c, total) if total else 0 for c, total in zip(codes, totals)]
            expected = self.torch.tensor(bits, dtype=self.torch.int32).reshape(1, 128, 128)
            self.assertTrue(self.torch.equal(entry[1]["mask"].view(self.torch.int32), expected))
        with self.assertRaisesRegex(ValueError, "overlap|FIXED"):
            self.compose((a, b), "FIXED")

    def test_offsets_match_exact_host_roll(self):
        base = self.mask()
        for dx, dy in ((1, 0), (0, 1), (-7, 17), (128, -128)):
            actual = self.node.generate(**{**DEFAULTS, "offset_x": dx, "offset_y": dy})[0]
            self.assertTrue(self.torch.equal(actual, self.torch.roll(base, shifts=(dy, dx), dims=(1, 2))))
