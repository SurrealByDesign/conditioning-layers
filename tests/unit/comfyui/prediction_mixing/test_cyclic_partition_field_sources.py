"""Real CPU MASK and Layer interoperability; offline host lane."""

import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.procedural_field_sources import (
    ConditioningLayersCyclicPartitionField, cyclic_partition_field_codes,
)
from conditioning_layers.comfyui.influence_field_sources import codes_to_mask
from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui.field_remap import ConditioningLayersFieldRemap
from conditioning_layers.comfyui.field_blur import ConditioningLayersFieldBlur
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code, round_ratio_to_binary32_bits,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose,
)
from test_cyclic_partition_field_codes import GOLDENS


class CyclicPartitionSourceTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersCyclicPartitionField()
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        host = patch.dict("sys.modules", {"comfy": comfy})
        host.start()
        self.addCleanup(host.stop)

    def compose(self, masks, modes):
        stack = None
        for index, (mask, mode) in enumerate(zip(masks, modes)):
            conditioning = [[self.torch.ones((1, 2, 3)), {}]]
            layer = ConditioningLayersLayer().create(conditioning, mask, 1, mode, True,
                                                    unique_id=str(index))[0]
            stack = ConditioningLayersAddLayer().add(layer, stack)[0]
        return ConditioningLayersCompose().compose(stack)[0]

    def test_all_outputs_mask_contract_bits_and_fresh_storage(self):
        for members in (2, 3, 4):
            first = self.node.generate(7, 5, members, 3)
            second = self.node.generate(7, 5, members, 3)
            self.assertEqual(len({m.data_ptr() for m in first + second}), 8)
            codes = cyclic_partition_field_codes(7, 5, members, 3)
            for index, mask in enumerate(first):
                self.assertEqual(mask.device.type, "cpu")
                self.assertEqual(mask.dtype, self.torch.float32)
                self.assertEqual(tuple(mask.shape), (1, 128, 128))
                self.assertFalse(mask.requires_grad)
                expected = codes_to_mask(codes[index])
                self.assertTrue(self.torch.equal(mask.view(self.torch.int32), expected.view(self.torch.int32)))
                self.assertTrue(self.torch.equal(mask, second[index]))
                if index >= members:
                    self.assertFalse(bool(mask.any()))
            snapshots = tuple(m.clone() for m in first + second)
            for index, mask in enumerate(first):
                mask.fill_(0.5)
                for other in range(index + 1, 8):
                    self.assertTrue(self.torch.equal((first + second)[other], snapshots[other]))

    def test_host_golden_hashes_match_pure_codes(self):
        for args, expected in GOLDENS:
            planes = tuple(bytes(recover_sample_code(v) for v in m.reshape(-1).tolist())
                           for m in self.node.generate(*args))
            self.assertEqual(hashlib.sha256(b"".join(planes)).hexdigest(), expected)
            self.assertEqual(planes, tuple(bytes(p) for p in cyclic_partition_field_codes(*args)))

    def assert_partition_composes(self, members):
        masks = self.node.generate(8, 8, members, 1)[:members]
        result = self.compose(masks, ("FIXED",) * members)
        self.assertEqual(len(result), members)
        weights = [entry[1]["mask"] for entry in result]
        for mask, weight in zip(masks, weights):
            self.assertTrue(self.torch.equal(mask, weight))
        self.assertTrue(self.torch.equal(sum(weights), self.torch.ones_like(masks[0])))
        self.assertTrue(self.torch.equal(sum((m > 0).int() for m in masks),
                                        self.torch.ones_like(masks[0], dtype=self.torch.int32)))

    def test_two_member_full_fixed_partition(self):
        self.assert_partition_composes(2)

    def test_three_member_full_fixed_partition_without_remainder(self):
        self.assert_partition_composes(3)

    def test_four_member_full_fixed_partition(self):
        self.assert_partition_composes(4)

    def test_existing_blended_and_mixed_modes_preserved(self):
        masks = self.node.generate(8, 8, 3, 1)[:3]
        for modes in (("BLENDED",) * 3, ("FIXED", "BLENDED", "BLENDED")):
            for mask, entry in zip(masks, self.compose(masks, modes)):
                self.assertTrue(self.torch.equal(mask, entry[1]["mask"]))

    def test_transform_then_layer(self):
        source = self.node.generate(7, 5, 3, 2)[0]
        transformed = ConditioningLayersFieldTransform().transform(source, rotation_degrees=90,
                                                                  offset_x=3)[0]
        for mode in ("FIXED", "BLENDED"):
            result = self.compose((transformed,), (mode,))
            self.assertTrue(self.torch.equal(result[0][1]["mask"], (transformed > 0).float()))

    def test_remap_then_layer(self):
        source = self.node.generate(7, 5, 3, 2)[0]
        remapped = ConditioningLayersFieldRemap().remap(source, 0, 255, 0, 128)[0]
        self.assertEqual({recover_sample_code(v) for v in remapped.reshape(-1).tolist()}, {0, 128})
        for mode in ("FIXED", "BLENDED"):
            result = self.compose((remapped,), (mode,))
            self.assertTrue(self.torch.equal(result[0][1]["mask"], source))

    def test_blur_then_blended_exact_weights_and_fixed_overlap_rejection(self):
        soft = tuple(ConditioningLayersFieldBlur().blur(mask, 3)[0]
                     for mask in self.node.generate(8, 8, 3, 1)[:3])
        self.assertTrue(any(bool(((m > 0) & (m < 1)).any()) for m in soft))
        self.assertTrue(bool(((soft[0] > 0) & (soft[1] > 0)).any()))
        codes = [tuple(recover_sample_code(v) for v in m.reshape(-1).tolist()) for m in soft]
        totals = tuple(map(sum, zip(*codes)))
        result = self.compose(soft, ("BLENDED",) * 3)
        for plane, entry in zip(codes, result):
            bits = [round_ratio_to_binary32_bits(code, total) if total else 0
                    for code, total in zip(plane, totals)]
            expected = self.torch.tensor(bits, dtype=self.torch.int32).reshape(1, 128, 128)
            self.assertTrue(self.torch.equal(entry[1]["mask"].view(self.torch.int32), expected))
        with self.assertRaisesRegex(ValueError, "overlap|FIXED"):
            self.compose(soft, ("FIXED",) * 3)

    def test_empty_active_and_unused_outputs_preserve_layer_rejection(self):
        masks = self.node.generate(1, 1, 3, 1)
        self.assertTrue(self.torch.equal(self.compose(masks[:1], ("FIXED",))[0][1]["mask"], masks[0]))
        for empty in masks[1:]:
            for mode in ("FIXED", "BLENDED"):
                with self.assertRaisesRegex(ValueError, "positive|support|empty"):
                    self.compose((empty,), (mode,))


if __name__ == "__main__":
    unittest.main()
