"""Read-only validation of one explicitly configured local ComfyUI checkout."""

from __future__ import annotations

import os
from pathlib import Path
import re

from conditioning_layers.comfyui.prediction_mixing import (
    NODE_CONTRACTS,
    ComfyUIComponentInventory,
    snapshot_is_supported,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .errors import deduplicate_findings, runtime_finding
from .models import (
    ComfyUIHostConfiguration,
    ComfyUIHostSnapshot,
    HostCompatibilityStatus,
    HostNodeContractSnapshot,
    HostValidationResult,
)

_VERSION_PATTERN = re.compile(
    r'^__version__\s*=\s*["\'](?P<version>[^"\']+)["\']\s*$', re.MULTILINE
)
_REVISION_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


def validate_local_host(
    configuration: ComfyUIHostConfiguration,
    inventory: ComfyUIComponentInventory,
    required_node_classes: tuple[str, ...],
    node_contract_snapshot: HostNodeContractSnapshot | None,
) -> HostValidationResult:
    """Validate local paths and static evidence without importing or launching ComfyUI."""

    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []
    information: list[ValidationFinding] = []

    if (
        configuration.supported_profile_identifier
        != inventory.comfyui_profile_identifier
    ):
        errors.append(
            runtime_finding(
                "runtime.host_profile",
                FindingSeverity.ERROR,
                "The configured host profile does not match the graph inventory.",
                field_path="host.supported_profile_identifier",
            )
        )

    path_checks = (
        (
            "comfyui_root",
            configuration.comfyui_root,
            configuration.checkout_trusted_root,
        ),
        (
            "git_checkout_path",
            configuration.git_checkout_path,
            configuration.checkout_trusted_root,
        ),
        (
            "input_directory",
            configuration.input_directory,
            configuration.data_trusted_root,
        ),
        (
            "output_directory",
            configuration.output_directory,
            configuration.data_trusted_root,
        ),
        ("model_root", configuration.model_root, configuration.model_trusted_root),
    )
    filesystem_verified = True
    for role, path, trusted_root in path_checks:
        if not _validate_directory(role, path, trusted_root, errors):
            filesystem_verified = False
    if configuration.user_directory is not None and not _validate_directory(
        "user_directory",
        configuration.user_directory,
        configuration.data_trusted_root,
        errors,
    ):
        filesystem_verified = False

    if filesystem_verified and not os.access(configuration.git_checkout_path, os.R_OK):
        filesystem_verified = False
        errors.append(
            runtime_finding(
                "runtime.host_root",
                FindingSeverity.ERROR,
                "The configured ComfyUI checkout is not readable.",
                field_path="host.git_checkout_path",
            )
        )

    observed_version = _read_comfyui_version(configuration.git_checkout_path)
    observed_revision = _read_git_revision(configuration.git_checkout_path)
    version_status = _compatibility_status(
        observed_version, inventory.expected_comfyui_version
    )
    revision_status = _compatibility_status(
        observed_revision, inventory.expected_comfyui_revision
    )
    _append_compatibility_finding(
        errors,
        information,
        code="runtime.host_version",
        label="ComfyUI version",
        observed=observed_version,
        expected=inventory.expected_comfyui_version,
        status=version_status,
        field_path="host.version",
    )
    _append_compatibility_finding(
        errors,
        information,
        code="runtime.host_revision",
        label="ComfyUI revision",
        observed=observed_revision,
        expected=inventory.expected_comfyui_revision,
        status=revision_status,
        field_path="host.revision",
    )

    unresolved: list[str] = []
    node_contracts_verified = _validate_node_snapshot(
        node_contract_snapshot,
        inventory,
        required_node_classes,
        observed_version,
        observed_revision,
        errors,
        information,
    )
    if node_contract_snapshot is None:
        unresolved.append("runtime.node_contract_unknown")
    elif not snapshot_is_supported(node_contract_snapshot):
        unresolved.append("profile.semantic_contract_unresolved")

    snapshot = ComfyUIHostSnapshot(
        profile_identifier=configuration.supported_profile_identifier,
        launch_profile_identifier=configuration.launch_profile_identifier,
        comfyui_root=configuration.comfyui_root,
        input_directory=configuration.input_directory,
        output_directory=configuration.output_directory,
        user_directory=configuration.user_directory,
        model_root=configuration.model_root,
        git_checkout_path=configuration.git_checkout_path,
        observed_comfyui_version=observed_version,
        observed_comfyui_revision=observed_revision,
        version_status=version_status,
        revision_status=revision_status,
        node_contract_snapshot_identifier=(
            node_contract_snapshot.snapshot_identifier
            if node_contract_snapshot is not None
            else None
        ),
        node_contract_snapshot_fingerprint=(
            node_contract_snapshot.snapshot_fingerprint
            if node_contract_snapshot is not None
            else None
        ),
        staging_cleanup_policy=configuration.staging_cleanup_policy,
        filesystem_verified=filesystem_verified,
        node_contracts_verified=node_contracts_verified,
    )
    errors_tuple = deduplicate_findings(errors)
    return HostValidationResult(
        snapshot=snapshot,
        errors=errors_tuple,
        warnings=deduplicate_findings(warnings),
        information=deduplicate_findings(information),
        compatible=(
            not errors_tuple
            and filesystem_verified
            and version_status is HostCompatibilityStatus.EXACT_MATCH
            and revision_status is HostCompatibilityStatus.EXACT_MATCH
            and node_contracts_verified
        ),
        unresolved_requirements=tuple(unresolved),
    )


def _validate_directory(
    role: str,
    path: Path,
    trusted_root: Path | None,
    errors: list[ValidationFinding],
) -> bool:
    field_path = f"host.{role}"
    if not isinstance(path, Path) or not path.is_absolute():
        errors.append(
            runtime_finding(
                "runtime.host_root",
                FindingSeverity.ERROR,
                f"Configured {role} must be an absolute local filesystem path.",
                field_path=field_path,
            )
        )
        return False
    try:
        if not path.exists() or not path.is_dir():
            errors.append(
                runtime_finding(
                    "runtime.host_root",
                    FindingSeverity.ERROR,
                    f"Configured {role} must exist and be a directory.",
                    field_path=field_path,
                )
            )
            return False
        resolved = path.resolve(strict=True)
        if trusted_root is not None:
            if not trusted_root.is_absolute() or not trusted_root.exists():
                errors.append(
                    runtime_finding(
                        "runtime.host_root",
                        FindingSeverity.ERROR,
                        f"Trusted root for {role} is invalid.",
                        field_path=field_path,
                    )
                )
                return False
            resolved_trusted = trusted_root.resolve(strict=True)
            if not resolved.is_relative_to(resolved_trusted):
                errors.append(
                    runtime_finding(
                        "runtime.host_root",
                        FindingSeverity.ERROR,
                        f"Configured {role} resolves outside its trusted root.",
                        field_path=field_path,
                    )
                )
                return False
    except (OSError, RuntimeError):
        errors.append(
            runtime_finding(
                "runtime.host_root",
                FindingSeverity.ERROR,
                f"Configured {role} could not be resolved safely.",
                field_path=field_path,
            )
        )
        return False
    return True


def _read_comfyui_version(checkout: Path) -> str | None:
    version_file = checkout / "comfyui_version.py"
    try:
        resolved_checkout = checkout.resolve(strict=True)
        if version_file.is_file() and version_file.resolve(strict=True).is_relative_to(
            resolved_checkout
        ):
            match = _VERSION_PATTERN.search(version_file.read_text(encoding="utf-8"))
            if match is not None:
                return match.group("version")
    except (OSError, UnicodeError):
        return None
    return None


def _read_git_revision(checkout: Path) -> str | None:
    git_marker = checkout / ".git"
    try:
        resolved_checkout = checkout.resolve(strict=True)
        if git_marker.is_dir():
            git_directory = git_marker.resolve(strict=True)
        elif git_marker.is_file():
            marker = _read_git_metadata(git_marker, resolved_checkout)
            if not marker.startswith("gitdir:"):
                return None
            git_directory = Path(marker.removeprefix("gitdir:").strip())
            if not git_directory.is_absolute():
                git_directory = (checkout / git_directory).resolve(strict=False)
        else:
            return None
        git_directory = git_directory.resolve(strict=True)
        if not git_directory.is_relative_to(resolved_checkout):
            return _read_linked_worktree_revision(
                git_marker, git_directory, resolved_checkout
            )
        head = (git_directory / "HEAD").read_text(encoding="utf-8").strip()
        if _REVISION_PATTERN.fullmatch(head):
            return head.lower()
        if not head.startswith("ref: "):
            return None
        reference = head.removeprefix("ref: ").strip()
        reference_file = git_directory.joinpath(*reference.split("/"))
        if reference_file.is_file():
            value = reference_file.read_text(encoding="utf-8").strip()
            return value.lower() if _REVISION_PATTERN.fullmatch(value) else None
        packed = git_directory / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith(("#", "^")):
                    continue
                value, separator, name = line.partition(" ")
                if (
                    separator
                    and name == reference
                    and _REVISION_PATTERN.fullmatch(value)
                ):
                    return value.lower()
    except (OSError, UnicodeError, RuntimeError, ValueError):
        return None
    return None


def _read_git_metadata(path: Path, root: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("Git metadata must remain inside its bound directory")
    return resolved.read_text(encoding="utf-8").strip()


def _read_linked_worktree_revision(
    git_marker: Path, git_directory: Path, checkout: Path
) -> str | None:
    """Read a pinned detached worktree only after reciprocal static binding."""

    # An external directory is not trusted merely because .git names it.
    # Git's per-worktree backlink and common-directory relationship must agree.
    if not git_marker.is_file() or git_marker.resolve(strict=True).parent != checkout:
        return None
    backlink = _read_git_metadata(git_directory / "gitdir", git_directory)
    common = _read_git_metadata(git_directory / "commondir", git_directory)
    if not backlink or not common:
        return None
    backlink_path = (git_directory / backlink).resolve(strict=True)
    common_directory = (git_directory / common).resolve(strict=True)
    if (
        backlink_path != git_marker.resolve(strict=True)
        or git_directory.parent.name != "worktrees"
        or common_directory != git_directory.parent.parent
    ):
        return None
    head = _read_git_metadata(git_directory / "HEAD", git_directory)
    # The supported pinned host has detached HEAD. Shared/symbolic worktree
    # refs remain unverified; this is not a general Git reference resolver.
    return head.lower() if _REVISION_PATTERN.fullmatch(head) else None


def _compatibility_status(
    observed: str | None,
    expected: str,
) -> HostCompatibilityStatus:
    if observed is None:
        return HostCompatibilityStatus.UNABLE_TO_VERIFY
    if observed.casefold() == expected.casefold():
        return HostCompatibilityStatus.EXACT_MATCH
    return HostCompatibilityStatus.UNSUPPORTED_MISMATCH


def _append_compatibility_finding(
    errors: list[ValidationFinding],
    information: list[ValidationFinding],
    *,
    code: str,
    label: str,
    observed: str | None,
    expected: str,
    status: HostCompatibilityStatus,
    field_path: str,
) -> None:
    if status is HostCompatibilityStatus.EXACT_MATCH:
        information.append(
            runtime_finding(
                code,
                FindingSeverity.INFORMATION,
                f"{label} exactly matches {expected}.",
                field_path=field_path,
            )
        )
    elif status is HostCompatibilityStatus.UNABLE_TO_VERIFY:
        errors.append(
            runtime_finding(
                code,
                FindingSeverity.ERROR,
                f"{label} could not be verified from local static evidence.",
                field_path=field_path,
            )
        )
    else:
        errors.append(
            runtime_finding(
                code,
                FindingSeverity.ERROR,
                f"{label} {observed!r} is unsupported; the inventory requires {expected!r}.",
                field_path=field_path,
            )
        )


def _validate_node_snapshot(
    snapshot: HostNodeContractSnapshot | None,
    inventory: ComfyUIComponentInventory,
    required_node_classes: tuple[str, ...],
    observed_version: str | None,
    observed_revision: str | None,
    errors: list[ValidationFinding],
    information: list[ValidationFinding],
) -> bool:
    if snapshot is None:
        errors.append(
            runtime_finding(
                "runtime.node_contract_unknown",
                FindingSeverity.ERROR,
                "A trusted node-contract snapshot is required before submission.",
                field_path="host.node_contract_snapshot",
            )
        )
        return False
    if (
        snapshot.profile_identifier != inventory.comfyui_profile_identifier
        or snapshot.comfyui_version != observed_version
        or snapshot.comfyui_revision.casefold() != (observed_revision or "").casefold()
    ):
        errors.append(
            runtime_finding(
                "runtime.node_contract_mismatch",
                FindingSeverity.ERROR,
                "The node-contract snapshot is not tied to this exact host profile and checkout.",
                field_path="host.node_contract_snapshot",
            )
        )
        return False
    snapshot_supported = snapshot_is_supported(snapshot)
    if not snapshot_supported:
        errors.append(
            runtime_finding(
                "profile.semantic_contract_unresolved",
                FindingSeverity.ERROR,
                "The node-contract snapshot lacks complete, portable semantic evidence.",
                field_path="host.node_contract_snapshot",
            )
        )
    for class_name in required_node_classes:
        expected = NODE_CONTRACTS.get(class_name)
        observed = snapshot.contracts.get(class_name)
        if (
            expected is None
            or observed is None
            or observed.class_name != class_name
            or observed.required_inputs != tuple(sorted(expected.required_inputs))
            or observed.output_indices != tuple(sorted(expected.output_indices))
        ):
            errors.append(
                runtime_finding(
                    "runtime.node_contract_mismatch",
                    FindingSeverity.ERROR,
                    f"Built-in node contract {class_name!r} does not match the generated graph profile.",
                    field_path=f"host.node_contract_snapshot.{class_name}",
                )
            )
    if any(finding.code == "runtime.node_contract_mismatch" for finding in errors):
        return False
    information.append(
        runtime_finding(
            "runtime.node_contract_verified",
            FindingSeverity.INFORMATION,
            "All required built-in node contracts match the trusted host snapshot.",
            field_path="host.node_contract_snapshot",
        )
    )
    return snapshot_supported
