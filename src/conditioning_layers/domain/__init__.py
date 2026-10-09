"""Pure document-domain models, operations, and validation."""

from .composition_policy import (
    COMPOSITION_POLICY_FAMILY_ID,
    NORMALIZED_BLEND,
    REGISTERED_COMPOSITION_POLICIES,
    REQUIRE_NO_OVERLAP,
    CompositionPolicyError,
    CompositionPolicyRecord,
    CompositionPolicyReference,
    resolve_composition_policy,
)
from .errors import (
    DomainOperationError,
    DuplicateLayerIdError,
    InvalidLayerPositionError,
    LayerNotFoundError,
)
from .models import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION,
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
    PrototypeDocumentVersion,
    get_effective_composition_policy,
)
from .validation import (
    PREDICTION_MIXING_ADAPTER_ID,
    FindingSeverity,
    ValidationFinding,
    validate_document,
)

__all__ = [
    "COMPOSITION_POLICY_FAMILY_ID",
    "COMPOSITION_POLICY_PROTOTYPE_VERSION",
    "CURRENT_PROTOTYPE_VERSION",
    "PREDICTION_MIXING_ADAPTER_ID",
    "ConditioningDocument",
    "CompositionPolicyError",
    "CompositionPolicyRecord",
    "CompositionPolicyReference",
    "DomainOperationError",
    "DuplicateLayerIdError",
    "FindingSeverity",
    "InfluenceFieldAssetReference",
    "InvalidLayerPositionError",
    "LayerNotFoundError",
    "NORMALIZED_BLEND",
    "PromptLayer",
    "PrototypeDocumentVersion",
    "REGISTERED_COMPOSITION_POLICIES",
    "REQUIRE_NO_OVERLAP",
    "ValidationFinding",
    "get_effective_composition_policy",
    "resolve_composition_policy",
    "validate_document",
]
