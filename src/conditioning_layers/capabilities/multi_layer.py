"""ADR-0024 selected exact-cardinality authority and product admission.

This authority is additive. The ordinary capability/evaluator remain frozen.
Registration establishes executable eligibility, never product admission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json

from conditioning_layers.domain import (
    CompositionPolicyReference, ConditioningDocument, FindingSeverity, InfluenceFieldAssetReference,
    PREDICTION_MIXING_ADAPTER_ID, REQUIRE_NO_OVERLAP, ValidationFinding,
    get_effective_composition_policy, validate_document,
)

from .evaluation import _append_standard_warnings, evaluate_prediction_mixing
from .composition_policy import retained_execution_policy_findings
from .models import CapabilityEvaluation


ORDINARY_V1_CONTRACT_IDENTIFIER = "prediction-mixing.ordinary-v1"
MULTI_LAYER_CONTRACT_IDENTIFIER = "prediction-mixing.multi-layer.v1"
MULTI_LAYER_CONTRACT_VERSION = 1
ORDINARY_PRODUCT_ENTRY_IDENTIFIER = "prediction-mixing.ordinary-v1.one-or-two"


@dataclass(frozen=True, slots=True)
class MultiLayerEligibilityEntry:
    identifier: str
    contract_identifier: str
    contract_version: int
    exact_cardinality: int
    adapter_identifier: str
    condition_kind: str
    layer_kind: str
    field_format: str
    field_encodings: tuple[str, ...]
    field_width: int
    field_height: int
    field_reference_required: bool
    field_sha256_required: bool
    field_nonconstant_required: bool
    field_values_finite: bool
    field_minimum: float
    field_maximum: float
    continuous_fields_supported: bool
    field_polarity: str
    field_orientation: str
    field_transformations: str
    overlap_policy: str
    positive_stored_sample_threshold: int
    complete_coverage_required: bool
    strength_minimum: float
    strength_maximum: float
    effective_weight_expression: str
    zero_strength_active_is_represented: bool
    disabled_layers_excluded: bool
    retained_order_semantics: str
    adapter_settings_supported: bool
    fingerprint: str


def fingerprint_eligibility_entry(entry: MultiLayerEligibilityEntry) -> str:
    if not isinstance(entry, MultiLayerEligibilityEntry):
        raise TypeError("entry must be a MultiLayerEligibilityEntry")
    material = asdict(entry)
    material.pop("fingerprint")
    return hashlib.sha256(_canonical(material)).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


_ENTRY = MultiLayerEligibilityEntry(
    identifier="prediction-mixing.multi-layer.exact-3.v1",
    contract_identifier=MULTI_LAYER_CONTRACT_IDENTIFIER,
    contract_version=MULTI_LAYER_CONTRACT_VERSION,
    exact_cardinality=3,
    adapter_identifier=PREDICTION_MIXING_ADAPTER_ID,
    condition_kind="homogeneous-prompt-layer-prediction-mixing",
    layer_kind="Prompt Layer",
    field_format="png",
    field_encodings=("grayscale_8", "rgb_identical_8"),
    field_width=128, field_height=128,
    field_reference_required=True, field_sha256_required=True,
    field_nonconstant_required=True, field_values_finite=True,
    field_minimum=0.0, field_maximum=1.0,
    continuous_fields_supported=True,
    field_polarity="stored-zero-none-255-full-before-strength",
    field_orientation="top-left-x-right-y-down",
    field_transformations="none",
    overlap_policy="require_no_overlap", positive_stored_sample_threshold=0,
    complete_coverage_required=False,
    strength_minimum=0.0, strength_maximum=1.0,
    effective_weight_expression="effective field weight = normalized field value × requested Strength",
    zero_strength_active_is_represented=True, disabled_layers_excluded=True,
    retained_order_semantics="retained-for-repeatability-no-execution-priority",
    adapter_settings_supported=False,
    fingerprint="",
)
EXACT_THREE_ELIGIBILITY = replace(_ENTRY, fingerprint=fingerprint_eligibility_entry(_ENTRY))
# Independent committed semantic authority; supplied registries cannot register themselves.
_REVIEWED_EXACT_THREE = EXACT_THREE_ELIGIBILITY
REGISTERED_ELIGIBILITY_ENTRIES = (EXACT_THREE_ELIGIBILITY,)
PRODUCT_ADMITTED_ENTRIES = (ORDINARY_PRODUCT_ENTRY_IDENTIFIER, EXACT_THREE_ELIGIBILITY.identifier)


POLICY_BOUND_ELIGIBILITY_IDENTIFIER = "prediction-mixing.policy-bound-eligibility.v1"
POLICY_BOUND_ELIGIBILITY_VERSION = 1


@dataclass(frozen=True, slots=True)
class PolicyBoundEligibilityEntry:
    """Policy-bearing successor representation of selected eligibility authority.

    This semantic binding refers to independently reviewed eligibility. It does
    not register a new executable entry, realization, or product admission.
    Relationship evidence requirements and document policy are separate values.
    """

    format_identifier: str
    format_version: int
    eligibility_entry_identifier: str
    eligibility_entry_fingerprint: str
    contract_identifier: str
    contract_version: int
    exact_cardinality: int
    relationship_constraint: str
    composition_policy: CompositionPolicyReference
    fingerprint: str


def fingerprint_policy_bound_eligibility(entry: PolicyBoundEligibilityEntry) -> str:
    if not isinstance(entry, PolicyBoundEligibilityEntry):
        raise TypeError("entry must be a PolicyBoundEligibilityEntry")
    material = asdict(entry)
    material.pop("fingerprint")
    return hashlib.sha256(_canonical(material)).hexdigest()


_POLICY_BOUND_EXACT_THREE = PolicyBoundEligibilityEntry(
    format_identifier=POLICY_BOUND_ELIGIBILITY_IDENTIFIER,
    format_version=POLICY_BOUND_ELIGIBILITY_VERSION,
    eligibility_entry_identifier=EXACT_THREE_ELIGIBILITY.identifier,
    eligibility_entry_fingerprint=EXACT_THREE_ELIGIBILITY.fingerprint,
    contract_identifier=EXACT_THREE_ELIGIBILITY.contract_identifier,
    contract_version=EXACT_THREE_ELIGIBILITY.contract_version,
    exact_cardinality=EXACT_THREE_ELIGIBILITY.exact_cardinality,
    relationship_constraint="mutually-exclusive-positive-stored-samples",
    composition_policy=REQUIRE_NO_OVERLAP.reference,
    fingerprint="",
)
POLICY_BOUND_EXACT_THREE = replace(
    _POLICY_BOUND_EXACT_THREE,
    fingerprint=fingerprint_policy_bound_eligibility(_POLICY_BOUND_EXACT_THREE),
)
_REVIEWED_POLICY_BOUND_EXACT_THREE = POLICY_BOUND_EXACT_THREE


def verify_policy_bound_eligibility(entry: object) -> tuple[ValidationFinding, ...]:
    """Reject invented bindings even when their fingerprint is self-consistent."""

    if type(entry) is not PolicyBoundEligibilityEntry:
        return (_error("capability.policy_eligibility_invalid", "Policy-bearing eligibility is malformed."),)
    if (
        any(type(value) is not str for value in (
            entry.format_identifier, entry.eligibility_entry_identifier,
            entry.eligibility_entry_fingerprint, entry.contract_identifier,
            entry.relationship_constraint, entry.fingerprint,
        ))
        or any(type(value) is not int for value in (
            entry.format_version, entry.contract_version, entry.exact_cardinality,
        ))
        or type(entry.composition_policy) is not CompositionPolicyReference
        or type(entry.composition_policy.policy_identifier) is not str
        or type(entry.composition_policy.policy_version) is not int
    ):
        return (_error("capability.policy_eligibility_invalid", "Policy-bearing eligibility requires its exact canonical representation."),)
    retained_errors = verify_eligibility_entry(EXACT_THREE_ELIGIBILITY)
    try:
        valid = (
            fingerprint_policy_bound_eligibility(entry) == entry.fingerprint
            and _canonical(asdict(entry)) == _canonical(asdict(_REVIEWED_POLICY_BOUND_EXACT_THREE))
        )
    except (TypeError, ValueError, UnicodeError):
        valid = False
    if not valid:
        return retained_errors + (_error(
            "capability.policy_eligibility_unregistered",
            "No reviewed policy-bearing eligibility authority matches this binding.",
        ),)
    return retained_errors


def select_policy_bound_eligibility(
    document: ConditioningDocument, *,
    contract_identifier: str = MULTI_LAYER_CONTRACT_IDENTIFIER,
    contract_version: int = MULTI_LAYER_CONTRACT_VERSION,
    relationship_constraint: str = "mutually-exclusive-positive-stored-samples",
) -> PolicyBoundEligibilityEntry:
    """Select neutral authority offline, without granting execution or admission.

    Only the retained exact-three No Overlap binding exists. Blend cannot inherit
    this entry merely because its field geometry happens to be non-overlapping.
    """

    if not isinstance(document, ConditioningDocument):
        raise TypeError("document must be a ConditioningDocument")
    if any(item.severity is FindingSeverity.ERROR for item in validate_document(document)):
        raise ValueError("document is invalid for policy-bearing eligibility selection")
    policy = get_effective_composition_policy(document)
    selected = POLICY_BOUND_EXACT_THREE
    if (
        type(contract_identifier) is not str or type(contract_version) is not int
        or type(relationship_constraint) is not str
        or contract_identifier != selected.contract_identifier
        or contract_version != selected.contract_version
        or len(document.active_layers) != selected.exact_cardinality
        or relationship_constraint != selected.relationship_constraint
        or policy.reference != selected.composition_policy
        or document.selected_adapter_id != EXACT_THREE_ELIGIBILITY.adapter_identifier
        or bool(document.adapter_settings)
        or verify_policy_bound_eligibility(selected)
    ):
        raise ValueError("no reviewed policy-bearing eligibility matches the selected contract, count, relationship, and policy")
    return selected


def multi_layer_warnings(*, zero_strength_active: bool = False) -> tuple[ValidationFinding, ...]:
    """Retain applicable experimental field/Strength/order/risk evidence."""
    warnings: list[ValidationFinding] = []
    _append_standard_warnings(warnings)
    if zero_strength_active:
        warnings.append(ValidationFinding(
            code="capability.zero_strength_active", severity=FindingSeverity.WARNING,
            message="A visible zero-Strength layer remains counted, inspected, and represented.",
            field_path="layers",
        ))
    return tuple(warnings)


def verify_eligibility_entry(
    entry: object, *, registry: tuple[MultiLayerEligibilityEntry, ...] | None = None,
) -> tuple[ValidationFinding, ...]:
    """Recompute and compare selected authority; unrelated entries are not hashed."""
    if not isinstance(entry, MultiLayerEligibilityEntry):
        return (_error("capability.eligibility_invalid", "Eligibility entry is malformed."),)
    entries = REGISTERED_ELIGIBILITY_ENTRIES if registry is None else registry
    if not isinstance(entries, tuple) or not all(isinstance(item, MultiLayerEligibilityEntry) for item in entries):
        return (_error("capability.eligibility_registry_invalid", "Eligibility registry is malformed."),)
    if any(type(item.identifier) is not str or not item.identifier
           or type(item.contract_identifier) is not str or not item.contract_identifier
           or type(item.exact_cardinality) is not int or item.exact_cardinality < 1 for item in entries):
        return (_error("capability.eligibility_registry_invalid", "Eligibility registry route keys are malformed."),)
    identities = tuple(item.identifier for item in entries)
    routes = tuple((item.contract_identifier, item.exact_cardinality) for item in entries)
    if len(set(identities)) != len(identities) or len(set(routes)) != len(routes):
        return (_error("capability.eligibility_shadowed", "Eligibility authority is ambiguous."),)
    matches = tuple(item for item in entries if item.identifier == entry.identifier)
    if not matches:
        return (_error("capability.eligibility_unregistered", "Eligibility entry is not registered."),)
    try:
        valid = (
            fingerprint_eligibility_entry(entry) == entry.fingerprint
            and _canonical(asdict(entry)) == _canonical(asdict(matches[0]))
            and _canonical(asdict(entry)) == _canonical(asdict(_REVIEWED_EXACT_THREE))
        )
    except (TypeError, ValueError, UnicodeError):
        valid = False
    if not valid:
        return (_error("capability.eligibility_identity_mismatch", "Selected immutable eligibility authority differs from reviewed content."),)
    return ()


def product_supported_cardinalities(
    admitted_entries: tuple[str, ...] | None = None,
) -> tuple[int, ...]:
    """Project the actual admitted set, without assuming a contiguous range."""
    selected = PRODUCT_ADMITTED_ENTRIES if admitted_entries is None else admitted_entries
    if not isinstance(selected, tuple) or not all(type(item) is str for item in selected) or len(set(selected)) != len(selected):
        raise ValueError("Product admission must be a unique immutable entry set")
    counts: set[int] = set()
    for identifier in selected:
        if identifier == ORDINARY_PRODUCT_ENTRY_IDENTIFIER:
            counts.update((1, 2))
        else:
            matches = tuple(item for item in REGISTERED_ELIGIBILITY_ENTRIES if item.identifier == identifier)
            if len(matches) != 1 or verify_eligibility_entry(matches[0]):
                raise ValueError("Product admission references unknown eligibility")
            counts.add(matches[0].exact_cardinality)
    return tuple(sorted(counts))


@dataclass(frozen=True, slots=True)
class PredictionMixingRoute:
    contract_identifier: str | None
    eligibility_entry: MultiLayerEligibilityEntry | None
    active_layer_count: int
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    ordinary_evaluation: CapabilityEvaluation | None
    qualification_selected: bool

    @property
    def compatible(self) -> bool:
        return not self.errors and self.contract_identifier is not None


def evaluate_multi_layer_eligibility(
    document: ConditioningDocument, entry: object = EXACT_THREE_ELIGIBILITY,
) -> tuple[ValidationFinding, ...]:
    """Validate selected-entry intent without applying product admission."""
    errors = list(verify_eligibility_entry(entry))
    if not isinstance(document, ConditioningDocument):
        return tuple(errors) + (_error("capability.document_invalid", "Document is malformed."),)
    errors.extend(item for item in validate_document(document) if item.severity is FindingSeverity.ERROR)
    errors.extend(retained_execution_policy_findings(document))
    if document.selected_adapter_id != PREDICTION_MIXING_ADAPTER_ID:
        errors.append(_error("capability.adapter_unsupported", "Select the supported Prediction Mixing adapter."))
    if document.adapter_settings:
        errors.append(_error("capability.adapter_settings_unsupported", "Prediction Mixing defines no adapter settings."))
    if isinstance(entry, MultiLayerEligibilityEntry) and len(document.active_layers) != entry.exact_cardinality:
        errors.append(_error("capability.exact_cardinality_mismatch", "Active Prompt Layer count must equal selected eligibility cardinality."))
    for layer in document.active_layers:
        reference = layer.influence_field
        if not isinstance(reference, InfluenceFieldAssetReference):
            errors.append(_error("capability.field_required", "Every Active Prompt Layer requires an Influence Field.", layer.layer_id))
        elif not isinstance(reference.relative_path, str) or not reference.relative_path.lower().endswith(".png"):
            errors.append(_error("capability.field_format", "Every Active Influence Field must be PNG.", layer.layer_id))
    return tuple(errors)


def route_prediction_mixing(
    document: ConditioningDocument, *,
    qualification_entry: MultiLayerEligibilityEntry | None = None,
    product_admitted_entries: tuple[str, ...] | None = None,
) -> PredictionMixingRoute:
    """Internal deterministic router; no selector is accepted from product input.

    Governed qualification may bypass only admission by selecting the registered
    exact entry. It cannot widen cardinality, change authority, or select v1.
    """
    if not isinstance(document, ConditioningDocument):
        raise TypeError("document must be a ConditioningDocument")
    count = len(document.active_layers)
    policy_errors = retained_execution_policy_findings(document)
    if policy_errors:
        errors = tuple(item for item in validate_document(document) if item.severity is FindingSeverity.ERROR)
        return PredictionMixingRoute(None, None, count, errors + policy_errors, (), None, False)
    if count < 3 and qualification_entry is None:
        evaluation = evaluate_prediction_mixing(document)
        admitted = PRODUCT_ADMITTED_ENTRIES if product_admitted_entries is None else product_admitted_entries
        errors = evaluation.errors
        if ORDINARY_PRODUCT_ENTRY_IDENTIFIER not in admitted:
            errors += (_error("capability.product_not_admitted", "Ordinary execution is not product admitted."),)
        return PredictionMixingRoute(
            ORDINARY_V1_CONTRACT_IDENTIFIER if count in (1, 2) else None,
            None, count, errors, evaluation.warnings, evaluation, False,
        )
    if count >= 4:
        errors = tuple(item for item in validate_document(document) if item.severity is FindingSeverity.ERROR)
        return PredictionMixingRoute(None, None, count, errors + (_error("capability.active_layer_limit", "No execution contract admits this Active Prompt Layer count."),), (), None, False)
    entry = EXACT_THREE_ELIGIBILITY if qualification_entry is None else qualification_entry
    errors = evaluate_multi_layer_eligibility(document, entry)
    if qualification_entry is None:
        admitted = PRODUCT_ADMITTED_ENTRIES if product_admitted_entries is None else product_admitted_entries
        if entry.identifier not in admitted:
            errors += (_error("capability.product_not_admitted", "Three Active Prompt Layers await live qualification and explicit product admission."),)
            counts = product_supported_cardinalities(admitted)
            errors += (_error("capability.active_layer_limit", "Product generation supports these Active Prompt Layer counts: "
                              + ", ".join(str(count) for count in counts) + "."),)
    warnings = tuple(item for item in validate_document(document) if item.severity is FindingSeverity.WARNING)
    warnings += multi_layer_warnings(zero_strength_active=any(layer.strength == 0.0 for layer in document.active_layers))
    return PredictionMixingRoute(MULTI_LAYER_CONTRACT_IDENTIFIER, entry, count, errors, warnings, None, qualification_entry is not None)


def _error(code: str, message: str, layer_id: str | None = None) -> ValidationFinding:
    return ValidationFinding(code=code, severity=FindingSeverity.ERROR,
                             message=message, layer_id=layer_id, field_path="layers")
