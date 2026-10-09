"""Run C1-H1's retained regressions with no socket or process launch.

The existing execution fixture normally creates an ephemeral HTTP server. Here
only its server lifecycle and urllib opener are replaced by in-memory responses;
the actual client, protocol serialization/parsing and test assertions still run.
This does not verify socket behavior. No browser suite is loaded.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
from email.message import Message
import importlib
import io
import json
from pathlib import Path
import sys
import subprocess
from threading import Lock
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
GROUPS = {
    "application": ("integrations/comfyui_panel", ("test_application.py", "test_compatibility_injection.py")),
    "execution": ("execution/comfyui", ("test_*.py",)),
    "compatibility": ("comfyui/prediction_mixing", ("test_profiles.py", "test_graph.py")),
    "historical": ("comfyui/prediction_mixing", ("test_*contract_family.py",)),
}
FENCES = ("socket.socket", "socket.create_connection", "socket.getaddrinfo",
          "urllib.request.urlopen", "urllib.request.OpenerDirector.open",
          "http.client.HTTPConnection.connect", "subprocess.Popen",
          "webbrowser.open", "os.system", "os.startfile")


def fence(*args, **kwargs):
    raise AssertionError("Offline regression fence: network/process launch prohibited")


def fenced_probe(source):
    """Fresh Python identity probes inherit the same network/launch fences."""
    with ExitStack() as stack:
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=fence, create=True))
        exec(compile(source, "<retained-offline-identity-probe>", "exec"), {"__name__": "__main__"})


def python_probe_launcher(original):
    def launch(command, *args, **kwargs):
        if not isinstance(command, list) or not command or command[0] != sys.executable or kwargs.get("shell"):
            return fence()
        if command[1:2] == ["-c"]:
            index = 2
        elif command[1:5] == ["-B", "-W", "error", "-c"]:
            index = 5
        else:
            return fence()
        # Only the retained Python -c identity probes are admitted. Their code
        # runs after fences are installed; they cannot spawn another process.
        source = command[index]
        bootstrap = (
            f"import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); "
            f"from offline_regressions import fenced_probe; fenced_probe({source!r})"
        )
        return original(command[:index] + [bootstrap] + command[index + 1:], *args, **kwargs)
    return launch


def memory_server(stack):
    support = importlib.import_module("_support")
    server_type = support.FakeComfyUI
    active = []

    def initialize(server):
        server._responses = defaultdict(list)
        server.requests = []
        server._lock = Lock()

    def enter(server):
        if active:
            raise AssertionError("Only one in-memory fixture may be active")
        active.append(server)
        return server

    def leave(server, *args):
        active.remove(server)

    def open_response(opener, request, timeout=None):
        if not active:
            return fence()
        url = urlsplit(request.full_url)
        if (url.scheme, url.hostname, url.port) != ("http", "127.0.0.1", 18765):
            return fence()
        server = active[0]
        payload = json.loads(request.data) if request.data else None
        with server._lock:
            server.requests.append((request.method, url.path, payload))
            queue = server._responses[(request.method, url.path)]
            response = queue.pop(0) if len(queue) > 1 else queue[0] if queue else support.Response(404, {})
        if response.disconnect:
            raise OSError("offline disconnected response")
        stream = io.BytesIO(response.raw_body if response.raw_body is not None else json.dumps(response.payload).encode())
        stream.status = response.status
        stream.headers = Message()
        stream.headers["Content-Type"] = response.content_type
        return stream

    for name, replacement in (("__init__", initialize), ("__enter__", enter), ("__exit__", leave),
                              ("port", property(lambda server: 18765))):
        stack.enter_context(patch.object(server_type, name, replacement))
    stack.enter_context(patch("urllib.request.OpenerDirector.open", open_response))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=GROUPS)
    args = parser.parse_args(argv)
    directory, patterns = GROUPS[args.group]
    path = ROOT / "tests/unit" / directory
    sys.path.insert(0, str(path))
    original_popen = subprocess.Popen
    with ExitStack() as stack:
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=fence, create=True))
        if args.group in {"compatibility", "historical"}:
            stack.enter_context(patch("subprocess.Popen", side_effect=python_probe_launcher(original_popen)))
        if args.group == "execution":
            memory_server(stack)
        suite = unittest.TestSuite()
        for pattern in patterns:
            suite.addTests(unittest.defaultTestLoader.discover(str(path), pattern=pattern))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
