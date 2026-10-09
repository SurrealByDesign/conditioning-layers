"""ADR-0028 offline generalized Blend realization for exact N=4..9 only.

Not imported by the package root, product router, panel, web or root loader.
Availability, product admission and host registration stay separate gates.
"""

from .authority import (
    EXACT_EIGHT_GENERALIZED_BLEND_REALIZATION, EXACT_FIVE_GENERALIZED_BLEND_REALIZATION,
    EXACT_FOUR_GENERALIZED_BLEND_REALIZATION, EXACT_NINE_GENERALIZED_BLEND_REALIZATION,
    EXACT_SEVEN_GENERALIZED_BLEND_REALIZATION, EXACT_SIX_GENERALIZED_BLEND_REALIZATION,
    GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES, INVENTORY,
    REGISTERED_GENERALIZED_BLEND_PERMITTED_CLASS_AUTHORITIES,
    REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS,
    fingerprint_authority, fingerprint_generalized_realization_binding,
    select_generalized_realization_binding, verify_generalized_permitted_class_authority,
    verify_generalized_realization_binding,
)
from .graph import (
    fingerprint_generalized_blend_graph, generate_generalized_blend_workflow,
    validate_generalized_blend_artifact,
)
from .models import (
    GENERATOR_VERSION_IDENTIFIER, GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION,
    OFFLINE_FIXTURE_AVAILABILITY_SCOPE,
    GeneralizedBlendGraphArtifact, GeneralizedBlendGraphPermittedClassAuthority,
    GeneralizedBlendGraphResult, GeneralizedBlendRealizationBinding,
    GeneralizedBlendWorkflowProvenance,
)
