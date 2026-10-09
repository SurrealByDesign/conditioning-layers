"""Public maintenance suites; reuse retained network/process fences."""
import argparse
import p2b_offline
import offline_regressions

GROUPS = {
    **p2b_offline.GROUPS,
    "nodes": ("comfyui/prediction_mixing", (
        "test_layer_nodes_contracts.py", "test_layer_nodes_composition.py",
        "test_field_*.py", "test_influence_field_*.py", "test_painted_field_*.py",
        "test_pattern_field_*.py", "test_preset_field_*.py", "test_procedural_field_*.py",
        "test_noise_field_*.py", "test_scatter_field_codes.py", "test_cyclic_partition_field_*.py",
        "test_polar_partition_field_*.py", "test_voronoi_partition_field_*.py",
        "test_numeric_control_ui_contracts.py")),
    "blend": ("comfyui/prediction_mixing", ("test_blend_*.py",)),
    "node-runtime": ("comfyui/prediction_mixing", ("test_layer_node_runtime.py",)),
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=(*GROUPS, "execution"))
    args = parser.parse_args()
    if args.group == "execution":
        raise SystemExit(offline_regressions.main([args.group]))
    p2b_offline.GROUPS = GROUPS
    raise SystemExit(p2b_offline.main([args.group]))
