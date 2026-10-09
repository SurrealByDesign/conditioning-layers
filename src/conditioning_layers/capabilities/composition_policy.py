"""Fail-closed boundary between persisted policy intent and retained execution."""

from __future__ import annotations

from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION,
    CURRENT_PROTOTYPE_VERSION,
    REQUIRE_NO_OVERLAP,
    CompositionPolicyError,
    ConditioningDocument,
    FindingSeverity,
    PrototypeDocumentVersion,
    ValidationFinding,
    get_effective_composition_policy,
)


def retained_execution_policy_findings(
    document: ConditioningDocument,
) -> tuple[ValidationFinding, ...]:
    """Admit only the unchanged legacy document/policy execution boundary.

    Known, persistable policy intent does not establish an executable contract.
    Separate backend successors do not change this retained product boundary.
    """

    version = document.version
    successor_version = (
        isinstance(version, PrototypeDocumentVersion)
        and type(version.major) is int and type(version.minor) is int
        and version == COMPOSITION_POLICY_PROTOTYPE_VERSION
    )
    if document.composition_policy is None and not successor_version:
        # Pre-existing inputs keep the retained evaluator's validation behavior,
        # including historical newer-minor warnings and malformed-version errors.
        return ()
    try:
        policy = get_effective_composition_policy(document)
    except (CompositionPolicyError, TypeError, ValueError):
        return (_error(
            "capability.composition_policy_invalid",
            "The document Composition Policy cannot be resolved exactly.",
            "composition_policy",
        ),)
    if policy != REQUIRE_NO_OVERLAP:
        return (_error(
            "capability.composition_policy_not_realizable",
            "This Composition Policy is known authored intent, but has no retained product execution route or product admission.",
            "composition_policy",
        ),)
    if document.version != CURRENT_PROTOTYPE_VERSION:
        return (_error(
            "capability.document_execution_format_unsupported",
            "This document format can be saved and opened, but has no retained execution projection.",
            "version",
        ),)
    return ()


def _error(code: str, message: str, field_path: str) -> ValidationFinding:
    return ValidationFinding(
        code=code, severity=FindingSeverity.ERROR,
        message=message, field_path=field_path,
    )
