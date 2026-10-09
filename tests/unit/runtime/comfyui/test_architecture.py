from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = ROOT / "src" / "conditioning_layers"
RUNTIME_DIRECTORY = PACKAGE_ROOT / "runtime"
INWARD_DIRECTORIES = tuple(
    PACKAGE_ROOT / name
    for name in (
        "domain",
        "persistence",
        "capabilities",
        "assets",
        "adapters",
        "comfyui",
    )
)
BANNED_IMPORT_ROOTS = {
    "PIL",
    "aiohttp",
    "comfy",
    "execution",
    "frontend",
    "httpx",
    "krea",
    "numpy",
    "requests",
    "socket",
    "subprocess",
    "torch",
    "urllib",
}
ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "conditioning_layers",
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "os",
    "pathlib",
    "re",
    "shutil",
    "tempfile",
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


class RuntimeArchitectureTests(unittest.TestCase):
    def test_inward_packages_do_not_import_runtime(self) -> None:
        offenders: list[str] = []
        for directory in INWARD_DIRECTORIES:
            for path in directory.rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                if "conditioning_layers.runtime" in text or "..runtime" in text:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_runtime_uses_only_standard_library_and_declared_inward_imports(
        self,
    ) -> None:
        unexpected: dict[str, set[str]] = {}
        for path in RUNTIME_DIRECTORY.rglob("*.py"):
            # ADR-0026's route-specific availability observation reads process
            # argv and the actual registered project class, without host imports.
            allowed = ALLOWED_IMPORT_ROOTS | (
                {"sys"} if path.relative_to(RUNTIME_DIRECTORY).as_posix() == "comfyui/blend.py" else set()
            )
            outside = imported_roots(path) - allowed
            if outside:
                unexpected[str(path.relative_to(RUNTIME_DIRECTORY))] = outside
        self.assertEqual(unexpected, {})

    def test_runtime_imports_no_host_tensor_image_ui_http_or_execution_runtime(
        self,
    ) -> None:
        banned: dict[str, set[str]] = {}
        for path in RUNTIME_DIRECTORY.rglob("*.py"):
            matches = imported_roots(path) & BANNED_IMPORT_ROOTS
            if matches:
                banned[str(path.relative_to(RUNTIME_DIRECTORY))] = matches
        self.assertEqual(banned, {})

    def test_importing_runtime_loads_no_banned_runtime(self) -> None:
        before = set(sys.modules)
        importlib.import_module("conditioning_layers.runtime.comfyui")
        newly_loaded_roots = {
            name.split(".", 1)[0] for name in set(sys.modules) - before
        }
        self.assertEqual(newly_loaded_roots & BANNED_IMPORT_ROOTS, set())

    def test_no_dependency_manifest_was_added(self) -> None:
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
