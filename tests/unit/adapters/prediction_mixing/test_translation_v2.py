from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing import (
    PREDICTION_MIXING_EXECUTION_PROFILE,
)
from conditioning_layers.adapters.prediction_mixing.v2 import (
    ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
    TranslationStatus,
    build_capability_execution_projection,
    build_document_execution_projection,
    build_execution_profile_projection,
    fingerprint_capability_execution_projection,
    fingerprint_document_execution_projection,
    fingerprint_execution_profile_projection,
    fingerprint_topology_policy,
    fingerprint_translation_plan_v2,
    serialize_document_execution_projection,
    serialize_translation_plan_v2,
    translate_prediction_mixing_v2,
)
from conditioning_layers.assets import (
    FieldRelationshipCertificationStatus,
    FieldRelationshipInput,
    InfluenceFieldBinding,
    InfluenceFieldBindingStatus,
    InfluenceFieldLibrarySelection,
    bind_influence_field_library,
    fingerprint_field_relationship_certificate,
    fingerprint_influence_field_binding,
    inspect_field_relationships,
)
from conditioning_layers.capabilities import evaluate_prediction_mixing
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)


ROOT = Path(__file__).resolve().parents[4]
LIBRARY_ROOT = ROOT / "influence-field-library" / "v1"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _family_record(family_id: str) -> dict[str, object]:
    catalog = _read_json(LIBRARY_ROOT / "library-manifest.json")
    return next(
        item
        for item in catalog["families"]  # type: ignore[index]
        if item["pattern_family_id"] == family_id
    )  # type: ignore[return-value]


def _selection(
    family_id: str,
    permutation_id: str,
) -> InfluenceFieldLibrarySelection:
    record = _family_record(family_id)
    return InfluenceFieldLibrarySelection(
        expected_catalog_sha256=_sha256(
            (LIBRARY_ROOT / "library-manifest.json").read_bytes()
        ),
        family_identifier=family_id,
        family_version=1,
        permutation_identifier=permutation_id,
        expected_family_manifest_sha256=str(record["manifest_sha256"]),
    )


@dataclass(frozen=True, slots=True)
class _Case:
    document: ConditioningDocument
    certificate: object
    binding: InfluenceFieldBinding
    document_projection: object
    capability_projection: object
    profile_projection: object


class TranslationV2Case(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case_number = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_case(
        self,
        *,
        family_id: str = "two-layer.left-right.v1",
        permutation_id: str = "AB",
        include_disabled: bool = False,
        adapter_identifier: str = PREDICTION_MIXING_ADAPTER_ID,
        strengths: tuple[float, ...] | None = None,
    ) -> _Case:
        self.case_number += 1
        record = _family_record(family_id)
        manifest = _read_json(LIBRARY_ROOT / str(record["manifest_filename"]))
        permutation = next(
            item
            for item in manifest["assignment_permutations"]  # type: ignore[index]
            if item["permutation_id"] == permutation_id
        )
        ordered_ids = tuple(permutation["ordered_field_ids"])
        field_map = {
            item["asset_id"]: item
            for item in manifest["fields"]  # type: ignore[index]
        }
        layers: list[PromptLayer] = []
        inputs: list[FieldRelationshipInput] = []
        asset_root = self.root / f"document-{self.case_number}.assets"
        for ordinal, field_id in enumerate(ordered_ids):
            source = LIBRARY_ROOT / str(field_map[field_id]["filename"])
            data = source.read_bytes()
            reference = f"fields/layer-{ordinal}.png"
            destination = asset_root / reference
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            layer = PromptLayer(
                layer_id=f"layer-{ordinal}",
                name=f"Layer {ordinal}",
                prompt_text=f"Regional prompt {ordinal}",
                visible=True,
                strength=(strengths[ordinal] if strengths else 1.0),
                influence_field=InfluenceFieldAssetReference(
                    relative_path=reference,
                    checksum=_sha256(data),
                ),
            )
            document_index = len(layers)
            layers.append(layer)
            inputs.append(
                FieldRelationshipInput(
                    layer=layer,
                    document_index=document_index,
                )
            )
            if include_disabled and ordinal == 0:
                layers.append(
                    PromptLayer(
                        layer_id="disabled-layer",
                        name="Disabled",
                        prompt_text="Stored but not executed.",
                        visible=False,
                        strength=0.25,
                    )
                )
        document = ConditioningDocument(
            version=CURRENT_PROTOTYPE_VERSION,
            document_id=f"document-{self.case_number}",
            base_prompt="A neutral studio scene.",
            layers=tuple(layers),
            selected_adapter_id=adapter_identifier,
        )
        inspected = inspect_field_relationships(asset_root, tuple(inputs))
        self.assertEqual(inspected.errors, ())
        binding_result = bind_influence_field_library(
            LIBRARY_ROOT,
            document,
            _selection(family_id, permutation_id),
            inspected.certificate,
        )
        if adapter_identifier == PREDICTION_MIXING_ADAPTER_ID:
            self.assertEqual(binding_result.errors, ())
            self.assertEqual(
                binding_result.binding.status,
                InfluenceFieldBindingStatus.BOUND,
            )
        document_projection = build_document_execution_projection(document)
        capability_projection = build_capability_execution_projection(
            document,
            document_projection,
        )
        return _Case(
            document=document,
            certificate=inspected.certificate,
            binding=binding_result.binding,
            document_projection=document_projection,
            capability_projection=capability_projection,
            profile_projection=build_execution_profile_projection(),
        )

    def translate(self, case: _Case, **changes: object):
        values = {
            "document": case.document,
            "document_projection": case.document_projection,
            "capability_projection": case.capability_projection,
            "binding": case.binding,
            "certificate": case.certificate,
            "execution_profile_projection": case.profile_projection,
            "topology_policy": ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
        }
        values.update(changes)
        return translate_prediction_mixing_v2(**values)  # type: ignore[arg-type]


class ProjectionContractTests(TranslationV2Case):
    def test_document_projection_is_immutable_and_excludes_non_execution_state(self) -> None:
        case = self.make_case(include_disabled=True)
        projection = case.document_projection
        serialized = serialize_document_execution_projection(projection)  # type: ignore[arg-type]

        self.assertNotIn(case.document.document_id.encode("utf-8"), serialized)
        self.assertNotIn(b"Layer 0", serialized)
        self.assertNotIn(b"disabled-layer", serialized)
        self.assertNotIn(b"Stored but not executed", serialized)
        with self.assertRaises(FrozenInstanceError):
            projection.fingerprint = "0" * 64  # type: ignore[misc,union-attr]

    def test_non_semantic_document_changes_do_not_change_projection(self) -> None:
        case = self.make_case(include_disabled=True)
        layers = list(case.document.layers)
        layers[0] = replace(layers[0], name="Renamed active layer")
        layers[1] = replace(
            layers[1],
            name="Renamed disabled layer",
            prompt_text="Changed disabled prompt.",
            strength=0.9,
        )
        changed = replace(
            case.document,
            document_id="another-document-id",
            layers=tuple(layers),
        )
        self.assertEqual(
            build_document_execution_projection(changed),
            case.document_projection,
        )

    def test_each_execution_semantic_document_change_changes_identity(self) -> None:
        case = self.make_case()
        original = case.document_projection.fingerprint  # type: ignore[union-attr]
        first, second = case.document.layers
        mutations = (
            replace(case.document, base_prompt="Changed Base Prompt"),
            replace(
                case.document,
                layers=(replace(first, prompt_text="Changed prompt"), second),
            ),
            replace(
                case.document,
                layers=(replace(first, strength=0.5), second),
            ),
            replace(
                case.document,
                layers=(
                    replace(
                        first,
                        influence_field=replace(
                            first.influence_field,  # type: ignore[arg-type]
                            relative_path="fields/renamed.png",
                        ),
                    ),
                    second,
                ),
            ),
            replace(
                case.document,
                layers=(
                    replace(
                        first,
                        influence_field=replace(
                            first.influence_field,  # type: ignore[arg-type]
                            checksum="f" * 64,
                        ),
                    ),
                    second,
                ),
            ),
            replace(case.document, layers=(second, first)),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertNotEqual(
                    build_document_execution_projection(mutation).fingerprint,
                    original,
                )

    def test_boolean_strength_is_rejected_before_projection(self) -> None:
        case = self.make_case()
        changed = replace(
            case.document,
            layers=(replace(case.document.layers[0], strength=True), case.document.layers[1]),
        )
        with self.assertRaises(ValueError):
            build_document_execution_projection(changed)

    def test_capability_projection_ignores_prose_and_evaluator_order(self) -> None:
        case = self.make_case()
        real = evaluate_prediction_mixing(case.document)
        changed = replace(
            real,
            warnings=tuple(
                replace(item, message=f"Reworded {index}")
                for index, item in enumerate(reversed(real.warnings))
            ),
            information=tuple(
                replace(item, message=f"Different {index}")
                for index, item in enumerate(reversed(real.information))
            ),
        )
        with patch(
            "conditioning_layers.adapters.prediction_mixing.v2.projections.evaluate_prediction_mixing",
            return_value=changed,
        ):
            projected = build_capability_execution_projection(
                case.document,
                case.document_projection,  # type: ignore[arg-type]
            )
        self.assertEqual(projected, case.capability_projection)

    def test_profile_projection_excludes_hardware_prose_and_capability_maximum(self) -> None:
        changed = replace(
            PREDICTION_MIXING_EXECUTION_PROFILE,
            tested_hardware_note="Different diagnostic prose",
            maximum_active_layers=999,
        )
        self.assertEqual(
            build_execution_profile_projection(changed),
            build_execution_profile_projection(),
        )

    def test_profile_semantic_change_changes_projection_identity(self) -> None:
        changed = replace(
            PREDICTION_MIXING_EXECUTION_PROFILE,
            model_variant="Different model variant",
        )
        self.assertNotEqual(
            build_execution_profile_projection(changed).fingerprint,
            build_execution_profile_projection().fingerprint,
        )


class SuccessfulTranslationTests(TranslationV2Case):
    def test_two_layer_request_produces_complete_deterministic_plan(self) -> None:
        case = self.make_case(strengths=(0.25, 1.0))
        first = self.translate(case)
        second = self.translate(case)

        self.assertEqual(first.status, TranslationStatus.TRANSLATED)
        self.assertIsNotNone(first.plan)
        self.assertEqual(first.plan, second.plan)
        self.assertEqual(
            serialize_translation_plan_v2(first.plan),  # type: ignore[arg-type]
            serialize_translation_plan_v2(second.plan),  # type: ignore[arg-type]
        )
        plan = first.plan
        assert plan is not None
        self.assertEqual(
            plan.fingerprint,
            fingerprint_translation_plan_v2(plan),
        )
        self.assertEqual(
            tuple(item.layer_id for item in plan.regional_conditions),
            ("layer-0", "layer-1"),
        )
        self.assertEqual(
            tuple(item.requested_strength for item in plan.regional_conditions),
            (0.25, 1.0),
        )
        self.assertEqual(
            tuple(item.library_field_id for item in plan.regional_conditions),
            ("A", "B"),
        )
        self.assertEqual(
            plan.regional_conditions[0].combined_prompt_text,
            "A neutral studio scene.\n\nRegional prompt 0",
        )
        self.assertEqual(
            tuple(
                (item.left_operand, item.right_condition, item.result)
                for item in plan.fold_schedule
            ),
            (("condition:0", "condition:1", "fold:0"),),
        )

    def test_plan_is_immutable_and_contains_no_host_or_execution_state(self) -> None:
        result = self.translate(self.make_case())
        plan = result.plan
        assert plan is not None
        with self.assertRaises(FrozenInstanceError):
            plan.fingerprint = "0" * 64  # type: ignore[misc]
        serialized = serialize_translation_plan_v2(plan)
        for forbidden in (
            b"class_type",
            b"node_id",
            b"sampler",
            b"scheduler",
            b"seed",
            b"output_prefix",
            b"queue",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_document_id_layer_names_and_diagnostic_messages_do_not_change_plan(self) -> None:
        case = self.make_case(include_disabled=True)
        baseline = self.translate(case)
        layers = list(case.document.layers)
        layers[0] = replace(layers[0], name="Different display name")
        layers[1] = replace(
            layers[1],
            prompt_text="Different disabled prompt",
            strength=0.75,
        )
        changed_document = replace(
            case.document,
            document_id="different-id",
            layers=tuple(layers),
        )
        changed_document_projection = build_document_execution_projection(
            changed_document
        )
        changed_capability = build_capability_execution_projection(
            changed_document,
            changed_document_projection,
        )
        changed = self.translate(
            case,
            document=changed_document,
            document_projection=changed_document_projection,
            capability_projection=changed_capability,
        )
        self.assertEqual(changed.status, TranslationStatus.TRANSLATED)
        self.assertEqual(changed.plan.fingerprint, baseline.plan.fingerprint)  # type: ignore[union-attr]

    def test_committed_library_has_no_one_field_family(self) -> None:
        catalog = _read_json(LIBRARY_ROOT / "library-manifest.json")
        self.assertNotIn(
            1,
            {item["layer_count"] for item in catalog["families"]},  # type: ignore[index]
        )

    def test_prompt_and_strength_mutations_change_plan_identity(self) -> None:
        case = self.make_case()
        baseline = self.translate(case)
        first, second = case.document.layers
        documents = (
            replace(
                case.document,
                layers=(replace(first, prompt_text="Changed prompt"), second),
            ),
            replace(
                case.document,
                layers=(replace(first, strength=0.5), second),
            ),
        )
        for document in documents:
            with self.subTest(document=document):
                projection = build_document_execution_projection(document)
                capability = build_capability_execution_projection(
                    document,
                    projection,
                )
                result = self.translate(
                    case,
                    document=document,
                    document_projection=projection,
                    capability_projection=capability,
                )
                self.assertEqual(result.status, TranslationStatus.TRANSLATED)
                self.assertNotEqual(
                    result.plan.fingerprint,  # type: ignore[union-attr]
                    baseline.plan.fingerprint,  # type: ignore[union-attr]
                )


class RejectionTests(TranslationV2Case):
    def test_three_valid_layers_are_rejected_by_current_capability(self) -> None:
        case = self.make_case(
            family_id="three-layer.vertical-thirds.v1",
            permutation_id="ABC",
        )
        result = self.translate(case)
        self.assertEqual(result.status, TranslationStatus.REJECTED)
        self.assertIsNone(result.plan)
        self.assertIn("translation.capability_rejected", _codes(result))
        self.assertIn("translation.active_layer_limit", _codes(result))

    def test_unsupported_profile_is_rejected_when_evidence_target_agrees(self) -> None:
        case = self.make_case()
        profile = _refingerprint_profile(
            replace(case.profile_projection, profile_identifier="unsupported.profile.v1")  # type: ignore[arg-type]
        )
        binding = _refingerprint_binding(
            replace(
                case.binding,
                target=replace(
                    case.binding.target,
                    runtime_profile_identifier=profile.profile_identifier,
                ),
            )
        )
        result = self.translate(
            case,
            execution_profile_projection=profile,
            binding=binding,
        )
        self.assertEqual(result.status, TranslationStatus.REJECTED)
        self.assertIn("translation.unsupported_profile", _codes(result))

    def test_unsupported_topology_is_rejected_when_evidence_target_agrees(self) -> None:
        case = self.make_case()
        topology = _refingerprint_topology(
            replace(
                ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
                policy_identifier="prediction-mixing.another-topology.v1",
            )
        )
        binding = _refingerprint_binding(
            replace(
                case.binding,
                target=replace(
                    case.binding.target,
                    topology_policy_identifier=topology.policy_identifier,
                ),
            )
        )
        result = self.translate(case, topology_policy=topology, binding=binding)
        self.assertEqual(result.status, TranslationStatus.REJECTED)
        self.assertIn("translation.unsupported_topology", _codes(result))

    def test_unsupported_adapter_is_rejected_with_consistent_target(self) -> None:
        case = self.make_case()
        document = replace(
            case.document,
            selected_adapter_id="unsupported.adapter.v1",
        )
        document_projection = build_document_execution_projection(document)
        capability = build_capability_execution_projection(
            document,
            document_projection,
        )
        binding = _refingerprint_binding(
            replace(
                case.binding,
                target=replace(
                    case.binding.target,
                    adapter_identifier="unsupported.adapter.v1",
                ),
            )
        )
        result = self.translate(
            case,
            document=document,
            document_projection=document_projection,
            capability_projection=capability,
            binding=binding,
        )
        self.assertEqual(result.status, TranslationStatus.REJECTED)
        self.assertIn("translation.unsupported_adapter", _codes(result))

    def test_zero_active_layers_are_rejected_by_capability(self) -> None:
        case = self.make_case()
        document = replace(
            case.document,
            layers=tuple(replace(layer, visible=False) for layer in case.document.layers),
        )
        document_projection = build_document_execution_projection(document)
        capability = build_capability_execution_projection(
            document,
            document_projection,
        )
        certificate = _refingerprint_certificate(
            replace(case.certificate, ordered_fields=(), pairwise_evidence=())  # type: ignore[arg-type]
        )
        embedded = replace(
            case.binding.certificate,
            fingerprint=certificate.fingerprint,
            ordered_layer_ids=(),
            ordered_source_sha256=(),
        )
        binding = _refingerprint_binding(
            replace(
                case.binding,
                assignments=(),
                certificate=embedded,
                library=replace(case.binding.library, ordered_field_ids=()),
            )
        )
        result = self.translate(
            case,
            document=document,
            document_projection=document_projection,
            capability_projection=capability,
            certificate=certificate,
            binding=binding,
        )
        self.assertEqual(result.status, TranslationStatus.REJECTED)
        self.assertIn("translation.capability_rejected", _codes(result))


class InvalidEvidenceTests(TranslationV2Case):
    def test_document_projection_fingerprint_tampering_is_invalid(self) -> None:
        case = self.make_case()
        result = self.translate(
            case,
            document_projection=replace(
                case.document_projection, fingerprint="0" * 64  # type: ignore[arg-type]
            ),
        )
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.document_projection_malformed", _codes(result))

    def test_document_projection_staleness_is_invalid_even_when_refingerprinted(self) -> None:
        case = self.make_case()
        changed = replace(
            case.document_projection,  # type: ignore[arg-type]
            base_prompt_text="Stale prompt",
            fingerprint="",
        )
        changed = replace(
            changed,
            fingerprint=fingerprint_document_execution_projection(changed),
        )
        result = self.translate(case, document_projection=changed)
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.document_projection_mismatch", _codes(result))

    def test_capability_projection_tampering_is_invalid(self) -> None:
        case = self.make_case()
        result = self.translate(
            case,
            capability_projection=replace(
                case.capability_projection, fingerprint="0" * 64  # type: ignore[arg-type]
            ),
        )
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.capability_projection_mismatch", _codes(result))

    def test_binding_and_certificate_fingerprint_tampering_are_invalid(self) -> None:
        case = self.make_case()
        for changed, code in (
            (
                {"binding": replace(case.binding, fingerprint="0" * 64)},
                "translation.binding_fingerprint_mismatch",
            ),
            (
                {"certificate": replace(case.certificate, fingerprint="0" * 64)},  # type: ignore[arg-type]
                "translation.certificate_fingerprint_mismatch",
            ),
        ):
            with self.subTest(code=code):
                result = self.translate(case, **changed)
                self.assertEqual(result.status, TranslationStatus.INVALID)
                self.assertIn(code, _codes(result))

    def test_unbound_binding_and_uncertified_certificate_are_invalid(self) -> None:
        case = self.make_case()
        unbound = _refingerprint_binding(
            replace(case.binding, status=InfluenceFieldBindingStatus.UNBOUND)
        )
        unbound_result = self.translate(case, binding=unbound)
        self.assertEqual(unbound_result.status, TranslationStatus.INVALID)
        self.assertIn("translation.binding_unbound", _codes(unbound_result))

        uncertified = _refingerprint_certificate(
            replace(
                case.certificate,  # type: ignore[arg-type]
                status=FieldRelationshipCertificationStatus.UNCERTIFIED,
            )
        )
        uncertified_result = self.translate(case, certificate=uncertified)
        self.assertEqual(uncertified_result.status, TranslationStatus.INVALID)
        self.assertIn(
            "translation.certificate_uncertified",
            _codes(uncertified_result),
        )

    def test_certificate_substitution_is_invalid(self) -> None:
        first = self.make_case(permutation_id="AB")
        second = self.make_case(permutation_id="BA")
        result = self.translate(first, certificate=second.certificate)
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.binding_certificate_mismatch", _codes(result))

    def test_reordered_certificate_is_invalid(self) -> None:
        case = self.make_case()
        certificate = _refingerprint_certificate(
            replace(
                case.certificate,  # type: ignore[arg-type]
                ordered_fields=tuple(reversed(case.certificate.ordered_fields)),  # type: ignore[union-attr]
            )
        )
        result = self.translate(case, certificate=certificate)
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertTrue(
            {
                "translation.binding_certificate_mismatch",
                "translation.document_order_mismatch",
            }
            & _codes(result)
        )

    def test_moving_disabled_layer_requires_new_binding_evidence(self) -> None:
        case = self.make_case(include_disabled=True)
        moved = replace(
            case.document,
            layers=(
                case.document.layers[1],
                case.document.layers[0],
                case.document.layers[2],
            ),
        )
        document_projection = build_document_execution_projection(moved)
        self.assertEqual(document_projection, case.document_projection)
        capability = build_capability_execution_projection(moved, document_projection)
        result = self.translate(
            case,
            document=moved,
            document_projection=document_projection,
            capability_projection=capability,
        )
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.document_order_mismatch", _codes(result))

    def test_changed_document_field_reference_and_hash_are_invalid(self) -> None:
        case = self.make_case()
        first, second = case.document.layers
        reference = first.influence_field
        assert isinstance(reference, InfluenceFieldAssetReference)
        mutations = (
            replace(reference, relative_path="fields/different.png"),
            replace(reference, checksum="f" * 64),
        )
        for changed_reference in mutations:
            with self.subTest(reference=changed_reference):
                document = replace(
                    case.document,
                    layers=(
                        replace(first, influence_field=changed_reference),
                        second,
                    ),
                )
                projection = build_document_execution_projection(document)
                capability = build_capability_execution_projection(
                    document,
                    projection,
                )
                result = self.translate(
                    case,
                    document=document,
                    document_projection=projection,
                    capability_projection=capability,
                )
                self.assertEqual(result.status, TranslationStatus.INVALID)
                self.assertIn(
                    "translation.field_identity_mismatch",
                    _codes(result),
                )

    def test_changed_certificate_field_hash_is_invalid(self) -> None:
        case = self.make_case()
        records = list(case.certificate.ordered_fields)  # type: ignore[union-attr]
        records[0] = replace(records[0], source_sha256="f" * 64)
        certificate = _refingerprint_certificate(
            replace(case.certificate, ordered_fields=tuple(records))  # type: ignore[arg-type]
        )
        embedded = replace(
            case.binding.certificate,
            fingerprint=certificate.fingerprint,
            ordered_source_sha256=tuple(
                item.source_sha256 for item in certificate.ordered_fields
            ),
        )
        binding = _refingerprint_binding(
            replace(case.binding, certificate=embedded)
        )
        result = self.translate(
            case,
            certificate=certificate,
            binding=binding,
        )
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.field_identity_mismatch", _codes(result))

    def test_changed_polarity_and_orientation_are_invalid(self) -> None:
        case = self.make_case()
        mutations = (
            replace(
                case.certificate,  # type: ignore[arg-type]
                polarity=replace(
                    case.certificate.polarity,  # type: ignore[union-attr]
                    inverted=True,
                ),
            ),
            replace(
                case.certificate,  # type: ignore[arg-type]
                orientation=replace(
                    case.certificate.orientation,  # type: ignore[union-attr]
                    mirrored_x=True,
                ),
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                certificate = _refingerprint_certificate(mutation)
                embedded = replace(
                    case.binding.certificate,
                    fingerprint=certificate.fingerprint,
                )
                binding = _refingerprint_binding(
                    replace(case.binding, certificate=embedded)
                )
                result = self.translate(
                    case,
                    certificate=certificate,
                    binding=binding,
                )
                self.assertEqual(result.status, TranslationStatus.INVALID)
                self.assertIn(
                    "translation.field_identity_mismatch",
                    _codes(result),
                )

    def test_same_profile_identifier_with_changed_content_is_invalid(self) -> None:
        case = self.make_case()
        profile = _refingerprint_profile(
            replace(case.profile_projection, model_variant="Changed")  # type: ignore[arg-type]
        )
        result = self.translate(case, execution_profile_projection=profile)
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.profile_content_mismatch", _codes(result))

    def test_prompt_policy_drift_is_invalid_and_explicit(self) -> None:
        case = self.make_case()
        profile = _refingerprint_profile(
            replace(case.profile_projection, prompt_combination_delimiter=" ")  # type: ignore[arg-type]
        )
        result = self.translate(case, execution_profile_projection=profile)
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.prompt_policy_mismatch", _codes(result))

    def test_topology_fingerprint_tampering_is_invalid(self) -> None:
        case = self.make_case()
        result = self.translate(
            case,
            topology_policy=replace(
                ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
                fingerprint="0" * 64,
            ),
        )
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.topology_fingerprint_mismatch", _codes(result))

    def test_invalid_evidence_takes_precedence_over_capability_rejection(self) -> None:
        case = self.make_case(
            family_id="three-layer.vertical-thirds.v1",
            permutation_id="ABC",
        )
        result = self.translate(
            case,
            binding=replace(case.binding, fingerprint="0" * 64),
        )
        self.assertEqual(result.status, TranslationStatus.INVALID)
        self.assertIn("translation.binding_fingerprint_mismatch", _codes(result))
        self.assertIn("translation.capability_rejected", _codes(result))


def _codes(result) -> set[str]:
    return {item.code for item in result.findings}


def _refingerprint_binding(binding: InfluenceFieldBinding) -> InfluenceFieldBinding:
    value = replace(binding, fingerprint="")
    return replace(value, fingerprint=fingerprint_influence_field_binding(value))


def _refingerprint_certificate(certificate):
    value = replace(certificate, fingerprint="")
    return replace(
        value,
        fingerprint=fingerprint_field_relationship_certificate(value),
    )


def _refingerprint_profile(profile):
    value = replace(profile, fingerprint="")
    return replace(
        value,
        fingerprint=fingerprint_execution_profile_projection(value),
    )


def _refingerprint_topology(topology):
    value = replace(topology, fingerprint="")
    return replace(value, fingerprint=fingerprint_topology_policy(value))


if __name__ == "__main__":
    unittest.main()
