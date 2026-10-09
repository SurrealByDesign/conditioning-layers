from __future__ import annotations

import ast
import base64
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).parents[4]
FRONTEND = ROOT / "web" / "js" / "conditioning_layers.js"
STORE = ROOT / "web" / "js" / "layer_draft.js"
PREVIEW = ROOT / "web" / "js" / "field_preview.js"


def run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def module_data_url(path: Path) -> str:
    return "data:text/javascript;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


class FrontendArchitectureTests(unittest.TestCase):
    def test_validated_sidebar_contract_and_compatibility_are_isolated(self) -> None:
        source = FRONTEND.read_text(encoding="utf-8")
        self.assertIn("extensionManager?.sidebarTab?.registerSidebarTab", source)
        self.assertIn("extensionManager?.registerSidebarTab", source)
        self.assertIn('type: "custom"', source)
        self.assertIn("function registerSidebarCompatibility", source)
        self.assertIn("app.registerExtension", source)

    def test_dynamic_store_preserves_state_across_add_remove_and_reorder(self) -> None:
        encoded = base64.b64encode(STORE.read_bytes()).decode("ascii")
        script = f"""
          const module = await import('data:text/javascript;base64,{encoded}');
          let index = 0;
          const store = module.createLayerStore(() => `row-${{++index}}`);
          const a = store.addLayer(); const b = store.addLayer(); const c = store.addLayer();
          a.promptText = 'A'; a.strength = 0.25; a.active = false; a.field = {{name:'a', type:'image/png', size:1}};
          b.promptText = 'B'; b.strength = 0.5; b.field = {{name:'b', type:'image/png', size:1}};
          c.promptText = 'C'; c.strength = 1; c.field = {{name:'c', type:'image/png', size:1}};
          store.moveLayer(c.rowId, -1); store.moveLayer(c.rowId, -1);
          store.removeLayer(b.rowId);
          for (let i = 0; i < 100; i++) store.addLayer();
          const request = store.toRequest('Base', 'key');
          console.log(JSON.stringify({{
            first: request.layers[0], second: request.layers[1], count: request.layers.length,
            removedFileCleared: b.field === null
          }}));
        """
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["first"]["row_id"], "row-3")
        self.assertEqual(result["first"]["prompt_text"], "C")
        self.assertEqual(result["second"]["row_id"], "row-1")
        self.assertEqual(result["second"]["strength"], 0.25)
        self.assertFalse(result["second"]["active"])
        self.assertEqual(result["count"], 102)
        self.assertTrue(result["removedFileCleared"])

    def test_generate_guard_and_no_javascript_capability_rule(self) -> None:
        source = FRONTEND.read_text(encoding="utf-8")
        store = STORE.read_text(encoding="utf-8")
        self.assertIn("if (state.pending || state.blocked) return", source)
        self.assertIn("generateButton.disabled", source)
        self.assertNotIn("active-layer", source.casefold())
        self.assertNotIn("maximum_tested", source)
        self.assertNotIn("layers.length > 2", source)
        self.assertNotIn("layers.length > 2", store)

    def test_minimal_persistence_controls_and_document_projection_are_present(self) -> None:
        source = FRONTEND.read_text(encoding="utf-8")
        for label in ("New Document", "Save", "Save As", "Open"):
            self.assertIn(f'"{label}"', source)
        self.assertIn("/conditioning-layers/documents", source)
        self.assertIn('aria-label", "Document name"', source)
        self.assertNotIn("globalThis.prompt", source)
        # Slice 10C authorizes field previews; the other document-manager
        # increments remain deferred.
        for deferred in ("recent files", "search documents", "rename document", "delete document"):
            self.assertNotIn(deferred, source.casefold())
        self.assertNotIn("webkitdirectory", source)
        self.assertNotIn("filesystem_path", source)

    def test_open_projection_rebuilds_order_disabled_strength_and_persisted_fields(self) -> None:
        encoded = base64.b64encode(STORE.read_bytes()).decode("ascii")
        script = f"""
          const module = await import('data:text/javascript;base64,{encoded}');
          let index = 0;
          const store = module.createLayerStore(() => `row-${{++index}}`);
          store.replaceFromDocument({{layers: [
            {{layer_id:'layer-b', name:'B', prompt_text:'Prompt B', strength:0.375, active:false, field_persisted:true}},
            {{layer_id:'layer-a', name:'A', prompt_text:'Prompt A', strength:1, active:true, field_persisted:true}}
          ]}});
          const request = store.toRequest('Base', 'key', {{documentKey:'study', documentId:'document-1'}});
          console.log(JSON.stringify(request));
        """
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["document_key"], "study")
        self.assertEqual([item["layer_id"] for item in result["layers"]], ["layer-b", "layer-a"])
        self.assertFalse(result["layers"][0]["active"])
        self.assertEqual(result["layers"][0]["strength"], 0.375)
        self.assertTrue(result["layers"][0]["retained_field"])
        self.assertIsNone(result["layers"][0]["field_part"])

    def test_preview_state_transitions_and_stale_load_guard(self) -> None:
        script = f"""
          const module = await import('{module_data_url(PREVIEW)}');
          let created = 0;
          const revoked = [];
          const registry = module.createPreviewRegistry(
            (file) => `blob:${{file.name}}-${{++created}}`,
            (url) => revoked.push(url),
          );
          const states = [];
          states.push(registry.get('r1'));
          const loading = registry.setUpload('r1', {{name: 'field.png'}});
          states.push(registry.get('r1').state);
          const staleUrl = loading.url;
          registry.markLoaded('r1', staleUrl, 128, 128);
          states.push({{...registry.get('r1')}});
          registry.setUpload('r1', {{name: 'replacement.png'}});
          const ignoredStale = registry.markLoaded('r1', staleUrl, 64, 64);
          states.push(registry.get('r1').state);
          registry.markFailed('r1', registry.get('r1').url, 'broken');
          states.push({{...registry.get('r1')}});
          registry.clearField('r1');
          states.push(registry.get('r1').state);
          console.log(JSON.stringify({{states, revoked, ignoredStale, created}}));
        """
        result = run_node(script)
        self.assertIsNone(result["states"][0])
        self.assertEqual(result["states"][1], "loading")
        self.assertEqual(result["states"][2]["state"], "valid")
        self.assertEqual(result["states"][2]["width"], 128)
        self.assertEqual(result["states"][3], "loading")
        self.assertEqual(result["states"][4]["state"], "invalid")
        self.assertEqual(result["states"][4]["message"], "broken")
        self.assertEqual(result["states"][5], "none")
        self.assertIsNone(result["ignoredStale"])
        self.assertEqual(result["revoked"], ["blob:field.png-1", "blob:replacement.png-2"])

    def test_preview_cleanup_on_replace_remove_and_release_all(self) -> None:
        script = f"""
          const module = await import('{module_data_url(PREVIEW)}');
          let created = 0;
          const revoked = [];
          const registry = module.createPreviewRegistry(
            () => `blob:${{++created}}`,
            (url) => revoked.push(url),
          );
          registry.setUpload('a', {{name: 'a.png'}});
          registry.setUpload('a', {{name: 'a2.png'}});
          registry.setUpload('b', {{name: 'b.png'}});
          registry.setPersisted('c', '/conditioning-layers/documents/study/fields/layer-1');
          registry.release('a');
          const afterRelease = registry.get('a');
          registry.releaseAll();
          console.log(JSON.stringify({{
            revoked,
            afterRelease,
            persistedGone: registry.get('c'),
            persistedUrlNeverRevoked: !revoked.some((url) => url.startsWith('/conditioning-layers')),
          }}));
        """
        result = run_node(script)
        self.assertEqual(result["revoked"], ["blob:1", "blob:2", "blob:3"])
        self.assertIsNone(result["afterRelease"])
        self.assertIsNone(result["persistedGone"])
        self.assertTrue(result["persistedUrlNeverRevoked"])

    def test_preview_association_survives_reorder_and_never_enters_payloads(self) -> None:
        script = f"""
          const store_module = await import('{module_data_url(STORE)}');
          const preview_module = await import('{module_data_url(PREVIEW)}');
          let index = 0;
          const store = store_module.createLayerStore(() => `row-${{++index}}`);
          const registry = preview_module.createPreviewRegistry(
            (file) => `blob:${{file.name}}`,
            () => {{}},
          );
          const a = store.addLayer(); const b = store.addLayer();
          a.field = {{name: 'a.png', type: 'image/png', size: 1}};
          b.field = {{name: 'b.png', type: 'image/png', size: 1}};
          registry.setUpload(a.rowId, a.field);
          registry.setUpload(b.rowId, b.field);
          const before = JSON.stringify(store.toRequest('Base', 'key'));
          store.moveLayer(b.rowId, -1);
          const request = store.toRequest('Base', 'key');
          const keys = new Set();
          for (const layer of request.layers) Object.keys(layer).forEach((key) => keys.add(key));
          console.log(JSON.stringify({{
            firstRow: request.layers[0].row_id,
            firstPreview: registry.get(request.layers[0].row_id).url,
            secondPreview: registry.get(request.layers[1].row_id).url,
            payloadKeys: [...keys].sort(),
            payloadUnchangedByPreviews: before === JSON.stringify((() => {{
              registry.markLoaded(a.rowId, 'blob:a.png', 128, 128);
              store.moveLayer(b.rowId, 1);
              return store.toRequest('Base', 'key');
            }})()),
          }}));
        """
        result = run_node(script)
        self.assertEqual(result["firstRow"], "row-2")
        self.assertEqual(result["firstPreview"], "blob:b.png")
        self.assertEqual(result["secondPreview"], "blob:a.png")
        self.assertEqual(
            result["payloadKeys"],
            sorted([
                "row_id",
                "layer_id",
                "name",
                "prompt_text",
                "strength",
                "active",
                "field_part",
                "retained_field",
            ]),
        )
        self.assertTrue(result["payloadUnchangedByPreviews"])

    def test_open_projection_carries_field_url_without_serializing_it(self) -> None:
        script = f"""
          const module = await import('{module_data_url(STORE)}');
          let index = 0;
          const store = module.createLayerStore(() => `row-${{++index}}`);
          store.replaceFromDocument({{layers: [
            {{layer_id: 'layer-a', name: 'A', prompt_text: 'Prompt', strength: 1,
              active: true, field_persisted: true,
              field_url: '/conditioning-layers/documents/study/fields/layer-a'}},
          ]}});
          const request = store.toRequest('Base', 'key', {{documentKey: 'study', documentId: 'doc'}});
          console.log(JSON.stringify({{
            fieldUrl: store.layers[0].fieldUrl,
            serialized: JSON.stringify(request).includes('field_url'),
          }}));
        """
        result = run_node(script)
        self.assertEqual(result["fieldUrl"], "/conditioning-layers/documents/study/fields/layer-a")
        self.assertFalse(result["serialized"])

    def test_no_visible_node_framework_or_bridge(self) -> None:
        loader = (ROOT / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(loader)
        assignments = {
            target.id: node.value
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            for target in (node.target,)
        }
        self.assertIsInstance(assignments["NODE_CLASS_MAPPINGS"], ast.Dict)
        self.assertEqual(len(assignments["NODE_CLASS_MAPPINGS"].keys), 0)
        imports = [line for line in FRONTEND.read_text(encoding="utf-8").splitlines() if line.startswith("import ")]
        self.assertEqual(len(imports), 4)
        self.assertTrue(
            all(
                "scripts/" in line or "layer_draft.js" in line or "field_preview.js" in line
                for line in imports
            )
        )
        self.assertFalse(any((ROOT / name).exists() for name in ("package.json", "vite.config.js", "webpack.config.js")))


if __name__ == "__main__":
    unittest.main()
