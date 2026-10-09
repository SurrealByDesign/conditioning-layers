"""ComfyUI-contained artist sidebar integration for Phase 2 Slice 10A."""

from .application import ExistingBackendApplication, PanelHostContext
from .jobs import PanelJobConflict, PanelJobCoordinator, PanelJobSnapshot
from .models import (
    PanelExecutionDraft,
    PanelFinding,
    PanelLayerDraft,
    PanelOutput,
    PanelRequestError,
    PanelRunResult,
    RetainedField,
    UploadedField,
    parse_panel_request,
)

__all__ = [
    "ExistingBackendApplication",
    "PanelExecutionDraft",
    "PanelFinding",
    "PanelHostContext",
    "PanelJobConflict",
    "PanelJobCoordinator",
    "PanelJobSnapshot",
    "PanelLayerDraft",
    "PanelOutput",
    "PanelRequestError",
    "PanelRunResult",
    "RetainedField",
    "UploadedField",
    "parse_panel_request",
]
