"""Node System Phase 1 values: one authored layer and one ordered layer stack.

Pure Python. Conditioning and field tensors are carried opaquely; only the
node runtime inspects them. A layer's identity is the ComfyUI node that
authored it, never its content: two layers with the same prompt or the same
field bytes stay distinct, and one layer cannot be added to a stack twice.
Stack order is authored order. It is kept for repeatability, not priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


LAYER_TYPE = "CONDITIONING_LAYER"
LAYER_STACK_TYPE = "CONDITIONING_LAYER_STACK"


def validate_blend_group(value: object) -> str:
    """One literal group key; empty is the default group, never a membership list."""
    if type(value) is not str or value != value.strip():
        raise ValueError("Blend Group must be one string without leading or trailing whitespace")
    return value


class LayerMode(str, Enum):
    """Per-layer composition mode; see `composition` for the exact rule."""

    BLENDED = "BLENDED"
    FIXED = "FIXED"


@dataclass(frozen=True, slots=True, eq=False)
class LayerDescriptor:
    """One layer branch: ordinary CONDITIONING, its field MASK, Strength, mode."""

    layer_id: str
    conditioning: object
    mask: object
    strength: float
    mode: LayerMode
    enabled: bool = True
    blend_group: str = ""

    def __post_init__(self) -> None:
        if type(self.layer_id) is not str or not self.layer_id.strip():
            raise ValueError("A layer requires the identity of the node that authored it")
        strength = self.strength
        if (type(strength) not in (int, float) or not math.isfinite(strength)
                or not 0 <= strength <= 1):
            raise ValueError(f"Layer {self.layer_id}: Strength must be a finite number in [0, 1]")
        # Both signed zeros are the same authored Strength, as in the retained plans.
        object.__setattr__(self, "strength", 0.0 if strength == 0 else float(strength))
        try:
            mode = LayerMode(self.mode)
        except ValueError:
            raise ValueError(f"Layer {self.layer_id}: mode must be BLENDED or FIXED") from None
        object.__setattr__(self, "mode", mode)
        if type(self.enabled) is not bool:
            raise ValueError(f"Layer {self.layer_id}: enabled must be a boolean")
        validate_blend_group(self.blend_group)


@dataclass(frozen=True, slots=True, eq=False)
class LayerStack:
    """Layers in authored order; built one Add Layer node at a time."""

    layers: tuple[LayerDescriptor, ...]

    def __post_init__(self) -> None:
        if type(self.layers) is not tuple or not self.layers:
            raise ValueError("A layer stack holds one or more layers")
        seen: set[str] = set()
        for layer in self.layers:
            if type(layer) is not LayerDescriptor:
                raise ValueError("A layer stack holds only Conditioning Layer outputs")
            if layer.layer_id in seen:
                raise ValueError(f"Layer {layer.layer_id} is already in this stack; add each layer once")
            seen.add(layer.layer_id)

    def append(self, layer: LayerDescriptor) -> LayerStack:
        return LayerStack(self.layers + (layer,))

    @property
    def enabled_layers(self) -> tuple[LayerDescriptor, ...]:
        return tuple(layer for layer in self.layers if layer.enabled)
