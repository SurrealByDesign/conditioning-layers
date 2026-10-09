"""Prototype format-version dispatch with no speculative migration history."""

from __future__ import annotations

from dataclasses import dataclass

from conditioning_layers.domain import FindingSeverity

from .errors import PersistenceFinding


@dataclass(frozen=True, order=True, slots=True)
class PrototypeFormatVersion:
    """Version of the JSON envelope, distinct from domain document version."""

    major: int
    minor: int


CURRENT_FORMAT_VERSION = PrototypeFormatVersion(major=1, minor=0)
COMPOSITION_POLICY_FORMAT_VERSION = PrototypeFormatVersion(major=2, minor=0)


@dataclass(frozen=True, slots=True)
class MigrationDecision:
    """Current-version dispatch result; no destructive rewrite is performed."""

    supported: bool
    findings: tuple[PersistenceFinding, ...] = ()


def dispatch_migration(version: PrototypeFormatVersion) -> MigrationDecision:
    """Accept explicit 1.0 and 2.0 formats without migrating either.

    2.0 is an incompatible required-policy successor, not an optional 1.x field
    that the retained loader could warn about and discard. CURRENT remains 1.0
    for retained product documents. Unsupported versions keep distinct older/
    newer diagnostics relative to that retained format. No file is rewritten.
    """

    if version in (CURRENT_FORMAT_VERSION, COMPOSITION_POLICY_FORMAT_VERSION):
        return MigrationDecision(supported=True)

    relation = "older" if version < CURRENT_FORMAT_VERSION else "newer"
    return MigrationDecision(
        supported=False,
        findings=(
            PersistenceFinding(
                code=f"format.version.unsupported_{relation}",
                severity=FindingSeverity.ERROR,
                message=(
                    f"Prototype format version {version.major}.{version.minor} is "
                    f"{relation} than supported version "
                    f"{CURRENT_FORMAT_VERSION.major}.{CURRENT_FORMAT_VERSION.minor}; "
                    "no migration is defined."
                ),
                json_path="$.format_version",
            ),
        ),
    )
