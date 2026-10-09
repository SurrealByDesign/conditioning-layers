"""Deterministic compatibility and warning evaluation; no translation or I/O."""

from __future__ import annotations

from collections.abc import Mapping
import math

from conditioning_layers.domain import (
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    ValidationFinding,
    validate_document,
)

from .models import CapabilityEvaluation, CapabilitySummary
from .composition_policy import retained_execution_policy_findings
from .prediction_mixing import PREDICTION_MIXING_CAPABILITY


def evaluate_prediction_mixing(
    document: ConditioningDocument,
    *,
    require_selected_adapter: bool = True,
) -> CapabilityEvaluation:
    """Evaluate document intent against the one canonical capability record.

    This function performs no asset access, overlap detection, translation, host
    inspection, or execution. ``require_selected_adapter=False`` permits an
    unconfigured document to be inspected against this capability; a different
    selected adapter is still rejected.
    """

    if not isinstance(document, ConditioningDocument):
        raise TypeError(
            "evaluate_prediction_mixing requires a ConditioningDocument"
        )

    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []
    information: list[ValidationFinding] = []

    for finding in validate_document(document):
        if finding.severity is FindingSeverity.ERROR:
            errors.append(finding)
        elif finding.severity is FindingSeverity.WARNING:
            _append_unique(warnings, finding)
        else:
            information.append(finding)

    errors.extend(retained_execution_policy_findings(document))

    adapter_id = document.selected_adapter_id
    if adapter_id is None:
        if require_selected_adapter:
            errors.append(
                _finding(
                    "capability.adapter_required",
                    FindingSeverity.ERROR,
                    "Select prediction-mixing.experimental.v1 before execution.",
                    field_path="selected_adapter_id",
                )
            )
    elif adapter_id != PREDICTION_MIXING_CAPABILITY.adapter_identifier:
        errors.append(
            _finding(
                "capability.adapter_unsupported",
                FindingSeverity.ERROR,
                "The selected adapter is not supported by this capability record.",
                field_path="selected_adapter_id",
            )
        )

    settings = document.adapter_settings
    if isinstance(settings, Mapping) and settings:
        errors.append(
            _finding(
                "capability.adapter_settings_unsupported",
                FindingSeverity.ERROR,
                "Prediction Mixing defines no adapter settings in this prototype.",
                field_path="adapter_settings",
            )
        )

    active_layers = document.active_layers
    active_count = len(active_layers)
    if active_count < PREDICTION_MIXING_CAPABILITY.minimum_visible_prompt_layers:
        errors.append(
            _finding(
                "capability.active_layer_minimum",
                FindingSeverity.ERROR,
                "Prediction Mixing requires at least one visible Prompt Layer.",
                field_path="layers",
            )
        )
    elif active_count > PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers:
        maximum = (
            PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers
        )
        errors.append(
            _finding(
                "capability.active_layer_limit",
                FindingSeverity.ERROR,
                f"Prediction Mixing supports at most {maximum} visible Prompt Layers.",
                field_path="layers",
            )
        )

    zero_strength_layer_ids: list[str] = []
    for layer in active_layers:
        reference = layer.influence_field
        if reference is None:
            errors.append(
                _finding(
                    "capability.field_required",
                    FindingSeverity.ERROR,
                    "Each visible Prompt Layer requires an Influence Field reference.",
                    layer_id=layer.layer_id,
                    field_path="influence_field",
                )
            )
        elif isinstance(reference, InfluenceFieldAssetReference):
            relative_path = reference.relative_path
            if isinstance(relative_path, str) and not relative_path.lower().endswith(
                ".png"
            ):
                errors.append(
                    _finding(
                        "capability.field_format",
                        FindingSeverity.ERROR,
                        "Each visible Prompt Layer requires a PNG Influence Field reference.",
                        layer_id=layer.layer_id,
                        field_path="influence_field.relative_path",
                    )
                )

        strength = layer.strength
        if (
            isinstance(strength, (int, float))
            and not isinstance(strength, bool)
            and math.isfinite(strength)
            and strength == 0.0
        ):
            zero_strength_layer_ids.append(layer.layer_id)

    _append_standard_warnings(warnings)

    if active_count == 1:
        _append_unique(
            warnings,
            _finding(
                "evidence.one_layer_subset",
                FindingSeverity.WARNING,
                "One visible layer is supported as a constrained subset with less direct evidence than two-layer assignment.",
                field_path="layers",
            ),
        )
    elif active_count == 2:
        information.append(
            _finding(
                "evidence.two_layer_observed",
                FindingSeverity.INFORMATION,
                "Two visible layers match the strongest direct Phase 1 Prediction Mixing evidence.",
                field_path="layers",
            )
        )

    if zero_strength_layer_ids:
        _append_unique(
            warnings,
            _finding(
                "capability.zero_strength_active",
                FindingSeverity.WARNING,
                (
                    "A visible zero-Strength layer still counts as active and must "
                    "remain represented in later provenance."
                ),
                field_path="layers",
            ),
        )

    compatible = not errors
    summary = _build_summary(
        compatible=compatible,
        active_layer_count=active_count,
        warnings=tuple(warnings),
    )
    return CapabilityEvaluation(
        adapter_identifier=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
        selected_adapter_identifier=adapter_id,
        compatible=compatible,
        active_layer_count=active_count,
        errors=tuple(errors),
        warnings=tuple(warnings),
        information=tuple(information),
        capability=PREDICTION_MIXING_CAPABILITY,
        summary=summary,
    )


def validate_prediction_mixing_capability(
    document: ConditioningDocument,
) -> tuple[ValidationFinding, ...]:
    """Compatibility facade over the authoritative capability evaluation.

    The facade retains the original narrow findings-only result shape. It owns
    no policy: eligibility errors and the zero-Strength diagnostic are projected
    from :func:`evaluate_prediction_mixing`.
    """

    evaluation = evaluate_prediction_mixing(document)
    zero_strength_warnings = tuple(
        finding
        for finding in evaluation.warnings
        if finding.code == "capability.zero_strength_active"
    )
    return evaluation.errors + zero_strength_warnings


def _append_standard_warnings(warnings: list[ValidationFinding]) -> None:
    standard = (
        _finding(
            "capability.adapter_experimental",
            FindingSeverity.WARNING,
            "Prediction Mixing is experimental and makes no production-quality claim.",
        ),
        *(
            _finding(risk.code, FindingSeverity.WARNING, risk.message)
            for risk in PREDICTION_MIXING_CAPABILITY.known_risks
        ),
        _finding(
            "capability.strength_non_linear",
            FindingSeverity.WARNING,
            "Strength is requested weighting and is not perceptually linear.",
            field_path="layers.strength",
        ),
        _finding(
            "capability.order_nonsemantic",
            FindingSeverity.WARNING,
            "Retained document order does not express execution priority for this adapter.",
            field_path="layers",
        ),
        _finding(
            "risk.runtime_scaling",
            FindingSeverity.WARNING,
            PREDICTION_MIXING_CAPABILITY.runtime_scaling.statement,
        ),
        _finding(
            "risk.vram",
            FindingSeverity.WARNING,
            PREDICTION_MIXING_CAPABILITY.vram.statement,
        ),
        _finding(
            "evidence.limited",
            FindingSeverity.WARNING,
            "Capability evidence is limited to the recorded Phase 1 configurations.",
        ),
        _finding(
            "capability.continuous_field_tradeoff",
            FindingSeverity.WARNING,
            "Continuous fields can soften boundaries while increasing leakage or fusion.",
            field_path="layers.influence_field",
        ),
    )
    for finding in standard:
        _append_unique(warnings, finding)


def _build_summary(
    *,
    compatible: bool,
    active_layer_count: int,
    warnings: tuple[ValidationFinding, ...],
) -> CapabilitySummary:
    if active_layer_count == 1:
        evidence_scope = (
            "One-layer operation is an inferred constrained subset; strongest direct "
            "Phase 1 evidence is two-layer assignment."
        )
    elif active_layer_count == 2:
        evidence_scope = (
            "Two-layer assignment has the strongest direct Phase 1 evidence; tested "
            "conditions remain limited to the recorded research profile."
        )
    else:
        minimum = PREDICTION_MIXING_CAPABILITY.minimum_visible_prompt_layers
        maximum = (
            PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers
        )
        evidence_scope = (
            "The requested active-layer count is outside the tested "
            f"{minimum}-to-{maximum}-layer range."
        )

    return CapabilitySummary(
        adapter_display_name=PREDICTION_MIXING_CAPABILITY.display_name,
        status=PREDICTION_MIXING_CAPABILITY.status,
        compatible=compatible,
        active_layer_count=active_layer_count,
        tested_maximum=(
            PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers
        ),
        supported_field_behavior=(
            PREDICTION_MIXING_CAPABILITY.imported_png_fields.note,
            PREDICTION_MIXING_CAPABILITY.continuous_fields.note,
        ),
        unsupported_behavior=(
            PREDICTION_MIXING_CAPABILITY.overlap.note,
            PREDICTION_MIXING_CAPABILITY.retained_order_execution.note,
            PREDICTION_MIXING_CAPABILITY.production_quality.note,
        ),
        key_warnings=warnings,
        evidence_scope=evidence_scope,
    )


def _append_unique(
    findings: list[ValidationFinding],
    candidate: ValidationFinding,
) -> None:
    if all(existing.code != candidate.code for existing in findings):
        findings.append(candidate)


def _finding(
    code: str,
    severity: FindingSeverity,
    message: str,
    *,
    layer_id: str | None = None,
    field_path: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity,
        message=message,
        layer_id=layer_id,
        field_path=field_path,
    )
