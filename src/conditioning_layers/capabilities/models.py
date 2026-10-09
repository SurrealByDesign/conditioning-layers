"""Immutable, data-only capability reporting structures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from conditioning_layers.domain import ValidationFinding


class EvidenceLevel(str, Enum):
    """Small vocabulary distinguishing evidence from product declarations."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    DECLARED = "declared"
    UNTESTED = "untested"
    UNSUPPORTED = "unsupported"


class AdapterStatus(str, Enum):
    """Prototype adapter maturity status."""

    EXPERIMENTAL = "experimental"


class SupportStatus(str, Enum):
    """How the one prototype adapter treats a requested behavior."""

    SUPPORTED = "supported"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"
    NON_SEMANTIC = "non_semantic"


@dataclass(frozen=True, slots=True)
class EvidenceStatement:
    """One concise claim and the level supporting it."""

    statement: str
    evidence: EvidenceLevel


@dataclass(frozen=True, slots=True)
class SupportClaim:
    """Machine-readable support status with evidence-bounded explanation."""

    status: SupportStatus
    evidence: EvidenceLevel
    note: str


@dataclass(frozen=True, slots=True)
class RiskDeclaration:
    """Known adapter risk that later execution surfaces must disclose."""

    code: str
    message: str
    evidence: EvidenceLevel
    evidence_reference: str


@dataclass(frozen=True, slots=True)
class PredictionMixingCapability:
    """The single evidence-bounded capability record authorized for Slice 3."""

    adapter_identifier: str
    display_name: str
    backend_name: str
    status: AdapterStatus
    supported_layer_type: str
    minimum_visible_prompt_layers: int
    maximum_tested_visible_prompt_layers: int
    one_layer_evidence: EvidenceLevel
    two_layer_evidence: EvidenceLevel
    disabled_layers_excluded: EvidenceStatement
    imported_png_fields: SupportClaim
    continuous_fields: SupportClaim
    overlap: SupportClaim
    retained_order_execution: SupportClaim
    strength: SupportClaim
    tested_resolution: EvidenceStatement
    runtime_scaling: EvidenceStatement
    vram: EvidenceStatement
    provenance: SupportClaim
    production_quality: SupportClaim
    known_risks: tuple[RiskDeclaration, ...]
    evidence_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilitySummary:
    """UI-ready data with no rendering or execution behavior."""

    adapter_display_name: str
    status: AdapterStatus
    compatible: bool
    active_layer_count: int
    tested_maximum: int
    supported_field_behavior: tuple[str, ...]
    unsupported_behavior: tuple[str, ...]
    key_warnings: tuple[ValidationFinding, ...]
    evidence_scope: str


@dataclass(frozen=True, slots=True)
class CapabilityEvaluation:
    """Deterministic compatibility result for one Conditioning Document."""

    adapter_identifier: str
    selected_adapter_identifier: str | None
    compatible: bool
    active_layer_count: int
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    capability: PredictionMixingCapability
    summary: CapabilitySummary
