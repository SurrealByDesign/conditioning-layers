"""Node System Phase 1 offline selections using the retained P2B fences.

Developer lane (CPython 3.10.11): node-system. Host lane (the pinned ComfyUI
environment, CPython 3.12.11, real Torch with an in-memory comfy stub):
node-system-runtime. No host, browser, network, model, generation or
qualification execution; only the retained Python -c probes.
"""

import p2b_offline


GROUPS = {
    "node-system": ("comfyui/prediction_mixing", (
        "test_layer_nodes_composition.py", "test_layer_nodes_contracts.py")),
    "node-system-runtime": ("comfyui/prediction_mixing", ("test_layer_node_runtime.py",)),
}


def main():
    p2b_offline.GROUPS = GROUPS
    return p2b_offline.main()


if __name__ == "__main__":
    raise SystemExit(main())
