"""Periodic field sampling and native interoperability; offline host lane."""

from fractions import Fraction
import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

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


def reference(source, rx, ry, px=0, py=0):
    """Independent rational four-weight sum; round only after the full sum."""
    result = []
    for y in range(128):
        for x in range(128):
            u = (Fraction(2 * x + 1, 2) - px) * rx - Fraction(1, 2)
            v = (Fraction(2 * y + 1, 2) - py) * ry - Fraction(1, 2)
            ix, iy = u // 1, v // 1
            fx, fy = u - ix, v - iy
            value = sum(source[((iy + j) % 128) * 128 + (ix + i) % 128] * wx * wy
                        for i, wx in ((0, 1 - fx), (1, fx))
                        for j, wy in ((0, 1 - fy), (1, fy)))
            result.append((2 * value.numerator + value.denominator) // (2 * value.denominator))
    return tuple(result)


class RepeatTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersFieldRepeat()
        self.source = tuple((x + 3 * y) % 256 for y in range(128) for x in range(128))
        self.mask = fields.codes_to_mask(self.source)

    def repeat(self, mask=None, **kwargs):
        return self.node.repeat(self.mask if mask is None else mask, **kwargs)[0]

    def codes(self, mask):
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, "cpu")
        self.assertEqual(tuple(mask.shape), (1, 128, 128))
        codes = tuple(recover_sample_code(v) for v in mask.reshape(-1).tolist())
        self.assertTrue(self.torch.equal(mask.view(self.torch.int32),
                                        fields.codes_to_mask(codes).view(self.torch.int32)))
        return codes

    def test_grayscale_identity_is_bit_exact_and_storage_is_independent(self):
        original = self.mask.clone()
        result = self.repeat()
        self.assertEqual(self.codes(result), self.source)
        self.assertTrue(self.torch.equal(result.view(self.torch.int32), original.view(self.torch.int32)))
        self.assertNotEqual(result.data_ptr(), self.mask.data_ptr())
        result.zero_()
        self.assertTrue(self.torch.equal(self.mask, original))

    def test_pattern_identity_and_all_16_original_bytes_are_preserved(self):
        registry = patterns.pattern_registry()
        self.assertEqual(len(registry), 16)
        for name, checksum in registry.items():
            with self.subTest(name=name):
                path = patterns.REFERENCE_FIELD_ROOT / name
                before = path.read_bytes()
                self.assertEqual(hashlib.sha256(before).hexdigest(), checksum)
                mask = patterns.ConditioningLayersPatternField().load(name)[0]
                original = mask.clone()
                self.assertTrue(self.torch.equal(self.repeat(mask).view(self.torch.int32),
                                                mask.view(self.torch.int32)))
                self.codes(self.repeat(mask, repeats_x=3, repeats_y=4, phase_x=-7, phase_y=13))
                self.assertTrue(self.torch.equal(mask, original))
                self.assertEqual(path.read_bytes(), before)

    def test_two_horizontal_repetitions_average_source_pairs(self):
        expected = tuple((self.source[y * 128 + (2 * x) % 128]
                          + self.source[y * 128 + (2 * x + 1) % 128] + 1) // 2
                         for y in range(128) for x in range(128))
        result = self.repeat(repeats_x=2)
        self.assertEqual(self.codes(result), expected)
        self.assertTrue(self.torch.equal(result[:, :, :64], result[:, :, 64:]))

    def test_two_vertical_repetitions_average_source_pairs(self):
        expected = tuple((self.source[((2 * y) % 128) * 128 + x]
                          + self.source[((2 * y + 1) % 128) * 128 + x] + 1) // 2
                         for y in range(128) for x in range(128))
        result = self.repeat(repeats_y=2)
        self.assertEqual(self.codes(result), expected)
        self.assertTrue(self.torch.equal(result[:, :64, :], result[:, 64:, :]))

    def test_several_x_counts_match_rational_reference(self):
        for count in (3, 4, 7, 8, 15, 16):
            with self.subTest(count=count):
                self.assertEqual(self.codes(self.repeat(repeats_x=count)), reference(self.source, count, 1))

    def test_several_y_counts_match_rational_reference(self):
        for count in (3, 4, 7, 8, 15, 16):
            with self.subTest(count=count):
                self.assertEqual(self.codes(self.repeat(repeats_y=count)), reference(self.source, 1, count))

    def test_xy_original_checkerboard_grid_and_grayscale_match_reference(self):
        for name, rx, ry in (("checkerboard-coarse.png", 2, 4),
                              ("grid-3x3-center-corners.png", 3, 5),
                              ("soft-radial-gradient.png", 4, 2)):
            with self.subTest(name=name):
                with Image.open(patterns.REFERENCE_FIELD_ROOT / name) as image:
                    source = tuple(image.tobytes())
                mask = patterns.ConditioningLayersPatternField().load(name)[0]
                result = self.repeat(mask, repeats_x=rx, repeats_y=ry, phase_x=5, phase_y=-7)
                self.assertEqual(self.codes(result), reference(source, rx, ry, 5, -7))
                self.assertTrue(self.torch.equal(result, self.repeat(mask, repeats_x=rx, repeats_y=ry,
                                                                    phase_x=5, phase_y=-7)))

    def test_signed_phase_is_destination_pixel_shift_with_wrap(self):
        for rx, ry in ((1, 1), (2, 4), (3, 7), (16, 15)):
            base = self.repeat(repeats_x=rx, repeats_y=ry)
            for px, py in ((5, 0), (-5, 0), (0, 9), (0, -9), (5, -9), (-128, 128)):
                with self.subTest(rx=rx, ry=ry, px=px, py=py):
                    actual = self.repeat(repeats_x=rx, repeats_y=ry, phase_x=px, phase_y=py)
                    self.assertTrue(self.torch.equal(actual, self.torch.roll(base, (py, px), (1, 2))))

    def test_complete_tile_period_and_full_field_phase_equivalence(self):
        for count in (1, 2, 4, 8, 16):
            period = 128 // count
            base = self.repeat(repeats_x=count, repeats_y=count)
            for px, py in ((period, 0), (-period, 0), (0, period), (0, -period)):
                self.assertTrue(self.torch.equal(base, self.repeat(repeats_x=count, repeats_y=count,
                                                                  phase_x=px, phase_y=py)))
        for count in (3, 5, 7, 15):
            self.assertTrue(self.torch.equal(self.repeat(repeats_x=count, phase_x=-121),
                                            self.repeat(repeats_x=count, phase_x=7)))
            self.assertTrue(self.torch.equal(self.repeat(repeats_y=count, phase_y=-121),
                                            self.repeat(repeats_y=count, phase_y=7)))

    def test_quantize_once_and_exact_half_ties_up(self):
        # First 2x2 is [0,1;0,0]: the final .25 rounds to 0, not 1
        # (rounding each row first would incorrectly round .5 to 1 twice).
        codes = [0] * 16384
        codes[1] = 1
        mask = fields.codes_to_mask(codes)
        self.assertEqual(self.codes(self.repeat(mask, repeats_x=2, repeats_y=2))[0], 0)
        self.assertEqual(self.codes(self.repeat(mask, repeats_x=2))[0], 1)
        codes[0], codes[1] = 2, 3
        self.assertEqual(self.codes(self.repeat(fields.codes_to_mask(codes), repeats_x=2))[0], 3)

    def test_real_grayscale_structure_survives_in_each_repeated_tile(self):
        mask = patterns.ConditioningLayersPatternField().load("soft-radial-gradient.png")[0]
        result = self.repeat(mask, repeats_x=2, repeats_y=2)
        codes = self.codes(result)
        self.assertGreater(len(set(codes)), 100)
        self.assertGreater(codes[31 * 128 + 31], codes[0])
        tile = result[:, :64, :64]
        for y, x in ((0, 64), (64, 0), (64, 64)):
            self.assertTrue(self.torch.equal(tile, result[:, y:y + 64, x:x + 64]))

    def test_pattern_procedural_transform_invert_paths_reach_layer_and_compose(self):
        pattern = patterns.ConditioningLayersPatternField().load("grid-3x3-cross.png")[0]
        procedural = fields.ConditioningLayersRadialGradientField().generate(64, 64, 64, 64, 255, 0)[0]
        repeated = self.repeat(pattern, repeats_x=2, repeats_y=3)
        transform = ConditioningLayersFieldTransform()
        paths = [repeated, transform.transform(repeated, rotation_degrees=19, uniform_scale=.8)[0],
                 self.repeat(procedural, repeats_x=3, repeats_y=2),
                 fields.ConditioningLayersInvertField().invert(repeated)[0],
                 self.repeat(transform.transform(pattern, scale_x=.7, offset_x=5)[0], repeats_x=2)]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}):
            for field in paths:
                self.codes(field)
                for mode in ("FIXED", "BLENDED"):
                    conditioning = [[self.torch.ones((1, 2, 3)), {}]]
                    layer = ConditioningLayersLayer().create(conditioning, field, 1, mode, True,
                                                            unique_id="repeat")[0]
                    stack = ConditioningLayersAddLayer().add(layer)[0]
                    result = ConditioningLayersCompose().compose(stack)[0]
                    self.assertIs(result[0][0], conditioning[0][0])
                    self.assertTrue(self.torch.equal(result[0][1]["mask"], (field > 0).float()))

    def test_explicit_node_order_changes_result_and_transform_still_clips(self):
        transform = ConditioningLayersFieldTransform()
        after = transform.transform(self.repeat(repeats_x=2), offset_x=17)[0]
        before = self.repeat(transform.transform(self.mask, offset_x=17)[0], repeats_x=2)
        self.assertFalse(self.torch.equal(after, before))
        self.assertEqual(int(self.torch.count_nonzero(after[:, :, :17])), 0)
        self.assertTrue(self.torch.equal(self.repeat(repeats_x=2, phase_x=17),
                                        self.torch.roll(self.repeat(repeats_x=2), 17, 2)))

    def test_constant_and_empty_fields_are_constructible_consumer_rule_unchanged(self):
        for code in (0, 1, 173, 255):
            mask = fields.codes_to_mask([code] * 16384)
            result = self.repeat(mask, repeats_x=16, repeats_y=7, phase_x=-13, phase_y=23)
            self.assertEqual(set(self.codes(result)), {code})
        empty = self.repeat(fields.codes_to_mask([0] * 16384), repeats_x=3)
        layer = ConditioningLayersLayer().create([[self.torch.ones((1, 2, 3)), {}]], empty, 1,
                                                "BLENDED", True, unique_id="empty")[0]
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}), self.assertRaises(ValueError):
            ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0])

    def test_retained_alternate_encoding_2d_and_noncontiguous_masks(self):
        alternate = self.torch.tensor([round_ratio_to_binary32(c * 256, 65535) for c in self.source],
                                     dtype=self.torch.float32).reshape(1, 128, 128)
        self.assertEqual(self.codes(self.repeat(alternate)), self.source)
        self.assertTrue(self.torch.equal(self.repeat(alternate, repeats_x=2), self.repeat(repeats_x=2)))
        self.assertTrue(self.torch.equal(self.repeat(self.mask[0]), self.mask))
        transposed = self.mask.transpose(1, 2)
        self.assertTrue(self.torch.equal(self.repeat(transposed), transposed))

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
                self.node.repeat(mask)

    def test_invalid_counts_and_phases_rejected(self):
        for key in ("repeats_x", "repeats_y", "phase_x", "phase_y"):
            for value in (True, False, "1", None, 1.0, .5, float("nan"), float("inf")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.repeat(**{key: value})
        for key in ("repeats_x", "repeats_y"):
            for value in (-1, 0, 17, 10**20):
                with self.assertRaises(ValueError):
                    self.repeat(**{key: value})
        for key in ("phase_x", "phase_y"):
            for value in (-129, 129):
                with self.assertRaises(ValueError):
                    self.repeat(**{key: value})


if __name__ == "__main__":
    unittest.main()
