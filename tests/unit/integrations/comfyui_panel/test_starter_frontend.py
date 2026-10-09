from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from conditioning_layers.integrations.comfyui_panel.guidance import panel_capability_guidance
from conditioning_layers.integrations.comfyui_panel.starter_fields import product_field_presets


ROOT = Path(__file__).parents[4]
FRONTEND = ROOT / "web/js/conditioning_layers.js"
STORE = ROOT / "web/js/layer_draft.js"
PREVIEW = ROOT / "web/js/field_preview.js"
LIBRARY = ROOT / "influence-field-library/v1"
MANIFEST = LIBRARY / "manifests/two-layer.left-right.v1.manifest.json"


def module_data_url(source: bytes) -> str:
    return "data:text/javascript;base64," + base64.b64encode(source).decode("ascii")


def run_node(script: str) -> dict:
    # stdin avoids the Windows command-line length limit for the sidebar module.
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def starter_fixture() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fields = {field["asset_id"]: field for field in manifest["fields"]}
    return {
        side: {
            "id": f"two-layer.left-right.v1:{asset_id}",
            "sha256": fields[asset_id]["sha256"],
            "bytes": base64.b64encode(
                (LIBRARY / fields[asset_id]["filename"]).read_bytes()
            ).decode("ascii"),
        }
        for side, asset_id in (("left", "A"), ("right", "B"))
    }


def store_script(body: str) -> str:
    return f"""
      import {{ createHash }} from 'node:crypto';
      const {{ createLayerStore, loadPresetCatalog, loadPresetField }} = await import(
        {json.dumps(module_data_url(STORE.read_bytes()))}
      );
      const {{ createPreviewRegistry }} = await import(
        {json.dumps(module_data_url(PREVIEW.read_bytes()))}
      );
      const assets = {json.dumps(starter_fixture())};
      const presets = {json.dumps([preset.to_json() for preset in product_field_presets()])};
      // Historical fixture shorthand calls the generic loader, never a UI list.
      const loadStarterField = (side, fetch) => loadPresetField(assets[side]?.id ?? side, presets, fetch);
      const calls = [];
      const fetchStarter = async (url) => {{
        calls.push(url);
        const id = decodeURIComponent(url.split('/').at(-1));
        const side = Object.keys(assets).find(key => assets[key].id === id);
        if (!assets[side]) throw new Error(`Unexpected route ${{url}}`);
        return new Response(Buffer.from(assets[side].bytes, 'base64'), {{
          headers: {{'Content-Type': 'image/png'}},
        }});
      }};
      const digest = async (file) => createHash('sha256')
        .update(Buffer.from(await file.arrayBuffer())).digest('hex');
      const parts = async (form) => ({{
        request: JSON.parse(await form.get('request').text()),
        uploads: await Promise.all([...form.entries()]
          .filter(([key]) => key !== 'request')
          .map(async ([key, file]) => ({{key, type:file.type, sha256:await digest(file)}}))),
      }});
      {body}
    """


def sidebar_script(body: str, *, before_render: str = "") -> str:
    source = FRONTEND.read_text(encoding="utf-8")
    source = source.replace(
        'import { app } from "../../../scripts/app.js";',
        'const app = globalThis.testApp;',
    ).replace(
        'import { api } from "../../../scripts/api.js";',
        'const api = globalThis.testApi;',
    ).replace(
        '"./layer_draft.js"', json.dumps(module_data_url(STORE.read_bytes()))
    ).replace(
        '"./field_preview.js"', json.dumps(module_data_url(PREVIEW.read_bytes()))
    )
    # Only the host DOM and HTTP boundaries are substituted. The actual sidebar
    # registration, event handlers, draft ingestion, and preview code execute.
    return store_script(f"""
      class Node {{
        constructor(tag) {{
          this.tagName = tag; this.children = []; this.dataset = {{}};
          this.listeners = {{}}; this.attributes = {{}}; this.className = '';
          this._text = ''; this.value = ''; this.disabled = false;
          this.classList = {{
            add: (...names) => {{
              this.className = [...new Set([...this.className.split(' '), ...names])].join(' ');
            }},
            remove: (...names) => {{
              this.className = this.className.split(' ').filter(x => !names.includes(x)).join(' ');
            }},
          }};
        }}
        get textContent() {{ return this._text + this.children.map(x => x.textContent).join(' '); }}
        set textContent(value) {{ this._text = String(value ?? ''); this.replaceChildren(); }}
        append(...nodes) {{ for (const node of nodes) {{ node.remove(); node.parent = this; this.children.push(node); }} }}
        prepend(node) {{ node.remove(); node.parent = this; this.children.unshift(node); }}
        replaceChildren(...nodes) {{
          for (const child of this.children) child.parent = null;
          this.children = []; this.append(...nodes);
        }}
        remove() {{
          if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
          this.parent = null;
        }}
        replaceWith(node) {{
          if (!this.parent) return;
          const parent = this.parent;
          parent.children.splice(parent.children.indexOf(this), 1, node);
          node.parent = parent; this.parent = null;
        }}
        setAttribute(name, value) {{ this.attributes[name] = value; }}
        addEventListener(name, handler) {{ (this.listeners[name] ??= []).push(handler); }}
        async fire(name) {{ for (const handler of this.listeners[name] ?? []) await handler(); }}
        querySelectorAll(selector) {{
          return descendants(this).filter(node => node.className.split(' ').includes(selector.slice(1)));
        }}
      }}
      const descendants = (node) => node.children.flatMap(child => [child, ...descendants(child)]);
      const container = new Node('div');
      const find = (predicate) => descendants(container).find(predicate);
      const button = (label) => find(node => node.tagName === 'button' && node.textContent === label);
      const presetSelect = (index = 0) => container.querySelectorAll('.cl-preset-select')[index];
      const choosePreset = async (label, index = 0) => {{
        const select = presetSelect(index);
        const option = select.children.find(node => node.textContent === label);
        if (!option) throw new Error('Missing preset option: ' + label);
        select.value = option.value;
        await select.fire('change');
      }};
      const fileInput = () => find(node => node.type === 'file');
      const caption = () => find(node => node.className === 'cl-preview-meta');
      const selected = () => find(node => node.className === 'cl-file-name').textContent;
      const tick = () => new Promise(resolve => setImmediate(resolve));
      const settle = async () => {{ await tick(); await tick(); }};
      const revoked = []; const created = [];
      URL.createObjectURL = (file) => {{
        const url = `blob:test-${{created.length + 1}}`;
        created.push({{url, file}}); return url;
      }};
      URL.revokeObjectURL = url => revoked.push(url);
      globalThis.document = {{
        createElement: tag => new Node(tag), head: new Node('head'),
        getElementById: () => ({{id:'conditioning-layers-styles'}}),
      }};
      const guidance = {json.dumps(panel_capability_guidance())};
      const requests = []; const uploads = []; let saved = null; let deferStarter = null;
      let catalogPayload = {{presets}};
      let saveFailure = null; let documentSequence = 0; let layerSequence = 0;
      let extension; let definition;
      globalThis.testApp = {{
        registerExtension: item => {{ extension = item; }},
        extensionManager: {{sidebarTab: {{registerSidebarTab: item => {{ definition = item; }}}}}},
      }};
      globalThis.testApi = {{ fetchApi: async (url, options = {{}}) => {{
        requests.push({{url, method:options.method ?? 'GET'}});
        if (url === '/conditioning-layers/capabilities') return {{ok:true, json:async () => guidance}};
        if (url === '/conditioning-layers/starter-fields') return {{ok:true, json:async () => catalogPayload}};
        if (url.startsWith('/conditioning-layers/starter-fields/')) {{
          if (deferStarter) await deferStarter;
          return fetchStarter(url);
        }}
        if (url === '/conditioning-layers/documents' && !options.method) {{
          return {{ok:true, json:async () => ({{documents:saved ? [saved] : []}})}};
        }}
        if (url.startsWith('/conditioning-layers/documents') && options.body) {{
          if (saveFailure) return {{ok:false, json:async () => saveFailure}};
          const serialized = await parts(options.body); uploads.push(serialized);
          const request = serialized.request;
          const key = options.method === 'PUT' ? request.source_document_key
            : request.display_name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
              .replace(/^-+|-+$/g, '').slice(0,80).replace(/-+$/, '');
          saved = {{document_key:key, document_id:options.method === 'PUT'
              ? request.document_id : `document-${{++documentSequence}}`,
            display_name:key.split('-').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' '),
            base_prompt:request.base_prompt,
            layers:request.layers.map(row => ({{
              layer_id:row.layer_id ?? `layer-${{++layerSequence}}`, name:row.name,
              prompt_text:row.prompt_text, strength:row.strength, active:row.active,
              field_persisted:true,
            }})),
          }};
          for (const layer of saved.layers) {{
            layer.field_url = `/conditioning-layers/documents/${{key}}/fields/${{layer.layer_id}}`;
          }}
          return {{ok:true, json:async () => saved}};
        }}
        if (saved && url === `/conditioning-layers/documents/${{saved.document_key}}`) return {{ok:true, json:async () => saved}};
        throw new Error(`Unexpected HTTP request: ${{url}}`);
      }} }};
      {before_render}
      await import({json.dumps(module_data_url(source.encode('utf-8')))});
      extension.setup();
      const dispose = definition.render(container);
      await settle();
      {body}
    """)


class StarterDraftTests(unittest.TestCase):
    def test_left_and_right_load_the_exact_manifest_png_bytes(self) -> None:
        result = run_node(store_script("""
          const result = {};
          for (const side of ['left', 'right']) {
            const file = await loadStarterField(side, fetchStarter);
            result[side] = {name:file.name, type:file.type, sha256:await digest(file)};
          }
          console.log(JSON.stringify({result, calls}));
        """))
        hashes = {
            "left": "0c519e60efdffbfebbbe2c60235a0f03fb10af8f33d1d3f59c900739ae0fd3e0",
            "right": "b649d32ce6f7481291adaa4b7e68988ade1d9ec53e9624bbf52dd92be628ee4d",
        }
        for side, expected in hashes.items():
            self.assertEqual(starter_fixture()[side]["sha256"], expected)
            self.assertEqual(result["result"][side], {
                "name": f"{side.title()}.png", "type": "image/png", "sha256": expected,
            })
        self.assertEqual(result["calls"], [
            "/conditioning-layers/starter-fields/two-layer.left-right.v1%3AA",
            "/conditioning-layers/starter-fields/two-layer.left-right.v1%3AB",
        ])

    def test_starter_and_manual_import_have_identical_canonical_multipart_state(self) -> None:
        result = run_node(store_script("""
          const comparisons = [];
          for (const side of ['left', 'right']) {
            const store = createLayerStore(() => 'row-a'); const layer = store.addLayer();
            layer.promptText = 'Regional subject'; layer.strength = 0.375; layer.active = false;
            store.assignField(layer.rowId, await loadStarterField(side, fetchStarter));
            const starter = await parts(store.toMultipart('Base', 'key'));
            const starterSave = await parts(store.toDocumentMultipart('Base', 'Study'));
            const stateKeys = Object.keys(layer).sort();
            store.assignField(layer.rowId, new File([Buffer.from(assets[side].bytes, 'base64')],
              'manual.png', {type:'image/png'}));
            const manual = await parts(store.toMultipart('Base', 'key'));
            const manualSave = await parts(store.toDocumentMultipart('Base', 'Study'));
            comparisons.push({starter, manual, starterSave, manualSave, stateKeys});
          }
          console.log(JSON.stringify({comparisons}));
        """))
        for comparison in result["comparisons"]:
            self.assertEqual(comparison["starter"], comparison["manual"])
            self.assertEqual(comparison["starterSave"], comparison["manualSave"])
            row = comparison["starter"]["request"]["layers"][0]
            self.assertEqual(row["field_part"], "field-row-a")
            self.assertFalse(row["retained_field"])
            self.assertEqual(row["strength"], 0.375)
            self.assertFalse(row["active"])
            self.assertEqual(comparison["stateKeys"], sorted([
                "rowId", "layerId", "name", "promptText", "strength", "active",
                "field", "persistedField", "fieldUrl", "presetId",
            ]))

    def test_switches_cancel_and_removed_row_keep_field_ownership_consistent(self) -> None:
        result = run_node(store_script("""
          const store = createLayerStore(() => 'row-a'); const layer = store.addLayer();
          const custom = new File(['custom'], 'custom.png', {type:'image/png'});
          const states = [];
          for (const field of [await loadStarterField('left', fetchStarter), custom,
              await loadStarterField('right', fetchStarter)]) {
            store.assignField(layer.rowId, field);
            states.push({name:layer.field.name, persisted:layer.persistedField, url:layer.fieldUrl});
          }
          const selected = layer.field;
          const cancel = store.assignField(layer.rowId, null);
          const kept = layer.field === selected;
          store.removeLayer(layer.rowId);
          const removed = store.assignField(layer.rowId, custom);
          console.log(JSON.stringify({states, cancel, kept, removed, count:store.layers.length, field:layer.field}));
        """))
        self.assertEqual([state["name"] for state in result["states"]], [
            "Left.png", "custom.png", "Right.png",
        ])
        self.assertTrue(all(not state["persisted"] and state["url"] is None for state in result["states"]))
        self.assertFalse(result["cancel"])
        self.assertTrue(result["kept"])
        self.assertFalse(result["removed"])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["field"])

    def test_existing_document_projection_reopens_and_can_replace_a_retained_field(self) -> None:
        result = run_node(store_script("""
          let index = 0;
          const store = createLayerStore(() => `row-${++index}`);
          store.replaceFromDocument({layers:[
            {layer_id:'layer-b',name:'B',prompt_text:'Prompt B',strength:0.375,active:false,
              field_persisted:true,field_url:'/conditioning-layers/documents/old/fields/layer-b'},
            {layer_id:'layer-a',name:'A',prompt_text:'Prompt A',strength:1,active:true,field_persisted:true},
          ]});
          const state = {documentId:'old-id',documentKey:'old'};
          const before = await parts(store.toMultipart('Old Base','key',state));
          const saved = await parts(store.toDocumentMultipart('Old Base','Old',state));
          const oldUrl = store.layers[0].fieldUrl;
          const absentOldUrl = store.layers[1].fieldUrl;
          store.assignField(store.layers[0].rowId, await loadStarterField('right',fetchStarter));
          const after = await parts(store.toMultipart('Old Base','key',state));
          console.log(JSON.stringify({before,saved,after,oldUrl,absentOldUrl,
            replacementUrl:store.layers[0].fieldUrl}));
        """))
        self.assertEqual(result["before"]["uploads"], [])
        self.assertEqual(result["saved"]["uploads"], [])
        rows = result["before"]["request"]["layers"]
        self.assertEqual([row["layer_id"] for row in rows], ["layer-b", "layer-a"])
        self.assertEqual(rows[0]["strength"], 0.375)
        self.assertFalse(rows[0]["active"])
        self.assertTrue(all(row["retained_field"] and row["field_part"] is None for row in rows))
        self.assertEqual(result["oldUrl"], "/conditioning-layers/documents/old/fields/layer-b")
        self.assertIsNone(result["absentOldUrl"])
        self.assertIsNone(result["replacementUrl"])
        self.assertEqual(result["after"]["uploads"][0]["sha256"], starter_fixture()["right"]["sha256"])
        self.assertFalse(result["after"]["request"]["layers"][0]["retained_field"])
        self.assertTrue(result["after"]["request"]["layers"][1]["retained_field"])

    def test_bad_starter_responses_do_not_produce_a_replacement_file(self) -> None:
        result = run_node(store_script("""
          const failures = [];
          const responses = [
            new Response('missing',{status:404}),
            new Response('wrong',{headers:{'Content-Type':'text/plain'}}),
            new Response(new Uint8Array(0),{headers:{'Content-Type':'image/png'}}),
            new Response(new Uint8Array(8*1024*1024+1),{headers:{'Content-Type':'image/png'}}),
          ];
          for (const response of responses) {
            try { await loadStarterField('left',async () => response); failures.push(null); }
            catch (error) { failures.push(error instanceof Error && error.message); }
          }
          let invalidCalls = 0;
          for (const id of ['../right','top','constructor','__proto__']) {
            try { await loadStarterField(id,async () => { invalidCalls++; }); failures.push(null); }
            catch (error) { failures.push(error.message); }
          }
          console.log(JSON.stringify({failures,invalidCalls}));
        """))
        self.assertTrue(all(result["failures"]))
        self.assertEqual(result["invalidCalls"], 0)


class StarterSidebarTests(unittest.TestCase):
    def test_selector_custom_input_and_preview_transitions_use_actual_handlers(self) -> None:
        result = run_node(sidebar_script("""
          const labels = ['Left','Right'].map(label => presetSelect().children.some(option => option.textContent === label));
          if (button('Left') || button('Right')) throw new Error('Obsolete product buttons');
          const customLabel = fileInput().parent.textContent;
          const sequence = [];
          for (const side of ['Left','Right']) {
            await choosePreset(side);
            const image = find(node => node.tagName === 'img');
            const loading = caption().textContent;
            image.naturalWidth = 128; image.naturalHeight = 128; await image.fire('load');
            sequence.push({selected:selected(),loading,caption:caption().textContent,
              sha256:await digest(created.at(-1).file)});
          }
          fileInput().files = [new File(['custom'], 'artist.png', {type:'image/png'})];
          await fileInput().fire('change');
          const custom = selected(); const customPreview = created.at(-1).url;
          fileInput().files = []; await fileInput().fire('change');
          const cancelled = selected();
          await choosePreset('Left');
          const backToStarter = selected();
          const text = container.textContent;
          dispose();
          console.log(JSON.stringify({labels,customLabel,sequence,custom,cancelled,
            customPreview,backToStarter,text,revoked,created:created.map(x => x.url),requests}));
        """))
        self.assertEqual(result["labels"], [True, True])
        self.assertIn("Custom PNG", result["customLabel"])
        for side, state in zip(("left", "right"), result["sequence"]):
            self.assertEqual(state["selected"], f"Selected preset: {side.title()}")
            self.assertIn("Loading preview", state["loading"])
            self.assertIn("128×128 px", state["caption"])
            self.assertEqual(state["sha256"], starter_fixture()[side]["sha256"])
        self.assertEqual(result["custom"], "Selected: artist.png")
        self.assertEqual(result["cancelled"], result["custom"])
        self.assertEqual(result["backToStarter"], "Selected preset: Left")
        self.assertEqual(result["revoked"], result["created"])
        for wording in ("White = stronger influence", "Black = weaker/no influence"):
            self.assertIn(wording, result["text"])
        self.assertTrue(all(request["method"] == "GET" for request in result["requests"]))

    def test_pending_starter_cannot_overwrite_newer_custom_selection(self) -> None:
        result = run_node(sidebar_script("""
          let resolveStarter; deferStarter = new Promise(resolve => { resolveStarter = resolve; });
          const pending = choosePreset('Left');
          const pendingDisabled = presetSelect().disabled && ['Generate','Save'].every(label => button(label).disabled);
          fileInput().files = [new File(['custom'], 'newer.png', {type:'image/png'})];
          await fileInput().fire('change');
          resolveStarter(); await pending;
          console.log(JSON.stringify({pendingDisabled,selected:selected(),created:created.length,
            sha256:await digest(created[0].file),reenabled:!presetSelect().disabled,requests}));
        """))
        self.assertTrue(result["pendingDisabled"])
        self.assertEqual(result["selected"], "Selected: newer.png")
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["sha256"], hashlib.sha256(b"custom").hexdigest())
        self.assertTrue(result["reenabled"])

    def test_removed_layer_or_disposed_panel_does_not_acquire_a_pending_starter(self) -> None:
        for action in ("await button('Remove').fire('click');", "dispose();"):
            with self.subTest(action=action):
                result = run_node(sidebar_script("""
                  let resolveStarter; deferStarter = new Promise(resolve => { resolveStarter = resolve; });
                  const pending = choosePreset('Right');
                """ + action + """
                  resolveStarter(); await pending;
                  console.log(JSON.stringify({created:created.length,
                    rows:container.querySelectorAll('.cl-layer').length,revoked}));
                """))
                self.assertEqual(result["created"], 0)
                self.assertEqual(result["rows"], 0)
                self.assertEqual(result["revoked"], [])

    def test_save_new_open_preserves_the_normal_saved_field_projection(self) -> None:
        result = run_node(sidebar_script("""
          await choosePreset('Right');
          find(node => node.attributes['aria-label'] === 'Document name').value = 'M3 Study';
          await button('Save').fire('click');
          const afterSave = selected();
          const savedPreview = find(node => node.tagName === 'img').src;
          await button('New Document').fire('click');
          find(node => node.attributes['aria-label'] === 'Saved Conditioning Layers document').value = saved.document_key;
          await button('Open').fire('click');
          const afterOpen = selected();
          const openedPreview = find(node => node.tagName === 'img').src;
          await button('Save').fire('click');
          console.log(JSON.stringify({afterSave,afterOpen,savedPreview,openedPreview,uploads,revoked,requests}));
        """))
        self.assertEqual(result["afterSave"], "Saved Influence Field")
        self.assertEqual(result["afterOpen"], "Saved Influence Field")
        self.assertEqual(result["savedPreview"], result["openedPreview"])
        self.assertEqual(result["openedPreview"], "/conditioning-layers/documents/m3-study/fields/layer-1")
        self.assertEqual(result["uploads"][0]["uploads"][0]["sha256"], starter_fixture()["right"]["sha256"])
        self.assertEqual(result["uploads"][1]["uploads"], [])
        self.assertTrue(result["uploads"][1]["request"]["layers"][0]["retained_field"])
        self.assertEqual(result["revoked"], ["blob:test-1"])
        self.assertFalse(any("executions" in request["url"] or request["url"] == "/prompt"
                             for request in result["requests"]))

    def test_guidance_and_bounded_findings_render_from_current_python_authority(self) -> None:
        result = run_node(sidebar_script("""
          const initialText = container.textContent;
          const active = find(node => node.type === 'checkbox');
          active.checked = false; await active.fire('change');
          const inactiveText = container.textContent;
          const codes = descendants(container).filter(node => node.dataset.code).map(node => node.dataset.code);
          console.log(JSON.stringify({initialText,inactiveText,codes,requests}));
        """))
        guidance = panel_capability_guidance()
        for key in ("active_guidance", "strength_guidance", "order_guidance",
                    "profile_guidance", "overlap_guidance"):
            self.assertIn(guidance[key], result["initialText"])
        self.assertIn("1 Active.", result["initialText"])
        self.assertIn("0 Active.", result["inactiveText"])
        self.assertEqual(result["codes"], [finding["code"] for finding in guidance["findings"]])
        for finding in guidance["findings"]:
            self.assertIn(finding["message"], result["initialText"])
        self.assertIn("retained", str(guidance["order_guidance"]).lower())
        for forbidden in ("EXP-0014", "Track B", "qualified-v2", "Stage-0"):
            self.assertNotIn(forbidden, result["initialText"])
        source = FRONTEND.read_text(encoding="utf-8")
        self.assertIn('api.fetchApi("/conditioning-layers/capabilities")', source)
        self.assertNotIn("maximum_tested", source)
        self.assertNotIn("layers.length > 2", source)
        self.assertNotIn('fetchApi("/prompt"', source)

    def test_persistent_notices_are_not_duplicated_and_errors_remain_visible(self) -> None:
        result = run_node(sidebar_script("""
          await choosePreset('Left');
          find(node => node.attributes['aria-label'] === 'Document name').value = 'Study';
          saveFailure = {findings:[
            {code:'capability.adapter_experimental',severity:'warning',message:'Already disclosed'},
            {code:'capability.adapter_experimental',severity:'error',message:'An error must remain visible'},
            {code:'capability.zero_strength_active',severity:'warning',message:'Zero Strength still counts'},
          ]};
          await button('Save').fire('click');
          const findings = descendants(container).filter(node => node.dataset.code).map(node => ({
            code:node.dataset.code,className:node.className,text:node.textContent,
          }));
          console.log(JSON.stringify({findings}));
        """))
        matching = [item for item in result["findings"]
                    if item["code"] == "capability.adapter_experimental"]
        self.assertEqual(len(matching), 2)
        self.assertTrue(any("cl-error" in item["className"] for item in matching))
        self.assertFalse(any(item["text"] == "Already disclosed" for item in matching))
        self.assertTrue(any(item["code"] == "capability.zero_strength_active"
                            for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
