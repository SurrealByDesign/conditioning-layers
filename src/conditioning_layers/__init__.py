"""Backend-neutral Conditioning Layers prototype core."""

from .domain import (
    CURRENT_PROTOTYPE_VERSION,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    PrototypeDocumentVersion,
    ValidationFinding,
    validate_document,
)
from .capabilities import validate_prediction_mixing_capability

__all__ = [
    "CURRENT_PROTOTYPE_VERSION",
    "PREDICTION_MIXING_ADAPTER_ID",
    "ConditioningDocument",
    "FindingSeverity",
    "InfluenceFieldAssetReference",
    "PromptLayer",
    "PrototypeDocumentVersion",
    "ValidationFinding",
    "validate_document",
    "validate_prediction_mixing_capability",
]
