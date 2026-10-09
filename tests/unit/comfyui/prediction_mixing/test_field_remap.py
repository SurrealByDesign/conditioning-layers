"""Exact numeric field remapping and native interoperability; offline host lane."""

from fractions import Fraction
import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.field_remap import ConditioningLayersFieldRemap
from conditioning_layers.comfyui.field_repeat import ConditioningLayersFieldRepeat
from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui import influence_field_sources as fields
from conditioning_layers.comfyui import pattern_field_source as patterns
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code, round_ratio_to_binary32,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose,
)


def reference(code, low, high, first, last):
    """Independent piecewise rational interpolation, with explicit tie handling."""
    if code <= low:
        return first
    if code >= high:
        return last
    t = Fraction(code - low, high - low)
    value = (1 - t) * first + t * last
    whole, remainder = divmod(value.numerator, value.denominator)
    return whole + int(Fraction(remainder, value.denominator) >= Fraction(1, 2))


class RemapTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersFieldRemap()
        self.source = tuple((x + 3 * y) % 256 for y in range(128) for x in range(128))
        self.mask = fields.codes_to_mask(self.source)

    def remap(self, mask=None, **kwargs):
        return self.node.remap(self.mask if mask is None else mask, **kwargs)[0]

    def codes(self, mask):
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, "cpu")
        self.assertEqual(tuple(mask.shape), (1, 128, 128))
        codes = tuple(recover_sample_code(v) for v in mask.reshape(-1).tolist())
        self.assertTrue(self.torch.equal(mask.view(self.torch.int32),
                                        fields.codes_to_mask(codes).view(self.torch.int32)))
        return codes

    def test_grayscale_identity_all_codes_bit_exact_and_fresh_storage(self):
        self.assertEqual(set(self.source), set(range(256)))
        original = self.mask.clone()
        result = self.remap()
        self.assertEqual(self.codes(result), self.source)
        self.assertTrue(self.torch.equal(result.view(self.torch.int32), original.view(self.torch.int32)))
        self.assertNotEqual(result.data_ptr(), self.mask.data_ptr())
        result.zero_()
        self.assertTrue(self.torch.equal(self.mask, original))

    def test_all_16_patterns_identity_nonidentity_and_original_bytes_preserved(self):
        registry = patterns.pattern_registry()
        self.assertEqual(len(registry), 16)
        for name, checksum in registry.items():
            with self.subTest(name=name):
                path = patterns.REFERENCE_FIELD_ROOT / name
                before = path.read_bytes()
                self.assertEqual(hashlib.sha256(before).hexdigest(), checksum)
                mask = patterns.ConditioningLayersPatternField().load(name)[0]
                original = mask.clone()
                identity = self.remap(mask)
                self.codes(identity)
                self.assertTrue(self.torch.equal(identity.view(self.torch.int32), mask.view(self.torch.int32)))
                self.codes(self.remap(mask, input_low=50, input_high=200, output_low=240, output_high=10))
                self.assertTrue(self.torch.equal(mask, original))
                self.assertEqual(path.read_bytes(), before)

    def test_range_expansion_clamps_all_five_boundary_cases(self):
        codes = self.codes(self.remap(input_low=50, input_high=200))
        by_input = dict(zip(self.source, codes))
        for x, expected in ((49, 0), (50, 0), (100, 85), (125, 128), (200, 255), (201, 255)):
            self.assertEqual(by_input[x], expected)

    def test_range_compression(self):
        by_input = dict(zip(self.source, self.codes(self.remap(output_low=60, output_high=180))))
        for x, expected in ((0, 60), (85, 100), (170, 140), (255, 180)):
            self.assertEqual(by_input[x], expected)

    def test_descending_range_and_endpoint_clamping(self):
        codes = self.codes(self.remap(input_low=50, input_high=200, output_low=220, output_high=20))
        by_input = dict(zip(self.source, codes))
        for x, expected in ((49, 220), (50, 220), (125, 120), (200, 20), (201, 20)):
            self.assertEqual(by_input[x], expected)

    def test_representative_fractional_and_half_ties_round_up(self):
        for params, expected in (((0, 6, 0, 3), (0, 1, 1, 2, 2, 3, 3)),
                                 ((0, 6, 3, 0), (3, 3, 2, 2, 1, 1, 0)),
                                 ((0, 6, 1, 3), (1, 1, 2, 2, 2, 3, 3))):
            with self.subTest(params=params):
                result = self.node.remap(self.mask, *params)[0]
                by_input = dict(zip(self.source, self.codes(result)))
                self.assertEqual(tuple(by_input[x] for x in range(7)), expected)

    def test_all_256_codes_match_rational_reference_and_are_deterministic(self):
        for params in ((0, 255, 0, 255), (0, 255, 255, 0), (40, 190, 0, 255),
                       (0, 255, 50, 201), (19, 202, 230, 12), (0, 6, 0, 3),
                       (0, 6, 3, 0), (127, 128, 0, 255), (0, 255, 81, 81)):
            with self.subTest(params=params):
                before = self.mask.clone()
                result = self.node.remap(self.mask, *params)[0]
                self.assertEqual(self.codes(result), tuple(reference(x, *params) for x in self.source))
                self.assertTrue(self.torch.equal(result, self.node.remap(self.mask, *params)[0]))
                self.assertTrue(self.torch.equal(self.mask, before))

    def test_full_range_reversal_equals_retained_invert_for_both_encodings(self):
        alternate = self.torch.tensor([round_ratio_to_binary32(c * 256, 65535) for c in self.source],
                                     dtype=self.torch.float32).reshape(1, 128, 128)
        for mask in (self.mask, alternate):
            result = self.remap(mask, output_low=255, output_high=0)
            inverted = fields.ConditioningLayersInvertField().invert(mask)[0]
            self.assertEqual(self.codes(result), tuple(255 - c for c in self.source))
            self.assertEqual(self.codes(result), self.codes(inverted))
            self.assertTrue(self.torch.equal(result.view(self.torch.int32), inverted.view(self.torch.int32)))

    def test_alternate_encoding_identity_2d_noncontiguous_and_grad_input(self):
        alternate = self.torch.tensor([round_ratio_to_binary32(c * 256, 65535) for c in self.source],
                                     dtype=self.torch.float32).reshape(1, 128, 128)
        self.assertFalse(self.torch.equal(alternate, self.mask))
        self.assertEqual(self.codes(self.remap(alternate)), self.source)
        self.assertTrue(self.torch.equal(self.remap(alternate), self.mask))
        self.assertTrue(self.torch.equal(self.remap(self.mask[0]), self.mask))
        transposed = self.mask.transpose(1, 2)
        self.assertTrue(self.torch.equal(self.remap(transposed), transposed))
        self.mask.requires_grad_(True)
        self.assertFalse(self.remap().requires_grad)

    def test_sources_repeat_transform_and_invert_paths_reach_layer_and_compose(self):
        pattern = patterns.ConditioningLayersPatternField().load("soft-radial-gradient.png")[0]
        procedural = fields.ConditioningLayersLinearGradientField().generate(.5, 64, 127.5, 64, 0, 255)[0]
        repeated = ConditioningLayersFieldRepeat().repeat(pattern, repeats_x=2, repeats_y=3)[0]
        transformed = ConditioningLayersFieldTransform().transform(pattern, rotation_degrees=19)[0]
        combined = ConditioningLayersFieldTransform().transform(repeated, offset_x=9)[0]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}):
            for source in (pattern, procedural, repeated, transformed, combined, self.mask):
                original = source.clone()
                remapped = self.remap(source, input_low=40, input_high=200, output_low=0, output_high=230)
                for field in (remapped, fields.ConditioningLayersInvertField().invert(remapped)[0]):
                    self.codes(field)
                    for mode in ("FIXED", "BLENDED"):
                        conditioning = [[self.torch.ones((1, 2, 3)), {}]]
                        layer = ConditioningLayersLayer().create(conditioning, field, 1, mode, True,
                                                                unique_id="remap")[0]
                        result = ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0])[0]
                        self.assertIs(result[0][0], conditioning[0][0])
                        self.assertTrue(self.torch.equal(result[0][1]["mask"], (field > 0).float()))
                self.assertTrue(self.torch.equal(source, original))

    def test_equal_output_endpoints_and_empty_consumer_rejection_unchanged(self):
        for code in (0, 1, 173, 255):
            result = self.remap(output_low=code, output_high=code)
            self.assertEqual(set(self.codes(result)), {code})
            constant = fields.codes_to_mask([code] * 16384)
            self.assertTrue(self.torch.equal(self.remap(constant), constant))
        empty = self.remap(output_low=0, output_high=0)
        layer = ConditioningLayersLayer().create([[self.torch.ones((1, 2, 3)), {}]], empty, 1,
                                                "BLENDED", True, unique_id="empty")[0]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}), self.assertRaises(ValueError):
            ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0])

    def test_invalid_masks_rejected_without_snapping(self):
        torch = self.torch
        invalid = [None, [], self.mask.double(), self.mask.to(torch.int32),
                   torch.zeros((2, 128, 128)), torch.zeros((1, 64, 64)), torch.zeros((1, 1, 128, 128)),
                   torch.empty((1, 128, 128), device="meta")]
        for value in (.5, -.1, 1.1, float("nan"), float("inf")):
            mask = self.mask.clone()
            mask[0, 0, 0] = value
            invalid.append(mask)
        for mask in invalid:
            with self.subTest(kind=type(mask)), self.assertRaises(ValueError):
                self.node.remap(mask)

    def test_invalid_parameter_types_bounds_and_input_ranges_rejected(self):
        for key in ("input_low", "input_high", "output_low", "output_high"):
            for value in (True, False, "1", None, 1.0, .5, float("nan"), float("inf"), -1, 256, 10**20):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.remap(**{key: value})
        for low, high in ((0, 0), (127, 127), (255, 255), (200, 50), (255, 0)):
            with self.subTest(low=low, high=high), self.assertRaisesRegex(ValueError, "input_low < input_high"):
                self.remap(input_low=low, input_high=high)


if __name__ == "__main__":
    unittest.main()
