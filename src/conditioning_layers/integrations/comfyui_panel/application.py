"""Thin Slice 10A orchestration over the existing validated backend APIs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
import tempfile
from urllib.parse import urlencode

from conditioning_layers.adapters.prediction_mixing import (
    translate_prediction_mixing,
)
from conditioning_layers.assets import (
    FieldRelationshipInput,
    inspect_field_relationships,
    inspect_field_asset,
    inspect_field_pair,
    to_field_asset_profile,
    to_overlap_assessment,
)
from conditioning_layers.capabilities import evaluate_prediction_mixing
from conditioning_layers.capabilities.multi_layer import (
    MULTI_LAYER_CONTRACT_IDENTIFIER,
    ORDINARY_V1_CONTRACT_IDENTIFIER,
)
from conditioning_layers.capabilities.product import BLEND_CONTRACT_IDENTIFIER, route_product_prediction_mixing
from conditioning_layers.comfyui.prediction_mixing import (
    DEFAULT_SUPPORTED_PROFILE,
    CompatibilityProfile,
    FieldStagingMap,
    RuntimeGenerationSettings,
    generate_prediction_mixing_workflow,
)
from conditioning_layers.domain import (
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    ValidationFinding,
    validate_document,
)
from conditioning_layers.execution.comfyui import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
    execute_submission_bundle,
)
from conditioning_layers.persistence import document_asset_root
from conditioning_layers.runtime.comfyui import (
    ComfyUIHostConfiguration,
    prepare_submission_bundle,
    staging_namespace_for_document,
)

from .models import (
    PanelExecutionDraft,
    PanelFinding,
    PanelOutput,
    PanelRunResult,
    project_findings,
    RetainedField,
)
from .documents import PanelDocumentError, PanelDocumentStore
from .guidance import project_product_warnings


StatePublisher = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class PanelHostContext:
    """Explicit local host inputs supplied by the ComfyUI loader boundary."""

    host_configuration: ComfyUIHostConfiguration
    server_configuration: ComfyUIServerConfiguration
    execution_policy: ComfyUIExecutionPolicy


@dataclass(frozen=True, slots=True)
class MaterializedPanelDocument:
    """Canonical document and document-owned temporary asset location."""

    document: ConditioningDocument
    document_path: Path
    asset_root: Path
    layer_labels: dict[str, str]


@dataclass(frozen=True, slots=True)
class PreparedPanelExecution:
    """Real submission readiness, reusable by governed offline qualification."""

    bundle: object
    layer_labels: dict[str, str]
    warnings: tuple[ValidationFinding, ...]
    multi_layer: bool
    route_identifier: str = ORDINARY_V1_CONTRACT_IDENTIFIER


class ExistingBackendApplication:
    """Map one panel request through existing validation and execution APIs."""

    def __init__(
        self,
        host: PanelHostContext,
        *,
        compatibility: CompatibilityProfile = DEFAULT_SUPPORTED_PROFILE,
        execution_client: Callable[..., object] = execute_submission_bundle,
        qualification_entry: object | None = None,
    ) -> None:
        self._host = host
        self.compatibility = compatibility
        self._execution_client = execution_client
        # In-process governed selection only; never a request or UI setting.
        self._qualification_entry = qualification_entry

    def prepare(
        self,
        draft: PanelExecutionDraft,
        execution_id: str,
        publish_state: StatePublisher,
    ) -> PreparedPanelExecution | PanelRunResult:
        """Validate and stage once without contacting or submitting to a server."""

        publish_state("validating")
        if self._host.server_configuration.port != 8000:
            return _rejected(
                _panel_error(
                    "panel.host.port",
                    "Conditioning Layers requires the validated loopback port 8000 profile.",
                )
            )

        with tempfile.TemporaryDirectory(prefix="conditioning-layers-panel-") as root:
            try:
                materialized = materialize_document(
                    draft,
                    execution_id,
                    Path(root),
                    PanelDocumentStore(self._host.host_configuration.user_directory),
                )
            except PanelDocumentError as error:
                return _rejected(error.finding)
            document = materialized.document
            labels = materialized.layer_labels

            domain_findings = validate_document(document)
            if _has_errors(domain_findings):
                return PanelRunResult(
                    state="rejected",
                    findings=project_findings(domain_findings, labels),
                )

            route = route_product_prediction_mixing(
                document, qualification_entry=self._qualification_entry,
            )
            if not route.compatible:
                return PanelRunResult(
                    state="rejected", findings=project_findings(route.errors, labels),
                )
            if route.contract_identifier == BLEND_CONTRACT_IDENTIFIER:
                from .blend_application import prepare_blend
                return prepare_blend(self, materialized, draft, execution_id, publish_state, route)
            if route.contract_identifier == MULTI_LAYER_CONTRACT_IDENTIFIER:
                return self._prepare_multi_layer(
                    materialized, draft, execution_id, publish_state, route,
                )

            capability = evaluate_prediction_mixing(document)
            if not capability.compatible:
                return PanelRunResult(
                    state="rejected",
                    findings=project_findings(capability.errors, labels),
                )

            active_layers = document.active_layers
            if len(active_layers) == 1:
                inspection = inspect_field_asset(
                    materialized.asset_root,
                    active_layers[0],
                )
                field_inspections = (inspection,)
                asset_errors = inspection.errors
                overlap_assessment = None
            else:
                # The authoritative capability gate above makes this exactly two.
                # This branch is the frozen pairwise v1 inspection path, not a
                # second product-policy decision.
                pair = inspect_field_pair(
                    materialized.asset_root,
                    active_layers[0],
                    active_layers[1],
                )
                field_inspections = pair.fields
                asset_errors = tuple(
                    finding
                    for inspection in pair.fields
                    for finding in inspection.errors
                ) + pair.overlap.errors
                overlap_assessment = to_overlap_assessment(pair.overlap)
            if asset_errors or not all(item.certified for item in field_inspections):
                return PanelRunResult(
                    state="rejected",
                    findings=project_findings(asset_errors, labels)
                    or (_panel_error("panel.field.invalid", "An active Influence Field is invalid."),),
                )

            profiles = tuple(to_field_asset_profile(item) for item in field_inspections)
            if any(item is None for item in profiles):
                return _rejected(
                    _panel_error(
                        "panel.field.profile",
                        "An active Influence Field could not be certified for execution.",
                    )
                )
            translated = translate_prediction_mixing(
                document,
                profiles,  # type: ignore[arg-type]
                overlap_assessment=overlap_assessment,
            )
            if not translated.translated or translated.plan is None:
                return PanelRunResult(
                    state="rejected",
                    findings=project_findings(translated.errors, labels),
                )

            plan = translated.plan
            namespace = staging_namespace_for_document(document.document_id)
            staging = FieldStagingMap(
                {
                    layer.layer_id: f"{namespace}/{layer.layer_id}.png"
                    for layer in active_layers
                }
            )
            settings = RuntimeGenerationSettings(
                seed=draft.resolved_seed,
                output_filename_prefix=f"conditioning-layers-panel/{execution_id}",
                execution_request_id=execution_id,
            )
            generated = generate_prediction_mixing_workflow(
                plan,
                self.compatibility.inventory,
                settings,
                staging,
            )
            if not generated.generated or generated.artifact is None:
                return PanelRunResult(
                    state="rejected",
                    findings=project_findings(generated.errors, labels),
                )

            publish_state("preparing")
            prepared = prepare_submission_bundle(
                generated.artifact,
                generated.artifact.provenance_inputs,
                self.compatibility.inventory,
                self._host.host_configuration,
                field_inspections,
                materialized.asset_root,
                self.compatibility.node_snapshot,
            )
            if not prepared.ready or prepared.bundle is None:
                return PanelRunResult(
                    state="rejected",
                    findings=project_findings(prepared.errors, labels),
                )

            return PreparedPanelExecution(prepared.bundle, labels, capability.warnings, False)

    def _prepare_multi_layer(self, materialized, draft, execution_id, publish_state, route):
        from conditioning_layers.adapters.prediction_mixing.multi_layer import translate_prediction_mixing_multi_layer
        from conditioning_layers.comfyui.prediction_mixing.multi_layer import (
            generate_prediction_mixing_multi_layer_workflow, select_realization_binding,
        )
        from conditioning_layers.runtime.comfyui.multi_layer import prepare_multi_layer_submission_bundle

        document, labels = materialized.document, materialized.layer_labels
        inspected = inspect_field_relationships(
            materialized.asset_root,
            tuple(FieldRelationshipInput(layer, index) for index, layer in enumerate(document.layers) if layer.visible),
        )
        field_profiles = tuple(to_field_asset_profile(item) for item in inspected.fields)
        translated = translate_prediction_mixing_multi_layer(
            document, inspected.certificate, field_profiles, eligibility_entry=route.eligibility_entry,
        )
        if not translated.translated or translated.plan is None:
            return PanelRunResult(state="rejected", findings=project_findings(translated.errors, labels))
        namespace = staging_namespace_for_document(document.document_id)
        staging = FieldStagingMap({layer.layer_id: f"{namespace}/{layer.layer_id}.png" for layer in document.active_layers})
        settings = RuntimeGenerationSettings(
            seed=draft.resolved_seed, output_filename_prefix=f"conditioning-layers-panel/{execution_id}",
            execution_request_id=execution_id,
        )
        generated = generate_prediction_mixing_multi_layer_workflow(
            translated.plan, self.compatibility.inventory, settings, staging,
            document_id=document.document_id,
            disabled_layer_ids=tuple(layer.layer_id for layer in document.layers if not layer.visible),
            # Exact registered-host selection; an unbound host is rejected, never rebound.
            binding=select_realization_binding(translated.plan.eligibility_entry, self.compatibility),
        )
        if not generated.generated:
            return PanelRunResult(state="rejected", findings=project_findings(generated.errors, labels))
        publish_state("preparing")
        prepared = prepare_multi_layer_submission_bundle(
            generated.artifact, generated.artifact.provenance_inputs,
            self.compatibility.inventory, self._host.host_configuration,
            inspected.fields, materialized.asset_root, self.compatibility.node_snapshot,
        )
        if not prepared.ready or prepared.bundle is None:
            return PanelRunResult(state="rejected", findings=project_findings(prepared.errors, labels))
        return PreparedPanelExecution(prepared.bundle, labels, translated.warnings, True, MULTI_LAYER_CONTRACT_IDENTIFIER)

    def run(self, draft, execution_id, publish_state) -> PanelRunResult:
        """Prepare through the same route, then execute exactly once."""
        prepared = self.prepare(draft, execution_id, publish_state)
        if isinstance(prepared, PanelRunResult):
            return prepared
        if prepared.route_identifier == BLEND_CONTRACT_IDENTIFIER:
            from .blend_application import execute_blend
            return execute_blend(self, prepared, execution_id, publish_state)
        labels = prepared.layer_labels
        client = self._execution_client
        if prepared.multi_layer and client is execute_submission_bundle:
            from conditioning_layers.execution.comfyui.multi_layer import execute_multi_layer_submission_bundle
            client = execute_multi_layer_submission_bundle
        return self._execute_prepared(prepared, client, labels, publish_state)

    def _execute_prepared(self, prepared, client, labels, publish_state):
        # The retained output projection is shared; contract validation belongs
        # to the selected client and is never retried via another family.
        if prepared.bundle is not None:
            publish_state("executing")
            execution = client(
                prepared.bundle,
                self._host.server_configuration,
                self._host.execution_policy,
                trusted_snapshot=self.compatibility.node_snapshot,
            )
            execution_errors = tuple(getattr(execution, "errors", ()))
            if not getattr(execution, "completed", False):
                findings = project_findings(execution_errors, labels)
                if not findings:
                    terminal = getattr(
                        getattr(execution, "terminal_state", None),
                        "value",
                        "failed",
                    )
                    findings = (
                        _panel_error(
                            "panel.execution.terminal",
                            f"ComfyUI execution ended in state {terminal}.",
                        ),
                    )
                return PanelRunResult(state="failed", findings=findings)

            outputs = tuple(getattr(execution, "outputs", ()))
            if not outputs:
                return _rejected(
                    _panel_error(
                        "panel.output.missing",
                        "ComfyUI completed without a safely associated image output.",
                    )
                )
            output = outputs[0]
            if (
                len(output.filename) > 255
                or len(output.subfolder) > 768
                or output.storage_type != "output"
            ):
                return _rejected(
                    _panel_error(
                        "panel.output.unsafe",
                        "ComfyUI returned output metadata that cannot be projected safely.",
                    )
                )
            projected_output = PanelOutput(
                filename=output.filename,
                subfolder=output.subfolder,
                storage_type=output.storage_type,
                view_url="/view?"
                + urlencode(
                    {
                        "filename": output.filename,
                        "subfolder": output.subfolder,
                        "type": output.storage_type,
                    }
                ),
            )
            return PanelRunResult(
                state="completed",
                findings=project_product_warnings(prepared.warnings, labels),
                output=projected_output,
            )


def materialize_document(
    draft: PanelExecutionDraft,
    execution_id: str,
    temporary_root: Path,
    document_store: PanelDocumentStore | None = None,
) -> MaterializedPanelDocument:
    """Create canonical intent and bounded document-owned assets from uploads."""

    if draft.document_key is not None:
        if document_store is None:
            raise PanelDocumentError("panel.document.field_ownership", "An opened source requires its document store.", status=409)
        document_store.validate_execution_source(draft)

    document_path = temporary_root / "panel.conditioning.json"
    asset_root = document_asset_root(document_path)
    fields_root = asset_root / "fields"
    fields_root.mkdir(parents=True, exist_ok=False)
    layers: list[PromptLayer] = []
    labels: dict[str, str] = {}
    used_layer_ids: set[str] = set()
    reserved_layer_ids = {row.layer_id for row in draft.layers if row.layer_id is not None}
    for index, row in enumerate(draft.layers, start=1):
        layer_id = row.layer_id
        if layer_id is None:
            layer_id = f"panel-{row.row_id}"
            while layer_id in used_layer_ids or layer_id in reserved_layer_ids:
                layer_id = f"{layer_id}-{index}"
        used_layer_ids.add(layer_id)
        relative_path = f"fields/{layer_id}.png"
        if isinstance(row.field, RetainedField):
            if document_store is None or draft.document_key is None:
                raise PanelDocumentError(
                    "panel.document.field_ownership",
                    "A retained Influence Field requires an opened document.",
                    status=409,
                )
            field_data = document_store.resolve_execution_field(
                draft.document_key,
                draft.document_id,
                row.field.layer_id,
                composition_policy=draft.composition_policy,
            )
        else:
            field_data = row.field.data
        checksum = hashlib.sha256(field_data).hexdigest()
        (fields_root / f"{layer_id}.png").write_bytes(field_data)
        layers.append(
            PromptLayer(
                layer_id=layer_id,
                name=row.name,
                prompt_text=row.prompt_text,
                visible=row.active,
                strength=row.strength,
                influence_field=InfluenceFieldAssetReference(
                    relative_path=relative_path,
                    checksum=checksum,
                ),
            )
        )
        labels[layer_id] = row.name or f"Layer {index}"
    return MaterializedPanelDocument(
        document=ConditioningDocument(
            version=draft.document_version,
            composition_policy=draft.composition_policy,
            document_id=draft.document_id or f"panel-{execution_id}",
            base_prompt=draft.base_prompt,
            layers=tuple(layers),
            selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID,
            adapter_settings={},
        ),
        document_path=document_path,
        asset_root=asset_root,
        layer_labels=labels,
    )


def _has_errors(findings: Sequence[ValidationFinding]) -> bool:
    return any(finding.severity is FindingSeverity.ERROR for finding in findings)


def _panel_error(code: str, message: str) -> PanelFinding:
    return PanelFinding(
        code=code,
        severity=FindingSeverity.ERROR.value,
        message=message,
    )


def _rejected(*findings: PanelFinding) -> PanelRunResult:
    return PanelRunResult(state="rejected", findings=tuple(findings))
