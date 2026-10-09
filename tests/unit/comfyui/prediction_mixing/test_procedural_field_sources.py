"""Real CPU tensor and Layer interoperability; host lane, no running host."""

import hashlib
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.procedural_field_sources import ConditioningLayersScatterField, scatter_field_codes
from conditioning_layers.comfyui.influence_field_sources import (
    codes_to_mask, ConditioningLayersInvertField, ConditioningLayersSolidField,
)
from conditioning_layers.comfyui.field_blur import ConditioningLayersFieldBlur
from conditioning_layers.comfyui.field_repeat import ConditioningLayersFieldRepeat
from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui.field_remap import ConditioningLayersFieldRemap
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code, round_ratio_to_binary32_bits,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose,
)
from test_scatter_field_codes import GOLDENS, DEFAULTS


class ProceduralSourceTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = ConditioningLayersScatterField()
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: torch.float32)
        self.host = patch.dict("sys.modules", {"comfy": comfy})
        self.host.start()
        self.addCleanup(self.host.stop)

    def compose(self, masks, modes):
        stack = None
        for index, (mask, mode) in enumerate(zip(masks, modes)):
            conditioning = [[self.torch.ones((1, 2, 3)), {}]]
            layer = ConditioningLayersLayer().create(conditioning, mask, 1, mode, True,
                                                    unique_id=str(index))[0]
            stack = ConditioningLayersAddLayer().add(layer, stack)[0]
        return ConditioningLayersCompose().compose(stack)[0]

    def test_mask_contract_exact_bits_and_fresh_storage(self):
        first = self.node.generate(**DEFAULTS)[0]
        second = self.node.generate(**DEFAULTS)[0]
        self.assertEqual(first.dtype, self.torch.float32)
        self.assertEqual(first.device.type, "cpu")
        self.assertEqual(tuple(first.shape), (1, 128, 128))
        self.assertFalse(first.requires_grad)
        expected = codes_to_mask(scatter_field_codes(**DEFAULTS))
        self.assertTrue(self.torch.equal(first.view(self.torch.int32), expected.view(self.torch.int32)))
        self.assertNotEqual(first.data_ptr(), second.data_ptr())
        first.zero_()
        self.assertTrue(self.torch.equal(second, expected))

    def test_host_and_developer_golden_hashes_identical(self):
        for args, expected in GOLDENS:
            mask = self.node.generate(*args)[0]
            codes = bytes(recover_sample_code(v) for v in mask.reshape(-1).tolist())
            self.assertEqual(hashlib.sha256(codes).hexdigest(), expected)
            self.assertEqual(codes, bytes(scatter_field_codes(*args)))

    def test_scatter_and_invert_fixed_disjoint_full_coverage(self):
        mask = self.node.generate(**DEFAULTS)[0]
        inverse = ConditioningLayersInvertField().invert(mask)[0]
        result = self.compose((mask, inverse), ("FIXED", "FIXED"))
        weights = [entry[1]["mask"] for entry in result]
        self.assertEqual(len(weights), 2)
        self.assertTrue(self.torch.equal(weights[0], mask))
        self.assertTrue(self.torch.equal(weights[1], inverse))
        self.assertFalse(bool((weights[0] * weights[1]).any()))
        self.assertTrue(self.torch.equal(weights[0] + weights[1], self.torch.ones_like(mask)))

    def test_scatter_blur_and_solid_blended(self):
        soft = ConditioningLayersFieldBlur().blur(self.node.generate(**DEFAULTS)[0], 3)[0]
        solid = ConditioningLayersSolidField().generate(255)[0]
        result = self.compose((soft, solid), ("BLENDED", "BLENDED"))
        first, second = (entry[1]["mask"] for entry in result)
        self.assertTrue(bool(((soft > 0) & (soft < 1)).any()))
        codes = [recover_sample_code(v) for v in soft.reshape(-1).tolist()]
        for actual, solid_branch in ((first, False), (second, True)):
            bits = [round_ratio_to_binary32_bits(255 if solid_branch else c, c + 255) for c in codes]
            expected = self.torch.tensor(bits, dtype=self.torch.int32).reshape(1, 128, 128)
            self.assertTrue(self.torch.equal(actual.view(self.torch.int32), expected))

    def test_scatter_repeat_transform_layer(self):
        source = self.node.generate(**DEFAULTS)[0]
        repeated = ConditioningLayersFieldRepeat().repeat(source, 2, 3, 7, -4)[0]
        transformed = ConditioningLayersFieldTransform().transform(repeated, rotation_degrees=90, offset_x=3)[0]
        for mode in ("FIXED", "BLENDED"):
            result = self.compose((transformed,), (mode,))
            self.assertTrue(self.torch.equal(result[0][1]["mask"], (transformed > 0).float()))

    def test_scatter_remap_layer(self):
        source = self.node.generate(**DEFAULTS)[0]
        remapped = ConditioningLayersFieldRemap().remap(source, 0, 255, 0, 128)[0]
        self.assertEqual({recover_sample_code(v) for v in remapped.reshape(-1).tolist()}, {0, 128})
        for mode in ("FIXED", "BLENDED"):
            result = self.compose((remapped,), (mode,))
            self.assertTrue(self.torch.equal(result[0][1]["mask"], source))

    def test_density_zero_enabled_layer_rejected(self):
        empty = self.node.generate(**{**DEFAULTS, "density_percent": 0})[0]
        self.assertFalse(bool(empty.any()))
        for mode in ("FIXED", "BLENDED"):
            with self.assertRaisesRegex(ValueError, "positive|support|empty"):
                self.compose((empty,), (mode,))


if __name__ == "__main__":
    unittest.main()
