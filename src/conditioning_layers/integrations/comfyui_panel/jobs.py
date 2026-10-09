"""Minimal in-memory exactly-once coordination for one active panel execution."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Protocol
import uuid

from .models import (
    PanelExecutionDraft,
    PanelFinding,
    PanelRunResult,
)


TERMINAL_STATES = frozenset({"completed", "failed", "rejected"})
MAX_RETAINED_JOBS = 32


class PanelApplication(Protocol):
    def run(
        self,
        draft: PanelExecutionDraft,
        execution_id: str,
        publish_state,
    ) -> PanelRunResult: ...


@dataclass(frozen=True, slots=True)
class PanelJobSnapshot:
    """Bounded read-only state returned by POST and GET routes."""

    execution_id: str
    state: str
    findings: tuple[PanelFinding, ...] = ()
    output: object | None = None
    seed: int | None = None

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "execution_id": self.execution_id,
            "state": self.state,
            "terminal": self.state in TERMINAL_STATES,
            "findings": [finding.to_json() for finding in self.findings],
        }
        if self.seed is not None:
            # A selected run value, including before validation/submission.
            # Decimal text preserves the full ordinary-v1 uint64 range in JS.
            result["seed"] = str(self.seed)
        if self.output is not None:
            result["output"] = self.output.to_json()  # type: ignore[union-attr]
        return result


@dataclass(slots=True)
class _Job:
    execution_id: str
    idempotency_key: str
    request_fingerprint: str
    seed: int
    state: str = "accepted"
    findings: tuple[PanelFinding, ...] = ()
    output: object | None = None

    def snapshot(self) -> PanelJobSnapshot:
        return PanelJobSnapshot(
            execution_id=self.execution_id,
            state=self.state,
            findings=self.findings,
            output=self.output,
            seed=self.seed,
        )


class PanelJobConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.finding = PanelFinding(
            code=code,
            severity="error",
            message=message,
        )


class PanelJobCoordinator:
    """Bind idempotency keys to requests and run accepted work off-loop."""

    def __init__(self, application: PanelApplication) -> None:
        self._application = application
        self._lock = RLock()
        self._jobs_by_id: OrderedDict[str, _Job] = OrderedDict()
        self._jobs_by_key: dict[str, _Job] = {}
        self._active_id: str | None = None
        self._futures: set[asyncio.Future[object]] = set()

    def submit(
        self,
        draft: PanelExecutionDraft,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[PanelJobSnapshot, bool]:
        """Schedule at most one worker call; never await or run it on the loop."""

        with self._lock:
            existing = self._jobs_by_key.get(draft.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != draft.fingerprint:
                    raise PanelJobConflict(
                        "panel.idempotency.reused",
                        "That Generate request key is already bound to different input.",
                    )
                return existing.snapshot(), False
            if self._active_id is not None:
                raise PanelJobConflict(
                    "panel.execution.active",
                    "A Conditioning Layers generation is already active.",
                )
            if len(self._jobs_by_id) >= MAX_RETAINED_JOBS:
                raise PanelJobConflict(
                    "panel.execution.capacity",
                    "The bounded panel execution history is full; restart ComfyUI before generating again.",
                )
            execution_id = uuid.uuid4().hex
            job = _Job(
                execution_id=execution_id,
                idempotency_key=draft.idempotency_key,
                request_fingerprint=draft.fingerprint,
                seed=draft.resolved_seed,
            )
            self._jobs_by_id[execution_id] = job
            self._jobs_by_key[draft.idempotency_key] = job
            self._active_id = execution_id
            future = loop.run_in_executor(
                None,
                self._run_job,
                draft,
                execution_id,
                loop,
            )
            self._futures.add(future)
            future.add_done_callback(self._future_done)
            return job.snapshot(), True

    def get(self, execution_id: str) -> PanelJobSnapshot | None:
        """Return a snapshot without scheduling, submitting, or mutating work."""

        with self._lock:
            job = self._jobs_by_id.get(execution_id)
            return None if job is None else job.snapshot()

    def _run_job(
        self,
        draft: PanelExecutionDraft,
        execution_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        def publish(state: str) -> None:
            loop.call_soon_threadsafe(self._publish_state, execution_id, state)

        try:
            result = self._application.run(draft, execution_id, publish)
        except Exception:
            result = PanelRunResult(
                state="failed",
                findings=(
                    PanelFinding(
                        code="panel.execution.internal",
                        severity="error",
                        message="Conditioning Layers could not complete this request.",
                    ),
                ),
            )
        loop.call_soon_threadsafe(self._finish, execution_id, result)

    def _publish_state(self, execution_id: str, state: str) -> None:
        if state not in {"validating", "preparing", "executing"}:
            return
        with self._lock:
            job = self._jobs_by_id.get(execution_id)
            if job is not None and job.state not in TERMINAL_STATES:
                job.state = state

    def _finish(self, execution_id: str, result: PanelRunResult) -> None:
        with self._lock:
            job = self._jobs_by_id.get(execution_id)
            if job is None:
                return
            job.state = result.state if result.state in TERMINAL_STATES else "failed"
            job.findings = result.findings
            job.output = result.output if job.state == "completed" else None
            if self._active_id == execution_id:
                self._active_id = None

    def _future_done(self, future: asyncio.Future[object]) -> None:
        self._futures.discard(future)
