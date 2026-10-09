"""Product-eligible preset view of the authoritative Influence Field Library."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from conditioning_layers.assets.errors import AssetInspectionError
from conditioning_layers.assets.models import DEFAULT_INSPECTION_LIMITS
from conditioning_layers.assets.png_inspector import inspect_png_bytes

from .models import MAX_FIELD_BYTES, MAX_METADATA_BYTES, PanelRequestError


_LIBRARY_ROOT = Path(__file__).resolve().parents[4] / "influence-field-library" / "v1"
_FAMILY_ID = re.compile(r"(two|three)-layer\.[a-z0-9-]+\.v1")
_PRESET_ID = re.compile(r"(?:two|three)-layer\.[a-z0-9-]+\.v1:[ABC]")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_PRODUCT_STATUS = "validated-product-asset"
_STATUSES = {_PRODUCT_STATUS, "research-only", "illustrative", "unsupported"}
# Historical route aliases only. They neither enumerate nor authorize presets.
_LEGACY_IDS = {"left": "two-layer.left-right.v1:A", "right": "two-layer.left-right.v1:B"}


@dataclass(frozen=True, slots=True)
class InfluenceFieldPreset:
    """Ephemeral manifest projection; never a second registry or saved schema."""

    identifier: str
    display_name: str
    relative_path: str
    checksum: str

    def to_json(self) -> dict[str, str]:
        # The client needs no filesystem paths, PNG bytes, or execution policy.
        return {"id": self.identifier, "display_name": self.display_name}


def product_field_presets() -> tuple[InfluenceFieldPreset, ...]:
    """Enumerate eligible partition fields in catalog, then manifest order.

    Complements and previews are different manifest roles, not implicitly
    selectable partition fields. P1A must govern any future complement exposure.
    Only metadata is read here; selected PNGs are verified at retrieval.
    """

    try:
        root = _LIBRARY_ROOT.resolve(strict=True)
        catalog = json.loads(_read_contained(root / "library-manifest.json", root, MAX_METADATA_BYTES))
        if (
            not isinstance(catalog, dict)
            or catalog.get("library_id") != "conditioning-layers.influence-field-library"
            or type(catalog.get("library_version")) is not int
            or catalog["library_version"] != 1
            or not isinstance(catalog.get("families"), list)
            or len(catalog["families"]) > 64
        ):
            raise ValueError("invalid catalog")
        presets = []
        seen = set()
        for record in catalog["families"]:
            if not isinstance(record, dict):
                raise ValueError("invalid family record")
            family_id = record.get("pattern_family_id")
            if (
                not isinstance(family_id, str)
                or len(family_id) > 128
                or _FAMILY_ID.fullmatch(family_id) is None
                or family_id in seen
                or record.get("support_status") not in _STATUSES
            ):
                raise ValueError("invalid or duplicate family identity")
            seen.add(family_id)
            if record["support_status"] != _PRODUCT_STATUS:
                continue
            manifest_filename = f"manifests/{family_id}.manifest.json"
            if record.get("manifest_filename") != manifest_filename:
                raise ValueError("invalid manifest reference")
            raw = _read_contained(root / manifest_filename, root, MAX_METADATA_BYTES)
            if hashlib.sha256(raw).hexdigest() != record.get("manifest_sha256"):
                raise ValueError("manifest identity mismatch")
            manifest = json.loads(raw)
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_id") != "conditioning-layers.influence-field-family-manifest"
                or type(manifest.get("schema_version")) is not int
                or manifest["schema_version"] != 1
                or type(manifest.get("library_version")) is not int
                or manifest["library_version"] != 1
                or manifest.get("pattern_family_id") != family_id
                or manifest.get("support_status") != _PRODUCT_STATUS
                or manifest.get("image_mode") != "grayscale-8"
                or manifest.get("resolution") != {"width": 128, "height": 128}
                or any(type(value) is not int for value in manifest["resolution"].values())
                or type(manifest.get("layer_count")) is not int
                or manifest["layer_count"] not in (2, 3)
                or type(record.get("layer_count")) is not int
                or record["layer_count"] != manifest["layer_count"]
            ):
                raise ValueError("invalid eligible manifest")
            fields = manifest.get("fields")
            if (
                not isinstance(fields, list)
                or len(fields) != manifest["layer_count"]
                or not all(isinstance(field, dict) for field in fields)
                or sorted(field.get("asset_id", "") for field in fields) != list("ABC"[:len(fields)])
            ):
                raise ValueError("invalid or duplicate field identities")
            name = manifest.get("display_name")
            if not isinstance(name, str) or not name.strip() or len(name) > 160:
                raise ValueError("invalid display name")
            # Slash-separated family names follow canonical A/B/C label order
            # in this library, independent of enumeration order. An unsplit
            # family name is qualified by the explicit field ID.
            labels = [label.strip() for label in name.split("/")]
            for field in fields:
                asset_id = field["asset_id"]
                filename, checksum = field.get("filename"), field.get("sha256")
                if (
                    field.get("role") != "partition-field"
                    or not isinstance(filename, str)
                    or not filename or "\\" in filename or ":" in filename
                    or not isinstance(checksum, str) or _SHA256.fullmatch(checksum) is None
                ):
                    raise ValueError("invalid field metadata")
                relative = PurePosixPath(filename)
                if (
                    relative.is_absolute() or ".." in relative.parts
                    or relative.suffix != ".png"
                    or relative.parts[:2] != tuple(family_id.split(".")[:2])
                ):
                    raise ValueError("field path escapes its family")
                label = (labels[ord(asset_id) - ord("A")]
                         if len(labels) == len(fields) and all(labels)
                         else f"{name} — Field {asset_id}")
                presets.append(InfluenceFieldPreset(f"{family_id}:{asset_id}", label, filename, checksum))
        return tuple(presets)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        raise _unavailable() from error


def read_starter_field(starter_id: str) -> bytes:
    """Resolve a stable preset ID (or exact legacy alias) through eligibility."""

    if not isinstance(starter_id, str):
        raise _not_found()
    preset_id = _LEGACY_IDS.get(starter_id, starter_id)
    if len(preset_id) > 130 or _PRESET_ID.fullmatch(preset_id) is None:
        raise _not_found()
    preset = next((item for item in product_field_presets() if item.identifier == preset_id), None)
    if preset is None:
        # Preserve the old route's unavailable response for a withdrawn starter.
        raise _unavailable() if starter_id in _LEGACY_IDS else _not_found()
    try:
        root = _LIBRARY_ROOT.resolve(strict=True)
        family_root = root.joinpath(*PurePosixPath(preset.relative_path).parts[:2]).resolve(strict=True)
        if not family_root.is_relative_to(root):
            raise ValueError("family escapes library")
        path = root / preset.relative_path
        data = _read_contained(path, family_root, MAX_FIELD_BYTES)
        if hashlib.sha256(data).hexdigest() != preset.checksum:
            raise ValueError("field checksum mismatch")
        decoded = inspect_png_bytes(path, layer_id="preset", relative_reference=preset.relative_path,
                                    limits=DEFAULT_INSPECTION_LIMITS)
        if (decoded.profile.checksum != preset.checksum
                or (decoded.profile.width, decoded.profile.height, decoded.profile.channel_count) != (128, 128, 1)
                or not set(decoded.values) <= {0, 255}):
            raise ValueError("field does not match library metadata")
        return data
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, AssetInspectionError) as error:
        raise _unavailable() from error


def _not_found() -> PanelRequestError:
    return PanelRequestError("panel.starter.not_found", "The requested Influence Field preset was not found.", status=404)


def _unavailable() -> PanelRequestError:
    return PanelRequestError("panel.starter.unavailable",
                             "Influence Field presets are unavailable. Custom PNG import remains available.", status=503)


def _read_contained(path: Path, trusted_root: Path, limit: int) -> bytes:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_relative_to(trusted_root) or not resolved.is_file():
        raise ValueError("preset asset is not a contained regular file")
    with resolved.open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("preset asset size is invalid")
    return data
