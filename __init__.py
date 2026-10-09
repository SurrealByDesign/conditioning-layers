"""ComfyUI custom-node loader for the Conditioning Layers sidebar extension."""

from pathlib import Path
import os
import sys


_PACKAGE_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _PACKAGE_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from conditioning_layers.integrations.comfyui_panel.routes import register_routes


NODE_CLASS_MAPPINGS: dict[str, object] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}
WEB_DIRECTORY = "./web"

register_routes()

# The supported sidebar and No Overlap routes are registered before the optional
# Blend boundary. Any Blend import, dependency, or initialization failure leaves
# their registration intact and makes only this component unavailable.
BLEND_COMPONENT_IDENTITY = None
BLEND_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.prediction_mixing.blend_component import initialize_blend_node_registration

    _blend_mappings, _blend_identity = initialize_blend_node_registration()
    _blend_names = {name: "Normalized Blend Preparation" for name in _blend_mappings}
except Exception as _blend_error:
    BLEND_REGISTRATION_ERROR = f"{type(_blend_error).__name__}: {_blend_error}"
else:
    NODE_CLASS_MAPPINGS = _blend_mappings
    NODE_DISPLAY_NAME_MAPPINGS = _blend_names
    BLEND_COMPONENT_IDENTITY = _blend_identity

# Readiness is independent of component availability and product admission.
# Its own import/registration failure cannot undo any retained sidebar routes.
BLEND_READINESS_REGISTRATION_ERROR = None
try:
    from conditioning_layers.integrations.blend_readiness import register_readiness_route

    register_readiness_route(BLEND_COMPONENT_IDENTITY)
except Exception as _readiness_error:
    BLEND_READINESS_REGISTRATION_ERROR = f"{type(_readiness_error).__name__}: {_readiness_error}"

# Node System Phase 1 layer-workflow nodes are a separate optional boundary.
# Node availability is not product admission, and a failure here cannot undo
# the sidebar, Blend or readiness registration above.
LAYER_NODE_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.prediction_mixing.layer_nodes import initialize_layer_node_registration

    _layer_mappings, _layer_names = initialize_layer_node_registration()
    if set(_layer_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Layer node names collide with registered nodes")
except Exception as _layer_error:
    LAYER_NODE_REGISTRATION_ERROR = f"{type(_layer_error).__name__}: {_layer_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_layer_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_layer_names}

# Field sources are independently available; failure cannot undo Layer, Blend,
# sidebar or readiness registration, and Layer/Blend failures do not hide them.
FIELD_SOURCE_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.influence_field_sources import initialize_field_source_node_registration

    _field_mappings, _field_names = initialize_field_source_node_registration()
    if set(_field_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Field source node names collide with registered nodes")
except Exception as _field_error:
    FIELD_SOURCE_REGISTRATION_ERROR = f"{type(_field_error).__name__}: {_field_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_field_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_field_names}

# File-backed patterns are isolated from procedural sources and Layer/Blend.
# Missing library files are diagnosed by the node, never at root registration.
PATTERN_FIELD_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.pattern_field_source import initialize_pattern_field_node_registration

    _pattern_mappings, _pattern_names = initialize_pattern_field_node_registration()
    if set(_pattern_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Pattern Field node names collide with registered nodes")
except Exception as _pattern_error:
    PATTERN_FIELD_REGISTRATION_ERROR = f"{type(_pattern_error).__name__}: {_pattern_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_pattern_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_pattern_names}

# Field geometry is independent of source and consumer node registration.
FIELD_TRANSFORM_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.field_transform import initialize_field_transform_node_registration

    _transform_mappings, _transform_names = initialize_field_transform_node_registration()
    if set(_transform_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Field Transform node names collide with registered nodes")
except Exception as _transform_error:
    FIELD_TRANSFORM_REGISTRATION_ERROR = f"{type(_transform_error).__name__}: {_transform_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_transform_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_transform_names}

# Periodic field authoring is isolated from Transform and source/consumer nodes.
FIELD_REPEAT_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.field_repeat import initialize_field_repeat_node_registration

    _repeat_mappings, _repeat_names = initialize_field_repeat_node_registration()
    if set(_repeat_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Field Repeat node names collide with registered nodes")
except Exception as _repeat_error:
    FIELD_REPEAT_REGISTRATION_ERROR = f"{type(_repeat_error).__name__}: {_repeat_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_repeat_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_repeat_names}

# Numeric field authoring is independent of spatial operations and consumers.
FIELD_REMAP_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.field_remap import initialize_field_remap_node_registration

    _remap_mappings, _remap_names = initialize_field_remap_node_registration()
    if set(_remap_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Field Remap node names collide with registered nodes")
except Exception as _remap_error:
    FIELD_REMAP_REGISTRATION_ERROR = f"{type(_remap_error).__name__}: {_remap_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_remap_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_remap_names}

# Spatial smoothing is independent of other field operations and consumers.
FIELD_BLUR_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.field_blur import initialize_field_blur_node_registration

    _blur_mappings, _blur_names = initialize_field_blur_node_registration()
    if set(_blur_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Field Blur node names collide with registered nodes")
except Exception as _blur_error:
    FIELD_BLUR_REGISTRATION_ERROR = f"{type(_blur_error).__name__}: {_blur_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_blur_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_blur_names}

# Procedural fields are independent of earlier source, operation and Layer nodes.
PROCEDURAL_FIELD_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.procedural_field_sources import initialize_procedural_field_node_registration

    _procedural_mappings, _procedural_names = initialize_procedural_field_node_registration()
    if set(_procedural_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Procedural field node names collide with registered nodes")
except Exception as _procedural_error:
    PROCEDURAL_FIELD_REGISTRATION_ERROR = f"{type(_procedural_error).__name__}: {_procedural_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_procedural_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_procedural_names}

# Spatial fade authoring has its own optional failure boundary.
FIELD_FADE_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.field_fade import initialize_field_fade_node_registration

    _fade_mappings, _fade_names = initialize_field_fade_node_registration()
    if set(_fade_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Field Fade node names collide with registered nodes")
except Exception as _fade_error:
    FIELD_FADE_REGISTRATION_ERROR = f"{type(_fade_error).__name__}: {_fade_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_fade_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_fade_names}

# Retained binary presets have a separate manifest and failure boundary.
PRESET_FIELD_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.preset_field_source import initialize_preset_field_node_registration

    _preset_mappings, _preset_names = initialize_preset_field_node_registration()
    if set(_preset_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Preset Field node names collide with registered nodes")
except Exception as _preset_error:
    PRESET_FIELD_REGISTRATION_ERROR = f"{type(_preset_error).__name__}: {_preset_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_preset_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_preset_names}

# Inline Painted Field is isolated from other nodes, routes and admission.
PAINTED_FIELD_REGISTRATION_ERROR = None
try:
    from conditioning_layers.comfyui.painted_field_source import initialize_painted_field_node_registration

    _painted_mappings, _painted_names = initialize_painted_field_node_registration()
    if set(_painted_mappings) & set(NODE_CLASS_MAPPINGS):
        raise RuntimeError("Painted Field node names collide with registered nodes")
except Exception as _painted_error:
    PAINTED_FIELD_REGISTRATION_ERROR = f"{type(_painted_error).__name__}: {_painted_error}"
else:
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **_painted_mappings}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **_painted_names}

# Qualification invocation is a separate owner-only, opt-in tooling boundary.
# Ordinary startup never imports it or issues authorization. A failed optional
# registration cannot unwind sidebar, Blend or readiness registration above.
P3D_QUALIFICATION_BRIDGE_REGISTRATION_ERROR = None
if os.environ.get("CONDITIONING_LAYERS_P3D_QUALIFICATION_BRIDGE") == "1":
    try:
        _qualification_tooling_root = str(_PACKAGE_ROOT / "tests" / "tooling")
        if _qualification_tooling_root not in sys.path:
            sys.path.insert(0, _qualification_tooling_root)
        from p3d_blend_invocation_bridge import register_invocation_route

        register_invocation_route()
    except Exception as _bridge_error:
        # Store only the exception type: registration may have issued a secret.
        P3D_QUALIFICATION_BRIDGE_REGISTRATION_ERROR = type(_bridge_error).__name__

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
