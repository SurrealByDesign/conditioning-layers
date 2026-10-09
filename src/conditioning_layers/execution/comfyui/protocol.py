"""Narrow standard-library HTTP protocol for the validated ComfyUI profile."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid

from conditioning_layers.runtime.comfyui import ComfyUISubmissionBundle
from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0280_SUPPORTED_PROFILE,
    HostNodeContractRecord,
    HostNodeContractSnapshot,
    NodeInputEvidence,
    snapshot_is_supported,
)

from .errors import ProtocolFailure
from .models import (
    ComfyUIServerConfiguration,
    ServerIdentityMode,
    ServerIdentitySnapshot,
)


_REVISION_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
_REQUIRED_NODE_CLASSES = (
    "UNETLoader",
    "CLIPLoader",
    "CLIPTextEncode",
    "LoadImageMask",
    "ConditioningSetMask",
    "ConditioningCombine",
    "EmptyLatentImage",
    "KSampler",
    "VAELoader",
    "VAEDecode",
    "SaveImage",
)
_REQUIRED_NODE_CLASS_SET = frozenset(_REQUIRED_NODE_CLASSES)
_MISSING_DEFAULT = object()


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise urllib.error.HTTPError(
            request.full_url,
            code,
            "redirects are prohibited by the local-only execution client",
            headers,
            file_pointer,
        )


class LocalJsonTransport:
    """Per-client opener with proxies, cookies, credentials, and redirects disabled."""

    def __init__(self, configuration: ComfyUIServerConfiguration) -> None:
        self.configuration = configuration
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RejectRedirects(),
        )

    def get_json(self, endpoint: str) -> object:
        return self._request_json("GET", endpoint, None)

    def get_required_node_contract(self, node_class: str) -> object:
        """Fetch one of the eleven approved built-in node contracts only."""

        if node_class not in _REQUIRED_NODE_CLASS_SET:
            raise ProtocolFailure(
                "execution.server_contract_protocol",
                "Object-info fetches are limited to the approved built-in node set.",
            )
        endpoint = "/object_info/" + urllib.parse.quote(node_class, safe="")
        return self._request_json("GET", endpoint, None)

    def post_json(self, endpoint: str, payload: Mapping[str, object]) -> object:
        return self._request_json("POST", endpoint, payload)

    def post_no_content(self, endpoint: str, payload: Mapping[str, object]) -> None:
        body = _json_bytes(payload)
        self._validate_request_size(body)
        request = urllib.request.Request(
            self._url(endpoint),
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
            },
        )
        try:
            with self._opener.open(
                request,
                timeout=self.configuration.request_timeout_seconds,
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise ProtocolFailure(
                        "execution.submission_http",
                        f"ComfyUI returned HTTP {response.status}.",
                    )
                response.read(1)
        except ProtocolFailure:
            raise
        except urllib.error.HTTPError as error:
            raise ProtocolFailure(
                "execution.submission_http",
                f"ComfyUI returned HTTP {error.code}.",
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise ProtocolFailure(
                "execution.connection",
                "The local ComfyUI server could not be reached.",
            ) from error

    def _request_json(
        self,
        method: str,
        endpoint: str,
        payload: Mapping[str, object] | None,
    ) -> object:
        body = _json_bytes(payload) if payload is not None else None
        if body is not None:
            self._validate_request_size(body)
        headers = {"Accept": "application/json"}
        if body is not None:
            headers.update(
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Content-Length": str(len(body)),
                }
            )
        request = urllib.request.Request(
            self._url(endpoint),
            data=body,
            method=method,
            headers=headers,
        )
        timeout = (
            self.configuration.connection_timeout_seconds
            if endpoint == "/system_stats"
            else self.configuration.request_timeout_seconds
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                if response.status < 200 or response.status >= 300:
                    raise ProtocolFailure(
                        "execution.submission_http",
                        f"ComfyUI returned HTTP {response.status}.",
                    )
                content_type = response.headers.get_content_type()
                if content_type != "application/json":
                    raise ProtocolFailure(
                        _response_code(endpoint),
                        "ComfyUI response was not JSON.",
                    )
                raw = response.read(self.configuration.maximum_response_bytes + 1)
                if len(raw) > self.configuration.maximum_response_bytes:
                    raise ProtocolFailure(
                        _response_code(endpoint),
                        "ComfyUI response exceeded the configured bound.",
                    )
        except ProtocolFailure:
            raise
        except urllib.error.HTTPError as error:
            raise ProtocolFailure(
                "execution.submission_http" if endpoint == "/prompt" else _response_code(endpoint),
                f"ComfyUI returned HTTP {error.code}.",
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise ProtocolFailure(
                "execution.connection",
                "The local ComfyUI server could not be reached.",
            ) from error
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProtocolFailure(
                _response_code(endpoint),
                "ComfyUI returned malformed UTF-8 JSON.",
            ) from error

    def _url(self, endpoint: str) -> str:
        if not endpoint.startswith("/") or "?" in endpoint or "#" in endpoint:
            raise ProtocolFailure("execution.server_config", "Unsafe protocol endpoint.")
        host = f"[{self.configuration.host}]" if ":" in self.configuration.host else self.configuration.host
        base = self.configuration.api_base_path.strip("/")
        prefix = f"/{base}" if base else ""
        return f"http://{host}:{self.configuration.port}{prefix}{endpoint}"

    def _validate_request_size(self, body: bytes) -> None:
        if len(body) > self.configuration.maximum_request_bytes:
            raise ProtocolFailure(
                "execution.submission_response",
                "Execution request exceeded the configured bound.",
            )


def establish_server_identity(
    transport: LocalJsonTransport,
    bundle: ComfyUISubmissionBundle,
    *,
    trusted_snapshot: HostNodeContractSnapshot = COMFYUI_0280_SUPPORTED_PROFILE.node_snapshot,
) -> ServerIdentitySnapshot:
    """Accept a server by exact revision or the complete semantic contract route."""

    payload = transport.get_json("/system_stats")
    system, version, expected_revision, reported_revision = _identity_evidence(
        payload, bundle
    )
    if reported_revision is not None:
        if _REVISION_PATTERN.fullmatch(reported_revision) is None:
            raise ProtocolFailure(
                "execution.server_identity_unverified",
                "Running ComfyUI reported an unparseable revision.",
            )
        return _exact_revision_identity(
            payload,
            system,
            bundle,
            version,
            expected_revision,
            reported_revision,
        )
    return _semantic_contract_identity(
        payload,
        system,
        transport,
        bundle,
        version,
        expected_revision,
        trusted_snapshot,
    )


def validate_server_identity(
    payload: object,
    bundle: ComfyUISubmissionBundle,
) -> ServerIdentitySnapshot:
    """Validate Route A only; semantic identity requires a bounded transport."""

    system, version, expected_revision, reported_revision = _identity_evidence(
        payload, bundle
    )
    if reported_revision is None or _REVISION_PATTERN.fullmatch(reported_revision) is None:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Running ComfyUI did not report a trusted exact revision.",
        )
    return _exact_revision_identity(
        payload,
        system,
        bundle,
        version,
        expected_revision,
        reported_revision,
    )


def validate_semantic_server_identity(
    payload: object,
    transport: LocalJsonTransport,
    bundle: ComfyUISubmissionBundle,
    *,
    trusted_snapshot: HostNodeContractSnapshot = COMFYUI_0280_SUPPORTED_PROFILE.node_snapshot,
) -> ServerIdentitySnapshot:
    """Validate Route B against one explicitly supplied trusted snapshot."""

    system, version, expected_revision, reported_revision = _identity_evidence(
        payload, bundle
    )
    if reported_revision is not None:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Semantic identity is only used when exact revision evidence is absent.",
        )
    return _semantic_contract_identity(
        payload,
        system,
        transport,
        bundle,
        version,
        expected_revision,
        trusted_snapshot,
    )


def _identity_evidence(
    payload: object,
    bundle: ComfyUISubmissionBundle,
) -> tuple[Mapping[str, object], str, str, str | None]:
    """Parse only the shared identity evidence needed by both routes."""

    if not isinstance(payload, Mapping) or not isinstance(payload.get("system"), Mapping):
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Server identity response is missing system evidence.",
        )
    system = payload["system"]
    version = system.get("comfyui_version")
    expected_version = bundle.host_snapshot.observed_comfyui_version
    expected_revision = bundle.host_snapshot.observed_comfyui_revision
    if not isinstance(version, str) or version != expected_version:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Running ComfyUI version does not match the validated bundle host.",
        )
    if not isinstance(expected_revision, str) or _REVISION_PATTERN.fullmatch(expected_revision) is None:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Bundle host revision is unavailable.",
        )

    raw_revision = system.get("git_revision", system.get("comfyui_revision"))
    if raw_revision is not None and not isinstance(raw_revision, str):
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Running ComfyUI revision evidence is not a string.",
        )
    return system, version, expected_revision.lower(), raw_revision


def _exact_revision_identity(
    payload: object,
    system: Mapping[str, object],
    bundle: ComfyUISubmissionBundle,
    version: str,
    expected_revision: str,
    reported_revision: str,
) -> ServerIdentitySnapshot:
    if reported_revision.casefold() != expected_revision.casefold():
        raise ProtocolFailure(
            "execution.server_revision",
            "Running ComfyUI revision does not match the validated bundle host.",
        )
    argv_digest = _launch_argument_digest(system.get("argv"))
    devices = payload.get("devices")
    return ServerIdentitySnapshot(
        profile_identifier=bundle.profile_identifier,
        comfyui_version=version,
        comfyui_revision=expected_revision,
        revision_evidence="system_stats_revision",
        launch_arguments_sha256=argv_digest,
        device_count=len(devices) if isinstance(devices, list) else 0,
        identity_mode=ServerIdentityMode.EXACT_REVISION,
        reported_comfyui_revision=reported_revision.lower(),
        trusted_snapshot_fingerprint=(
            bundle.host_snapshot.node_contract_snapshot_fingerprint
        ),
        finding_codes=("execution.server_identity_exact",),
    )


def _semantic_contract_identity(
    payload: object,
    system: Mapping[str, object],
    transport: LocalJsonTransport,
    bundle: ComfyUISubmissionBundle,
    version: str,
    expected_revision: str,
    trusted_snapshot: HostNodeContractSnapshot,
) -> ServerIdentitySnapshot:
    argv = system.get("argv")
    argv_digest = _validate_local_launch_arguments(argv, transport.configuration)
    _validate_offline_semantic_evidence(bundle, trusted_snapshot, version, expected_revision)
    normalized_contracts = []
    for node_class in _REQUIRED_NODE_CLASSES:
        response = transport.get_required_node_contract(node_class)
        normalized_contracts.append(
            _normalize_live_contract(
                node_class,
                response,
                trusted_snapshot.contracts[node_class],
            )
        )
    live_fingerprint = _fingerprint(
        {"contracts": normalized_contracts, "version": version}
    )
    devices = payload.get("devices")
    return ServerIdentitySnapshot(
        profile_identifier=bundle.profile_identifier,
        comfyui_version=version,
        comfyui_revision=expected_revision,
        revision_evidence="semantic_contract",
        launch_arguments_sha256=argv_digest,
        device_count=len(devices) if isinstance(devices, list) else 0,
        identity_mode=ServerIdentityMode.SEMANTIC_CONTRACT,
        reported_comfyui_revision=None,
        trusted_snapshot_fingerprint=trusted_snapshot.snapshot_fingerprint,
        live_contract_fingerprint=live_fingerprint,
        finding_codes=("execution.server_identity_semantic",),
    )


def _validate_offline_semantic_evidence(
    bundle: ComfyUISubmissionBundle,
    snapshot: HostNodeContractSnapshot,
    version: str,
    expected_revision: str,
) -> None:
    host = bundle.host_snapshot
    runtime = bundle.provenance
    if (
        not snapshot_is_supported(snapshot)
        or snapshot.unresolved_items
        or tuple(snapshot.contracts) != _REQUIRED_NODE_CLASSES
    ):
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Trusted semantic evidence is unresolved or incomplete.",
        )
    if (
        snapshot.profile_identifier != bundle.profile_identifier
        or snapshot.comfyui_version != version
        or snapshot.comfyui_revision.casefold() != expected_revision.casefold()
        or host.node_contract_snapshot_identifier != snapshot.snapshot_identifier
        or host.node_contract_snapshot_fingerprint != snapshot.snapshot_fingerprint
        or runtime.node_contract_snapshot_identifier != snapshot.snapshot_identifier
        or runtime.node_contract_snapshot_fingerprint != snapshot.snapshot_fingerprint
        or not host.filesystem_verified
        or not host.node_contracts_verified
        or any(
            not item.verified
            or item.sha256 is None
            or item.sha256 != item.expected_sha256
            or item.byte_size != item.expected_byte_size
            for item in bundle.verified_components
        )
    ):
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Offline host, snapshot, or component evidence does not match the selected profile.",
        )


def _validate_local_launch_arguments(
    value: object,
    configuration: ComfyUIServerConfiguration,
) -> str:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Running ComfyUI launch arguments are unavailable or malformed.",
        )
    argv = tuple(value)
    if not any(_portable_basename(item).casefold() == "main.py" for item in argv):
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Launch arguments do not identify the approved ComfyUI entry point.",
        )
    listen_values = _option_values(argv, "--listen", bare_value="0.0.0.0")
    if len(listen_values) > 1 or any(
        item.casefold() not in {"127.0.0.1", "localhost", "::1"}
        for item in listen_values
    ):
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Launch arguments do not constrain ComfyUI to loopback.",
        )
    port_values = _option_values(argv, "--port")
    if len(port_values) > 1:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Launch arguments contain an ambiguous port.",
        )
    expected_port = 8188 if not port_values else _parse_port(port_values[0])
    if expected_port != configuration.port:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Launch arguments do not match the configured loopback port.",
        )
    digest = _launch_argument_digest(value)
    assert digest is not None
    return digest


def _normalize_live_contract(
    node_class: str,
    payload: object,
    expected: HostNodeContractRecord,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise _contract_protocol(node_class, "response is not an object")
    if node_class not in payload:
        raise ProtocolFailure(
            "execution.server_contract_missing",
            f"Required built-in node {node_class} is absent.",
        )
    if set(payload) != {node_class} or not isinstance(payload[node_class], Mapping):
        raise _contract_protocol(node_class, "response shape is not node-specific")
    info = payload[node_class]
    if info.get("name") != node_class:
        raise _contract_mismatch(node_class, "class name changed")
    inputs = info.get("input")
    if not isinstance(inputs, Mapping):
        raise _contract_protocol(node_class, "input contract is missing")
    required = inputs.get("required")
    optional = inputs.get("optional", {})
    if not isinstance(required, Mapping) or not isinstance(optional, Mapping):
        raise _contract_protocol(node_class, "required or optional inputs are malformed")
    if set(required) != set(expected.host_required_inputs):
        raise _contract_mismatch(node_class, "required input names changed")
    if not set(expected.host_optional_inputs) <= set(optional):
        raise _contract_mismatch(node_class, "profile-used optional inputs changed")

    normalized_inputs = []
    for evidence in expected.input_evidence:
        source = required if evidence.host_requirement == "required" else optional
        if evidence.name not in source:
            raise _contract_mismatch(node_class, f"input {evidence.name} changed requirement")
        normalized_inputs.append(
            _normalize_input_spec(
                node_class,
                source[evidence.name],
                evidence,
            )
        )

    outputs = info.get("output")
    if (
        not isinstance(outputs, list | tuple)
        or not all(isinstance(item, str) for item in outputs)
    ):
        raise _contract_protocol(node_class, "output contract is malformed")
    if tuple(outputs) != expected.return_types or any(
        index < 0 or index >= len(outputs) for index in expected.output_indices
    ):
        raise _contract_mismatch(node_class, "output types or indices changed")

    live_function = info.get("function")
    if live_function is None:
        function_name = expected.function_name
        function_evidence = "trusted_offline_snapshot"
    elif not isinstance(live_function, str):
        raise _contract_protocol(node_class, "function name is malformed")
    elif live_function != expected.function_name:
        raise _contract_mismatch(node_class, "function name changed")
    else:
        function_name = live_function
        function_evidence = "live_object_info"

    return {
        "class_name": node_class,
        "required_inputs": list(expected.host_required_inputs),
        "optional_inputs": list(expected.host_optional_inputs),
        "inputs": normalized_inputs,
        "output_types": list(outputs),
        "output_count": len(outputs),
        "output_indices": list(expected.output_indices),
        "function_name": function_name,
        "function_evidence": function_evidence,
    }


def _normalize_input_spec(
    node_class: str,
    value: object,
    expected: NodeInputEvidence,
) -> dict[str, object]:
    if not isinstance(value, list | tuple) or not 1 <= len(value) <= 2:
        raise _contract_protocol(node_class, f"input {expected.name} is malformed")
    type_descriptor = value[0]
    options = value[1] if len(value) == 2 else {}
    if not isinstance(options, Mapping):
        raise _contract_protocol(node_class, f"input {expected.name} options are malformed")
    live_enum: tuple[str, ...] = ()
    if isinstance(type_descriptor, str):
        live_type = type_descriptor
    elif isinstance(type_descriptor, list | tuple) and all(
        isinstance(item, str) for item in type_descriptor
    ):
        live_type = "STRING"
        live_enum = tuple(type_descriptor)
    else:
        raise _contract_protocol(node_class, f"input {expected.name} type is unknown")
    if live_type != expected.accepted_type:
        raise _contract_mismatch(node_class, f"input {expected.name} type changed")
    if expected.enum_values and not set(expected.enum_values) <= set(live_enum):
        raise _contract_mismatch(node_class, f"input {expected.name} enum changed")
    if expected.external_enumeration is not None and not live_enum:
        raise _contract_mismatch(
            node_class,
            f"input {expected.name} external enumeration is unavailable",
        )
    if expected.default_value is not None:
        live_default = options.get(
            "default",
            live_enum[0] if live_enum else _MISSING_DEFAULT,
        )
        if not _canonical_equal(live_default, expected.default_value):
            raise _contract_mismatch(
                node_class, f"input {expected.name} default changed"
            )
    normalized: dict[str, object] = {
        "name": expected.name,
        "requirement": expected.host_requirement,
        "type": live_type,
        "relevant_enum_values": list(expected.enum_values),
    }
    if expected.default_value is not None:
        normalized["default"] = expected.default_value
    if expected.external_enumeration is not None:
        normalized["external_enumeration"] = True
    return normalized


def _option_values(
    argv: tuple[str, ...],
    option: str,
    *,
    bare_value: str | None = None,
) -> tuple[str, ...]:
    values: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == option:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                if bare_value is None:
                    raise ProtocolFailure(
                        "execution.server_identity_unverified",
                        f"Launch option {option} is missing a value.",
                    )
                values.append(bare_value)
            else:
                values.append(argv[index + 1])
                index += 1
        elif item.startswith(option + "="):
            value = item[len(option) + 1 :]
            if not value:
                raise ProtocolFailure(
                    "execution.server_identity_unverified",
                    f"Launch option {option} is missing a value.",
                )
            values.append(value)
        index += 1
    return tuple(values)


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Launch port is malformed.",
        ) from error
    if not 1 <= port <= 65535:
        raise ProtocolFailure(
            "execution.server_identity_unverified",
            "Launch port is outside the valid range.",
        )
    return port


def _portable_basename(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _launch_argument_digest(value: object) -> str | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_equal(first: object, second: object) -> bool:
    try:
        return json.dumps(first, allow_nan=False, sort_keys=True) == json.dumps(
            second, allow_nan=False, sort_keys=True
        )
    except (TypeError, ValueError):
        return False


def _contract_protocol(node_class: str, reason: str) -> ProtocolFailure:
    return ProtocolFailure(
        "execution.server_contract_protocol",
        f"Live contract for {node_class} is unparseable: {reason}.",
    )


def _contract_mismatch(node_class: str, reason: str) -> ProtocolFailure:
    return ProtocolFailure(
        "execution.server_contract_mismatch",
        f"Live contract for {node_class} does not match the trusted snapshot: {reason}.",
    )


def submission_payload(
    bundle: ComfyUISubmissionBundle,
    client_identifier: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {"prompt": bundle.to_api_graph()}
    if client_identifier is not None:
        payload["client_id"] = client_identifier
    return payload


def parse_prompt_id(payload: object) -> str:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("prompt_id"), str):
        raise ProtocolFailure(
            "execution.prompt_id",
            "Submission response did not contain a valid prompt ID.",
        )
    prompt_id = payload["prompt_id"]
    try:
        parsed = uuid.UUID(prompt_id)
    except (ValueError, AttributeError) as error:
        raise ProtocolFailure(
            "execution.prompt_id",
            "Submission response prompt ID was malformed.",
        ) from error
    if str(parsed) != prompt_id:
        raise ProtocolFailure(
            "execution.prompt_id",
            "Submission response prompt ID was not canonical.",
        )
    return prompt_id


def parse_queue_presence(payload: object, prompt_id: str) -> tuple[bool, bool]:
    if not isinstance(payload, Mapping):
        raise ProtocolFailure("execution.queue_protocol", "Queue response is not an object.")
    running = payload.get("queue_running")
    pending = payload.get("queue_pending")
    if not isinstance(running, list) or not isinstance(pending, list):
        raise ProtocolFailure("execution.queue_protocol", "Queue response is missing queue arrays.")
    return _queue_contains(running, prompt_id), _queue_contains(pending, prompt_id)


def parse_history_record(payload: object, prompt_id: str) -> Mapping[str, object] | None:
    if not isinstance(payload, Mapping):
        raise ProtocolFailure("execution.history_protocol", "History response is not an object.")
    if prompt_id not in payload:
        return None
    record = payload[prompt_id]
    if not isinstance(record, Mapping):
        raise ProtocolFailure("execution.history_protocol", "Prompt history record is malformed.")
    return record


def history_endpoint(prompt_id: str) -> str:
    return "/history/" + urllib.parse.quote(prompt_id, safe="")


def _queue_contains(items: list[object], prompt_id: str) -> bool:
    for item in items:
        if not isinstance(item, list | tuple) or len(item) < 2:
            raise ProtocolFailure("execution.queue_protocol", "Queue item is malformed.")
        if item[1] == prompt_id:
            return True
    return False


def _json_bytes(payload: Mapping[str, object] | None) -> bytes:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProtocolFailure(
            "execution.bundle_fingerprint",
            "Execution request was not canonical JSON.",
        ) from error


def _response_code(endpoint: str) -> str:
    if endpoint == "/prompt":
        return "execution.submission_response"
    if endpoint == "/queue":
        return "execution.queue_protocol"
    if endpoint.startswith("/history/"):
        return "execution.history_protocol"
    if endpoint.startswith("/object_info/"):
        return "execution.server_contract_protocol"
    return "execution.server_identity_unverified"
