"""Real CPU MASK and retained Layer/operation interoperability; offline host lane."""

from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import preset_field_source as presets
from conditioning_layers.comfyui.influence_field_sources import ConditioningLayersInvertField
from conditioning_layers.comfyui.field_transform import ConditioningLayersFieldTransform
from conditioning_layers.comfyui.field_remap import ConditioningLayersFieldRemap
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code, round_ratio_to_binary32_bits
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose)
from test_preset_field_library import LIBRARY, LABELS, png_codes


class PresetRuntimeTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = presets.ConditioningLayersPresetField()

    def codes(self, mask):
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, "cpu")
        self.assertEqual(tuple(mask.shape), (1, 128, 128))
        self.assertFalse(mask.requires_grad)
        return bytes(recover_sample_code(v) for v in mask.reshape(-1).tolist())

    def test_all_four_assets_preserve_source_codes_canonical_bits_fresh_storage(self):
        for label, asset in presets.preset_registry().items():
            with self.subTest(preset=label):
                path = LIBRARY / asset["path"]
                before = path.read_bytes()
                codes = png_codes(before)
                a, b = self.node.load(label)[0], self.node.load(label)[0]
                self.assertEqual(self.codes(a), codes)
                self.assertNotEqual(a.data_ptr(), b.data_ptr())
                self.assertEqual(a.view(self.torch.int32).reshape(-1).tolist(),
                                 [round_ratio_to_binary32_bits(c, 255) for c in codes])
                self.assertEqual(self.node.IS_CHANGED(label), asset["sha256"])
                a.zero_()
                self.assertEqual(self.codes(b), codes)
                self.assertEqual(self.codes(self.node.load(label)[0]), codes)
                self.assertEqual(path.read_bytes(), before)

    def test_exact_complement_and_invert_interoperability(self):
        for dark, light in ((LABELS[0], LABELS[1]), (LABELS[2], LABELS[3])):
            a, b = self.node.load(dark)[0], self.node.load(light)[0]
            self.assertTrue(self.torch.equal(ConditioningLayersInvertField().invert(a)[0], b))
            self.assertEqual(self.codes(b), bytes(255 - c for c in self.codes(a)))

    def accept_layer(self, mask):
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}):
            for mode in ("FIXED", "BLENDED"):
                conditioning = [[self.torch.ones((1, 2, 3)), {}]]
                layer = ConditioningLayersLayer().create(conditioning, mask, 1.0, mode, True, unique_id="preset")[0]
                result = ConditioningLayersCompose().compose(ConditioningLayersAddLayer().add(layer)[0])[0]
                self.assertIs(result[0][0], conditioning[0][0])
                self.assertTrue(self.torch.equal(result[0][1]["mask"], (mask > 0).float()))

    def test_qr_and_upc_both_polarities_direct_layer_acceptance(self):
        for label in LABELS:
            with self.subTest(preset=label):
                self.accept_layer(self.node.load(label)[0])

    def test_qr_transform_and_remap_to_layer(self):
        source = self.node.load(LABELS[0])[0]
        for params in ({"rotation_degrees": 90}, {"flip_horizontal": True}, {"offset_x": 0.5}):
            transformed = ConditioningLayersFieldTransform().transform(source, **params)[0]
            self.codes(transformed)
            self.accept_layer(transformed)
        remapped = ConditioningLayersFieldRemap().remap(source, output_low=17, output_high=230)[0]
        self.assertEqual(set(self.codes(remapped)), {17, 230})
        self.accept_layer(remapped)

    def test_upc_invert_to_layer(self):
        source = self.node.load(LABELS[2])[0]
        self.accept_layer(ConditioningLayersInvertField().invert(source)[0])


if __name__ == "__main__":
    unittest.main()
