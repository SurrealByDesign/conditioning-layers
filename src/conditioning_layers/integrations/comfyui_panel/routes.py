"""ComfyUI-specific route registration and multipart adaptation for Slice 10A."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from conditioning_layers.comfyui.prediction_mixing import (
    DEFAULT_SUPPORTED_PROFILE,
)
from conditioning_layers.execution.comfyui import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
)
from conditioning_layers.runtime.comfyui import (
    ComfyUIHostConfiguration,
    StagingCleanupPolicy,
)

from .application import ExistingBackendApplication, PanelHostContext
from .documents import (
    PanelDocumentError,
    PanelDocumentStore,
    parse_document_request,
)
from .jobs import PanelJobConflict, PanelJobCoordinator
from .guidance import panel_capability_guidance
from .models import (
    FIELD_PART_PREFIX,
    MAX_FIELD_BYTES,
    MAX_METADATA_BYTES,
    MAX_MULTIPART_PARTS,
    MAX_TOTAL_BYTES,
    PNG_MIME_TYPE,
    REQUEST_METADATA_PART,
    PanelFinding,
    PanelRequestError,
    UploadedField,
    parse_panel_request,
    validate_execution_id,
)
from .starter_fields import product_field_presets, read_starter_field


_REGISTERED = False
_COORDINATOR: PanelJobCoordinator | None = None


def register_routes() -> None:
    """Register execution and minimal canonical-document routes with PromptServer."""

    global _REGISTERED, _COORDINATOR
    if _REGISTERED:
        return

    from aiohttp import web
    from server import PromptServer

    host_context = _build_host_context()
    coordinator = PanelJobCoordinator(ExistingBackendApplication(host_context))
    document_store = PanelDocumentStore(host_context.host_configuration.user_directory)
    routes = PromptServer.instance.routes

    @routes.get("/conditioning-layers/capabilities")
    async def get_capabilities(_request):
        return web.json_response(
            panel_capability_guidance(),
            headers={"Cache-Control": "no-store"},
        )

    @routes.post("/conditioning-layers/executions")
    async def create_execution(request):
        try:
            draft = await _read_multipart_request(request)
            snapshot, created = coordinator.submit(
                draft,
                asyncio.get_running_loop(),
            )
            return web.json_response(
                snapshot.to_json(),
                status=202 if created else 200,
            )
        except PanelRequestError as exc:
            return web.json_response(
                _error_payload(exc.finding),
                status=exc.status,
            )
        except PanelJobConflict as exc:
            return web.json_response(
                _error_payload(exc.finding),
                status=409,
            )

    @routes.get("/conditioning-layers/executions/{execution_id}")
    async def get_execution(request):
        execution_id = request.match_info.get("execution_id", "")
        if not validate_execution_id(execution_id):
            finding = PanelFinding(
                code="panel.execution.identifier",
                severity="error",
                message="Execution identifier is invalid.",
            )
            return web.json_response(_error_payload(finding), status=404)
        snapshot = coordinator.get(execution_id)
        if snapshot is None:
            finding = PanelFinding(
                code="panel.execution.not_found",
                severity="error",
                message="Execution was not found.",
            )
            return web.json_response(_error_payload(finding), status=404)
        return web.json_response(snapshot.to_json())

    @routes.get("/conditioning-layers/documents")
    async def list_documents(_request):
        return web.json_response({"documents": document_store.list_documents()})

    @routes.get("/conditioning-layers/starter-fields")
    async def get_field_presets(_request):
        try:
            return web.json_response(
                {"presets": [preset.to_json() for preset in product_field_presets()]},
                headers={"Cache-Control": "no-store"},
            )
        except PanelRequestError as exc:
            return web.json_response(_error_payload(exc.finding), status=exc.status)

    @routes.get("/conditioning-layers/starter-fields/{starter_id}")
    async def get_starter_field(request):
        try:
            data = read_starter_field(request.match_info.get("starter_id", ""))
            return web.Response(
                body=data,
                content_type=PNG_MIME_TYPE,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": "inline",
                },
            )
        except PanelRequestError as exc:
            return web.json_response(_error_payload(exc.finding), status=exc.status)

    @routes.get("/conditioning-layers/documents/{document_key}")
    async def open_document(request):
        try:
            opened = document_store.open(
                request.match_info.get("document_key", ""),
                policy_aware=request.headers.get("X-Conditioning-Layers-Policy-Editor") == "1",
            )
            return web.json_response(opened.to_json())
        except PanelDocumentError as exc:
            return web.json_response(_error_payload(exc.finding), status=exc.status)

    @routes.get("/conditioning-layers/documents/{document_key}/fields/{layer_id}")
    async def read_document_field(request):
        try:
            data = document_store.read_field(
                request.match_info.get("document_key", ""),
                request.match_info.get("layer_id", ""),
            )
            return web.Response(
                body=data,
                content_type=PNG_MIME_TYPE,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": "inline",
                },
            )
        except PanelDocumentError as exc:
            return web.json_response(_error_payload(exc.finding), status=exc.status)

    @routes.post("/conditioning-layers/documents")
    async def save_document_as(request):
        try:
            draft = await _read_document_multipart_request(request)
            opened = document_store.save_as(draft)
            return web.json_response(opened.to_json(), status=201)
        except (PanelRequestError, PanelDocumentError) as exc:
            return web.json_response(_error_payload(exc.finding), status=exc.status)

    @routes.put("/conditioning-layers/documents/{document_key}")
    async def save_open_document(request):
        try:
            draft = await _read_document_multipart_request(request)
            opened = document_store.save(
                request.match_info.get("document_key", ""),
                draft,
            )
            return web.json_response(opened.to_json())
        except (PanelRequestError, PanelDocumentError) as exc:
            return web.json_response(_error_payload(exc.finding), status=exc.status)

    _COORDINATOR = coordinator
    _REGISTERED = True


async def _read_multipart_request(request) -> object:
    metadata, uploads, part_count, total_bytes = await _read_multipart_parts(request)
    return parse_panel_request(
        metadata,
        uploads,
        multipart_part_count=part_count,
        total_bytes=total_bytes,
    )


async def _read_document_multipart_request(request) -> object:
    metadata, uploads, part_count, total_bytes = await _read_multipart_parts(request)
    return parse_document_request(
        metadata,
        uploads,
        multipart_part_count=part_count,
        total_bytes=total_bytes,
    )


async def _read_multipart_parts(request) -> tuple[bytes, dict[str, UploadedField], int, int]:
    content_type = request.headers.get("Content-Type", "")
    if not content_type.casefold().startswith("multipart/form-data"):
        raise PanelRequestError(
            "panel.request.content_type",
            "Requests with Influence Fields must use multipart/form-data.",
            status=415,
        )
    content_length = request.content_length
    if content_length is not None and content_length > MAX_TOTAL_BYTES:
        raise PanelRequestError(
            "panel.request.total_size",
            "The multipart request exceeds the 17 MiB transport limit.",
            status=413,
        )

    reader = await request.multipart()
    metadata: bytes | None = None
    uploads: dict[str, UploadedField] = {}
    part_count = 0
    total_bytes = 0
    while True:
        part = await reader.next()
        if part is None:
            break
        part_count += 1
        if part_count > MAX_MULTIPART_PARTS:
            raise PanelRequestError(
                "panel.request.part_limit",
                "The multipart request contains too many parts.",
                status=413,
            )
        name = part.name or ""
        if name == REQUEST_METADATA_PART:
            if metadata is not None:
                raise PanelRequestError(
                    "panel.request.metadata_duplicate",
                    "The request accepts exactly one metadata part.",
                )
            if (part.headers.get("Content-Type") or "").casefold().split(";", 1)[0] != "application/json":
                raise PanelRequestError(
                    "panel.request.metadata_mime",
                    "Request metadata must use application/json.",
                    status=415,
                )
            metadata = await _read_part(part, MAX_METADATA_BYTES)
            total_bytes += len(metadata)
        elif name.startswith(FIELD_PART_PREFIX):
            if name in uploads:
                raise PanelRequestError(
                    "panel.request.field_duplicate",
                    "Influence Field part names must be unique.",
                )
            content_type = (part.headers.get("Content-Type") or "").casefold()
            data = await _read_part(part, MAX_FIELD_BYTES)
            total_bytes += len(data)
            # Client filenames are deliberately neither read nor retained.
            uploads[name] = UploadedField(
                part_name=name,
                content_type=content_type,
                data=data,
            )
        else:
            raise PanelRequestError(
                "panel.request.part_name",
                "The multipart request contains an unsupported part.",
            )
        if total_bytes > MAX_TOTAL_BYTES:
            raise PanelRequestError(
                "panel.request.total_size",
                "The multipart request exceeds the 17 MiB transport limit.",
                status=413,
            )
    if metadata is None:
        raise PanelRequestError(
            "panel.request.metadata_missing",
            "The request requires one JSON metadata part.",
        )
    return metadata, uploads, part_count, total_bytes


async def _read_part(part, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await part.read_chunk(size=64 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise PanelRequestError(
                "panel.request.part_size",
                "A multipart part exceeds its transport limit.",
                status=413,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _build_host_context() -> PanelHostContext:
    import folder_paths
    from comfy.cli_args import args

    comfyui_root = Path(folder_paths.__file__).resolve().parent
    input_directory = Path(folder_paths.get_input_directory()).resolve()
    output_directory = Path(folder_paths.get_output_directory()).resolve()
    user_directory = Path(folder_paths.get_user_directory()).resolve()
    model_root = Path(folder_paths.models_dir).resolve()
    data_root = Path(
        os.path.commonpath(
            (input_directory, output_directory, user_directory, model_root)
        )
    )
    model_directories = _trusted_model_directories(folder_paths, model_root)
    host = ComfyUIHostConfiguration(
        comfyui_root=comfyui_root,
        input_directory=input_directory,
        output_directory=output_directory,
        user_directory=user_directory,
        model_root=model_root,
        model_directories=model_directories,
        git_checkout_path=comfyui_root,
        supported_profile_identifier=(
            DEFAULT_SUPPORTED_PROFILE.inventory.comfyui_profile_identifier
        ),
        launch_profile_identifier="desktop-managed-loopback-8000",
        staging_cleanup_policy=StagingCleanupPolicy.CALLER_MANAGED,
        checkout_trusted_root=comfyui_root,
        data_trusted_root=data_root,
        model_trusted_root=model_root,
    )
    server = ComfyUIServerConfiguration(
        host="127.0.0.1",
        port=int(args.port),
        connection_timeout_seconds=5.0,
        request_timeout_seconds=30.0,
        polling_interval_seconds=1.0,
        total_execution_timeout_seconds=900.0,
        client_identifier="conditioning-layers-panel",
    )
    policy = ComfyUIExecutionPolicy(
        permit_prompt_cancellation_on_timeout=False,
        require_output_prefix_match=True,
        require_expected_save_image_node=True,
        retain_staged_assets=True,
        recommend_checksum_safe_cleanup=True,
    )
    return PanelHostContext(
        host_configuration=host,
        server_configuration=server,
        execution_policy=policy,
    )


def _error_payload(finding: PanelFinding) -> dict[str, Any]:
    return {
        "state": "rejected",
        "terminal": True,
        "findings": [finding.to_json()],
    }


def _trusted_model_directories(folder_paths_module, model_root: Path) -> dict[str, tuple[Path, ...]]:
    """Exclude extra configured roots from the one validated local model root."""

    trusted_root = model_root.resolve()
    result: dict[str, tuple[Path, ...]] = {}
    for category in ("diffusion_models", "text_encoders", "vae"):
        candidates = tuple(
            Path(value).resolve()
            for value in folder_paths_module.get_folder_paths(category)
        )
        result[category] = tuple(
            path for path in candidates if path.is_relative_to(trusted_root)
        )
    return result
