"""Native field geometry and codebook interoperability; offline host lane."""

from fractions import Fraction
import hashlib
import math
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui import influence_field_sources as fields
from conditioning_layers.comfyui import pattern_field_source as patterns
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code, round_ratio_to_binary32
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose,
)


class TransformTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersFieldTransform()
        # All codes, asymmetric spatial arrangement, independent of source nodes.
        self.mask = fields.codes_to_mask((x + 3 * y) % 256 for y in range(128) for x in range(128))

    def transform(self, mask=None, **kwargs):
        return self.node.transform(self.mask if mask is None else mask, **kwargs)[0]

    def codes(self, mask):
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, "cpu")
        self.assertEqual(tuple(mask.shape), (1, 128, 128))
        codes = tuple(recover_sample_code(value) for value in mask.reshape(-1).tolist())
        self.assertTrue(self.torch.equal(mask.view(self.torch.int32), fields.codes_to_mask(codes).view(self.torch.int32)))
        return codes

    def test_identity_is_bit_exact_and_owns_fresh_storage(self):
        original = self.mask.clone()
        for kwargs in ({}, {"rotation_degrees": 0}, {"rotation_degrees": 360},
                       {"rotation_degrees": -360}, {"uniform_scale": 2, "scale_x": .5, "scale_y": .5}):
            result = self.transform(**kwargs)
            self.assertTrue(self.torch.equal(result.view(self.torch.int32), original.view(self.torch.int32)))
            self.assertNotEqual(result.data_ptr(), self.mask.data_ptr())
            result.zero_()
            self.assertTrue(self.torch.equal(self.mask, original))

    def test_each_flip_is_exact_spatial_reversal_and_involution(self):
        for key, axis in (("flip_horizontal", 2), ("flip_vertical", 1)):
            with self.subTest(key=key):
                result = self.transform(**{key: True})
                self.assertTrue(self.torch.equal(result, self.mask.flip((axis,))))
                self.assertTrue(self.torch.equal(self.transform(result, **{key: True}), self.mask))
        both = self.transform(flip_horizontal=True, flip_vertical=True)
        self.assertTrue(self.torch.equal(both, self.mask.flip((1, 2))))
        self.assertTrue(self.torch.equal(self.transform(both, flip_horizontal=True, flip_vertical=True), self.mask))

    def test_signed_integer_offsets_clip_and_never_wrap(self):
        for dx, dy in ((7, 0), (-7, 0), (0, 11), (0, -11), (7, -11),
                       (128, 0), (-128, 0), (0, 128), (0, -128), (16384, -16384)):
            with self.subTest(dx=dx, dy=dy):
                expected = self.torch.zeros_like(self.mask)
                for y in range(128):
                    for x in range(128):
                        if 0 <= x - dx < 128 and 0 <= y - dy < 128:
                            expected[0, y, x] = self.mask[0, y - dy, x - dx]
                self.assertTrue(self.torch.equal(self.transform(offset_x=dx, offset_y=dy), expected))

    def test_fractional_offsets_use_bilinear_half_up_not_bankers_rounding(self):
        mask = fields.codes_to_mask(x for y in range(128) for x in range(128))
        output = self.codes(self.transform(mask, offset_x=.5))
        self.assertEqual(output[20 * 128 + 2], 2)  # 1.5 -> 2
        self.assertEqual(output[20 * 128 + 3], 3)  # 2.5 -> 3
        self.assertEqual(output[20 * 128], 0)  # source x=0, edge-center clamp
        solid = fields.codes_to_mask([255] * 16384)
        shifted = self.codes(self.transform(solid, offset_x=.75))
        self.assertEqual(shifted[0], 0)  # outside footprint, no interpolation halo
        self.assertEqual(shifted[1], 255)

    def test_uniform_shrink_zero_fills_and_preserves_center(self):
        solid = fields.codes_to_mask([255] * 16384)
        output = self.codes(self.transform(solid, uniform_scale=.5))
        expected = tuple(255 if 32 <= x < 96 and 32 <= y < 96 else 0
                         for y in range(128) for x in range(128))
        self.assertEqual(output, expected)

    def test_uniform_enlarge_keeps_constant_edge_values_without_padding_fade(self):
        solid = fields.codes_to_mask([173] * 16384)
        self.assertTrue(self.torch.equal(self.transform(solid, uniform_scale=2), solid))
        rectangle = fields.ConditioningLayersRectangleField().generate(64, 64, 32, 32, 255, 0)[0]
        output = self.transform(rectangle, uniform_scale=2)
        self.codes(output)
        self.assertTrue(self.torch.equal(output, output.flip((1, 2))))
        self.assertEqual(int((output > 0).sum()), 66 * 66)  # bilinear edge samples included
        self.assertEqual(float(output[0, 64, 64]), 1.0)
        self.assertEqual(float(output[0, 0, 0]), 0.0)

    def test_nonuniform_scales_and_uniform_multiplier(self):
        solid = fields.codes_to_mask([255] * 16384)
        for sx, sy in ((.5, 1), (1, .5), (.5, .25), (.5, 2)):
            with self.subTest(sx=sx, sy=sy):
                result = self.transform(solid, scale_x=sx, scale_y=sy)
                expected = tuple(255 if abs(x + .5 - 64) < 64 * sx and abs(y + .5 - 64) < 64 * sy else 0
                                 for y in range(128) for x in range(128))
                self.assertEqual(self.codes(result), expected)
                self.assertTrue(self.torch.equal(result, self.transform(solid, uniform_scale=2, scale_x=sx/2, scale_y=sy/2)))

    def test_quarter_turns_are_exact_clockwise_permutations(self):
        for angle, turns in ((0, 0), (90, -1), (180, -2), (270, -3), (-90, 1)):
            with self.subTest(angle=angle):
                self.assertTrue(self.torch.equal(self.transform(rotation_degrees=angle),
                                                self.torch.rot90(self.mask, turns, (1, 2))))

    def test_combined_order_is_local_flip_scale_rotate_then_canvas_offset(self):
        result = self.transform(flip_horizontal=True, rotation_degrees=90, offset_x=3, offset_y=-2)
        rotated = self.torch.rot90(self.mask.flip((2,)), -1, (1, 2))
        expected = self.torch.zeros_like(rotated)
        expected[:, :126, 3:] = rotated[:, 2:, :125]
        self.assertTrue(self.torch.equal(result, expected))
        solid = fields.codes_to_mask([255] * 16384)
        output = self.codes(self.transform(solid, scale_x=.5, rotation_degrees=90))
        self.assertEqual(output, tuple(255 if 32 <= y < 96 else 0 for y in range(128) for x in range(128)))

    def test_arbitrary_rotation_is_deterministic_centered_and_clipped(self):
        solid = fields.codes_to_mask([255] * 16384)
        result = self.transform(solid, rotation_degrees=33)
        self.assertTrue(self.torch.equal(result, self.transform(solid, rotation_degrees=33)))
        self.assertTrue(self.torch.equal(result, result.flip((1, 2))))
        codes = self.codes(result)
        for index in (0, 127, 127 * 128, 16383):
            self.assertEqual(codes[index], 0)
        self.assertEqual(codes[64 * 128 + 64], 255)
        tiny = fields.ConditioningLayersRectangleField().generate(64, 64, 8, 8, 255, 0)[0]
        centered = self.transform(tiny, rotation_degrees=33)
        self.assertTrue(self.torch.equal(centered, centered.flip((1, 2))))
        self.assertTrue(self.torch.equal(self.transform(tiny, rotation_degrees=33, offset_x=128), self.torch.zeros_like(tiny)))

    def test_real_grayscale_matches_independent_rational_bilinear_oracle(self):
        path = patterns.REFERENCE_FIELD_ROOT / "soft-radial-gradient.png"
        with Image.open(path) as image:
            source = tuple(image.tobytes())
        mask = patterns.ConditioningLayersPatternField().load(path.name)[0]
        result = self.transform(mask, uniform_scale=.75, rotation_degrees=31, offset_x=2.25, offset_y=-1.5)
        self.assertTrue(self.torch.equal(result, self.transform(mask, uniform_scale=.75, rotation_degrees=31,
                                                              offset_x=2.25, offset_y=-1.5)))
        output = self.codes(result)
        self.assertGreater(len(set(output)), 200)
        # Independent four-weight rational sum at binary64 mapped coordinates.
        # Allows no output tolerance: every quantized code must match.
        cosine, sine = math.cos(math.radians(31)), math.sin(math.radians(31))
        expected = []
        for y in range(128):
            for x in range(128):
                dx, dy = x + .5 - 64 - 2.25, y + .5 - 64 + 1.5
                px, py = (cosine * dx + sine * dy) / .75 + 64, (-sine * dx + cosine * dy) / .75 + 64
                if not (0 <= px < 128 and 0 <= py < 128):
                    expected.append(0)
                    continue
                px, py = Fraction(max(0, min(127, px - .5))), Fraction(max(0, min(127, py - .5)))
                ix, iy = int(px), int(py)
                fx, fy = px - ix, py - iy
                value = sum(source[min(127, iy + j) * 128 + min(127, ix + i)] * wx * wy
                            for i, wx in ((0, 1-fx), (1, fx)) for j, wy in ((0, 1-fy), (1, fy)))
                expected.append((2 * value.numerator + value.denominator) // (2 * value.denominator))
        self.assertEqual(output, tuple(expected))

    def test_all_originals_are_read_only_and_transform_outputs_are_codebook_compatible(self):
        for name, checksum in patterns.pattern_registry().items():
            path = patterns.REFERENCE_FIELD_ROOT / name
            before = path.read_bytes()
            mask = patterns.ConditioningLayersPatternField().load(name)[0]
            saved = mask.clone()
            output = self.transform(mask, scale_x=.83, scale_y=1.2, rotation_degrees=-17, offset_x=-5.5)
            self.codes(output)
            self.assertTrue(self.torch.equal(mask, saved))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(hashlib.sha256(before).hexdigest(), checksum)

    def test_pattern_procedural_and_invert_paths_reach_both_layer_modes(self):
        masks = [patterns.ConditioningLayersPatternField().load("checkerboard-coarse.png")[0],
                 fields.ConditioningLayersRectangleField().generate(64, 64, 64, 64, 255, 0)[0],
                 fields.ConditioningLayersRadialGradientField().generate(64, 64, 64, 64, 255, 0)[0]]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}):
            for mask in masks:
                transformed = self.transform(mask, uniform_scale=.75, rotation_degrees=15)
                for field in (transformed, fields.ConditioningLayersInvertField().invert(transformed)[0]):
                    for mode in ("FIXED", "BLENDED"):
                        conditioning = [[self.torch.ones((1, 2, 3)), {}]]
                        layer = ConditioningLayersLayer().create(conditioning, field, 1, mode, True, unique_id="transform")[0]
                        stack = ConditioningLayersAddLayer().add(layer)[0]
                        result = ConditioningLayersCompose().compose(stack)[0]
                        self.assertIs(result[0][0], conditioning[0][0])
                        self.assertTrue(self.torch.equal(result[0][1]["mask"], (field > 0).float()))

    def test_empty_output_is_allowed_but_enabled_empty_composition_still_fails(self):
        empty = self.transform(offset_x=128)
        self.assertEqual(set(self.codes(empty)), {0})
        self.assertTrue(self.torch.equal(self.transform(empty), empty))
        layer = ConditioningLayersLayer().create([[self.torch.ones((1, 2, 3)), {}]], empty, 1, "BLENDED", True,
                                                unique_id="empty")[0]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}), self.assertRaises(ValueError):
            ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0])

    def test_retained_encodings_promoted_2d_and_noncontiguous_inputs(self):
        # Pinned PyAV gray -> gbrpf32le decoder's retained second encoding.
        alternate = self.torch.tensor([round_ratio_to_binary32(code * 256, 65535)
                                       for code in list(range(256)) * 64], dtype=self.torch.float32)
        alternate = alternate.reshape(1, 128, 128)
        original_codes = tuple(recover_sample_code(v) for v in alternate.reshape(-1).tolist())
        self.assertEqual(self.codes(self.transform(alternate)), original_codes)
        self.assertTrue(self.torch.equal(self.transform(self.mask[0]), self.mask))
        transpose = self.mask.transpose(1, 2)
        self.assertTrue(self.torch.equal(self.transform(transpose), transpose))

    def test_invalid_masks_are_rejected_without_input_snapping(self):
        torch = self.torch
        invalid = [None, [], self.mask.double(), self.mask.to(torch.int32),
                   torch.zeros((2, 128, 128)), torch.zeros((1, 64, 64)), torch.zeros((1, 1, 128, 128)),
                   torch.empty((1, 128, 128), device="meta")]
        for value in (.5, -.1, 1.1, float("nan"), float("inf")):
            mask = self.mask.clone()
            mask[0, 0, 0] = value
            invalid.append(mask)
        for mask in invalid:
            with self.subTest(mask_type=type(mask)), self.assertRaises(ValueError):
                self.node.transform(mask)

    def test_controls_reject_nonfinite_wrong_types_and_out_of_range(self):
        for key in ("uniform_scale", "scale_x", "scale_y", "rotation_degrees", "offset_x", "offset_y"):
            for value in (float("nan"), float("inf"), -float("inf"), True, "1", None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.transform(**{key: value})
        for key in ("uniform_scale", "scale_x", "scale_y"):
            for value in (0, -.5, .001, 101):
                with self.assertRaises(ValueError):
                    self.transform(**{key: value})
        for key, value in (("rotation_degrees", 361), ("offset_x", 16385), ("offset_y", -16385),
                           ("flip_horizontal", 1), ("flip_vertical", "false")):
            with self.assertRaises(ValueError):
                self.transform(**{key: value})


if __name__ == "__main__":
    unittest.main()
