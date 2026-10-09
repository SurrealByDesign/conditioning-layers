"""Deterministic queue/history polling with explicit terminal evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import time

from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .errors import ProtocolFailure, execution_finding
from .models import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
    ExecutionState,
    QueueHistoryObservation,
)
from .protocol import (
    LocalJsonTransport,
    history_endpoint,
    parse_history_record,
    parse_queue_presence,
)


@dataclass(frozen=True, slots=True)
class PollingResult:
    state: ExecutionState
    observations: tuple[QueueHistoryObservation, ...]
    history_record: Mapping[str, object] | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    elapsed_seconds: float


def poll_until_terminal(
    transport: LocalJsonTransport,
    prompt_id: str,
    configuration: ComfyUIServerConfiguration,
    policy: ComfyUIExecutionPolicy,
    *,
    started_monotonic: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> PollingResult:
    """Poll only queue and prompt-specific history; queue emptiness is never success."""

    started = clock() if started_monotonic is None else started_monotonic
    observations: list[QueueHistoryObservation] = []
    seen_in_queue = False
    last_running = False
    sequence = 0
    while True:
        elapsed = max(0.0, clock() - started)
        if elapsed >= configuration.total_execution_timeout_seconds:
            return _timed_out(
                transport,
                prompt_id,
                policy,
                last_running,
                observations,
                elapsed,
            )
        try:
            running, pending = parse_queue_presence(
                transport.get_json("/queue"), prompt_id
            )
            history = parse_history_record(
                transport.get_json(history_endpoint(prompt_id)), prompt_id
            )
        except ProtocolFailure as failure:
            return PollingResult(
                state=ExecutionState.UNKNOWN,
                observations=tuple(observations),
                history_record=None,
                errors=(
                    execution_finding(
                        failure.code,
                        FindingSeverity.ERROR,
                        failure.message,
                    ),
                ),
                warnings=(),
                information=(),
                elapsed_seconds=max(0.0, clock() - started),
            )

        last_running = running
        seen_in_queue = seen_in_queue or running or pending
        state, history_status = _observed_state(running, pending, history)
        observations.append(
            QueueHistoryObservation(
                sequence=sequence,
                elapsed_seconds=round(elapsed, 6),
                state=state,
                in_running_queue=running,
                in_pending_queue=pending,
                history_present=history is not None,
                history_status=history_status,
            )
        )
        sequence += 1

        if history is not None:
            terminal = _terminal_history_state(history)
            if terminal is ExecutionState.COMPLETED:
                return PollingResult(
                    state=terminal,
                    observations=tuple(observations),
                    history_record=history,
                    errors=(),
                    warnings=(),
                    information=(
                        execution_finding(
                            "execution.completed",
                            FindingSeverity.INFORMATION,
                            "ComfyUI history reports successful completion.",
                        ),
                    ),
                    elapsed_seconds=max(0.0, clock() - started),
                )
            if terminal in {ExecutionState.FAILED, ExecutionState.INTERRUPTED}:
                code = (
                    "execution.interrupted"
                    if terminal is ExecutionState.INTERRUPTED
                    else "execution.failed"
                )
                return PollingResult(
                    state=terminal,
                    observations=tuple(observations),
                    history_record=history,
                    errors=(
                        execution_finding(
                            code,
                            FindingSeverity.ERROR,
                            "ComfyUI history reports interrupted execution."
                            if terminal is ExecutionState.INTERRUPTED
                            else "ComfyUI history reports execution failure.",
                        ),
                    ),
                    warnings=(),
                    information=(),
                    elapsed_seconds=max(0.0, clock() - started),
                )
            return PollingResult(
                state=ExecutionState.UNKNOWN,
                observations=tuple(observations),
                history_record=history,
                errors=(
                    execution_finding(
                        "execution.history_protocol",
                        FindingSeverity.ERROR,
                        "Prompt history exists without terminal status evidence.",
                    ),
                ),
                warnings=(),
                information=(),
                elapsed_seconds=max(0.0, clock() - started),
            )

        if seen_in_queue and not running and not pending:
            return PollingResult(
                state=ExecutionState.UNKNOWN,
                observations=tuple(observations),
                history_record=None,
                errors=(
                    execution_finding(
                        "execution.history_protocol",
                        FindingSeverity.ERROR,
                        "Tracked prompt disappeared from the queue without terminal history.",
                    ),
                ),
                warnings=(),
                information=(),
                elapsed_seconds=max(0.0, clock() - started),
            )
        remaining = configuration.total_execution_timeout_seconds - max(
            0.0, clock() - started
        )
        sleeper(min(configuration.polling_interval_seconds, max(0.0, remaining)))


def _observed_state(
    running: bool,
    pending: bool,
    history: Mapping[str, object] | None,
) -> tuple[ExecutionState, str | None]:
    if history is not None:
        status = history.get("status")
        status_name = status.get("status_str") if isinstance(status, Mapping) else None
        return _terminal_history_state(history), status_name if isinstance(status_name, str) else None
    if running:
        return ExecutionState.RUNNING, None
    if pending:
        return ExecutionState.QUEUED, None
    return ExecutionState.UNKNOWN, None


def _terminal_history_state(history: Mapping[str, object]) -> ExecutionState:
    status = history.get("status")
    if not isinstance(status, Mapping):
        return ExecutionState.UNKNOWN
    status_name = status.get("status_str")
    completed = status.get("completed")
    if status_name == "success" and completed is True:
        return ExecutionState.COMPLETED
    if status_name == "error":
        serialized = json.dumps(status.get("messages", []), ensure_ascii=False).casefold()
        if "interrupt" in serialized:
            return ExecutionState.INTERRUPTED
        return ExecutionState.FAILED
    return ExecutionState.UNKNOWN


def _timed_out(
    transport: LocalJsonTransport,
    prompt_id: str,
    policy: ComfyUIExecutionPolicy,
    running: bool,
    observations: list[QueueHistoryObservation],
    elapsed: float,
) -> PollingResult:
    warnings: tuple[ValidationFinding, ...] = ()
    if policy.permit_prompt_cancellation_on_timeout and running:
        try:
            transport.post_no_content("/interrupt", {"prompt_id": prompt_id})
            warnings = (
                execution_finding(
                    "execution.interruption_requested",
                    FindingSeverity.WARNING,
                    "A prompt-specific interrupt was requested after timeout.",
                ),
            )
        except ProtocolFailure as failure:
            warnings = (
                execution_finding(
                    failure.code,
                    FindingSeverity.WARNING,
                    "Prompt-specific interruption could not be confirmed.",
                ),
            )
    elif policy.permit_prompt_cancellation_on_timeout:
        warnings = (
            execution_finding(
                "execution.cancellation_unsupported",
                FindingSeverity.WARNING,
                "No prompt-specific interrupt was attempted because the tracked prompt was not proven active.",
            ),
        )
    return PollingResult(
        state=ExecutionState.TIMED_OUT,
        observations=tuple(observations),
        history_record=None,
        errors=(
            execution_finding(
                "execution.timed_out",
                FindingSeverity.ERROR,
                "Execution did not reach terminal history before the bounded timeout.",
            ),
        ),
        warnings=warnings,
        information=(),
        elapsed_seconds=elapsed,
    )
