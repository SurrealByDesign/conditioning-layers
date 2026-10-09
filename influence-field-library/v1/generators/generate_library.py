"""Generate the deterministic Conditioning Layers Influence Field Library v1."""

from __future__ import annotations

import argparse
import binascii
from dataclasses import dataclass
import hashlib
import itertools
import json
from pathlib import Path
import struct
import uuid
import zlib


WIDTH = 128
HEIGHT = 128
SCHEMA_ID = "conditioning-layers.influence-field-family-manifest"
SCHEMA_VERSION = 1
LIBRARY_VERSION = 1
GENERATOR_ID = "conditioning-layers.influence-field-library.generator"
GENERATOR_VERSION = 1
SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT = SCRIPT_PATH.parents[1]
REPOSITORY_ROOT = SCRIPT_PATH.parents[3]
MANIFEST_SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "influence-field-family-manifest.v1.schema.json"
VALID_SUPPORT_STATUSES = {
    "validated-product-asset",
    "research-only",
    "illustrative",
    "unsupported",
}
LAYER_PROMPTS = (
    "Matte red ceramic surface.",
    "Glossy blue glazed ceramic surface.",
    "Pale speckled stoneware surface.",
)
BASE_PROMPT = (
    "A single centered wide ceramic relief panel in a simple studio photograph "
    "on a plain neutral background with soft diffuse lighting, no text."
)


@dataclass(frozen=True, slots=True)
class FamilyDefinition:
    family_id: str
    slug: str
    display_name: str
    description: str
    layer_count: int
    support_status: str
    parameters: dict[str, object]
    intended_use: tuple[str, ...]
    known_limitations: tuple[str, ...]
    geometric_variants: tuple[dict[str, object], ...]


FAMILIES = (
    FamilyDefinition(
        family_id="two-layer.left-right.v1",
        slug="left-right",
        display_name="Left / Right",
        description="Exact hard partition at the vertical center line.",
        layer_count=2,
        support_status="validated-product-asset",
        parameters={"kind": "vertical_split", "split_x": 64},
        intended_use=("product reference", "two-layer spatial assignment"),
        known_limitations=(
            "A hard center boundary can produce seams, contact, or fusion.",
            "Asset validation does not guarantee prompt confinement.",
        ),
        geometric_variants=(
            {
                "variant_id": "mirror-horizontal",
                "operation": "mirror-horizontal",
                "target_pattern_family_id": "two-layer.left-right.v1",
                "source_to_target_field_mapping": {"A": "B", "B": "A"},
            },
            {
                "variant_id": "rotate-90-clockwise",
                "operation": "rotate-90-clockwise",
                "target_pattern_family_id": "two-layer.top-bottom.v1",
                "source_to_target_field_mapping": {"A": "A", "B": "B"},
            },
        ),
    ),
    FamilyDefinition(
        family_id="two-layer.top-bottom.v1",
        slug="top-bottom",
        display_name="Top / Bottom",
        description="Exact hard partition at the horizontal center line.",
        layer_count=2,
        support_status="research-only",
        parameters={"kind": "horizontal_split", "split_y": 64},
        intended_use=("research control", "two-layer spatial assignment"),
        known_limitations=(
            "This exact asset family has not completed product-path validation.",
            "A hard center boundary can produce seams or topology changes.",
        ),
        geometric_variants=(
            {
                "variant_id": "mirror-vertical",
                "operation": "mirror-vertical",
                "target_pattern_family_id": "two-layer.top-bottom.v1",
                "source_to_target_field_mapping": {"A": "B", "B": "A"},
            },
            {
                "variant_id": "rotate-90-counterclockwise",
                "operation": "rotate-90-counterclockwise",
                "target_pattern_family_id": "two-layer.left-right.v1",
                "source_to_target_field_mapping": {"A": "A", "B": "B"},
            },
        ),
    ),
    FamilyDefinition(
        family_id="three-layer.vertical-thirds.v1",
        slug="vertical-thirds",
        display_name="Vertical Thirds",
        description="Three mutually exclusive vertical regions with complete coverage.",
        layer_count=3,
        support_status="research-only",
        parameters={"kind": "vertical_thirds", "boundaries_x": [43, 85]},
        intended_use=("EXP-0013 candidate", "three-layer scaling research"),
        known_limitations=(
            "Three Active Prompt Layers are rejected by the current product.",
            "No three-layer rendering or performance claim is established.",
        ),
        geometric_variants=(
            {
                "variant_id": "mirror-horizontal",
                "operation": "mirror-horizontal",
                "target_pattern_family_id": "three-layer.vertical-thirds.v1",
                "source_to_target_field_mapping": {"A": "C", "B": "B", "C": "A"},
            },
            {
                "variant_id": "rotate-90-clockwise",
                "operation": "rotate-90-clockwise",
                "target_pattern_family_id": "three-layer.horizontal-thirds.v1",
                "source_to_target_field_mapping": {"A": "A", "B": "B", "C": "C"},
            },
            {
                "variant_id": "rotate-90-counterclockwise",
                "operation": "rotate-90-counterclockwise",
                "target_pattern_family_id": "three-layer.horizontal-thirds.v1",
                "source_to_target_field_mapping": {"A": "C", "B": "B", "C": "A"},
            },
        ),
    ),
    FamilyDefinition(
        family_id="three-layer.horizontal-thirds.v1",
        slug="horizontal-thirds",
        display_name="Horizontal Thirds",
        description="Three mutually exclusive horizontal regions with complete coverage.",
        layer_count=3,
        support_status="research-only",
        parameters={"kind": "horizontal_thirds", "boundaries_y": [43, 85]},
        intended_use=("EXP-0013 candidate", "three-layer scaling research"),
        known_limitations=(
            "Three Active Prompt Layers are rejected by the current product.",
            "No three-layer rendering or performance claim is established.",
        ),
        geometric_variants=(
            {
                "variant_id": "mirror-vertical",
                "operation": "mirror-vertical",
                "target_pattern_family_id": "three-layer.horizontal-thirds.v1",
                "source_to_target_field_mapping": {"A": "C", "B": "B", "C": "A"},
            },
            {
                "variant_id": "rotate-90-clockwise",
                "operation": "rotate-90-clockwise",
                "target_pattern_family_id": "three-layer.vertical-thirds.v1",
                "source_to_target_field_mapping": {"A": "C", "B": "B", "C": "A"},
            },
            {
                "variant_id": "rotate-90-counterclockwise",
                "operation": "rotate-90-counterclockwise",
                "target_pattern_family_id": "three-layer.vertical-thirds.v1",
                "source_to_target_field_mapping": {"A": "A", "B": "B", "C": "C"},
            },
        ),
    ),
    FamilyDefinition(
        family_id="three-layer.center-ring-outer.v1",
        slug="center-ring-outer",
        display_name="Center Disk / Middle Ring / Outer Field",
        description="Concentric hard partition with a center disk, middle ring, and outer region.",
        layer_count=3,
        support_status="research-only",
        parameters={
            "kind": "center_ring_outer",
            "center_x_doubled": 127,
            "center_y_doubled": 127,
            "inner_radius_pixels": 24,
            "outer_radius_pixels": 48,
        },
        intended_use=("post-simple-gate research candidate", "non-linear topology reference"),
        known_limitations=(
            "This family is excluded from the initial EXP-0013 simple-partition gate.",
            "Prior nested/radial research observed geometry artifacts and global collapse.",
            "Three Active Prompt Layers are rejected by the current product.",
        ),
        geometric_variants=(
            {
                "variant_id": "rotate-or-mirror-invariant",
                "operation": "all-right-angle-rotations-and-axis-mirrors",
                "target_pattern_family_id": "three-layer.center-ring-outer.v1",
                "source_to_target_field_mapping": {"A": "A", "B": "B", "C": "C"},
            },
            {
                "variant_id": "center-edge-assignment-reversal",
                "operation": "assignment-only-center-edge-reversal",
                "target_pattern_family_id": "three-layer.center-ring-outer.v1",
                "source_to_target_field_mapping": {"A": "C", "B": "B", "C": "A"},
            },
        ),
    ),
)


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    body = chunk_type + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body))


def encode_grayscale8(pixels: bytes) -> bytes:
    if len(pixels) != WIDTH * HEIGHT:
        raise ValueError("pixel buffer must be exactly 128 x 128 bytes")
    scanlines = b"".join(
        b"\x00" + pixels[y * WIDTH : (y + 1) * WIDTH] for y in range(HEIGHT)
    )
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + _chunk(b"IEND", b"")
    )


def _pixels(function) -> bytes:
    return bytes(function(x, y) for y in range(HEIGHT) for x in range(WIDTH))


def _partition_fields(definition: FamilyDefinition) -> dict[str, bytes]:
    kind = definition.parameters["kind"]
    if kind == "vertical_split":
        labels = _pixels(lambda x, _y: 0 if x < 64 else 1)
    elif kind == "horizontal_split":
        labels = _pixels(lambda _x, y: 0 if y < 64 else 1)
    elif kind == "vertical_thirds":
        labels = _pixels(lambda x, _y: 0 if x < 43 else (1 if x < 85 else 2))
    elif kind == "horizontal_thirds":
        labels = _pixels(lambda _x, y: 0 if y < 43 else (1 if y < 85 else 2))
    elif kind == "center_ring_outer":
        inner_squared = (2 * 24) ** 2
        outer_squared = (2 * 48) ** 2

        def region(x: int, y: int) -> int:
            distance_squared = (2 * x - 127) ** 2 + (2 * y - 127) ** 2
            if distance_squared < inner_squared:
                return 0
            return 1 if distance_squared < outer_squared else 2

        labels = _pixels(region)
    else:
        raise ValueError(f"unsupported family kind: {kind}")
    return {
        chr(65 + index): bytes(255 if label == index else 0 for label in labels)
        for index in range(definition.layer_count)
    }


def _validate_partition(fields: dict[str, bytes], layer_count: int) -> tuple[int, int]:
    expected_ids = tuple(chr(65 + index) for index in range(layer_count))
    if tuple(fields) != expected_ids:
        raise ValueError("partition field IDs are not canonical")
    if any(len(values) != WIDTH * HEIGHT for values in fields.values()):
        raise ValueError("partition field dimensions are invalid")
    if any(set(values) - {0, 255} for values in fields.values()):
        raise ValueError("partition fields must be binary grayscale")
    overlap = 0
    unassigned = 0
    for pixel_values in zip(*(fields[field_id] for field_id in expected_ids), strict=True):
        nonzero = sum(value > 0 for value in pixel_values)
        overlap += int(nonzero > 1)
        unassigned += int(nonzero == 0)
        if sum(pixel_values) != 255:
            raise ValueError("partition fields do not sum to 255 at every pixel")
    if overlap or unassigned:
        raise ValueError("partition must have zero overlap and complete coverage")
    return overlap, unassigned


def _complements(fields: dict[str, bytes]) -> dict[str, bytes]:
    complements = {
        f"not-{field_id}": bytes(255 - value for value in values)
        for field_id, values in fields.items()
    }
    for field_id, values in fields.items():
        other_ids = tuple(candidate for candidate in fields if candidate != field_id)
        expected = bytes(
            sum(fields[candidate][index] for candidate in other_ids)
            for index in range(WIDTH * HEIGHT)
        )
        if complements[f"not-{field_id}"] != expected:
            raise ValueError(f"not-{field_id} does not equal the other partition fields")
        if any(a + b != 255 for a, b in zip(values, complements[f"not-{field_id}"], strict=True)):
            raise ValueError(f"not-{field_id} is not an exact pixel inverse")
    return complements


def _preview(fields: dict[str, bytes]) -> bytes:
    levels = (80, 208) if len(fields) == 2 else (64, 144, 224)
    ordered = tuple(fields)
    output = bytearray(WIDTH * HEIGHT)
    for index in range(WIDTH * HEIGHT):
        members = [position for position, field_id in enumerate(ordered) if fields[field_id][index] == 255]
        if len(members) != 1:
            raise ValueError("preview requires an exact partition")
        output[index] = levels[members[0]]
    return bytes(output)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    observed = _sha256(path.read_bytes())
    expected = _sha256(data)
    if observed != expected:
        raise RuntimeError(f"post-write identity mismatch: {path}")
    return observed


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _asset_entry(asset_id: str, filename: str, sha256: str, role: str) -> dict[str, object]:
    return {"asset_id": asset_id, "filename": filename, "role": role, "sha256": sha256}


def _workflow(definition: FamilyDefinition, field_entries: list[dict[str, object]]) -> dict[str, object]:
    classification = "illustrative" if definition.layer_count == 2 else "expected-rejection"
    execution_status = "asset-inspection-only" if definition.layer_count == 2 else "not-authorized"
    prompts = LAYER_PROMPTS[: definition.layer_count]
    note_lines = [
        f"INFLUENCE FIELD LIBRARY V1 — {definition.display_name}",
        "",
        f"Pattern family: {definition.family_id}",
        f"Classification: {classification}",
        f"Execution status: {execution_status}",
        "",
        "FROZEN REFERENCE SETTINGS (NOT QUEUED BY THIS WORKFLOW)",
        f"Base Prompt: {BASE_PROMPT}",
    ]
    note_lines.extend(
        f"Layer {chr(65 + index)}: {prompt} | Strength 1.0 | field-{chr(97 + index)}.png"
        for index, prompt in enumerate(prompts)
    )
    note_lines.extend(
        [
            "Model: krea2_turbo_bf16.safetensors",
            "Seed: 27182818 | Euler | Simple | 8 steps | CFG 1.0 | denoise 1.0",
            "Resolution: 1024 x 1024 | batch 1 | negative prompt empty",
            "",
            "EXPECTED OBSERVATION",
            "Confirm asset identity, orientation, partition coverage, and field labels.",
            "This workflow contains no model or sampler nodes and performs no image generation.",
        ]
    )
    if definition.layer_count == 3:
        note_lines.extend(
            [
                "The current product must reject three Active Prompt Layers before submission.",
                "Do not add an execution chain or treat this as three-layer qualification.",
            ]
        )
    note = "\n".join(note_lines)
    nodes: list[dict[str, object]] = [
        {
            "id": 1,
            "type": "Note",
            "pos": [-900, -500],
            "size": [700, 620],
            "flags": {},
            "order": 0,
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "properties": {"text": note},
            "widgets_values": [note],
        }
    ]
    links: list[list[object]] = []
    next_node_id = 2
    next_link_id = 1
    for index, entry in enumerate(field_entries):
        load_id = next_node_id
        preview_id = next_node_id + 1
        next_node_id += 2
        link_id = next_link_id
        next_link_id += 1
        input_name = f"conditioning-layers-library/{entry['filename']}"
        nodes.append(
            {
                "id": load_id,
                "type": "LoadImage",
                "pos": [-100, -350 + index * 320],
                "size": [320, 300],
                "flags": {},
                "order": load_id - 1,
                "mode": 0,
                "inputs": [],
                "outputs": [
                    {"name": "IMAGE", "type": "IMAGE", "links": [link_id]},
                    {"name": "MASK", "type": "MASK", "links": []},
                ],
                "properties": {"Node name for S&R": "LoadImage"},
                "widgets_values": [input_name, "image"],
            }
        )
        nodes.append(
            {
                "id": preview_id,
                "type": "PreviewImage",
                "pos": [320, -350 + index * 320],
                "size": [320, 300],
                "flags": {},
                "order": preview_id - 1,
                "mode": 0,
                "inputs": [
                    {"name": "images", "type": "IMAGE", "link": link_id}
                ],
                "outputs": [],
                "properties": {"Node name for S&R": "PreviewImage"},
                "widgets_values": [],
            }
        )
        links.append([link_id, load_id, 0, preview_id, 0, "IMAGE"])
    workflow_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"conditioning-layers:{definition.family_id}:asset-inspection"))
    return {
        "id": workflow_id,
        "revision": 0,
        "last_node_id": next_node_id - 1,
        "last_link_id": next_link_id - 1,
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {
            "frontendVersion": "1.45.21",
            "conditioning_layers_library": {
                "classification": classification,
                "execution_status": execution_status,
                "pattern_family_id": definition.family_id,
                "workflow_id": f"{definition.family_id}.asset-inspection",
            },
        },
        "version": 0.4,
    }


def _generate_family(output_root: Path, definition: FamilyDefinition, generator_sha256: str) -> dict[str, object]:
    if definition.support_status not in VALID_SUPPORT_STATUSES:
        raise ValueError("invalid support status")
    fields = _partition_fields(definition)
    overlap, unassigned = _validate_partition(fields, definition.layer_count)
    complements = _complements(fields)
    layer_directory = (
        "two-layer" if definition.layer_count == 2 else "three-layer"
    ) + f"/{definition.slug}"
    field_entries: list[dict[str, object]] = []
    for field_id, pixels in fields.items():
        filename = f"{layer_directory}/field-{field_id.lower()}.png"
        digest = _write_bytes(output_root / filename, encode_grayscale8(pixels))
        field_entries.append(_asset_entry(field_id, filename, digest, "partition-field"))
    complement_entries: list[dict[str, object]] = []
    for complement_id, pixels in complements.items():
        source_id = complement_id.removeprefix("not-")
        filename = f"{layer_directory}/{complement_id.lower()}.png"
        digest = _write_bytes(output_root / filename, encode_grayscale8(pixels))
        other_ids = [field_id for field_id in fields if field_id != source_id]
        entry = _asset_entry(complement_id, filename, digest, "pixel-complement")
        entry.update(
            {
                "source_field_id": source_id,
                "expression": f"255 - {source_id}",
                "equivalent_partition_sum": other_ids,
            }
        )
        complement_entries.append(entry)
    preview_filename = f"previews/{definition.family_id}.png"
    preview_digest = _write_bytes(
        output_root / preview_filename,
        encode_grayscale8(_preview(fields)),
    )
    workflow_filename = f"workflows/{definition.family_id}.asset-inspection.workflow.json"
    workflow_payload = _workflow(definition, field_entries)
    workflow_digest = _write_bytes(output_root / workflow_filename, _json_bytes(workflow_payload))
    classification = "illustrative" if definition.layer_count == 2 else "expected-rejection"
    execution_status = "asset-inspection-only" if definition.layer_count == 2 else "not-authorized"
    field_ids = tuple(fields)
    permutations = [
        {"permutation_id": "".join(permutation), "ordered_field_ids": list(permutation)}
        for permutation in itertools.permutations(field_ids)
    ]
    manifest = {
        "assignment_permutations": permutations,
        "binary_grayscale_status": {
            "complement_fields": "binary-grayscale-8",
            "partition_fields": "binary-grayscale-8",
            "preview": "illustrative-grayscale-8",
        },
        "compatible_workflows": [
            {
                "classification": classification,
                "execution_status": execution_status,
                "filename": workflow_filename,
                "sha256": workflow_digest,
                "workflow_id": f"{definition.family_id}.asset-inspection",
            }
        ],
        "description": definition.description,
        "display_name": definition.display_name,
        "fields": field_entries,
        "generator": {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "parameters": definition.parameters,
            "source_sha256": generator_sha256,
        },
        "geometric_variants": list(definition.geometric_variants),
        "image_mode": "grayscale-8",
        "intended_use": list(definition.intended_use),
        "known_limitations": list(definition.known_limitations),
        "layer_count": definition.layer_count,
        "library_version": LIBRARY_VERSION,
        "partition_relationship": {
            "complete_coverage": True,
            "equation": " + ".join(field_ids) + " = 255",
            "overlap_pixel_count": overlap,
            "per_pixel_sum": 255,
            "unassigned_pixel_count": unassigned,
        },
        "pattern_family_id": definition.family_id,
        "pixel_complements": complement_entries,
        "preview": _asset_entry(
            f"{definition.family_id}.preview",
            preview_filename,
            preview_digest,
            "composite-preview",
        ),
        "resolution": {"height": HEIGHT, "width": WIDTH},
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "support_status": definition.support_status,
    }
    manifest_filename = f"manifests/{definition.family_id}.manifest.json"
    manifest_digest = _write_bytes(output_root / manifest_filename, _json_bytes(manifest))
    return {
        "layer_count": definition.layer_count,
        "manifest_filename": manifest_filename,
        "manifest_sha256": manifest_digest,
        "pattern_family_id": definition.family_id,
        "support_status": definition.support_status,
    }


def generate(output_root: Path = DEFAULT_OUTPUT_ROOT) -> None:
    output_root = output_root.resolve()
    generator_sha256 = _sha256(SCRIPT_PATH.read_bytes())
    if not MANIFEST_SCHEMA_PATH.is_file():
        raise RuntimeError("Influence Field Library manifest schema is missing")
    family_records = [
        _generate_family(output_root, definition, generator_sha256)
        for definition in FAMILIES
    ]
    catalog = {
        "families": family_records,
        "generator": {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "source_sha256": generator_sha256,
        },
        "library_id": "conditioning-layers.influence-field-library",
        "library_version": LIBRARY_VERSION,
        "manifest_schema": {
            "filename": "schemas/influence-field-family-manifest.v1.schema.json",
            "sha256": _sha256(MANIFEST_SCHEMA_PATH.read_bytes()),
        },
    }
    _write_bytes(output_root / "library-manifest.json", _json_bytes(catalog))
    validate_generated_library(output_root)


def validate_generated_library(output_root: Path) -> None:
    catalog = json.loads((output_root / "library-manifest.json").read_text(encoding="utf-8"))
    if len(catalog.get("families", ())) != len(FAMILIES):
        raise RuntimeError("library catalog family count mismatch")
    for record in catalog["families"]:
        manifest_path = output_root / record["manifest_filename"]
        if _sha256(manifest_path.read_bytes()) != record["manifest_sha256"]:
            raise RuntimeError("manifest identity mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["partition_relationship"] != {
            "complete_coverage": True,
            "equation": " + ".join(entry["asset_id"] for entry in manifest["fields"]) + " = 255",
            "overlap_pixel_count": 0,
            "per_pixel_sum": 255,
            "unassigned_pixel_count": 0,
        }:
            raise RuntimeError("partition relationship mismatch")
        for entry in (
            manifest["fields"]
            + manifest["pixel_complements"]
            + [manifest["preview"]]
            + manifest["compatible_workflows"]
        ):
            path = output_root / entry["filename"]
            if not path.is_file() or _sha256(path.read_bytes()) != entry["sha256"]:
                raise RuntimeError(f"generated identity mismatch: {entry['filename']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    generate(args.output_root)


if __name__ == "__main__":
    main()
