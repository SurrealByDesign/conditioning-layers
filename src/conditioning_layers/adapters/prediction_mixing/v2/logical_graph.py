"""Deterministic logical graph realization for Translation Plan v2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import re

from .canonical import CanonicalizationError, canonical_json_bytes
from .identity import (
    exact_contract_equal,
    fingerprint_capability_execution_projection,
    fingerprint_document_execution_projection,
    fingerprint_execution_profile_projection,
    fingerprint_translation_plan_v2,
    fingerprint_without_field,
)
from .logical_graph_models import (
    GRAPH_TRANSLATION_ENGINE_IDENTIFIER,
    GRAPH_TRANSLATION_ENGINE_VERSION,
    LOGICAL_EDGE_IDENTIFIER,
    LOGICAL_EDGE_VERSION,
    LOGICAL_EXECUTION_GRAPH_IDENTIFIER,
    LOGICAL_EXECUTION_GRAPH_VERSION,
    LOGICAL_OUTPUT_IDENTIFIER,
    LOGICAL_OUTPUT_VERSION,
    GraphTranslationFinding,
    GraphTranslationResult,
    GraphTranslationStatus,
    LogicalEdge,
    LogicalEndpointKind,
    LogicalExecutionGraph,
    LogicalGraphInput,
    LogicalGraphOutput,
    LogicalGraphTopology,
    LogicalOperation,
    LogicalOperationKind,
    TranslationPlanReference,
)
from .models import (
    CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
    CAPABILITY_EXECUTION_PROJECTION_VERSION,
    DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
    DOCUMENT_EXECUTION_PROJECTION_VERSION,
    EXECUTION_PROFILE_PROJECTION_IDENTIFIER,
    EXECUTION_PROFILE_PROJECTION_VERSION,
    TOPOLOGY_POLICY_IDENTIFIER,
    TOPOLOGY_POLICY_VERSION,
    TRANSLATION_PLAN_V2_IDENTIFIER,
    TRANSLATION_PLAN_V2_VERSION,
    AbstractFoldStep,
    CapabilityDecision,
    CapabilityExecutionProjection,
    CertificateIdentity,
    DocumentExecutionLayer,
    DocumentExecutionProjection,
    EvidenceIdentity,
    ExecutionProfileProjection,
    OrderedLeftFoldTopologyPolicy,
    RegionalConditionPlanV2,
    TranslationPlanV2,
)
from .topology import (
    ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
    build_ordered_left_fold_schedule,
    fingerprint_topology_policy,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CONDITION_PORT = "condition"
_LEFT_PORT = "left"
_RIGHT_PORT = "right"


def translate_plan_to_logical_execution_graph(
    plan: TranslationPlanV2,
) -> GraphTranslationResult:
    """Validate one v2 plan and realize its ordered logical data flow."""

    if not isinstance(plan, TranslationPlanV2):
        raise TypeError("plan must be a TranslationPlanV2")

    invalid: list[GraphTranslationFinding] = []
    rejected: list[GraphTranslationFinding] = []
    _validate_translation_plan(plan, invalid, rejected)
    if invalid:
        return _result(GraphTranslationStatus.INVALID, None, invalid + rejected)
    if rejected:
        return _result(GraphTranslationStatus.REJECTED, None, rejected)

    inputs = tuple(
        _graph_input(ordinal, condition)
        for ordinal, condition in enumerate(plan.regional_conditions)
    )
    operations = _operations(inputs)
    topology = _topology(plan, operations)
    edges = _edges(inputs, operations)
    outputs = _outputs(operations)
    graph = LogicalExecutionGraph(
        contract_identifier=LOGICAL_EXECUTION_GRAPH_IDENTIFIER,
        contract_version=LOGICAL_EXECUTION_GRAPH_VERSION,
        translation_engine_identifier=GRAPH_TRANSLATION_ENGINE_IDENTIFIER,
        translation_engine_version=GRAPH_TRANSLATION_ENGINE_VERSION,
        adapter_identifier=plan.adapter_identifier,
        source_plan=TranslationPlanReference(
            contract_identifier=plan.contract_identifier,
            contract_version=plan.contract_version,
            fingerprint=plan.fingerprint,
        ),
        topology=topology,
        inputs=inputs,
        operations=operations,
        edges=edges,
        outputs=outputs,
        fingerprint="",
    )
    graph = replace(graph, fingerprint=fingerprint_logical_execution_graph(graph))
    findings = validate_logical_execution_graph(graph)
    if findings:
        return _result(GraphTranslationStatus.INVALID, None, list(findings))
    return _result(GraphTranslationStatus.BUILT, graph, [])


def serialize_logical_execution_graph(graph: LogicalExecutionGraph) -> bytes:
    """Return canonical identity bytes for a complete logical graph."""

    if not isinstance(graph, LogicalExecutionGraph):
        raise TypeError("graph must be a LogicalExecutionGraph")
    return canonical_json_bytes(graph)


def fingerprint_logical_execution_graph(graph: LogicalExecutionGraph) -> str:
    """Fingerprint the complete graph except its recorded fingerprint."""

    if not isinstance(graph, LogicalExecutionGraph):
        raise TypeError("graph must be a LogicalExecutionGraph")
    return _fingerprint_without_field(graph)


def fingerprint_logical_graph_input(value: LogicalGraphInput) -> str:
    """Fingerprint one logical input and its exact regional condition."""

    if not isinstance(value, LogicalGraphInput):
        raise TypeError("value must be a LogicalGraphInput")
    return _fingerprint_without_field(value)


def fingerprint_logical_operation(value: LogicalOperation) -> str:
    """Fingerprint one semantic operation and its semantic dependencies."""

    if not isinstance(value, LogicalOperation):
        raise TypeError("value must be a LogicalOperation")
    return _fingerprint_without_field(value)


def fingerprint_logical_edge(value: LogicalEdge) -> str:
    """Fingerprint one logical edge."""

    if not isinstance(value, LogicalEdge):
        raise TypeError("value must be a LogicalEdge")
    return _fingerprint_without_field(value)


def fingerprint_logical_output(value: LogicalGraphOutput) -> str:
    """Fingerprint one graph output."""

    if not isinstance(value, LogicalGraphOutput):
        raise TypeError("value must be a LogicalGraphOutput")
    return _fingerprint_without_field(value)


def fingerprint_logical_topology(value: LogicalGraphTopology) -> str:
    """Fingerprint one realized topology."""

    if not isinstance(value, LogicalGraphTopology):
        raise TypeError("value must be a LogicalGraphTopology")
    return _fingerprint_without_field(value)


def validate_logical_execution_graph(
    graph: LogicalExecutionGraph,
) -> tuple[GraphTranslationFinding, ...]:
    """Fail closed on any mutation or inconsistent logical identity."""

    if not isinstance(graph, LogicalExecutionGraph):
        raise TypeError("graph must be a LogicalExecutionGraph")
    findings: list[GraphTranslationFinding] = []
    _validate_logical_graph_canonical_types(graph, findings)
    if findings:
        expected_fingerprint = _safe_fingerprint(
            fingerprint_logical_execution_graph,
            graph,
        )
        if expected_fingerprint is None or graph.fingerprint != expected_fingerprint:
            findings.append(
                _finding(
                    "logical_graph.graph_identity_mismatch",
                    "The logical graph fingerprint is invalid.",
                    "fingerprint",
                )
            )
        return _deduplicate(findings)
    if (
        graph.contract_identifier != LOGICAL_EXECUTION_GRAPH_IDENTIFIER
        or graph.contract_version != LOGICAL_EXECUTION_GRAPH_VERSION
    ):
        findings.append(
            _finding(
                "logical_graph.contract_mismatch",
                "The logical graph contract is unsupported.",
                "contract_identifier",
            )
        )
    if (
        graph.translation_engine_identifier
        != GRAPH_TRANSLATION_ENGINE_IDENTIFIER
        or graph.translation_engine_version != GRAPH_TRANSLATION_ENGINE_VERSION
    ):
        findings.append(
            _finding(
                "logical_graph.engine_mismatch",
                "The graph translation engine identity is unsupported.",
                "translation_engine_identifier",
            )
        )
    if (
        graph.source_plan.contract_identifier != TRANSLATION_PLAN_V2_IDENTIFIER
        or graph.source_plan.contract_version != TRANSLATION_PLAN_V2_VERSION
        or not _valid_sha256(graph.source_plan.fingerprint)
    ):
        findings.append(
            _finding(
                "logical_graph.source_plan_mismatch",
                "The source Translation Plan identity is invalid.",
                "source_plan",
            )
        )

    for ordinal, value in enumerate(graph.inputs):
        if value.fingerprint != fingerprint_logical_graph_input(value):
            findings.append(
                _finding(
                    "logical_graph.input_identity_mismatch",
                    "A logical input fingerprint is invalid.",
                    f"inputs[{ordinal}].fingerprint",
                )
            )
        if (
            value.input_identifier != f"input:condition:{ordinal}"
            or value.input_ordinal != ordinal
            or value.condition.active_ordinal != ordinal
        ):
            findings.append(
                _finding(
                    "logical_graph.input_structure_mismatch",
                    "A logical input identity or ordinal is inconsistent.",
                    f"inputs[{ordinal}]",
                )
            )
    for ordinal, value in enumerate(graph.operations):
        if value.fingerprint != fingerprint_logical_operation(value):
            findings.append(
                _finding(
                    "logical_graph.operation_identity_mismatch",
                    "A logical operation fingerprint is invalid.",
                    f"operations[{ordinal}].fingerprint",
                )
            )
    for ordinal, value in enumerate(graph.edges):
        if value.fingerprint != fingerprint_logical_edge(value):
            findings.append(
                _finding(
                    "logical_graph.edge_identity_mismatch",
                    "A logical edge fingerprint is invalid.",
                    f"edges[{ordinal}].fingerprint",
                )
            )
    for ordinal, value in enumerate(graph.outputs):
        if value.fingerprint != fingerprint_logical_output(value):
            findings.append(
                _finding(
                    "logical_graph.output_identity_mismatch",
                    "A logical output fingerprint is invalid.",
                    f"outputs[{ordinal}].fingerprint",
                )
            )
    if graph.topology.fingerprint != fingerprint_logical_topology(graph.topology):
        findings.append(
            _finding(
                "logical_graph.topology_identity_mismatch",
                "The realized topology fingerprint is invalid.",
                "topology.fingerprint",
            )
        )
    if (
        graph.topology.policy_identifier != TOPOLOGY_POLICY_IDENTIFIER
        or graph.topology.policy_version != TOPOLOGY_POLICY_VERSION
        or graph.topology.policy_fingerprint
        != ORDERED_LEFT_FOLD_TOPOLOGY_POLICY.fingerprint
    ):
        findings.append(
            _finding(
                "logical_graph.unsupported_topology",
                "The realized topology policy is unsupported.",
                "topology.policy_identifier",
            )
        )

    if not graph.inputs:
        findings.append(
            _finding(
                "logical_graph.no_conditions",
                "A logical execution graph requires at least one condition.",
                "inputs",
            )
        )
    elif not findings:
        expected_operations = _operations(graph.inputs)
        expected_topology = _topology_from_policy_fields(
            graph.topology.policy_identifier,
            graph.topology.policy_version,
            graph.topology.policy_fingerprint,
            expected_operations,
        )
        expected_edges = _edges(graph.inputs, expected_operations)
        expected_outputs = _outputs(expected_operations)
        if not exact_contract_equal(graph.operations, expected_operations):
            findings.append(
                _finding(
                    "logical_graph.operation_structure_mismatch",
                    "Logical operations do not match the deterministic topology.",
                    "operations",
                )
            )
        if not exact_contract_equal(graph.topology, expected_topology):
            findings.append(
                _finding(
                    "logical_graph.topology_structure_mismatch",
                    "The realized topology does not match its logical operations.",
                    "topology",
                )
            )
        if not exact_contract_equal(graph.edges, expected_edges):
            findings.append(
                _finding(
                    "logical_graph.edge_structure_mismatch",
                    "Logical edges do not match the deterministic data flow.",
                    "edges",
                )
            )
        if not exact_contract_equal(graph.outputs, expected_outputs):
            findings.append(
                _finding(
                    "logical_graph.output_structure_mismatch",
                    "Logical outputs do not match the deterministic data flow.",
                    "outputs",
                )
            )
    if graph.fingerprint != fingerprint_logical_execution_graph(graph):
        findings.append(
            _finding(
                "logical_graph.graph_identity_mismatch",
                "The logical graph fingerprint is invalid.",
                "fingerprint",
            )
        )
    return _deduplicate(findings)


def _validate_translation_plan_canonical_types(
    plan: TranslationPlanV2,
    findings: list[GraphTranslationFinding],
) -> None:
    _require_string(plan.contract_identifier, "contract_identifier", findings)
    _require_integer(plan.contract_version, "contract_version", findings, minimum=1)
    _require_string(plan.adapter_identifier, "adapter_identifier", findings)
    _require_string(plan.fingerprint, "fingerprint", findings)

    document = plan.document_projection
    if not _require_exact_model(
        document,
        DocumentExecutionProjection,
        "document_projection",
        findings,
    ):
        return
    _require_string(document.format_identifier, "document_projection.format_identifier", findings)
    _require_integer(document.format_version, "document_projection.format_version", findings, minimum=1)
    _require_integer(
        document.source_document_major_version,
        "document_projection.source_document_major_version",
        findings,
        minimum=0,
    )
    _require_integer(
        document.source_document_minor_version,
        "document_projection.source_document_minor_version",
        findings,
        minimum=0,
    )
    _require_optional_string(
        document.selected_adapter_identifier,
        "document_projection.selected_adapter_identifier",
        findings,
    )
    for field_name in (
        "canonical_adapter_settings_json",
        "base_prompt_text",
        "fingerprint",
    ):
        _require_string(
            getattr(document, field_name),
            f"document_projection.{field_name}",
            findings,
        )
    if _require_tuple(document.active_layers, "document_projection.active_layers", findings):
        for ordinal, layer in enumerate(document.active_layers):
            _validate_document_layer_types(
                layer,
                f"document_projection.active_layers[{ordinal}]",
                findings,
            )

    capability = plan.capability_projection
    if _require_exact_model(
        capability,
        CapabilityExecutionProjection,
        "capability_projection",
        findings,
    ):
        for field_name in (
            "format_identifier",
            "capability_policy_identifier",
            "capability_policy_fingerprint",
            "subject_document_projection_fingerprint",
            "authoritative_adapter_identifier",
            "homogeneous_condition_kind",
            "fingerprint",
        ):
            _require_string(
                getattr(capability, field_name),
                f"capability_projection.{field_name}",
                findings,
            )
        _require_optional_string(
            capability.selected_adapter_identifier,
            "capability_projection.selected_adapter_identifier",
            findings,
        )
        for field_name in (
            "format_version",
            "capability_policy_version",
            "active_layer_count",
            "minimum_active_layer_count",
            "maximum_active_layer_count",
        ):
            _require_integer(
                getattr(capability, field_name),
                f"capability_projection.{field_name}",
                findings,
                minimum=0,
            )
        _require_boolean(
            capability.compatible,
            "capability_projection.compatible",
            findings,
        )
        for field_name in ("decisions", "accepted_constraints"):
            values = getattr(capability, field_name)
            if _require_tuple(
                values,
                f"capability_projection.{field_name}",
                findings,
            ):
                for ordinal, decision in enumerate(values):
                    _validate_capability_decision_types(
                        decision,
                        f"capability_projection.{field_name}[{ordinal}]",
                        findings,
                    )

    _validate_evidence_identity_types(
        plan.binding_identity,
        EvidenceIdentity,
        "binding_identity",
        findings,
    )
    certificate = plan.certificate_identity
    if _validate_evidence_identity_types(
        certificate,
        CertificateIdentity,
        "certificate_identity",
        findings,
    ):
        _require_string(
            certificate.relationship_policy_identifier,
            "certificate_identity.relationship_policy_identifier",
            findings,
        )
        _require_integer(
            certificate.relationship_policy_version,
            "certificate_identity.relationship_policy_version",
            findings,
            minimum=1,
        )

    profile = plan.execution_profile_projection
    if _require_exact_model(
        profile,
        ExecutionProfileProjection,
        "execution_profile_projection",
        findings,
    ):
        for field_name in (
            "format_identifier",
            "profile_identifier",
            "adapter_identifier",
            "backend_identifier",
            "model_family",
            "model_variant",
            "expected_field_encoding",
            "base_prompt_policy",
            "prompt_combination_delimiter",
            "negative_prompt_policy",
            "effective_weight_expression",
            "homogeneous_condition_kind",
            "fingerprint",
        ):
            _require_string(
                getattr(profile, field_name),
                f"execution_profile_projection.{field_name}",
                findings,
            )
        _require_integer(
            profile.format_version,
            "execution_profile_projection.format_version",
            findings,
            minimum=1,
        )
        for field_name in (
            "output_width",
            "output_height",
            "latent_width",
            "latent_height",
            "expected_field_width",
            "expected_field_height",
        ):
            _require_integer(
                getattr(profile, field_name),
                f"execution_profile_projection.{field_name}",
                findings,
                minimum=1,
            )

    topology = plan.topology_policy
    if _require_exact_model(
        topology,
        OrderedLeftFoldTopologyPolicy,
        "topology_policy",
        findings,
    ):
        for field_name in (
            "policy_identifier",
            "input_order_source",
            "single_condition_behavior",
            "multiple_condition_strategy",
            "fingerprint",
        ):
            _require_string(
                getattr(topology, field_name),
                f"topology_policy.{field_name}",
                findings,
            )
        _require_integer(
            topology.policy_version,
            "topology_policy.policy_version",
            findings,
            minimum=1,
        )
        for field_name in (
            "balancing_permitted",
            "sorting_permitted",
            "commutation_permitted",
            "tree_optimization_permitted",
        ):
            _require_boolean(
                getattr(topology, field_name),
                f"topology_policy.{field_name}",
                findings,
            )

    if _require_tuple(plan.regional_conditions, "regional_conditions", findings):
        for ordinal, condition in enumerate(plan.regional_conditions):
            _validate_regional_condition_types(
                condition,
                f"regional_conditions[{ordinal}]",
                findings,
            )
    if _require_tuple(plan.fold_schedule, "fold_schedule", findings):
        for ordinal, step in enumerate(plan.fold_schedule):
            path = f"fold_schedule[{ordinal}]"
            if _require_exact_model(step, AbstractFoldStep, path, findings):
                _require_integer(
                    step.step_ordinal,
                    f"{path}.step_ordinal",
                    findings,
                    minimum=0,
                )
                for field_name in ("left_operand", "right_condition", "result"):
                    _require_string(
                        getattr(step, field_name),
                        f"{path}.{field_name}",
                        findings,
                    )


def _validate_document_layer_types(
    layer: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> None:
    if not _require_exact_model(layer, DocumentExecutionLayer, path, findings):
        return
    _require_integer(layer.active_ordinal, f"{path}.active_ordinal", findings, minimum=0)
    for field_name in ("layer_id", "prompt_text", "influence_field_reference"):
        _require_string(getattr(layer, field_name), f"{path}.{field_name}", findings)
    _require_float(layer.requested_strength, f"{path}.requested_strength", findings)
    _require_optional_string(
        layer.declared_field_sha256,
        f"{path}.declared_field_sha256",
        findings,
    )


def _validate_capability_decision_types(
    decision: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> None:
    if not _require_exact_model(decision, CapabilityDecision, path, findings):
        return
    _require_string(decision.code, f"{path}.code", findings)
    _require_optional_integer(
        decision.active_ordinal,
        f"{path}.active_ordinal",
        findings,
        minimum=0,
    )
    _require_optional_string(decision.layer_id, f"{path}.layer_id", findings)
    _require_optional_string(decision.field_path, f"{path}.field_path", findings)


def _validate_evidence_identity_types(
    identity: object,
    expected_type: type[object],
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    if not _require_exact_model(identity, expected_type, path, findings):
        return False
    _require_string(identity.format_identifier, f"{path}.format_identifier", findings)
    _require_integer(identity.format_version, f"{path}.format_version", findings, minimum=1)
    _require_string(identity.fingerprint, f"{path}.fingerprint", findings)
    return True


def _validate_regional_condition_types(
    condition: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> None:
    if not _require_exact_model(condition, RegionalConditionPlanV2, path, findings):
        return
    _require_integer(condition.active_ordinal, f"{path}.active_ordinal", findings, minimum=0)
    for field_name in (
        "layer_id",
        "regional_prompt_text",
        "combined_prompt_text",
        "library_identifier",
        "family_identifier",
        "permutation_identifier",
        "library_field_id",
        "library_field_reference",
        "document_field_reference",
        "source_field_sha256",
        "encoding",
        "effective_weight_expression",
    ):
        _require_string(getattr(condition, field_name), f"{path}.{field_name}", findings)
    _require_float(condition.requested_strength, f"{path}.requested_strength", findings)
    for field_name in ("library_version", "family_version", "width", "height"):
        _require_integer(
            getattr(condition, field_name),
            f"{path}.{field_name}",
            findings,
            minimum=1,
        )
    _validate_field_polarity_types(condition.polarity, f"{path}.polarity", findings)
    _validate_field_orientation_types(
        condition.orientation,
        f"{path}.orientation",
        findings,
    )


def _validate_field_polarity_types(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> None:
    if not _require_named_model(
        value,
        "conditioning_layers.assets.models",
        "FieldPolarity",
        path,
        findings,
    ):
        return
    _require_integer(value.no_influence_sample, f"{path}.no_influence_sample", findings, minimum=0, maximum=255)
    _require_integer(value.full_influence_sample, f"{path}.full_influence_sample", findings, minimum=0, maximum=255)
    _require_boolean(value.inverted, f"{path}.inverted", findings)
    _require_boolean(value.applied_before_strength, f"{path}.applied_before_strength", findings)


def _validate_field_orientation_types(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> None:
    if not _require_named_model(
        value,
        "conditioning_layers.assets.models",
        "FieldOrientation",
        path,
        findings,
    ):
        return
    for field_name in (
        "origin",
        "positive_x",
        "positive_y",
        "resizing",
        "interpolation",
        "transformation",
    ):
        _require_string(getattr(value, field_name), f"{path}.{field_name}", findings)
    _require_integer(
        value.rotation_degrees,
        f"{path}.rotation_degrees",
        findings,
        minimum=0,
    )
    _require_boolean(value.mirrored_x, f"{path}.mirrored_x", findings)
    _require_boolean(value.mirrored_y, f"{path}.mirrored_y", findings)


def _validate_logical_graph_canonical_types(
    graph: LogicalExecutionGraph,
    findings: list[GraphTranslationFinding],
) -> None:
    for field_name in (
        "contract_identifier",
        "translation_engine_identifier",
        "adapter_identifier",
        "fingerprint",
    ):
        _require_string(getattr(graph, field_name), field_name, findings)
    _require_integer(graph.contract_version, "contract_version", findings, minimum=1)
    _require_integer(
        graph.translation_engine_version,
        "translation_engine_version",
        findings,
        minimum=1,
    )

    source_plan = graph.source_plan
    if _require_exact_model(source_plan, TranslationPlanReference, "source_plan", findings):
        _require_string(source_plan.contract_identifier, "source_plan.contract_identifier", findings)
        _require_integer(source_plan.contract_version, "source_plan.contract_version", findings, minimum=1)
        _require_string(source_plan.fingerprint, "source_plan.fingerprint", findings)

    topology = graph.topology
    if _require_exact_model(topology, LogicalGraphTopology, "topology", findings):
        _require_string(topology.policy_identifier, "topology.policy_identifier", findings)
        _require_integer(topology.policy_version, "topology.policy_version", findings, minimum=1)
        _require_string(topology.policy_fingerprint, "topology.policy_fingerprint", findings)
        _require_string(
            topology.final_output_operation_identifier,
            "topology.final_output_operation_identifier",
            findings,
        )
        _require_string(topology.fingerprint, "topology.fingerprint", findings)
        for field_name in (
            "ordered_source_operation_identifiers",
            "ordered_combine_operation_identifiers",
        ):
            values = getattr(topology, field_name)
            if _require_tuple(values, f"topology.{field_name}", findings):
                for ordinal, value in enumerate(values):
                    _require_string(value, f"topology.{field_name}[{ordinal}]", findings)

    if _require_tuple(graph.inputs, "inputs", findings):
        for ordinal, value in enumerate(graph.inputs):
            path = f"inputs[{ordinal}]"
            if _require_exact_model(value, LogicalGraphInput, path, findings):
                _require_string(value.input_identifier, f"{path}.input_identifier", findings)
                _require_integer(value.input_ordinal, f"{path}.input_ordinal", findings, minimum=0)
                _validate_regional_condition_types(value.condition, f"{path}.condition", findings)
                _require_string(value.fingerprint, f"{path}.fingerprint", findings)

    if _require_tuple(graph.operations, "operations", findings):
        for ordinal, value in enumerate(graph.operations):
            path = f"operations[{ordinal}]"
            if not _require_exact_model(value, LogicalOperation, path, findings):
                continue
            _require_string(value.operation_identifier, f"{path}.operation_identifier", findings)
            if type(value.operation_kind) is not LogicalOperationKind:
                _canonical_type_finding(findings, f"{path}.operation_kind", "a supported LogicalOperationKind")
            _require_integer(value.operation_ordinal, f"{path}.operation_ordinal", findings, minimum=0)
            _require_string(value.output_port_name, f"{path}.output_port_name", findings)
            _require_optional_string(value.source_input_identifier, f"{path}.source_input_identifier", findings)
            _require_string(value.fingerprint, f"{path}.fingerprint", findings)
            for field_name in (
                "input_port_names",
                "dependency_operation_identifiers",
                "semantic_fingerprint_inputs",
            ):
                values = getattr(value, field_name)
                if _require_tuple(values, f"{path}.{field_name}", findings):
                    for position, item in enumerate(values):
                        _require_string(item, f"{path}.{field_name}[{position}]", findings)

    if _require_tuple(graph.edges, "edges", findings):
        for ordinal, value in enumerate(graph.edges):
            path = f"edges[{ordinal}]"
            if not _require_exact_model(value, LogicalEdge, path, findings):
                continue
            for field_name in (
                "contract_identifier",
                "edge_identifier",
                "source_identifier",
                "source_semantic_fingerprint",
                "source_port_name",
                "target_operation_identifier",
                "target_operation_fingerprint",
                "target_port_name",
                "fingerprint",
            ):
                _require_string(getattr(value, field_name), f"{path}.{field_name}", findings)
            _require_integer(value.contract_version, f"{path}.contract_version", findings, minimum=1)
            _require_integer(value.edge_ordinal, f"{path}.edge_ordinal", findings, minimum=0)
            if type(value.source_kind) is not LogicalEndpointKind:
                _canonical_type_finding(findings, f"{path}.source_kind", "a supported LogicalEndpointKind")

    if _require_tuple(graph.outputs, "outputs", findings):
        for ordinal, value in enumerate(graph.outputs):
            path = f"outputs[{ordinal}]"
            if not _require_exact_model(value, LogicalGraphOutput, path, findings):
                continue
            for field_name in (
                "contract_identifier",
                "output_identifier",
                "semantic_role",
                "source_operation_identifier",
                "source_operation_fingerprint",
                "source_port_name",
                "fingerprint",
            ):
                _require_string(getattr(value, field_name), f"{path}.{field_name}", findings)
            _require_integer(value.contract_version, f"{path}.contract_version", findings, minimum=1)
            _require_integer(value.output_ordinal, f"{path}.output_ordinal", findings, minimum=0)


def _require_exact_model(
    value: object,
    expected_type: type[object],
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    if type(value) is expected_type:
        return True
    _canonical_type_finding(findings, path, expected_type.__name__)
    return False


def _require_named_model(
    value: object,
    module_name: str,
    type_name: str,
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    observed_type = type(value)
    if observed_type.__module__ == module_name and observed_type.__name__ == type_name:
        return True
    _canonical_type_finding(findings, path, type_name)
    return False


def _require_string(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    if type(value) is str:
        return True
    _canonical_type_finding(findings, path, "str")
    return False


def _require_optional_string(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    if value is None or type(value) is str:
        return True
    _canonical_type_finding(findings, path, "str or None")
    return False


def _require_integer(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> bool:
    if type(value) is not int:
        _canonical_type_finding(findings, path, "int")
        return False
    if minimum is not None and value < minimum:
        _canonical_type_finding(findings, path, f"int >= {minimum}")
        return False
    if maximum is not None and value > maximum:
        _canonical_type_finding(findings, path, f"int <= {maximum}")
        return False
    return True


def _require_optional_integer(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
    *,
    minimum: int | None = None,
) -> bool:
    if value is None:
        return True
    return _require_integer(value, path, findings, minimum=minimum)


def _require_float(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    if type(value) is float:
        return True
    _canonical_type_finding(findings, path, "float")
    return False


def _require_boolean(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    if type(value) is bool:
        return True
    _canonical_type_finding(findings, path, "bool")
    return False


def _require_tuple(
    value: object,
    path: str,
    findings: list[GraphTranslationFinding],
) -> bool:
    if type(value) is tuple:
        return True
    _canonical_type_finding(findings, path, "tuple")
    return False


def _canonical_type_finding(
    findings: list[GraphTranslationFinding],
    path: str,
    expected: str,
) -> None:
    findings.append(
        _finding(
            "logical_graph.canonical_type_mismatch",
            f"The canonical contract field must be {expected}.",
            path,
        )
    )


def _safe_fingerprint(
    function: Callable[[object], str],
    value: object,
) -> str | None:
    try:
        return function(value)
    except (AttributeError, CanonicalizationError, TypeError, ValueError):
        return None


def _validate_translation_plan(
    plan: TranslationPlanV2,
    invalid: list[GraphTranslationFinding],
    rejected: list[GraphTranslationFinding],
) -> None:
    type_finding_count = len(invalid)
    _validate_translation_plan_canonical_types(plan, invalid)
    if (
        plan.contract_identifier != TRANSLATION_PLAN_V2_IDENTIFIER
        or plan.contract_version != TRANSLATION_PLAN_V2_VERSION
    ):
        rejected.append(
            _finding(
                "logical_graph.unsupported_translation_plan",
                "The Translation Plan contract is unsupported.",
                "contract_identifier",
            )
        )
    expected_plan_fingerprint = _safe_fingerprint(fingerprint_translation_plan_v2, plan)
    if (
        expected_plan_fingerprint is None
        or plan.fingerprint != expected_plan_fingerprint
    ):
        invalid.append(
            _finding(
                "logical_graph.translation_plan_fingerprint_mismatch",
                "The Translation Plan fingerprint is invalid.",
                "fingerprint",
            )
        )
    if len(invalid) > type_finding_count:
        return

    topology = plan.topology_policy
    expected_topology_fingerprint = _safe_fingerprint(
        fingerprint_topology_policy,
        topology,
    )
    if (
        expected_topology_fingerprint is None
        or topology.fingerprint != expected_topology_fingerprint
    ):
        invalid.append(
            _finding(
                "logical_graph.topology_fingerprint_mismatch",
                "The topology-policy fingerprint is invalid.",
                "topology_policy.fingerprint",
            )
        )
    if (
        topology.policy_identifier != TOPOLOGY_POLICY_IDENTIFIER
        or topology.policy_version != TOPOLOGY_POLICY_VERSION
    ):
        rejected.append(
            _finding(
                "logical_graph.unsupported_topology",
                "The topology policy is unsupported.",
                "topology_policy.policy_identifier",
            )
        )
    elif not exact_contract_equal(topology, ORDERED_LEFT_FOLD_TOPOLOGY_POLICY):
        invalid.append(
            _finding(
                "logical_graph.topology_contract_mismatch",
                "The known topology identity has changed semantic content.",
                "topology_policy",
            )
        )

    projection_checks = (
        (
            plan.document_projection.fingerprint,
            fingerprint_document_execution_projection(plan.document_projection),
            "logical_graph.document_projection_mismatch",
            "document_projection.fingerprint",
        ),
        (
            plan.capability_projection.fingerprint,
            fingerprint_capability_execution_projection(plan.capability_projection),
            "logical_graph.capability_projection_mismatch",
            "capability_projection.fingerprint",
        ),
        (
            plan.execution_profile_projection.fingerprint,
            fingerprint_execution_profile_projection(
                plan.execution_profile_projection
            ),
            "logical_graph.profile_projection_mismatch",
            "execution_profile_projection.fingerprint",
        ),
    )
    for recorded, expected, code, path in projection_checks:
        if recorded != expected:
            invalid.append(
                _finding(code, "An upstream projection fingerprint is invalid.", path)
            )

    projection_contracts = (
        (
            plan.document_projection.format_identifier,
            plan.document_projection.format_version,
            DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
            DOCUMENT_EXECUTION_PROJECTION_VERSION,
            "document_projection",
        ),
        (
            plan.capability_projection.format_identifier,
            plan.capability_projection.format_version,
            CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
            CAPABILITY_EXECUTION_PROJECTION_VERSION,
            "capability_projection",
        ),
        (
            plan.execution_profile_projection.format_identifier,
            plan.execution_profile_projection.format_version,
            EXECUTION_PROFILE_PROJECTION_IDENTIFIER,
            EXECUTION_PROFILE_PROJECTION_VERSION,
            "execution_profile_projection",
        ),
    )
    for observed_identifier, observed_version, identifier, version, path in (
        projection_contracts
    ):
        if observed_identifier != identifier or observed_version != version:
            invalid.append(
                _finding(
                    "logical_graph.translation_plan_mismatch",
                    "An upstream projection contract is unsupported.",
                    path,
                )
            )
    if (
        not _valid_sha256(plan.binding_identity.fingerprint)
        or not _valid_sha256(plan.certificate_identity.fingerprint)
    ):
        invalid.append(
            _finding(
                "logical_graph.translation_plan_mismatch",
                "An evidence identity is not a canonical SHA-256 value.",
                "binding_identity",
            )
        )

    conditions = plan.regional_conditions
    document_layers = plan.document_projection.active_layers
    capability = plan.capability_projection
    profile = plan.execution_profile_projection
    if not conditions:
        invalid.append(
            _finding(
                "logical_graph.no_conditions",
                "A translated plan must contain at least one condition.",
                "regional_conditions",
            )
        )
        return
    if (
        len(document_layers) != len(conditions)
        or capability.active_layer_count != len(conditions)
    ):
        invalid.append(
            _finding(
                "logical_graph.translation_plan_mismatch",
                "Condition counts disagree inside the Translation Plan.",
                "regional_conditions",
            )
        )
    if (
        not capability.compatible
        or len(conditions) < capability.minimum_active_layer_count
        or len(conditions) > capability.maximum_active_layer_count
    ):
        invalid.append(
            _finding(
                "logical_graph.translation_plan_mismatch",
                "The plan contains an incompatible capability projection.",
                "capability_projection.compatible",
            )
        )
    if (
        capability.subject_document_projection_fingerprint
        != plan.document_projection.fingerprint
        or plan.adapter_identifier != capability.authoritative_adapter_identifier
        or plan.adapter_identifier != capability.selected_adapter_identifier
        or plan.adapter_identifier != profile.adapter_identifier
        or capability.homogeneous_condition_kind
        != profile.homogeneous_condition_kind
    ):
        invalid.append(
            _finding(
                "logical_graph.translation_plan_mismatch",
                "Adapter, subject, or condition-kind identities disagree.",
                "adapter_identifier",
            )
        )
    expected_schedule = build_ordered_left_fold_schedule(len(conditions))
    if plan.fold_schedule != expected_schedule:
        invalid.append(
            _finding(
                "logical_graph.malformed_fold_schedule",
                "The fold schedule does not match the ordered-left-fold policy.",
                "fold_schedule",
            )
        )

    for ordinal, (condition, layer) in enumerate(
        zip(conditions, document_layers, strict=False)
    ):
        if (
            condition.active_ordinal != ordinal
            or layer.active_ordinal != ordinal
            or condition.layer_id != layer.layer_id
            or condition.regional_prompt_text != layer.prompt_text
            or condition.requested_strength != layer.requested_strength
            or condition.document_field_reference
            != layer.influence_field_reference
            or (
                layer.declared_field_sha256 is not None
                and condition.source_field_sha256
                != layer.declared_field_sha256
            )
            or condition.combined_prompt_text
            != (
                plan.document_projection.base_prompt_text
                + profile.prompt_combination_delimiter
                + layer.prompt_text
            )
            or condition.width != profile.expected_field_width
            or condition.height != profile.expected_field_height
            or condition.encoding != profile.expected_field_encoding
            or condition.effective_weight_expression
            != profile.effective_weight_expression
        ):
            invalid.append(
                _finding(
                    "logical_graph.translation_plan_mismatch",
                    "A regional condition disagrees with its plan projections.",
                    f"regional_conditions[{ordinal}]",
                )
            )


def _graph_input(
    ordinal: int,
    condition: RegionalConditionPlanV2,
) -> LogicalGraphInput:
    value = LogicalGraphInput(
        input_identifier=f"input:condition:{ordinal}",
        input_ordinal=ordinal,
        condition=condition,
        fingerprint="",
    )
    return replace(value, fingerprint=fingerprint_logical_graph_input(value))


def _operations(
    inputs: tuple[LogicalGraphInput, ...],
) -> tuple[LogicalOperation, ...]:
    source_operations: list[LogicalOperation] = []
    for ordinal, graph_input in enumerate(inputs):
        value = LogicalOperation(
            operation_identifier=f"operation:source-condition:{ordinal}",
            operation_kind=LogicalOperationKind.SOURCE_CONDITION,
            operation_ordinal=ordinal,
            input_port_names=(_CONDITION_PORT,),
            output_port_name=_CONDITION_PORT,
            source_input_identifier=graph_input.input_identifier,
            dependency_operation_identifiers=(),
            semantic_fingerprint_inputs=(graph_input.fingerprint,),
            fingerprint="",
        )
        source_operations.append(
            replace(value, fingerprint=fingerprint_logical_operation(value))
        )

    combine_operations: list[LogicalOperation] = []
    for step_ordinal in range(max(len(inputs) - 1, 0)):
        left = (
            source_operations[0]
            if step_ordinal == 0
            else combine_operations[step_ordinal - 1]
        )
        right = source_operations[step_ordinal + 1]
        value = LogicalOperation(
            operation_identifier=f"operation:combine:{step_ordinal}",
            operation_kind=LogicalOperationKind.COMBINE,
            operation_ordinal=len(source_operations) + step_ordinal,
            input_port_names=(_LEFT_PORT, _RIGHT_PORT),
            output_port_name=_CONDITION_PORT,
            source_input_identifier=None,
            dependency_operation_identifiers=(
                left.operation_identifier,
                right.operation_identifier,
            ),
            semantic_fingerprint_inputs=(left.fingerprint, right.fingerprint),
            fingerprint="",
        )
        combine_operations.append(
            replace(value, fingerprint=fingerprint_logical_operation(value))
        )

    final_source = (
        combine_operations[-1] if combine_operations else source_operations[0]
    )
    final = LogicalOperation(
        operation_identifier="operation:final-output",
        operation_kind=LogicalOperationKind.FINAL_OUTPUT,
        operation_ordinal=len(source_operations) + len(combine_operations),
        input_port_names=(_CONDITION_PORT,),
        output_port_name=_CONDITION_PORT,
        source_input_identifier=None,
        dependency_operation_identifiers=(final_source.operation_identifier,),
        semantic_fingerprint_inputs=(final_source.fingerprint,),
        fingerprint="",
    )
    final = replace(final, fingerprint=fingerprint_logical_operation(final))
    return tuple(source_operations + combine_operations + [final])


def _topology(
    plan: TranslationPlanV2,
    operations: tuple[LogicalOperation, ...],
) -> LogicalGraphTopology:
    policy = plan.topology_policy
    return _topology_from_policy_fields(
        policy.policy_identifier,
        policy.policy_version,
        policy.fingerprint,
        operations,
    )


def _topology_from_policy_fields(
    policy_identifier: str,
    policy_version: int,
    policy_fingerprint: str,
    operations: tuple[LogicalOperation, ...],
) -> LogicalGraphTopology:
    value = LogicalGraphTopology(
        policy_identifier=policy_identifier,
        policy_version=policy_version,
        policy_fingerprint=policy_fingerprint,
        ordered_source_operation_identifiers=tuple(
            item.operation_identifier
            for item in operations
            if item.operation_kind is LogicalOperationKind.SOURCE_CONDITION
        ),
        ordered_combine_operation_identifiers=tuple(
            item.operation_identifier
            for item in operations
            if item.operation_kind is LogicalOperationKind.COMBINE
        ),
        final_output_operation_identifier="operation:final-output",
        fingerprint="",
    )
    return replace(value, fingerprint=fingerprint_logical_topology(value))


def _edges(
    inputs: tuple[LogicalGraphInput, ...],
    operations: tuple[LogicalOperation, ...],
) -> tuple[LogicalEdge, ...]:
    source_operations = tuple(
        item
        for item in operations
        if item.operation_kind is LogicalOperationKind.SOURCE_CONDITION
    )
    combine_operations = tuple(
        item
        for item in operations
        if item.operation_kind is LogicalOperationKind.COMBINE
    )
    edges: list[LogicalEdge] = []
    for graph_input, operation in zip(inputs, source_operations, strict=True):
        edges.append(
            _edge(
                len(edges),
                LogicalEndpointKind.GRAPH_INPUT,
                graph_input.input_identifier,
                graph_input.fingerprint,
                _CONDITION_PORT,
                operation,
                _CONDITION_PORT,
            )
        )
    for ordinal, combine in enumerate(combine_operations):
        left = source_operations[0] if ordinal == 0 else combine_operations[ordinal - 1]
        right = source_operations[ordinal + 1]
        edges.append(
            _edge(
                len(edges),
                LogicalEndpointKind.OPERATION,
                left.operation_identifier,
                left.fingerprint,
                _CONDITION_PORT,
                combine,
                _LEFT_PORT,
            )
        )
        edges.append(
            _edge(
                len(edges),
                LogicalEndpointKind.OPERATION,
                right.operation_identifier,
                right.fingerprint,
                _CONDITION_PORT,
                combine,
                _RIGHT_PORT,
            )
        )
    final = operations[-1]
    final_source = combine_operations[-1] if combine_operations else source_operations[0]
    edges.append(
        _edge(
            len(edges),
            LogicalEndpointKind.OPERATION,
            final_source.operation_identifier,
            final_source.fingerprint,
            _CONDITION_PORT,
            final,
            _CONDITION_PORT,
        )
    )
    return tuple(edges)


def _edge(
    ordinal: int,
    source_kind: LogicalEndpointKind,
    source_identifier: str,
    source_semantic_fingerprint: str,
    source_port_name: str,
    target_operation: LogicalOperation,
    target_port_name: str,
) -> LogicalEdge:
    value = LogicalEdge(
        contract_identifier=LOGICAL_EDGE_IDENTIFIER,
        contract_version=LOGICAL_EDGE_VERSION,
        edge_identifier=f"edge:{ordinal}",
        edge_ordinal=ordinal,
        source_kind=source_kind,
        source_identifier=source_identifier,
        source_semantic_fingerprint=source_semantic_fingerprint,
        source_port_name=source_port_name,
        target_operation_identifier=target_operation.operation_identifier,
        target_operation_fingerprint=target_operation.fingerprint,
        target_port_name=target_port_name,
        fingerprint="",
    )
    return replace(value, fingerprint=fingerprint_logical_edge(value))


def _outputs(
    operations: tuple[LogicalOperation, ...],
) -> tuple[LogicalGraphOutput, ...]:
    final = operations[-1]
    value = LogicalGraphOutput(
        contract_identifier=LOGICAL_OUTPUT_IDENTIFIER,
        contract_version=LOGICAL_OUTPUT_VERSION,
        output_identifier="output:final-condition",
        output_ordinal=0,
        semantic_role="final_condition",
        source_operation_identifier=final.operation_identifier,
        source_operation_fingerprint=final.fingerprint,
        source_port_name=final.output_port_name,
        fingerprint="",
    )
    value = replace(value, fingerprint=fingerprint_logical_output(value))
    return (value,)


def _fingerprint_without_field(value: object) -> str:
    return fingerprint_without_field(value)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _result(
    status: GraphTranslationStatus,
    graph: LogicalExecutionGraph | None,
    findings: list[GraphTranslationFinding],
) -> GraphTranslationResult:
    return GraphTranslationResult(
        status=status,
        graph=graph,
        findings=_deduplicate(findings),
    )


def _deduplicate(
    findings: list[GraphTranslationFinding],
) -> tuple[GraphTranslationFinding, ...]:
    retained: list[GraphTranslationFinding] = []
    seen: set[tuple[str, str | None]] = set()
    for finding in findings:
        key = (finding.code, finding.field_path)
        if key not in seen:
            retained.append(finding)
            seen.add(key)
    return tuple(retained)


def _finding(
    code: str,
    message: str,
    field_path: str | None = None,
) -> GraphTranslationFinding:
    return GraphTranslationFinding(
        code=code,
        message=message,
        field_path=field_path,
    )
