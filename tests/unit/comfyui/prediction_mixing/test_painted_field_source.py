"""Real CPU MASK bit identities and retained consumers; offline host lane."""
import base64
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.assets.field_png import encode_field_png, PREFIX
from conditioning_layers.comfyui.painted_field_source import ConditioningLayersPaintedField
from conditioning_layers.comfyui.influence_field_sources import ConditioningLayersInvertField
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code, round_ratio_to_binary32_bits
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose)


class PaintedRuntime(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersPaintedField()

    def field(self, codes):
        return self.node.load(PREFIX + base64.b64encode(encode_field_png(codes)).decode())[0]

    def check(self, mask, codes):
        self.assertEqual((tuple(mask.shape), mask.dtype, mask.device.type, mask.requires_grad),
                         ((1, 128, 128), self.torch.float32, "cpu", False))
        self.assertEqual(mask.view(self.torch.int32).reshape(-1).tolist(),
                         [round_ratio_to_binary32_bits(c, 255) for c in codes])
        self.assertEqual(bytes(recover_sample_code(v) for v in mask.reshape(-1).tolist()), codes)

    def test_empty_and_noncanonical_png_zero_have_exact_positive_zero_bits(self):
        self.check(self.node.load("")[0], bytes(16384))
        self.check(self.field(bytes(16384)), bytes(16384))

    def test_all_codes_and_deterministic_pseudorandom_fields_have_fresh_exact_storage(self):
        codes = bytes((i * 73 + i // 128 * 19) % 256 for i in range(16384))
        first, second = self.field(codes), self.field(codes)
        self.check(first, codes); self.check(second, codes)
        self.assertNotEqual(first.data_ptr(), second.data_ptr())
        first.zero_(); self.check(second, codes)

    def test_invert_twice_is_bit_identity(self):
        codes = bytes(range(256)) * 64
        original = self.field(codes)
        inverted = ConditioningLayersInvertField().invert(original)[0]
        restored = ConditioningLayersInvertField().invert(inverted)[0]
        self.check(restored, codes)

    def test_layer_accepts_positive_output_in_both_modes_and_compose_rejects_zero(self):
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}):
            for mode in ("FIXED", "BLENDED"):
                conditioning = [[self.torch.ones((1, 2, 3)), {}]]
                positive = self.field(bytes(range(256)) * 64)
                layer = ConditioningLayersLayer().create(conditioning, positive, 1.0, mode, True, unique_id="painted")[0]
                self.assertTrue(ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0]))
                zero = ConditioningLayersLayer().create(conditioning, self.node.load("")[0], 1.0, mode, True, unique_id="painted")[0]
                with self.assertRaises(ValueError):
                    ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(zero)[0])
