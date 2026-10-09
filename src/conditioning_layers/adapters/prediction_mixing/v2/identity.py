"""Consumer-safe canonical identity helpers for Translation Plan v2 contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum

from .canonical import portable_value, sha256_canonical
from .models import (
    CapabilityExecutionProjection,
    DocumentExecutionProjection,
    ExecutionProfileProjection,
    OrderedLeftFoldTopologyPolicy,
    TranslationPlanV2,
)


def fingerprint_document_execution_projection(
    projection: DocumentExecutionProjection,
) -> str:
    """Fingerprint every document-projection field except its fingerprint."""

    if not isinstance(projection, DocumentExecutionProjection):
        raise TypeError("projection must be a DocumentExecutionProjection")
    return fingerprint_without_field(projection)


def fingerprint_capability_execution_projection(
    projection: CapabilityExecutionProjection,
) -> str:
    """Fingerprint capability semantics without diagnostic prose."""

    if not isinstance(projection, CapabilityExecutionProjection):
        raise TypeError("projection must be a CapabilityExecutionProjection")
    return fingerprint_without_field(projection)


def fingerprint_execution_profile_projection(
    projection: ExecutionProfileProjection,
) -> str:
    """Fingerprint execution-relevant profile content."""

    if not isinstance(projection, ExecutionProfileProjection):
        raise TypeError("projection must be an ExecutionProfileProjection")
    return fingerprint_without_field(projection)


def fingerprint_topology_policy(policy: OrderedLeftFoldTopologyPolicy) -> str:
    """Fingerprint topology semantics without trusting its name alone."""

    if not isinstance(policy, OrderedLeftFoldTopologyPolicy):
        raise TypeError("policy must be an OrderedLeftFoldTopologyPolicy")
    return fingerprint_without_field(policy)


def fingerprint_translation_plan_v2(plan: TranslationPlanV2) -> str:
    """Fingerprint every plan identity input except its fingerprint."""

    if not isinstance(plan, TranslationPlanV2):
        raise TypeError("plan must be a TranslationPlanV2")
    return fingerprint_without_field(plan)


def fingerprint_without_field(value: object) -> str:
    """Hash one canonical dataclass after removing its fingerprint field."""

    material = portable_value(value)
    if not isinstance(material, dict):
        raise TypeError("fingerprint material must be an object")
    if "fingerprint" not in material:
        raise TypeError("fingerprint material must contain a fingerprint field")
    material.pop("fingerprint")
    return sha256_canonical(material)


def exact_contract_equal(left: object, right: object) -> bool:
    """Compare immutable contract values without Python numeric type aliases."""

    if type(left) is not type(right):
        return False
    if is_dataclass(left):
        return all(
            exact_contract_equal(getattr(left, item.name), getattr(right, item.name))
            for item in fields(left)
        )
    if isinstance(left, Enum):
        return exact_contract_equal(left.value, right.value)
    if type(left) is tuple:
        return len(left) == len(right) and all(
            exact_contract_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if type(left) in (str, int, float, bool, type(None)):
        return left == right
    return False
