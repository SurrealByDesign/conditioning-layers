"""Lexical document-owned asset path handling without filesystem inspection."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from .errors import AssetPathError


_URI_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def document_asset_root(document_path: str | Path) -> Path:
    """Return the sibling asset directory for a document path.

    ``example.conditioning.json`` maps to ``example.conditioning.assets``.
    This computation does not create or inspect either path.
    """

    path = Path(document_path)
    if not path.name:
        raise AssetPathError(
            "document.path.invalid",
            "Document path must include a file name.",
            document_path,
        )
    return path.with_suffix(".assets")


def normalize_asset_reference(reference: str) -> str:
    """Validate and normalize an asset-root-relative reference to POSIX separators."""

    if not isinstance(reference, str):
        raise AssetPathError(
            "asset.path.invalid_type",
            "Asset reference must be text.",
            reference,
        )
    if not reference or not reference.strip():
        raise AssetPathError(
            "asset.path.empty",
            "Asset reference must not be empty.",
            reference,
        )
    if "\x00" in reference:
        raise AssetPathError(
            "asset.path.invalid",
            "Asset reference contains an invalid null character.",
            reference,
        )
    if reference.startswith(("\\\\", "//")):
        raise AssetPathError(
            "asset.path.unc",
            "UNC asset references are not allowed.",
            reference,
        )

    windows_path = PureWindowsPath(reference)
    posix_path = PurePosixPath(reference)
    if windows_path.drive:
        raise AssetPathError(
            "asset.path.drive_qualified",
            "Drive-qualified asset references are not allowed.",
            reference,
        )
    if windows_path.is_absolute() or posix_path.is_absolute():
        raise AssetPathError(
            "asset.path.absolute",
            "Absolute asset references are not allowed.",
            reference,
        )
    if _URI_SCHEME_PATTERN.match(reference):
        raise AssetPathError(
            "asset.path.uri",
            "URI asset references are not allowed.",
            reference,
        )

    segments = re.split(r"[\\/]", reference)
    if any(segment == ".." for segment in segments):
        raise AssetPathError(
            "asset.path.traversal",
            "Parent traversal is not allowed in asset references.",
            reference,
        )
    if any(segment in {"", "."} for segment in segments):
        raise AssetPathError(
            "asset.path.empty_segment",
            "Asset references must not contain empty or current-directory segments.",
            reference,
        )

    return "/".join(segments)


def resolve_asset_path(document_path: str | Path, reference: str) -> Path:
    """Join a safe reference beneath the document-owned asset root lexically.

    No call to ``resolve`` is made, so this function does not inspect or follow
    symlinks. A later filesystem-aware layer must repeat containment checks when
    it is authorized to inspect assets.
    """

    normalized = normalize_asset_reference(reference)
    return document_asset_root(document_path).joinpath(*normalized.split("/"))
