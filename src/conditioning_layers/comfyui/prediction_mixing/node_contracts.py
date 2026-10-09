"""Portable static ComfyUI node-contract and semantic-evidence records."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
from types import MappingProxyType


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class NodeInputEvidence:
    """One graph-relevant host input described without importing ComfyUI."""

    name: str
    host_requirement: str
    accepted_type: str
    enum_values: tuple[str, ...] = ()
    default_value: object | None = None
    external_enumeration: str | None = None


@dataclass(frozen=True, slots=True)
class HostNodeContractRecord:
    """Static evidence for one required built-in node class."""

    class_name: str
    required_inputs: tuple[str, ...]
    output_indices: tuple[int, ...]
    host_required_inputs: tuple[str, ...] = ()
    host_optional_inputs: tuple[str, ...] = ()
    input_evidence: tuple[NodeInputEvidence, ...] = ()
    return_types: tuple[str, ...] = ()
    function_name: str = ""
    source_file: str = ""
    source_symbol: str = ""
    source_file_sha256: str = ""
    source_symbol_fingerprint: str = ""
    contract_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class SemanticEvidenceRecord:
    """Static source evidence for one execution-semantic requirement."""

    evidence_identifier: str
    source_file: str
    source_symbols: tuple[str, ...]
    source_file_sha256: str
    symbol_fingerprints: tuple[str, ...]
    conclusion: str
    notes: str


@dataclass(frozen=True, slots=True)
class StaticSymbolEvidence:
    """A safely parsed class or function symbol and its normalized AST hash."""

    source_file: str
    source_file_sha256: str
    symbol: str
    symbol_fingerprint: str


@dataclass(frozen=True, slots=True)
class HostNodeContractSnapshot:
    """Immutable contract evidence bound to one exact supported host profile."""

    snapshot_identifier: str
    profile_identifier: str
    comfyui_version: str
    comfyui_revision: str
    contracts: Mapping[str, HostNodeContractRecord]
    source_reference: str
    semantic_evidence: tuple[SemanticEvidenceRecord, ...] = ()
    source_file_hashes: Mapping[str, str] = field(default_factory=dict)
    snapshot_fingerprint: str = ""
    limitations: tuple[str, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    evidence_timestamp: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.contracts, Mapping):
            object.__setattr__(
                self, "contracts", MappingProxyType(dict(self.contracts))
            )
        if isinstance(self.source_file_hashes, Mapping):
            object.__setattr__(
                self,
                "source_file_hashes",
                MappingProxyType(dict(self.source_file_hashes)),
            )


REQUIRED_SEMANTIC_EVIDENCE = frozenset(
    {
        "prediction_mixing.conditioning_set_mask",
        "prediction_mixing.conditioning_combine",
        "prediction_mixing.regional_accumulation",
        "prediction_mixing.cfg1_empty_negative",
    }
)


def extract_static_symbol_evidence(
    source_text: str,
    *,
    source_file: str,
    symbol: str,
    expected_source_sha256: str | None = None,
) -> StaticSymbolEvidence:
    """Parse one top-level symbol without importing or executing source code."""

    if not _portable_relative_path(source_file):
        raise ValueError("source_file must be a portable relative POSIX path")
    source_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if expected_source_sha256 is not None and source_sha256 != expected_source_sha256:
        raise ValueError("source text does not match its declared SHA-256")
    try:
        tree = ast.parse(source_text, filename=source_file)
    except SyntaxError as error:
        raise ValueError("source text is not parseable Python") from error
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == symbol
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one top-level symbol {symbol!r}")
    normalized = ast.dump(matches[0], annotate_fields=True, include_attributes=False)
    return StaticSymbolEvidence(
        source_file=source_file,
        source_file_sha256=source_sha256,
        symbol=symbol,
        symbol_fingerprint=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def create_node_contract_record(
    *,
    class_name: str,
    required_inputs: tuple[str, ...],
    output_indices: tuple[int, ...],
    host_required_inputs: tuple[str, ...],
    host_optional_inputs: tuple[str, ...],
    input_evidence: tuple[NodeInputEvidence, ...],
    return_types: tuple[str, ...],
    function_name: str,
    source_file: str,
    source_symbol: str,
    source_file_sha256: str,
    source_symbol_fingerprint: str,
) -> HostNodeContractRecord:
    """Construct a deterministic, self-verifying node-contract record."""

    draft = HostNodeContractRecord(
        class_name=class_name,
        required_inputs=required_inputs,
        output_indices=output_indices,
        host_required_inputs=host_required_inputs,
        host_optional_inputs=host_optional_inputs,
        input_evidence=input_evidence,
        return_types=return_types,
        function_name=function_name,
        source_file=source_file,
        source_symbol=source_symbol,
        source_file_sha256=source_file_sha256,
        source_symbol_fingerprint=source_symbol_fingerprint,
    )
    return HostNodeContractRecord(
        **{
            field: getattr(draft, field)
            for field in draft.__dataclass_fields__
            if field != "contract_fingerprint"
        },
        contract_fingerprint=fingerprint_node_contract(draft),
    )


def fingerprint_node_contract(record: HostNodeContractRecord) -> str:
    """Fingerprint graph-relevant contract data and exact source evidence."""

    payload = {
        "class_name": record.class_name,
        "required_inputs": list(record.required_inputs),
        "output_indices": list(record.output_indices),
        "host_required_inputs": list(record.host_required_inputs),
        "host_optional_inputs": list(record.host_optional_inputs),
        "input_evidence": [
            {
                "name": item.name,
                "host_requirement": item.host_requirement,
                "accepted_type": item.accepted_type,
                "enum_values": list(item.enum_values),
                "default_value": item.default_value,
                "external_enumeration": item.external_enumeration,
            }
            for item in record.input_evidence
        ],
        "return_types": list(record.return_types),
        "function_name": record.function_name,
        "source_file": record.source_file,
        "source_file_sha256": record.source_file_sha256,
        "source_symbol": record.source_symbol,
        "source_symbol_fingerprint": record.source_symbol_fingerprint,
    }
    return _fingerprint(payload)


def create_host_node_contract_snapshot(
    *,
    snapshot_identifier: str,
    profile_identifier: str,
    comfyui_version: str,
    comfyui_revision: str,
    contracts: Mapping[str, HostNodeContractRecord],
    source_reference: str,
    semantic_evidence: tuple[SemanticEvidenceRecord, ...],
    source_file_hashes: Mapping[str, str],
    limitations: tuple[str, ...] = (),
    unresolved_items: tuple[str, ...] = (),
    evidence_timestamp: str | None = None,
) -> HostNodeContractSnapshot:
    """Create a snapshot whose fingerprint excludes timestamp and local roots."""

    draft = HostNodeContractSnapshot(
        snapshot_identifier=snapshot_identifier,
        profile_identifier=profile_identifier,
        comfyui_version=comfyui_version,
        comfyui_revision=comfyui_revision,
        contracts=contracts,
        source_reference=source_reference,
        semantic_evidence=semantic_evidence,
        source_file_hashes=source_file_hashes,
        limitations=limitations,
        unresolved_items=unresolved_items,
        evidence_timestamp=evidence_timestamp,
    )
    return HostNodeContractSnapshot(
        snapshot_identifier=draft.snapshot_identifier,
        profile_identifier=draft.profile_identifier,
        comfyui_version=draft.comfyui_version,
        comfyui_revision=draft.comfyui_revision,
        contracts=draft.contracts,
        source_reference=draft.source_reference,
        semantic_evidence=draft.semantic_evidence,
        source_file_hashes=draft.source_file_hashes,
        snapshot_fingerprint=fingerprint_host_node_contract_snapshot(draft),
        limitations=draft.limitations,
        unresolved_items=draft.unresolved_items,
        evidence_timestamp=draft.evidence_timestamp,
    )


def fingerprint_host_node_contract_snapshot(
    snapshot: HostNodeContractSnapshot,
) -> str:
    """Fingerprint portable evidence; timestamps and source-reference labels are excluded."""

    payload = {
        "snapshot_identifier": snapshot.snapshot_identifier,
        "profile_identifier": snapshot.profile_identifier,
        "comfyui_version": snapshot.comfyui_version,
        "comfyui_revision": snapshot.comfyui_revision.lower(),
        "contracts": {
            name: record.contract_fingerprint
            for name, record in sorted(snapshot.contracts.items())
        },
        "semantic_evidence": [
            {
                "evidence_identifier": item.evidence_identifier,
                "source_file": item.source_file,
                "source_symbols": list(item.source_symbols),
                "source_file_sha256": item.source_file_sha256,
                "symbol_fingerprints": list(item.symbol_fingerprints),
                "conclusion": item.conclusion,
                "notes": item.notes,
            }
            for item in snapshot.semantic_evidence
        ],
        "source_file_hashes": dict(sorted(snapshot.source_file_hashes.items())),
        "limitations": list(snapshot.limitations),
        "unresolved_items": list(snapshot.unresolved_items),
    }
    return _fingerprint(payload)


def snapshot_is_supported(snapshot: HostNodeContractSnapshot) -> bool:
    """Return whether complete, portable, self-consistent evidence supports use."""

    semantic_ids = {item.evidence_identifier for item in snapshot.semantic_evidence}
    if (
        snapshot.unresolved_items
        or not REQUIRED_SEMANTIC_EVIDENCE <= semantic_ids
        or _REVISION_PATTERN.fullmatch(snapshot.comfyui_revision.lower()) is None
    ):
        return False
    if any(item.conclusion != "confirmed" for item in snapshot.semantic_evidence):
        return False
    if snapshot.snapshot_fingerprint != fingerprint_host_node_contract_snapshot(snapshot):
        return False
    if not _portable_relative_path(snapshot.source_reference):
        return False
    if any(
        not _portable_relative_path(path) or _SHA256_PATTERN.fullmatch(digest) is None
        for path, digest in snapshot.source_file_hashes.items()
    ):
        return False
    for item in snapshot.semantic_evidence:
        if (
            not _portable_relative_path(item.source_file)
            or _SHA256_PATTERN.fullmatch(item.source_file_sha256) is None
            or snapshot.source_file_hashes.get(item.source_file)
            != item.source_file_sha256
            or len(item.source_symbols) != len(item.symbol_fingerprints)
            or any(
                _SHA256_PATTERN.fullmatch(fingerprint) is None
                for fingerprint in item.symbol_fingerprints
            )
        ):
            return False
    for name, record in snapshot.contracts.items():
        if (
            name != record.class_name
            or record.contract_fingerprint != fingerprint_node_contract(record)
            or not _portable_relative_path(record.source_file)
            or _SHA256_PATTERN.fullmatch(record.source_file_sha256) is None
            or _SHA256_PATTERN.fullmatch(record.source_symbol_fingerprint) is None
            or snapshot.source_file_hashes.get(record.source_file)
            != record.source_file_sha256
            or any(index < 0 or index >= len(record.return_types) for index in record.output_indices)
        ):
            return False
    return True


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _portable_relative_path(value: str) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        not posix.is_absolute()
        and not windows.is_absolute()
        and windows.drive == ""
        and ".." not in posix.parts
    )
