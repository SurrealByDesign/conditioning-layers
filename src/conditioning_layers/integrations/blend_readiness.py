"""Fixed process-local Blend readiness observation, separate from execution.

No readiness record is accepted by the submission or P3D accounting boundaries.
Registration is optional and occurs after the retained sidebar registration.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from enum import Enum
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from conditioning_layers.comfyui.prediction_mixing.blend.authority import (
    BLEND_GRAPH_PERMITTED_CLASSES, INVENTORY, SNAPSHOT,
    verify_permitted_class_authority,
)
from conditioning_layers.execution.comfyui.blend import _verify_target_process
from conditioning_layers.execution.comfyui.protocol import _launch_argument_digest
from conditioning_layers.runtime.comfyui.blend import (
    capture_blend_component_availability, portable_value,
)
from conditioning_layers.runtime.comfyui.host_validation import validate_local_host

from .comfyui_panel.routes import _build_host_context


ATTESTATION_SCHEMA = "p3d-blend-readiness-attestation.v1"
READINESS_PATH = "/conditioning-layers/readiness/normalized-blend"
CHALLENGE_HEADER = "X-Conditioning-Layers-Readiness-Challenge"
HOST = "127.0.0.1"
PORT = 8000
SUPPORTED_TARGET = {
    "host": HOST, "port": PORT,
    "profile": INVENTORY.comfyui_profile_identifier,
    "version": INVENTORY.expected_comfyui_version,
    "revision": INVENTORY.expected_comfyui_revision,
}
VERIFIED_FIELDS = (
    "component_verified", "target_process_verified", "permitted_classes_verified",
)
ATTESTATION_FIELDS = frozenset((
    "schema", "observed_at_utc", "challenge", "process_id", "argv",
    "launch_arguments_sha256", "target", "host_context", "component_identity",
    "component_verified", "runtime_dtype", "disqualifying_flags",
    "target_process_verified", "permitted_class_authority", "permitted_classes_verified",
    "overall_ready", "reason_codes",
))
DISQUALIFYING_FLAGS = (
    "--fp16-intermediates", "--force-fp16", "--cpu", "--directml",
)
_CHALLENGE = re.compile(r"[0-9a-f]{64}\Z")
_PUBLISHED_IDENTITY = None
_REGISTERED = False


def _json_value(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict) or hasattr(value, "items"):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def host_context_projection(host_configuration):
    """Expose observed installation paths for exact external reconciliation."""

    return {item.name: _json_value(getattr(host_configuration, item.name))
            for item in fields(host_configuration)}


def _valid_challenge(value):
    return type(value) is str and _CHALLENGE.fullmatch(value) is not None


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class _ProcessLocalStats:
    """The retained target verifier's sole read, without a socket or HTTP call."""

    def __init__(self, configuration):
        self.configuration = configuration

    def get_json(self, path):
        if path != "/system_stats":
            raise ValueError("readiness_local_read_disallowed")
        return {"system": {"argv": list(sys.argv)}}


def capture_attestation(challenge):
    """Observe the current host through retained owners; never prepare a bundle."""

    if not _valid_challenge(challenge):
        raise ValueError("readiness_challenge_invalid")
    arguments = list(sys.argv)
    process_id = os.getpid()
    record = {
        "schema": ATTESTATION_SCHEMA,
        "observed_at_utc": None,
        "challenge": challenge,
        "process_id": process_id,
        "argv": arguments,
        "launch_arguments_sha256": _launch_argument_digest(arguments),
        "target": {
            "host": HOST, "port": PORT,
            "profile": INVENTORY.comfyui_profile_identifier,
            "version": None, "revision": None,
        },
        "host_context": None,
        "component_identity": None,
        "component_verified": False,
        "runtime_dtype": None,
        "disqualifying_flags": [flag for flag in DISQUALIFYING_FLAGS
            if any(type(item) is str and item.split("=", 1)[0] == flag for item in arguments)],
        "target_process_verified": False,
        "permitted_class_authority": portable_value(BLEND_GRAPH_PERMITTED_CLASSES),
        "permitted_classes_verified": False,
        "overall_ready": False,
        "reason_codes": [],
    }
    reasons = record["reason_codes"]
    availability = None
    try:
        availability = capture_blend_component_availability(_PUBLISHED_IDENTITY)
        record["component_identity"] = portable_value(availability.implementation)
        record["component_verified"] = True
        record["runtime_dtype"] = "torch.float32"
    except Exception:
        # Individual predicates remain owned by the retained availability gate.
        reasons.append("retained_component_unavailable")

    context = None
    try:
        context = _build_host_context()
        host = context.host_configuration
        server = context.server_configuration
        record["host_context"] = host_context_projection(host)
        validation = validate_local_host(
            host, INVENTORY, INVENTORY.required_node_class_names, SNAPSHOT,
        )
        record["target"] = {
            "host": server.host, "port": server.port,
            "profile": host.supported_profile_identifier,
            "version": validation.snapshot.observed_comfyui_version,
            "revision": validation.snapshot.observed_comfyui_revision,
        }
        if (server.host != HOST or type(server.port) is not int or server.port != PORT
                or validation.compatible is not True or validation.errors
                or validation.unresolved_requirements):
            raise ValueError("retained_host_unverified")
    except Exception:
        reasons.append("retained_host_unverified")

    try:
        if availability is None or context is None:
            raise ValueError("target_process_unverified")
        _verify_target_process(
            _ProcessLocalStats(context.server_configuration),
            SimpleNamespace(component_availability=availability),
            SimpleNamespace(launch_arguments_sha256=record["launch_arguments_sha256"]),
        )
        record["target_process_verified"] = True
    except Exception:
        reasons.append("target_process_unverified")

    try:
        if verify_permitted_class_authority(BLEND_GRAPH_PERMITTED_CLASSES, INVENTORY):
            raise ValueError("permitted_class_authority_unverified")
        record["permitted_classes_verified"] = True
    except Exception:
        reasons.append("permitted_class_authority_unverified")

    if os.getpid() != process_id or list(sys.argv) != arguments:
        reasons.append("process_observation_changed")
    record["observed_at_utc"] = utc_now()
    record["overall_ready"] = not reasons
    return record


def _request_allowed(request):
    """Constrain the route to a direct fixed IPv4 loopback readiness request."""

    try:
        headers = request.headers
        peer = request.transport.get_extra_info("peername")
        local = request.transport.get_extra_info("sockname")
        header_names = [name.lower() for name in headers]
        return (
            request.method == "GET" and request.path == READINESS_PATH
            and request.raw_path == READINESS_PATH and not request.query_string
            and request.content_length in (None, 0) and not request.can_read_body
            and headers.get("Host") == f"{HOST}:{PORT}"
            and header_names.count("host") == 1
            and header_names.count(CHALLENGE_HEADER.lower()) == 1
            and _valid_challenge(headers.get(CHALLENGE_HEADER))
            and not any(name in ("origin", "forwarded", "transfer-encoding")
                        or name.startswith("x-forwarded-") for name in header_names)
            and type(peer) is tuple and len(peer) == 2 and peer[0] == HOST
            and type(local) is tuple and len(local) == 2
            and local[0] == HOST and type(local[1]) is int and local[1] == PORT
        )
    except Exception:
        return False


async def handle_readiness_request(request):
    from aiohttp import web

    headers = {"Cache-Control": "no-store"}
    if not _request_allowed(request):
        return web.json_response({
            "schema": ATTESTATION_SCHEMA, "overall_ready": False,
            "reason_codes": ["readiness_request_rejected"],
        }, status=403, headers=headers)
    try:
        record = capture_attestation(request.headers[CHALLENGE_HEADER])
        return web.json_response(record, headers=headers)
    except Exception:
        return web.json_response({
            "schema": ATTESTATION_SCHEMA, "overall_ready": False,
            "reason_codes": ["readiness_internal_error"],
        }, status=503, headers=headers)


def register_readiness_route(published_identity):
    """Optional startup registration; no model, job or accounting operation."""

    global _REGISTERED, _PUBLISHED_IDENTITY
    if _REGISTERED:
        return
    from server import PromptServer

    PromptServer.instance.routes.get(READINESS_PATH)(handle_readiness_request)
    _PUBLISHED_IDENTITY = published_identity
    _REGISTERED = True
