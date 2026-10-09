"""Static expected evidence for exact ComfyUI qualification candidates.

Retained C1-E1 expected evidence under ADR-0023, registered QUALIFICATION_ONLY
by C1-P1. Registration does not claim product support or establish generation
compatibility. This module reads no checkout/server at import time.

C1-S1 separately promotes the retained 0.34.6 identity in the current registry;
the qualification-time records and their immutable evidence remain unchanged.
The 0.37.2 host refresh registers a successor QUALIFICATION_ONLY identity only.

Contracts were derived through read-only AST inspection at the pinned revision.
The existing graph-relevant projection retains profile-used loader/sampler enums,
external filename enumerations, and defaults. Numeric ranges, hidden inputs,
RETURN_NAMES and presentation options have no fields in the frozen record;
their source remains bound by file and symbol hashes (review in docs/TESTING.md).
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from .node_contracts import (
    HostNodeContractRecord,
    NodeInputEvidence,
    SemanticEvidenceRecord,
    create_host_node_contract_snapshot,
    create_node_contract_record,
)
from .profiles import (
    CANONICAL_COMFYUI_0280_INVENTORY,
    COMFYUI_0280_SUPPORTED_PROFILE,
    CompatibilityProfile,
    ProfileSupportStatus,
)


COMFYUI_0345_REVISION = "7fd919f0caff66a52289ea5b19cb6eaca0da04ef"
COMFYUI_0345_PROFILE_IDENTIFIER = "comfyui-0.34.5.prediction-mixing.v1"
COMFYUI_0345_INVENTORY_IDENTIFIER = "krea2-turbo-bf16-1024-comfyui-0.34.5.v1"
COMFYUI_0345_NODE_CONTRACT_IDENTIFIER = "comfyui-core-0.34.5.prediction-mixing.v1"
COMFYUI_0345_SNAPSHOT_IDENTIFIER = "comfyui-0.34.5.7fd919f.prediction-mixing.static.v1"


_SOURCE_FILE_HASHES = MappingProxyType({
    "comfyui_version.py": "8e22713d88b4af95d23730c41e5ad5691b7cc1bc810815516ed3917e624fb327",
    "nodes.py": "918a322c43665f24513856a5bec6c564ede01a29b6081b83fd67d27a49571e0c",
    "node_helpers.py": "22317a033cce556331bfedc5f4ab6c2833184fd2bbdf9496c9182a4973a7098a",
    "comfy/samplers.py": "a768a33b296c08055925f176e60e004a6f33fa95ecee3df6dd5583dccbc87a88",
    "comfy/comfy_types/__init__.py": "da3601f9bf71f36070985bd835df311a06e1c40dbcc86afd13e63cd84ed3054b",
    "comfy/comfy_types/node_typing.py": "6bc7906a84333a767e137e89efea041b45966cd589f344a28c14116a2484a7f5",
})

_SYMBOL_FINGERPRINTS = MappingProxyType({
    ("nodes.py", "UNETLoader"): "5e09c76474a2a25f2d56a03365ea1e9eee98aa33a137fd36804e7e76e168ac58",
    ("nodes.py", "CLIPLoader"): "0375980abfc970fda950bb836c81e452fc9fa0664afd22814abd8c449e459310",
    ("nodes.py", "CLIPTextEncode"): "e82e7e7c78e9899746da4daf9740f6a5c4436759db390e0c0bdeca2599deb8dc",
    ("nodes.py", "LoadImageMask"): "1d76eb3d621b5a2e607821584b50bbc3c773d43b8a700528e0952017696eb4f6",
    ("nodes.py", "ConditioningSetMask"): "ae9414e3d0340aa6b8faaec159f363a66ab512d8c9015f306c206b931a775752",
    ("nodes.py", "ConditioningCombine"): "1ca44cdf2575d38da30563036f68144b4849b77825f680e2a0a00b2079fb3b70",
    ("nodes.py", "EmptyLatentImage"): "b43edd8ed00aaa911a16ee8dccef740c58a7c08d2601b1ef796fa505fd683dbc",
    ("nodes.py", "KSampler"): "511d924097d6409e91112380edf38a2665d8780910254e7074ed3706dc4b0358",
    ("nodes.py", "VAELoader"): "0bab14cdf849dfe576db14d61651684d4accfc24b00ce57a3d2301519d60b54f",
    ("nodes.py", "VAEDecode"): "415fc89ff153646c5144cbccb93049ac7a052de28438c49e99259ec75920d383",
    ("nodes.py", "SaveImage"): "03032738051814439b9368eef80264e0dc3c770c04ed32e4870f426df3171104",
    ("nodes.py", "LoadImage"): "2e09ef839246ba43c67efdb3ba627b90b7e6efb2071def830021313f4fc377bf",
    ("node_helpers.py", "conditioning_set_values"): "2d762134c40dc2bd7de9f454661e4dfe3575294aa3dd744592a1715aa626d204",
    ("comfy/samplers.py", "get_area_and_mult"): "519a97cd458a47aef4f6856e9d9ca3c95ccf831c7896b04f30fe2b937cb3f1a7",
    ("comfy/samplers.py", "_calc_cond_batch"): "c11a2665d97abaa13fbcbe47d0fedfeb720625be03bc1d1e36dcda3b81c7132f",
    ("comfy/samplers.py", "resolve_areas_and_cond_masks_multidim"): "a388b765dd0895be4d6e7c2ac26c475df5b4af85808f6609926a7eca9bf68066",
    ("comfy/samplers.py", "sampling_function"): "b2548ba220b52d155531817c39f87514dfe3d209ba4ae281da23538feef33884",
    ("comfy/samplers.py", "cfg_function"): "e4f583585ace25e0f153ff5d1586dcf88dcf83361f0900f4252f30da5fb12813",
    ("comfy/samplers.py", "KSampler"): "82c69d53bae2e1fab2d3a1a2869f0e13b8824b3a296a90073313fa24ec2f133a",
    ("comfy/samplers.py", "CFGGuider"): "5bd8412d5e51a1695e1020cb0287acd6e1b75fb25fa7bce5a95f3adc40cc8f05",
    ("comfy/comfy_types/node_typing.py", "StrEnum"): "dea4131bc8036e1b94ea6179035b466ef51ab6b95ba00da3699fd66880b78204",
    ("comfy/comfy_types/node_typing.py", "IO"): "aa1c8a78e361806ec5495581a7b5cc95a019b1e88e72d4486fbf87ca87bc6219",
})


def _node(
    class_name: str,
    *,
    required: tuple[str, ...],
    host_required: tuple[str, ...],
    host_optional: tuple[str, ...],
    inputs: tuple[NodeInputEvidence, ...],
    returns: tuple[str, ...],
    outputs_used: tuple[int, ...],
    function: str,
) -> HostNodeContractRecord:
    return create_node_contract_record(
        class_name=class_name,
        required_inputs=required,
        output_indices=outputs_used,
        host_required_inputs=host_required,
        host_optional_inputs=host_optional,
        input_evidence=inputs,
        return_types=returns,
        function_name=function,
        source_file="nodes.py",
        source_symbol=class_name,
        source_file_sha256=_SOURCE_FILE_HASHES["nodes.py"],
        source_symbol_fingerprint=_SYMBOL_FINGERPRINTS[("nodes.py", class_name)],
    )


COMFYUI_0345_NODE_CONTRACTS = MappingProxyType({
    "UNETLoader": _node(
        "UNETLoader",
        required=('unet_name', 'weight_dtype'),
        host_required=('unet_name', 'weight_dtype'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('unet_name', 'required', 'STRING', external_enumeration='diffusion_models'),
            NodeInputEvidence('weight_dtype', 'required', 'STRING', enum_values=('default', 'fp8_e4m3fn', 'fp8_e4m3fn_fast', 'fp8_e5m2'), default_value='default'),
        ),
        returns=('MODEL',),
        outputs_used=(0,),
        function='load_unet',
    ),
    "CLIPLoader": _node(
        "CLIPLoader",
        required=('clip_name', 'device', 'type'),
        host_required=('clip_name', 'type'),
        host_optional=('device',),
        inputs=(
            NodeInputEvidence('clip_name', 'required', 'STRING', external_enumeration='text_encoders'),
            NodeInputEvidence('type', 'required', 'STRING', enum_values=('krea2',)),
            NodeInputEvidence('device', 'optional', 'STRING', enum_values=('default', 'cpu'), default_value='default'),
        ),
        returns=('CLIP',),
        outputs_used=(0,),
        function='load_clip',
    ),
    "CLIPTextEncode": _node(
        "CLIPTextEncode",
        required=('clip', 'text'),
        host_required=('text', 'clip'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('text', 'required', 'STRING'),
            NodeInputEvidence('clip', 'required', 'CLIP'),
        ),
        returns=('CONDITIONING',),
        outputs_used=(0,),
        function='encode',
    ),
    "LoadImageMask": _node(
        "LoadImageMask",
        required=('channel', 'image'),
        host_required=('image', 'channel'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('image', 'required', 'STRING', external_enumeration='input_images'),
            NodeInputEvidence('channel', 'required', 'STRING', enum_values=('alpha', 'red', 'green', 'blue'), default_value='alpha'),
        ),
        returns=('MASK',),
        outputs_used=(0,),
        function='load_image_mask',
    ),
    "ConditioningSetMask": _node(
        "ConditioningSetMask",
        required=('conditioning', 'mask', 'set_cond_area', 'strength'),
        host_required=('conditioning', 'mask', 'strength', 'set_cond_area'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('conditioning', 'required', 'CONDITIONING'),
            NodeInputEvidence('mask', 'required', 'MASK'),
            NodeInputEvidence('strength', 'required', 'FLOAT', default_value=1.0),
            NodeInputEvidence('set_cond_area', 'required', 'STRING', enum_values=('default', 'mask bounds'), default_value='default'),
        ),
        returns=('CONDITIONING',),
        outputs_used=(0,),
        function='append',
    ),
    "ConditioningCombine": _node(
        "ConditioningCombine",
        required=('conditioning_1', 'conditioning_2'),
        host_required=('conditioning_1', 'conditioning_2'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('conditioning_1', 'required', 'CONDITIONING'),
            NodeInputEvidence('conditioning_2', 'required', 'CONDITIONING'),
        ),
        returns=('CONDITIONING',),
        outputs_used=(0,),
        function='combine',
    ),
    "EmptyLatentImage": _node(
        "EmptyLatentImage",
        required=('batch_size', 'height', 'width'),
        host_required=('width', 'height', 'batch_size'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('width', 'required', 'INT', default_value=512),
            NodeInputEvidence('height', 'required', 'INT', default_value=512),
            NodeInputEvidence('batch_size', 'required', 'INT', default_value=1),
        ),
        returns=('LATENT',),
        outputs_used=(0,),
        function='generate',
    ),
    "KSampler": _node(
        "KSampler",
        required=('cfg', 'denoise', 'latent_image', 'model', 'negative', 'positive', 'sampler_name', 'scheduler', 'seed', 'steps'),
        host_required=('model', 'seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'positive', 'negative', 'latent_image', 'denoise'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('model', 'required', 'MODEL'),
            NodeInputEvidence('seed', 'required', 'INT', default_value=0),
            NodeInputEvidence('steps', 'required', 'INT', default_value=20),
            NodeInputEvidence('cfg', 'required', 'FLOAT', default_value=8.0),
            NodeInputEvidence('sampler_name', 'required', 'STRING', enum_values=('euler',), external_enumeration='comfy.samplers.SAMPLER_NAMES'),
            NodeInputEvidence('scheduler', 'required', 'STRING', enum_values=('simple',), external_enumeration='comfy.samplers.SCHEDULER_NAMES'),
            NodeInputEvidence('positive', 'required', 'CONDITIONING'),
            NodeInputEvidence('negative', 'required', 'CONDITIONING'),
            NodeInputEvidence('latent_image', 'required', 'LATENT'),
            NodeInputEvidence('denoise', 'required', 'FLOAT', default_value=1.0),
        ),
        returns=('LATENT',),
        outputs_used=(0,),
        function='sample',
    ),
    "VAELoader": _node(
        "VAELoader",
        required=('vae_name',),
        host_required=('vae_name',),
        host_optional=(),
        inputs=(
            NodeInputEvidence('vae_name', 'required', 'STRING', external_enumeration='vae'),
        ),
        returns=('VAE',),
        outputs_used=(0,),
        function='load_vae',
    ),
    "VAEDecode": _node(
        "VAEDecode",
        required=('samples', 'vae'),
        host_required=('samples', 'vae'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('samples', 'required', 'LATENT'),
            NodeInputEvidence('vae', 'required', 'VAE'),
        ),
        returns=('IMAGE',),
        outputs_used=(0,),
        function='decode',
    ),
    "SaveImage": _node(
        "SaveImage",
        required=('filename_prefix', 'images'),
        host_required=('images', 'filename_prefix'),
        host_optional=(),
        inputs=(
            NodeInputEvidence('images', 'required', 'IMAGE'),
            NodeInputEvidence('filename_prefix', 'required', 'STRING', default_value='ComfyUI'),
        ),
        returns=('IMAGE',),
        outputs_used=(),
        function='save_images',
    ),
})


def _semantic(
    identifier: str,
    source_file: str,
    symbols: tuple[str, ...],
    notes: str,
) -> SemanticEvidenceRecord:
    return SemanticEvidenceRecord(
        evidence_identifier=identifier,
        source_file=source_file,
        source_symbols=symbols,
        source_file_sha256=_SOURCE_FILE_HASHES[source_file],
        symbol_fingerprints=tuple(
            _SYMBOL_FINGERPRINTS[(source_file, symbol)] for symbol in symbols
        ),
        conclusion="confirmed",
        notes=notes,
    )


COMFYUI_0345_SEMANTIC_EVIDENCE = (
    _semantic(
        "prediction_mixing.conditioning_set_mask",
        "nodes.py",
        ("ConditioningSetMask",),
        "append adds a batch dimension only when needed, retains the mask, and "
        "passes Strength as mask_strength to conditioning_set_values. The "
        "selected default area sets set_area_to_bounds to False; it does not "
        "threshold the mask or request a bounding-box area.",
    ),
    _semantic(
        "prediction_mixing.conditioning_combine",
        "nodes.py",
        ("ConditioningCombine",),
        "combine returns the ordered list concatenation conditioning_1 + "
        "conditioning_2 in one CONDITIONING output. It neither merges metadata "
        "nor averages embeddings, preserving the emitted left-fold entries.",
    ),
    _semantic(
        "prediction_mixing.conditioning_metadata_copy",
        "node_helpers.py",
        ("conditioning_set_values",),
        "Each result entry retains t[0] and receives t[1].copy() before values "
        "are assigned. ConditioningSetMask uses the default append=False, so "
        "mask fields replace keys on the copied dictionary without changing "
        "the original metadata; this is a shallow copy, not a tensor copy.",
    ),
    _semantic(
        "prediction_mixing.regional_accumulation",
        "comfy/samplers.py",
        (
            "get_area_and_mult",
            "_calc_cond_batch",
            "resolve_areas_and_cond_masks_multidim",
        ),
        "Mask preparation resizes the field to latent dimensions and creates "
        "a bounds area only when set_area_to_bounds is requested. For the "
        "ordinary graph's default area, get_area_and_mult retains area=None "
        "and multiplies mask by mask_strength and conditioning strength. "
        "The default _calc_cond_batch path sums prediction * multiplier over "
        "the full latent, then divides by multiplier counts initialized at "
        "1e-37. This confirms weighted normalization, not perceptually linear "
        "Strength or product overlap support; multigpu/custom hooks are outside "
        "this ordinary-path conclusion.",
    ),
    _semantic(
        "prediction_mixing.cfg1_empty_negative",
        "comfy/samplers.py",
        ("sampling_function", "cfg_function", "KSampler", "CFGGuider"),
        "KSampler aliases the source sampler/scheduler lists containing euler "
        "and simple. CFGGuider.predict_noise dispatches to sampling_function. "
        "With CFG 1.0 and the default disable_cfg1_optimization=False, that "
        "function passes None for the unconditioned branch; default batching "
        "leaves its prediction zero and cfg_function yields the conditional "
        "prediction. The graph still supplies an empty negative encoding. "
        "Custom CFG/batch callbacks and pre/post CFG hooks are outside this "
        "default-path conclusion.",
    ),
    _semantic(
        "prediction_mixing.static_input_type_tokens",
        "comfy/comfy_types/node_typing.py",
        ("StrEnum", "IO"),
        "nodes.py imports IO through comfy/comfy_types/__init__.py, whose "
        "re-export is separately file-hash-bound. IO inherits the local "
        "str/Enum base: STRING, CLIP and CONDITIONING have exactly those "
        "string values. CLIPTextEncode's IO-valued declarations therefore "
        "project to the existing graph type tokens without substituting types.",
    ),
    _semantic(
        "prediction_mixing.inherited_mask_input",
        "nodes.py",
        ("LoadImage", "LoadImageMask"),
        "LoadImageMask inherits LoadImage and merges its required image input "
        "with channel. LoadImage.INPUT_TYPES supplies the sorted external "
        "input-image enumeration; LoadImageMask declares alpha/red/green/blue. "
        "The selected red branch clones channel zero of the inherited image "
        "tensor. The record therefore retains required image/channel, the "
        "input_images external enumeration and MASK output zero; this static "
        "trace makes no decoded-image or live generation claim.",
    ),
)


COMFYUI_0345_NODE_SNAPSHOT = create_host_node_contract_snapshot(
    snapshot_identifier=COMFYUI_0345_SNAPSHOT_IDENTIFIER,
    profile_identifier=COMFYUI_0345_PROFILE_IDENTIFIER,
    comfyui_version="0.34.5",
    comfyui_revision=COMFYUI_0345_REVISION,
    contracts=COMFYUI_0345_NODE_CONTRACTS,
    source_reference="static-evidence/comfyui-0.34.5-7fd919f",
    semantic_evidence=COMFYUI_0345_SEMANTIC_EVIDENCE,
    source_file_hashes=_SOURCE_FILE_HASHES,
    limitations=(
        "Static evidence covers only ordinary one- and two-layer Prediction Mixing graphs.",
        "Model filenames remain external inventory values; no installed components were inspected.",
        "No runtime import, live introspection, submission, decoded-image or visual behavior claim is included.",
        "Independent evidence acceptance and commit are required before later qualification use.",
        "Static compatibility does not establish generation compatibility or product support.",
    ),
    evidence_timestamp="2026-09-07",
)


# The snapshot schema binds profile/version/revision; the inventory owns the
# matching inventory and node-contract identifiers. No new snapshot fields.
COMFYUI_0345_QUALIFICATION_INVENTORY = replace(
    CANONICAL_COMFYUI_0280_INVENTORY,
    inventory_identifier=COMFYUI_0345_INVENTORY_IDENTIFIER,
    comfyui_profile_identifier=COMFYUI_0345_PROFILE_IDENTIFIER,
    expected_comfyui_version="0.34.5",
    expected_comfyui_revision=COMFYUI_0345_REVISION,
    node_contract_identifier=COMFYUI_0345_NODE_CONTRACT_IDENTIFIER,
)


COMFYUI_0345_QUALIFICATION_PROFILE = CompatibilityProfile(
    inventory=COMFYUI_0345_QUALIFICATION_INVENTORY,
    node_snapshot=COMFYUI_0345_NODE_SNAPSHOT,
    status=ProfileSupportStatus.QUALIFICATION_ONLY,
)

# C1 static refresh: independently re-read all six 0.34.6 source files and
# recomputed all 22 AST symbols. The five implementation files are byte-exact
# matches to 0.34.5; only the version file differs. Reuse those immutable records
# explicitly, retaining the historical snapshot and all its identities.
# See docs/C1_COMFYUI_0346_STATIC_REFRESH.md. No runtime evidence capture.
COMFYUI_0346_REVISION = "8fed37813848259fbdd2548ae3cd9f14df7fd68b"
COMFYUI_0346_PROFILE_IDENTIFIER = "comfyui-0.34.6.prediction-mixing.v1"
COMFYUI_0346_INVENTORY_IDENTIFIER = "krea2-turbo-bf16-1024-comfyui-0.34.6.v1"
COMFYUI_0346_NODE_CONTRACT_IDENTIFIER = "comfyui-core-0.34.6.prediction-mixing.v1"
COMFYUI_0346_SNAPSHOT_IDENTIFIER = "comfyui-0.34.6.8fed378.prediction-mixing.static.v1"

COMFYUI_0346_NODE_CONTRACTS = COMFYUI_0345_NODE_CONTRACTS
COMFYUI_0346_SEMANTIC_EVIDENCE = COMFYUI_0345_SEMANTIC_EVIDENCE
COMFYUI_0346_NODE_SNAPSHOT = create_host_node_contract_snapshot(
    snapshot_identifier=COMFYUI_0346_SNAPSHOT_IDENTIFIER,
    profile_identifier=COMFYUI_0346_PROFILE_IDENTIFIER,
    comfyui_version="0.34.6",
    comfyui_revision=COMFYUI_0346_REVISION,
    contracts=COMFYUI_0346_NODE_CONTRACTS,
    source_reference="static-evidence/comfyui-0.34.6-8fed378",
    semantic_evidence=COMFYUI_0346_SEMANTIC_EVIDENCE,
    source_file_hashes={
        **_SOURCE_FILE_HASHES,
        "comfyui_version.py": "8db74223298f12a7ae972f2a95d1150dce37ce8f6d3a6522c192c7f1b685f19f",
    },
    limitations=COMFYUI_0345_NODE_SNAPSHOT.limitations,
    evidence_timestamp="2026-09-07",
)
COMFYUI_0346_QUALIFICATION_INVENTORY = replace(
    CANONICAL_COMFYUI_0280_INVENTORY,
    inventory_identifier=COMFYUI_0346_INVENTORY_IDENTIFIER,
    comfyui_profile_identifier=COMFYUI_0346_PROFILE_IDENTIFIER,
    expected_comfyui_version="0.34.6",
    expected_comfyui_revision=COMFYUI_0346_REVISION,
    node_contract_identifier=COMFYUI_0346_NODE_CONTRACT_IDENTIFIER,
)
COMFYUI_0346_QUALIFICATION_PROFILE = CompatibilityProfile(
    inventory=COMFYUI_0346_QUALIFICATION_INVENTORY,
    node_snapshot=COMFYUI_0346_NODE_SNAPSHOT,
    status=ProfileSupportStatus.QUALIFICATION_ONLY,
)

# C1-S1 is the explicit support-policy decision following retained C1-H1.
# Keep the qualification-time record above truthful for historical callers.
# Only the lifecycle wrapper changes; evidence objects and identities are shared.
COMFYUI_0346_SUPPORTED_PROFILE = replace(
    COMFYUI_0346_QUALIFICATION_PROFILE, status=ProfileSupportStatus.SUPPORTED
)
COMFYUI_0280_HISTORICAL_PROFILE = replace(
    COMFYUI_0280_SUPPORTED_PROFILE, status=ProfileSupportStatus.QUALIFICATION_ONLY
)

# One fixed product default, never selected from host observations or "latest".
DEFAULT_SUPPORTED_PROFILE = COMFYUI_0346_SUPPORTED_PROFILE

# 0.37.2 host refresh: the Desktop launcher moved the pinned checkout to 830232b.
# All six files were re-read and all 22 AST symbols recomputed after the method
# reproduced every retained 0.34.6 value. node_helpers.py and comfy_types are
# byte-exact; 20 symbols are unchanged. CLIPLoader only appends "yue2" (the
# recorded "krea2" member remains) and EmptyLatentImage width/height defaults
# move 512 -> 1024. comfy/samplers.py only inserts a KSAMPLER_NAMES entry outside
# every recorded symbol. Only these measured deltas are rebound; other contract
# fields and all semantic conclusions are the retained records. Registration is
# QUALIFICATION_ONLY. The retained N=3 bindings still pin 0.34.6; this host's
# separate additive N=3 bindings belong to their realization owners (ADR-0024).
# See docs/COMFYUI_0_37_2_HOST_SUPPORT_REFRESH.md. No runtime evidence capture.
COMFYUI_0372_REVISION = "830232b856045ca2892833212d7771078a13edd5"
COMFYUI_0372_PROFILE_IDENTIFIER = "comfyui-0.37.2.prediction-mixing.v1"
COMFYUI_0372_INVENTORY_IDENTIFIER = "krea2-turbo-bf16-1024-comfyui-0.37.2.v1"
COMFYUI_0372_NODE_CONTRACT_IDENTIFIER = "comfyui-core-0.37.2.prediction-mixing.v1"
COMFYUI_0372_SNAPSHOT_IDENTIFIER = "comfyui-0.37.2.830232b.prediction-mixing.static.v1"

_0372_SOURCE_FILE_HASHES = MappingProxyType({
    **_SOURCE_FILE_HASHES,
    "comfyui_version.py": "f30805f9d1724c45b347962272479c5d3f2d4c4f016acc512bb1206001f478ae",
    "nodes.py": "1af4a41e1d844550a836cf1d1b00fad85d3d0aefaf435743431a8f1598643e22",
    "comfy/samplers.py": "f2c264ca9d394612f828e3ffe167c856a278a10e1711b269f0ba65dccb66393f",
})
_0372_CHANGED_NODE_SYMBOLS = MappingProxyType({
    "CLIPLoader": "0b7e6013e2b87ee0ae357ec0830621977f3ecfe489bc9a6d0433ed1f9b06bddc",
    "EmptyLatentImage": "1111d801b056164fa56066dfc3bfacec9f3686ea3e373664bb357bbf65cf2cb7",
})
# Every project graph sets width/height explicitly; the host default is evidence only.
_0372_CHANGED_INPUTS = MappingProxyType({
    "EmptyLatentImage": (
        NodeInputEvidence('width', 'required', 'INT', default_value=1024),
        NodeInputEvidence('height', 'required', 'INT', default_value=1024),
        NodeInputEvidence('batch_size', 'required', 'INT', default_value=1),
    ),
})


def _rebind_0372(record: HostNodeContractRecord) -> HostNodeContractRecord:
    return create_node_contract_record(
        class_name=record.class_name,
        required_inputs=record.required_inputs,
        output_indices=record.output_indices,
        host_required_inputs=record.host_required_inputs,
        host_optional_inputs=record.host_optional_inputs,
        input_evidence=_0372_CHANGED_INPUTS.get(record.class_name, record.input_evidence),
        return_types=record.return_types,
        function_name=record.function_name,
        source_file=record.source_file,
        source_symbol=record.source_symbol,
        source_file_sha256=_0372_SOURCE_FILE_HASHES[record.source_file],
        source_symbol_fingerprint=_0372_CHANGED_NODE_SYMBOLS.get(
            record.class_name, record.source_symbol_fingerprint
        ),
    )


COMFYUI_0372_NODE_CONTRACTS = MappingProxyType({
    name: _rebind_0372(record) for name, record in COMFYUI_0346_NODE_CONTRACTS.items()
})
# All semantic symbols are unchanged; only their bound file hashes move.
COMFYUI_0372_SEMANTIC_EVIDENCE = tuple(
    replace(item, source_file_sha256=_0372_SOURCE_FILE_HASHES[item.source_file])
    for item in COMFYUI_0346_SEMANTIC_EVIDENCE
)
COMFYUI_0372_NODE_SNAPSHOT = create_host_node_contract_snapshot(
    snapshot_identifier=COMFYUI_0372_SNAPSHOT_IDENTIFIER,
    profile_identifier=COMFYUI_0372_PROFILE_IDENTIFIER,
    comfyui_version="0.37.2",
    comfyui_revision=COMFYUI_0372_REVISION,
    contracts=COMFYUI_0372_NODE_CONTRACTS,
    source_reference="static-evidence/comfyui-0.37.2-830232b",
    semantic_evidence=COMFYUI_0372_SEMANTIC_EVIDENCE,
    source_file_hashes=_0372_SOURCE_FILE_HASHES,
    limitations=COMFYUI_0345_NODE_SNAPSHOT.limitations,
    evidence_timestamp="2026-09-25",
)
COMFYUI_0372_QUALIFICATION_INVENTORY = replace(
    CANONICAL_COMFYUI_0280_INVENTORY,
    inventory_identifier=COMFYUI_0372_INVENTORY_IDENTIFIER,
    comfyui_profile_identifier=COMFYUI_0372_PROFILE_IDENTIFIER,
    expected_comfyui_version="0.37.2",
    expected_comfyui_revision=COMFYUI_0372_REVISION,
    node_contract_identifier=COMFYUI_0372_NODE_CONTRACT_IDENTIFIER,
)
COMFYUI_0372_QUALIFICATION_PROFILE = CompatibilityProfile(
    inventory=COMFYUI_0372_QUALIFICATION_INVENTORY,
    node_snapshot=COMFYUI_0372_NODE_SNAPSHOT,
    status=ProfileSupportStatus.QUALIFICATION_ONLY,
)

# Exact 0.37.4 static evidence from the separate 2026-09-27 compatibility capture.
# All node/semantic source bytes and observations equal 0.37.2; only the version
# source changed. Keep a distinct snapshot and exact provenance, never a version
# alias or runtime refresh. See COMFYUI_0_37_4_QUALIFICATION_REGISTRATION.md.
COMFYUI_0374_REVISION = "8ff6dc384ba5c410266b40e137799e049459d4f2"
COMFYUI_0374_PROFILE_IDENTIFIER = "comfyui-0.37.4.prediction-mixing.v1"
COMFYUI_0374_INVENTORY_IDENTIFIER = "krea2-turbo-bf16-1024-comfyui-0.37.4.v1"
COMFYUI_0374_NODE_CONTRACT_IDENTIFIER = "comfyui-core-0.37.4.prediction-mixing.v1"
COMFYUI_0374_SNAPSHOT_IDENTIFIER = "comfyui-0.37.4.8ff6dc3.prediction-mixing.static.v1"
_0374_SOURCE_FILE_HASHES = MappingProxyType({
    **_0372_SOURCE_FILE_HASHES,
    "comfyui_version.py": "0e872e4ae3d66fbde4ab70d63457c50484fb9dfb3fc32125981ba07a4949e65b",
})
COMFYUI_0374_NODE_CONTRACTS = MappingProxyType(dict(COMFYUI_0372_NODE_CONTRACTS))
COMFYUI_0374_SEMANTIC_EVIDENCE = COMFYUI_0372_SEMANTIC_EVIDENCE
COMFYUI_0374_NODE_SNAPSHOT = create_host_node_contract_snapshot(
    snapshot_identifier=COMFYUI_0374_SNAPSHOT_IDENTIFIER,
    profile_identifier=COMFYUI_0374_PROFILE_IDENTIFIER,
    comfyui_version="0.37.4",
    comfyui_revision=COMFYUI_0374_REVISION,
    contracts=COMFYUI_0374_NODE_CONTRACTS,
    source_reference="static-evidence/comfyui-0.37.4-8ff6dc3",
    semantic_evidence=COMFYUI_0374_SEMANTIC_EVIDENCE,
    source_file_hashes=_0374_SOURCE_FILE_HASHES,
    limitations=COMFYUI_0372_NODE_SNAPSHOT.limitations,
    evidence_timestamp="2026-09-27",
)
COMFYUI_0374_QUALIFICATION_INVENTORY = replace(
    COMFYUI_0372_QUALIFICATION_INVENTORY,
    inventory_identifier=COMFYUI_0374_INVENTORY_IDENTIFIER,
    comfyui_profile_identifier=COMFYUI_0374_PROFILE_IDENTIFIER,
    expected_comfyui_version="0.37.4",
    expected_comfyui_revision=COMFYUI_0374_REVISION,
    node_contract_identifier=COMFYUI_0374_NODE_CONTRACT_IDENTIFIER,
)
COMFYUI_0374_QUALIFICATION_PROFILE = CompatibilityProfile(
    inventory=COMFYUI_0374_QUALIFICATION_INVENTORY,
    node_snapshot=COMFYUI_0374_NODE_SNAPSHOT,
    status=ProfileSupportStatus.QUALIFICATION_ONLY,
)

# Explicit immutable assembly after complete evidence records exist.
# Historical 0.27.1 remains inventory-only in profiles.py; no snapshot is borrowed.
REGISTERED_COMFYUI_PROFILES = MappingProxyType({
    COMFYUI_0280_SUPPORTED_PROFILE.inventory.comfyui_profile_identifier:
        COMFYUI_0280_HISTORICAL_PROFILE,
    COMFYUI_0345_PROFILE_IDENTIFIER: COMFYUI_0345_QUALIFICATION_PROFILE,
    COMFYUI_0346_PROFILE_IDENTIFIER: COMFYUI_0346_SUPPORTED_PROFILE,
    COMFYUI_0372_PROFILE_IDENTIFIER: COMFYUI_0372_QUALIFICATION_PROFILE,
    COMFYUI_0374_PROFILE_IDENTIFIER: COMFYUI_0374_QUALIFICATION_PROFILE,
})
