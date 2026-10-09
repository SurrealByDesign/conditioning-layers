"""Selected immutable N=3 realization; never a mutable inventory/profile alias.

Each binding pins one exact registered host. Selection keys on that host's
complete registered evidence, never a version string, "latest" or an observed
host, and an unbound host never falls back to another host's binding.
"""

from dataclasses import replace

from conditioning_layers.adapters.prediction_mixing.multi_layer import MULTI_LAYER_EXECUTION_PROFILE
from conditioning_layers.adapters.prediction_mixing.v2.topology import ORDERED_LEFT_FOLD_TOPOLOGY_POLICY
from conditioning_layers.capabilities.multi_layer import EXACT_THREE_ELIGIBILITY
from conditioning_layers.comfyui.prediction_mixing.node_contracts import fingerprint_host_node_contract_snapshot
from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0346_SUPPORTED_PROFILE, COMFYUI_0372_QUALIFICATION_PROFILE,
    COMFYUI_0374_QUALIFICATION_PROFILE, REGISTERED_COMFYUI_PROFILES,
    CompatibilityProfile, ProfileSupportStatus,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .canonical import canonical_bytes, fingerprint, json_value
from .models import RealizationBinding, GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION, GENERATOR_VERSION_IDENTIFIER

INVENTORY = COMFYUI_0346_SUPPORTED_PROFILE.inventory
SNAPSHOT = COMFYUI_0346_SUPPORTED_PROFILE.node_snapshot


def fingerprint_realization_binding(binding: RealizationBinding) -> str:
    material = json_value(binding)
    material.pop("fingerprint")
    return fingerprint(material)


_BINDING = RealizationBinding(
    identifier="prediction-mixing.multi-layer.realization.exact-3.comfyui-0.34.6.v1",
    contract_identifier=EXACT_THREE_ELIGIBILITY.contract_identifier,
    contract_version=1,
    eligibility_entry_identifier=EXACT_THREE_ELIGIBILITY.identifier,
    eligibility_entry_fingerprint=EXACT_THREE_ELIGIBILITY.fingerprint,
    exact_cardinality=3,
    execution_profile_identifier=MULTI_LAYER_EXECUTION_PROFILE.profile_identifier,
    execution_profile_fingerprint=MULTI_LAYER_EXECUTION_PROFILE.fingerprint,
    topology_policy_identifier=ORDERED_LEFT_FOLD_TOPOLOGY_POLICY.policy_identifier,
    topology_policy_fingerprint=ORDERED_LEFT_FOLD_TOPOLOGY_POLICY.fingerprint,
    graph_identifier=GRAPH_FORMAT_IDENTIFIER,
    graph_version=GRAPH_FORMAT_VERSION,
    generator_identifier=GENERATOR_VERSION_IDENTIFIER,
    inventory_identifier=INVENTORY.inventory_identifier,
    inventory_fingerprint=fingerprint(INVENTORY),
    snapshot_identifier=SNAPSHOT.snapshot_identifier,
    snapshot_fingerprint=SNAPSHOT.snapshot_fingerprint,
    comfyui_profile_identifier=INVENTORY.comfyui_profile_identifier,
    comfyui_revision=INVENTORY.expected_comfyui_revision,
    node_allocation="4N + 7; dense decimal IDs; loaders, positive, negative, fields, masks, folds, latent, sampler, VAE, decode, save",
    host_link_allocation="5N + 6",
    realization_semantics=(
        "ordered-left-fold; conditioning_1=left; conditioning_2=right",
        "ConditioningCombine ordered list concatenation; no priority",
        "LoadImageMask red; ConditioningSetMask default; exact Strength; no pruning",
        "one sampler/decode/SaveImage; no separate Base condition",
        "Euler/Simple; steps=8; cfg=1.0; denoise=1.0; batch=1",
    ),
    fingerprint="",
)
EXACT_THREE_REALIZATION = replace(_BINDING, fingerprint=fingerprint_realization_binding(_BINDING))

# ComfyUI 0.37.2 (docs/COMFYUI_0_37_2_HOST_SUPPORT_REFRESH.md): the retained
# declaration with only its identifier and exact host pins rebound to that
# registered QUALIFICATION_ONLY evidence. Realization semantics are unchanged.
_BINDING_0372 = replace(
    EXACT_THREE_REALIZATION,
    identifier="prediction-mixing.multi-layer.realization.exact-3.comfyui-0.37.2.v1",
    inventory_identifier=COMFYUI_0372_QUALIFICATION_PROFILE.inventory.inventory_identifier,
    inventory_fingerprint=fingerprint(COMFYUI_0372_QUALIFICATION_PROFILE.inventory),
    snapshot_identifier=COMFYUI_0372_QUALIFICATION_PROFILE.node_snapshot.snapshot_identifier,
    snapshot_fingerprint=COMFYUI_0372_QUALIFICATION_PROFILE.node_snapshot.snapshot_fingerprint,
    comfyui_profile_identifier=COMFYUI_0372_QUALIFICATION_PROFILE.inventory.comfyui_profile_identifier,
    comfyui_revision=COMFYUI_0372_QUALIFICATION_PROFILE.inventory.expected_comfyui_revision,
    fingerprint="",
)
EXACT_THREE_REALIZATION_COMFYUI_0372 = replace(
    _BINDING_0372, fingerprint=fingerprint_realization_binding(_BINDING_0372))

# Additive exact 0.37.4 authority; unchanged retained exact-3 semantics.
_BINDING_0374 = replace(
    EXACT_THREE_REALIZATION,
    identifier="prediction-mixing.multi-layer.realization.exact-3.comfyui-0.37.4.v1",
    inventory_identifier=COMFYUI_0374_QUALIFICATION_PROFILE.inventory.inventory_identifier,
    inventory_fingerprint=fingerprint(COMFYUI_0374_QUALIFICATION_PROFILE.inventory),
    snapshot_identifier=COMFYUI_0374_QUALIFICATION_PROFILE.node_snapshot.snapshot_identifier,
    snapshot_fingerprint=COMFYUI_0374_QUALIFICATION_PROFILE.node_snapshot.snapshot_fingerprint,
    comfyui_profile_identifier=COMFYUI_0374_QUALIFICATION_PROFILE.inventory.comfyui_profile_identifier,
    comfyui_revision=COMFYUI_0374_QUALIFICATION_PROFILE.inventory.expected_comfyui_revision,
    fingerprint="",
)
EXACT_THREE_REALIZATION_COMFYUI_0374 = replace(
    _BINDING_0374, fingerprint=fingerprint_realization_binding(_BINDING_0374))

# Committed (binding, host evidence) pairs. A binding verifies only against its
# own host's complete inventory and snapshot, never against another host's.
_REVIEWED_HOSTS = (
    (EXACT_THREE_REALIZATION, COMFYUI_0346_SUPPORTED_PROFILE),
    (EXACT_THREE_REALIZATION_COMFYUI_0372, COMFYUI_0372_QUALIFICATION_PROFILE),
    (EXACT_THREE_REALIZATION_COMFYUI_0374, COMFYUI_0374_QUALIFICATION_PROFILE),
)
REGISTERED_REALIZATION_BINDINGS = (
    EXACT_THREE_REALIZATION, EXACT_THREE_REALIZATION_COMFYUI_0372, EXACT_THREE_REALIZATION_COMFYUI_0374,
)


def _reviewed_host(identifier):
    matches = tuple(pair for pair in _REVIEWED_HOSTS if pair[0].identifier == identifier)
    return matches[0] if len(matches) == 1 else None


def realization_host_profile(binding: object) -> CompatibilityProfile | None:
    """Committed host evidence pinned by an exactly reviewed binding, else None."""
    try:
        host = _reviewed_host(binding.identifier) if type(binding) is RealizationBinding else None
        if host is not None and canonical_bytes(binding) == canonical_bytes(host[0]):
            return host[1]
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        pass
    return None


def registered_host_evidence(profile: object) -> bool:
    """Exact registered inventory/snapshot; a SUPPORTED claim needs a SUPPORTED registration.

    Support status is not realization identity: the historical QUALIFICATION_ONLY
    wrapper of supported evidence remains valid, but no caller can promote a
    qualification-only host by constructing its own SUPPORTED wrapper.
    """
    try:
        if type(profile) is not CompatibilityProfile or type(profile.status) is not ProfileSupportStatus:
            return False
        registered = REGISTERED_COMFYUI_PROFILES.get(profile.inventory.comfyui_profile_identifier)
        return (type(registered) is CompatibilityProfile
                and canonical_bytes(profile.inventory) == canonical_bytes(registered.inventory)
                and canonical_bytes(profile.node_snapshot) == canonical_bytes(registered.node_snapshot)
                and (profile.status is not ProfileSupportStatus.SUPPORTED
                     or registered.status is ProfileSupportStatus.SUPPORTED))
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return False


def claims_host(binding: object, profile: CompatibilityProfile) -> bool:
    """Any shared host identity counts, so a shadowing sibling makes selection ambiguous."""
    inventory, snapshot = profile.inventory, profile.node_snapshot
    return (binding.comfyui_profile_identifier == inventory.comfyui_profile_identifier
            or binding.comfyui_revision == inventory.expected_comfyui_revision
            or binding.inventory_identifier == inventory.inventory_identifier
            or binding.inventory_fingerprint == fingerprint(inventory)
            or binding.snapshot_identifier == snapshot.snapshot_identifier
            or binding.snapshot_fingerprint == snapshot.snapshot_fingerprint)


def select_realization_binding(entry: object, profile: object) -> RealizationBinding | None:
    """The single registered binding for this exact entry and exact registered host.

    Unregistered, forged or promoted-by-caller evidence, no candidate, several
    candidates, or a candidate differing from reviewed authority returns None.
    Graph realization then rejects the missing binding; nothing falls back.
    """
    try:
        if not registered_host_evidence(profile):
            return None
        candidates = tuple(
            item for item in REGISTERED_REALIZATION_BINDINGS
            if type(item) is RealizationBinding
            and item.eligibility_entry_identifier == entry.identifier
            and claims_host(item, profile)
        )
        if len(candidates) != 1:
            return None
        binding = candidates[0]
        host = _reviewed_host(binding.identifier)
        if (host is None or canonical_bytes(binding) != canonical_bytes(host[0])
                or binding.eligibility_entry_fingerprint != entry.fingerprint
                or canonical_bytes(profile.inventory) != canonical_bytes(host[1].inventory)
                or canonical_bytes(profile.node_snapshot) != canonical_bytes(host[1].node_snapshot)):
            return None
        return binding
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return None


def verify_realization_binding(binding: object, plan: object, inventory: object,
                               *, registry=None) -> tuple[ValidationFinding, ...]:
    """Compare selected content with committed authority, independently of inputs."""
    try:
        entries = REGISTERED_REALIZATION_BINDINGS if registry is None else registry
        if type(binding) is not RealizationBinding:
            raise ValueError("wrong binding type")
        selected = tuple(item for item in entries if item.identifier == binding.identifier)
        host = _reviewed_host(binding.identifier)
        if len(selected) != 1 or host is None or canonical_bytes(selected[0]) != canonical_bytes(host[0]):
            raise ValueError("missing, duplicate or altered registration")
        if (canonical_bytes(binding) != canonical_bytes(selected[0])
                or binding.fingerprint != fingerprint_realization_binding(binding)):
            raise ValueError("binding content or fingerprint mismatch")
        if canonical_bytes(inventory) != canonical_bytes(host[1].inventory):
            raise ValueError("complete pinned inventory mismatch")
        if fingerprint_host_node_contract_snapshot(host[1].node_snapshot) != binding.snapshot_fingerprint:
            raise ValueError("snapshot mismatch")
        if (plan.eligibility_entry.identifier != binding.eligibility_entry_identifier
                or plan.eligibility_entry.fingerprint != binding.eligibility_entry_fingerprint
                or plan.eligibility_entry.exact_cardinality != binding.exact_cardinality
                or plan.execution_profile.profile_identifier != binding.execution_profile_identifier
                or plan.execution_profile.fingerprint != binding.execution_profile_fingerprint
                or plan.topology_policy.fingerprint != binding.topology_policy_fingerprint
                or plan.contract_identifier != binding.contract_identifier
                or plan.contract_version != binding.contract_version):
            raise ValueError("selected plan authority mismatch")
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return (ValidationFinding("multi_layer.realization.invalid", FindingSeverity.ERROR,
                                  "The selected realization does not match registered authority."),)
    return ()
