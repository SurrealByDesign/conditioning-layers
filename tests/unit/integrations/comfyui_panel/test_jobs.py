from __future__ import annotations

import asyncio
from threading import Event, get_ident
import unittest

from conditioning_layers.integrations.comfyui_panel import (
    PanelExecutionDraft,
    PanelJobConflict,
    PanelJobCoordinator,
    PanelLayerDraft,
    PanelRunResult,
    UploadedField,
)

from _support import grayscale_png


def request(key="request-1", prompt="Prompt"):
    return PanelExecutionDraft(
        base_prompt="Base",
        idempotency_key=key,
        layers=(
            PanelLayerDraft(
                row_id="row-a",
                layer_id=None,
                name="Layer A",
                prompt_text=prompt,
                strength=1.0,
                active=True,
                field=UploadedField("field-row-a", "image/png", grayscale_png(255, 0)),
            ),
        ),
    )


class BlockingApplication:
    def __init__(self):
        self.started = Event()
        self.release = Event()
        self.calls = 0
        self.thread_ids = []

    def run(self, draft, execution_id, publish):
        self.calls += 1
        self.thread_ids.append(get_ident())
        publish("executing")
        self.started.set()
        self.release.wait(2)
        return PanelRunResult(state="completed")


class JobCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_key_is_exactly_once_conflict_is_bounded_and_get_is_read_only(self) -> None:
        application = BlockingApplication()
        coordinator = PanelJobCoordinator(application)
        loop = asyncio.get_running_loop()
        loop_thread = get_ident()
        first, created = coordinator.submit(request(), loop)
        self.assertTrue(created)
        await asyncio.to_thread(application.started.wait, 1)

        duplicate, duplicate_created = coordinator.submit(request(), loop)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate.execution_id, first.execution_id)
        with self.assertRaises(PanelJobConflict) as active:
            coordinator.submit(request("request-2"), loop)
        self.assertEqual(active.exception.finding.code, "panel.execution.active")
        with self.assertRaises(PanelJobConflict) as reused:
            coordinator.submit(request(prompt="Changed"), loop)
        self.assertEqual(reused.exception.finding.code, "panel.idempotency.reused")

        for _ in range(5):
            self.assertIsNotNone(coordinator.get(first.execution_id))
        self.assertEqual(application.calls, 1)
        self.assertNotEqual(application.thread_ids, [loop_thread])

        application.release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            snapshot = coordinator.get(first.execution_id)
            if snapshot and snapshot.state == "completed":
                break
        self.assertEqual(snapshot.state, "completed")
        self.assertEqual(application.calls, 1)


if __name__ == "__main__":
    unittest.main()
