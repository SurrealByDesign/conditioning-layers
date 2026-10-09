"""The graph-v3 owner permits retained built-ins plus one governed component.

This explicitly resolves ADR0026-R2C-R3-2 without changing the retained eleven
class inventory or its validator. It is not a general component registry.
Each exact-3 binding and class authority pins one exact registered host; host
selection is exact and never falls back to another host's authority.
"""

from dataclasses import replace

from conditioning_layers.adapters.prediction_mixing.blend import BLEND_EXECUTION_PROFILE
from conditioning_layers.adapters.prediction_mixing.v2.identity import exact_contract_equal
from conditioning_layers.adapters.prediction_mixing.v2.topology import ORDERED_LEFT_FOLD_TOPOLOGY_POLICY
from conditioning_layers.capabilities.blend import EXACT_THREE_BLEND_ELIGIBILITY
from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0346_SUPPORTED_PROFILE, COMFYUI_0372_QUALIFICATION_PROFILE,
    COMFYUI_0374_QUALIFICATION_PROFILE,
)
from conditioning_layers.comfyui.prediction_mixing.blend_component import (
    BLEND_NODE_CLASS, blend_component_identity, validate_blend_component_identity,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.authority import (
    claims_host, registered_host_evidence,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import (
    canonical_bytes, fingerprint, json_value,
)
from conditioning_layers.comfyui.prediction_mixing.node_contracts import fingerprint_host_node_contract_snapshot
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .models import (
    GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION, GENERATOR_VERSION_IDENTIFIER,
    BlendGraphPermittedClassAuthority, BlendRealizationBinding,
)


INVENTORY = COMFYUI_0346_SUPPORTED_PROFILE.inventory
SNAPSHOT = COMFYUI_0346_SUPPORTED_PROFILE.node_snapshot
COMPONENT_IDENTITY = blend_component_identity()


def fingerprint_authority(value):
    material = json_value(value)
    material.pop("fingerprint")
    return fingerprint(material)


_CLASSES = BlendGraphPermittedClassAuthority(
    identifier="prediction-mixing.normalized-blend.graph-permitted-classes.v1",
    graph_identifier=GRAPH_FORMAT_IDENTIFIER, graph_version=GRAPH_FORMAT_VERSION,
    retained_inventory_identifier=INVENTORY.inventory_identifier,
    retained_inventory_fingerprint=fingerprint(INVENTORY),
    required_builtin_classes=INVENTORY.required_node_class_names,
    project_component_class=BLEND_NODE_CLASS,
    project_component_contract_fingerprint=COMPONENT_IDENTITY.contract_fingerprint,
    fingerprint="",
)
BLEND_GRAPH_PERMITTED_CLASSES = replace(_CLASSES, fingerprint=fingerprint_authority(_CLASSES))
_REVIEWED_CLASSES = BLEND_GRAPH_PERMITTED_CLASSES


_BINDING = BlendRealizationBinding(
    identifier="prediction-mixing.multi-layer.realization.exact-3.normalized-blend.comfyui-0.34.6.v1",
    contract_identifier=EXACT_THREE_BLEND_ELIGIBILITY.contract_identifier,
    contract_version=EXACT_THREE_BLEND_ELIGIBILITY.contract_version,
    eligibility_entry_identifier=EXACT_THREE_BLEND_ELIGIBILITY.identifier,
    eligibility_entry_fingerprint=EXACT_THREE_BLEND_ELIGIBILITY.fingerprint,
    exact_cardinality=3,
    execution_profile_identifier=BLEND_EXECUTION_PROFILE.profile_identifier,
    execution_profile_fingerprint=BLEND_EXECUTION_PROFILE.fingerprint,
    topology_policy_identifier=ORDERED_LEFT_FOLD_TOPOLOGY_POLICY.policy_identifier,
    topology_policy_fingerprint=ORDERED_LEFT_FOLD_TOPOLOGY_POLICY.fingerprint,
    graph_identifier=GRAPH_FORMAT_IDENTIFIER, graph_version=GRAPH_FORMAT_VERSION,
    generator_identifier=GENERATOR_VERSION_IDENTIFIER,
    inventory_identifier=INVENTORY.inventory_identifier, inventory_fingerprint=fingerprint(INVENTORY),
    snapshot_identifier=SNAPSHOT.snapshot_identifier, snapshot_fingerprint=SNAPSHOT.snapshot_fingerprint,
    comfyui_profile_identifier=INVENTORY.comfyui_profile_identifier,
    comfyui_revision=INVENTORY.expected_comfyui_revision,
    node_allocation="4N + 8; exact N=3; dense IDs; preparation after folds before latent/sampler",
    host_link_allocation="5N + 7; exact N=3",
    project_component_identity=COMPONENT_IDENTITY,
    permitted_class_authority_identifier=BLEND_GRAPH_PERMITTED_CLASSES.identifier,
    permitted_class_authority_fingerprint=BLEND_GRAPH_PERMITTED_CLASSES.fingerprint,
    project_component_availability_required=True,
    realization_semantics=(
        "ordered-left-fold; conditioning_1=left; conditioning_2=right; no priority",
        "LoadImageMask red; ConditioningSetMask default; authored binary64 Strength; no pruning",
        "exact recovered 8-bit sample code and exact dyadic Strength; support before product",
        "exact rational normalization; one binary32 round-to-nearest ties-to-even; zero branch without division",
        "deterministic CPU preparation; batch=1; 128x128; prepared binary32 masks; mask_strength=1.0",
        "no area strength; no resize; no hooks, wrappers, transformations or schedules",
        "retained binary32 KSampler accumulator; reject fp16-intermediates; no dtype-changing transfer",
        "route-specific source/implementation/node-contract/availability verification before submission",
        "one sampler/decode/SaveImage; Base repeated with two newlines; no Base denominator term",
        "Euler/Simple; steps=8; cfg=1.0; denoise=1.0; batch=1; not live-qualified; not product-admitted",
    ),
    fingerprint="",
)
EXACT_THREE_BLEND_REALIZATION = replace(_BINDING, fingerprint=fingerprint_authority(_BINDING))
_REVIEWED_BINDING = EXACT_THREE_BLEND_REALIZATION

# ComfyUI 0.37.2 (docs/COMFYUI_0_37_2_HOST_SUPPORT_REFRESH.md): the retained
# declarations with only identifiers and exact host pins rebound to that
# registered QUALIFICATION_ONLY evidence. Component, algorithm, eligibility,
# graph and realization semantics are the retained exact-3 values.
_INVENTORY_0372 = COMFYUI_0372_QUALIFICATION_PROFILE.inventory
_SNAPSHOT_0372 = COMFYUI_0372_QUALIFICATION_PROFILE.node_snapshot
_CLASSES_0372 = replace(
    BLEND_GRAPH_PERMITTED_CLASSES,
    identifier="prediction-mixing.normalized-blend.graph-permitted-classes.comfyui-0.37.2.v1",
    retained_inventory_identifier=_INVENTORY_0372.inventory_identifier,
    retained_inventory_fingerprint=fingerprint(_INVENTORY_0372),
    required_builtin_classes=_INVENTORY_0372.required_node_class_names,
    fingerprint="",
)
BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372 = replace(
    _CLASSES_0372, fingerprint=fingerprint_authority(_CLASSES_0372))
_BINDING_0372 = replace(
    EXACT_THREE_BLEND_REALIZATION,
    identifier="prediction-mixing.multi-layer.realization.exact-3.normalized-blend.comfyui-0.37.2.v1",
    inventory_identifier=_INVENTORY_0372.inventory_identifier,
    inventory_fingerprint=fingerprint(_INVENTORY_0372),
    snapshot_identifier=_SNAPSHOT_0372.snapshot_identifier,
    snapshot_fingerprint=_SNAPSHOT_0372.snapshot_fingerprint,
    comfyui_profile_identifier=_INVENTORY_0372.comfyui_profile_identifier,
    comfyui_revision=_INVENTORY_0372.expected_comfyui_revision,
    permitted_class_authority_identifier=BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372.identifier,
    permitted_class_authority_fingerprint=BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372.fingerprint,
    fingerprint="",
)
EXACT_THREE_BLEND_REALIZATION_COMFYUI_0372 = replace(
    _BINDING_0372, fingerprint=fingerprint_authority(_BINDING_0372))

# Additive exact 0.37.4 authority; unchanged retained exact-3 semantics.
_INVENTORY_0374 = COMFYUI_0374_QUALIFICATION_PROFILE.inventory
_SNAPSHOT_0374 = COMFYUI_0374_QUALIFICATION_PROFILE.node_snapshot
_CLASSES_0374 = replace(
    BLEND_GRAPH_PERMITTED_CLASSES,
    identifier="prediction-mixing.normalized-blend.graph-permitted-classes.comfyui-0.37.4.v1",
    retained_inventory_identifier=_INVENTORY_0374.inventory_identifier,
    retained_inventory_fingerprint=fingerprint(_INVENTORY_0374),
    required_builtin_classes=_INVENTORY_0374.required_node_class_names,
    fingerprint="",
)
BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0374 = replace(
    _CLASSES_0374, fingerprint=fingerprint_authority(_CLASSES_0374))
_BINDING_0374 = replace(
    EXACT_THREE_BLEND_REALIZATION,
    identifier="prediction-mixing.multi-layer.realization.exact-3.normalized-blend.comfyui-0.37.4.v1",
    inventory_identifier=_INVENTORY_0374.inventory_identifier,
    inventory_fingerprint=fingerprint(_INVENTORY_0374),
    snapshot_identifier=_SNAPSHOT_0374.snapshot_identifier,
    snapshot_fingerprint=_SNAPSHOT_0374.snapshot_fingerprint,
    comfyui_profile_identifier=_INVENTORY_0374.comfyui_profile_identifier,
    comfyui_revision=_INVENTORY_0374.expected_comfyui_revision,
    permitted_class_authority_identifier=BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0374.identifier,
    permitted_class_authority_fingerprint=BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0374.fingerprint,
    fingerprint="",
)
EXACT_THREE_BLEND_REALIZATION_COMFYUI_0374 = replace(
    _BINDING_0374, fingerprint=fingerprint_authority(_BINDING_0374))

# Committed (binding, class authority, host evidence) triples. Each authority
# verifies only against its own host's complete inventory and snapshot.
_REVIEWED_HOSTS = (
    (_REVIEWED_BINDING, _REVIEWED_CLASSES, COMFYUI_0346_SUPPORTED_PROFILE),
    (EXACT_THREE_BLEND_REALIZATION_COMFYUI_0372, BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372,
     COMFYUI_0372_QUALIFICATION_PROFILE),
    (EXACT_THREE_BLEND_REALIZATION_COMFYUI_0374, BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0374,
     COMFYUI_0374_QUALIFICATION_PROFILE),
)
REGISTERED_BLEND_REALIZATION_BINDINGS = (
    EXACT_THREE_BLEND_REALIZATION, EXACT_THREE_BLEND_REALIZATION_COMFYUI_0372, EXACT_THREE_BLEND_REALIZATION_COMFYUI_0374,
)


def _reviewed_host(identifier, position=0):
    matches = tuple(host for host in _REVIEWED_HOSTS if host[position].identifier == identifier)
    return matches[0] if len(matches) == 1 else None


def realization_host_profile(binding):
    """Committed host evidence pinned by an exactly reviewed Blend binding, else None."""
    try:
        host = _reviewed_host(binding.identifier) if type(binding) is BlendRealizationBinding else None
        if host is not None and exact_contract_equal(binding, host[0]):
            return host[2]
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        pass
    return None


def select_blend_realization(entry, profile):
    """(binding, class authority) for this exact entry and exact registered host, else None.

    Unregistered, forged or promoted-by-caller evidence, no candidate, several
    candidates, or a candidate differing from reviewed authority returns None.
    Graph realization then rejects the missing authority; nothing falls back.
    """
    try:
        if not registered_host_evidence(profile):
            return None
        candidates = tuple(
            item for item in REGISTERED_BLEND_REALIZATION_BINDINGS
            if type(item) is BlendRealizationBinding
            and item.eligibility_entry_identifier == entry.identifier
            and claims_host(item, profile)
        )
        if len(candidates) != 1:
            return None
        binding = candidates[0]
        host = _reviewed_host(binding.identifier)
        if (host is None or not exact_contract_equal(binding, host[0])
                or binding.eligibility_entry_fingerprint != entry.fingerprint
                or canonical_bytes(profile.inventory) != canonical_bytes(host[2].inventory)
                or canonical_bytes(profile.node_snapshot) != canonical_bytes(host[2].node_snapshot)):
            return None
        return binding, host[1]
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return None


def fingerprint_realization_binding(binding):
    if type(binding) is not BlendRealizationBinding:
        raise TypeError("A BlendRealizationBinding is required")
    return fingerprint_authority(binding)


def verify_permitted_class_authority(authority, inventory, graph=None):
    try:
        host = (_reviewed_host(authority.identifier, 1)
                if type(authority) is BlendGraphPermittedClassAuthority else None)
        if (host is None
                or not exact_contract_equal(authority, host[1])
                or authority.fingerprint != fingerprint_authority(authority)
                or not exact_contract_equal(inventory, host[2].inventory)):
            raise ValueError("permitted-class authority differs")
        if graph is not None:
            permitted = set(authority.required_builtin_classes) | {authority.project_component_class}
            actual = {item["class_type"] for item in graph.values()}
            if actual != permitted:
                raise ValueError("Blend graph requires its exact governed class set")
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return (_error("blend.graph_classes.invalid", "Graph-v3 permitted classes must match committed authority."),)
    return ()


def verify_realization_binding(binding, plan, inventory, *, registry=None):
    """Validate expected implementation; runtime availability is a separate gate."""
    try:
        entries = REGISTERED_BLEND_REALIZATION_BINDINGS if registry is None else registry
        if type(binding) is not BlendRealizationBinding:
            raise ValueError("binding type")
        selected = tuple(item for item in entries if item.identifier == binding.identifier)
        host = _reviewed_host(binding.identifier)
        if (len(selected) != 1 or host is None
                or not exact_contract_equal(selected[0], host[0])
                or not exact_contract_equal(binding, host[0])
                or binding.fingerprint != fingerprint_realization_binding(binding)
                or not exact_contract_equal(inventory, host[2].inventory)
                or fingerprint_host_node_contract_snapshot(host[2].node_snapshot) != binding.snapshot_fingerprint):
            raise ValueError("binding authority")
        if not validate_blend_component_identity(binding.project_component_identity):
            raise ValueError("project implementation identity")
        if (plan.eligibility_entry.identifier != binding.eligibility_entry_identifier
                or plan.eligibility_entry.fingerprint != binding.eligibility_entry_fingerprint
                or plan.eligibility_entry.exact_cardinality != binding.exact_cardinality
                or plan.execution_profile.profile_identifier != binding.execution_profile_identifier
                or plan.execution_profile.fingerprint != binding.execution_profile_fingerprint
                or plan.topology_policy.fingerprint != binding.topology_policy_fingerprint
                or plan.contract_identifier != binding.contract_identifier
                or plan.contract_version != binding.contract_version):
            raise ValueError("selected plan authority")
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return (_error("blend.realization.invalid", "Blend realization must match committed authority and project implementation."),)
    return ()


def _error(code, message):
    return ValidationFinding(code, FindingSeverity.ERROR, message)
