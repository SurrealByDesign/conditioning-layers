"""Small diagnostics and exception boundary for prototype persistence."""

from __future__ import annotations

from dataclasses import dataclass

from conditioning_layers.domain import (
    ConditioningDocument,
    FindingSeverity,
    ValidationFinding,
)


@dataclass(frozen=True, slots=True)
class PersistenceFinding:
    """One machine-readable persistence diagnostic."""

    code: str
    severity: FindingSeverity
    message: str
    json_path: str | None = None
    layer_id: str | None = None


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Normal result for user-authored input, including malformed documents."""

    document: ConditioningDocument | None
    persistence_findings: tuple[PersistenceFinding, ...] = ()
    domain_findings: tuple[ValidationFinding, ...] = ()
    capability_findings: tuple[ValidationFinding, ...] = ()

    @property
    def findings(self) -> tuple[PersistenceFinding | ValidationFinding, ...]:
        """Return persistence, domain, then optionally requested capability findings."""

        return (
            self.persistence_findings
            + self.domain_findings
            + self.capability_findings
        )

    @property
    def ok(self) -> bool:
        """Whether a document loaded without any error-severity finding."""

        return self.document is not None and not any(
            finding.severity is FindingSeverity.ERROR for finding in self.findings
        )


class PersistenceError(Exception):
    """Base class for persistence operation failures."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DocumentEncodeError(PersistenceError):
    """Raised when a domain document cannot be encoded safely."""

    def __init__(
        self,
        findings: tuple[PersistenceFinding | ValidationFinding, ...],
    ) -> None:
        super().__init__("document.encode_rejected", "Document encoding was rejected.")
        self.findings = findings


class DocumentIOError(PersistenceError):
    """Raised for explicit save API filesystem failures."""

    def __init__(self, code: str, message: str, path: str) -> None:
        super().__init__(code, message)
        self.path = path


class AssetPathError(PersistenceError):
    """Raised when an asset reference is not lexically safe."""

    def __init__(self, code: str, message: str, value: object) -> None:
        super().__init__(code, message)
        self.value = value
