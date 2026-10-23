"""Bounded P2B offline suites: no network, host, browser, or execution submission.

Retained Python identity/import probes inherit the existing offline fences.
Panel JavaScript checks run only inline Node.js fixtures with network and child
process APIs fenced before the fixture loads; no browser process is admitted.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import ExitStack
import json
import selectors
import subprocess
import sys
from threading import Event
import unittest
from unittest.mock import patch

from offline_regressions import FENCES, ROOT, fence, python_probe_launcher


GROUPS = {
    "composition-preview": ("integrations", ("test_composition_preview.py", "test_composition_preview_groups.py")),
    "hotdog-template": ("integrations", ("test_field_editor_hotdog.py",)),
    "field-editor": ("integrations", ("test_field_editor_frontend.py", "test_field_editor_brush_engine.py",
                                      "test_field_editor_value_profile.py", "test_field_editor_custom_tip.py",
                                      "test_field_editor_brush_library.py", "test_field_editor_procedural_tip.py",
                                      "test_field_editor_field_tools.py", "test_field_editor_pressure.py",
                                      "test_field_editor_multi_field.py", "test_field_editor_transfer.py",
                                      "test_field_editor_balance.py", "test_field_editor_brush_dynamics.py")),
    "domain": ("domain", ("test_*.py",)),
    "capabilities": ("capabilities", ("test_*.py",)),
    "translation": ("adapters/prediction_mixing", ("test_*.py",)),
    "assets": ("assets", ("test_*.py",)),
    "persistence": ("persistence", ("test_*.py",)),
    "runtime": ("runtime/comfyui", ("test_*.py",)),
    "goldens": ("runtime/comfyui", ("test_historical_identities.py",)),
    "panel": ("integrations/comfyui_panel", ("test_*.py",)),
    "application-multi": ("integrations/comfyui_panel", ("test_multi_layer_application.py",)),
    "library": ("influence_field_library", ("test_*.py",)),
    "graph": ("comfyui/prediction_mixing", (
        "test_graph.py", "test_validation.py", "test_node_contracts.py",
        "test_profiles.py",
        "test_compatibility_registry.py", "test_architecture.py",
        "test_multi_layer*.py",
    )),
}

NODE_FENCE = """
import { syncBuiltinESMExports } from 'node:module';
const deny = () => { throw new Error('P2B offline fence: network/process prohibited'); };
for (const [name, methods] of [
  ['net', ['connect', 'createConnection', 'createServer']],
  ['tls', ['connect', 'createServer']],
  ['http', ['request', 'get', 'createServer']],
  ['https', ['request', 'get', 'createServer']],
  ['http2', ['connect', 'createServer', 'createSecureServer']],
  ['dgram', ['createSocket']],
  ['dns', ['lookup', 'resolve']],
  ['child_process', ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']],
]) {
  const api = (await import(`node:${name}`)).default;
  for (const method of methods) api[method] = deny;
}
const net = (await import('node:net')).default;
net.Socket.prototype.connect = deny;
net.Server.prototype.listen = deny;
globalThis.fetch = deny;
globalThis.WebSocket = class { constructor() { deny(); } };
syncBuiltinESMExports();
"""


class MemoryWakeupSelector(selectors.BaseSelector):
    """Async fixture scheduler with a thread wakeup and no OS I/O handles."""

    def __init__(self):
        self.wakeup = Event()

    register = unregister = modify = fence

    def select(self, timeout=None):
        self.wakeup.wait(timeout)
        self.wakeup.clear()
        return []

    def get_map(self):
        return {}


class MemoryWakeupLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        super().__init__(MemoryWakeupSelector())

    def _make_self_pipe(self):
        self._ssock = self._csock = None

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        if self._selector is not None:
            self._selector.wakeup.set()


def offline_probe_launcher(original, *, allow_node):
    python = python_probe_launcher(original)

    def launch(command, *args, **kwargs):
        if (allow_node and isinstance(command, list)
                and command[:2] == ["node", "--input-type=module"]
                and (len(command) == 2 or (len(command) == 4 and command[2] == "-e"))
                and not kwargs.get("shell")):
            encoded = base64.b64encode(NODE_FENCE.encode()).decode("ascii")
            fenced = [command[0], "--import", f"data:text/javascript;base64,{encoded}", *command[1:]]
            return original(fenced, *args, **kwargs)
        return python(command, *args, **kwargs)

    return launch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=GROUPS)
    parser.add_argument("--identities", action="store_true",
                        help="After successful application-multi tests, print both offline canonical identity records")
    args = parser.parse_args(argv)
    if args.identities and args.group != "application-multi":
        parser.error("--identities requires application-multi")
    directory, patterns = GROUPS[args.group]
    path = ROOT / "tests/unit" / directory
    sys.path.insert(0, str(path))
    original_popen = subprocess.Popen
    with ExitStack() as stack:
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=fence, create=True))
        stack.enter_context(patch("subprocess.Popen", side_effect=offline_probe_launcher(
            original_popen, allow_node=args.group in {"panel", "field-editor", "hotdog-template", "composition-preview"},
        )))
        if args.group in {"panel", "composition-preview"}:
            # Windows' ordinary asyncio self-pipe opens loopback sockets. These
            # tests need callback/timer/thread scheduling only, not socket I/O.
            stack.enter_context(patch("asyncio.events.new_event_loop", MemoryWakeupLoop))
        suite = unittest.TestSuite()
        for pattern in patterns:
            suite.addTests(unittest.defaultTestLoader.discover(str(path), pattern=pattern))
        if suite.countTestCases() == 0:
            raise AssertionError("The selected P2B suite discovered no tests")
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        if args.identities and result.wasSuccessful():
            from test_multi_layer_application import FAMILIES, canonical_snapshot
            snapshots = [canonical_snapshot(family) for family in FAMILIES]
            for snapshot in snapshots:
                snapshot.pop("graph")
            print(json.dumps(snapshots, indent=2, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
