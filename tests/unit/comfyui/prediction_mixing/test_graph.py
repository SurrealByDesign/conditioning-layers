from __future__ import annotations

from dataclasses import FrozenInstanceError
import copy
import hashlib
import unittest

from conditioning_layers.adapters.prediction_mixing import (
    FieldAssetProfile,
    FieldChannelProfile,
    FieldValueKind,
    OverlapAssessment,
    translate_prediction_mixing,
)
from conditioning_layers.capabilities import PREDICTION_MIXING_CAPABILITY
from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_INVENTORY,
    CANONICAL_NODE_CLASS_NAMES,
    FieldStagingMap,
    GRAPH_FORMAT_IDENTIFIER,
    RuntimeGenerationSettings,
    fingerprint_api_graph,
    generate_prediction_mixing_workflow,
    node_id_layout,
    validate_api_graph,
)
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)


CHECKSUMS = {
    "a": "a" * 64,
    "b": "b" * 64,
    "c": "c" * 64,
    "disabled": "d" * 64,
}


def make_layer(
    layer_id: str,
    *,
    prompt: str | None = None,
    strength: float = 1.0,
    visible: bool = True,
) -> PromptLayer:
    return PromptLayer(
        layer_id=layer_id,
        name=f"Layer {layer_id}",
        prompt_text=prompt or f"Regional prompt {layer_id}",
        visible=visible,
        strength=strength,
        influence_field=InfluenceFieldAssetReference(
            relative_path=f"fields/{layer_id}.png",
            checksum=CHECKSUMS[layer_id],
        ),
    )


def make_profile(layer_id: str) -> FieldAssetProfile:
    return FieldAssetProfile(
        layer_id=layer_id,
        relative_path=f"fields/{layer_id}.png",
        checksum=CHECKSUMS[layer_id],
        width=128,
        height=128,
        channel_count=1,
        channel_profile=FieldChannelProfile.GRAYSCALE_8,
        minimum_normalized_value=0.0,
        maximum_normalized_value=1.0,
        finite_values=True,
        value_kind=FieldValueKind.BINARY,
    )


def make_plan(
    layer_ids: tuple[str, ...] = ("a", "b"),
    *,
    prompts: dict[str, str] | None = None,
    strengths: dict[str, float] | None = None,
    include_disabled: bool = True,
):
    prompts = prompts or {}
    strengths = strengths or {}
    layers = tuple(
        make_layer(
            layer_id,
            prompt=prompts.get(layer_id),
            strength=strengths.get(layer_id, 1.0),
        )
        for layer_id in layer_ids
    )
    if include_disabled:
        layers += (make_layer("disabled", visible=False),)
    document = ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="document-1",
        base_prompt="A coherent studio scene",
        layers=layers,
        selected_adapter_id=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
        adapter_settings={},
    )
    translated = translate_prediction_mixing(
        document,
        tuple(make_profile(layer_id) for layer_id in layer_ids),
        overlap_assessment=(
            OverlapAssessment.NO_OVERLAP if len(layer_ids) == 2 else None
        ),
    )
    assert translated.plan is not None, translated.errors
    return translated.plan


def make_staging(layer_ids: tuple[str, ...] = ("a", "b")) -> FieldStagingMap:
    return FieldStagingMap(
        {layer_id: f"conditioning-layers/document-1/{layer_id}.png" for layer_id in layer_ids}
    )


def generate(
    plan=None,
    *,
    seed: int = 18472639,
    prefix: str = "conditioning-layers/document-1/request-1",
    staging: FieldStagingMap | None = None,
    inventory=CANONICAL_COMFYUI_INVENTORY,
):
    plan = make_plan() if plan is None else plan
    layer_ids = tuple(item.layer_id for item in plan.active_regional_conditions)
    return generate_prediction_mixing_workflow(
        plan,
        inventory,
        RuntimeGenerationSettings(
            seed=seed,
            output_filename_prefix=prefix,
            execution_request_id="request-1",
        ),
        staging or make_staging(layer_ids),
    )


def codes(findings: tuple[object, ...]) -> set[str]:
    return {item.code for item in findings}  # type: ignore[attr-defined]


class OneLayerGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = make_plan(("a",))
        self.result = generate(self.plan)
        self.graph = self.result.artifact.to_api_graph()  # type: ignore[union-attr]

    def test_exact_builtin_node_set_and_dense_ids(self) -> None:
        self.assertTrue(self.result.generated, self.result.errors)
        self.assertEqual(set(self.graph), {str(index) for index in range(1, 12)})
        self.assertEqual(
            [node["class_type"] for node in self.graph.values()],
            [
                "UNETLoader",
                "CLIPLoader",
                "CLIPTextEncode",
                "CLIPTextEncode",
                "LoadImageMask",
                "ConditioningSetMask",
                "EmptyLatentImage",
                "KSampler",
                "VAELoader",
                "VAEDecode",
                "SaveImage",
            ],
        )
        self.assertNotIn("ConditioningCombine", {
            node["class_type"] for node in self.graph.values()
        })

    def test_prompt_field_mask_sampler_decode_and_save_contracts(self) -> None:
        ids = node_id_layout(("a",))
        condition = self.plan.active_regional_conditions[0]
        self.assertEqual(
            self.graph[ids["prompt:a"]]["inputs"]["text"],
            condition.combined_prompt_text,
        )
        self.assertEqual(
            self.graph[ids["field:a"]]["inputs"],
            {
                "image": "conditioning-layers/document-1/a.png",
                "channel": "red",
            },
        )
        self.assertEqual(
            self.graph[ids["mask:a"]]["inputs"],
            {
                "strength": 1.0,
                "set_cond_area": "default",
                "conditioning": [ids["prompt:a"], 0],
                "mask": [ids["field:a"], 0],
            },
        )
        sampler = self.graph[ids["sampler"]]["inputs"]
        self.assertEqual(sampler["positive"], [ids["mask:a"], 0])
        self.assertEqual(
            (sampler["seed"], sampler["steps"], sampler["cfg"]),
            (18472639, 8, 1.0),
        )
        self.assertEqual(
            (sampler["sampler_name"], sampler["scheduler"], sampler["denoise"]),
            ("euler", "simple", 1.0),
        )
        self.assertEqual(self.graph[ids["decode"]]["class_type"], "VAEDecode")
        self.assertEqual(self.graph[ids["save"]]["class_type"], "SaveImage")

    def test_disabled_layer_is_provenance_only(self) -> None:
        serialized = str(self.graph)
        self.assertNotIn("fields/disabled.png", serialized)
        self.assertEqual(
            self.result.artifact.provenance_inputs.disabled_layer_ids,  # type: ignore[union-attr]
            ("disabled",),
        )


class TwoLayerGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = make_plan(
            strengths={"a": 0.25, "b": 0.75},
            prompts={"a": "matte red glaze", "b": "glossy blue glaze"},
        )
        self.result = generate(self.plan)
        self.graph = self.result.artifact.to_api_graph()  # type: ignore[union-attr]
        self.ids = node_id_layout(("a", "b"))

    def test_two_layer_topology_matches_verified_contract(self) -> None:
        self.assertTrue(self.result.generated, self.result.errors)
        self.assertEqual(set(self.graph), {str(index) for index in range(1, 16)})
        class_types = [node["class_type"] for node in self.graph.values()]
        self.assertEqual(class_types.count("CLIPTextEncode"), 3)
        self.assertEqual(class_types.count("LoadImageMask"), 2)
        self.assertEqual(class_types.count("ConditioningSetMask"), 2)
        self.assertEqual(class_types.count("ConditioningCombine"), 1)
        self.assertEqual(
            self.graph[self.ids["combine"]]["inputs"],
            {
                "conditioning_1": [self.ids["mask:a"], 0],
                "conditioning_2": [self.ids["mask:b"], 0],
            },
        )

    def test_exact_strengths_prompts_and_no_global_base_prediction(self) -> None:
        conditions = {item.layer_id: item for item in self.plan.active_regional_conditions}
        for layer_id, strength in (("a", 0.25), ("b", 0.75)):
            self.assertEqual(
                self.graph[self.ids[f"mask:{layer_id}"]]["inputs"]["strength"],
                strength,
            )
            self.assertEqual(
                self.graph[self.ids[f"prompt:{layer_id}"]]["inputs"]["text"],
                conditions[layer_id].combined_prompt_text,
            )
        encoded_texts = [
            node["inputs"]["text"]
            for node in self.graph.values()
            if node["class_type"] == "CLIPTextEncode"
        ]
        self.assertEqual(encoded_texts.count("A coherent studio scene"), 0)
        self.assertEqual(encoded_texts[-1], "")
        self.assertEqual(
            self.graph[self.ids["sampler"]]["inputs"]["positive"],
            [self.ids["combine"], 0],
        )

    def test_artifact_is_immutable_and_api_copy_is_isolated(self) -> None:
        artifact = self.result.artifact
        with self.assertRaises(FrozenInstanceError):
            artifact.graph_fingerprint = "changed"  # type: ignore[union-attr,misc]
        graph_copy = artifact.to_api_graph()  # type: ignore[union-attr]
        graph_copy["1"]["inputs"]["unet_name"] = "changed"  # type: ignore[index]
        self.assertEqual(
            artifact.to_api_graph()["1"]["inputs"]["unet_name"],  # type: ignore[index,union-attr]
            CANONICAL_COMFYUI_INVENTORY.model_filename,
        )


class DeterminismAndProvenanceTests(unittest.TestCase):
    def test_identical_inputs_produce_identical_artifacts(self) -> None:
        plan = make_plan()
        first = generate(plan)
        second = generate(plan)

        self.assertEqual(first, second)
        self.assertEqual(first.artifact.to_api_graph(), second.artifact.to_api_graph())  # type: ignore[union-attr]
        self.assertEqual(len(first.artifact.graph_fingerprint), 64)  # type: ignore[union-attr]

    def test_fingerprint_changes_for_seed_prompt_strength_order_and_staging(self) -> None:
        baseline = generate(make_plan()).artifact.graph_fingerprint  # type: ignore[union-attr]
        changed = {
            generate(make_plan(), seed=9).artifact.graph_fingerprint,  # type: ignore[union-attr]
            generate(make_plan(prompts={"a": "changed"})).artifact.graph_fingerprint,  # type: ignore[union-attr]
            generate(make_plan(strengths={"a": 0.5})).artifact.graph_fingerprint,  # type: ignore[union-attr]
            generate(make_plan(("b", "a"))).artifact.graph_fingerprint,  # type: ignore[union-attr]
            generate(
                make_plan(),
                staging=FieldStagingMap(
                    {
                        "a": "conditioning-layers/changed-a.png",
                        "b": "conditioning-layers/b.png",
                    }
                ),
            ).artifact.graph_fingerprint,  # type: ignore[union-attr]
        }
        self.assertNotIn(baseline, changed)
        self.assertEqual(len(changed), 5)

    def test_fingerprint_covers_component_and_execution_values(self) -> None:
        artifact = generate(make_plan()).artifact
        graph = artifact.to_api_graph()  # type: ignore[union-attr]
        baseline = fingerprint_api_graph(graph)
        changed_model = copy.deepcopy(graph)
        changed_model["1"]["inputs"]["unet_name"] = "another.safetensors"
        changed_profile = copy.deepcopy(graph)
        changed_profile["11"]["inputs"]["width"] = 768
        changed_sampler = copy.deepcopy(graph)
        changed_sampler["12"]["inputs"]["sampler_name"] = "another"

        self.assertNotEqual(baseline, fingerprint_api_graph(changed_model))
        self.assertNotEqual(baseline, fingerprint_api_graph(changed_profile))
        self.assertNotEqual(baseline, fingerprint_api_graph(changed_sampler))

    def test_complete_provenance_and_warning_deduplication(self) -> None:
        plan = make_plan(strengths={"a": 0.0})
        result = generate(plan)
        provenance = result.artifact.provenance_inputs  # type: ignore[union-attr]

        self.assertEqual(provenance.document_id, plan.document_id)
        self.assertEqual(provenance.translation_plan_fingerprint, plan.fingerprint)
        self.assertEqual(provenance.graph_fingerprint, result.artifact.graph_fingerprint)  # type: ignore[union-attr]
        self.assertEqual(provenance.component_inventory_identifier, CANONICAL_COMFYUI_INVENTORY.inventory_identifier)
        self.assertEqual(provenance.disabled_layer_ids, ("disabled",))
        self.assertEqual(tuple(item.layer_id for item in provenance.active_layers), ("a", "b"))
        self.assertEqual(provenance.active_layers[0].requested_strength, 0.0)
        self.assertEqual(
            provenance.active_layers[0].combined_prompt_sha256,
            hashlib.sha256(
                plan.active_regional_conditions[0].combined_prompt_text.encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            provenance.active_layers[0].document_field_reference,
            "fields/a.png",
        )
        self.assertEqual(
            provenance.active_layers[0].staged_field_filename,
            "conditioning-layers/document-1/a.png",
        )
        self.assertEqual(
            len(provenance.mandatory_warning_codes),
            len(set(provenance.mandatory_warning_codes)),
        )

    def test_graph_metadata_is_profile_specific_and_minimal(self) -> None:
        artifact = generate(make_plan()).artifact
        self.assertEqual(artifact.graph_format_identifier, GRAPH_FORMAT_IDENTIFIER)  # type: ignore[union-attr]
        self.assertEqual(artifact.adapter_identifier, PREDICTION_MIXING_CAPABILITY.adapter_identifier)  # type: ignore[union-attr]
        self.assertEqual(artifact.source_translation_plan_fingerprint, make_plan().fingerprint)  # type: ignore[union-attr]
        self.assertEqual(artifact.required_host_components, CANONICAL_NODE_CLASS_NAMES)  # type: ignore[union-attr]
        for node in artifact.to_api_graph().values():  # type: ignore[union-attr]
            self.assertEqual(set(node), {"inputs", "class_type"})  # type: ignore[arg-type]


class GraphValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = make_plan()
        self.settings = RuntimeGenerationSettings(
            seed=18472639,
            output_filename_prefix="conditioning-layers/document-1/request-1",
            execution_request_id="request-1",
        )
        self.staging = make_staging()
        self.artifact = generate(self.plan).artifact

    def validate(self, graph):
        return validate_api_graph(
            graph,
            self.plan,
            CANONICAL_COMFYUI_INVENTORY,
            self.settings,
            self.staging,
        )

    def test_generated_graph_passes_integrity_validation(self) -> None:
        self.assertEqual(self.validate(self.artifact.to_api_graph()), ())  # type: ignore[union-attr]

    def test_missing_link_invalid_output_and_custom_node_fail(self) -> None:
        cases = []
        missing = self.artifact.to_api_graph()  # type: ignore[union-attr]
        missing["12"]["inputs"]["model"] = ["99", 0]  # type: ignore[index]
        cases.append(missing)
        output = self.artifact.to_api_graph()  # type: ignore[union-attr]
        output["12"]["inputs"]["model"] = ["1", 9]  # type: ignore[index]
        cases.append(output)
        custom = self.artifact.to_api_graph()  # type: ignore[union-attr]
        custom["1"]["class_type"] = "CustomModelLoader"  # type: ignore[index]
        cases.append(custom)
        for graph in cases:
            with self.subTest(graph=graph):
                self.assertTrue(
                    codes(self.validate(graph))
                    & {"workflow.graph_invalid", "workflow.node_contract"}
                )

    def test_deterministic_roles_are_unique_and_active_count_exact(self) -> None:
        layout = node_id_layout(("a", "b"))
        self.assertEqual(len(layout), len(set(layout)))
        self.assertEqual(len(layout.values()), len(set(layout.values())))
        self.assertEqual(
            sum(
                node["class_type"] == "ConditioningSetMask"
                for node in self.artifact.to_api_graph().values()  # type: ignore[union-attr]
            ),
            self.plan.active_layer_count,
        )


if __name__ == "__main__":
    unittest.main()
