"""Filesystem-aware resolution layered on persistence lexical path safety."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from conditioning_layers.persistence import AssetPathError, normalize_asset_reference

from .errors import AssetInspectionError


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """A canonical reference and contained real filesystem path."""

    relative_reference: str
    path: Path


def resolve_field_asset(asset_root: str | Path, reference: str) -> ResolvedAsset:
    """Resolve one lexically safe reference and reject real-path escape."""

    try:
        normalized = normalize_asset_reference(reference)
    except AssetPathError as error:
        raise AssetInspectionError("asset.path_escape", str(error)) from error

    if not normalized.lower().endswith(".png"):
        raise AssetInspectionError(
            "asset.unsupported_format",
            "Influence Field assets must use the .png file extension.",
        )

    root = Path(asset_root)
    candidate = root.joinpath(*normalized.split("/"))
    try:
        resolved_root = root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise AssetInspectionError(
            "asset.path_escape",
            "Asset path could not be resolved safely.",
        ) from error

    if not resolved_candidate.is_relative_to(resolved_root):
        raise AssetInspectionError(
            "asset.symlink_escape",
            "Resolved asset path escapes the document-owned asset root.",
        )

    try:
        if not candidate.exists():
            raise AssetInspectionError(
                "asset.not_found",
                "Referenced Influence Field asset was not found.",
            )
        if not candidate.is_file():
            raise AssetInspectionError(
                "asset.not_file",
                "Referenced Influence Field asset is not a regular file.",
            )
    except AssetInspectionError:
        raise
    except OSError as error:
        raise AssetInspectionError(
            "asset.not_file",
            "Referenced asset could not be inspected as a file.",
        ) from error

    return ResolvedAsset(normalized, resolved_candidate)
