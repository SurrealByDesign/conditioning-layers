"""Exact original PNG -> native MASK correspondence; offline host lane."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from conditioning_layers.comfyui import pattern_field_source as patterns
from conditioning_layers.comfyui.influence_field_sources import ConditioningLayersInvertField
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code, round_ratio_to_binary32_bits,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersLayer, ConditioningLayersAddLayer, ConditioningLayersCompose,
)


class PatternRuntimeTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.node = patterns.ConditioningLayersPatternField()

    def codes(self, mask):
        self.assertEqual(mask.dtype, self.torch.float32)
        self.assertEqual(mask.device.type, "cpu")
        self.assertEqual(tuple(mask.shape), (1, 128, 128))
        return bytes(recover_sample_code(value) for value in mask.reshape(-1).tolist())

    def test_every_original_including_checker_stripe_grids_irregular_and_all_radial_codes(self):
        for asset, checksum in patterns.pattern_registry().items():
            with self.subTest(asset=asset):
                path = patterns.REFERENCE_FIELD_ROOT / asset
                before = path.read_bytes()
                with Image.open(path) as image:
                    self.assertEqual((image.format, image.mode, image.size, image.info),
                                     ("PNG", "L", (128, 128), {}))
                    source = image.tobytes()
                mask = self.node.load(asset)[0]
                self.assertEqual(self.codes(mask), source)
                self.assertEqual(mask.view(self.torch.int32).reshape(-1).tolist(),
                                 [round_ratio_to_binary32_bits(code, 255) for code in source])
                if asset.startswith("soft-radial"):
                    self.assertEqual(set(source), set(range(256)))
                self.assertEqual(hashlib.sha256(before).hexdigest(), checksum)
                self.assertEqual(self.node.IS_CHANGED(asset), checksum)
                self.assertEqual(path.read_bytes(), before)
                # Each call owns its tensor; upstream consumers cannot alter later loads.
                mask.zero_()
                self.assertEqual(self.codes(self.node.load(asset)[0]), source)

    def test_every_inverse_is_available_and_matches_invert_field_exactly(self):
        manifest = json.loads((patterns.REFERENCE_FIELD_ROOT / "pairs.json").read_text())
        for pair in manifest["pairs"]:
            with self.subTest(pair=pair["pair_name"]):
                source = self.node.load(pair["source_filename"])[0]
                inverse = self.node.load(pair["inverse_filename"])[0]
                self.assertTrue(self.torch.equal(ConditioningLayersInvertField().invert(source)[0], inverse))
                self.assertEqual(self.codes(inverse), bytes(255 - code for code in self.codes(source)))

    def test_direct_layer_and_compose_acceptance_in_both_existing_modes(self):
        comfy = ModuleType("comfy")
        comfy.model_management = SimpleNamespace(intermediate_dtype=lambda: self.torch.float32)
        with patch.dict("sys.modules", {"comfy": comfy}):
            for asset in patterns.pattern_registry():
                for mode in ("FIXED", "BLENDED"):
                    with self.subTest(asset=asset, mode=mode):
                        mask = self.node.load(asset)[0]
                        conditioning = [[self.torch.ones((1, 2, 3)), {}]]
                        layer = ConditioningLayersLayer().create(conditioning, mask, 1.0, mode, True,
                                                                  unique_id="pattern")[0]
                        stack = ConditioningLayersAddLayer().add(layer)[0]
                        composed = ConditioningLayersCompose().compose(stack)[0]
                        self.assertIs(composed[0][0], conditioning[0][0])
                        self.assertTrue(self.torch.equal(composed[0][1]["mask"], (mask > 0).float()))

    def test_missing_invalid_and_replaced_assets_fail_without_repair(self):
        original_root = patterns.REFERENCE_FIELD_ROOT
        asset = "checkerboard-coarse.png"
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(patterns, "REFERENCE_FIELD_ROOT", Path(directory)):
            root = Path(directory)
            (root / "pairs.json").write_bytes((original_root / "pairs.json").read_bytes())
            path = root / asset
            for call in (self.node.load, self.node.IS_CHANGED):
                with self.assertRaisesRegex(ValueError, "missing or invalid asset"):
                    call(asset)
            path.write_bytes(b"not a PNG")
            with self.assertRaisesRegex(ValueError, "missing or invalid asset"):
                self.node.load(asset)
            cases = (("L", (64, 128)), ("L", (256, 128)), ("RGB", (128, 128)),
                     ("RGBA", (128, 128)), ("P", (128, 128)), ("I;16", (128, 128)),
                     ("L", (128, 128)))
            for mode, size in cases:
                with self.subTest(mode=mode, size=size):
                    Image.new(mode, size).save(path)
                    before = path.read_bytes()
                    for call in (self.node.load, self.node.IS_CHANGED):
                        with self.assertRaisesRegex(ValueError, "Pattern Field"):
                            call(asset)
                    self.assertEqual(path.read_bytes(), before)
            path.write_bytes((original_root / asset).read_bytes()[:-12])
            with self.assertRaisesRegex(ValueError, "missing or invalid asset"):
                self.node.load(asset)


if __name__ == "__main__":
    unittest.main()
