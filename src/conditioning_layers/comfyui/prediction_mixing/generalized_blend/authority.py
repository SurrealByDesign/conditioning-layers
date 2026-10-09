"""ADR-0028 generalized permitted classes and exact N=4..9 realization bindings.

Each binding is a fixed source declaration for one reviewed Slice A entry.
There is no range, wildcard, placeholder, maximum-derived or caller-authored
binding. Verification compares complete typed content with the reviewed
declaration of the same identifier; registration alone cannot authenticate a
self-consistent forgery. No generalized N=3 binding exists: the retained
exact-3 realization remains the only exact-3 authority. Availability is
offline fixture construction only, not host registration.
"""

from dataclasses import replace

from conditioning_layers.adapters.prediction_mixing.blend import BLEND_EXECUTION_PROFILE
from conditioning_layers.adapters.prediction_mixing.v2.identity import exact_contract_equal
from conditioning_layers.adapters.prediction_mixing.v2.topology import ORDERED_LEFT_FOLD_TOPOLOGY_POLICY
from conditioning_layers.capabilities.blend import (
    EXACT_FOUR_BLEND_ELIGIBILITY, EXACT_FIVE_BLEND_ELIGIBILITY, EXACT_SIX_BLEND_ELIGIBILITY,
    EXACT_SEVEN_BLEND_ELIGIBILITY, EXACT_EIGHT_BLEND_ELIGIBILITY, EXACT_NINE_BLEND_ELIGIBILITY,
    verify_blend_eligibility,
)
from conditioning_layers.comfyui.prediction_mixing import COMFYUI_0346_SUPPORTED_PROFILE
from conditioning_layers.comfyui.prediction_mixing.blend_component import BLEND_ALGORITHM_ID
from conditioning_layers.comfyui.prediction_mixing.generalized_blend_component import (
    GENERALIZED_BLEND_NODE_CLASS, generalized_blend_component_identity,
    validate_generalized_blend_component_identity,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import fingerprint, json_value
from conditioning_layers.comfyui.prediction_mixing.node_contracts import fingerprint_host_node_contract_snapshot
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .models import (
    GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION, GENERATOR_VERSION_IDENTIFIER,
    OFFLINE_FIXTURE_AVAILABILITY_SCOPE,
    GeneralizedBlendGraphPermittedClassAuthority, GeneralizedBlendRealizationBinding,
)


INVENTORY = COMFYUI_0346_SUPPORTED_PROFILE.inventory
SNAPSHOT = COMFYUI_0346_SUPPORTED_PROFILE.node_snapshot
COMPONENT_IDENTITY = generalized_blend_component_identity()


def fingerprint_authority(value):
    material = json_value(value)
    material.pop("fingerprint")
    return fingerprint(material)


_CLASSES = GeneralizedBlendGraphPermittedClassAuthority(
    identifier="prediction-mixing.normalized-blend.generalized.graph-permitted-classes.v1",
    graph_identifier=GRAPH_FORMAT_IDENTIFIER, graph_version=GRAPH_FORMAT_VERSION,
    retained_inventory_identifier=INVENTORY.inventory_identifier,
    retained_inventory_fingerprint=fingerprint(INVENTORY),
    required_builtin_classes=INVENTORY.required_node_class_names,
    project_component_class=GENERALIZED_BLEND_NODE_CLASS,
    project_component_contract_fingerprint=COMPONENT_IDENTITY.contract_fingerprint,
    project_component_implementation_fingerprint=COMPONENT_IDENTITY.implementation_fingerprint,
    fingerprint="",
)
GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES = replace(_CLASSES, fingerprint=fingerprint_authority(_CLASSES))
_REVIEWED_CLASSES = GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES
REGISTERED_GENERALIZED_BLEND_PERMITTED_CLASS_AUTHORITIES = (GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES,)


_REALIZATION_SEMANTICS = (
    "ordered-left-fold; conditioning_1=left; conditioning_2=right; no priority",
    "LoadImageMask red; ConditioningSetMask default; authored binary64 Strength; no pruning or deduplication",
    "exact recovered 8-bit sample code and exact dyadic Strength; support before product",
    "exact rational normalization; one binary32 round-to-nearest ties-to-even; zero branch without division",
    "deterministic CPU preparation; batch=1; 128x128; prepared binary32 masks; mask_strength=1.0",
    "explicit trusted expected_count literal equals exact N; the received collection never authorizes its count",
    "no area strength; no resize; no hooks, wrappers, transformations or schedules",
    "retained binary32 KSampler accumulator; N-dependent rounding bound; exact-3 seed neutralization not claimed",
    "one sampler/decode/SaveImage; Base repeated with two newlines; no Base denominator term",
    "offline fixture availability only; no host registration; not submission-ready; not live-qualified; not product-admitted",
)


def _reviewed_binding(identifier, entry):
    """Declare one exact binding from one fixed reviewed entry constant."""
    n = entry.exact_cardinality
    binding = GeneralizedBlendRealizationBinding(
        identifier=identifier,
        contract_identifier=entry.contract_identifier, contract_version=entry.contract_version,
        eligibility_entry_identifier=entry.identifier, eligibility_entry_fingerprint=entry.fingerprint,
        exact_cardinality=n, expected_count=n,
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
        node_allocation=(f"4N + 8 = {4 * n + 8}; exact N={n}; dense IDs; preparation {4 * n + 3} "
                         f"after folds before latent/sampler; SaveImage {4 * n + 8} last"),
        host_link_allocation=f"5N + 7 = {5 * n + 7}; exact N={n}; expected-count literal adds no link",
        algorithm_identifier=BLEND_ALGORITHM_ID,
        project_component_identity=COMPONENT_IDENTITY,
        permitted_class_authority_identifier=GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES.identifier,
        permitted_class_authority_fingerprint=GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES.fingerprint,
        component_availability_scope=OFFLINE_FIXTURE_AVAILABILITY_SCOPE,
        realization_semantics=_REALIZATION_SEMANTICS,
        fingerprint="",
    )
    return replace(binding, fingerprint=fingerprint_authority(binding))


EXACT_FOUR_GENERALIZED_BLEND_REALIZATION = _reviewed_binding(
    "prediction-mixing.multi-layer.realization.exact-4.normalized-blend.generalized-preparation.comfyui-0.34.6.v1",
    EXACT_FOUR_BLEND_ELIGIBILITY)
EXACT_FIVE_GENERALIZED_BLEND_REALIZATION = _reviewed_binding(
    "prediction-mixing.multi-layer.realization.exact-5.normalized-blend.generalized-preparation.comfyui-0.34.6.v1",
    EXACT_FIVE_BLEND_ELIGIBILITY)
EXACT_SIX_GENERALIZED_BLEND_REALIZATION = _reviewed_binding(
    "prediction-mixing.multi-layer.realization.exact-6.normalized-blend.generalized-preparation.comfyui-0.34.6.v1",
    EXACT_SIX_BLEND_ELIGIBILITY)
EXACT_SEVEN_GENERALIZED_BLEND_REALIZATION = _reviewed_binding(
    "prediction-mixing.multi-layer.realization.exact-7.normalized-blend.generalized-preparation.comfyui-0.34.6.v1",
    EXACT_SEVEN_BLEND_ELIGIBILITY)
EXACT_EIGHT_GENERALIZED_BLEND_REALIZATION = _reviewed_binding(
    "prediction-mixing.multi-layer.realization.exact-8.normalized-blend.generalized-preparation.comfyui-0.34.6.v1",
    EXACT_EIGHT_BLEND_ELIGIBILITY)
EXACT_NINE_GENERALIZED_BLEND_REALIZATION = _reviewed_binding(
    "prediction-mixing.multi-layer.realization.exact-9.normalized-blend.generalized-preparation.comfyui-0.34.6.v1",
    EXACT_NINE_BLEND_ELIGIBILITY)

# Reviewed content is independent of registration: replacing a registered
# binding with a self-consistent forgery cannot make that forgery trusted.
_REVIEWED_BINDINGS = (
    EXACT_FOUR_GENERALIZED_BLEND_REALIZATION, EXACT_FIVE_GENERALIZED_BLEND_REALIZATION,
    EXACT_SIX_GENERALIZED_BLEND_REALIZATION, EXACT_SEVEN_GENERALIZED_BLEND_REALIZATION,
    EXACT_EIGHT_GENERALIZED_BLEND_REALIZATION, EXACT_NINE_GENERALIZED_BLEND_REALIZATION,
)
REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS = _REVIEWED_BINDINGS


def fingerprint_generalized_realization_binding(binding):
    if type(binding) is not GeneralizedBlendRealizationBinding:
        raise TypeError("A GeneralizedBlendRealizationBinding is required")
    return fingerprint_authority(binding)


def verify_generalized_permitted_class_authority(authority, inventory, graph=None):
    try:
        registered = tuple(item for item in REGISTERED_GENERALIZED_BLEND_PERMITTED_CLASS_AUTHORITIES
                           if item.identifier == authority.identifier)
        if (type(authority) is not GeneralizedBlendGraphPermittedClassAuthority
                or len(registered) != 1
                or not exact_contract_equal(authority, _REVIEWED_CLASSES)
                or not exact_contract_equal(registered[0], _REVIEWED_CLASSES)
                or authority.fingerprint != fingerprint_authority(authority)
                # Another registered authority cannot shadow this graph version.
                or sum(item.graph_version == authority.graph_version
                       for item in REGISTERED_GENERALIZED_BLEND_PERMITTED_CLASS_AUTHORITIES) != 1
                or not exact_contract_equal(inventory, INVENTORY)):
            raise ValueError("permitted-class authority differs")
        if graph is not None:
            permitted = set(authority.required_builtin_classes) | {authority.project_component_class}
            if {item["class_type"] for item in graph.values()} != permitted:
                raise ValueError("Generalized Blend graph requires its exact governed class set")
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return (_error("blend.generalized_graph_classes.invalid",
                       "Graph-v4 permitted classes must match committed generalized authority."),)
    return ()


def verify_generalized_realization_binding(binding, plan, inventory):
    """Validate the exact reviewed binding and the verified plan it realizes."""
    try:
        if type(binding) is not GeneralizedBlendRealizationBinding:
            raise ValueError("binding type")
        reviewed = tuple(item for item in _REVIEWED_BINDINGS if item.identifier == binding.identifier)
        registered = tuple(item for item in REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS
                           if item.identifier == binding.identifier)
        if (len(reviewed) != 1 or len(registered) != 1
                or not exact_contract_equal(binding, reviewed[0])
                or not exact_contract_equal(registered[0], reviewed[0])
                or binding.fingerprint != fingerprint_generalized_realization_binding(binding)
                # No second registered binding may shadow this exact entry or count.
                or sum(item.eligibility_entry_identifier == binding.eligibility_entry_identifier
                       or item.exact_cardinality == binding.exact_cardinality
                       for item in REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS) != 1
                or not exact_contract_equal(inventory, INVENTORY)
                or fingerprint_host_node_contract_snapshot(SNAPSHOT) != binding.snapshot_fingerprint
                or not validate_generalized_blend_component_identity(binding.project_component_identity)):
            raise ValueError("binding authority")
        if (verify_blend_eligibility(plan.eligibility_entry)
                or plan.eligibility_entry.identifier != binding.eligibility_entry_identifier
                or plan.eligibility_entry.fingerprint != binding.eligibility_entry_fingerprint
                or plan.eligibility_entry.exact_cardinality != binding.exact_cardinality
                or len(plan.regional_conditions) != binding.expected_count
                or plan.execution_profile.profile_identifier != binding.execution_profile_identifier
                or plan.execution_profile.fingerprint != binding.execution_profile_fingerprint
                or plan.topology_policy.fingerprint != binding.topology_policy_fingerprint
                or plan.contract_identifier != binding.contract_identifier
                or plan.contract_version != binding.contract_version):
            raise ValueError("selected plan authority")
    except (TypeError, ValueError, AttributeError, KeyError, UnicodeError):
        return (_error("blend.generalized_realization.invalid",
                       "Generalized Blend realization must match committed exact authority and implementation."),)
    return ()


def select_generalized_realization_binding(plan):
    """Exact lookup by the plan's entry identifier; no count inference or fallback."""
    try:
        matches = tuple(item for item in REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS
                        if item.eligibility_entry_identifier == plan.eligibility_entry.identifier)
        if len(matches) == 1 and not verify_generalized_realization_binding(matches[0], plan, INVENTORY):
            return matches[0]
    except (TypeError, AttributeError):
        pass
    raise ValueError("No reviewed exact generalized Blend realization binding matches this plan")


def _error(code, message):
    return ValidationFinding(code, FindingSeverity.ERROR, message)
