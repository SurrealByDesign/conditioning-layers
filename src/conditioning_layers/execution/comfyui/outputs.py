"""Safe metadata-only output association from prompt-specific terminal history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from conditioning_layers.domain import FindingSeverity, ValidationFinding
from conditioning_layers.runtime.comfyui import ComfyUISubmissionBundle

from .errors import execution_finding
from .models import AssociatedOutput, ComfyUIExecutionPolicy


_URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True, slots=True)
class OutputAssociationResult:
    outputs: tuple[AssociatedOutput, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]


def associate_outputs(
    history_record: Mapping[str, object],
    bundle: ComfyUISubmissionBundle,
    policy: ComfyUIExecutionPolicy,
) -> OutputAssociationResult:
    """Associate only expected SaveImage history metadata for the tracked prompt."""

    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []
    outputs: list[AssociatedOutput] = []
    expected_nodes = tuple(
        node_id
        for node_id, node in bundle.graph_mapping.items()
        if isinstance(node, Mapping) and node.get("class_type") == "SaveImage"
    )
    if policy.require_expected_save_image_node and len(expected_nodes) != 1:
        errors.append(
            execution_finding(
                "execution.output_missing",
                FindingSeverity.ERROR,
                "The verified graph does not identify exactly one expected SaveImage node.",
            )
        )
        return OutputAssociationResult((), tuple(errors), (), ())

    history_outputs = history_record.get("outputs")
    if not isinstance(history_outputs, Mapping):
        errors.append(
            execution_finding(
                "execution.output_missing",
                FindingSeverity.ERROR,
                "Terminal history contains no output mapping.",
            )
        )
        return OutputAssociationResult((), tuple(errors), (), ())

    for node_id, node_output in history_outputs.items():
        if not isinstance(node_id, str) or node_id not in expected_nodes:
            errors.append(
                execution_finding(
                    "execution.output_unsafe",
                    FindingSeverity.ERROR,
                    "Terminal history contains output from an unexpected node.",
                )
            )
            continue
        if not isinstance(node_output, Mapping):
            errors.append(_missing_output())
            continue
        images = node_output.get("images")
        if not isinstance(images, list) or not images:
            errors.append(_missing_output())
            continue
        for item in images:
            output = _parse_output(item, node_id, bundle, policy, errors, warnings)
            if output is not None:
                outputs.append(output)

    if not outputs:
        errors.append(_missing_output())
    locators = [item.relative_locator for item in outputs]
    if len(locators) != len(set(locators)):
        errors.append(
            execution_finding(
                "execution.output_unsafe",
                FindingSeverity.ERROR,
                "Terminal history contains duplicate ambiguous output locators.",
            )
        )
        outputs = []
    information = ()
    if outputs and not errors:
        information = (
            execution_finding(
                "execution.outputs_associated",
                FindingSeverity.INFORMATION,
                "Outputs were associated through prompt-specific terminal history.",
            ),
        )
    return OutputAssociationResult(
        outputs=tuple(outputs),
        errors=_deduplicate(errors),
        warnings=_deduplicate(warnings),
        information=information,
    )


def _parse_output(
    item: object,
    node_id: str,
    bundle: ComfyUISubmissionBundle,
    policy: ComfyUIExecutionPolicy,
    errors: list[ValidationFinding],
    warnings: list[ValidationFinding],
) -> AssociatedOutput | None:
    if not isinstance(item, Mapping):
        errors.append(_missing_output())
        return None
    filename = item.get("filename")
    subfolder = item.get("subfolder", "")
    storage_type = item.get("type")
    if not all(isinstance(value, str) for value in (filename, subfolder, storage_type)):
        errors.append(_missing_output())
        return None
    locator = f"{subfolder}/{filename}" if subfolder else filename
    if not _safe_relative_locator(locator, bundle.host_snapshot.output_directory):
        errors.append(
            execution_finding(
                "execution.output_unsafe",
                FindingSeverity.ERROR,
                "Output locator is absolute, escaping, or otherwise unsafe.",
            )
        )
        return None
    if storage_type != "output":
        errors.append(
            execution_finding(
                "execution.output_unsafe",
                FindingSeverity.ERROR,
                "SaveImage output must use ComfyUI output storage.",
            )
        )
        return None
    if policy.require_output_prefix_match and not _matches_prefix(
        locator, bundle.expected_output_prefix
    ):
        errors.append(
            execution_finding(
                "execution.output_prefix",
                FindingSeverity.ERROR,
                "Associated output does not match the bundle's expected SaveImage prefix.",
            )
        )
        return None
    metadata = {
        str(key): value
        for key, value in item.items()
        if key not in {"filename", "subfolder", "type"}
        and isinstance(value, str | int | float | bool | type(None))
    }
    return AssociatedOutput(
        node_id=node_id,
        output_type="images",
        filename=filename,
        subfolder=subfolder,
        storage_type=storage_type,
        relative_locator=locator,
        metadata=metadata,
    )


def _safe_relative_locator(value: str, output_root: Path) -> bool:
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or _URI_PATTERN.match(value)
        or any(character in value for character in '<>:"|?*')
    ):
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        return False
    try:
        candidate = output_root.resolve(strict=True).joinpath(*posix.parts).resolve(
            strict=False
        )
        return candidate.is_relative_to(output_root.resolve(strict=True))
    except (OSError, RuntimeError):
        return False


def _matches_prefix(locator: str, expected_prefix: str) -> bool:
    if not locator.startswith(expected_prefix):
        return False
    remainder = locator[len(expected_prefix) :]
    return bool(remainder) and remainder[0] in {"_", "."}


def _missing_output() -> ValidationFinding:
    return execution_finding(
        "execution.output_missing",
        FindingSeverity.ERROR,
        "Expected SaveImage output metadata is missing or malformed.",
    )


def _deduplicate(findings: list[ValidationFinding]) -> tuple[ValidationFinding, ...]:
    unique: list[ValidationFinding] = []
    seen: set[tuple[str, FindingSeverity]] = set()
    for finding in findings:
        key = (finding.code, finding.severity)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return tuple(unique)
