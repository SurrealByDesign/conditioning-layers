"""Field Blur numerics and native consumer interoperability; host lane."""

import hashlib
import math
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.field_blur import ConditioningLayersFieldBlur, _quantize
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


def reference_sample(codes, x, y, radius):
    """Independent full 2-D Gaussian sum (no separable passes or Torch)."""
    sigma = radius / 2
    terms, weights = [], []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            weight = math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma))
            weights.append(weight)
            if 0 <= x + dx < 128 and 0 <= y + dy < 128:
                terms.append(codes[(y + dy) * 128 + x + dx] * weight)
    value = math.fsum(terms) / math.fsum(weights)
    whole, fraction = divmod(value, 1)
    return int(whole) + int(fraction >= .5)


class BlurTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersFieldBlur()
        self.source = tuple((x + 3 * y) % 256 for y in range(128) for x in range(128))
        self.mask = fields.codes_to_mask(self.source)

    def blur(self, mask=None, radius=0):
        return self.node.blur(self.mask if mask is None else mask, radius)[0]

    def codes(self, mask):
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, "cpu")
        self.assertEqual(tuple(mask.shape), (1, 128, 128))
        codes = tuple(recover_sample_code(v) for v in mask.reshape(-1).tolist())
        self.assertTrue(self.torch.equal(mask.view(self.torch.int32),
                                        fields.codes_to_mask(codes).view(self.torch.int32)))
        return codes

    def test_zero_radius_all_grayscale_codes_bit_identity_and_fresh_storage(self):
        original = self.mask.clone()
        result = self.blur()
        self.assertEqual(set(self.source), set(range(256)))
        self.assertEqual(self.codes(result), self.source)
        self.assertTrue(self.torch.equal(result.view(self.torch.int32), original.view(self.torch.int32)))
        self.assertNotEqual(result.data_ptr(), self.mask.data_ptr())
        result.zero_()
        self.assertTrue(self.torch.equal(self.mask, original))

    def test_alternate_encoding_identity_and_positive_radius_equivalence(self):
        alternate = self.torch.tensor([round_ratio_to_binary32(c * 256, 65535) for c in self.source],
                                     dtype=self.torch.float32).reshape(1, 128, 128)
        self.assertFalse(self.torch.equal(alternate, self.mask))
        self.assertEqual(self.codes(self.blur(alternate)), self.source)
        for radius in (0, 3):
            self.assertTrue(self.torch.equal(self.blur(alternate, radius), self.blur(radius=radius)))

    def test_2d_noncontiguous_and_gradient_inputs(self):
        self.assertTrue(self.torch.equal(self.blur(self.mask[0]), self.mask))
        transposed = self.mask.transpose(1, 2)
        self.assertFalse(transposed.is_contiguous())
        self.assertTrue(self.torch.equal(self.blur(transposed), transposed))
        self.codes(self.blur(transposed, 3))
        self.mask.requires_grad_(True)
        self.assertFalse(self.blur(radius=3).requires_grad)

    def test_binary_vertical_split_transition_interiors_and_symmetry(self):
        source = fields.codes_to_mask(255 if x >= 64 else 0 for y in range(128) for x in range(128))
        for radius in (1, 4, 16, 32):
            result = self.blur(source, radius)
            row = self.codes(result)[64 * 128:65 * 128]
            self.assertEqual(row[64 - radius - 1], 0)
            if radius < 32:
                self.assertEqual(row[64 + radius], 255)
            else:
                # A 65-cell kernel cannot fit inside the 64-cell white half.
                self.assertEqual(max(row), 254)
            self.assertTrue(0 < row[63] < row[64] < 255)
            self.assertEqual(tuple(row[32:96]), tuple(sorted(row[32:96])))
            self.assertEqual(tuple(row[32:96]), tuple(255 - c for c in reversed(row[32:96])))
            self.assertTrue(self.torch.equal(result, self.blur(source, radius)))
            self.assertTrue(self.torch.equal(result, result.flip(1)))
            self.assertTrue(self.torch.equal(result.transpose(1, 2), self.blur(source.transpose(1, 2), radius)))

    def test_rectangle_and_ellipse_hard_edges_become_grayscale(self):
        sources = (fields.ConditioningLayersRectangleField().generate(64, 64, 64, 64, 255, 0)[0],
                   fields.ConditioningLayersEllipseField().generate(64, 64, 32, 32, 255, 0)[0])
        for source in sources:
            before = source.clone()
            self.assertEqual(set(self.codes(source)), {0, 255})
            result = self.blur(source, 4)
            codes = self.codes(result)
            self.assertGreater(len(set(codes)), 2)
            self.assertEqual(codes[64 * 128 + 64], 255)
            self.assertEqual(codes[0], 0)
            self.assertTrue(0 < codes[64 * 128 + 31] < codes[64 * 128 + 32] < 255)
            self.assertTrue(self.torch.equal(result, result.flip(1)))
            self.assertTrue(self.torch.equal(result, result.flip(2)))
            self.assertTrue(self.torch.equal(result, result.transpose(1, 2)))
            self.assertTrue(self.torch.equal(source, before))

    def test_soft_radial_gradient_identity_smoothing_and_center_symmetry(self):
        source = patterns.ConditioningLayersPatternField().load("soft-radial-gradient.png")[0]
        self.assertTrue(self.torch.equal(self.blur(source).view(self.torch.int32), source.view(self.torch.int32)))
        result = self.blur(source, 8)
        codes = self.codes(result)
        self.assertGreater(len(set(codes)), 32)
        self.assertTrue(0 < codes[64 * 128 + 64] <= max(self.codes(source)))
        self.assertEqual(codes[64 * 128 + 64], max(codes))
        self.assertTrue(self.torch.equal(result, result.flip(1)))
        self.assertTrue(self.torch.equal(result, result.flip(2)))
        self.assertTrue(self.torch.equal(result, result.transpose(1, 2)))
        self.assertTrue(self.torch.equal(result, self.blur(source, 8)))

    def test_zero_padding_fades_constant_canvas_without_edge_renormalization(self):
        source = fields.ConditioningLayersSolidField().generate(255)[0]
        for radius in (1, 8, 32):
            codes = self.codes(self.blur(source, radius))
            self.assertTrue(0 < codes[0] < codes[64 * 128] < codes[64 * 128 + 64] == 255)
            for x, y in ((0, 0), (0, 64), (radius, radius), (127, 127)):
                self.assertEqual(codes[y * 128 + x], reference_sample([255] * 16384, x, y, radius))

    def test_edge_touching_field_never_wraps(self):
        source = fields.codes_to_mask(255 if x < 8 else 0 for y in range(128) for x in range(128))
        result = self.blur(source, 32)
        codes = self.codes(result)
        self.assertTrue(all(codes[y * 128 + x] == 0 for y in range(128) for x in range(40, 128)))
        self.assertGreater(codes[64 * 128], 0)
        self.assertGreater(codes[64 * 128 + 8], 0)

    def test_fractional_convolution_matches_independent_2d_reference(self):
        for radius in (1, 3, 9, 32):
            codes = self.codes(self.blur(radius=radius))
            for x, y in ((0, 0), (1, 64), (32, 32), (63, 64), (91, 27), (127, 127)):
                with self.subTest(radius=radius, x=x, y=y):
                    self.assertEqual(codes[y * 128 + x], reference_sample(self.source, x, y, radius))

    def test_final_quantizer_exact_half_ties_adjacent_floats_and_clamp(self):
        # Gaussian weights do not generally produce exact rational halves.
        # Exercise every representable code half directly at the final boundary.
        for code in range(255):
            tie = code + .5
            self.assertEqual(_quantize(tie), code + 1)
            self.assertEqual(_quantize(math.nextafter(tie, -math.inf)), code)
            self.assertEqual(_quantize(math.nextafter(tie, math.inf)), code + 1)
        for value, expected in ((-1, 0), (256, 255), (.1, 0), (.9, 1), (123.25, 123), (123.75, 124)):
            self.assertEqual(_quantize(value), expected)

    def test_max_radius_deterministic_across_cpu_thread_counts_and_fresh(self):
        original = self.mask.clone()
        count = self.torch.get_num_threads()
        try:
            self.torch.set_num_threads(1)
            first = self.blur(radius=32)
            self.torch.set_num_threads(2)
            second = self.blur(radius=32)
        finally:
            self.torch.set_num_threads(count)
        self.codes(first)
        self.assertTrue(self.torch.equal(first.view(self.torch.int32), second.view(self.torch.int32)))
        self.assertNotEqual(first.data_ptr(), self.mask.data_ptr())
        first.zero_()
        self.assertTrue(self.torch.equal(self.mask, original))

    def test_all_16_patterns_blur_and_original_bytes_preserved(self):
        registry = patterns.pattern_registry()
        self.assertEqual(len(registry), 16)
        for name, checksum in registry.items():
            with self.subTest(name=name):
                path = patterns.REFERENCE_FIELD_ROOT / name
                before = path.read_bytes()
                self.assertEqual(hashlib.sha256(before).hexdigest(), checksum)
                source = patterns.ConditioningLayersPatternField().load(name)[0]
                original = source.clone()
                self.codes(self.blur(source, 4))
                self.assertTrue(self.torch.equal(source, original))
                self.assertEqual(path.read_bytes(), before)

    def test_source_and_operation_chains_reach_layer_and_compose(self):
        pattern = patterns.ConditioningLayersPatternField().load("soft-radial-gradient.png")[0]
        procedural = fields.ConditioningLayersLinearGradientField().generate(.5, 64, 127.5, 64, 0, 255)[0]
        repeated = ConditioningLayersFieldRepeat().repeat(pattern, 2, 3)[0]
        transformed = ConditioningLayersFieldTransform().transform(pattern, rotation_degrees=19)[0]
        combined = ConditioningLayersFieldTransform().transform(repeated, offset_x=9)[0]
        remapped = ConditioningLayersFieldRemap().remap(pattern, 40, 200, 0, 230)[0]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}):
            for source in (pattern, procedural, repeated, transformed, combined, remapped, self.mask):
                original = source.clone()
                blurred = self.blur(source, 4)
                for field in (blurred, fields.ConditioningLayersInvertField().invert(blurred)[0]):
                    self.codes(field)
                    for mode in ("FIXED", "BLENDED"):
                        conditioning = [[self.torch.ones((1, 2, 3)), {}]]
                        layer = ConditioningLayersLayer().create(conditioning, field, 1, mode, True,
                                                                unique_id="blur")[0]
                        result = ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0])[0]
                        self.assertIs(result[0][0], conditioning[0][0])
                        self.assertTrue(self.torch.equal(result[0][1]["mask"], (field > 0).float()))
                self.assertTrue(self.torch.equal(source, original))

    def test_zero_field_constructible_consumer_still_rejects_empty(self):
        source = fields.ConditioningLayersSolidField().generate(0)[0]
        result = self.blur(source, 32)
        self.assertEqual(set(self.codes(result)), {0})
        layer = ConditioningLayersLayer().create([[self.torch.ones((1, 2, 3)), {}]], result, 1,
                                                "BLENDED", True, unique_id="empty")[0]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}), self.assertRaises(ValueError):
            ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0])

    def test_invalid_masks_rejected_even_at_zero_radius(self):
        torch = self.torch
        invalid = [None, [], self.mask.double(), self.mask.to(torch.int32),
                   torch.zeros((2, 128, 128)), torch.zeros((1, 64, 64)), torch.zeros((1, 1, 128, 128)),
                   torch.empty((1, 128, 128), device="meta")]
        for value in (.5, -.1, 1.1, float("nan"), float("inf")):
            mask = self.mask.clone()
            mask[0, 0, 0] = value
            invalid.append(mask)
        for mask in invalid:
            for radius in (0, 4):
                with self.subTest(kind=type(mask), radius=radius), self.assertRaises(ValueError):
                    self.node.blur(mask, radius)

    def test_invalid_radius_types_and_bounds(self):
        for value in (True, False, "1", None, 1.0, .5, float("nan"), float("inf"), -1, 33, 10**20):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.blur(radius=value)


if __name__ == "__main__":
    unittest.main()
