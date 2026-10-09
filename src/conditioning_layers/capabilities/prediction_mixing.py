"""Canonical Phase 2 capability record for experimental Prediction Mixing."""

from conditioning_layers.domain import PREDICTION_MIXING_ADAPTER_ID

from .models import (
    AdapterStatus,
    EvidenceLevel,
    EvidenceStatement,
    PredictionMixingCapability,
    RiskDeclaration,
    SupportClaim,
    SupportStatus,
)


PHASE_1_REPORT = "research/PHASE_1_RESEARCH_REPORT.md"
EXP_0003 = (
    "research/experiments/EXP-0003-krea2-prediction-mixing/README.md"
)
EXP_0004 = (
    "research/experiments/EXP-0004-krea2-gradient-transition/README.md"
)
EXP_0005 = (
    "research/experiments/EXP-0005-krea2-base-regional-modifiers/README.md"
)


PREDICTION_MIXING_CAPABILITY = PredictionMixingCapability(
    adapter_identifier=PREDICTION_MIXING_ADAPTER_ID,
    display_name="Prediction Mixing (Experimental)",
    backend_name="Krea 2 in ComfyUI",
    status=AdapterStatus.EXPERIMENTAL,
    supported_layer_type="Prompt Layer",
    minimum_visible_prompt_layers=1,
    maximum_tested_visible_prompt_layers=2,
    one_layer_evidence=EvidenceLevel.INFERRED,
    two_layer_evidence=EvidenceLevel.OBSERVED,
    disabled_layers_excluded=EvidenceStatement(
        statement=(
            "Disabled Prompt Layers remain stored and are excluded from the "
            "active-layer count."
        ),
        evidence=EvidenceLevel.DECLARED,
    ),
    imported_png_fields=SupportClaim(
        status=SupportStatus.SUPPORTED,
        evidence=EvidenceLevel.OBSERVED,
        note=(
            "Every active Prompt Layer requires an imported PNG Influence Field "
            "reference; this record does not load or inspect the asset."
        ),
    ),
    continuous_fields=SupportClaim(
        status=SupportStatus.SUPPORTED,
        evidence=EvidenceLevel.OBSERVED,
        note=(
            "Continuous field values are technically supported, but softer "
            "boundaries can increase leakage or fusion."
        ),
    ),
    overlap=SupportClaim(
        status=SupportStatus.UNSUPPORTED,
        evidence=EvidenceLevel.UNSUPPORTED,
        note=(
            "The Phase 2 prototype defines no overlap behavior. This document "
            "model does not represent overlap requests for evaluation here."
        ),
    ),
    retained_order_execution=SupportClaim(
        status=SupportStatus.NON_SEMANTIC,
        evidence=EvidenceLevel.DECLARED,
        note=(
            "Document order is retained for organization and repeatability, not "
            "interpreted as execution priority."
        ),
    ),
    strength=SupportClaim(
        status=SupportStatus.EXPERIMENTAL,
        evidence=EvidenceLevel.OBSERVED,
        note=(
            "Strength is accepted as requested weighting from 0.0 through 1.0; "
            "it is not perceptually linear and only 1.0 has direct Phase 1 evidence."
        ),
    ),
    tested_resolution=EvidenceStatement(
        statement="1024 x 1024, Krea 2 Turbo BF16 research profile.",
        evidence=EvidenceLevel.OBSERVED,
    ),
    runtime_scaling=EvidenceStatement(
        statement="Runtime increases approximately with active condition count.",
        evidence=EvidenceLevel.OBSERVED,
    ),
    vram=EvidenceStatement(
        statement=(
            "The tested 16 GB environment had narrow VRAM headroom at the "
            "two-regional-condition profile."
        ),
        evidence=EvidenceLevel.OBSERVED,
    ),
    provenance=SupportClaim(
        status=SupportStatus.SUPPORTED,
        evidence=EvidenceLevel.DECLARED,
        note=(
            "The future adapter contract must account for every visible layer and "
            "attach the capability result to separate execution provenance."
        ),
    ),
    production_quality=SupportClaim(
        status=SupportStatus.UNSUPPORTED,
        evidence=EvidenceLevel.DECLARED,
        note="This experimental capability makes no production-quality claim.",
    ),
    known_risks=(
        RiskDeclaration(
            code="risk.seam",
            message="Visible seams may appear at Influence Field boundaries.",
            evidence=EvidenceLevel.OBSERVED,
            evidence_reference=EXP_0003,
        ),
        RiskDeclaration(
            code="risk.leakage",
            message="Prompt concepts may leak outside their intended regions.",
            evidence=EvidenceLevel.OBSERVED,
            evidence_reference=EXP_0004,
        ),
        RiskDeclaration(
            code="risk.fusion",
            message="Prompt concepts may fuse rather than remain independent.",
            evidence=EvidenceLevel.OBSERVED,
            evidence_reference=EXP_0003,
        ),
        RiskDeclaration(
            code="risk.topology",
            message="Base scene topology may change or fail to remain coherent.",
            evidence=EvidenceLevel.OBSERVED,
            evidence_reference=EXP_0005,
        ),
    ),
    evidence_references=(PHASE_1_REPORT, EXP_0003, EXP_0004, EXP_0005),
)
