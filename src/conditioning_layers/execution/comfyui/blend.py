"""ADR-0026 Blend-only one-shot client and policy/component-bearing records."""

from __future__ import annotations

from dataclasses import dataclass, fields
import time

from conditioning_layers.comfyui.prediction_mixing import (
    HostNodeContractSnapshot,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.authority import SNAPSHOT
from conditioning_layers.domain import FindingSeverity, ValidationFinding
from conditioning_layers.runtime.comfyui.blend import (
    BlendRuntimeProvenance, BlendSubmissionBundle, SelectedExecutionReferences,
    fingerprint_portable, selected_references, validate_blend_submission_bundle,
    validate_blend_component_availability,
)

from .client import _cleanup_recommendation
from .errors import ProtocolFailure, deduplicate_findings, execution_finding
from .models import (
    AssociatedOutput, CleanupRecommendation, CleanupRecommendationState, ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration, ExecutionState, QueueHistoryObservation,
    ServerIdentityMode, ServerIdentitySnapshot,
)
from .outputs import associate_outputs
from .polling import poll_until_terminal
from .protocol import (
    LocalJsonTransport, establish_server_identity, parse_prompt_id, submission_payload,
    _launch_argument_digest, _validate_local_launch_arguments,
)


EXECUTION_CLIENT_VERSION = "conditioning-layers.comfyui-execution-client.v4"
EXECUTION_PROVENANCE_VERSION = "conditioning-layers.execution-provenance.v4"
EXECUTION_RESULT_VERSION = "conditioning-layers.comfyui-execution-result.v3"


@dataclass(frozen=True, slots=True)
class BlendExecutionProvenance(SelectedExecutionReferences):
    provenance_version: str
    client_version_identifier: str
    document_id: str
    adapter_identifier: str
    translation_plan_fingerprint: str
    graph_fingerprint: str
    bundle_fingerprint: str
    runtime_provenance: object
    server_profile_identifier: str
    server_version: str
    server_revision: str
    server_identity_mode: ServerIdentityMode | None
    reported_server_revision: str | None
    trusted_snapshot_fingerprint: str | None
    live_contract_fingerprint: str | None
    launch_arguments_sha256: str | None
    server_identity_finding_codes: tuple[str, ...]
    prompt_id: str | None
    execution_request_id: str | None
    seed: int
    output_prefix: str
    active_layers: tuple
    field_hashes: tuple[tuple[str, str], ...]
    component_hashes: tuple[tuple[str, str], ...]
    warning_codes: tuple[str, ...]
    terminal_state: ExecutionState
    output_locators: tuple[str, ...]
    execution_error_codes: tuple[str, ...]
    provenance_fingerprint: str


@dataclass(frozen=True, slots=True)
class BlendExecutionResult:
    result_version: str
    bundle_fingerprint: str
    graph_fingerprint: str
    server_identity: ServerIdentitySnapshot | None
    prompt_id: str | None
    terminal_state: ExecutionState
    submitted: bool
    completed: bool
    submission_elapsed_seconds: float | None
    terminal_elapsed_seconds: float
    observations: tuple[QueueHistoryObservation, ...]
    outputs: tuple[AssociatedOutput, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    provenance: BlendExecutionProvenance | None
    cleanup_recommendation: CleanupRecommendation
    result_identity_fingerprint: str


def build_blend_execution_provenance(
    *, bundle: BlendSubmissionBundle,
    server_identity: ServerIdentitySnapshot | None, prompt_id: str | None,
    terminal_state: ExecutionState, outputs: tuple[AssociatedOutput, ...],
    errors: tuple[ValidationFinding, ...], warnings: tuple[ValidationFinding, ...],
) -> BlendExecutionProvenance:
    """Bind verified execution declarations and retain explicit cardinality."""

    if validate_blend_submission_bundle(bundle):
        raise ValueError("Execution provenance requires a completely verified multi-layer bundle")
    runtime = bundle.provenance
    workflow = bundle.graph_artifact.provenance_inputs
    payload = {
        **selected_references(bundle),
        "provenance_version": EXECUTION_PROVENANCE_VERSION,
        "client_version_identifier": EXECUTION_CLIENT_VERSION,
        "document_id": bundle.document_id,
        "adapter_identifier": bundle.adapter_identifier,
        "translation_plan_fingerprint": bundle.translation_plan_fingerprint,
        "graph_fingerprint": bundle.graph_fingerprint,
        "bundle_fingerprint": bundle.bundle_fingerprint,
        "runtime_provenance": runtime,
        "server_profile_identifier": (
            server_identity.profile_identifier if server_identity else runtime.host_profile_identifier
        ),
        "server_version": server_identity.comfyui_version if server_identity else runtime.comfyui_version,
        "server_revision": server_identity.comfyui_revision if server_identity else runtime.comfyui_revision,
        "server_identity_mode": server_identity.identity_mode if server_identity else None,
        "reported_server_revision": server_identity.reported_comfyui_revision if server_identity else None,
        "trusted_snapshot_fingerprint": (
            server_identity.trusted_snapshot_fingerprint if server_identity
            else runtime.node_contract_snapshot_fingerprint
        ),
        "live_contract_fingerprint": server_identity.live_contract_fingerprint if server_identity else None,
        "launch_arguments_sha256": server_identity.launch_arguments_sha256 if server_identity else None,
        "server_identity_finding_codes": server_identity.finding_codes if server_identity else (),
        "prompt_id": prompt_id,
        "execution_request_id": workflow.execution_request_id,
        "seed": runtime.seed,
        "output_prefix": runtime.output_prefix,
        "active_layers": workflow.active_layers,
        "field_hashes": tuple((item.layer_id, item.staged_sha256) for item in runtime.fields),
        "component_hashes": tuple((item.role, item.sha256) for item in runtime.components),
        "warning_codes": tuple(dict.fromkeys(runtime.warning_codes + tuple(item.code for item in warnings))),
        "terminal_state": terminal_state,
        "output_locators": tuple(item.relative_locator for item in outputs),
        "execution_error_codes": tuple(dict.fromkeys(item.code for item in errors)),
    }
    provenance = BlendExecutionProvenance(
        **payload, provenance_fingerprint=fingerprint_portable(payload),
    )
    if validate_blend_execution_provenance(provenance, bundle):
        raise ValueError("Execution evidence disagrees with the selected host or bundle")
    return provenance


def validate_blend_execution_provenance(
    provenance: object, bundle: BlendSubmissionBundle,
) -> tuple[ValidationFinding, ...]:
    """Reject re-signed provenance that disagrees with the selected bundle."""

    if type(provenance) is not BlendExecutionProvenance or validate_blend_submission_bundle(bundle):
        return (_provenance_error(),)
    try:
        payload = {item.name: getattr(provenance, item.name)
                   for item in fields(provenance) if item.name != "provenance_fingerprint"}
        workflow = bundle.graph_artifact.provenance_inputs
        runtime = bundle.provenance
        if (
            provenance.provenance_version != EXECUTION_PROVENANCE_VERSION
            or provenance.client_version_identifier != EXECUTION_CLIENT_VERSION
            or fingerprint_portable(payload) != provenance.provenance_fingerprint
            or fingerprint_portable(selected_references(provenance)) != fingerprint_portable(selected_references(bundle))
            or type(provenance.exact_admitted_cardinality) is not int
            or provenance.document_id != bundle.document_id
            or provenance.adapter_identifier != bundle.adapter_identifier
            or provenance.translation_plan_fingerprint != bundle.translation_plan_fingerprint
            or provenance.graph_fingerprint != bundle.graph_fingerprint
            or provenance.bundle_fingerprint != bundle.bundle_fingerprint
            or type(provenance.runtime_provenance) is not BlendRuntimeProvenance
            or fingerprint_portable(provenance.runtime_provenance) != fingerprint_portable(runtime)
            or type(provenance.active_layers) is not tuple
            or fingerprint_portable(provenance.active_layers) != fingerprint_portable(workflow.active_layers)
            or provenance.execution_request_id != workflow.execution_request_id
            or type(provenance.seed) is not int or provenance.seed != runtime.seed
            or provenance.output_prefix != runtime.output_prefix
            or provenance.field_hashes != tuple((item.layer_id, item.staged_sha256) for item in runtime.fields)
            or provenance.component_hashes != tuple((item.role, item.sha256) for item in runtime.components)
            or provenance.server_profile_identifier != runtime.host_profile_identifier
            or provenance.server_version != runtime.comfyui_version
            or provenance.server_revision != runtime.comfyui_revision
            or provenance.trusted_snapshot_fingerprint != runtime.node_contract_snapshot_fingerprint
            or (provenance.server_identity_mode is not None
                and provenance.launch_arguments_sha256 != _launch_argument_digest(
                    list(bundle.component_availability.launch_arguments)))
            or type(provenance.warning_codes) is not tuple
            or provenance.warning_codes[:len(runtime.warning_codes)] != runtime.warning_codes
            or len(set(provenance.warning_codes)) != len(provenance.warning_codes)
            or any(type(values) is not tuple or any(type(item) is not str for item in values)
                   for values in (provenance.warning_codes, provenance.output_locators,
                                  provenance.execution_error_codes, provenance.server_identity_finding_codes))
            or type(provenance.terminal_state) is not ExecutionState
            or not _valid_server_evidence(provenance)
        ):
            return (_provenance_error(),)
    except (AttributeError, TypeError, ValueError):
        return (_provenance_error(),)
    return ()


def fingerprint_blend_result_identity(provenance: BlendExecutionProvenance) -> str:
    """Successor result identity excludes incidental polling and timing evidence."""

    return fingerprint_portable({
        "result_version": EXECUTION_RESULT_VERSION,
        "provenance_fingerprint": provenance.provenance_fingerprint,
        "bundle_fingerprint": provenance.bundle_fingerprint,
        "graph_fingerprint": provenance.graph_fingerprint,
        "prompt_id": provenance.prompt_id,
        "terminal_state": provenance.terminal_state,
        "output_locators": provenance.output_locators,
        "error_codes": provenance.execution_error_codes,
    })


def execute_blend_submission_bundle(
    bundle: BlendSubmissionBundle, server_config: ComfyUIServerConfiguration,
    execution_policy: ComfyUIExecutionPolicy, *,
    trusted_snapshot: HostNodeContractSnapshot = SNAPSHOT,
) -> BlendExecutionResult:
    """Verify this successor family, submit once, and associate its sole SaveImage."""

    if type(bundle) is not BlendSubmissionBundle:
        raise TypeError("bundle must be a BlendSubmissionBundle")
    if not isinstance(server_config, ComfyUIServerConfiguration):
        raise TypeError("server_config must be a ComfyUIServerConfiguration")
    if not isinstance(execution_policy, ComfyUIExecutionPolicy):
        raise TypeError("execution_policy must be a ComfyUIExecutionPolicy")
    started = time.monotonic()

    def result(
        state=ExecutionState.NOT_SUBMITTED, *, identity=None, prompt_id=None,
        submitted=False, submission_elapsed=None, terminal_elapsed=None,
        observations=(), outputs=(), errors=(), warnings=(), information=(),
    ):
        return _result(
            bundle=bundle, server_identity=identity, prompt_id=prompt_id,
            state=state, submitted=submitted, submission_elapsed=submission_elapsed,
            terminal_elapsed=(time.monotonic() - started if terminal_elapsed is None else terminal_elapsed),
            observations=observations, outputs=outputs, errors=errors,
            warnings=warnings, information=information, policy=execution_policy,
        )

    bundle_errors = validate_blend_submission_bundle(bundle, verify_current_staged_bytes=True)
    if bundle_errors:
        return result(errors=bundle_errors)
    transport = LocalJsonTransport(server_config)
    try:
        identity = establish_server_identity(transport, bundle, trusted_snapshot=trusted_snapshot)
        _verify_target_process(transport, bundle, identity)
    except ProtocolFailure as failure:
        return result(errors=(_protocol_finding(failure),))
    identity_information = tuple(execution_finding(
        code, FindingSeverity.INFORMATION, "Running server identity matched the retained host contract.",
    ) for code in identity.finding_codes)
    # Registration, source, dtype and process state may have changed during the
    # host identity check. Reconcile again immediately before the sole POST.
    availability_errors = validate_blend_component_availability(bundle.component_availability)
    if availability_errors:
        return result(identity=identity, errors=availability_errors, information=identity_information)
    try:
        response = transport.post_json("/prompt", submission_payload(bundle, server_config.client_identifier))
    except ProtocolFailure as failure:
        return result(
            ExecutionState.NOT_SUBMITTED if failure.code == "execution.submission_http" else ExecutionState.UNKNOWN,
            identity=identity, errors=(_protocol_finding(failure),), information=identity_information,
        )
    try:
        prompt_id = parse_prompt_id(response)
    except ProtocolFailure as failure:
        return result(ExecutionState.UNKNOWN, identity=identity,
                      errors=(_protocol_finding(failure),), information=identity_information)
    submission_elapsed = time.monotonic() - started
    polling = poll_until_terminal(
        transport, prompt_id, server_config, execution_policy, started_monotonic=started,
    )
    errors, warnings, information = polling.errors, polling.warnings, identity_information + polling.information
    outputs = ()
    if polling.state is ExecutionState.COMPLETED and polling.history_record is not None:
        association = associate_outputs(polling.history_record, bundle, execution_policy)
        outputs = association.outputs
        errors += association.errors
        warnings += association.warnings
        information += association.information
    return result(
        polling.state, identity=identity, prompt_id=prompt_id, submitted=True,
        submission_elapsed=submission_elapsed, terminal_elapsed=polling.elapsed_seconds,
        observations=polling.observations, outputs=outputs, errors=errors,
        warnings=warnings, information=information,
    )


def _result(
    *, bundle, server_identity, prompt_id, state, submitted, submission_elapsed,
    terminal_elapsed, observations, outputs, errors, warnings, information, policy,
) -> BlendExecutionResult:
    bundle_errors = validate_blend_submission_bundle(bundle)
    if bundle_errors:
        errors += bundle_errors
        if submitted:
            # A terminal host response cannot restore lost project execution
            # authority. Preserve submission evidence without accepting output.
            state, outputs = ExecutionState.UNKNOWN, ()
    errors, warnings, information = map(deduplicate_findings, (errors, warnings, information))
    # Invalid input is preserved as rejection evidence, never promoted to a
    # fabricated reproduction record. No partial execution provenance survives.
    provenance = None
    if not bundle_errors:
        provenance = build_blend_execution_provenance(
            bundle=bundle, server_identity=server_identity, prompt_id=prompt_id,
            terminal_state=state, outputs=outputs, errors=errors, warnings=warnings,
        )
    fingerprint = (
        fingerprint_blend_result_identity(provenance) if provenance is not None
        else fingerprint_portable({
            "result_version": EXECUTION_RESULT_VERSION,
            "state": state, "error_codes": tuple(item.code for item in errors),
            "provenance": None,
        })
    )
    return BlendExecutionResult(
        result_version=EXECUTION_RESULT_VERSION,
        bundle_fingerprint=bundle.bundle_fingerprint, graph_fingerprint=bundle.graph_fingerprint,
        server_identity=server_identity, prompt_id=prompt_id, terminal_state=state,
        submitted=submitted, completed=state is ExecutionState.COMPLETED,
        submission_elapsed_seconds=round(submission_elapsed, 6) if submission_elapsed is not None else None,
        terminal_elapsed_seconds=round(max(0.0, terminal_elapsed), 6), observations=observations,
        outputs=outputs, errors=errors, warnings=warnings, information=information,
        provenance=provenance,
        cleanup_recommendation=(
            _cleanup_recommendation(bundle, state, outputs, errors, policy)
            if provenance is not None else CleanupRecommendation(
                state=CleanupRecommendationState.RETAIN,
                reason_codes=("execution.cleanup_invalid_bundle",), cleanup_plan=None,
            )
        ),
        result_identity_fingerprint=fingerprint,
    )


def _protocol_finding(failure: ProtocolFailure) -> ValidationFinding:
    return execution_finding(failure.code, FindingSeverity.ERROR, failure.message)


def _verify_target_process(transport, bundle: BlendSubmissionBundle, identity: ServerIdentitySnapshot) -> None:
    """Bind local project attestation to the target's actual launch contract.

    The Blend caller must run inside that local host process. No local source
    observation is accepted as proof of code in another host or remote process.
    These unchanged read-only protocol primitives do not qualify generation.
    """

    import sys

    arguments = bundle.component_availability.launch_arguments
    try:
        host_server = getattr(sys.modules.get("server"), "PromptServer", None)
        instance = getattr(host_server, "instance", None)
        if getattr(instance, "port", None) != transport.configuration.port:
            raise ProtocolFailure(
                "execution.blend_target_unverified",
                "Blend execution must target the running local host process that owns the observed registration.",
            )
        local_digest = _validate_local_launch_arguments(list(arguments), transport.configuration)
        payload = transport.get_json("/system_stats")
        system = payload.get("system", {})
        observed_arguments = system.get("argv")
        observed_digest = _validate_local_launch_arguments(observed_arguments, transport.configuration)
    except (AttributeError, TypeError, ValueError) as error:
        raise ProtocolFailure("execution.blend_target_unverified", "Blend target process evidence is unavailable.") from error
    if (identity.launch_arguments_sha256 != local_digest
            or local_digest != observed_digest
            or tuple(observed_arguments) != arguments
            or validate_blend_component_availability(bundle.component_availability)):
        raise ProtocolFailure(
            "execution.blend_target_unverified",
            "Blend component observation does not bind this target's current local process/runtime.",
        )


def _valid_server_evidence(provenance: BlendExecutionProvenance) -> bool:
    def digest(value):
        return type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value)

    mode = provenance.server_identity_mode
    if mode is None:
        return (provenance.reported_server_revision is None
                and provenance.live_contract_fingerprint is None
                and provenance.launch_arguments_sha256 is None
                and not provenance.server_identity_finding_codes
                and provenance.prompt_id is None
                and provenance.terminal_state is ExecutionState.NOT_SUBMITTED)
    if mode is ServerIdentityMode.EXACT_REVISION:
        return (provenance.reported_server_revision == provenance.server_revision
                and provenance.live_contract_fingerprint is None
                and (provenance.launch_arguments_sha256 is None or digest(provenance.launch_arguments_sha256))
                and provenance.server_identity_finding_codes == ("execution.server_identity_exact",))
    if mode is ServerIdentityMode.SEMANTIC_CONTRACT:
        return (provenance.reported_server_revision is None
                and digest(provenance.live_contract_fingerprint)
                and digest(provenance.launch_arguments_sha256)
                and provenance.server_identity_finding_codes == ("execution.server_identity_semantic",))
    return False


def _provenance_error() -> ValidationFinding:
    return execution_finding(
        "execution.blend_provenance_invalid", FindingSeverity.ERROR,
        "Multi-layer provenance disagrees with its selected execution authority or bundle.",
    )
