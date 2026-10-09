"""I/O-free policy-bearing Translation Plan v4 for the exact-three Blend route."""

from dataclasses import replace
import json
import math

from conditioning_layers.adapters.prediction_mixing import combine_prompt_text
from conditioning_layers.adapters.prediction_mixing.multi_layer.translate import _verify_certificate
from conditioning_layers.adapters.prediction_mixing.v2.canonical import canonical_json_bytes
from conditioning_layers.adapters.prediction_mixing.v2.identity import exact_contract_equal, fingerprint_without_field
from conditioning_layers.adapters.prediction_mixing.v2.models import TranslationStatus
from conditioning_layers.adapters.prediction_mixing.v2.topology import (
    ORDERED_LEFT_FOLD_TOPOLOGY_POLICY, build_ordered_left_fold_schedule,
)
from conditioning_layers.capabilities.blend import (
    BLEND_CONTRACT_IDENTIFIER, BLEND_CONTRACT_VERSION, EXACT_THREE_BLEND_ELIGIBILITY,
    evaluate_blend_eligibility, verify_blend_eligibility,
)
from conditioning_layers.capabilities.multi_layer import multi_layer_warnings
from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, ConditioningDocument, FindingSeverity,
    InfluenceFieldAssetReference, NORMALIZED_BLEND, PromptLayer, ValidationFinding,
)
from conditioning_layers.domain.execution_projection import (
    DocumentExecutionProjection, build_document_execution_projection,
    fingerprint_document_execution_projection,
)

from .models import (
    BLEND_EXECUTION_PROFILE, TRANSLATION_PLAN_V4_IDENTIFIER, TRANSLATION_PLAN_V4_VERSION,
    BlendExecutionProfile, RegionalConditionPlanV4, TranslationPlanV4, TranslationResultV4,
)


def fingerprint_execution_profile(profile):
    if type(profile) is not BlendExecutionProfile:
        raise TypeError("A BlendExecutionProfile is required")
    return fingerprint_without_field(profile)


def fingerprint_translation_plan_v4(plan):
    if type(plan) is not TranslationPlanV4:
        raise TypeError("A TranslationPlanV4 is required")
    return fingerprint_without_field(plan)


def serialize_translation_plan_v4(plan):
    if type(plan) is not TranslationPlanV4:
        raise TypeError("A TranslationPlanV4 is required")
    return canonical_json_bytes(plan)


def _warnings(conditions):
    return multi_layer_warnings(zero_strength_active=any(item.requested_strength == 0 for item in conditions)) + (
        ValidationFinding("blend.not_live_qualified", FindingSeverity.WARNING,
                          "Normalized Blend has offline implementation evidence only; it is not live-qualified."),
        ValidationFinding("blend.not_product_admitted", FindingSeverity.WARNING,
                          "Normalized Blend is not product-admitted."),
    )


def plan_warning_codes(plan):
    return tuple(item.code for item in _warnings(plan.regional_conditions))


def _verify_profile(profile):
    try:
        valid = (type(profile) is BlendExecutionProfile
                 and fingerprint_execution_profile(profile) == profile.fingerprint
                 and exact_contract_equal(profile, BLEND_EXECUTION_PROFILE))
    except (TypeError, ValueError, UnicodeError):
        valid = False
    return () if valid else (_error("blend.profile.invalid", "The immutable policy-bearing v3 profile is required."),)


def _validate_projection(projection, eligibility_entry=EXACT_THREE_BLEND_ELIGIBILITY):
    if (type(projection) is not DocumentExecutionProjection
            or fingerprint_document_execution_projection(projection) != projection.fingerprint):
        raise ValueError("projection identity")
    document = ConditioningDocument(
        version=COMPOSITION_POLICY_PROTOTYPE_VERSION, document_id="blend-projection-verification",
        base_prompt=projection.base_prompt_text,
        selected_adapter_id=projection.selected_adapter_identifier,
        adapter_settings=json.loads(projection.canonical_adapter_settings_json),
        composition_policy=projection.composition_policy,
        layers=tuple(PromptLayer(
            layer_id=item.layer_id, name="Projection layer", prompt_text=item.prompt_text,
            strength=item.requested_strength,
            influence_field=InfluenceFieldAssetReference(item.influence_field_reference, item.declared_field_sha256),
        ) for item in projection.active_layers),
    )
    if (evaluate_blend_eligibility(document, eligibility_entry)
            or not exact_contract_equal(build_document_execution_projection(document), projection)):
        raise ValueError("projection semantics")


def _conditions(projection, certificate, profiles, profile):
    return tuple(RegionalConditionPlanV4(
        active_ordinal=ordinal, document_index=record.document_index, layer_id=layer.layer_id,
        regional_prompt_text=layer.prompt_text,
        combined_prompt_text=combine_prompt_text(projection.base_prompt_text, layer.prompt_text),
        requested_strength=0.0 if layer.requested_strength == 0.0 else layer.requested_strength,
        field_profile=field, polarity=certificate.polarity, orientation=certificate.orientation,
        effective_weight_expression=profile.effective_weight_expression,
    ) for ordinal, (layer, record, field) in enumerate(zip(
        projection.active_layers, certificate.ordered_fields, profiles, strict=True)))


def translate_prediction_mixing_blend(
    document, certificate, field_profiles, *,
    eligibility_entry=EXACT_THREE_BLEND_ELIGIBILITY,
    execution_profile=BLEND_EXECUTION_PROFILE,
    contract_identifier=BLEND_CONTRACT_IDENTIFIER,
    topology_policy=ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
):
    """Realizable intent accepts measured overlap/gaps, with no admission bypass."""
    errors = list(evaluate_blend_eligibility(document, eligibility_entry))
    errors.extend(_verify_profile(execution_profile))
    if contract_identifier != BLEND_CONTRACT_IDENTIFIER:
        errors.append(_error("blend.contract.invalid", "The policy-aware family is required."))
    if not exact_contract_equal(topology_policy, ORDERED_LEFT_FOLD_TOPOLOGY_POLICY):
        errors.append(_error("blend.topology.invalid", "The unchanged ordered left fold is required."))
    try:
        projection = build_document_execution_projection(document)
    except (TypeError, ValueError, AttributeError, UnicodeError, OverflowError):
        errors.append(_error("blend.document.invalid", "Document cannot supply an exact execution projection."))
        projection = None
    if errors:
        return TranslationResultV4(TranslationStatus.REJECTED, None, tuple(errors))
    # This helper verifies measurement and source-identity relations only. The
    # retained translator's separate no-overlap admission check is not reused.
    errors.extend(_verify_certificate(projection, certificate, field_profiles, execution_profile,
        tuple(index for index, layer in enumerate(document.layers) if layer.visible is True)))
    if errors:
        return TranslationResultV4(TranslationStatus.INVALID, None, tuple(errors))
    conditions = _conditions(projection, certificate, field_profiles, execution_profile)
    plan = TranslationPlanV4(
        TRANSLATION_PLAN_V4_IDENTIFIER, TRANSLATION_PLAN_V4_VERSION,
        BLEND_CONTRACT_IDENTIFIER, BLEND_CONTRACT_VERSION,
        projection, eligibility_entry, execution_profile, certificate, conditions,
        topology_policy, build_ordered_left_fold_schedule(len(conditions)), "",
    )
    plan = replace(plan, fingerprint=fingerprint_translation_plan_v4(plan))
    errors = verify_translation_plan(plan)
    if errors:
        return TranslationResultV4(TranslationStatus.INVALID, None, errors)
    return TranslationResultV4(TranslationStatus.TRANSLATED, plan, _warnings(conditions))


def verify_translation_plan(plan):
    if type(plan) is not TranslationPlanV4:
        return (_error("blend.plan.invalid", "A Translation Plan v4 is required."),)
    errors = []
    try:
        if (plan.format_identifier != TRANSLATION_PLAN_V4_IDENTIFIER
                or type(plan.format_version) is not int or plan.format_version != TRANSLATION_PLAN_V4_VERSION
                or plan.contract_identifier != BLEND_CONTRACT_IDENTIFIER
                or type(plan.contract_version) is not int or plan.contract_version != BLEND_CONTRACT_VERSION
                or fingerprint_translation_plan_v4(plan) != plan.fingerprint):
            errors.append(_error("blend.plan.identity", "Plan identity or declarations disagree."))
        eligibility_errors = verify_blend_eligibility(plan.eligibility_entry)
        errors.extend(eligibility_errors)
        errors.extend(_verify_profile(plan.execution_profile))
        # Only verified authority may govern projection eligibility. Failed
        # authority retains the historical exact-3 diagnostic path, including
        # independent defects; its recorded error still prevents acceptance.
        if eligibility_errors:
            _validate_projection(plan.document_projection)
        else:
            _validate_projection(plan.document_projection, plan.eligibility_entry)
        count = len(plan.document_projection.active_layers)
        if count != plan.eligibility_entry.exact_cardinality or count != len(plan.regional_conditions):
            raise ValueError("exact cardinality")
        if (not exact_contract_equal(plan.document_projection.composition_policy, NORMALIZED_BLEND.reference)
                or not exact_contract_equal(plan.document_projection.composition_policy, plan.eligibility_entry.composition_policy)
                or not exact_contract_equal(plan.document_projection.composition_policy, plan.execution_profile.composition_policy)):
            raise ValueError("policy bindings")
        profiles = tuple(item.field_profile for item in plan.regional_conditions)
        errors.extend(_verify_certificate(plan.document_projection, plan.certificate, profiles, plan.execution_profile))
        if errors:
            return tuple(errors)
        expected = _conditions(plan.document_projection, plan.certificate, profiles, plan.execution_profile)
        if (not exact_contract_equal(plan.regional_conditions, expected)
                or any(item.requested_strength == 0 and math.copysign(1.0, item.requested_strength) < 0
                       for item in plan.regional_conditions)):
            raise ValueError("ordered source conditions")
        if (not exact_contract_equal(plan.topology_policy, ORDERED_LEFT_FOLD_TOPOLOGY_POLICY)
                or not exact_contract_equal(plan.fold_schedule, build_ordered_left_fold_schedule(count))):
            raise ValueError("ordered fold authority")
    except (TypeError, ValueError, AttributeError, IndexError, KeyError, UnicodeError, OverflowError):
        errors.append(_error("blend.plan.invalid", "Plan contains malformed or inconsistent source authority."))
    return tuple(errors)


def _error(code, message):
    return ValidationFinding(code, FindingSeverity.ERROR, message)
