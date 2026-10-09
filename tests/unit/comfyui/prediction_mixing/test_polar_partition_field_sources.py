"""Real CPU MASK and unchanged Layer/field-operation interoperability, offline."""

import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.procedural_field_sources import (
    ConditioningLayersPolarPartitionField, polar_partition_field_codes,
)
from conditioning_layers.comfyui.field_blur import ConditioningLayersFieldBlur
from conditioning_layers.comfyui.field_fade import ConditioningLayersFieldFade
from conditioning_layers.comfyui.field_remap import ConditioningLayersFieldRemap
from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code, round_ratio_to_binary32_bits,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose,
)
from test_polar_partition_field_codes import DEFAULTS, GOLDENS


class PolarPartitionSourceTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersPolarPartitionField()
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        host = patch.dict("sys.modules", {"comfy": comfy})
        host.start()
        self.addCleanup(host.stop)

    def masks(self, **changes):
        return self.node.generate(**{**DEFAULTS, **changes})

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
        self.codes(mask)
        for mode in ("FIXED", "BLENDED"):
            self.assertTrue(self.torch.equal(self.compose((mask,), mode)[0][1]["mask"], (mask > 0).float()))

    def test_all_outputs_contract_canonical_bits_and_fresh_storage(self):
        for members in (2, 3, 4):
            for mode in ("radial", "angular", "checker", "spiral"):
                changes = dict(members=members, assignment_mode=mode)
                first, second = self.masks(**changes), self.masks(**changes)
                self.assertEqual(len({m.data_ptr() for m in first + second}), 8)
                planes = polar_partition_field_codes(**{**DEFAULTS, **changes})
                for index, mask in enumerate(first):
                    self.assertEqual(mask.device.type, "cpu")
                    self.assertEqual(mask.dtype, self.torch.float32)
                    self.assertEqual(tuple(mask.shape), (1, 128, 128))
                    self.assertFalse(mask.requires_grad)
                    # Independent known IEEE bits: +0 and +1, no encoder self-check.
                    expected = self.torch.tensor([0x3f800000 if c else 0 for c in planes[index]],
                                                 dtype=self.torch.int32).reshape(1, 128, 128)
                    self.assertTrue(self.torch.equal(mask.view(self.torch.int32), expected))
                    self.assertTrue(self.torch.equal(mask, second[index]))
                    if index >= members:
                        self.assertFalse(bool(mask.any()))
                snapshots = tuple(m.clone() for m in first + second)
                for index, mask in enumerate(first):
                    mask.fill_(.5)
                    for other in range(index+1, 8):
                        self.assertTrue(self.torch.equal((first+second)[other], snapshots[other]))

    def test_host_goldens_match_developer_recovered_bytes(self):
        for args, digest in GOLDENS:
            planes = tuple(self.codes(mask) for mask in self.node.generate(*args))
            self.assertEqual(planes, polar_partition_field_codes(*args))
            self.assertEqual(hashlib.sha256(b"".join(bytes(p) for p in planes)).hexdigest(), digest)

    def test_host_rng_and_default_dtype_independence(self):
        import numpy
        torch_state = self.torch.random.get_rng_state()
        numpy_state = numpy.random.get_state()
        dtype = self.torch.get_default_dtype()
        expected = self.masks(assignment_mode="spiral")
        try:
            self.torch.set_default_dtype(self.torch.float64)
            for seed in (0, 42):
                self.torch.random.default_generator.manual_seed(seed)
                numpy.random.seed(seed)
                before = self.torch.random.get_rng_state()
                nb = numpy.random.get_state()
                for a, b in zip(expected, self.masks(assignment_mode="spiral")):
                    self.assertTrue(self.torch.equal(a, b))
                self.assertTrue(self.torch.equal(before, self.torch.random.get_rng_state()))
                after = numpy.random.get_state()
                self.assertTrue(numpy.array_equal(nb[1], after[1]))
                self.assertEqual(nb[2:], after[2:])
        finally:
            self.torch.random.set_rng_state(torch_state)
            numpy.random.set_state(numpy_state)
            self.torch.set_default_dtype(dtype)

    def test_polar_then_layer(self):
        self.assert_layer_support(self.masks()[0])

    def assert_fixed_partition(self, members):
        for mode in ("radial", "angular", "checker", "spiral"):
            masks = self.masks(members=members, assignment_mode=mode)[:members]
            result = self.compose(masks, "FIXED")
            self.assertEqual(len(result), members)
            for mask, entry in zip(masks, result):
                self.assertTrue(self.torch.equal(mask, entry[1]["mask"]))
            self.assertTrue(self.torch.equal(sum(masks), self.torch.ones_like(masks[0])))
            self.assertTrue(self.torch.equal(sum((m > 0).int() for m in masks),
                                            self.torch.ones_like(masks[0], dtype=self.torch.int32)))

    def test_two_member_exact_fixed_partition(self):
        self.assert_fixed_partition(2)

    def test_three_member_exclusive_exhaustive_partition(self):
        self.assert_fixed_partition(3)

    def test_four_member_exclusive_exhaustive_partition(self):
        self.assert_fixed_partition(4)

    def assert_soft_blended(self, masks, *, overlaps=True):
        self.assertTrue(any(bool(((m > 0) & (m < 1)).any()) for m in masks))
        self.assertEqual(bool(((masks[0] > 0) & (masks[1] > 0)).any()), overlaps)
        planes = tuple(self.codes(m) for m in masks)
        totals = tuple(map(sum, zip(*planes)))
        for plane, entry in zip(planes, self.compose(masks, "BLENDED")):
            bits = [round_ratio_to_binary32_bits(c, total) if total else 0
                    for c, total in zip(plane, totals)]
            expected = self.torch.tensor(bits, dtype=self.torch.int32).reshape(1, 128, 128)
            self.assertTrue(self.torch.equal(entry[1]["mask"].view(self.torch.int32), expected))
        if overlaps:
            with self.assertRaisesRegex(ValueError, "overlap|FIXED"):
                self.compose(masks, "FIXED")

    def test_blur_then_blended_and_fixed_overlap_rejection(self):
        self.assert_soft_blended(tuple(ConditioningLayersFieldBlur().blur(m, 3)[0]
                                       for m in self.masks()[:2]))

    def test_fade_then_blended_preserves_zero_support(self):
        self.assert_soft_blended(tuple(ConditioningLayersFieldFade().apply(m, end_value=40)[0]
                                       for m in self.masks()[:2]), overlaps=False)

    def test_remap_then_layer(self):
        source = self.masks()[0]
        remapped = ConditioningLayersFieldRemap().remap(source, 0, 255, 0, 128)[0]
        self.assertEqual(set(self.codes(remapped)), {0, 128})
        self.assert_layer_support(remapped)

    def test_interpolating_transform_then_layer(self):
        transformed = tuple(ConditioningLayersFieldTransform().transform(
            m, rotation_degrees=31, offset_x=3)[0] for m in self.masks()[:2])
        self.assert_layer_support(transformed[0])
        self.assert_soft_blended(transformed)

    def test_empty_active_and_unused_outputs_preserve_layer_validation(self):
        masks = self.masks(rings=1, sectors=1, members=3)
        self.assert_layer_support(masks[0])
        for empty in masks[1:]:
            for mode in ("FIXED", "BLENDED"):
                with self.assertRaisesRegex(ValueError, "positive|support|empty"):
                    self.compose((empty,), mode)
        layer = ConditioningLayersLayer().create([[self.torch.ones((1, 2, 3)), {}]],
                                                masks[0], 1, "FIXED", True, unique_id="active")[0]
        disabled = ConditioningLayersLayer().create([[self.torch.ones((1, 2, 3)), {}]],
                                                   masks[1], 1, "FIXED", False, unique_id="disabled")[0]
        stack = ConditioningLayersAddLayer().add(layer)[0]
        stack = ConditioningLayersAddLayer().add(disabled, stack)[0]
        self.assertEqual(len(ConditioningLayersCompose().compose(stack)[0]), 1)
