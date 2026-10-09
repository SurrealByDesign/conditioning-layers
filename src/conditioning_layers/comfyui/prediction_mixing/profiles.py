"""Exact ComfyUI host profiles and static graph-compatibility evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType

from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .inventory import CANONICAL_COMFYUI_INVENTORY, NODE_CONTRACTS
from .models import ComfyUIComponentInventory
from .node_contracts import (
    HostNodeContractRecord,
    HostNodeContractSnapshot,
    NodeInputEvidence,
    SemanticEvidenceRecord,
    create_host_node_contract_snapshot,
    create_node_contract_record,
    snapshot_is_supported,
)


COMFYUI_0280_PROFILE_IDENTIFIER = "comfyui-0.28.0.prediction-mixing.v1"
COMFYUI_0280_NODE_CONTRACT_IDENTIFIER = (
    "comfyui-core-0.28.0.prediction-mixing.v1"
)
COMFYUI_0280_INVENTORY_IDENTIFIER = (
    "krea2-turbo-bf16-1024-comfyui-0.28.0.v1"
)
COMFYUI_0280_SNAPSHOT_IDENTIFIER = (
    "comfyui-0.28.0.700821e.prediction-mixing.static.v1"
)
COMFYUI_0280_REVISION = "700821e1364eaab0e8f21c538a2131719fec57bf"

_NODES_SHA256 = "aecd111cf3f1ccf5a5ca6b4293d47dfe236f9a717e5190cbb6a66a03afb8d009"
_HELPERS_SHA256 = "22317a033cce556331bfedc5f4ab6c2833184fd2bbdf9496c9182a4973a7098a"
_SAMPLERS_SHA256 = "d882256ae9baa1d23f1367ab2ec3b021fdc15fe39ce4cb49ea2c1ee10026a649"

_NODE_SYMBOL_FINGERPRINTS = {
    "UNETLoader": "5e09c76474a2a25f2d56a03365ea1e9eee98aa33a137fd36804e7e76e168ac58",
    "CLIPLoader": "058ef044855252b33f155ea7dedbdefb53e37b219665ad87a6581a0bd4d40b75",
    "CLIPTextEncode": "e82e7e7c78e9899746da4daf9740f6a5c4436759db390e0c0bdeca2599deb8dc",
    "LoadImageMask": "1d76eb3d621b5a2e607821584b50bbc3c773d43b8a700528e0952017696eb4f6",
    "ConditioningSetMask": "ae9414e3d0340aa6b8faaec159f363a66ab512d8c9015f306c206b931a775752",
    "ConditioningCombine": "1ca44cdf2575d38da30563036f68144b4849b77825f680e2a0a00b2079fb3b70",
    "EmptyLatentImage": "b43edd8ed00aaa911a16ee8dccef740c58a7c08d2601b1ef796fa505fd683dbc",
    "KSampler": "511d924097d6409e91112380edf38a2665d8780910254e7074ed3706dc4b0358",
    "VAELoader": "d93244e17bb4c24a4069ec548041754b05e95d1a44e9b800a595890e60db007a",
    "VAEDecode": "415fc89ff153646c5144cbccb93049ac7a052de28438c49e99259ec75920d383",
    "SaveImage": "03032738051814439b9368eef80264e0dc3c770c04ed32e4870f426df3171104",
}

_SAMPLER_SYMBOL_FINGERPRINTS = {
    "get_area_and_mult": "519a97cd458a47aef4f6856e9d9ca3c95ccf831c7896b04f30fe2b937cb3f1a7",
    "_calc_cond_batch": "c11a2665d97abaa13fbcbe47d0fedfeb720625be03bc1d1e36dcda3b81c7132f",
    "cfg_function": "e4f583585ace25e0f153ff5d1586dcf88dcf83361f0900f4252f30da5fb12813",
    "sampling_function": "b2548ba220b52d155531817c39f87514dfe3d209ba4ae281da23538feef33884",
}


class ProfileCompatibilityVerdict(str, Enum):
    """The four allowed outcomes of a host-profile review."""

    COMPATIBLE = "compatible"
    STRUCTURAL_SEMANTICS_UNRESOLVED = (
        "structurally_compatible_but_semantically_unresolved"
    )
    INCOMPATIBLE = "incompatible"
    INCONCLUSIVE = "inconclusive"


class ProfileSupportStatus(str, Enum):
    """Product support policy, distinct from static compatibility findings."""

    SUPPORTED = "supported"
    QUALIFICATION_ONLY = "qualification_only"


@dataclass(frozen=True, slots=True)
class CompatibilityProfile:
    """Internal selection of retained expected evidence and support policy."""

    inventory: ComfyUIComponentInventory
    node_snapshot: HostNodeContractSnapshot
    status: ProfileSupportStatus


@dataclass(frozen=True, slots=True)
class GraphProfileCompatibilityResult:
    """Immutable structured result without host execution or introspection."""

    verdict: ProfileCompatibilityVerdict
    structurally_compatible: bool
    semantically_compatible: bool
    supported: bool
    findings: tuple[ValidationFinding, ...]


def _input(
    name: str,
    requirement: str,
    accepted_type: str,
    *,
    enum_values: tuple[str, ...] = (),
    default: object | None = None,
    external: str | None = None,
) -> NodeInputEvidence:
    return NodeInputEvidence(
        name=name,
        host_requirement=requirement,
        accepted_type=accepted_type,
        enum_values=enum_values,
        default_value=default,
        external_enumeration=external,
    )


def _node(
    class_name: str,
    *,
    required: tuple[str, ...],
    host_required: tuple[str, ...],
    host_optional: tuple[str, ...] = (),
    inputs: tuple[NodeInputEvidence, ...],
    returns: tuple[str, ...],
    outputs_used: tuple[int, ...],
    function: str,
) -> HostNodeContractRecord:
    return create_node_contract_record(
        class_name=class_name,
        required_inputs=tuple(sorted(required)),
        output_indices=outputs_used,
        host_required_inputs=host_required,
        host_optional_inputs=host_optional,
        input_evidence=inputs,
        return_types=returns,
        function_name=function,
        source_file="nodes.py",
        source_symbol=class_name,
        source_file_sha256=_NODES_SHA256,
        source_symbol_fingerprint=_NODE_SYMBOL_FINGERPRINTS[class_name],
    )


COMFYUI_0280_NODE_CONTRACTS = MappingProxyType({
    "UNETLoader": _node(
        "UNETLoader",
        required=("unet_name", "weight_dtype"),
        host_required=("unet_name", "weight_dtype"),
        inputs=(
            _input("unet_name", "required", "STRING", external="diffusion_models"),
            _input(
                "weight_dtype",
                "required",
                "STRING",
                enum_values=("default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"),
                default="default",
            ),
        ),
        returns=("MODEL",),
        outputs_used=(0,),
        function="load_unet",
    ),
    "CLIPLoader": _node(
        "CLIPLoader",
        required=("clip_name", "type", "device"),
        host_required=("clip_name", "type"),
        host_optional=("device",),
        inputs=(
            _input("clip_name", "required", "STRING", external="text_encoders"),
            _input("type", "required", "STRING", enum_values=("krea2",)),
            _input(
                "device",
                "optional",
                "STRING",
                enum_values=("default", "cpu"),
                default="default",
            ),
        ),
        returns=("CLIP",),
        outputs_used=(0,),
        function="load_clip",
    ),
    "CLIPTextEncode": _node(
        "CLIPTextEncode",
        required=("text", "clip"),
        host_required=("text", "clip"),
        inputs=(
            _input("text", "required", "STRING"),
            _input("clip", "required", "CLIP"),
        ),
        returns=("CONDITIONING",),
        outputs_used=(0,),
        function="encode",
    ),
    "LoadImageMask": _node(
        "LoadImageMask",
        required=("image", "channel"),
        host_required=("image", "channel"),
        inputs=(
            _input("image", "required", "STRING", external="input_images"),
            _input(
                "channel",
                "required",
                "STRING",
                enum_values=("alpha", "red", "green", "blue"),
                default="alpha",
            ),
        ),
        returns=("MASK",),
        outputs_used=(0,),
        function="load_image_mask",
    ),
    "ConditioningSetMask": _node(
        "ConditioningSetMask",
        required=("conditioning", "mask", "strength", "set_cond_area"),
        host_required=("conditioning", "mask", "strength", "set_cond_area"),
        inputs=(
            _input("conditioning", "required", "CONDITIONING"),
            _input("mask", "required", "MASK"),
            _input("strength", "required", "FLOAT", default=1.0),
            _input(
                "set_cond_area",
                "required",
                "STRING",
                enum_values=("default", "mask bounds"),
                default="default",
            ),
        ),
        returns=("CONDITIONING",),
        outputs_used=(0,),
        function="append",
    ),
    "ConditioningCombine": _node(
        "ConditioningCombine",
        required=("conditioning_1", "conditioning_2"),
        host_required=("conditioning_1", "conditioning_2"),
        inputs=(
            _input("conditioning_1", "required", "CONDITIONING"),
            _input("conditioning_2", "required", "CONDITIONING"),
        ),
        returns=("CONDITIONING",),
        outputs_used=(0,),
        function="combine",
    ),
    "EmptyLatentImage": _node(
        "EmptyLatentImage",
        required=("width", "height", "batch_size"),
        host_required=("width", "height", "batch_size"),
        inputs=(
            _input("width", "required", "INT", default=512),
            _input("height", "required", "INT", default=512),
            _input("batch_size", "required", "INT", default=1),
        ),
        returns=("LATENT",),
        outputs_used=(0,),
        function="generate",
    ),
    "KSampler": _node(
        "KSampler",
        required=(
            "model", "seed", "steps", "cfg", "sampler_name", "scheduler",
            "positive", "negative", "latent_image", "denoise",
        ),
        host_required=(
            "model", "seed", "steps", "cfg", "sampler_name", "scheduler",
            "positive", "negative", "latent_image", "denoise",
        ),
        inputs=(
            _input("model", "required", "MODEL"),
            _input("seed", "required", "INT", default=0),
            _input("steps", "required", "INT", default=20),
            _input("cfg", "required", "FLOAT", default=8.0),
            _input("sampler_name", "required", "STRING", enum_values=("euler",), external="comfy.samplers.SAMPLER_NAMES"),
            _input("scheduler", "required", "STRING", enum_values=("simple",), external="comfy.samplers.SCHEDULER_NAMES"),
            _input("positive", "required", "CONDITIONING"),
            _input("negative", "required", "CONDITIONING"),
            _input("latent_image", "required", "LATENT"),
            _input("denoise", "required", "FLOAT", default=1.0),
        ),
        returns=("LATENT",),
        outputs_used=(0,),
        function="sample",
    ),
    "VAELoader": _node(
        "VAELoader",
        required=("vae_name",),
        host_required=("vae_name",),
        inputs=(_input("vae_name", "required", "STRING", external="vae"),),
        returns=("VAE",),
        outputs_used=(0,),
        function="load_vae",
    ),
    "VAEDecode": _node(
        "VAEDecode",
        required=("samples", "vae"),
        host_required=("samples", "vae"),
        inputs=(
            _input("samples", "required", "LATENT"),
            _input("vae", "required", "VAE"),
        ),
        returns=("IMAGE",),
        outputs_used=(0,),
        function="decode",
    ),
    "SaveImage": _node(
        "SaveImage",
        required=("images", "filename_prefix"),
        host_required=("images", "filename_prefix"),
        inputs=(
            _input("images", "required", "IMAGE"),
            _input("filename_prefix", "required", "STRING", default="ComfyUI"),
        ),
        returns=("IMAGE",),
        outputs_used=(),
        function="save_images",
    ),
})


COMFYUI_0280_SEMANTIC_EVIDENCE = (
    SemanticEvidenceRecord(
        evidence_identifier="prediction_mixing.conditioning_set_mask",
        source_file="nodes.py",
        source_symbols=("ConditioningSetMask",),
        source_file_sha256=_NODES_SHA256,
        symbol_fingerprints=(_NODE_SYMBOL_FINGERPRINTS["ConditioningSetMask"],),
        conclusion="confirmed",
        notes=(
            "The default area leaves set_area_to_bounds false; mask_strength receives "
            "the graph Strength and the full mask is retained."
        ),
    ),
    SemanticEvidenceRecord(
        evidence_identifier="prediction_mixing.conditioning_combine",
        source_file="nodes.py",
        source_symbols=("ConditioningCombine",),
        source_file_sha256=_NODES_SHA256,
        symbol_fingerprints=(_NODE_SYMBOL_FINGERPRINTS["ConditioningCombine"],),
        conclusion="confirmed",
        notes="Combine returns conditioning_1 + conditioning_2 without rewriting entries.",
    ),
    SemanticEvidenceRecord(
        evidence_identifier="prediction_mixing.conditioning_metadata_copy",
        source_file="node_helpers.py",
        source_symbols=("conditioning_set_values",),
        source_file_sha256=_HELPERS_SHA256,
        symbol_fingerprints=(
            "2d762134c40dc2bd7de9f454661e4dfe3575294aa3dd744592a1715aa626d204",
        ),
        conclusion="confirmed",
        notes="Conditioning metadata is copied per entry before mask fields are set.",
    ),
    SemanticEvidenceRecord(
        evidence_identifier="prediction_mixing.regional_accumulation",
        source_file="comfy/samplers.py",
        source_symbols=("get_area_and_mult", "_calc_cond_batch"),
        source_file_sha256=_SAMPLERS_SHA256,
        symbol_fingerprints=(
            _SAMPLER_SYMBOL_FINGERPRINTS["get_area_and_mult"],
            _SAMPLER_SYMBOL_FINGERPRINTS["_calc_cond_batch"],
        ),
        conclusion="confirmed",
        notes=(
            "Mask and mask_strength form the multiplier; area remains None for the "
            "default setting, and regional predictions are weighted and normalized "
            "across the full latent."
        ),
    ),
    SemanticEvidenceRecord(
        evidence_identifier="prediction_mixing.cfg1_empty_negative",
        source_file="comfy/samplers.py",
        source_symbols=("sampling_function", "cfg_function"),
        source_file_sha256=_SAMPLERS_SHA256,
        symbol_fingerprints=(
            _SAMPLER_SYMBOL_FINGERPRINTS["sampling_function"],
            _SAMPLER_SYMBOL_FINGERPRINTS["cfg_function"],
        ),
        conclusion="confirmed",
        notes=(
            "At CFG 1.0 the unconditioned branch is omitted unless explicitly disabled; "
            "the graph's empty negative encoding remains structurally required but is "
            "not evaluated by the default CFG1 optimization."
        ),
    ),
)


COMFYUI_0280_NODE_SNAPSHOT = create_host_node_contract_snapshot(
    snapshot_identifier=COMFYUI_0280_SNAPSHOT_IDENTIFIER,
    profile_identifier=COMFYUI_0280_PROFILE_IDENTIFIER,
    comfyui_version="0.28.0",
    comfyui_revision=COMFYUI_0280_REVISION,
    contracts=COMFYUI_0280_NODE_CONTRACTS,
    source_reference="static-evidence/comfyui-0.28.0-700821e",
    semantic_evidence=COMFYUI_0280_SEMANTIC_EVIDENCE,
    source_file_hashes={
        "nodes.py": _NODES_SHA256,
        "node_helpers.py": _HELPERS_SHA256,
        "comfy/samplers.py": _SAMPLERS_SHA256,
    },
    limitations=(
        "Static validation covers only generated one- and two-layer Prediction Mixing graphs.",
        "Model filenames remain caller-verified external inventory values.",
        "No runtime import, node introspection, graph submission, or visual behavior claim is included.",
    ),
    evidence_timestamp="2026-07-15",
)


CANONICAL_COMFYUI_0280_INVENTORY = replace(
    CANONICAL_COMFYUI_INVENTORY,
    inventory_identifier=COMFYUI_0280_INVENTORY_IDENTIFIER,
    comfyui_profile_identifier=COMFYUI_0280_PROFILE_IDENTIFIER,
    expected_comfyui_version="0.28.0",
    expected_comfyui_revision=COMFYUI_0280_REVISION,
    node_contract_identifier=COMFYUI_0280_NODE_CONTRACT_IDENTIFIER,
)

# Retained M2 support-time record for historical reproduction. Current support
# selection belongs to REGISTERED_COMFYUI_PROFILES, not this historical name.
COMFYUI_0280_SUPPORTED_PROFILE = CompatibilityProfile(
    inventory=CANONICAL_COMFYUI_0280_INVENTORY,
    node_snapshot=COMFYUI_0280_NODE_SNAPSHOT,
    status=ProfileSupportStatus.SUPPORTED,
)

# Retained public legacy inventory lookup, not current product support policy.
# Historical 0.27.1 has no retained complete node snapshot; its migration to the
# status-bearing registry is deferred rather than borrowing M2 evidence.
SUPPORTED_COMFYUI_INVENTORIES = (
    CANONICAL_COMFYUI_INVENTORY,
    CANONICAL_COMFYUI_0280_INVENTORY,
)


def canonical_inventory_for_profile(
    profile_identifier: str,
) -> ComfyUIComponentInventory | None:
    """Preserve the legacy 0.27.1/0.28.0 lookup, not product support selection.

    New pinning callers use registered_inventory_for_profile; current support
    policy callers use supported_inventory_for_profile instead.
    """

    return next(
        (
            inventory
            for inventory in SUPPORTED_COMFYUI_INVENTORIES
            if inventory.comfyui_profile_identifier == profile_identifier
        ),
        None,
    )


def registered_inventory_for_profile(
    profile_identifier: str,
) -> ComfyUIComponentInventory | None:
    """Resolve exact registered evidence, including qualification-only pins.

    Historical 0.27.1 retains its inventory-only integrity lookup separately
    until legitimate complete snapshot evidence permits registry migration.
    Unknown identifiers never fall back to M2 or another profile.
    """

    # The assembly module depends on the record and M2 constants above.
    from .qualification_profiles import REGISTERED_COMFYUI_PROFILES

    if not isinstance(profile_identifier, str):
        return None
    profile = REGISTERED_COMFYUI_PROFILES.get(profile_identifier)
    if profile is not None:
        return profile.inventory
    if profile_identifier == CANONICAL_COMFYUI_INVENTORY.comfyui_profile_identifier:
        return CANONICAL_COMFYUI_INVENTORY
    return None


def supported_inventory_for_profile(
    profile_identifier: str,
) -> ComfyUIComponentInventory | None:
    """Resolve only exact SUPPORTED records; no historical or candidate fallback."""

    from .qualification_profiles import REGISTERED_COMFYUI_PROFILES

    if not isinstance(profile_identifier, str):
        return None
    profile = REGISTERED_COMFYUI_PROFILES.get(profile_identifier)
    if profile is None or profile.status is not ProfileSupportStatus.SUPPORTED:
        return None
    return profile.inventory


def evaluate_graph_profile_compatibility(
    graph: Mapping[str, object],
    inventory: ComfyUIComponentInventory,
    snapshot: HostNodeContractSnapshot,
) -> GraphProfileCompatibilityResult:
    """Check graph structure and separate semantic support without execution."""

    findings: list[ValidationFinding] = []
    structural = True
    if (
        snapshot.profile_identifier != inventory.comfyui_profile_identifier
        or snapshot.comfyui_version != inventory.expected_comfyui_version
        or snapshot.comfyui_revision.lower()
        != inventory.expected_comfyui_revision.lower()
    ):
        structural = False
        findings.append(_finding("profile.graph_incompatible", "Snapshot and inventory identity do not match."))

    for node_id, node in graph.items():
        if not isinstance(node, Mapping):
            structural = False
            findings.append(_finding("profile.node_contract_changed", f"Node {node_id} is not a mapping."))
            continue
        class_name = node.get("class_type")
        inputs = node.get("inputs")
        contract = snapshot.contracts.get(class_name) if isinstance(class_name, str) else None
        if contract is None:
            structural = False
            findings.append(_finding("profile.node_missing", f"Node {node_id} has no verified built-in contract."))
            continue
        if not isinstance(inputs, Mapping) or tuple(sorted(inputs)) != contract.required_inputs:
            structural = False
            findings.append(_finding("profile.node_contract_changed", f"Node {node_id} inputs differ from the verified contract."))
            continue
        for value in inputs.values():
            if not (
                isinstance(value, list | tuple)
                and len(value) == 2
                and isinstance(value[0], str)
                and isinstance(value[1], int)
                and not isinstance(value[1], bool)
            ):
                continue
            source = graph.get(value[0])
            source_name = source.get("class_type") if isinstance(source, Mapping) else None
            source_contract = snapshot.contracts.get(source_name) if isinstance(source_name, str) else None
            if source_contract is None or value[1] not in source_contract.output_indices:
                structural = False
                findings.append(_finding("profile.output_contract_changed", f"Node {node_id} references an unavailable output slot."))

    semantics = snapshot_is_supported(snapshot)
    if structural:
        findings.append(_finding("profile.graph_compatible", "The graph matches every required static node and output contract.", FindingSeverity.INFORMATION))
    if not semantics:
        findings.append(_finding("profile.semantic_contract_unresolved", "Semantic evidence is incomplete or not self-consistent."))

    if structural and semantics:
        verdict = ProfileCompatibilityVerdict.COMPATIBLE
        findings.extend(
            (
                _finding("profile.snapshot_created", "A deterministic trusted snapshot is available.", FindingSeverity.INFORMATION),
                _finding("profile.supported", "The exact host profile is supported.", FindingSeverity.INFORMATION),
            )
        )
    elif structural:
        verdict = ProfileCompatibilityVerdict.STRUCTURAL_SEMANTICS_UNRESOLVED
        findings.append(_finding("profile.not_supported", "The host profile is not supported."))
    else:
        verdict = ProfileCompatibilityVerdict.INCOMPATIBLE
        findings.append(_finding("profile.not_supported", "The host profile is not supported."))
    return GraphProfileCompatibilityResult(
        verdict=verdict,
        structurally_compatible=structural,
        semantically_compatible=semantics,
        supported=structural and semantics,
        findings=tuple(_deduplicate(findings)),
    )


def _finding(
    code: str,
    message: str,
    severity: FindingSeverity = FindingSeverity.ERROR,
) -> ValidationFinding:
    return ValidationFinding(code=code, severity=severity, message=message)


def _deduplicate(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    result: list[ValidationFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
