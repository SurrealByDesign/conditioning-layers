from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = ROOT / "src" / "conditioning_layers"
COMFYUI_DIRECTORY = PACKAGE_ROOT / "comfyui"
INWARD_DIRECTORIES = tuple(
    PACKAGE_ROOT / name
    for name in ("domain", "persistence", "capabilities", "assets", "adapters")
)
BANNED_IMPORT_ROOTS = {
    "av",
    "comfy",
    "comfyui",
    "execution",
    "frontend",
    "krea",
    "numpy",
    "PIL",
    "requests",
    "torch",
}
BLEND_NODE_RUNTIME = "prediction_mixing/blend_node.py"
BLEND_NODE_RUNTIME_IMPORTS = {"comfy", "torch", "numpy", "av"}
# ADR-0028 Slice B adds exactly one offline generalized node runtime, never
# host-registered, with the same function-local runtime dependencies.
GENERALIZED_BLEND_NODE_RUNTIME = "prediction_mixing/generalized_blend_node.py"
# Node System Phase 1 adds one layer-node runtime; it needs only Torch and
# comfy.model_management, both function-local like the Blend runtimes.
LAYER_NODE_RUNTIME = "prediction_mixing/layer_nodes/nodes.py"
LAYER_NODE_RUNTIME_IMPORTS = {"comfy", "torch"}
FIELD_SOURCE_RUNTIME = "influence_field_sources.py"
FIELD_OPERATION_RUNTIMES = ("field_transform.py", "field_repeat.py", "field_remap.py", "field_blur.py", "field_fade.py")
OPTIONAL_NODE_RUNTIMES = (BLEND_NODE_RUNTIME, GENERALIZED_BLEND_NODE_RUNTIME, LAYER_NODE_RUNTIME, FIELD_SOURCE_RUNTIME) + FIELD_OPERATION_RUNTIMES
ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "ast",
    "collections",
    "conditioning_layers",
    "dataclasses",
    "decimal",
    "enum",
    "hashlib",
    "json",
    "math",
    "pathlib",
    "re",
    "sys",
    "typing",
    "types",
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


class ComfyUIArchitectureTests(unittest.TestCase):
    def test_inward_packages_do_not_import_comfyui_generation(self) -> None:
        offenders: list[str] = []
        for directory in INWARD_DIRECTORIES:
            for path in directory.rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                if "conditioning_layers.comfyui" in text or "..comfyui" in text:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_generation_uses_only_standard_library_and_inward_imports(self) -> None:
        # The ADR-0013 operational boundary is explicitly enumerated here;
        # its dedicated architecture tests apply the tighter import policy.
        operational_extra_roots = {
            # ADR-0026 owns one optional, isolated runtime node. Metadata graph
            # authority continues to reject all tensor/host imports.
            BLEND_NODE_RUNTIME: BLEND_NODE_RUNTIME_IMPORTS,
            GENERALIZED_BLEND_NODE_RUNTIME: BLEND_NODE_RUNTIME_IMPORTS,
            LAYER_NODE_RUNTIME: LAYER_NODE_RUNTIME_IMPORTS,
            FIELD_SOURCE_RUNTIME: {"torch"},
            **{runtime: {"torch"} for runtime in FIELD_OPERATION_RUNTIMES},
            "prediction_mixing/blend_preparation.py": {"struct"},
            "prediction_mixing/bundle_assembly_v2/assembler.py": {"os"},
            "prediction_mixing/bundle_assembly_v2/filesystem.py": {
                "os",
                "secrets",
                "stat",
            },
            "prediction_mixing/bundle_assembly_v2/windows_filesystem.py": {
                "ctypes",
                "msvcrt",
                "os",
            },
            # ADR-0016 phase 8 permits only read-side descriptor inspection
            # in this exact private acquisition module.
            "prediction_mixing/runtime_qualification_v2/filesystem.py": {
                "os",
            },
            # ADR-0014 phase 7 permits bounded read-only loopback requests only
            # in these exact route-specific private acquisition modules.
            # `requests` stays in BANNED_IMPORT_ROOTS, and `socket` and `urllib`
            # stay outside the allowance, so the widening reaches the standard-
            # library client and nothing else.
            "prediction_mixing/runtime_qualification_v2/system_stats.py": {
                "http",
            },
            "prediction_mixing/runtime_qualification_v2/object_info.py": {
                "http",
            },
            # ADR-0029 section 3: the canonical anchor extractor fixes its
            # parser-warning handling, so a process warning filter such as
            # -W error cannot change an observation. It reads no file.
            "prediction_mixing/host_compatibility/extractor.py": {"warnings"},
        }
        unexpected: dict[str, set[str]] = {}
        for path in COMFYUI_DIRECTORY.rglob("*.py"):
            relative = path.relative_to(COMFYUI_DIRECTORY).as_posix()
            allowed = ALLOWED_IMPORT_ROOTS | operational_extra_roots.get(
                relative, set()
            )
            outside = imported_roots(path) - allowed
            if outside:
                unexpected[relative] = outside
        self.assertEqual(unexpected, {})

    def test_generation_imports_no_host_image_tensor_ui_or_client_runtime(self) -> None:
        banned: dict[str, set[str]] = {}
        for path in COMFYUI_DIRECTORY.rglob("*.py"):
            matches = imported_roots(path) & BANNED_IMPORT_ROOTS
            relative = path.relative_to(COMFYUI_DIRECTORY).as_posix()
            if relative == FIELD_SOURCE_RUNTIME or relative in FIELD_OPERATION_RUNTIMES:
                matches -= {"torch"}
            elif relative == LAYER_NODE_RUNTIME:
                matches -= LAYER_NODE_RUNTIME_IMPORTS
            elif relative in OPTIONAL_NODE_RUNTIMES:
                matches -= BLEND_NODE_RUNTIME_IMPORTS
            if matches:
                banned[str(path.relative_to(COMFYUI_DIRECTORY))] = matches
        self.assertEqual(banned, {})

    def test_optional_blend_runtime_dependencies_are_function_local(self) -> None:
        for runtime in OPTIONAL_NODE_RUNTIMES:
            path = COMFYUI_DIRECTORY / runtime
            tree = ast.parse(path.read_text(encoding="utf-8"))
            top_level = ast.Module(body=[node for node in tree.body
                                       if isinstance(node, (ast.Import, ast.ImportFrom))], type_ignores=[])
            roots = {alias.name.split(".", 1)[0] for node in top_level.body
                     if isinstance(node, ast.Import) for alias in node.names}
            roots.update(node.module.split(".", 1)[0] for node in top_level.body
                         if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module)
            self.assertEqual(roots & BLEND_NODE_RUNTIME_IMPORTS, set(), runtime)

    def test_importing_generator_loads_no_banned_runtime(self) -> None:
        importlib.import_module("conditioning_layers.comfyui.prediction_mixing")
        loaded_roots = {name.split(".", 1)[0] for name in sys.modules}
        self.assertEqual(loaded_roots & BANNED_IMPORT_ROOTS, set())

    def test_no_runtime_dependency_manifest_was_added(self) -> None:
        manifests = {
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "Pipfile",
            "poetry.lock",
            "uv.lock",
        }
        self.assertEqual({name for name in manifests if (ROOT / name).exists()}, set())


if __name__ == "__main__":
    unittest.main()
