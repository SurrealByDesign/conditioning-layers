"""Portable runtime provenance construction without local absolute paths."""

from __future__ import annotations

from .models import (
    RUNTIME_PROVENANCE_VERSION,
    ComfyUIHostSnapshot,
    ComponentFileRecord,
    PortableComponentProvenance,
    PortableFieldProvenance,
    RuntimeProvenance,
    StagedAssetRecord,
)


def build_runtime_provenance(
    *,
    document_id: str,
    translation_plan_fingerprint: str,
    graph_fingerprint: str,
    adapter_identifier: str,
    inventory_identifier: str,
    host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...],
    staged_assets: tuple[StagedAssetRecord, ...],
    seed: int,
    output_prefix: str,
    warning_codes: tuple[str, ...],
    bundle_fingerprint: str,
) -> RuntimeProvenance:
    """Create sanitized provenance for a verified pre-submission bundle."""

    assert host_snapshot.observed_comfyui_version is not None
    assert host_snapshot.observed_comfyui_revision is not None
    assert host_snapshot.node_contract_snapshot_identifier is not None
    assert host_snapshot.node_contract_snapshot_fingerprint is not None
    portable_components = tuple(
        PortableComponentProvenance(
            role=record.role.value,
            category=record.category,
            filename=record.filename,
            byte_size=record.byte_size,  # type: ignore[arg-type]
            sha256=record.sha256,  # type: ignore[arg-type]
        )
        for record in components
    )
    portable_fields = tuple(
        PortableFieldProvenance(
            layer_id=record.layer_id,
            document_reference=record.document_reference,
            source_sha256=record.expected_sha256,
            staged_filename=record.staged_filename,
            staged_sha256=record.observed_sha256,  # type: ignore[arg-type]
            disposition=record.disposition.value,
        )
        for record in staged_assets
    )
    return RuntimeProvenance(
        provenance_version=RUNTIME_PROVENANCE_VERSION,
        document_id=document_id,
        translation_plan_fingerprint=translation_plan_fingerprint,
        graph_fingerprint=graph_fingerprint,
        adapter_identifier=adapter_identifier,
        inventory_identifier=inventory_identifier,
        host_profile_identifier=host_snapshot.profile_identifier,
        comfyui_version=host_snapshot.observed_comfyui_version,
        comfyui_revision=host_snapshot.observed_comfyui_revision,
        node_contract_snapshot_identifier=(
            host_snapshot.node_contract_snapshot_identifier
        ),
        node_contract_snapshot_fingerprint=(
            host_snapshot.node_contract_snapshot_fingerprint
        ),
        components=portable_components,
        fields=portable_fields,
        seed=seed,
        output_prefix=output_prefix,
        warning_codes=warning_codes,
        bundle_fingerprint=bundle_fingerprint,
    )
