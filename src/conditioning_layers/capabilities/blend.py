"""Reviewed exact-cardinality Blend eligibility, separate from product admission.

ADR-0025/0026 govern this additive policy-aware family. The retained router and
all its accepted/rejected inputs remain unchanged. Product admission is owned
by the separate product-aware authority, not these status declarations. ADR-0028
adds exact N=4..9 entries for offline backend use; product defaults stay exact-3.
"""

from dataclasses import asdict, dataclass, fields, replace
import hashlib
import json

from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, NORMALIZED_BLEND,
    CompositionPolicyReference, ConditioningDocument, FindingSeverity,
    InfluenceFieldAssetReference, PREDICTION_MIXING_ADAPTER_ID, ValidationFinding,
    get_effective_composition_policy, validate_document,
)


BLEND_CONTRACT_IDENTIFIER = "prediction-mixing.multi-layer.v2"
BLEND_CONTRACT_VERSION = 2
BLEND_RELATIONSHIP_CONSTRAINT = "prediction-mixing.ordered-stored-positive-overlap-permitted.v1"


@dataclass(frozen=True, slots=True)
class BlendEligibilityEntry:
    identifier: str
    contract_identifier: str
    contract_version: int
    exact_cardinality: int
    adapter_identifier: str
    composition_policy: CompositionPolicyReference
    relationship_constraint: str
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


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint_blend_eligibility(entry: BlendEligibilityEntry) -> str:
    if type(entry) is not BlendEligibilityEntry:
        raise TypeError("An exact BlendEligibilityEntry is required")
    material = asdict(entry)
    material.pop("fingerprint")
    return hashlib.sha256(_canonical(material)).hexdigest()


_ENTRY = BlendEligibilityEntry(
    identifier="prediction-mixing.multi-layer.exact-3.normalized-blend.v1",
    contract_identifier=BLEND_CONTRACT_IDENTIFIER, contract_version=BLEND_CONTRACT_VERSION,
    exact_cardinality=3, adapter_identifier=PREDICTION_MIXING_ADAPTER_ID,
    composition_policy=NORMALIZED_BLEND.reference,
    relationship_constraint=BLEND_RELATIONSHIP_CONSTRAINT,
    condition_kind="homogeneous-prompt-layer-prediction-mixing", layer_kind="Prompt Layer",
    field_format="png", field_encodings=("grayscale_8", "rgb_identical_8"),
    field_width=128, field_height=128, field_reference_required=True,
    field_sha256_required=True, field_nonconstant_required=True,
    field_values_finite=True, field_minimum=0.0, field_maximum=1.0,
    continuous_fields_supported=True,
    field_polarity="stored-zero-none-255-full-before-strength",
    field_orientation="top-left-x-right-y-down", field_transformations="none",
    positive_stored_sample_threshold=0, complete_coverage_required=False,
    strength_minimum=0.0, strength_maximum=1.0,
    effective_weight_expression="u_i = F_i * S_i; w_i = u_i / sum_j u_j at positive support; zero support means no contribution",
    zero_strength_active_is_represented=True, disabled_layers_excluded=True,
    retained_order_semantics="retained-for-repeatability-no-execution-priority",
    adapter_settings_supported=False, fingerprint="",
)
EXACT_THREE_BLEND_ELIGIBILITY = replace(_ENTRY, fingerprint=fingerprint_blend_eligibility(_ENTRY))


def _reviewed_exact_entry(identifier, cardinality):
    entry = replace(EXACT_THREE_BLEND_ELIGIBILITY, identifier=identifier,
                    exact_cardinality=cardinality, fingerprint="")
    return replace(entry, fingerprint=fingerprint_blend_eligibility(entry))


# Fixed source declarations, never constructed from document or caller input.
EXACT_FOUR_BLEND_ELIGIBILITY = _reviewed_exact_entry(
    "prediction-mixing.multi-layer.exact-4.normalized-blend.v1", 4)
EXACT_FIVE_BLEND_ELIGIBILITY = _reviewed_exact_entry(
    "prediction-mixing.multi-layer.exact-5.normalized-blend.v1", 5)
EXACT_SIX_BLEND_ELIGIBILITY = _reviewed_exact_entry(
    "prediction-mixing.multi-layer.exact-6.normalized-blend.v1", 6)
EXACT_SEVEN_BLEND_ELIGIBILITY = _reviewed_exact_entry(
    "prediction-mixing.multi-layer.exact-7.normalized-blend.v1", 7)
EXACT_EIGHT_BLEND_ELIGIBILITY = _reviewed_exact_entry(
    "prediction-mixing.multi-layer.exact-8.normalized-blend.v1", 8)
EXACT_NINE_BLEND_ELIGIBILITY = _reviewed_exact_entry(
    "prediction-mixing.multi-layer.exact-9.normalized-blend.v1", 9)

# Reviewed content is independent of registration: replacing a registered entry
# with a self-consistent forgery cannot make that forgery trusted authority.
_REVIEWED_ENTRIES = (
    EXACT_THREE_BLEND_ELIGIBILITY, EXACT_FOUR_BLEND_ELIGIBILITY,
    EXACT_FIVE_BLEND_ELIGIBILITY, EXACT_SIX_BLEND_ELIGIBILITY,
    EXACT_SEVEN_BLEND_ELIGIBILITY, EXACT_EIGHT_BLEND_ELIGIBILITY,
    EXACT_NINE_BLEND_ELIGIBILITY,
)
REGISTERED_BLEND_ELIGIBILITY_ENTRIES = _REVIEWED_ENTRIES
# These retained declarations describe exact-3 product status only.
BLEND_PRODUCT_ADMITTED = True
BLEND_LIVE_QUALIFIED = True


def _matches_reviewed_entry(entry, reviewed):
    return (
        type(entry) is BlendEligibilityEntry
        and all(type(getattr(entry, item.name)) is type(getattr(reviewed, item.name))
                for item in fields(entry))
        and fingerprint_blend_eligibility(entry) == entry.fingerprint
        and _canonical(asdict(entry)) == _canonical(asdict(reviewed))
    )


def verify_blend_eligibility(entry: object) -> tuple[ValidationFinding, ...]:
    """Self-consistent fingerprints cannot invent or widen registration."""
    try:
        reviewed = tuple(item for item in _REVIEWED_ENTRIES if item.identifier == entry.identifier)
        registered = tuple(item for item in REGISTERED_BLEND_ELIGIBILITY_ENTRIES
                           if item.identifier == entry.identifier)
        valid = (
            len(reviewed) == 1 and len(registered) == 1
            and _matches_reviewed_entry(entry, reviewed[0])
            and _matches_reviewed_entry(registered[0], reviewed[0])
            # A second ID cannot shadow this exact contract/count route, even
            # with a different policy, fingerprint or other forged constraints.
            and sum(item.contract_identifier == reviewed[0].contract_identifier
                    and item.exact_cardinality == reviewed[0].exact_cardinality
                    for item in REGISTERED_BLEND_ELIGIBILITY_ENTRIES) == 1
        )
    except (TypeError, ValueError, AttributeError, UnicodeError):
        valid = False
    return () if valid else (_error("blend.eligibility.invalid", "Blend eligibility must match committed exact-three authority."),)


def evaluate_blend_eligibility(
    document: ConditioningDocument, entry: object = EXACT_THREE_BLEND_ELIGIBILITY,
) -> tuple[ValidationFinding, ...]:
    """Backend intent eligibility only: no admission, host or component claim."""
    errors = list(verify_blend_eligibility(entry))
    if not isinstance(document, ConditioningDocument):
        return tuple(errors) + (_error("blend.document.invalid", "A Conditioning Document is required."),)
    errors.extend(item for item in validate_document(document) if item.severity is FindingSeverity.ERROR)
    if errors:
        return tuple(errors)
    if (document.version != COMPOSITION_POLICY_PROTOTYPE_VERSION
            or get_effective_composition_policy(document) != NORMALIZED_BLEND):
        errors.append(_error("blend.policy.unsupported", "The explicit policy-bearing document must select Normalized Blend."))
    if document.selected_adapter_id != PREDICTION_MIXING_ADAPTER_ID or document.adapter_settings:
        errors.append(_error("blend.adapter.unsupported", "Blend requires the retained adapter without settings."))
    if len(document.active_layers) != entry.exact_cardinality:
        errors.append(_error("blend.cardinality.unsupported", "The sole Blend eligibility entry requires exactly three Active Prompt Layers."))
    for layer in document.active_layers:
        if (not isinstance(layer.influence_field, InfluenceFieldAssetReference)
                or not layer.influence_field.relative_path.lower().endswith(".png")):
            errors.append(_error("blend.field.required", "Every Active Prompt Layer requires its authored PNG."))
    return tuple(errors)


def select_blend_eligibility(document: ConditioningDocument) -> BlendEligibilityEntry:
    if evaluate_blend_eligibility(document):
        raise ValueError("No registered Blend route matches this document")
    return EXACT_THREE_BLEND_ELIGIBILITY


def _error(code, message):
    return ValidationFinding(code, FindingSeverity.ERROR, message)
