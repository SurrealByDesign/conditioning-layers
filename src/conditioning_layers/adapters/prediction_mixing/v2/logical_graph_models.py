"""Immutable logical execution graph contracts for Prediction Mixing v2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import RegionalConditionPlanV2


GRAPH_TRANSLATION_ENGINE_IDENTIFIER = (
    "prediction-mixing.graph-translation-engine.v1"
)
GRAPH_TRANSLATION_ENGINE_VERSION = 1
LOGICAL_EXECUTION_GRAPH_IDENTIFIER = (
    "prediction-mixing.logical-execution-graph.v1"
)
LOGICAL_EXECUTION_GRAPH_VERSION = 1
LOGICAL_EDGE_IDENTIFIER = "prediction-mixing.logical-edge.v1"
LOGICAL_EDGE_VERSION = 1
LOGICAL_OUTPUT_IDENTIFIER = "prediction-mixing.logical-output.v1"
LOGICAL_OUTPUT_VERSION = 1


class GraphTranslationStatus(str, Enum):
    """The all-or-nothing outcome of logical graph translation."""

    BUILT = "built"
    REJECTED = "rejected"
    INVALID = "invalid"


class LogicalOperationKind(str, Enum):
    """Backend-host-neutral semantic operations for Prediction Mixing."""

    SOURCE_CONDITION = "source_condition"
    COMBINE = "combine"
    FINAL_OUTPUT = "final_output"


class LogicalEndpointKind(str, Enum):
    """The two endpoint categories permitted in a logical edge."""

    GRAPH_INPUT = "graph_input"
    OPERATION = "operation"


@dataclass(frozen=True, slots=True)
class GraphTranslationFinding:
    """Structured rejection or invalidity without fingerprinted prose."""

    code: str
    message: str
    field_path: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationPlanReference:
    """Exact upstream Translation Plan v2 identity consumed by the graph."""

    contract_identifier: str
    contract_version: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LogicalGraphInput:
    """One ordered regional condition exposed to logical data flow."""

    input_identifier: str
    input_ordinal: int
    condition: RegionalConditionPlanV2
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LogicalOperation:
    """One semantic operation without a backend node class or node ID."""

    operation_identifier: str
    operation_kind: LogicalOperationKind
    operation_ordinal: int
    input_port_names: tuple[str, ...]
    output_port_name: str
    source_input_identifier: str | None
    dependency_operation_identifiers: tuple[str, ...]
    semantic_fingerprint_inputs: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LogicalEdge:
    """One directed logical value flow between named semantic ports."""

    contract_identifier: str
    contract_version: int
    edge_identifier: str
    edge_ordinal: int
    source_kind: LogicalEndpointKind
    source_identifier: str
    source_semantic_fingerprint: str
    source_port_name: str
    target_operation_identifier: str
    target_operation_fingerprint: str
    target_port_name: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LogicalGraphOutput:
    """One graph-level logical output sourced from a semantic operation."""

    contract_identifier: str
    contract_version: int
    output_identifier: str
    output_ordinal: int
    semantic_role: str
    source_operation_identifier: str
    source_operation_fingerprint: str
    source_port_name: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LogicalGraphTopology:
    """Exact realized order of one supported abstract topology policy."""

    policy_identifier: str
    policy_version: int
    policy_fingerprint: str
    ordered_source_operation_identifiers: tuple[str, ...]
    ordered_combine_operation_identifiers: tuple[str, ...]
    final_output_operation_identifier: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LogicalExecutionGraph:
    """Complete backend-host-neutral graph for Prediction Mixing semantics."""

    contract_identifier: str
    contract_version: int
    translation_engine_identifier: str
    translation_engine_version: int
    adapter_identifier: str
    source_plan: TranslationPlanReference
    topology: LogicalGraphTopology
    inputs: tuple[LogicalGraphInput, ...]
    operations: tuple[LogicalOperation, ...]
    edges: tuple[LogicalEdge, ...]
    outputs: tuple[LogicalGraphOutput, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class GraphTranslationResult:
    """All-or-nothing logical graph result."""

    status: GraphTranslationStatus
    graph: LogicalExecutionGraph | None
    findings: tuple[GraphTranslationFinding, ...]
