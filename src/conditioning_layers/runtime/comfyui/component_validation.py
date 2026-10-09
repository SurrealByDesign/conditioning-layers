"""Narrow component-file verification without loading model formats."""

from __future__ import annotations

import hashlib
from pathlib import Path

from conditioning_layers.comfyui.prediction_mixing import (
    ComfyUIComponentInventory,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .errors import deduplicate_findings, runtime_finding
from .models import (
    ComfyUIHostConfiguration,
    ComponentFileRecord,
    ComponentRole,
    ComponentValidationResult,
)


_COMPONENT_FIELDS = (
    (
        ComponentRole.MODEL,
        "diffusion_models",
        "model_filename",
        "model_size_bytes",
        "model_sha256",
    ),
    (
        ComponentRole.TEXT_ENCODER,
        "text_encoders",
        "text_encoder_filename",
        "text_encoder_size_bytes",
        "text_encoder_sha256",
    ),
    (
        ComponentRole.VAE,
        "vae",
        "vae_filename",
        "vae_size_bytes",
        "vae_sha256",
    ),
)


def validate_component_files(
    configuration: ComfyUIHostConfiguration,
    inventory: ComfyUIComponentInventory,
) -> ComponentValidationResult:
    """Verify only declared component categories, filenames, sizes, and hashes."""

    errors: list[ValidationFinding] = []
    information: list[ValidationFinding] = []
    records: list[ComponentFileRecord] = []
    valid_directories = _validated_model_directories(configuration, errors)

    for role, category, filename_field, size_field, checksum_field in _COMPONENT_FIELDS:
        filename = getattr(inventory, filename_field)
        expected_size = getattr(inventory, size_field)
        expected_sha256 = getattr(inventory, checksum_field)
        candidates = _component_candidates(
            valid_directories.get(category, ()), filename
        )
        if not candidates:
            wrong_categories = tuple(
                candidate_category
                for candidate_category, directories in valid_directories.items()
                if candidate_category != category
                and _component_candidates(directories, filename)
            )
            code = "runtime.component_category" if wrong_categories else "runtime.component_missing"
            message = (
                f"Component {filename!r} is present only in an unexpected declared category."
                if wrong_categories
                else f"Required component {filename!r} was not found in category {category!r}."
            )
            errors.append(
                runtime_finding(
                    code,
                    FindingSeverity.ERROR,
                    message,
                    field_path=f"components.{role.value}",
                )
            )
            records.append(
                ComponentFileRecord(
                    role=role,
                    category=category,
                    filename=filename,
                    local_path=None,
                    byte_size=None,
                    sha256=None,
                    expected_byte_size=expected_size,
                    expected_sha256=expected_sha256,
                    verified=False,
                )
            )
            continue
        if len(candidates) > 1:
            errors.append(
                runtime_finding(
                    "runtime.component_ambiguous",
                    FindingSeverity.ERROR,
                    f"Component filename {filename!r} resolves to multiple declared category paths.",
                    field_path=f"components.{role.value}",
                )
            )
            records.append(
                ComponentFileRecord(
                    role=role,
                    category=category,
                    filename=filename,
                    local_path=None,
                    byte_size=None,
                    sha256=None,
                    expected_byte_size=expected_size,
                    expected_sha256=expected_sha256,
                    verified=False,
                )
            )
            continue

        candidate = candidates[0]
        observed_size: int | None = None
        observed_sha256: str | None = None
        verified = True
        try:
            resolved_root = configuration.model_root.resolve(strict=True)
            resolved_candidate = candidate.resolve(strict=True)
            if not resolved_candidate.is_relative_to(resolved_root):
                raise ValueError("component path escapes model root")
            if not resolved_candidate.is_file():
                raise ValueError("component is not a regular file")
            observed_size = resolved_candidate.stat().st_size
            observed_sha256 = _sha256_file(resolved_candidate)
        except (OSError, RuntimeError, ValueError):
            verified = False
            errors.append(
                runtime_finding(
                    "runtime.component_missing",
                    FindingSeverity.ERROR,
                    f"Component {filename!r} is not a readable regular file inside the model root.",
                    field_path=f"components.{role.value}",
                )
            )

        if observed_size is not None and expected_size is not None and observed_size != expected_size:
            verified = False
            errors.append(
                runtime_finding(
                    "runtime.component_size",
                    FindingSeverity.ERROR,
                    f"Component {filename!r} has {observed_size} bytes; expected {expected_size}.",
                    field_path=f"components.{role.value}",
                )
            )
        if (
            observed_sha256 is not None
            and expected_sha256 is not None
            and observed_sha256.casefold() != expected_sha256.casefold()
        ):
            verified = False
            errors.append(
                runtime_finding(
                    "runtime.component_checksum",
                    FindingSeverity.ERROR,
                    f"Component {filename!r} does not match its declared SHA-256.",
                    field_path=f"components.{role.value}",
                )
            )
        if verified:
            information.append(
                runtime_finding(
                    "runtime.component_verified",
                    FindingSeverity.INFORMATION,
                    f"Component {filename!r} matches its declared file evidence.",
                    field_path=f"components.{role.value}",
                )
            )
        records.append(
            ComponentFileRecord(
                role=role,
                category=category,
                filename=filename,
                local_path=candidate if observed_sha256 is not None else None,
                byte_size=observed_size,
                sha256=observed_sha256,
                expected_byte_size=expected_size,
                expected_sha256=expected_sha256,
                verified=verified,
            )
        )

    errors_tuple = deduplicate_findings(errors)
    return ComponentValidationResult(
        records=tuple(records),
        errors=errors_tuple,
        warnings=(),
        information=deduplicate_findings(information),
        verified=(not errors_tuple and len(records) == len(_COMPONENT_FIELDS)),
    )


def _validated_model_directories(
    configuration: ComfyUIHostConfiguration,
    errors: list[ValidationFinding],
) -> dict[str, tuple[Path, ...]]:
    valid: dict[str, tuple[Path, ...]] = {}
    try:
        resolved_model_root = configuration.model_root.resolve(strict=True)
    except (OSError, RuntimeError):
        errors.append(
            runtime_finding(
                "runtime.host_root",
                FindingSeverity.ERROR,
                "The configured model root cannot be resolved.",
                field_path="host.model_root",
            )
        )
        return valid
    for category, directories in configuration.model_directories.items():
        accepted: list[Path] = []
        for directory in directories:
            try:
                if not isinstance(directory, Path) or not directory.is_absolute():
                    raise ValueError("category path is not absolute")
                resolved = directory.resolve(strict=True)
                if not resolved.is_dir() or not resolved.is_relative_to(resolved_model_root):
                    raise ValueError("category path is outside model root")
                accepted.append(resolved)
            except (OSError, RuntimeError, ValueError):
                errors.append(
                    runtime_finding(
                        "runtime.component_category",
                        FindingSeverity.ERROR,
                        f"Declared model category path for {category!r} is invalid or outside the model root.",
                        field_path=f"host.model_directories.{category}",
                    )
                )
        valid[category] = tuple(accepted)
    return valid


def _component_candidates(directories: tuple[Path, ...], filename: str) -> tuple[Path, ...]:
    found: list[Path] = []
    for directory in directories:
        candidate = directory / filename
        try:
            if candidate.exists():
                found.append(candidate)
        except OSError:
            continue
    return tuple(found)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
