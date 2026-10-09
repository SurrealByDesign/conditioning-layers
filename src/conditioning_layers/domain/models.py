"""Immutable prototype Conditioning Document value objects.

The models intentionally permit semantically invalid user-authored values so
validation can return all relevant findings at once. Document operations guard
structural misuse and return new documents; they never execute or persist intent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from .composition_policy import (
    REQUIRE_NO_OVERLAP,
    CompositionPolicyError,
    CompositionPolicyRecord,
    CompositionPolicyReference,
    resolve_composition_policy,
)
from .errors import (
    DomainOperationError,
    DuplicateLayerIdError,
    InvalidLayerPositionError,
    LayerNotFoundError,
)


@dataclass(frozen=True, slots=True)
class PrototypeDocumentVersion:
    """Prototype format version carried as intent, independent of persistence."""

    major: int
    minor: int


CURRENT_PROTOTYPE_VERSION = PrototypeDocumentVersion(major=1, minor=0)
COMPOSITION_POLICY_PROTOTYPE_VERSION = PrototypeDocumentVersion(major=2, minor=0)


@dataclass(frozen=True, slots=True)
class InfluenceFieldAssetReference:
    """Identity metadata for an influence-field asset; no file is accessed."""

    relative_path: str
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class PromptLayer:
    """Artist-authored spatial prompt intent in retained document order."""

    layer_id: str
    name: str
    prompt_text: str
    visible: bool = True
    strength: float = 1.0
    influence_field: InfluenceFieldAssetReference | None = None


@dataclass(frozen=True, slots=True)
class ConditioningDocument:
    """A backend-neutral, copy-on-write prototype Conditioning Document.

    Retained layer position is document order only. It does not express
    execution priority or promise an output change when reordered.
    """

    version: PrototypeDocumentVersion
    document_id: str
    base_prompt: str
    layers: tuple[PromptLayer, ...] = ()
    selected_adapter_id: str | None = None
    adapter_settings: object = field(default_factory=dict)
    composition_policy: CompositionPolicyReference | None = None

    def __post_init__(self) -> None:
        if isinstance(self.layers, list):
            object.__setattr__(self, "layers", tuple(self.layers))
        if isinstance(self.adapter_settings, Mapping):
            object.__setattr__(
                self,
                "adapter_settings",
                MappingProxyType(dict(self.adapter_settings)),
            )

    @property
    def active_layers(self) -> tuple[PromptLayer, ...]:
        """Return layers requesting execution participation, in document order."""

        if not isinstance(self.layers, tuple):
            return ()
        return tuple(
            layer
            for layer in self.layers
            if isinstance(layer, PromptLayer) and layer.visible is True
        )

    def add_layer(
        self,
        layer: PromptLayer,
        position: int | None = None,
    ) -> ConditioningDocument:
        """Add a layer at a deterministic position, or append it by default."""

        self._require_operable_layers()
        if not isinstance(layer, PromptLayer):
            raise DomainOperationError("add_layer requires a PromptLayer")
        self._require_new_layer_id(layer.layer_id)

        insertion = len(self.layers) if position is None else position
        if (
            isinstance(insertion, bool)
            or not isinstance(insertion, int)
            or not 0 <= insertion <= len(self.layers)
        ):
            raise InvalidLayerPositionError(
                f"add position must be between 0 and {len(self.layers)}"
            )

        layers = list(self.layers)
        layers.insert(insertion, layer)
        return replace(self, layers=tuple(layers))

    def remove_layer(self, layer_id: str) -> ConditioningDocument:
        """Remove exactly one identified layer."""

        index = self._layer_index(layer_id)
        return replace(self, layers=self.layers[:index] + self.layers[index + 1 :])

    def duplicate_layer(
        self,
        layer_id: str,
        new_layer_id: str,
    ) -> ConditioningDocument:
        """Copy editable properties into a new identity immediately after source."""

        index = self._layer_index(layer_id)
        self._require_new_layer_id(new_layer_id)
        duplicate = replace(self.layers[index], layer_id=new_layer_id)
        layers = list(self.layers)
        layers.insert(index + 1, duplicate)
        return replace(self, layers=tuple(layers))

    def move_layer(self, layer_id: str, new_position: int) -> ConditioningDocument:
        """Move a layer to an exact final document position."""

        index = self._layer_index(layer_id)
        if (
            isinstance(new_position, bool)
            or not isinstance(new_position, int)
            or not 0 <= new_position < len(self.layers)
        ):
            raise InvalidLayerPositionError(
                f"move position must be between 0 and {len(self.layers) - 1}"
            )

        layers = list(self.layers)
        layer = layers.pop(index)
        layers.insert(new_position, layer)
        return replace(self, layers=tuple(layers))

    def toggle_visibility(self, layer_id: str) -> ConditioningDocument:
        """Toggle whether one layer requests execution participation."""

        index = self._layer_index(layer_id)
        layer = self.layers[index]
        if not isinstance(layer.visible, bool):
            raise DomainOperationError(
                "cannot toggle Visibility until the layer has a boolean value"
            )
        return self._replace_layer(index, replace(layer, visible=not layer.visible))

    def update_strength(
        self,
        layer_id: str,
        strength: float,
    ) -> ConditioningDocument:
        """Set requested Strength without assigning perceptual semantics."""

        index = self._layer_index(layer_id)
        return self._replace_layer(
            index,
            replace(self.layers[index], strength=strength),
        )

    def update_prompt_text(
        self,
        layer_id: str,
        prompt_text: str,
    ) -> ConditioningDocument:
        """Replace one layer's artist-authored prompt text."""

        index = self._layer_index(layer_id)
        return self._replace_layer(
            index,
            replace(self.layers[index], prompt_text=prompt_text),
        )

    def update_layer_name(
        self,
        layer_id: str,
        name: str,
    ) -> ConditioningDocument:
        """Replace an artist-facing layer name without altering prompt text."""

        index = self._layer_index(layer_id)
        return self._replace_layer(index, replace(self.layers[index], name=name))

    def update_base_prompt(self, base_prompt: str) -> ConditioningDocument:
        """Replace document-level Base Prompt intent."""

        return replace(self, base_prompt=base_prompt)

    def _replace_layer(
        self,
        index: int,
        layer: PromptLayer,
    ) -> ConditioningDocument:
        layers = list(self.layers)
        layers[index] = layer
        return replace(self, layers=tuple(layers))

    def _layer_index(self, layer_id: str) -> int:
        self._require_operable_layers()
        matches = [
            index
            for index, layer in enumerate(self.layers)
            if layer.layer_id == layer_id
        ]
        if not matches:
            raise LayerNotFoundError(f"layer not found: {layer_id!r}")
        if len(matches) > 1:
            raise DomainOperationError(
                f"cannot operate on duplicate layer identity: {layer_id!r}"
            )
        return matches[0]

    def _require_new_layer_id(self, layer_id: str) -> None:
        if not isinstance(layer_id, str) or not layer_id.strip():
            raise DomainOperationError("new layer ID must be a non-empty string")
        if any(layer.layer_id == layer_id for layer in self.layers):
            raise DuplicateLayerIdError(f"duplicate layer ID: {layer_id!r}")

    def _require_operable_layers(self) -> None:
        if not isinstance(self.layers, tuple) or not all(
            isinstance(layer, PromptLayer) for layer in self.layers
        ):
            raise DomainOperationError(
                "document layer collection must validate before editing operations"
            )


def get_effective_composition_policy(
    document: ConditioningDocument,
) -> CompositionPolicyRecord:
    """Resolve document intent; only retained 1.0 has an implicit default.

    This pure compatibility projection never edits the document or grants
    execution support. Successor intent must be explicit even for No Overlap.
    """

    if not isinstance(document, ConditioningDocument):
        raise TypeError("get_effective_composition_policy requires a ConditioningDocument")
    if (
        type(document.version) is not PrototypeDocumentVersion
        or type(document.version.major) is not int
        or type(document.version.minor) is not int
    ):
        raise CompositionPolicyError(
            "composition_policy.document_version.unsupported",
            "Composition Policy requires an exact supported prototype document version.",
        )
    if document.version == CURRENT_PROTOTYPE_VERSION:
        if document.composition_policy is not None:
            raise CompositionPolicyError(
                "composition_policy.legacy_explicit",
                "Explicit Composition Policy requires prototype document version 2.0.",
            )
        return REQUIRE_NO_OVERLAP
    if document.version != COMPOSITION_POLICY_PROTOTYPE_VERSION:
        raise CompositionPolicyError(
            "composition_policy.document_version.unsupported",
            "Composition Policy cannot be resolved for this prototype document version.",
        )
    if document.composition_policy is None:
        raise CompositionPolicyError(
            "composition_policy.required",
            "Prototype document version 2.0 requires an explicit Composition Policy.",
        )
    return resolve_composition_policy(document.composition_policy)
