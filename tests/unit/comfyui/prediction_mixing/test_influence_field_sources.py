"""Influence Field Sources v1 with real Torch; offline host lane."""

from fractions import Fraction
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import influence_field_sources as fields
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code, round_ratio_to_binary32, round_ratio_to_binary32_bits,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose, FIELD_SHAPE,
)


def defaults(node):
    return {name: spec[1]["default"] for name, spec in node.INPUT_TYPES()["required"].items()}


class FieldTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch

    def generate(self, node, **overrides):
        return node().generate(**(defaults(node) | overrides))[0]

    def codes(self, mask):
        self.assertEqual(tuple(mask.shape), FIELD_SHAPE)
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, "cpu")
        return tuple(recover_sample_code(value) for value in mask.reshape(-1).tolist())

    def test_all_256_solid_codes_exact_bits_shape_dtype(self):
        for code in range(256):
            with self.subTest(code=code):
                mask = self.generate(fields.ConditioningLayersSolidField, value=code)
                self.assertEqual(set(self.codes(mask)), {code})
                self.assertEqual(mask.view(self.torch.int32).unique().tolist(),
                                 [round_ratio_to_binary32_bits(code, 255)])

    def test_rectangle_half_open_boundaries_and_non_square_geometry(self):
        mask = self.generate(fields.ConditioningLayersRectangleField, center_x=3.5, center_y=4.5,
                             width=4, height=2, inside_value=173, outside_value=9)
        expected = tuple(173 if 1 <= x < 5 and 3 <= y < 5 else 9
                         for y in range(128) for x in range(128))
        self.assertEqual(self.codes(mask), expected)
        clipped = self.generate(fields.ConditioningLayersRectangleField, center_x=0, center_y=0,
                                width=2, height=2)
        self.assertEqual(self.codes(clipped).count(255), 1)

    def test_ellipse_non_circular_inclusive_boundary_and_clipping(self):
        mask = self.generate(fields.ConditioningLayersEllipseField, center_x=10.5, center_y=20.5,
                             radius_x=4, radius_y=2, inside_value=205, outside_value=3)
        expected = tuple(205 if Fraction((x - 10)**2, 16) + Fraction((y - 20)**2, 4) <= 1 else 3
                         for y in range(128) for x in range(128))
        self.assertEqual(self.codes(mask), expected)
        for x, y in ((6, 20), (14, 20), (10, 18), (10, 22)):
            self.assertEqual(expected[y * 128 + x], 205)
        self.assertEqual(expected[23 * 128 + 10], 3)
        clipped = self.generate(fields.ConditioningLayersEllipseField, center_x=0, center_y=0,
                                radius_x=1, radius_y=1)
        self.assertEqual(self.codes(clipped).count(255), 1)

    def test_linear_directions_endpoints_and_constant_rows(self):
        node = fields.ConditioningLayersLinearGradientField
        horizontal = self.generate(node)
        codes = self.codes(horizontal)
        self.assertEqual((codes[0], codes[127]), (0, 255))
        self.assertEqual(list(codes[:128]), sorted(codes[:128]))
        self.assertEqual(codes, codes[:128] * 128)
        reverse = self.generate(node, start_x=127.5, end_x=0.5)
        vertical = self.generate(node, start_x=64, end_x=64, start_y=0.5, end_y=127.5)
        self.assertTrue(self.torch.equal(horizontal.flip(2), reverse))
        self.assertTrue(self.torch.equal(horizontal.transpose(1, 2), vertical))
        diagonal = self.codes(self.generate(node, start_x=0.5, start_y=0.5, end_x=127.5, end_y=127.5))
        self.assertEqual((diagonal[0], diagonal[-1]), (0, 255))
        self.assertEqual(diagonal[10 * 128 + 30], diagonal[30 * 128 + 10])

    def test_linear_matches_exp0004_all_three_widths(self):
        for width in (8, 24, 48):
            start = 64 - width // 2
            row = tuple(255 if x < start else 0 if x >= start + width else
                        (255 * (2 * width - 2 * (x - start) - 1) + width) // (2 * width)
                        for x in range(128))
            mask = self.generate(fields.ConditioningLayersLinearGradientField,
                                 start_x=start, end_x=start + width, start_value=255, end_value=0)
            self.assertEqual(self.codes(mask), row * 128)

    def test_linear_half_up_quantization_and_equal_values(self):
        node = fields.ConditioningLayersLinearGradientField
        for start, end in ((0, 255), (255, 0), (9, 10), (10, 9)):
            mask = self.generate(node, start_x=0, end_x=1, start_value=start, end_value=end)
            self.assertEqual(self.codes(mask)[0], (start + end + 1) // 2)
            self.assertEqual(self.codes(mask)[1], end)
        self.assertEqual(set(self.codes(self.generate(node, start_value=73, end_value=73))), {73})

    def test_radial_exact_study_geometry_and_symmetry(self):
        mask = self.generate(fields.ConditioningLayersRadialGradientField)
        expected = tuple(max(0, 255 - (255 * ((2 * x - 127)**2 + (2 * y - 127)**2) + 8192) // 16384)
                         for y in range(128) for x in range(128))
        self.assertEqual(self.codes(mask), expected)
        for reflection in (mask.flip(1), mask.flip(2), mask.transpose(1, 2)):
            self.assertTrue(self.torch.equal(mask.view(self.torch.int32), reflection.view(self.torch.int32)))

    def test_radial_elliptical_extent_center_boundary_and_quantization(self):
        node = fields.ConditioningLayersRadialGradientField
        for center, outside in ((255, 0), (0, 255), (51, 180), (93, 93)):
            mask = self.generate(node, center_x=10.5, center_y=20.5, radius_x=4, radius_y=2,
                                 center_value=center, outside_value=outside)
            expected = []
            for y in range(128):
                for x in range(128):
                    distance = min(Fraction(1), Fraction((x - 10)**2, 16) + Fraction((y - 20)**2, 4))
                    loss = abs(center - outside) * distance
                    rounded = int(loss + Fraction(1, 2))
                    expected.append(center + (rounded if outside >= center else -rounded))
            self.assertEqual(self.codes(mask), tuple(expected))
            self.assertEqual(expected[20 * 128 + 10], center)
            self.assertEqual(expected[20 * 128 + 14], outside)
        # At normalized squared distance 1/2, retained loss rounds 127.5 to 128.
        mask = self.generate(node, center_x=10.5, center_y=20.5, radius_x=2, radius_y=2)
        self.assertEqual(self.codes(mask)[21 * 128 + 11], 127)

    def test_geometry_parameters_fail_closed(self):
        cases = (
            (fields.ConditioningLayersSolidField, "value", (-1, 256, True, 1.0, "1")),
            (fields.ConditioningLayersRectangleField, "width", (0, -1, 257, True, 2.5)),
            (fields.ConditioningLayersRectangleField, "height", (0, 257)),
            (fields.ConditioningLayersEllipseField, "radius_x", (0, -1, 129, float("inf"), True)),
            (fields.ConditioningLayersRadialGradientField, "radius_y", (0, 0.1, float("nan"))),
            (fields.ConditioningLayersLinearGradientField, "start_value", (-1, 256, None)),
            (fields.ConditioningLayersRectangleField, "center_x", (-0.5, 128.5, .1, True, "64", float("nan"))),
            (fields.ConditioningLayersEllipseField, "outside_value", (-1, 256, True)),
            (fields.ConditioningLayersRadialGradientField, "center_value", (-1, 256, True)),
        )
        for node, name, values in cases:
            for value in values:
                with self.subTest(node=node.__name__, name=name, value=value), self.assertRaises(ValueError):
                    self.generate(node, **{name: value})
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.generate(fields.ConditioningLayersLinearGradientField, end_x=.5)
        for codes in ((0,), (0,) * 16383 + (256,), (0,) * 16383 + (True,)):
            with self.assertRaises(ValueError):
                fields.codes_to_mask(codes)

    def test_invert_all_256_codes_both_encodings_complement_canonical_and_round_trip(self):
        torch = self.torch
        codes = tuple(range(256)) * 64
        canonical_bits = torch.tensor([round_ratio_to_binary32_bits(code, 255) for code in codes],
                                      dtype=torch.int32).reshape(FIELD_SHAPE)
        complement_bits = torch.tensor([round_ratio_to_binary32_bits(255 - code, 255) for code in codes],
                                       dtype=torch.int32).reshape(FIELD_SHAPE)
        for encoding in ("code/255", "code*256/65535"):
            with self.subTest(encoding=encoding):
                values = [round_ratio_to_binary32(code, 255) if encoding == "code/255" else
                          round_ratio_to_binary32(code * 256, 65535) for code in codes]
                mask = torch.tensor(values, dtype=torch.float32).reshape(FIELD_SHAPE)
                original_bits = mask.view(torch.int32).clone()
                inverted, = fields.ConditioningLayersInvertField().invert(mask)
                recovered, = fields.ConditioningLayersInvertField().invert(inverted)
                self.assertEqual(self.codes(inverted), tuple(255 - code for code in codes))
                self.assertEqual(self.codes(recovered), codes)
                self.assertTrue(torch.equal(inverted.view(torch.int32), complement_bits))
                self.assertTrue(torch.equal(recovered.view(torch.int32), canonical_bits))
                self.assertTrue(torch.equal(mask.view(torch.int32), original_bits))

    def test_invert_noncanonical_input_bits_need_not_survive_double_inversion(self):
        torch = self.torch
        # Both retained representations decode to code 128, but their bits differ.
        mask = torch.full(FIELD_SHAPE, round_ratio_to_binary32(128 * 256, 65535), dtype=torch.float32)
        inverted, = fields.ConditioningLayersInvertField().invert(mask)
        recovered, = fields.ConditioningLayersInvertField().invert(inverted)
        self.assertEqual(set(self.codes(inverted)), {127})
        self.assertEqual(set(self.codes(recovered)), {128})
        self.assertFalse(torch.equal(mask.view(torch.int32), recovered.view(torch.int32)))
        self.assertEqual(recovered.view(torch.int32).unique().tolist(),
                         [round_ratio_to_binary32_bits(128, 255)])

    def test_invert_representative_solid_codes_including_zero_and_full(self):
        for code in (0, 1, 2, 63, 127, 128, 173, 254, 255):
            with self.subTest(code=code):
                mask = self.generate(fields.ConditioningLayersSolidField, value=code)
                inverted, = fields.ConditioningLayersInvertField().invert(mask)
                self.assertEqual(set(self.codes(inverted)), {255 - code})

    def test_source_invert_layer_acceptance_and_canonical_double_inversion_bits(self):
        torch = self.torch
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        conditioning = [[torch.zeros((1, 3, 8)), {}]]
        sources = (
            (fields.ConditioningLayersSolidField, {"value": 173}),
            (fields.ConditioningLayersRectangleField, {}),
            (fields.ConditioningLayersEllipseField, {}),
            (fields.ConditioningLayersLinearGradientField, {}),
            (fields.ConditioningLayersRadialGradientField, {}),
        )
        for node, overrides in sources:
            with self.subTest(node=node.__name__):
                mask = self.generate(node, **overrides)
                inverted, = fields.ConditioningLayersInvertField().invert(mask)
                recovered, = fields.ConditioningLayersInvertField().invert(inverted)
                self.assertEqual(self.codes(inverted), tuple(255 - code for code in self.codes(mask)))
                self.assertTrue(torch.equal(mask.view(torch.int32), recovered.view(torch.int32)))
                for mode in ("FIXED", "BLENDED"):
                    layer, = ConditioningLayersLayer().create(conditioning, inverted, 1., mode, True, unique_id="1")
                    stack, = ConditioningLayersAddLayer().add(layer)
                    with patch.dict("sys.modules", {"comfy": comfy}):
                        result, = ConditioningLayersCompose().compose(stack)
                    self.assertIs(result[0][0], conditioning[0][0])

    def test_invert_accepts_two_d_noncontiguous_and_mixed_encoding_masks(self):
        torch = self.torch
        codes = tuple(range(256)) * 64
        values = [round_ratio_to_binary32(code, 255) if index % 2 else
                  round_ratio_to_binary32(code * 256, 65535) for index, code in enumerate(codes)]
        mask = torch.tensor(values, dtype=torch.float32).reshape(128, 128).transpose(0, 1)
        self.assertFalse(mask.is_contiguous())
        mask.requires_grad_(True)
        inverted, = fields.ConditioningLayersInvertField().invert(mask)
        expected = tuple(255 - recover_sample_code(value) for value in mask.detach().reshape(-1).tolist())
        self.assertEqual(self.codes(inverted), expected)
        self.assertFalse(inverted.requires_grad)

    def test_invert_and_layer_reject_invalid_masks_without_snapping(self):
        torch = self.torch
        good = self.generate(fields.ConditioningLayersSolidField, value=128)
        conditioning = [[torch.zeros((1, 3, 8)), {}]]
        invalid = [object(), good.tolist(), good.to(torch.float16), good.to(torch.float64),
                   good.to(torch.uint8), good[:, :64, :64], good.repeat(2, 1, 1),
                   good.reshape(-1), good.unsqueeze(0)]
        for value in (0.3, -0.1, 1.1, float("nan"), float("inf"), float("-inf")):
            mask = good.clone()
            mask[0, 0, 0] = value
            invalid.append(mask)
        off_by_one_bit = good.view(torch.int32).clone()
        off_by_one_bit[0, 0, 0] += 1
        invalid.append(off_by_one_bit.view(torch.float32))
        for index, mask in enumerate(invalid):
            with self.subTest(case=index):
                with self.assertRaises(ValueError):
                    fields.ConditioningLayersInvertField().invert(mask)
                with self.assertRaises(ValueError):
                    ConditioningLayersLayer().create(conditioning, mask, 1., "BLENDED", True, unique_id="1")

    def test_invert_full_field_still_rejected_as_empty_at_composition(self):
        torch = self.torch
        full = self.generate(fields.ConditioningLayersSolidField)
        zero, = fields.ConditioningLayersInvertField().invert(full)
        layer, = ConditioningLayersLayer().create([[torch.zeros((1, 3, 8)), {}]], zero,
                                                 1., "BLENDED", True, unique_id="1")
        stack, = ConditioningLayersAddLayer().add(layer)
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}), self.assertRaisesRegex(ValueError, "positive|empty"):
            ConditioningLayersCompose().compose(stack)

    def test_sources_accepted_by_layer_and_zero_still_rejected_at_composition(self):
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        conditioning = [[self.torch.zeros((1, 3, 8)), {}]]
        for node in (fields.ConditioningLayersSolidField, fields.ConditioningLayersRectangleField,
                     fields.ConditioningLayersEllipseField, fields.ConditioningLayersLinearGradientField,
                     fields.ConditioningLayersRadialGradientField):
            mask = self.generate(node)
            again = self.generate(node)
            self.assertEqual(self.codes(mask), self.codes(again))
            self.assertTrue(self.torch.equal(mask.view(self.torch.int32), again.view(self.torch.int32)))
            layer, = ConditioningLayersLayer().create(conditioning, mask, 1., "BLENDED", True, unique_id="1")
            stack, = ConditioningLayersAddLayer().add(layer)
            with patch.dict("sys.modules", {"comfy": comfy}):
                result, = ConditioningLayersCompose().compose(stack)
            self.assertIs(result[0][0], conditioning[0][0])
        zero = self.generate(fields.ConditioningLayersSolidField, value=0)
        layer, = ConditioningLayersLayer().create(conditioning, zero, 1., "BLENDED", True, unique_id="0")
        stack, = ConditioningLayersAddLayer().add(layer)
        with patch.dict("sys.modules", {"comfy": comfy}), self.assertRaisesRegex(ValueError, "positive|empty"):
            ConditioningLayersCompose().compose(stack)


if __name__ == "__main__":
    unittest.main()
