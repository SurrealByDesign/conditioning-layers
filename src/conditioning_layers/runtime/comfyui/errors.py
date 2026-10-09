"""Shared deterministic findings for local runtime preparation."""

from __future__ import annotations

from collections.abc import Iterable

from conditioning_layers.domain import FindingSeverity, ValidationFinding


def runtime_finding(
    code: str,
    severity: FindingSeverity,
    message: str,
    *,
    layer_id: str | None = None,
    field_path: str | None = None,
) -> ValidationFinding:
    """Create one structured runtime finding."""

    return ValidationFinding(
        code=code,
        severity=severity,
        message=message,
        layer_id=layer_id,
        field_path=field_path,
    )


def deduplicate_findings(
    findings: Iterable[ValidationFinding],
) -> tuple[ValidationFinding, ...]:
    """Retain deterministic order while removing duplicate diagnostic identity."""

    unique: list[ValidationFinding] = []
    seen: set[tuple[str, FindingSeverity, str | None, str | None]] = set()
    for finding in findings:
        key = (
            finding.code,
            finding.severity,
            finding.layer_id,
            finding.field_path,
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return tuple(unique)


def finding_codes(findings: Iterable[ValidationFinding]) -> tuple[str, ...]:
    """Return unique codes in first-observed order."""

    codes: list[str] = []
    for finding in findings:
        if finding.code not in codes:
            codes.append(finding.code)
    return tuple(codes)
