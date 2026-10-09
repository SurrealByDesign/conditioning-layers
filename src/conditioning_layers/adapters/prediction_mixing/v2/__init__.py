"""Isolated Translation Plan v2 contracts with lazy construction exports."""

from __future__ import annotations

from importlib import import_module

from .canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    canonical_json_text,
    sha256_canonical,
)
from .identity import (
    fingerprint_capability_execution_projection,
    fingerprint_document_execution_projection,
    fingerprint_execution_profile_projection,
    fingerprint_topology_policy,
    fingerprint_translation_plan_v2,
)
from .models import (
    CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
    CAPABILITY_POLICY_IDENTIFIER,
    DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
    EXECUTION_PROFILE_PROJECTION_IDENTIFIER,
    TOPOLOGY_POLICY_IDENTIFIER,
    TRANSLATION_PLAN_V2_IDENTIFIER,
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
    TranslationResultV2,
    TranslationStatus,
)
from .topology import (
    ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
    build_ordered_left_fold_schedule,
)


_LAZY_EXPORTS = {
    "GRAPH_TRANSLATION_ENGINE_IDENTIFIER": (
        ".logical_graph_models",
        "GRAPH_TRANSLATION_ENGINE_IDENTIFIER",
    ),
    "LOGICAL_EXECUTION_GRAPH_IDENTIFIER": (
        ".logical_graph_models",
        "LOGICAL_EXECUTION_GRAPH_IDENTIFIER",
    ),
    "GraphTranslationFinding": (".logical_graph_models", "GraphTranslationFinding"),
    "GraphTranslationResult": (".logical_graph_models", "GraphTranslationResult"),
    "GraphTranslationStatus": (".logical_graph_models", "GraphTranslationStatus"),
    "LogicalEdge": (".logical_graph_models", "LogicalEdge"),
    "LogicalEndpointKind": (".logical_graph_models", "LogicalEndpointKind"),
    "LogicalExecutionGraph": (".logical_graph_models", "LogicalExecutionGraph"),
    "LogicalGraphInput": (".logical_graph_models", "LogicalGraphInput"),
    "LogicalGraphOutput": (".logical_graph_models", "LogicalGraphOutput"),
    "LogicalGraphTopology": (".logical_graph_models", "LogicalGraphTopology"),
    "LogicalOperation": (".logical_graph_models", "LogicalOperation"),
    "LogicalOperationKind": (".logical_graph_models", "LogicalOperationKind"),
    "TranslationPlanReference": (
        ".logical_graph_models",
        "TranslationPlanReference",
    ),
    "fingerprint_logical_edge": (".logical_graph", "fingerprint_logical_edge"),
    "fingerprint_logical_execution_graph": (
        ".logical_graph",
        "fingerprint_logical_execution_graph",
    ),
    "fingerprint_logical_graph_input": (
        ".logical_graph",
        "fingerprint_logical_graph_input",
    ),
    "fingerprint_logical_operation": (
        ".logical_graph",
        "fingerprint_logical_operation",
    ),
    "fingerprint_logical_output": (".logical_graph", "fingerprint_logical_output"),
    "fingerprint_logical_topology": (
        ".logical_graph",
        "fingerprint_logical_topology",
    ),
    "serialize_logical_execution_graph": (
        ".logical_graph",
        "serialize_logical_execution_graph",
    ),
    "translate_plan_to_logical_execution_graph": (
        ".logical_graph",
        "translate_plan_to_logical_execution_graph",
    ),
    "validate_logical_execution_graph": (
        ".logical_graph",
        "validate_logical_execution_graph",
    ),
    "build_capability_execution_projection": (
        ".projections",
        "build_capability_execution_projection",
    ),
    "build_document_execution_projection": (
        ".projections",
        "build_document_execution_projection",
    ),
    "build_execution_profile_projection": (
        ".projections",
        "build_execution_profile_projection",
    ),
    "fingerprint_capability_policy": (
        ".projections",
        "fingerprint_capability_policy",
    ),
    "serialize_capability_execution_projection": (
        ".projections",
        "serialize_capability_execution_projection",
    ),
    "serialize_document_execution_projection": (
        ".projections",
        "serialize_document_execution_projection",
    ),
    "serialize_execution_profile_projection": (
        ".projections",
        "serialize_execution_profile_projection",
    ),
    "serialize_topology_policy": (".topology", "serialize_topology_policy"),
    "serialize_translation_plan_v2": (".translate", "serialize_translation_plan_v2"),
    "translate_prediction_mixing_v2": (".translate", "translate_prediction_mixing_v2"),
}


def __getattr__(name: str) -> object:
    """Load construction-side modules only when their public names are requested."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER",
    "CAPABILITY_POLICY_IDENTIFIER",
    "DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER",
    "EXECUTION_PROFILE_PROJECTION_IDENTIFIER",
    "GRAPH_TRANSLATION_ENGINE_IDENTIFIER",
    "LOGICAL_EXECUTION_GRAPH_IDENTIFIER",
    "ORDERED_LEFT_FOLD_TOPOLOGY_POLICY",
    "TOPOLOGY_POLICY_IDENTIFIER",
    "TRANSLATION_PLAN_V2_IDENTIFIER",
    "AbstractFoldStep",
    "CanonicalizationError",
    "CapabilityDecision",
    "CapabilityExecutionProjection",
    "CertificateIdentity",
    "DocumentExecutionLayer",
    "DocumentExecutionProjection",
    "EvidenceIdentity",
    "ExecutionProfileProjection",
    "GraphTranslationFinding",
    "GraphTranslationResult",
    "GraphTranslationStatus",
    "LogicalEdge",
    "LogicalEndpointKind",
    "LogicalExecutionGraph",
    "LogicalGraphInput",
    "LogicalGraphOutput",
    "LogicalGraphTopology",
    "LogicalOperation",
    "LogicalOperationKind",
    "OrderedLeftFoldTopologyPolicy",
    "RegionalConditionPlanV2",
    "TranslationPlanReference",
    "TranslationPlanV2",
    "TranslationResultV2",
    "TranslationStatus",
    "build_capability_execution_projection",
    "build_document_execution_projection",
    "build_execution_profile_projection",
    "build_ordered_left_fold_schedule",
    "canonical_json_bytes",
    "canonical_json_text",
    "fingerprint_capability_execution_projection",
    "fingerprint_capability_policy",
    "fingerprint_document_execution_projection",
    "fingerprint_execution_profile_projection",
    "fingerprint_logical_edge",
    "fingerprint_logical_execution_graph",
    "fingerprint_logical_graph_input",
    "fingerprint_logical_operation",
    "fingerprint_logical_output",
    "fingerprint_logical_topology",
    "fingerprint_topology_policy",
    "fingerprint_translation_plan_v2",
    "serialize_capability_execution_projection",
    "serialize_document_execution_projection",
    "serialize_execution_profile_projection",
    "serialize_logical_execution_graph",
    "serialize_topology_policy",
    "serialize_translation_plan_v2",
    "sha256_canonical",
    "translate_prediction_mixing_v2",
    "translate_plan_to_logical_execution_graph",
    "validate_logical_execution_graph",
]
