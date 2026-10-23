"""Real pinned Torch on CPU, in-memory host stub; no model or sampler execution."""
from dataclasses import replace
from unittest.mock import patch

import test_layer_node_runtime as runtime
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    ConditioningLayersCompose, ConditioningLayersComposeGroups, ConditioningLayersLayer, LayerMode, LayerStack,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition import compose_grouped_field_codes


class SelectiveRuntimeTests(runtime.RuntimeTestCase):
    def layers(self, groups=("a", "a", "b")):
        codes = tuple(tuple((p*(i+1)+i+1)%256 for p in range(16384)) for i in range(len(groups)))
        layers = tuple(ConditioningLayersLayer().create(self.conditioning(i), self.mask(plane),
                        (1., .5, 5e-324)[i%3], "BLENDED", True, unique_id=str(i), blend_group=group)[0]
                       for i,(plane,group) in enumerate(zip(codes,groups)))
        return layers, codes

    def test_grouped_output_structure_order_prompt_identity_and_exact_bits(self):
        layers, codes = self.layers()
        output = ConditioningLayersComposeGroups().compose(LayerStack(layers))[0]
        expected = compose_grouped_field_codes(codes, tuple(l.strength for l in layers),
                                               (LayerMode.BLENDED,)*3, tuple(l.blend_group for l in layers))
        self.assertEqual(self.bits(output), expected)
        for layer,(prompt,metadata) in zip(layers,output):
            self.assertIs(prompt, layer.conditioning[0][0])
            self.assertIs(metadata["pooled_output"],layer.conditioning[0][1]["pooled_output"])
            self.assertEqual((metadata["mask_strength"],metadata["set_area_to_bounds"]),(1.,False))
            self.assertEqual((metadata["mask"].dtype,metadata["mask"].device.type,tuple(metadata["mask"].shape)),
                             (self.torch.float32,"cpu",(1,128,128)))
            self.assertNotIn("mask",layer.conditioning[0][1])

    def test_missing_and_single_group_equal_legacy_conditioning(self):
        for groups in (("",)*3,("one",)*3):
            layers,_ = self.layers(groups)
            legacy = LayerStack(tuple(replace(l,blend_group="") for l in layers))
            self.assertSameConditioning(ConditioningLayersComposeGroups().compose(LayerStack(layers))[0],
                                        ConditioningLayersCompose().compose(legacy)[0])

    def test_legacy_rejects_explicit_membership_even_disabled_or_fixed(self):
        layers,_ = self.layers()
        for layer in (layers[0], replace(layers[0],enabled=False), replace(layers[0],mode=LayerMode.FIXED)):
            with self.assertRaisesRegex(ValueError,"Compose Blend Groups"):
                ConditioningLayersCompose().compose(LayerStack((layer,)))

    def test_disabled_never_reads_tensors_and_duplicates_fail(self):
        layers,_ = self.layers()
        disabled = replace(layers[0],layer_id="off",enabled=False,conditioning=object(),mask=object())
        node = ConditioningLayersComposeGroups()
        self.assertSameConditioning(node.compose(LayerStack(layers+(disabled,)))[0],node.compose(LayerStack(layers))[0])
        with self.assertRaises(ValueError):
            LayerStack(layers+(replace(layers[0],blend_group="elsewhere"),))
        with self.assertRaisesRegex(ValueError,"no enabled layer"):
            node.compose(LayerStack((disabled,)))

    def test_fixed_zero_suppresses_all_groups_and_conflict_is_global(self):
        layers,_ = self.layers()
        fixed = replace(layers[0],layer_id="fixed",mask=self.mask((255,)*16384),mode=LayerMode.FIXED,strength=0.)
        node = ConditioningLayersComposeGroups()
        output = node.compose(LayerStack(layers+(fixed,)))[0]
        self.assertTrue(all(not any(row) for row in self.bits(output)))
        with self.assertRaisesRegex(ValueError,"fixed.*other"):
            node.compose(LayerStack(layers+(fixed,replace(fixed,layer_id="other",blend_group="other"))))

    def test_plain_conditioning_and_dtype_validation_are_shared(self):
        layers,_ = self.layers()
        for key in ("mask", "hooks", "area", "start_percent", "control"):
            bad = replace(layers[0],conditioning=self.conditioning(0,**{key:object()}))
            with self.assertRaisesRegex(ValueError,"unsupported conditioning"):
                ConditioningLayersComposeGroups().compose(LayerStack((bad,)+layers[1:]))
        self.intermediate = self.torch.float16
        with self.assertRaisesRegex(ValueError,"binary32"):
            ConditioningLayersComposeGroups().compose(LayerStack(layers))

    def test_group_import_failure_does_not_affect_legacy_execution(self):
        layers,_ = self.layers(("",)*3)
        with patch.dict("sys.modules", {"conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition":None}):
            self.assertEqual(len(ConditioningLayersCompose().compose(LayerStack(layers))[0]),3)
