from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
from threading import Lock, Thread

from conditioning_layers.execution.comfyui import ComfyUIServerConfiguration
from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_0280_INVENTORY,
    COMFYUI_0280_NODE_SNAPSHOT,
)
from conditioning_layers.runtime.comfyui import prepare_submission_bundle


PROMPT_ID = "11111111-1111-4111-8111-111111111111"


def _load_runtime_support():
    path = Path(__file__).parents[2] / "runtime" / "comfyui" / "_support.py"
    spec = importlib.util.spec_from_file_location("_slice8_runtime_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_RUNTIME_SUPPORT = _load_runtime_support()


def make_bundle(root: Path, *, semantic_profile: bool = False):
    inventory = (
        CANONICAL_COMFYUI_0280_INVENTORY
        if semantic_profile
        else _RUNTIME_SUPPORT.CANONICAL_COMFYUI_INVENTORY
    )
    case = _RUNTIME_SUPPORT.make_case(root, inventory)
    result = prepare_submission_bundle(
        case.artifact,
        case.provenance,
        case.inventory,
        case.configuration,
        case.inspections,
        case.asset_root,
        COMFYUI_0280_NODE_SNAPSHOT if semantic_profile else case.node_snapshot,
    )
    assert result.ready and result.bundle is not None, result.errors
    return result.bundle


def save_node_id(bundle) -> str:
    return next(
        node_id
        for node_id, node in bundle.graph_mapping.items()
        if node["class_type"] == "SaveImage"
    )


def identity_payload(bundle, **system_overrides):
    system = {
        "comfyui_version": bundle.host_snapshot.observed_comfyui_version,
        "git_revision": bundle.host_snapshot.observed_comfyui_revision,
        "argv": [],
    }
    system.update(system_overrides)
    return {"system": system, "devices": [{"name": "test-device"}]}


def semantic_identity_payload(bundle, port: int, **system_overrides):
    return identity_payload(
        bundle,
        git_revision=None,
        argv=["main.py", "--listen", "127.0.0.1", "--port", str(port)],
        **system_overrides,
    )


def object_info_payload(
    bundle,
    node_class: str,
    *,
    include_function: bool = False,
    node_snapshot=COMFYUI_0280_NODE_SNAPSHOT,
):
    contract = node_snapshot.contracts[node_class]
    required = {}
    optional = {}
    for evidence in contract.input_evidence:
        enum_values = list(evidence.enum_values)
        if evidence.external_enumeration is not None:
            enum_values.extend(
                sorted(
                    {
                        inputs[evidence.name]
                        for node in bundle.graph_mapping.values()
                        if node["class_type"] == node_class
                        and evidence.name in (inputs := node["inputs"])
                        and isinstance(inputs[evidence.name], str)
                    }
                )
            )
            if not enum_values:
                enum_values.append("test-external-value")
        descriptor = enum_values if enum_values else evidence.accepted_type
        options = {}
        if evidence.default_value is not None:
            options["default"] = evidence.default_value
        spec = [descriptor, options]
        target = required if evidence.host_requirement == "required" else optional
        target[evidence.name] = spec
    info = {
        "name": node_class,
        "input": {"required": required, "optional": optional},
        "output": list(contract.return_types),
        "display_name": "ignored presentation metadata",
    }
    if include_function:
        info["function"] = contract.function_name
    return {node_class: info}


def configure_semantic_contracts(server: FakeComfyUI, bundle, *, include_function=False):
    for node_class in COMFYUI_0280_NODE_SNAPSHOT.contracts:
        server.add(
            "GET",
            f"/object_info/{node_class}",
            Response(
                payload=object_info_payload(
                    bundle,
                    node_class,
                    include_function=include_function,
                )
            ),
        )


def completed_history(bundle, images=None):
    if images is None:
        images = [
            {
                "filename": "request-1_00001_.png",
                "subfolder": "conditioning-layers/document-1",
                "type": "output",
            }
        ]
    return {
        PROMPT_ID: {
            "status": {"status_str": "success", "completed": True, "messages": []},
            "outputs": {save_node_id(bundle): {"images": images}},
        }
    }


@dataclass(frozen=True)
class Response:
    status: int = 200
    payload: object = None
    content_type: str = "application/json"
    disconnect: bool = False
    raw_body: bytes | None = None


class FakeComfyUI:
    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], list[Response]] = defaultdict(list)
        self.requests: list[tuple[str, str, object | None]] = []
        self._lock = Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                owner._handle(self, "GET")

            def do_POST(self):
                owner._handle(self, "POST")

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def add(self, method: str, path: str, *responses: Response) -> None:
        self._responses[(method, path)].extend(responses)

    def config(self, **overrides) -> ComfyUIServerConfiguration:
        values = {
            "port": self.port,
            "connection_timeout_seconds": 1.0,
            "request_timeout_seconds": 1.0,
            "polling_interval_seconds": 0.01,
            "total_execution_timeout_seconds": 0.2,
        }
        values.update(overrides)
        return ComfyUIServerConfiguration(**values)

    def _handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        payload = None
        if method == "POST":
            length = int(handler.headers.get("Content-Length", "0"))
            raw = handler.rfile.read(length)
            payload = json.loads(raw.decode("utf-8")) if raw else None
        with self._lock:
            self.requests.append((method, handler.path, payload))
            queue = self._responses[(method, handler.path)]
            response = queue.pop(0) if len(queue) > 1 else queue[0] if queue else Response(404, {})
        if response.disconnect:
            handler.close_connection = True
            handler.connection.shutdown(2)
            handler.connection.close()
            return
        body = (
            response.raw_body
            if response.raw_body is not None
            else json.dumps(response.payload).encode("utf-8")
        )
        handler.send_response(response.status)
        handler.send_header("Content-Type", response.content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(body)


def configure_success(server: FakeComfyUI, bundle) -> None:
    server.add("GET", "/system_stats", Response(payload=identity_payload(bundle)))
    server.add("POST", "/prompt", Response(payload={"prompt_id": PROMPT_ID}))
    server.add(
        "GET",
        "/queue",
        Response(payload={"queue_running": [], "queue_pending": []}),
    )
    server.add("GET", f"/history/{PROMPT_ID}", Response(payload=completed_history(bundle)))


def codes(findings) -> set[str]:
    return {finding.code for finding in findings}
