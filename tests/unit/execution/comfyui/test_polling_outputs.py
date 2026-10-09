from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from conditioning_layers.execution.comfyui import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
    ExecutionState,
)
from conditioning_layers.execution.comfyui.errors import ProtocolFailure
from conditioning_layers.execution.comfyui.outputs import associate_outputs
from conditioning_layers.execution.comfyui.polling import poll_until_terminal

from _support import PROMPT_ID, codes, completed_history, make_bundle, save_node_id


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class ScriptedTransport:
    def __init__(self, queues, histories) -> None:
        self.queues = list(queues)
        self.histories = list(histories)
        self.interrupts: list[tuple[str, object]] = []

    def get_json(self, endpoint: str):
        values = self.queues if endpoint == "/queue" else self.histories
        if not values:
            raise ProtocolFailure("execution.connection", "unreachable")
        return values.pop(0) if len(values) > 1 else values[0]

    def post_no_content(self, endpoint: str, payload) -> None:
        self.interrupts.append((endpoint, payload))


def queue(*, running=False, pending=False):
    return {
        "queue_running": [[0, PROMPT_ID]] if running else [],
        "queue_pending": [[0, PROMPT_ID]] if pending else [],
    }


class PollingTests(unittest.TestCase):
    def configuration(self, **overrides):
        values = {
            "polling_interval_seconds": 0.02,
            "total_execution_timeout_seconds": 0.06,
        }
        values.update(overrides)
        return ComfyUIServerConfiguration(**values)

    def test_empty_queue_without_history_waits_for_timeout(self) -> None:
        clock = FakeClock()
        transport = ScriptedTransport([queue()], [{}])
        result = poll_until_terminal(
            transport,
            PROMPT_ID,
            self.configuration(),
            ComfyUIExecutionPolicy(),
            clock=clock.now,
            sleeper=clock.sleep,
        )
        self.assertEqual(result.state, ExecutionState.TIMED_OUT)
        self.assertIn("execution.timed_out", codes(result.errors))
        self.assertEqual(len(clock.sleeps), 3)
        self.assertAlmostEqual(sum(clock.sleeps), 0.06)
        self.assertEqual(transport.interrupts, [])

    def test_prompt_disappearance_is_unknown(self) -> None:
        clock = FakeClock()
        transport = ScriptedTransport([queue(pending=True), queue()], [{}, {}])
        result = poll_until_terminal(
            transport,
            PROMPT_ID,
            self.configuration(),
            ComfyUIExecutionPolicy(),
            clock=clock.now,
            sleeper=clock.sleep,
        )
        self.assertEqual(result.state, ExecutionState.UNKNOWN)
        self.assertIn("execution.history_protocol", codes(result.errors))

    def test_queue_and_history_protocol_mismatches_are_distinct(self) -> None:
        cases = (
            (ScriptedTransport([{}], [{}]), "execution.queue_protocol"),
            (ScriptedTransport([queue()], [[]]), "execution.history_protocol"),
        )
        for transport, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = poll_until_terminal(
                    transport,
                    PROMPT_ID,
                    self.configuration(),
                    ComfyUIExecutionPolicy(),
                    clock=lambda: 0.0,
                    sleeper=lambda seconds: None,
                )
                self.assertEqual(result.state, ExecutionState.UNKNOWN)
                self.assertIn(expected_code, codes(result.errors))

    def test_direct_completed_history_needs_no_queue_presence(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            bundle = make_bundle(Path(root))
            transport = ScriptedTransport([queue()], [completed_history(bundle)])
            result = poll_until_terminal(
                transport,
                PROMPT_ID,
                self.configuration(),
                ComfyUIExecutionPolicy(),
                clock=lambda: 0.0,
                sleeper=lambda seconds: None,
            )
        self.assertEqual(result.state, ExecutionState.COMPLETED)

    def test_prompt_specific_interrupt_only_when_tracked_prompt_is_running(self) -> None:
        clock = FakeClock()
        transport = ScriptedTransport([queue(running=True)], [{}])
        result = poll_until_terminal(
            transport,
            PROMPT_ID,
            self.configuration(),
            ComfyUIExecutionPolicy(permit_prompt_cancellation_on_timeout=True),
            clock=clock.now,
            sleeper=clock.sleep,
        )
        self.assertEqual(result.state, ExecutionState.TIMED_OUT)
        self.assertEqual(transport.interrupts, [("/interrupt", {"prompt_id": PROMPT_ID})])
        self.assertIn("execution.interruption_requested", codes(result.warnings))

    def test_enabled_cancellation_does_not_broadly_interrupt_unproven_prompt(self) -> None:
        clock = FakeClock()
        transport = ScriptedTransport([queue()], [{}])
        result = poll_until_terminal(
            transport,
            PROMPT_ID,
            self.configuration(),
            ComfyUIExecutionPolicy(permit_prompt_cancellation_on_timeout=True),
            clock=clock.now,
            sleeper=clock.sleep,
        )
        self.assertEqual(transport.interrupts, [])
        self.assertIn("execution.cancellation_unsupported", codes(result.warnings))


class OutputAssociationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.bundle = make_bundle(Path(self.temporary.name))
        self.node_id = save_node_id(self.bundle)
        self.policy = ComfyUIExecutionPolicy()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def associate(self, images, *, node_id=None):
        history = {"outputs": {(node_id or self.node_id): {"images": images}}}
        return associate_outputs(history, self.bundle, self.policy)

    def image(self, filename="request-1_00001_.png", subfolder="conditioning-layers/document-1"):
        return {"filename": filename, "subfolder": subfolder, "type": "output"}

    def test_expected_and_multiple_outputs_are_accepted(self) -> None:
        single = self.associate([self.image()])
        multiple = self.associate(
            [self.image(), self.image("request-1_00002_.png")]
        )
        self.assertEqual(len(single.outputs), 1)
        self.assertEqual(len(multiple.outputs), 2)
        self.assertFalse(single.errors)

    def test_wrong_prefix_is_rejected(self) -> None:
        result = self.associate([self.image("other_00001_.png")])
        self.assertIn("execution.output_prefix", codes(result.errors))
        self.assertFalse(result.outputs)

    def test_unsafe_paths_are_rejected(self) -> None:
        images = (
            self.image("request-1_00001_.png", "../outside"),
            self.image("C:/private/request-1_00001_.png", ""),
            self.image("request-1_00001_.png", "http://host"),
        )
        for image in images:
            with self.subTest(image=image):
                result = self.associate([image])
                self.assertIn("execution.output_unsafe", codes(result.errors))

    def test_unexpected_node_and_missing_output_are_rejected(self) -> None:
        unexpected = self.associate([self.image()], node_id="999")
        missing = associate_outputs({"outputs": {}}, self.bundle, self.policy)
        self.assertIn("execution.output_unsafe", codes(unexpected.errors))
        self.assertIn("execution.output_missing", codes(missing.errors))

    def test_duplicate_locator_is_ambiguous(self) -> None:
        image = self.image()
        result = self.associate([image, dict(image)])
        self.assertIn("execution.output_unsafe", codes(result.errors))
        self.assertFalse(result.outputs)


if __name__ == "__main__":
    unittest.main()
