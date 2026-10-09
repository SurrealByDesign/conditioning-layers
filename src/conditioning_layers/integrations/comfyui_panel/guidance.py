"""Small read-only artist guidance projection of product-admitted authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from conditioning_layers.capabilities import PREDICTION_MIXING_CAPABILITY
from conditioning_layers.capabilities.product import product_supported_cardinalities, product_policy_cardinalities
from conditioning_layers.domain import NORMALIZED_BLEND, REQUIRE_NO_OVERLAP, FindingSeverity, ValidationFinding

from .models import PanelFinding, project_findings


# This is a UI disclosure selection, not another execution capability policy.
# Explicit codes keep unrelated diagnostics and qualification findings out.
PRODUCT_WARNING_CODES = frozenset(
    {
        "capability.adapter_experimental",
        "risk.seam",
        "risk.leakage",
        "risk.fusion",
        "risk.topology",
        "risk.runtime_scaling",
        "risk.vram",
        "capability.zero_strength_active",
    }
)


def panel_capability_guidance() -> dict[str, object]:
    """Describe the current adapter without validating or executing a draft."""

    capability = PREDICTION_MIXING_CAPABILITY
    admitted = product_supported_cardinalities()
    policies = product_policy_cardinalities()
    contiguous = bool(admitted) and admitted == tuple(range(admitted[0], admitted[-1] + 1))
    minimum = admitted[0] if contiguous else None
    maximum = admitted[-1] if contiguous else None
    support_text = (
        f"{minimum} to {maximum}" if contiguous and len(admitted) > 1
        else ", ".join(str(count) for count in admitted) if admitted else "no"
    )
    findings = (
        PanelFinding(
            "capability.adapter_experimental",
            FindingSeverity.WARNING.value,
            capability.production_quality.note,
        ),
        *(
            PanelFinding(risk.code, FindingSeverity.WARNING.value, risk.message)
            for risk in capability.known_risks
            if risk.code in PRODUCT_WARNING_CODES
        ),
        PanelFinding(
            "risk.runtime_scaling",
            FindingSeverity.WARNING.value,
            capability.runtime_scaling.statement,
        ),
        PanelFinding(
            "risk.vram",
            FindingSeverity.WARNING.value,
            capability.vram.statement,
        ),
    )
    return {
        "adapter_display_name": capability.display_name,
        "backend_name": capability.backend_name,
        "status": capability.status.value,
        "minimum_active_layers": minimum,
        "maximum_active_layers": maximum,
        "supported_active_layer_counts": list(admitted),
        "composition_policies": [
            {"policy_identifier": policy.identifier, "policy_version": policy.version,
             "display_name": policy.display_name,
             "supported_active_layer_counts": list(policies[policy.identifier])}
            for policy in (REQUIRE_NO_OVERLAP, NORMALIZED_BLEND)
        ],
        "blend_guidance": (
            ("Blend generation supports exactly three Active Prompt Layers. "
             if policies[NORMALIZED_BLEND.identifier] else
             "Blend is qualified but not product admitted. Edit and Save are available; Generate is unavailable. ")
            + "Strength is relative under Blend: a lone positive contributor has local weight 1 at any positive Strength. "
            "Results are not perceptually linear; zero total weight adds no layer contribution."
        ),
        "explicit_no_overlap_guidance": "Explicit 2.0 No Overlap can be preserved and saved but cannot execute through the retained product route.",
        "active_guidance": (
            f"Generation supports {support_text} Active Prompt Layers. "
            "Only Active layers participate; Disabled layers remain saved. "
            "An Active layer at zero Strength still counts toward the limit."
        ),
        # Translate EFFECTIVE_WEIGHT_EXPRESSION and the product brief's
        # normalization caveat into artist wording, without changing mapping.
        "strength_guidance": (
            "Strength scales requested overall influence in the field (0.0 to 1.0). "
            "Field values are multiplied by Strength. Results are experimental, "
            "not perceptually linear or Opacity. Normalization can cancel equal "
            "scaling of Active layers."
        ),
        "order_guidance": capability.retained_order_execution.note,
        "overlap_guidance": (
            "No Overlap: overlapping Active Influence Fields are rejected before generation. "
            + ("Normalized Blend: overlapping Active Influence Fields are allowed under explicit Blend policy "
               "with exactly three Active Prompt Layers."
               if policies[NORMALIZED_BLEND.identifier] else
               "Normalized Blend generation is unavailable; selecting or saving Blend does not grant admission.")
        ),
        "profile_guidance": capability.tested_resolution.statement,
        "findings": [finding.to_json() for finding in findings],
    }


def project_product_warnings(
    findings: Sequence[ValidationFinding],
    layer_labels: Mapping[str, str] | None = None,
) -> tuple[PanelFinding, ...]:
    """Retain only the bounded current product warnings actually supplied."""

    return project_findings(
        tuple(
            finding
            for finding in findings
            if finding.code in PRODUCT_WARNING_CODES
            and finding.severity is FindingSeverity.WARNING
        ),
        layer_labels,
    )
