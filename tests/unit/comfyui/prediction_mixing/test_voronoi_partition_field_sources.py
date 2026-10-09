"""Real CPU MASKs and retained Layer consumers; fenced offline host lane."""

import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.procedural_field_sources import (
    ConditioningLayersVoronoiPartitionField, voronoi_partition_field_codes,
)
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
from test_voronoi_partition_field_codes import GOLDENS


class VoronoiPartitionSourceTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersVoronoiPartitionField()
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        host = patch.dict("sys.modules", {"comfy": comfy})
        host.start()
        self.addCleanup(host.stop)

    def masks(self, members=3):
        return self.node.generate(1, 6, 100, members, "cyclic", 0)[:members]

    def compose(self, masks, mode):
        stack = None
        for index, mask in enumerate(masks):
            layer = ConditioningLayersLayer().create(
                [[self.torch.ones((1, 2, 3)), {}]], mask, 1, mode, True, unique_id=str(index))[0]
            stack = ConditioningLayersAddLayer().add(layer, stack)[0]
        return ConditioningLayersCompose().compose(stack)[0]

    def test_mask_contract_canonical_bits_and_fresh_storage(self):
        for members in (2, 3, 4):
            args = (1, 6, 100, members, "hashed", 3)
            first, second = self.node.generate(*args), self.node.generate(*args)
            self.assertEqual(len({m.data_ptr() for m in first + second}), 8)
            for k, (mask, plane) in enumerate(zip(first, voronoi_partition_field_codes(*args))):
                self.assertEqual(mask.device.type, "cpu")
                self.assertEqual(mask.dtype, self.torch.float32)
                self.assertEqual(tuple(mask.shape), (1, 128, 128))
                self.assertFalse(mask.requires_grad)
                expected_bits = self.torch.tensor([0x3f800000 if c else 0 for c in plane],
                                                 dtype=self.torch.int32).reshape(1, 128, 128)
                self.assertTrue(self.torch.equal(mask.view(self.torch.int32), expected_bits))
                self.assertTrue(self.torch.equal(mask, second[k]))
                if k >= members:
                    self.assertFalse(bool(mask.any()))
            snapshots = tuple(m.clone() for m in first + second)
            for index, mask in enumerate(first):
                mask.fill_(.5)
                for other in range(index + 1, 8):
                    self.assertTrue(self.torch.equal((first + second)[other], snapshots[other]))

    def test_goldens_recovered_codes_match_developer_lane(self):
        for args, expected in GOLDENS:
            planes = tuple(bytes(recover_sample_code(v) for v in mask.reshape(-1).tolist())
                           for mask in self.node.generate(*args))
            self.assertEqual(hashlib.sha256(b"".join(planes)).hexdigest(), expected)
            self.assertEqual(planes, tuple(bytes(p) for p in voronoi_partition_field_codes(*args)))

    def assert_fixed_partition(self, members):
        masks = self.masks(members)
        result = self.compose(masks, "FIXED")
        self.assertEqual(len(result), members)
        for mask, entry in zip(masks, result):
            self.assertTrue(bool(mask.any()))
            self.assertTrue(self.torch.equal(mask, entry[1]["mask"]))
        self.assertTrue(self.torch.equal(sum(masks), self.torch.ones_like(masks[0])))
        self.assertTrue(self.torch.equal(sum((m > 0).int() for m in masks),
                                        self.torch.ones_like(masks[0], dtype=self.torch.int32)))

    def test_two_member_fixed_partition(self):
        self.assert_fixed_partition(2)

    def test_three_member_fixed_partition(self):
        self.assert_fixed_partition(3)

    def test_four_member_fixed_partition(self):
        self.assert_fixed_partition(4)

    def assert_blended_weights(self, masks):
        planes = [tuple(recover_sample_code(v) for v in m.reshape(-1).tolist()) for m in masks]
        totals = tuple(map(sum, zip(*planes)))
        for codes, entry in zip(planes, self.compose(masks, "BLENDED")):
            bits = [round_ratio_to_binary32_bits(c, total) if total else 0 for c, total in zip(codes, totals)]
            expected = self.torch.tensor(bits, dtype=self.torch.int32).reshape(1, 128, 128)
            self.assertTrue(self.torch.equal(entry[1]["mask"].view(self.torch.int32), expected))

    def test_blur_blended_and_fixed_overlap_rejection(self):
        masks = tuple(ConditioningLayersFieldBlur().blur(m, 3)[0] for m in self.masks())
        self.assertTrue(bool(((masks[0] > 0) & (masks[1] > 0)).any()))
        self.assert_blended_weights(masks)
        with self.assertRaisesRegex(ValueError, "overlap|FIXED"):
            self.compose(masks, "FIXED")

    def test_fade_blended_and_soft_overlap_stays_rejected(self):
        masks = tuple(ConditioningLayersFieldFade().apply(m, end_value=40)[0] for m in self.masks())
        self.assertTrue(bool(((masks[0] > 0) & (masks[0] < 1)).any()))
        self.assert_blended_weights(masks)
        # Fade alone preserves zeros. On blurred fields, it preserves overlaps.
        overlapping = tuple(ConditioningLayersFieldFade().apply(
            ConditioningLayersFieldBlur().blur(m, 3)[0], end_value=40)[0] for m in self.masks())
        self.assert_blended_weights(overlapping)
        with self.assertRaisesRegex(ValueError, "overlap|FIXED"):
            self.compose(overlapping, "FIXED")

    def assert_layer_support(self, mask):
        self.assertTrue(bool(mask.any()))
        for mode in ("FIXED", "BLENDED"):
            self.assertTrue(self.torch.equal(self.compose((mask,), mode)[0][1]["mask"],
                                            (mask > 0).float()))

    def test_remap_then_layer(self):
        mask = ConditioningLayersFieldRemap().remap(self.masks()[0], 0, 255, 0, 128)[0]
        self.assertEqual({recover_sample_code(v) for v in mask.reshape(-1).tolist()}, {0, 128})
        self.assert_layer_support(mask)

    def test_repeat_then_layer(self):
        self.assert_layer_support(ConditioningLayersFieldRepeat().repeat(self.masks()[0], 3, 2, 7, 9)[0])

    def test_transform_then_layer(self):
        self.assert_layer_support(ConditioningLayersFieldTransform().transform(
            self.masks()[0], rotation_degrees=31, offset_x=3)[0])

    def test_enabled_empty_active_and_unused_members_still_rejected(self):
        masks = self.node.generate(0, 1, 100, 3, "cyclic", 0)
        self.assert_layer_support(masks[0])
        for empty in masks[1:]:
            for mode in ("FIXED", "BLENDED"):
                with self.assertRaisesRegex(ValueError, "positive|support|empty"):
                    self.compose((empty,), mode)
                disabled = ConditioningLayersLayer().create(
                    [[self.torch.ones((1, 2, 3)), {}]], empty, 1, mode, False, unique_id="empty")[0]
                active = ConditioningLayersLayer().create(
                    [[self.torch.ones((1, 2, 3)), {}]], masks[0], 1, mode, True, unique_id="full")[0]
                stack = ConditioningLayersAddLayer().add(disabled, None)[0]
                stack = ConditioningLayersAddLayer().add(active, stack)[0]
                self.assertEqual(len(ConditioningLayersCompose().compose(stack)[0]), 1)
