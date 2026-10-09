"""Minimal execution boundary for one verified ComfyUI submission bundle."""

from __future__ import annotations

import time

from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0280_SUPPORTED_PROFILE,
    HostNodeContractSnapshot,
    fingerprint_api_graph,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding
from conditioning_layers.runtime.comfyui import (
    BUNDLE_VERSION,
    ComfyUISubmissionBundle,
    build_cleanup_plan,
    fingerprint_submission_bundle,
)

from .errors import ProtocolFailure, deduplicate_findings, execution_finding
from .models import (
    EXECUTION_RESULT_VERSION,
    CleanupRecommendation,
    CleanupRecommendationState,
    ComfyUIExecutionPolicy,
    ComfyUIExecutionResult,
    ComfyUIServerConfiguration,
    ExecutionState,
    ServerIdentitySnapshot,
)
from .outputs import associate_outputs
from .polling import poll_until_terminal
from .protocol import (
    LocalJsonTransport,
    establish_server_identity,
    parse_prompt_id,
    submission_payload,
)
from .provenance import build_execution_provenance, fingerprint_result_identity


def execute_submission_bundle(
    bundle: ComfyUISubmissionBundle,
    server_config: ComfyUIServerConfiguration,
    execution_policy: ComfyUIExecutionPolicy,
    *,
    trusted_snapshot: HostNodeContractSnapshot = COMFYUI_0280_SUPPORTED_PROFILE.node_snapshot,
) -> ComfyUIExecutionResult:
    """Submit exactly one verified graph and observe only its queue/history record."""

    if not isinstance(bundle, ComfyUISubmissionBundle):
        raise TypeError("bundle must be a ComfyUISubmissionBundle")
    if not isinstance(server_config, ComfyUIServerConfiguration):
        raise TypeError("server_config must be a ComfyUIServerConfiguration")
    if not isinstance(execution_policy, ComfyUIExecutionPolicy):
        raise TypeError("execution_policy must be a ComfyUIExecutionPolicy")

    started = time.monotonic()
    bundle_errors = _validate_bundle(bundle)
    if bundle_errors:
        return _result(
            bundle=bundle,
            server_identity=None,
            prompt_id=None,
            state=ExecutionState.NOT_SUBMITTED,
            submitted=False,
            submission_elapsed=None,
            terminal_elapsed=time.monotonic() - started,
            observations=(),
            outputs=(),
            errors=bundle_errors,
            warnings=(),
            information=(),
            policy=execution_policy,
        )

    transport = LocalJsonTransport(server_config)
    try:
        identity = establish_server_identity(
            transport, bundle, trusted_snapshot=trusted_snapshot
        )
    except ProtocolFailure as failure:
        return _result(
            bundle=bundle,
            server_identity=None,
            prompt_id=None,
            state=ExecutionState.NOT_SUBMITTED,
            submitted=False,
            submission_elapsed=None,
            terminal_elapsed=time.monotonic() - started,
            observations=(),
            outputs=(),
            errors=(
                execution_finding(
                    failure.code,
                    FindingSeverity.ERROR,
                    failure.message,
                ),
            ),
            warnings=(),
            information=(),
            policy=execution_policy,
        )

    identity_information = tuple(
        execution_finding(
            code,
            FindingSeverity.INFORMATION,
            (
                "The running server matched the exact validated revision."
                if code == "execution.server_identity_exact"
                else "The running server matched the complete trusted semantic contract."
            ),
        )
        for code in identity.finding_codes
    )

    try:
        response = transport.post_json(
            "/prompt",
            submission_payload(bundle, server_config.client_identifier),
        )
    except ProtocolFailure as failure:
        state = (
            ExecutionState.NOT_SUBMITTED
            if failure.code == "execution.submission_http"
            else ExecutionState.UNKNOWN
        )
        return _result(
            bundle=bundle,
            server_identity=identity,
            prompt_id=None,
            state=state,
            submitted=False,
            submission_elapsed=None,
            terminal_elapsed=time.monotonic() - started,
            observations=(),
            outputs=(),
            errors=(
                execution_finding(
                    failure.code,
                    FindingSeverity.ERROR,
                    failure.message,
                ),
            ),
            warnings=(),
            information=identity_information,
            policy=execution_policy,
        )
    try:
        prompt_id = parse_prompt_id(response)
    except ProtocolFailure as failure:
        return _result(
            bundle=bundle,
            server_identity=identity,
            prompt_id=None,
            state=ExecutionState.UNKNOWN,
            submitted=False,
            submission_elapsed=None,
            terminal_elapsed=time.monotonic() - started,
            observations=(),
            outputs=(),
            errors=(
                execution_finding(
                    failure.code,
                    FindingSeverity.ERROR,
                    failure.message,
                ),
            ),
            warnings=(),
            information=identity_information,
            policy=execution_policy,
        )

    submission_elapsed = time.monotonic() - started
    polling = poll_until_terminal(
        transport,
        prompt_id,
        server_config,
        execution_policy,
        started_monotonic=started,
    )
    errors = list(polling.errors)
    warnings = list(polling.warnings)
    information = list(identity_information + polling.information)
    outputs = ()
    if polling.state is ExecutionState.COMPLETED and polling.history_record is not None:
        association = associate_outputs(
            polling.history_record,
            bundle,
            execution_policy,
        )
        outputs = association.outputs
        errors.extend(association.errors)
        warnings.extend(association.warnings)
        information.extend(association.information)
    return _result(
        bundle=bundle,
        server_identity=identity,
        prompt_id=prompt_id,
        state=polling.state,
        submitted=True,
        submission_elapsed=submission_elapsed,
        terminal_elapsed=polling.elapsed_seconds,
        observations=polling.observations,
        outputs=outputs,
        errors=tuple(errors),
        warnings=tuple(warnings),
        information=tuple(information),
        policy=execution_policy,
    )


def _validate_bundle(
    bundle: ComfyUISubmissionBundle,
) -> tuple[ValidationFinding, ...]:
    errors: list[ValidationFinding] = []
    if (
        bundle.bundle_version != BUNDLE_VERSION
        or not bundle.submission_ready
        or bundle.unresolved_runtime_requirements
    ):
        errors.append(
            execution_finding(
                "execution.bundle_not_ready",
                FindingSeverity.ERROR,
                "Only a submission-ready bundle with no unresolved requirements can execute.",
            )
        )
        return tuple(errors)
    graph = bundle.to_api_graph()
    if (
        fingerprint_api_graph(graph) != bundle.graph_fingerprint
        or graph != bundle.graph_artifact.to_api_graph()
        or bundle.graph_artifact.graph_fingerprint != bundle.graph_fingerprint
        or bundle.provenance.graph_fingerprint != bundle.graph_fingerprint
    ):
        errors.append(
            execution_finding(
                "execution.bundle_fingerprint",
                FindingSeverity.ERROR,
                "Bundle graph identity no longer matches its verified artifact.",
            )
        )
    expected_bundle_fingerprint = fingerprint_submission_bundle(
        artifact=bundle.graph_artifact,
        host_snapshot=bundle.host_snapshot,
        components=bundle.verified_components,
        staged_assets=bundle.staged_assets,
        warning_codes=bundle.warnings,
    )
    if (
        expected_bundle_fingerprint != bundle.bundle_fingerprint
        or bundle.provenance.bundle_fingerprint != bundle.bundle_fingerprint
        or bundle.provenance.document_id != bundle.document_id
        or bundle.provenance.translation_plan_fingerprint
        != bundle.translation_plan_fingerprint
        or bundle.provenance.host_profile_identifier != bundle.profile_identifier
    ):
        errors.append(
            execution_finding(
                "execution.bundle_fingerprint",
                FindingSeverity.ERROR,
                "Bundle fingerprint or portable provenance no longer matches verified inputs.",
            )
        )
    if (
        not bundle.host_snapshot.filesystem_verified
        or not bundle.host_snapshot.node_contracts_verified
        or any(not item.verified for item in bundle.verified_components)
        or any(
            not item.successful or item.observed_sha256 != item.expected_sha256
            for item in bundle.staged_assets
        )
    ):
        errors.append(
            execution_finding(
                "execution.bundle_not_ready",
                FindingSeverity.ERROR,
                "Bundle host, components, or staged fields are not fully verified.",
            )
        )
    return deduplicate_findings(errors)


def _result(
    *,
    bundle: ComfyUISubmissionBundle,
    server_identity: ServerIdentitySnapshot | None,
    prompt_id: str | None,
    state: ExecutionState,
    submitted: bool,
    submission_elapsed: float | None,
    terminal_elapsed: float,
    observations: tuple,
    outputs: tuple,
    errors: tuple[ValidationFinding, ...],
    warnings: tuple[ValidationFinding, ...],
    information: tuple[ValidationFinding, ...],
    policy: ComfyUIExecutionPolicy,
) -> ComfyUIExecutionResult:
    errors = deduplicate_findings(errors)
    warnings = deduplicate_findings(warnings)
    information = deduplicate_findings(information)
    provenance = build_execution_provenance(
        bundle=bundle,
        server_identity=server_identity,
        prompt_id=prompt_id,
        terminal_state=state,
        outputs=outputs,
        errors=errors,
        warnings=warnings,
    )
    cleanup = _cleanup_recommendation(
        bundle,
        state,
        outputs,
        errors,
        policy,
    )
    return ComfyUIExecutionResult(
        result_version=EXECUTION_RESULT_VERSION,
        bundle_fingerprint=bundle.bundle_fingerprint,
        graph_fingerprint=bundle.graph_fingerprint,
        server_identity=server_identity,
        prompt_id=prompt_id,
        terminal_state=state,
        submitted=submitted,
        completed=state is ExecutionState.COMPLETED,
        submission_elapsed_seconds=(
            round(submission_elapsed, 6) if submission_elapsed is not None else None
        ),
        terminal_elapsed_seconds=round(max(0.0, terminal_elapsed), 6),
        observations=observations,
        outputs=outputs,
        errors=errors,
        warnings=warnings,
        information=information,
        provenance=provenance,
        cleanup_recommendation=cleanup,
        result_identity_fingerprint=fingerprint_result_identity(provenance),
    )


def _cleanup_recommendation(
    bundle: ComfyUISubmissionBundle,
    state: ExecutionState,
    outputs: tuple,
    errors: tuple[ValidationFinding, ...],
    policy: ComfyUIExecutionPolicy,
) -> CleanupRecommendation:
    if policy.retain_staged_assets:
        return CleanupRecommendation(
            state=CleanupRecommendationState.RETAIN,
            reason_codes=("execution.cleanup_retain_policy",),
            cleanup_plan=None,
        )
    if (
        state is not ExecutionState.COMPLETED
        or not outputs
        or any(item.code.startswith("execution.output_") for item in errors)
        or not policy.recommend_checksum_safe_cleanup
    ):
        return CleanupRecommendation(
            state=CleanupRecommendationState.RETAIN,
            reason_codes=("execution.cleanup_terminal_evidence",),
            cleanup_plan=None,
        )
    plan = build_cleanup_plan(bundle)
    if plan.errors or not plan.items:
        return CleanupRecommendation(
            state=CleanupRecommendationState.NOT_ELIGIBLE,
            reason_codes=("execution.cleanup_not_eligible",),
            cleanup_plan=plan,
        )
    return CleanupRecommendation(
        state=CleanupRecommendationState.REVIEW_CHECKSUM_SAFE_PLAN,
        reason_codes=("execution.cleanup_review_required",),
        cleanup_plan=plan,
    )
