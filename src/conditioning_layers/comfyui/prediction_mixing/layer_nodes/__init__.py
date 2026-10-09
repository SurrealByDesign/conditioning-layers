"""Node System Phase 1: visible ComfyUI layer nodes over the retained Blend math.

Ordinary prompt, CLIP and LoRA nodes feed Conditioning Layer nodes; Add
Conditioning Layer chains them into an ordered stack of any positive length;
Compose Conditioning Layers feeds KSampler. Per layer, FIXED owns its positive
field samples exclusively and BLENDED shares the rest by the retained exact
normalized field x Strength rule.

Registration here is node availability only. It is separate from product
admission, the panel, document composition policy and host selection, none of
which this package reads or changes. Importing it never imports Torch or
ComfyUI.
"""

from .composition import LayerCompositionError, compose_field_codes, fixed_overlaps
from .models import LAYER_STACK_TYPE, LAYER_TYPE, LayerDescriptor, LayerMode, LayerStack
from .nodes import (
    FIELD_SHAPE, LAYER_NODE_CLASS_NAMES, UPSTREAM_METADATA,
    ConditioningLayersAddLayer, ConditioningLayersCompose, ConditioningLayersLayer,
    initialize_layer_node_registration,
)
from .workflow import (
    LayerWorkflowSpec, build_layer_node_workflow, describe_graph_input, fingerprint_semantics,
    layer_workflow_semantics, sampler_semantics, validate_layer_node_workflow,
)
