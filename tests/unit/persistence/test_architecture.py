from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_DIRECTORY = ROOT / "src" / "conditioning_layers" / "domain"
PERSISTENCE_DIRECTORY = ROOT / "src" / "conditioning_layers" / "persistence"
BANNED_IMPORT_ROOTS = {
    "comfy",
    "comfyui",
    "krea",
    "numpy",
    "PIL",
    "torch",
}
ALLOWED_PERSISTENCE_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "conditioning_layers",
    "dataclasses",
    "json",
    "math",
    "os",
    "pathlib",
    "re",
    "tempfile",
    "typing",
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


class PersistenceImportBoundaryTests(unittest.TestCase):
    def test_domain_does_not_import_persistence(self) -> None:
        offenders: list[str] = []
        for path in DOMAIN_DIRECTORY.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "conditioning_layers.persistence" in text or "..persistence" in text:
                offenders.append(path.name)

        self.assertEqual(offenders, [])

    def test_persistence_has_only_standard_library_and_core_layer_imports(self) -> None:
        unexpected: dict[str, set[str]] = {}
        for path in PERSISTENCE_DIRECTORY.glob("*.py"):
            outside = imported_roots(path) - ALLOWED_PERSISTENCE_IMPORT_ROOTS
            if outside:
                unexpected[path.name] = outside

        self.assertEqual(unexpected, {})

    def test_persistence_does_not_import_banned_runtime_modules(self) -> None:
        banned: dict[str, set[str]] = {}
        for path in PERSISTENCE_DIRECTORY.glob("*.py"):
            matches = imported_roots(path) & BANNED_IMPORT_ROOTS
            if matches:
                banned[path.name] = matches

        self.assertEqual(banned, {})

    def test_importing_persistence_does_not_load_banned_runtime_modules(self) -> None:
        importlib.import_module("conditioning_layers.persistence")
        loaded_roots = {name.split(".", 1)[0] for name in sys.modules}

        self.assertEqual(loaded_roots & BANNED_IMPORT_ROOTS, set())


if __name__ == "__main__":
    unittest.main()
