"""Internal ADR-0028 offline selector; never imported by product entry points.

The explicit IDs select existing reviewed registrations. Count, policy, caller
fingerprints, product status and a maximum cannot manufacture backend authority.
There is deliberately no registry, configuration or admission argument.
"""

from conditioning_layers.domain import ConditioningDocument
from . import blend


_OFFLINE_ENTRY_IDS = (
    "prediction-mixing.multi-layer.exact-4.normalized-blend.v1",
    "prediction-mixing.multi-layer.exact-5.normalized-blend.v1",
    "prediction-mixing.multi-layer.exact-6.normalized-blend.v1",
    "prediction-mixing.multi-layer.exact-7.normalized-blend.v1",
    "prediction-mixing.multi-layer.exact-8.normalized-blend.v1",
    "prediction-mixing.multi-layer.exact-9.normalized-blend.v1",
)


def select_bounded_blend_eligibility(document: ConditioningDocument) -> blend.BlendEligibilityEntry:
    """Select one committed exact entry for explicit offline backend planning."""
    try:
        if not isinstance(document, ConditioningDocument):
            raise ValueError("A Conditioning Document is required")
        matches = tuple(entry for entry in blend.REGISTERED_BLEND_ELIGIBILITY_ENTRIES
                        if entry.identifier in _OFFLINE_ENTRY_IDS
                        and entry.exact_cardinality == len(document.active_layers))
        if len(matches) == 1 and not blend.evaluate_blend_eligibility(document, matches[0]):
            return matches[0]
    except (TypeError, AttributeError):
        pass
    raise ValueError("No reviewed exact offline Blend entry matches this document")
