"""Exact-3 node contract, identity, and offline tensor preparation checks."""

from dataclasses import replace
import math
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing import blend_component as authority
from conditioning_layers.comfyui.prediction_mixing.blend_node import ConditioningLayersNormalizedBlend
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import round_ratio_to_binary32


class BlendComponentTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        comfy = ModuleType('comfy')
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        self.context = patch.dict('sys.modules', {'comfy': comfy})
        self.context.start()
        self.addCleanup(self.context.stop)
        self.model_management = comfy.model_management

    def conditions(self, codes=(1, 10, 1), strengths=(1., 1., 1.)):
        return [[self.torch.ones((1, 2, 3)), {
            'mask': self.torch.full((1, 128, 128), round_ratio_to_binary32(code, 255), dtype=self.torch.float32),
            'mask_strength': strength, 'set_area_to_bounds': False,
            'pooled_output': self.torch.ones((1, 3)),
        }] for code, strength in zip(codes, strengths)]

    def test_same_order_tensor_and_metadata_preservation_and_determinism(self):
        source = self.conditions()
        first, = ConditioningLayersNormalizedBlend().prepare(source)
        second, = ConditioningLayersNormalizedBlend().prepare(source)
        for ordinal, entry in enumerate(source):
            self.assertIs(first[ordinal][0], entry[0])
            self.assertIsNot(first[ordinal][1], entry[1])
            self.assertIs(first[ordinal][1]['pooled_output'], entry[1]['pooled_output'])
            self.assertIsNot(first[ordinal][1]['mask'], entry[1]['mask'])
            self.assertEqual(first[ordinal][1]['mask_strength'], 1.)
            self.assertIs(first[ordinal][1]['set_area_to_bounds'], False)
            self.assertEqual(first[ordinal][1]['mask'].dtype, self.torch.float32)
            self.assertEqual(first[ordinal][1]['mask'].device.type, 'cpu')
            self.assertEqual(tuple(first[ordinal][1]['mask'].shape), (1, 128, 128))
            self.assertTrue(self.torch.equal(first[ordinal][1]['mask'].view(self.torch.int32), second[ordinal][1]['mask'].view(self.torch.int32)))
        self.assertEqual(source[1][1]['mask'][0, 0, 0].item(), round_ratio_to_binary32(10, 255))

    def test_zero_and_tiny_strength_preserve_all_entries(self):
        output, = ConditioningLayersNormalizedBlend().prepare(self.conditions((1, 255, 0), (math.ulp(0.), 0., 1.)))
        self.assertEqual([entry[1]['mask'][0, 0, 0].item() for entry in output], [1., 0., 0.])
        output, = ConditioningLayersNormalizedBlend().prepare(self.conditions(strengths=(0., 0., 0.)))
        self.assertEqual(len(output), 3)
        self.assertTrue(all(self.torch.count_nonzero(entry[1]['mask']) == 0 for entry in output))

    def test_final_subnormal_bits_are_installed_without_float_conversion(self):
        output, = ConditioningLayersNormalizedBlend().prepare(self.conditions((1, 1, 0), (2.**-149, 1., 0.)))
        self.assertEqual(output[0][1]['mask'].view(self.torch.int32)[0, 0, 0].item(), 1)

    def test_rejects_unsupported_metadata_shapes_and_dtypes(self):
        for key, value in (('area', (128,128,0,0)), ('strength', 1.), ('hooks', None), ('start_percent', 0.), ('set_area_to_bounds', True)):
            source = self.conditions()
            source[0][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                ConditioningLayersNormalizedBlend().prepare(source)
        for mask in (self.torch.ones((1,64,128)), self.torch.ones((2,128,128)), self.torch.ones((1,128,128), dtype=self.torch.float16)):
            source = self.conditions()
            source[0][1]['mask'] = mask
            with self.assertRaises(ValueError):
                ConditioningLayersNormalizedBlend().prepare(source)
        for count in (0, 1, 2, 4):
            with self.assertRaises(ValueError):
                ConditioningLayersNormalizedBlend().prepare((self.conditions()*2)[:count])

    def test_invalid_samples_and_strengths_fail_closed(self):
        for invalid in (math.nan, math.inf, .5):
            source = self.conditions()
            source[0][1]['mask'][0,0,0] = invalid
            with self.assertRaises(ValueError):
                ConditioningLayersNormalizedBlend().prepare(source)
        for invalid in (math.nan, math.inf, -1., 2., True):
            with self.assertRaises(ValueError):
                ConditioningLayersNormalizedBlend().prepare(self.conditions(strengths=(invalid, 1., 1.)))

    def test_fp16_intermediate_setting_fails_closed(self):
        with patch('sys.argv', ['offline-test', '--fp16-intermediates']):
            with self.assertRaises(RuntimeError):
                ConditioningLayersNormalizedBlend().prepare(self.conditions())
        self.model_management.intermediate_dtype = lambda: self.torch.float16
        with self.assertRaises(ValueError):
            ConditioningLayersNormalizedBlend().prepare(self.conditions())

    def test_identity_source_anchor_and_cache_key_are_distinct_from_presence(self):
        identity = authority.blend_component_identity()
        self.assertTrue(authority.validate_blend_component_identity(identity))
        self.assertFalse(authority.validate_blend_component_identity(replace(identity, source_sha256='0'*64)))
        self.assertTrue(authority.verify_blend_component_source())
        self.assertEqual(ConditioningLayersNormalizedBlend.IS_CHANGED(self.conditions()), identity.implementation_fingerprint)
        with patch.object(authority, '_observed_sources', return_value={}):
            self.assertFalse(authority.verify_blend_component_source())
            self.assertEqual(authority.blend_component_identity(), identity)
            with self.assertRaises(RuntimeError):
                ConditioningLayersNormalizedBlend.IS_CHANGED(self.conditions())


if __name__ == '__main__':
    unittest.main()
