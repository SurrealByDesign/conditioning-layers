"""Focused execution-client exceptions and internal protocol failures."""

from __future__ import annotations

from collections.abc import Iterable

from conditioning_layers.domain import FindingSeverity, ValidationFinding


class ExecutionClientError(Exception):
    """Base exception for programmer misuse of the execution boundary."""


class ServerConfigurationError(ExecutionClientError, ValueError):
    """Raised when an explicit server configuration is unsafe or unbounded."""


class ExecutionPolicyError(ExecutionClientError, ValueError):
    """Raised when an execution policy is internally inconsistent."""


class ProtocolFailure(Exception):
    """Internal normal runtime failure converted to a structured finding."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def execution_finding(
    code: str,
    severity: FindingSeverity,
    message: str,
    *,
    field_path: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity,
        message=message,
        field_path=field_path,
    )


def deduplicate_findings(
    findings: Iterable[ValidationFinding],
) -> tuple[ValidationFinding, ...]:
    unique: list[ValidationFinding] = []
    seen: set[tuple[str, FindingSeverity, str | None, str | None]] = set()
    for finding in findings:
        key = (finding.code, finding.severity, finding.layer_id, finding.field_path)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return tuple(unique)
