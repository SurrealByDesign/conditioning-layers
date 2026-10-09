"""Node prerequisite: actual store/sidebar code, no browser or live requests."""

import json
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import multi_layer, product

from test_m4_frontend import h1_store_script, m4_script
from test_starter_frontend import run_node, store_script


BLEND = "conditioning-layers.composition-policy.normalized-blend.v1"
NO_OVERLAP = "conditioning-layers.composition-policy.require-no-overlap.v1"
PREAMBLE = f"const blend = {json.dumps(BLEND)}, noOverlap = {json.dumps(NO_OVERLAP)};"


def assert_observation(test, payload, *, success):
    """Also called with the actual Python Blend job projection in host tests."""
    result = run_node(m4_script(PREAMBLE + """
      const assert = (await import('node:assert/strict')).default;
      await prepare();
      const composition = control('Composition');
      composition.value = blend; await composition.fire('change');
      let posted;
      const payload = """ + json.dumps(payload) + """;
      intercept = async (url, options) => {
        if (!url.startsWith('/conditioning-layers/executions')) return undefined;
        if (options.method === 'POST') posted = JSON.parse(await options.body.get('request').text());
        return reply(payload);
      };
      await button('Generate').fire('click');
      assert.equal(posted.composition_policy.policy_identifier, blend);
      assert.deepEqual(posted.document_version, {major:2,minor:0});
      const output = find(node => node.className === 'cl-output');
      console.log(JSON.stringify({success:reuseAvailable(), images:output.children.filter(x=>x.tagName==='img').length,
        last:lastRun(), url:output.children.find(x=>x.tagName==='img')?.src ?? null}));
    """))
    test.assertEqual(result["success"], success, result)
    test.assertEqual(result["images"], 1 if success else 0, result)
    if success:
        test.assertEqual(result["url"], payload["output"]["view_url"])
        test.assertIn("completed", result["last"])


class BlendFrontendTests(unittest.TestCase):
    def test_store_policy_round_trip_edit_save_generate_and_restore_legacy_origin(self):
        result = run_node(store_script(PREAMBLE + """
          const assert = (await import('node:assert/strict')).default;
          const store = createLayerStore(() => 'row-a');
          const layer = store.addLayer();
          store.assignField(layer.rowId, new File(['png'], 'field.png', {type:'image/png'}));
          const original = store.toRequest('Base', 'key');
          const originalFingerprint = store.fingerprint(store.capture('Base', 'Study'));
          store.selectComposition(blend);
          assert.notEqual(store.fingerprint(store.capture('Base', 'Study')), originalFingerprint);
          const request = store.toRequest('Base', 'key');
          assert.deepEqual(request.document_version, {major:2,minor:0});
          assert.equal(request.composition_policy.policy_identifier, blend);
          const saved = await parts(store.toDocumentMultipart('Base', 'Study'));
          assert.deepEqual(saved.request.composition_policy, request.composition_policy);
          layer.active = false;
          assert.equal(store.toRequest('Base','key').composition_policy.policy_identifier, blend);
          layer.active = true;
          store.selectComposition(noOverlap);
          assert.deepEqual(store.toRequest('Base','key'), original);
          assert.equal(store.fingerprint(store.capture('Base','Study')), originalFingerprint);
          const opened = {document_version:{major:2,minor:0}, composition_policy:request.composition_policy,
            layers:[{layer_id:'layer-a',name:'A',prompt_text:'Prompt',strength:0.25,active:false,field_persisted:true}]};
          store.replaceFromDocument(opened);
          assert.deepEqual(store.toRequest('Base','key').composition_policy, request.composition_policy);
          store.selectComposition(noOverlap);
          assert.equal(store.toRequest('Base','key').composition_policy.policy_identifier, noOverlap);
          assert.deepEqual(store.toRequest('Base','key').document_version, {major:2,minor:0});
          const before = store.capture('Base','Study');
          for (const bad of [{document_version:{major:2,minor:0}},
            {...opened,composition_policy:{policy_identifier:'unknown',policy_version:1}},
            {...opened,composition_policy:null}]) {
            assert.throws(()=>store.replaceFromDocument(bad));
            assert.deepEqual(store.capture('Base','Study'),before);
          }
          // Reopening an original 1.0 document has the same reversible choice
          // as a new draft; it must not leave explicit 2.0 No Overlap behind.
          store.replaceFromDocument({layers:opened.layers});
          const legacyRequest = store.toRequest('Base','key');
          const legacyFingerprint = store.fingerprint(store.capture('Base','Study'));
          store.selectComposition(blend);
          store.selectComposition(noOverlap);
          assert.deepEqual(store.toRequest('Base','key'),legacyRequest);
          assert.equal(store.fingerprint(store.capture('Base','Study')),legacyFingerprint);
          store.clear(); assert.equal(store.compositionPolicy,null);
          console.log(JSON.stringify({ok:true}));
        """))
        self.assertTrue(result["ok"])

    def test_policy_save_acknowledgement_rejects_loss_and_preserves_concurrent_edits(self):
        result = run_node(h1_store_script(PREAMBLE + """
          const {store, record, ownership} = fixture();
          store.selectComposition(blend);
          const snapshot = store.capture('Base','Study');
          assert.throws(()=>store.acceptSaved(snapshot,record,ownership));
          record.document_version = {major:2,minor:0};
          record.composition_policy = {policy_identifier:blend,policy_version:1};
          store.selectComposition(noOverlap);
          store.acceptSaved(snapshot,record,ownership);
          assert.equal(store.compositionPolicy.policy_identifier,noOverlap);
          assert.notEqual(store.fingerprint(store.capture('Base','Study')),store.fingerprint(snapshot));
          console.log(JSON.stringify({ok:true}));
        """))
        self.assertTrue(result["ok"])

    def test_sidebar_capable_open_control_dirty_save_and_legacy_switch_back(self):
        result = run_node(m4_script(PREAMBLE + """
          const assert = (await import('node:assert/strict')).default;
          await prepare();
          const selector = control('Composition');
          assert.equal(selector.children.filter(x=>x.value===blend).length,1);
          assert.equal(selector.children.find(x=>x.value===blend).textContent,'Blend');
          selector.value = blend; await selector.fire('change');
          assert.ok(find(x=>x.textContent.includes('Blend generation supports exactly three Active Prompt Layers')));
          assert.equal(dirty(),'true');
          selector.value = noOverlap; await selector.fire('change');
          let body;
          intercept = async (url,options) => {
            if(options.method==='POST' && url==='/conditioning-layers/documents') {
              body = JSON.parse(await options.body.get('request').text());
              return reply({findings:[]},false);
            }
          };
          await button('Save As').fire('click');
          assert.equal('composition_policy' in body,false);
          const opened = {...record('blend'),display_name:'Blend',document_version:{major:2,minor:0},
            composition_policy:{policy_identifier:blend,policy_version:1}};
          intercept = async (url,options) => {
            if(url==='/conditioning-layers/documents/blend') {
              assert.equal(options.headers['X-Conditioning-Layers-Policy-Editor'],'1');
              return reply(opened);
            }
          };
          await chooseOpen('blend');
          assert.equal(control('Composition').value,blend);
          assert.equal(dirty(),'false');
          selector.value=noOverlap; await selector.fire('change');
          assert.equal(dirty(),'true');
          assert.ok(find(x=>x.textContent.includes('Explicit 2.0 No Overlap')));
          console.log(JSON.stringify({ok:true}));
        """))
        self.assertTrue(result["ok"])

    def test_sidebar_closed_authority_keeps_blend_save_only(self):
        with patch.object(product, "PRODUCT_ADMITTED_ENTRIES", multi_layer.PRODUCT_ADMITTED_ENTRIES):
            script = m4_script(PREAMBLE + """
              const assert = (await import('node:assert/strict')).default;
              await prepare();
              const selector = control('Composition');
              assert.ok(selector.children.find(x=>x.value===blend).textContent.includes('Save only'));
              selector.value=blend; await selector.fire('change');
              assert.ok(find(x=>x.textContent.includes('not product admitted')));
              console.log(JSON.stringify({ok:true}));
            """)
        self.assertTrue(run_node(script)["ok"])

    def test_unchanged_observation_accepts_valid_blend_and_rejects_invalid_locators(self):
        execution_id = "a" * 32
        filename = execution_id + "_00001_.png"
        output = {"type": "output", "subfolder": "conditioning-layers-panel", "filename": filename,
                  "view_url": f"/view?filename={filename}&subfolder=conditioning-layers-panel&type=output"}
        payload = {"execution_id": execution_id, "state": "completed", "terminal": True, "seed": "42", "findings": [], "output": output}
        assert_observation(self, payload, success=True)
        for changes in ({"subfolder": "wrong"}, {"filename": "b" * 32 + "_00001_.png"},
                        {"filename": execution_id + "_malformed.png"}, {"view_url": output["view_url"] + "&extra=1"},
                        {"view_url": output["view_url"].replace("00001", "00002")}, {"type": "temp"}):
            with self.subTest(changes=changes):
                assert_observation(self, {**payload, "output": {**output, **changes}}, success=False)
        missing = dict(payload)
        missing.pop("output")
        assert_observation(self, missing, success=False)
        assert_observation(self, {**missing, "state": "failed"}, success=False)


if __name__ == "__main__":
    unittest.main()
