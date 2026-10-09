from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from conditioning_layers.adapters.prediction_mixing.v2 import (
    CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
    DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
    ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
    TRANSLATION_PLAN_V2_IDENTIFIER,
    AbstractFoldStep,
    CapabilityExecutionProjection,
    CertificateIdentity,
    DocumentExecutionLayer,
    DocumentExecutionProjection,
    EvidenceIdentity,
    GraphTranslationStatus,
    LogicalEndpointKind,
    LogicalOperationKind,
    RegionalConditionPlanV2,
    TranslationPlanV2,
    TranslationStatus,
    build_capability_execution_projection,
    build_document_execution_projection,
    build_execution_profile_projection,
    build_ordered_left_fold_schedule,
    fingerprint_capability_execution_projection,
    fingerprint_document_execution_projection,
    fingerprint_logical_execution_graph,
    fingerprint_logical_edge,
    fingerprint_logical_graph_input,
    fingerprint_logical_operation,
    fingerprint_logical_output,
    fingerprint_topology_policy,
    fingerprint_translation_plan_v2,
    serialize_logical_execution_graph,
    translate_plan_to_logical_execution_graph,
    validate_logical_execution_graph,
)
from conditioning_layers.assets import FieldOrientation, FieldPolarity
from test_translation_v2 import (
    TranslationV2Case,
)


ADAPTER_IDENTIFIER = "prediction-mixing.experimental.v1"


def _plan(labels: tuple[str, ...]) -> TranslationPlanV2:
    profile = build_execution_profile_projection()
    document_layers = tuple(
        DocumentExecutionLayer(
            active_ordinal=ordinal,
            layer_id=f"layer-{label}",
            prompt_text=f"Prompt {label}",
            requested_strength=1.0 - (ordinal * 0.01),
            influence_field_reference=f"fields/{label}.png",
            declared_field_sha256=f"{ordinal + 1:064x}",
        )
        for ordinal, label in enumerate(labels)
    )
    document = DocumentExecutionProjection(
        format_identifier=DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
        format_version=1,
        source_document_major_version=1,
        source_document_minor_version=0,
        selected_adapter_identifier=ADAPTER_IDENTIFIER,
        canonical_adapter_settings_json="{}",
        base_prompt_text="Base prompt",
        active_layers=document_layers,
        fingerprint="",
    )
    document = replace(
        document,
        fingerprint=fingerprint_document_execution_projection(document),
    )
    capability = CapabilityExecutionProjection(
        format_identifier=CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
        format_version=1,
        capability_policy_identifier="prediction-mixing.capability-policy.v1",
        capability_policy_version=1,
        capability_policy_fingerprint="c" * 64,
        subject_document_projection_fingerprint=document.fingerprint,
        authoritative_adapter_identifier=ADAPTER_IDENTIFIER,
        selected_adapter_identifier=ADAPTER_IDENTIFIER,
        compatible=True,
        active_layer_count=len(labels),
        homogeneous_condition_kind=profile.homogeneous_condition_kind,
        minimum_active_layer_count=1,
        maximum_active_layer_count=max(2, len(labels)),
        decisions=(),
        accepted_constraints=(),
        fingerprint="",
    )
    capability = replace(
        capability,
        fingerprint=fingerprint_capability_execution_projection(capability),
    )
    conditions = tuple(
        RegionalConditionPlanV2(
            active_ordinal=ordinal,
            layer_id=layer.layer_id,
            regional_prompt_text=layer.prompt_text,
            combined_prompt_text=(
                document.base_prompt_text
                + profile.prompt_combination_delimiter
                + layer.prompt_text
            ),
            requested_strength=layer.requested_strength,
            library_identifier="conditioning-layers.influence-field-library",
            library_version=1,
            family_identifier=f"synthetic-{len(labels)}-field.v1",
            family_version=1,
            permutation_identifier="".join(labels),
            library_field_id=f"field-{label}",
            library_field_reference=f"fields/{label}.png",
            document_field_reference=layer.influence_field_reference,
            source_field_sha256=layer.declared_field_sha256 or "",
            width=profile.expected_field_width,
            height=profile.expected_field_height,
            encoding=profile.expected_field_encoding,
            polarity=FieldPolarity(),
            orientation=FieldOrientation(),
            effective_weight_expression=profile.effective_weight_expression,
        )
        for ordinal, (label, layer) in enumerate(zip(labels, document_layers, strict=True))
    )
    plan = TranslationPlanV2(
        contract_identifier=TRANSLATION_PLAN_V2_IDENTIFIER,
        contract_version=2,
        adapter_identifier=ADAPTER_IDENTIFIER,
        document_projection=document,
        capability_projection=capability,
        binding_identity=EvidenceIdentity(
            format_identifier="conditioning-layers.influence-field-binding.v1",
            format_version=1,
            fingerprint="a" * 64,
        ),
        certificate_identity=CertificateIdentity(
            format_identifier="conditioning-layers.field-relationship-certificate.v1",
            format_version=1,
            relationship_policy_identifier=(
                "prediction-mixing.ordered-n-way-field-relationship.v1"
            ),
            relationship_policy_version=1,
            fingerprint="b" * 64,
        ),
        execution_profile_projection=profile,
        topology_policy=ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
        regional_conditions=conditions,
        fold_schedule=build_ordered_left_fold_schedule(len(labels)),
        fingerprint="",
    )
    return _refingerprint_plan(plan)


def _refingerprint_plan(plan: TranslationPlanV2) -> TranslationPlanV2:
    value = replace(plan, fingerprint="")
    return replace(value, fingerprint=fingerprint_translation_plan_v2(value))


def _codes(result) -> set[str]:
    return {item.code for item in result.findings}


def _refingerprint_graph(graph):
    value = replace(graph, fingerprint="")
    return replace(value, fingerprint=fingerprint_logical_execution_graph(value))


def _replace_plan_execution_material(
    plan: TranslationPlanV2,
    *,
    document=None,
    conditions=None,
) -> TranslationPlanV2:
    document = document or plan.document_projection
    conditions = conditions or plan.regional_conditions
    document = replace(document, fingerprint="")
    document = replace(
        document,
        fingerprint=fingerprint_document_execution_projection(document),
    )
    capability = replace(
        plan.capability_projection,
        subject_document_projection_fingerprint=document.fingerprint,
        fingerprint="",
    )
    capability = replace(
        capability,
        fingerprint=fingerprint_capability_execution_projection(capability),
    )
    return _refingerprint_plan(
        replace(
            plan,
            document_projection=document,
            capability_projection=capability,
            regional_conditions=tuple(conditions),
        )
    )


def _semantic_variant(plan: TranslationPlanV2, mutation: str) -> TranslationPlanV2:
    layers = list(plan.document_projection.active_layers)
    conditions = list(plan.regional_conditions)
    document = plan.document_projection
    if mutation == "base_prompt":
        document = replace(document, base_prompt_text="Changed base prompt")
        conditions = [
            replace(
                condition,
                combined_prompt_text=(
                    document.base_prompt_text
                    + plan.execution_profile_projection.prompt_combination_delimiter
                    + condition.regional_prompt_text
                ),
            )
            for condition in conditions
        ]
    elif mutation == "regional_prompt":
        layers[0] = replace(layers[0], prompt_text="Changed regional prompt")
        conditions[0] = replace(
            conditions[0],
            regional_prompt_text=layers[0].prompt_text,
            combined_prompt_text=(
                document.base_prompt_text
                + plan.execution_profile_projection.prompt_combination_delimiter
                + layers[0].prompt_text
            ),
        )
    elif mutation == "strength":
        layers[0] = replace(layers[0], requested_strength=0.375)
        conditions[0] = replace(conditions[0], requested_strength=0.375)
    elif mutation == "field_sha256":
        layers[0] = replace(layers[0], declared_field_sha256="f" * 64)
        conditions[0] = replace(conditions[0], source_field_sha256="f" * 64)
    elif mutation == "polarity":
        conditions[0] = replace(
            conditions[0],
            polarity=replace(conditions[0].polarity, inverted=True),
        )
    elif mutation == "orientation":
        conditions[0] = replace(
            conditions[0],
            orientation=replace(conditions[0].orientation, rotation_degrees=90),
        )
    elif mutation == "condition_order":
        layers[0], layers[1] = layers[1], layers[0]
        conditions[0], conditions[1] = conditions[1], conditions[0]
        layers = [replace(layer, active_ordinal=index) for index, layer in enumerate(layers)]
        conditions = [
            replace(condition, active_ordinal=index)
            for index, condition in enumerate(conditions)
        ]
    else:
        raise AssertionError(f"unsupported test mutation: {mutation}")
    document = replace(document, active_layers=tuple(layers))
    return _replace_plan_execution_material(
        plan,
        document=document,
        conditions=tuple(conditions),
    )


class LogicalGraphShapeTests(unittest.TestCase):
    def test_one_condition_has_source_and_final_output_without_combine(self) -> None:
        result = translate_plan_to_logical_execution_graph(_plan(("A",)))
        self.assertEqual(result.status, GraphTranslationStatus.BUILT)
        graph = result.graph
        assert graph is not None
        self.assertEqual(len(graph.inputs), 1)
        self.assertEqual(
            tuple(item.operation_kind for item in graph.operations),
            (
                LogicalOperationKind.SOURCE_CONDITION,
                LogicalOperationKind.FINAL_OUTPUT,
            ),
        )
        self.assertEqual(len(graph.edges), 2)
        self.assertEqual(len(graph.outputs), 1)
        self.assertEqual(graph.topology.ordered_combine_operation_identifiers, ())

    def test_two_conditions_realize_one_ordered_combine(self) -> None:
        result = translate_plan_to_logical_execution_graph(_plan(("A", "B")))
        graph = result.graph
        assert graph is not None
        self.assertEqual(len(graph.operations), 4)
        combine = graph.operations[2]
        self.assertEqual(combine.operation_kind, LogicalOperationKind.COMBINE)
        self.assertEqual(
            combine.dependency_operation_identifiers,
            (
                "operation:source-condition:0",
                "operation:source-condition:1",
            ),
        )
        self.assertEqual(len(graph.edges), 5)

    def test_three_conditions_realize_an_ordered_iterative_left_fold(self) -> None:
        result = translate_plan_to_logical_execution_graph(_plan(("A", "B", "C")))
        graph = result.graph
        assert graph is not None
        combines = tuple(
            item
            for item in graph.operations
            if item.operation_kind is LogicalOperationKind.COMBINE
        )
        self.assertEqual(len(combines), 2)
        self.assertEqual(
            tuple(item.operation_identifier for item in graph.operations),
            (
                "operation:source-condition:0",
                "operation:source-condition:1",
                "operation:source-condition:2",
                "operation:combine:0",
                "operation:combine:1",
                "operation:final-output",
            ),
        )
        self.assertEqual(
            combines[1].dependency_operation_identifiers,
            ("operation:combine:0", "operation:source-condition:2"),
        )
        self.assertEqual(len(graph.edges), 8)

    def test_four_conditions_preserve_exact_condition_order(self) -> None:
        labels = ("D", "B", "A", "C")
        result = translate_plan_to_logical_execution_graph(_plan(labels))
        graph = result.graph
        assert graph is not None
        self.assertEqual(
            tuple(item.condition.layer_id for item in graph.inputs),
            tuple(f"layer-{label}" for label in labels),
        )
        self.assertEqual(
            graph.topology.ordered_combine_operation_identifiers,
            tuple(f"operation:combine:{index}" for index in range(3)),
        )
        self.assertEqual(len(graph.operations), 8)
        self.assertEqual(len(graph.edges), 11)

    def test_arbitrary_n_shape_is_iterative_and_deterministic(self) -> None:
        count = 32
        plan = _plan(tuple(f"{index:02d}" for index in range(count)))
        first = translate_plan_to_logical_execution_graph(plan)
        second = translate_plan_to_logical_execution_graph(plan)
        self.assertEqual(first, second)
        graph = first.graph
        assert graph is not None
        self.assertEqual(len(graph.inputs), count)
        self.assertEqual(len(graph.operations), 2 * count)
        self.assertEqual(len(graph.edges), (3 * count) - 1)
        self.assertEqual(
            graph.operations[-2].dependency_operation_identifiers,
            ("operation:combine:29", "operation:source-condition:31"),
        )

    def test_required_arbitrary_n_shapes_have_exact_component_counts(self) -> None:
        for count in (1, 2, 3, 4, 17, 64):
            with self.subTest(count=count):
                plan = _plan(tuple(f"field-{index}" for index in range(count)))
                result = translate_plan_to_logical_execution_graph(plan)
                self.assertEqual(result.status, GraphTranslationStatus.BUILT)
                graph = result.graph
                assert graph is not None
                self.assertEqual(len(graph.inputs), count)
                self.assertEqual(len(graph.operations), 2 * count)
                self.assertEqual(len(graph.edges), (3 * count) - 1)
                self.assertEqual(len(graph.outputs), 1)

    def test_edges_preserve_named_abstract_data_flow(self) -> None:
        graph = translate_plan_to_logical_execution_graph(
            _plan(("A", "B"))
        ).graph
        assert graph is not None
        self.assertEqual(graph.edges[0].source_kind, LogicalEndpointKind.GRAPH_INPUT)
        self.assertEqual(graph.edges[2].target_port_name, "left")
        self.assertEqual(graph.edges[3].target_port_name, "right")
        self.assertEqual(
            graph.outputs[0].source_operation_identifier,
            "operation:final-output",
        )


class RealTranslationPlanIntegrationTests(TranslationV2Case):
    def test_real_translated_two_layer_plan_builds_the_logical_graph(self) -> None:
        case = self.make_case()
        translated = self.translate(case)
        self.assertEqual(translated.status, TranslationStatus.TRANSLATED)
        plan = translated.plan
        assert plan is not None
        result = translate_plan_to_logical_execution_graph(plan)
        self.assertEqual(result.status, GraphTranslationStatus.BUILT)
        graph = result.graph
        assert graph is not None
        self.assertEqual(graph.source_plan.fingerprint, plan.fingerprint)
        self.assertEqual(len(graph.inputs), 2)
        self.assertEqual(len(graph.operations), 4)

    def test_excluded_document_metadata_does_not_change_plan_or_graph(self) -> None:
        case = self.make_case(include_disabled=True)
        baseline_translation = self.translate(case)
        baseline_plan = baseline_translation.plan
        assert baseline_plan is not None
        baseline_graph = translate_plan_to_logical_execution_graph(baseline_plan).graph
        assert baseline_graph is not None

        layers = list(case.document.layers)
        layers[0] = replace(layers[0], name="Renamed active layer")
        disabled_index = next(
            index for index, layer in enumerate(layers) if not layer.visible
        )
        layers[disabled_index] = replace(
            layers[disabled_index],
            name="Renamed disabled layer",
            prompt_text="Changed disabled content.",
            strength=0.75,
        )
        changed_document = replace(
            case.document,
            document_id="different-display-identity",
            layers=tuple(layers),
        )
        changed_projection = build_document_execution_projection(changed_document)
        changed_capability = build_capability_execution_projection(
            changed_document,
            changed_projection,
        )
        self.assertEqual(changed_projection, case.document_projection)
        self.assertEqual(changed_capability, case.capability_projection)
        changed_translation = self.translate(
            case,
            document=changed_document,
            document_projection=changed_projection,
            capability_projection=changed_capability,
        )
        self.assertEqual(changed_translation.plan, baseline_plan)
        changed_plan = changed_translation.plan
        assert changed_plan is not None
        changed_graph = translate_plan_to_logical_execution_graph(changed_plan).graph
        self.assertEqual(changed_graph, baseline_graph)

    def test_three_active_layers_are_rejected_before_graph_creation(self) -> None:
        case = self.make_case(
            family_id="three-layer.vertical-thirds.v1",
            permutation_id="ABC",
        )
        translated = self.translate(case)
        self.assertEqual(translated.status, TranslationStatus.REJECTED)
        self.assertIsNone(translated.plan)

    def test_upstream_translation_rejects_boolean_projection_alias(self) -> None:
        case = self.make_case()
        malformed = replace(
            case.document_projection,
            format_version=True,
            fingerprint="",
        )
        malformed = replace(
            malformed,
            fingerprint=fingerprint_document_execution_projection(malformed),
        )
        result = self.translate(case, document_projection=malformed)
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIsNone(result.plan)


class LogicalGraphIdentityTests(unittest.TestCase):
    def test_graph_and_every_component_have_deterministic_fingerprints(self) -> None:
        graph = translate_plan_to_logical_execution_graph(
            _plan(("A", "B", "C"))
        ).graph
        assert graph is not None
        self.assertRegex(graph.fingerprint, r"^[0-9a-f]{64}$")
        values = (
            graph.topology,
            *graph.inputs,
            *graph.operations,
            *graph.edges,
            *graph.outputs,
        )
        self.assertTrue(all(len(item.fingerprint) == 64 for item in values))
        self.assertEqual(
            graph.fingerprint,
            fingerprint_logical_execution_graph(graph),
        )
        self.assertEqual(validate_logical_execution_graph(graph), ())

    def test_execution_semantic_mutations_change_graph_identity(self) -> None:
        baseline = translate_plan_to_logical_execution_graph(
            _plan(("A", "B"))
        ).graph
        assert baseline is not None
        for labels in (("A", "C"), ("B", "A"), ("A", "B", "C")):
            with self.subTest(labels=labels):
                changed = translate_plan_to_logical_execution_graph(
                    _plan(labels)
                ).graph
                assert changed is not None
                self.assertNotEqual(changed.fingerprint, baseline.fingerprint)

    def test_every_semantic_mutation_propagates_to_edges_and_output(self) -> None:
        plan = _plan(("A", "B", "C"))
        baseline = translate_plan_to_logical_execution_graph(plan).graph
        assert baseline is not None
        baseline_combines = tuple(
            item
            for item in baseline.operations
            if item.operation_kind is LogicalOperationKind.COMBINE
        )
        for mutation in (
            "base_prompt",
            "regional_prompt",
            "strength",
            "field_sha256",
            "polarity",
            "orientation",
            "condition_order",
        ):
            with self.subTest(mutation=mutation):
                changed = translate_plan_to_logical_execution_graph(
                    _semantic_variant(plan, mutation)
                ).graph
                assert changed is not None
                changed_combines = tuple(
                    item
                    for item in changed.operations
                    if item.operation_kind is LogicalOperationKind.COMBINE
                )
                self.assertNotEqual(
                    changed.inputs[0].fingerprint,
                    baseline.inputs[0].fingerprint,
                )
                self.assertNotEqual(
                    changed.operations[0].fingerprint,
                    baseline.operations[0].fingerprint,
                )
                self.assertTrue(
                    all(
                        changed_item.fingerprint != baseline_item.fingerprint
                        for changed_item, baseline_item in zip(
                            changed_combines,
                            baseline_combines,
                            strict=True,
                        )
                    )
                )
                self.assertNotEqual(
                    tuple(item.fingerprint for item in changed.edges),
                    tuple(item.fingerprint for item in baseline.edges),
                )
                self.assertNotEqual(
                    changed.outputs[0].fingerprint,
                    baseline.outputs[0].fingerprint,
                )
                self.assertNotEqual(changed.fingerprint, baseline.fingerprint)

    def test_edge_and_output_identity_bind_semantic_sources(self) -> None:
        baseline = translate_plan_to_logical_execution_graph(
            _plan(("A", "B"))
        ).graph
        changed = translate_plan_to_logical_execution_graph(
            _semantic_variant(_plan(("A", "B")), "regional_prompt")
        ).graph
        assert baseline is not None and changed is not None
        self.assertEqual(
            baseline.edges[0].source_semantic_fingerprint,
            baseline.inputs[0].fingerprint,
        )
        self.assertEqual(
            baseline.edges[0].target_operation_fingerprint,
            baseline.operations[0].fingerprint,
        )
        self.assertEqual(
            baseline.outputs[0].source_operation_fingerprint,
            baseline.operations[-1].fingerprint,
        )
        self.assertNotEqual(
            baseline.edges[0].fingerprint,
            changed.edges[0].fingerprint,
        )
        self.assertNotEqual(
            baseline.outputs[0].fingerprint,
            changed.outputs[0].fingerprint,
        )

    def test_fresh_process_hash_seed_and_temp_directory_are_deterministic(self) -> None:
        root = Path(__file__).resolve().parents[4]
        script = """
from test_logical_graph_v2 import _plan
from conditioning_layers.adapters.prediction_mixing.v2.logical_graph import translate_plan_to_logical_execution_graph
result = translate_plan_to_logical_execution_graph(_plan(("A", "B", "C", "D")))
print(result.graph.fingerprint)
"""
        fingerprints: set[str] = set()
        for seed in ("1", "7", "101"):
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONPATH"] = os.pathsep.join(
                (str(root / "src"), str(root), str(Path(__file__).resolve().parent))
            )
            with tempfile.TemporaryDirectory() as temporary_directory:
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    cwd=temporary_directory,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            fingerprints.add(completed.stdout.strip())
        self.assertEqual(len(fingerprints), 1)

    def test_repeated_builds_in_one_process_are_identical(self) -> None:
        plan = _plan(("A", "B", "C", "D"))
        results = {
            translate_plan_to_logical_execution_graph(plan).graph.fingerprint
            for _ in range(100)
        }
        self.assertEqual(len(results), 1)

    def test_prompt_mutation_propagates_through_operation_identity_chain(self) -> None:
        plan = _plan(("A", "B", "C"))
        baseline = translate_plan_to_logical_execution_graph(plan).graph
        assert baseline is not None
        layers = list(plan.document_projection.active_layers)
        conditions = list(plan.regional_conditions)
        layers[0] = replace(layers[0], prompt_text="Changed prompt")
        conditions[0] = replace(
            conditions[0],
            regional_prompt_text="Changed prompt",
            combined_prompt_text=(
                "Base prompt"
                + plan.execution_profile_projection.prompt_combination_delimiter
                + "Changed prompt"
            ),
        )
        document = replace(
            plan.document_projection,
            active_layers=tuple(layers),
            fingerprint="",
        )
        document = replace(
            document,
            fingerprint=fingerprint_document_execution_projection(document),
        )
        capability = replace(
            plan.capability_projection,
            subject_document_projection_fingerprint=document.fingerprint,
            fingerprint="",
        )
        capability = replace(
            capability,
            fingerprint=fingerprint_capability_execution_projection(capability),
        )
        changed_plan = _refingerprint_plan(
            replace(
                plan,
                document_projection=document,
                capability_projection=capability,
                regional_conditions=tuple(conditions),
            )
        )
        changed = translate_plan_to_logical_execution_graph(changed_plan).graph
        assert changed is not None
        self.assertNotEqual(changed.inputs[0].fingerprint, baseline.inputs[0].fingerprint)
        self.assertEqual(changed.inputs[1].fingerprint, baseline.inputs[1].fingerprint)
        self.assertNotEqual(
            changed.operations[-1].fingerprint,
            baseline.operations[-1].fingerprint,
        )
        self.assertNotEqual(changed.fingerprint, baseline.fingerprint)

    def test_serialization_is_canonical_and_contains_no_comfyui_graph_details(self) -> None:
        graph = translate_plan_to_logical_execution_graph(_plan(("A", "B"))).graph
        assert graph is not None
        serialized = serialize_logical_execution_graph(graph)
        self.assertFalse(serialized.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(serialized.endswith(b"\n"))
        for forbidden in (
            b"class_type",
            b"node_id",
            b"SaveImage",
            b"KSampler",
            b"queue",
            b"output_prefix",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_strength_and_field_byte_mutations_change_graph_identity(self) -> None:
        plan = _plan(("A", "B"))
        baseline = translate_plan_to_logical_execution_graph(plan).graph
        assert baseline is not None
        layer = replace(
            plan.document_projection.active_layers[0],
            requested_strength=0.25,
        )
        condition = replace(
            plan.regional_conditions[0],
            requested_strength=0.25,
        )
        document = replace(
            plan.document_projection,
            active_layers=(layer, plan.document_projection.active_layers[1]),
            fingerprint="",
        )
        document = replace(
            document,
            fingerprint=fingerprint_document_execution_projection(document),
        )
        capability = replace(
            plan.capability_projection,
            subject_document_projection_fingerprint=document.fingerprint,
            fingerprint="",
        )
        capability = replace(
            capability,
            fingerprint=fingerprint_capability_execution_projection(capability),
        )
        strength_plan = _refingerprint_plan(
            replace(
                plan,
                document_projection=document,
                capability_projection=capability,
                regional_conditions=(condition, plan.regional_conditions[1]),
            )
        )
        field_plan = _plan(("A", "B"))
        field_layers = list(field_plan.document_projection.active_layers)
        field_conditions = list(field_plan.regional_conditions)
        field_layers[0] = replace(
            field_layers[0],
            declared_field_sha256="f" * 64,
        )
        field_conditions[0] = replace(
            field_conditions[0],
            source_field_sha256="f" * 64,
        )
        field_document = replace(
            field_plan.document_projection,
            active_layers=tuple(field_layers),
            fingerprint="",
        )
        field_document = replace(
            field_document,
            fingerprint=fingerprint_document_execution_projection(field_document),
        )
        field_capability = replace(
            field_plan.capability_projection,
            subject_document_projection_fingerprint=field_document.fingerprint,
            fingerprint="",
        )
        field_capability = replace(
            field_capability,
            fingerprint=fingerprint_capability_execution_projection(
                field_capability
            ),
        )
        field_plan = _refingerprint_plan(
            replace(
                field_plan,
                document_projection=field_document,
                capability_projection=field_capability,
                regional_conditions=tuple(field_conditions),
            )
        )
        for changed_plan in (strength_plan, field_plan):
            changed = translate_plan_to_logical_execution_graph(changed_plan).graph
            assert changed is not None
            self.assertNotEqual(changed.fingerprint, baseline.fingerprint)

    def test_contracts_are_deeply_immutable(self) -> None:
        graph = translate_plan_to_logical_execution_graph(_plan(("A",))).graph
        assert graph is not None
        with self.assertRaises(FrozenInstanceError):
            graph.fingerprint = "0" * 64  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            graph.operations[0].operation_identifier = "changed"  # type: ignore[misc]


class LogicalGraphRejectionTests(unittest.TestCase):
    def test_unsupported_translation_plan_version_is_rejected(self) -> None:
        plan = _refingerprint_plan(replace(_plan(("A",)), contract_version=3))
        result = translate_plan_to_logical_execution_graph(plan)
        self.assertEqual(result.status, GraphTranslationStatus.REJECTED)
        self.assertIsNone(result.graph)
        self.assertIn("logical_graph.unsupported_translation_plan", _codes(result))

    def test_unsupported_topology_is_rejected(self) -> None:
        plan = _plan(("A", "B"))
        topology = replace(
            plan.topology_policy,
            policy_identifier="prediction-mixing.unsupported-topology.v1",
            fingerprint="",
        )
        topology = replace(
            topology,
            fingerprint=fingerprint_topology_policy(topology),
        )
        plan = _refingerprint_plan(replace(plan, topology_policy=topology))
        result = translate_plan_to_logical_execution_graph(plan)
        self.assertEqual(result.status, GraphTranslationStatus.REJECTED)
        self.assertIsNone(result.graph)
        self.assertIn("logical_graph.unsupported_topology", _codes(result))

    def test_known_topology_name_with_changed_semantics_is_invalid(self) -> None:
        plan = _plan(("A", "B"))
        topology = replace(
            plan.topology_policy,
            balancing_permitted=True,
            fingerprint="",
        )
        topology = replace(
            topology,
            fingerprint=fingerprint_topology_policy(topology),
        )
        result = translate_plan_to_logical_execution_graph(
            _refingerprint_plan(replace(plan, topology_policy=topology))
        )
        self.assertEqual(result.status, GraphTranslationStatus.INVALID)
        self.assertIn("logical_graph.topology_contract_mismatch", _codes(result))


class LogicalGraphCanonicalTypeTests(unittest.TestCase):
    def assert_invalid_plan_type(self, plan: TranslationPlanV2) -> None:
        result = translate_plan_to_logical_execution_graph(_refingerprint_plan(plan))
        self.assertEqual(result.status, GraphTranslationStatus.INVALID)
        self.assertIsNone(result.graph)
        self.assertIn("logical_graph.canonical_type_mismatch", _codes(result))

    def assert_invalid_graph_type(self, graph) -> None:
        findings = validate_logical_execution_graph(_refingerprint_graph(graph))
        self.assertIn(
            "logical_graph.canonical_type_mismatch",
            {item.code for item in findings},
        )

    def test_plan_contract_versions_reject_boolean_and_float_aliases(self) -> None:
        for value in (True, 2.0):
            with self.subTest(value=value):
                self.assert_invalid_plan_type(
                    replace(_plan(("A",)), contract_version=value)
                )

    def test_plan_ordinals_reject_boolean_and_float_aliases(self) -> None:
        for value in (True, 1.0):
            with self.subTest(value=value):
                plan = _plan(("A", "B"))
                layers = list(plan.document_projection.active_layers)
                conditions = list(plan.regional_conditions)
                ordinal = 0 if value is True else 1
                layers[ordinal] = replace(layers[ordinal], active_ordinal=value)
                conditions[ordinal] = replace(
                    conditions[ordinal],
                    active_ordinal=value,
                )
                document = replace(
                    plan.document_projection,
                    active_layers=tuple(layers),
                    fingerprint="",
                )
                document = replace(
                    document,
                    fingerprint=fingerprint_document_execution_projection(document),
                )
                capability = replace(
                    plan.capability_projection,
                    subject_document_projection_fingerprint=document.fingerprint,
                    fingerprint="",
                )
                capability = replace(
                    capability,
                    fingerprint=fingerprint_capability_execution_projection(capability),
                )
                self.assert_invalid_plan_type(
                    replace(
                        plan,
                        document_projection=document,
                        capability_projection=capability,
                        regional_conditions=tuple(conditions),
                    )
                )

    def test_plan_count_and_fold_index_reject_boolean_aliases(self) -> None:
        plan = _plan(("A", "B"))
        capability = replace(
            plan.capability_projection,
            active_layer_count=True,
            fingerprint="",
        )
        capability = replace(
            capability,
            fingerprint=fingerprint_capability_execution_projection(capability),
        )
        self.assert_invalid_plan_type(
            replace(plan, capability_projection=capability)
        )

        step = replace(plan.fold_schedule[0], step_ordinal=True)
        self.assert_invalid_plan_type(replace(plan, fold_schedule=(step,)))

    def test_plan_rejects_list_where_tuple_is_required(self) -> None:
        plan = _plan(("A", "B"))
        self.assert_invalid_plan_type(
            replace(plan, fold_schedule=list(plan.fold_schedule))  # type: ignore[arg-type]
        )

    def test_graph_contract_input_edge_and_output_positions_reject_aliases(self) -> None:
        graph = translate_plan_to_logical_execution_graph(_plan(("A", "B"))).graph
        assert graph is not None
        for value in (True, 1.0):
            with self.subTest(field="contract_version", value=value):
                self.assert_invalid_graph_type(
                    replace(graph, contract_version=value)
                )

        for value in (True, 1.0):
            ordinal = 0 if value is True else 1
            changed_input = replace(
                graph.inputs[ordinal],
                input_ordinal=value,
                fingerprint="",
            )
            changed_input = replace(
                changed_input,
                fingerprint=fingerprint_logical_graph_input(changed_input),
            )
            with self.subTest(field="input_ordinal", value=value):
                self.assert_invalid_graph_type(
                    replace(
                        graph,
                        inputs=graph.inputs[:ordinal]
                        + (changed_input,)
                        + graph.inputs[ordinal + 1 :],
                    )
                )

        changed_edge = replace(graph.edges[0], edge_ordinal=True, fingerprint="")
        changed_edge = replace(
            changed_edge,
            fingerprint=fingerprint_logical_edge(changed_edge),
        )
        self.assert_invalid_graph_type(
            replace(graph, edges=(changed_edge,) + graph.edges[1:])
        )

        changed_output = replace(
            graph.outputs[0],
            output_ordinal=True,
            fingerprint="",
        )
        changed_output = replace(
            changed_output,
            fingerprint=fingerprint_logical_output(changed_output),
        )
        self.assert_invalid_graph_type(replace(graph, outputs=(changed_output,)))

    def test_graph_rejects_unsupported_string_enum_alias(self) -> None:
        graph = translate_plan_to_logical_execution_graph(_plan(("A",))).graph
        assert graph is not None
        operation = replace(
            graph.operations[0],
            operation_kind="source_condition",  # type: ignore[arg-type]
            fingerprint="",
        )
        operation = replace(
            operation,
            fingerprint=fingerprint_logical_operation(operation),
        )
        self.assert_invalid_graph_type(
            replace(graph, operations=(operation,) + graph.operations[1:])
        )


class LogicalGraphInvalidityTests(unittest.TestCase):
    def test_translation_plan_fingerprint_tampering_is_invalid(self) -> None:
        result = translate_plan_to_logical_execution_graph(
            replace(_plan(("A", "B")), fingerprint="0" * 64)
        )
        self.assertEqual(result.status, GraphTranslationStatus.INVALID)
        self.assertIsNone(result.graph)
        self.assertIn(
            "logical_graph.translation_plan_fingerprint_mismatch",
            _codes(result),
        )

    def test_malformed_fold_schedule_is_invalid(self) -> None:
        plan = _plan(("A", "B", "C"))
        malformed = (
            AbstractFoldStep(0, "condition:0", "condition:2", "fold:0"),
            AbstractFoldStep(1, "fold:0", "condition:1", "fold:1"),
        )
        result = translate_plan_to_logical_execution_graph(
            _refingerprint_plan(replace(plan, fold_schedule=malformed))
        )
        self.assertEqual(result.status, GraphTranslationStatus.INVALID)
        self.assertIn("logical_graph.malformed_fold_schedule", _codes(result))

    def test_every_required_fold_schedule_corruption_is_invalid(self) -> None:
        plan = _plan(("A", "B", "C", "D"))
        schedule = plan.fold_schedule
        corruptions = {
            "reordered": tuple(reversed(schedule)),
            "skipped": schedule[:-1],
            "duplicated": (schedule[0], schedule[0], schedule[2]),
            "cyclic": (replace(schedule[0], left_operand="fold:0"),) + schedule[1:],
            "incorrect_left": (
                schedule[0],
                replace(schedule[1], left_operand="condition:0"),
                schedule[2],
            ),
            "incorrect_right": (
                schedule[0],
                replace(schedule[1], right_condition="condition:3"),
                schedule[2],
            ),
            "incorrect_prior_fold": (
                schedule[0],
                replace(schedule[1], left_operand="fold:99"),
                schedule[2],
            ),
            "invalid_final_result": schedule[:-1]
            + (replace(schedule[-1], result="fold:99"),),
        }
        for name, malformed in corruptions.items():
            with self.subTest(name=name):
                result = translate_plan_to_logical_execution_graph(
                    _refingerprint_plan(replace(plan, fold_schedule=malformed))
                )
                self.assertEqual(result.status, GraphTranslationStatus.INVALID)
                self.assertIsNone(result.graph)
                self.assertIn("logical_graph.malformed_fold_schedule", _codes(result))

    def test_internal_translation_plan_mismatch_is_invalid(self) -> None:
        plan = _plan(("A", "B"))
        conditions = list(plan.regional_conditions)
        conditions[0] = replace(conditions[0], layer_id="different-layer")
        result = translate_plan_to_logical_execution_graph(
            _refingerprint_plan(
                replace(plan, regional_conditions=tuple(conditions))
            )
        )
        self.assertEqual(result.status, GraphTranslationStatus.INVALID)
        self.assertIn("logical_graph.translation_plan_mismatch", _codes(result))

    def test_invalid_identity_takes_precedence_over_unsupported_contract(self) -> None:
        plan = replace(_plan(("A",)), contract_version=3, fingerprint="0" * 64)
        result = translate_plan_to_logical_execution_graph(plan)
        self.assertEqual(result.status, GraphTranslationStatus.INVALID)
        self.assertIn("logical_graph.unsupported_translation_plan", _codes(result))

    def test_inconsistent_operation_identity_is_detected(self) -> None:
        graph = translate_plan_to_logical_execution_graph(
            _plan(("A", "B"))
        ).graph
        assert graph is not None
        operations = list(graph.operations)
        changed = replace(
            operations[0],
            operation_identifier="operation:source-condition:99",
            fingerprint="",
        )
        changed = replace(
            changed,
            fingerprint=fingerprint_logical_operation(changed),
        )
        operations[0] = changed
        graph = replace(graph, operations=tuple(operations), fingerprint="")
        graph = replace(
            graph,
            fingerprint=fingerprint_logical_execution_graph(graph),
        )
        codes = {item.code for item in validate_logical_execution_graph(graph)}
        self.assertIn("logical_graph.operation_structure_mismatch", codes)

    def test_edge_output_and_graph_fingerprint_mutations_are_detected(self) -> None:
        graph = translate_plan_to_logical_execution_graph(_plan(("A",))).graph
        assert graph is not None
        mutations = (
            replace(
                graph,
                edges=(replace(graph.edges[0], target_port_name="wrong"),)
                + graph.edges[1:],
            ),
            replace(
                graph,
                outputs=(replace(graph.outputs[0], source_port_name="wrong"),),
            ),
            replace(graph, fingerprint="0" * 64),
        )
        expected = (
            "logical_graph.edge_identity_mismatch",
            "logical_graph.output_identity_mismatch",
            "logical_graph.graph_identity_mismatch",
        )
        for mutation, code in zip(mutations, expected, strict=True):
            with self.subTest(code=code):
                self.assertIn(
                    code,
                    {item.code for item in validate_logical_execution_graph(mutation)},
                )

    def test_required_graph_corruptions_fail_closed(self) -> None:
        graph = translate_plan_to_logical_execution_graph(
            _plan(("A", "B", "C"))
        ).graph
        assert graph is not None

        duplicate_operation = replace(
            graph.operations[1],
            operation_identifier=graph.operations[0].operation_identifier,
            fingerprint="",
        )
        duplicate_operation = replace(
            duplicate_operation,
            fingerprint=fingerprint_logical_operation(duplicate_operation),
        )
        duplicate_edge = replace(
            graph.edges[1],
            edge_identifier=graph.edges[0].edge_identifier,
            fingerprint="",
        )
        duplicate_edge = replace(
            duplicate_edge,
            fingerprint=fingerprint_logical_edge(duplicate_edge),
        )
        dangling_edge = replace(
            graph.edges[0],
            target_operation_identifier="operation:missing",
            target_operation_fingerprint="0" * 64,
            fingerprint="",
        )
        dangling_edge = replace(
            dangling_edge,
            fingerprint=fingerprint_logical_edge(dangling_edge),
        )
        combine_index = next(
            index
            for index, operation in enumerate(graph.operations)
            if operation.operation_kind is LogicalOperationKind.COMBINE
        )
        cyclic_operation = replace(
            graph.operations[combine_index],
            dependency_operation_identifiers=(
                graph.operations[combine_index].operation_identifier,
                graph.operations[1].operation_identifier,
            ),
            fingerprint="",
        )
        cyclic_operation = replace(
            cyclic_operation,
            fingerprint=fingerprint_logical_operation(cyclic_operation),
        )
        nonfinal_output = replace(
            graph.outputs[0],
            source_operation_identifier=graph.operations[0].operation_identifier,
            source_operation_fingerprint=graph.operations[0].fingerprint,
            fingerprint="",
        )
        nonfinal_output = replace(
            nonfinal_output,
            fingerprint=fingerprint_logical_output(nonfinal_output),
        )
        inconsistent_edge = replace(
            graph.edges[0],
            source_semantic_fingerprint="0" * 64,
        )
        inconsistent_output = replace(
            graph.outputs[0],
            source_operation_fingerprint="0" * 64,
        )

        corruptions = {
            "reordered_operations": replace(
                graph,
                operations=(graph.operations[1], graph.operations[0])
                + graph.operations[2:],
            ),
            "reordered_edges": replace(
                graph,
                edges=(graph.edges[1], graph.edges[0]) + graph.edges[2:],
            ),
            "duplicate_operation_identifier": replace(
                graph,
                operations=(graph.operations[0], duplicate_operation)
                + graph.operations[2:],
            ),
            "duplicate_edge_identifier": replace(
                graph,
                edges=(graph.edges[0], duplicate_edge) + graph.edges[2:],
            ),
            "dangling_edge": replace(
                graph,
                edges=(dangling_edge,) + graph.edges[1:],
            ),
            "cyclic_dependency": replace(
                graph,
                operations=graph.operations[:combine_index]
                + (cyclic_operation,)
                + graph.operations[combine_index + 1 :],
            ),
            "orphan_output": replace(graph, outputs=()),
            "nonfinal_output": replace(graph, outputs=(nonfinal_output,)),
            "inconsistent_endpoint_fingerprint": replace(
                graph,
                edges=(inconsistent_edge,) + graph.edges[1:],
            ),
            "inconsistent_output_fingerprint": replace(
                graph,
                outputs=(inconsistent_output,),
            ),
        }
        for name, corruption in corruptions.items():
            with self.subTest(name=name):
                findings = validate_logical_execution_graph(
                    _refingerprint_graph(corruption)
                )
                self.assertNotEqual(findings, ())

    def test_input_and_topology_fingerprint_mutations_are_detected(self) -> None:
        graph = translate_plan_to_logical_execution_graph(_plan(("A",))).graph
        assert graph is not None
        mutations = (
            replace(
                graph,
                inputs=(replace(graph.inputs[0], fingerprint="0" * 64),),
            ),
            replace(
                graph,
                topology=replace(graph.topology, fingerprint="0" * 64),
            ),
        )
        expected = (
            "logical_graph.input_identity_mismatch",
            "logical_graph.topology_identity_mismatch",
        )
        for mutation, code in zip(mutations, expected, strict=True):
            with self.subTest(code=code):
                self.assertIn(
                    code,
                    {item.code for item in validate_logical_execution_graph(mutation)},
                )

    def test_non_plan_input_is_rejected_by_type_boundary(self) -> None:
        with self.assertRaises(TypeError):
            translate_plan_to_logical_execution_graph(object())  # type: ignore[arg-type]

    def test_rejected_and_invalid_results_never_expose_partial_graphs(self) -> None:
        rejected = translate_plan_to_logical_execution_graph(
            _refingerprint_plan(replace(_plan(("A",)), contract_version=3))
        )
        invalid = translate_plan_to_logical_execution_graph(
            replace(_plan(("A",)), fingerprint="0" * 64)
        )
        self.assertEqual(rejected.status, GraphTranslationStatus.REJECTED)
        self.assertEqual(invalid.status, GraphTranslationStatus.INVALID)
        self.assertIsNone(rejected.graph)
        self.assertIsNone(invalid.graph)


if __name__ == "__main__":
    unittest.main()
