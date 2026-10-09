"""Real native MASK modulation and Layer/Compose integration; offline host lane."""

import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.field_fade import ConditioningLayersFieldFade
from conditioning_layers.comfyui import influence_field_sources as fields, pattern_field_source as patterns
from conditioning_layers.comfyui.procedural_field_sources import ConditioningLayersScatterField, ConditioningLayersCyclicPartitionField
from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui.field_repeat import ConditioningLayersFieldRepeat
from conditioning_layers.comfyui.field_remap import ConditioningLayersFieldRemap
from conditioning_layers.comfyui.field_blur import ConditioningLayersFieldBlur
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code, round_ratio_to_binary32
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose
from test_field_fade_codes import GOLDENS, reference


PATTERN_GOLDEN = '64ddcad3b2efd41f70fd9c8b0200904c0be72be6fbeb4e70a2cce890421c8de6'


class FadeTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersFieldFade()
        self.source = tuple((x + 3*y) % 256 for y in range(128) for x in range(128))
        self.mask = fields.codes_to_mask(self.source)
        self.white = fields.codes_to_mask([255] * 16384)

    def apply(self, mask=None, **p):
        return self.node.apply(self.mask if mask is None else mask, **p)[0]

    def codes(self, mask):
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, 'cpu')
        self.assertEqual(tuple(mask.shape), (1, 128, 128))
        self.assertFalse(mask.requires_grad)
        codes = tuple(recover_sample_code(v) for v in mask.reshape(-1).tolist())
        self.assertTrue(self.torch.equal(mask.view(self.torch.int32), fields.codes_to_mask(codes).view(self.torch.int32)))
        return codes

    def test_identity_all_modes_all_codes_canonical_bits_fresh_storage(self):
        for mode in ('linear', 'circular', 'square'):
            original = self.mask.clone()
            out = self.apply(fade_mode=mode, start_value=255, end_value=255)
            self.assertEqual(self.codes(out), self.source)
            self.assertTrue(self.torch.equal(out.view(self.torch.int32), self.mask.view(self.torch.int32)))
            self.assertNotEqual(out.data_ptr(), self.mask.data_ptr())
            out.zero_()
            self.assertTrue(self.torch.equal(self.mask, original))

    def test_zero_modulation_and_zero_input_all_modes(self):
        for mode in ('linear', 'circular', 'square'):
            self.assertEqual(set(self.codes(self.apply(fade_mode=mode, start_value=0, end_value=0))), {0})
            self.assertEqual(set(self.codes(self.apply(self.white * 0, fade_mode=mode, start_value=40, end_value=180))), {0})

    def test_alternate_codebook_is_recovered_then_canonicalized(self):
        alternate = self.torch.tensor([round_ratio_to_binary32(c*256, 65535) for c in self.source],
                                     dtype=self.torch.float32).reshape(1, 128, 128)
        for mode in ('linear', 'circular', 'square'):
            self.assertEqual(self.codes(self.apply(alternate, fade_mode=mode, start_value=255, end_value=255)), self.source)
            self.assertTrue(self.torch.equal(self.apply(alternate, fade_mode=mode), self.apply(fade_mode=mode)))

    def test_2d_noncontiguous_requires_grad_inputs_and_source_preservation(self):
        self.assertTrue(self.torch.equal(self.apply(self.mask[0]), self.apply()))
        for mode in ('linear', 'circular', 'square'):
            transposed = self.mask.transpose(1, 2).requires_grad_(True)
            original = transposed.detach().clone()
            out = self.apply(transposed, fade_mode=mode)
            self.codes(out)
            self.assertTrue(self.torch.equal(out, self.apply(transposed.contiguous(), fade_mode=mode)))
            self.assertTrue(self.torch.equal(transposed, original))
            self.assertNotEqual(out.data_ptr(), transposed.data_ptr())

    def test_real_mask_goldens_match_decimal_oracle_and_pinned_hashes(self):
        for p, expected in GOLDENS:
            codes = self.codes(self.apply(self.white, **p))
            self.assertEqual(hashlib.sha256(bytes(codes)).hexdigest(), expected)
            self.assertEqual(codes, tuple(reference(x, y, **p) for y in range(128) for x in range(128)))

    def test_real_pattern_golden_matches_decoded_original_and_decimal_oracle(self):
        source = patterns.ConditioningLayersPatternField().load('soft-radial-gradient.png')[0]
        p = dict(angle_degrees=135., fade_start_position=.1, fade_end_position=.9,
                 start_value=40, end_value=180, curve_exponent=2.)
        codes = self.codes(self.apply(source, **p))
        original_codes = self.codes(source)
        expected = tuple(reference(i % 128, i // 128, c, **p) for i, c in enumerate(original_codes))
        self.assertEqual(codes, expected)
        self.assertEqual(hashlib.sha256(bytes(codes)).hexdigest(), PATTERN_GOLDEN)

    def test_multiplicative_grayscale_structure_ranges_and_exponents(self):
        for mode in ('linear', 'circular', 'square'):
            for first, last in ((255, 0), (0, 255), (180, 40), (40, 180), (128, 128)):
                for power in (.5, 1., 2., 4.):
                    p = dict(fade_mode=mode, start_value=first, end_value=last, curve_exponent=power)
                    codes = self.codes(self.apply(**p))
                    for i in (0, 67, 127, 31*128+92, 63*128+64, 100*128+37, 16383):
                        self.assertEqual(codes[i], reference(i % 128, i // 128, self.source[i], **p))
                    self.assertTrue(all(0 <= out <= inp for out, inp in zip(codes, self.source)))

    def test_exact_half_ties_and_no_intermediate_fade_quantization(self):
        # x=63 gives t=.5 at the authored start/end midpoint. M=1, F=127.5:
        # final .5 -> 1; prequantizing F would corrupt nearby products.
        p = dict(fade_start_position=0., fade_end_position=127/128)
        one = fields.codes_to_mask([1]*16384)
        self.assertEqual(self.codes(self.apply(one, **p))[63], 1)
        # M=128, F=127.5 ->64, whereas quantizing F=128 first gives 64.251...
        # Search independent expected values to prove the observable distinction.
        source = fields.codes_to_mask([101]*16384)
        codes = self.codes(self.apply(source, start_value=180, end_value=40))
        expected = [reference(x, 0, 101, start_value=180, end_value=40) for x in range(128)]
        twice = [int(101 * reference(x, 0, start_value=180, end_value=40) / 255 + .5) for x in range(128)]
        self.assertEqual(list(codes[:128]), expected)
        self.assertNotEqual(expected, twice)

    def test_unused_controls_have_no_effect_on_output_bits(self):
        radial = dict(center_x=None, center_y='unused', inner_size=1, outer_size=0,
                      aspect_x=0, aspect_y=float('nan'), rotation_degrees=999)
        self.assertTrue(self.torch.equal(self.apply(), self.apply(**radial)))
        for mode in ('circular', 'square'):
            self.assertTrue(self.torch.equal(self.apply(fade_mode=mode), self.apply(fade_mode=mode,
                angle_degrees=None, fade_start_position=1, fade_end_position=0)))

    def test_invalid_masks_rejected_even_for_constant_modulation(self):
        t = self.torch
        invalid = [None, [], self.mask.double(), self.mask.to(t.int32), t.zeros(2, 128, 128),
                   t.zeros(1, 64, 64), t.zeros(1, 1, 128, 128), t.empty((1, 128, 128), device='meta')]
        for value in (.5, -.1, 1.1, float('nan'), float('inf')):
            bad = self.mask.clone()
            bad[0, 0, 0] = value
            invalid.append(bad)
        for bad in invalid:
            for mode in ('linear', 'circular', 'square'):
                for value in (0, 255):
                    with self.assertRaises(ValueError):
                        self.apply(bad if bad is not None else [], fade_mode=mode, start_value=value, end_value=value)
        with self.assertRaises(ValueError):
            self.node.apply(None)

    def test_all_original_patterns_remain_byte_identical(self):
        registry = patterns.pattern_registry()
        self.assertEqual(len(registry), 16)
        for name, digest in registry.items():
            path = patterns.REFERENCE_FIELD_ROOT / name
            before = path.read_bytes()
            self.assertEqual(hashlib.sha256(before).hexdigest(), digest)
            mask = patterns.ConditioningLayersPatternField().load(name)[0]
            original = mask.clone()
            for mode in ('linear', 'circular', 'square'):
                self.codes(self.apply(mask, fade_mode=mode))
            self.assertTrue(self.torch.equal(mask, original))
            self.assertEqual(path.read_bytes(), before)

    def compose(self, masks, modes):
        comfy = ModuleType('comfy')
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        stack = None
        prompts = []
        for index, (mask, mode) in enumerate(zip(masks, modes)):
            conditioning = [[self.torch.ones((1, 2, 3)), {}]]
            prompts.append(conditioning[0][0])
            layer = ConditioningLayersLayer().create(conditioning, mask, 1, mode, True, unique_id=str(index))[0]
            stack = ConditioningLayersAddLayer().add(layer, stack)[0]
        with patch.dict('sys.modules', {'comfy': comfy}):
            result = ConditioningLayersCompose().compose(stack)[0]
        for entry, prompt in zip(result, prompts):
            self.assertIs(entry[0], prompt)
        return result

    def test_requested_source_operation_chains_reach_layer_and_compose(self):
        pattern = patterns.ConditioningLayersPatternField().load('soft-radial-gradient.png')[0]
        sources = (
            pattern,
            ConditioningLayersScatterField().generate(17, 8, 50, 75, 5., 25, 'disk')[0],
            fields.ConditioningLayersRectangleField().generate(64, 64, 64, 64, 255, 0)[0],
            fields.ConditioningLayersEllipseField().generate(64, 64, 32, 24, 255, 0)[0],
            ConditioningLayersCyclicPartitionField().generate(8, 8, 3, 1)[0],
            ConditioningLayersFieldRepeat().repeat(pattern, 2, 3)[0],
            ConditioningLayersFieldTransform().transform(pattern, rotation_degrees=19)[0],
            ConditioningLayersFieldRemap().remap(pattern, 40, 200, 0, 230)[0],
            ConditioningLayersFieldBlur().blur(pattern, 4)[0],
        )
        for source in sources:
            original = source.clone()
            for mode in ('linear', 'circular', 'square'):
                faded = self.apply(source, fade_mode=mode, end_value=40)
                for mask in (faded, fields.ConditioningLayersInvertField().invert(faded)[0]):
                    for layer_mode in ('FIXED', 'BLENDED'):
                        result = self.compose((mask,), (layer_mode,))
                        self.assertTrue(self.torch.equal(result[0][1]['mask'], (mask > 0).float()))
            self.assertTrue(self.torch.equal(source, original))

    def test_overlapping_faded_cyclic_members_blend_with_retained_ratio_and_fixed_rejects(self):
        raw = ConditioningLayersCyclicPartitionField().generate(8, 8, 2, 1)[:2]
        masks = [self.apply(ConditioningLayersFieldBlur().blur(m, 3)[0],
                            fade_mode=mode, start_value=180, end_value=40)
                 for m, mode in zip(raw, ('circular', 'square'))]
        result = self.compose(masks, ('BLENDED', 'BLENDED'))
        codes = [self.codes(m) for m in masks]
        for index, entry in enumerate(result):
            expected = [round_ratio_to_binary32(pair[index], sum(pair)) if sum(pair) else 0.
                        for pair in zip(*codes)]
            expected = self.torch.tensor(expected, dtype=self.torch.float32).reshape(1, 128, 128)
            self.assertTrue(self.torch.equal(entry[1]['mask'].view(self.torch.int32), expected.view(self.torch.int32)))
        with self.assertRaises(ValueError):
            self.compose(masks, ('FIXED', 'FIXED'))

    def test_all_zero_output_preserves_empty_layer_rejection(self):
        mask = self.apply(start_value=0, end_value=0)
        with self.assertRaises(ValueError):
            self.compose((mask,), ('BLENDED',))

    def test_repeatability_across_cpu_threads_and_fresh_storage(self):
        previous = self.torch.get_num_threads()
        try:
            for p, _ in GOLDENS:
                self.torch.set_num_threads(1)
                a = self.apply(**p)
                self.torch.set_num_threads(2)
                b = self.apply(**p)
                self.assertTrue(self.torch.equal(a, b))
                self.assertNotEqual(a.data_ptr(), b.data_ptr())
        finally:
            self.torch.set_num_threads(previous)


if __name__ == '__main__':
    unittest.main()
