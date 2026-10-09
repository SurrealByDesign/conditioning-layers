from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import unittest


CORE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "src" / "conditioning_layers" / "domain"
)
BANNED_IMPORT_ROOTS = {
    "comfy",
    "comfyui",
    "krea",
    "numpy",
    "PIL",
    "torch",
}
ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "dataclasses",
    "decimal",
    "enum",
    "hashlib",
    "json",
    "math",
    "pathlib",
    "re",
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


class CoreImportBoundaryTests(unittest.TestCase):
    def test_core_has_only_standard_library_absolute_imports(self) -> None:
        unexpected: dict[str, set[str]] = {}
        for path in CORE_DIRECTORY.glob("*.py"):
            roots = imported_roots(path)
            outside_boundary = roots - ALLOWED_IMPORT_ROOTS
            if outside_boundary:
                unexpected[path.name] = outside_boundary

        self.assertEqual(unexpected, {})

    def test_core_does_not_import_banned_host_or_backend_modules(self) -> None:
        banned: dict[str, set[str]] = {}
        for path in CORE_DIRECTORY.glob("*.py"):
            matches = imported_roots(path) & BANNED_IMPORT_ROOTS
            if matches:
                banned[path.name] = matches

        self.assertEqual(banned, {})

    def test_importing_core_does_not_load_banned_modules(self) -> None:
        importlib.import_module("conditioning_layers.domain")
        loaded_roots = {name.split(".", 1)[0] for name in sys.modules}

        self.assertEqual(loaded_roots & BANNED_IMPORT_ROOTS, set())


if __name__ == "__main__":
    unittest.main()
