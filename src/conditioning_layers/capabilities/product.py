"""Bounded product dispatch over retained ordinary, No Overlap and Blend APIs.

Admission is repository authority, never request/UI/environment configuration.
None means inherit the CURRENT legacy set at call time plus the admitted exact-3
Blend entry. Only offline fixtures override this value. Admission is governed by
P3D_EXACT3_PRODUCT_ADMISSION_DECISION.md, independently of status declarations.
"""

from dataclasses import dataclass

from conditioning_layers.domain import (
    NORMALIZED_BLEND, REQUIRE_NO_OVERLAP, ConditioningDocument, FindingSeverity,
    ValidationFinding, get_effective_composition_policy, validate_document,
)
from . import multi_layer
from .blend import (
    BLEND_CONTRACT_IDENTIFIER, EXACT_THREE_BLEND_ELIGIBILITY,
    evaluate_blend_eligibility, verify_blend_eligibility,
)


PRODUCT_ADMITTED_ENTRIES: tuple[str, ...] | None = None


def product_admitted_entries() -> tuple[str, ...]:
    legacy = multi_layer.PRODUCT_ADMITTED_ENTRIES
    # A Blend identifier accidentally appended to the old table cannot admit it.
    multi_layer.product_supported_cardinalities(legacy)
    selected = (legacy + (EXACT_THREE_BLEND_ELIGIBILITY.identifier,)
                if PRODUCT_ADMITTED_ENTRIES is None else PRODUCT_ADMITTED_ENTRIES)
    if (type(selected) is not tuple or any(type(item) is not str for item in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError("Product admission must be a unique immutable entry set")
    retained = tuple(item for item in selected if item != EXACT_THREE_BLEND_ELIGIBILITY.identifier)
    multi_layer.product_supported_cardinalities(retained)
    if EXACT_THREE_BLEND_ELIGIBILITY.identifier in selected and verify_blend_eligibility(EXACT_THREE_BLEND_ELIGIBILITY):
        raise ValueError("Product admission requires reviewed Blend eligibility")
    return selected


def product_policy_cardinalities() -> dict[str, tuple[int, ...]]:
    selected = product_admitted_entries()
    return {
        REQUIRE_NO_OVERLAP.identifier: multi_layer.product_supported_cardinalities(
            tuple(item for item in selected if item != EXACT_THREE_BLEND_ELIGIBILITY.identifier)),
        NORMALIZED_BLEND.identifier: ((3,) if EXACT_THREE_BLEND_ELIGIBILITY.identifier in selected else ()),
    }


def product_supported_cardinalities() -> tuple[int, ...]:
    return tuple(sorted({count for counts in product_policy_cardinalities().values() for count in counts}))


@dataclass(frozen=True, slots=True)
class ProductRoute:
    contract_identifier: str | None
    eligibility_entry: object | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...] = ()

    @property
    def compatible(self) -> bool:
        return self.contract_identifier is not None and not self.errors


def route_product_prediction_mixing(document: ConditioningDocument, *, qualification_entry=None) -> ProductRoute:
    errors = tuple(item for item in validate_document(document) if item.severity is FindingSeverity.ERROR)
    if errors:
        return ProductRoute(None, None, errors)
    try:
        admitted = product_admitted_entries()
    except ValueError:
        return ProductRoute(None, None, (_error("capability.product_admission_invalid", "Product admission authority is invalid."),))
    if get_effective_composition_policy(document) != NORMALIZED_BLEND:
        legacy = multi_layer.route_prediction_mixing(
            document, qualification_entry=qualification_entry,
            product_admitted_entries=tuple(item for item in admitted if item != EXACT_THREE_BLEND_ELIGIBILITY.identifier),
        )
        return ProductRoute(legacy.contract_identifier, legacy.eligibility_entry, legacy.errors, legacy.warnings)
    entry = EXACT_THREE_BLEND_ELIGIBILITY
    errors = evaluate_blend_eligibility(document, entry)
    if qualification_entry is not None:
        errors += (_error("capability.product_route_mismatch", "No Overlap qualification selection cannot select Blend."),)
    if entry.identifier not in admitted:
        errors += (_error("capability.product_not_admitted", "Blend is qualified but not product admitted. The document can be edited and saved."),)
    return ProductRoute(BLEND_CONTRACT_IDENTIFIER, entry, errors)


def _error(code, message):
    return ValidationFinding(code, FindingSeverity.ERROR, message)
