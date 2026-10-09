"""Named abstract ordered-left-fold topology contract for Translation Plan v2."""

from __future__ import annotations

from dataclasses import replace

from .canonical import canonical_json_bytes
from .identity import fingerprint_topology_policy
from .models import (
    TOPOLOGY_POLICY_IDENTIFIER,
    TOPOLOGY_POLICY_VERSION,
    AbstractFoldStep,
    OrderedLeftFoldTopologyPolicy,
)


def serialize_topology_policy(policy: OrderedLeftFoldTopologyPolicy) -> bytes:
    """Serialize the topology descriptor to canonical identity bytes."""

    if not isinstance(policy, OrderedLeftFoldTopologyPolicy):
        raise TypeError("policy must be an OrderedLeftFoldTopologyPolicy")
    return canonical_json_bytes(policy)


def build_ordered_left_fold_schedule(
    condition_count: int,
) -> tuple[AbstractFoldStep, ...]:
    """Build logical fold identities without graph nodes, classes, or links."""

    if (
        isinstance(condition_count, bool)
        or not isinstance(condition_count, int)
        or condition_count < 0
    ):
        raise ValueError("condition_count must be a non-negative integer")
    if condition_count < 2:
        return ()
    steps: list[AbstractFoldStep] = []
    for step_ordinal in range(condition_count - 1):
        steps.append(
            AbstractFoldStep(
                step_ordinal=step_ordinal,
                left_operand=(
                    "condition:0" if step_ordinal == 0 else f"fold:{step_ordinal - 1}"
                ),
                right_condition=f"condition:{step_ordinal + 1}",
                result=f"fold:{step_ordinal}",
            )
        )
    return tuple(steps)


_UNFINGERPRINTED_POLICY = OrderedLeftFoldTopologyPolicy(
    policy_identifier=TOPOLOGY_POLICY_IDENTIFIER,
    policy_version=TOPOLOGY_POLICY_VERSION,
    input_order_source="ordered_active_prompt_layers",
    single_condition_behavior="no_fold_step",
    multiple_condition_strategy="iterative_ordered_left_fold",
    balancing_permitted=False,
    sorting_permitted=False,
    commutation_permitted=False,
    tree_optimization_permitted=False,
    fingerprint="",
)

ORDERED_LEFT_FOLD_TOPOLOGY_POLICY = replace(
    _UNFINGERPRINTED_POLICY,
    fingerprint=fingerprint_topology_policy(_UNFINGERPRINTED_POLICY),
)
