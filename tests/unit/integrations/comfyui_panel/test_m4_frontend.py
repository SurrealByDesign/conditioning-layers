from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import tempfile
import unittest

from conditioning_layers.integrations.comfyui_panel.documents import PanelDocumentStore
from conditioning_layers.integrations.comfyui_panel.jobs import PanelJobSnapshot
from conditioning_layers.integrations.comfyui_panel.models import PanelFinding, PanelOutput

from _support import row as draft_row, upload
from test_documents import retained_rows, save_draft
from test_starter_frontend import run_node, sidebar_script, store_script


def m4_script(body: str, *, before_render: str = "") -> str:
    """Run actual sidebar handlers with only DOM, confirmation and HTTP fakes."""
    return sidebar_script("""
      const confirmations = []; let confirmResult = true;
      globalThis.confirm = (message) => { confirmations.push(message); return confirmResult; };
      const control = (label, scope = container) => descendants(scope).find(node =>
        node.attributes['aria-label'] === label || (node.parent?.tagName === 'label'
          && node.parent.children[0]?.textContent === label && node.tagName !== 'span'));
      const row = (index = 0) => container.querySelectorAll('.cl-layer')[index];
      const rowButton = (label, index = 0) => descendants(row(index)).find(node =>
        node.tagName === 'button' && node.textContent === label);
      const edit = async (label, value, scope = container) => {
        const target = control(label, scope); target.value = String(value);
        if (target.type === 'number') target.valueAsNumber = Number(value);
        await target.fire('input');
      };
      const dirty = () => find(node => node.className === 'cl-document-status').dataset.dirty;
      const lastRun = () => find(node => node.className === 'cl-last-run').textContent;
      const seedSummary = () => find(node => node.className === 'cl-seed-summary').textContent;
      const selectMode = async (value) => {
        const mode = control('Next generation seed'); mode.value = value; await mode.fire('change');
      };
      const reuseAvailable = () => !control('Next generation seed').children.find(option => option.value === 'reuse').disabled;
      const deferred = () => {
        let resolve; const promise = new Promise(done => { resolve = done; });
        return {promise, resolve};
      };
      const reply = (payload, ok = true) => ({ok, json:async () => structuredClone(payload)});
      const safeOutput = (executionId) => ({filename:`${executionId}_00001_.png`,
        subfolder:'conditioning-layers-panel', type:'output',
        view_url:`/view?filename=${executionId}_00001_.png&subfolder=conditioning-layers-panel&type=output`});
      const record = (key, base = key) => ({
        document_key:key, document_id:`id-${key}`, display_name:key, base_prompt:base,
        layers:[{layer_id:`layer-${key}`, name:`Layer ${key}`, prompt_text:`Prompt ${key}`,
          strength:1, active:true, field_persisted:true,
          field_url:`/conditioning-layers/documents/${key}/fields/layer-${key}`}],
      });
      let intercept = null; const m4Requests = [];
      const defaultFetch = globalThis.testApi.fetchApi;
      globalThis.testApi.fetchApi = async (url, options = {}) => {
        m4Requests.push({url, method:options.method ?? 'GET'});
        const handled = intercept ? await intercept(url, options) : undefined;
        return handled === undefined ? defaultFetch(url, options) : handled;
      };
      const prepare = async () => {
        await choosePreset('Left');
        await edit('Document name', 'Study');
        await edit('Base Prompt', 'Initial scene');
      };
      const chooseOpen = async (key) => {
        control('Saved Conditioning Layers document').value = key;
        return button('Open').fire('click');
      };
    """ + body, before_render=before_render)


def h1_store_script(body: str) -> str:
    return store_script("""
      const assert = (await import('node:assert/strict')).default;
      const fixture = (mode = 'new') => {
        let sequence = 0; const store = createLayerStore(() => `row-${++sequence}`);
        for (let i = 0; i < 2; i++) {
          const layer = store.addLayer(); layer.promptText = `Subject ${i}`;
          layer.active = i === 0; layer.strength = i === 0 ? 1 : 0.375;
          if (mode !== 'new') layer.layerId = `existing-${i}`;
          store.assignField(layer.rowId,
            new File([`png-${i}`], `custom-${i}.png`, {type:'image/png'}));
          // Model a previously acknowledged upload plus a replacement PNG.
          if (mode !== 'new' && i === 0) {
            layer.field = null; layer.persistedField = true;
            layer.fieldUrl = `/conditioning-layers/documents/original/fields/${layer.layerId}`;
          }
        }
        const ownership = {documentKey:mode === 'new' ? null : 'original',
          documentId:mode === 'new' ? null : 'document-original', saveAs:mode === 'copy'};
        const snapshot = store.capture('Base', mode === 'save' ? 'Original' : 'Study');
        const key = mode === 'save' ? 'original' : 'study';
        const record = {document_key:key, document_id:mode === 'save' ? 'document-original' : 'document-new',
          display_name:mode === 'save' ? 'Original' : 'Study', base_prompt:'Base',
          layers:snapshot.layers.map((row,i) => {
            const id = row.layerId ?? `new-${i}`;
            return {layer_id:id, name:row.name, prompt_text:row.promptText, strength:row.strength,
              active:row.active, field_persisted:true,
              field_url:`/conditioning-layers/documents/${key}/fields/${id}`};
          })};
        return {store, snapshot, record, ownership};
      };
    """ + body)


def h3_poll_script(body: str, *, invalidate_operation: bool = False) -> str:
    """Real Generate/poll handlers with controlled GET promises and timer expiry."""
    script = m4_script("""
      const assert = (await import('node:assert/strict')).default;
      await prepare();
      const executionId = '0123456789abcdef0123456789abcdef';
      const executionPath = `/conditioning-layers/executions/${executionId}`;
      const job = (state = 'completed', seed = '18446744073709551615') => ({
        execution_id:executionId, state, seed, findings:[],
        terminal:['completed','failed','rejected'].includes(state),
        ...(state === 'completed' ? {output:safeOutput(executionId)} : {}),
      });
      const status = () => find(node => node.className === 'cl-status').textContent;
      const images = () => descendants(container).filter(node => node.alt === 'Conditioning Layers generated result');
      const reads = []; const posts = [];
      let nextRead = async () => reply(job());
      let nextPost = async () => reply(job('accepted'));
      intercept = async (url,options) => {
        if (url === '/conditioning-layers/executions' && options.method === 'POST') {
          posts.push((await parts(options.body)).request); return nextPost();
        }
        if (url.startsWith('/conditioning-layers/executions/')) {
          reads.push(url); return nextRead();
        }
      };
      const expire = async () => {
        assert.equal(timers.length,1); const timer = timers.shift();
        assert.equal(timer.ms,1000); timer.resolve(); await settle();
      };
      const assertBlocked = () => {
        assert.equal(button('Generate').disabled,true);
        assert.match(status(),/unknown.*Reload/); assert.match(lastRun(),/unknown/);
        assert.equal(images().length,0);
      };
      const assertOnce = (expectedReads) => {
        assert.equal(posts.length,1);
        assert.deepEqual(reads,Array(expectedReads).fill(executionPath));
        assert.equal(m4Requests.some(call => call.url.includes('/prompt')),false);
      };
    """ + body, before_render="""
      const timers = [];
      globalThis.setTimeout = (resolve,ms) => { timers.push({resolve,ms}); return timers.length; };
    """)
    if invalidate_operation:
        # Generate disables every real document-replacement handler. Inject only
        # a lifecycle-token invalidator into the loaded module for this otherwise
        # unreachable stale-token race; handler entry and all effects remain real.
        def expose_token(match: re.Match[str]) -> str:
            source = base64.b64decode(match[1]).decode('utf-8')
            marker = '  function currentOperation(token)'
            if marker not in source:
                return match[0]
            source = source.replace(marker,
                '  globalThis.invalidateOperation = () => { state.operation += 1; };\n' + marker)
            return 'data:text/javascript;base64,' + base64.b64encode(source.encode('utf-8')).decode('ascii')

        script = re.sub(r'data:text/javascript;base64,([A-Za-z0-9+/=]+)', expose_token, script)
    return script


class H3PollingTests(unittest.TestCase):
    def check_script(self, body: str, *, invalidate_operation: bool = False) -> None:
        result = run_node(h3_poll_script(body + "\nconsole.log(JSON.stringify({passed:true}));",
                                        invalidate_operation=invalidate_operation))
        self.assertTrue(result['passed'])

    def test_transport_failure_recovers_same_execution_without_second_post(self) -> None:
        self.check_script("""
          nextRead = async () => { throw new TypeError('network disconnected'); };
          const pending = button('Generate').fire('click'); await settle();
          assertOnce(1); assert.equal(timers.length,1);
          nextRead = async () => reply(job()); await expire(); await pending;
          assertOnce(2); assert.equal(timers.length,0); assert.match(lastRun(),/completed/);
          assert.equal(button('Generate').disabled,false);
        """)

    def test_single_5xx_recovers_without_parsing_error_body(self) -> None:
        for code in (500, 503, 599):
            with self.subTest(code=code):
                self.check_script(f"const code = {code};" + """
                  let parsed = false;
                  nextRead = async () => ({ok:false,status:code,json:async () => {parsed=true; throw new Error('not JSON');}});
                  const pending = button('Generate').fire('click'); await settle();
                  nextRead = async () => reply(job()); await expire(); await pending;
                  assert.equal(parsed,false); assertOnce(2); assert.match(lastRun(),/completed/);
                """)

    def test_second_transient_failure_fails_closed_without_third_read(self) -> None:
        for second in ('transport', '5xx'):
            with self.subTest(second=second):
                self.check_script("const second = " + json.dumps(second) + ";" + """
                  nextRead = async () => { throw new TypeError('first read disconnected'); };
                  const pending = button('Generate').fire('click'); await settle();
                  nextRead = async () => {
                    if (second === 'transport') throw new TypeError('second read disconnected');
                    return {ok:false,status:503,json:async () => ({})};
                  };
                  await expire(); await pending; assertBlocked(); assertOnce(2);
                  assert.equal(timers.length,0); await button('Generate').fire('click'); assertOnce(2);
                """)

    def test_valid_nonterminal_recovery_does_not_replenish_read_budget(self) -> None:
        self.check_script("""
          nextRead = async () => { throw new TypeError('first gap'); };
          const pending = button('Generate').fire('click'); await settle();
          nextRead = async () => reply(job('executing')); await expire();
          assert.match(lastRun(),/executing/); assert.equal(reuseAvailable(),false);
          nextRead = async () => { throw new TypeError('later gap'); };
          await expire(); await pending; assertBlocked(); assertOnce(3); assert.equal(timers.length,0);
        """)

    def test_execution_identity_mismatch_fails_without_retry(self) -> None:
        self.check_script("""
          nextRead = async () => reply({...job(),execution_id:'fedcba9876543210fedcba9876543210'});
          await button('Generate').fire('click'); assertBlocked(); assertOnce(1);
          assert.equal(timers.length,0); assert.equal(reuseAvailable(),false);
        """)

    def test_malformed_authoritative_state_fails_without_retry(self) -> None:
        mutations = [
            'payload = null', 'payload = []', 'delete payload.state',
            "payload.state = 'impossible'", "payload.state = 'cancelled'", 'payload.terminal = false',
            "payload.terminal = 'true'", 'delete payload.findings',
            'payload.findings = [null]', "payload.findings = [{severity:'error'}]",
            'delete payload.output', 'payload.output = null', 'payload.output = []',
            "payload.seed = '7'", "payload.seed += '\\n'", 'payload.seed = 42', 'delete payload.seed',
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.check_script("""
                  nextRead = async () => { let payload = job();
                """ + mutation + "; return reply(payload); };" + """
                  await button('Generate').fire('click'); assertBlocked(); assertOnce(1);
                  assert.equal(timers.length,0); assert.equal(reuseAvailable(),false);
                """)

    def test_json_parse_or_body_failure_is_not_a_transport_retry(self) -> None:
        for failure in ('SyntaxError', 'TypeError'):
            with self.subTest(failure=failure):
                self.check_script("""
                  nextRead = async () => ({ok:true,status:200,json:async () => {
                """ + f"throw new {failure}('body failed');" + """
                  }});
                  await button('Generate').fire('click'); assertBlocked(); assertOnce(1);
                  assert.equal(timers.length,0);
                """)

    def test_non_5xx_http_failure_is_not_retried(self) -> None:
        for code in (400, 401, 404, 409, 429):
            with self.subTest(code=code):
                self.check_script(f"nextRead = async () => ({{ok:false,status:{code}}});" + """
                  await button('Generate').fire('click'); assertBlocked(); assertOnce(1);
                  assert.equal(timers.length,0);
                """)

    def test_recovered_malformed_or_wrong_identity_is_never_applied(self) -> None:
        for mutation in ("payload.execution_id = 'other'", "payload.state = 'impossible'",
                         'payload.output.filename = "wrong_00001_.png"'):
            with self.subTest(mutation=mutation):
                self.check_script("""
                  nextRead = async () => { throw new TypeError('read gap'); };
                  const pending = button('Generate').fire('click'); await settle();
                  nextRead = async () => { const payload = job();
                """ + mutation + "; return reply(payload); };" + """
                  await expire(); await pending; assertBlocked(); assertOnce(2);
                  assert.equal(timers.length,0); assert.equal(reuseAvailable(),false);
                """)

    def test_generate_stays_disabled_during_wait_and_deferred_reobservation(self) -> None:
        self.check_script("""
          nextRead = async () => { throw new TypeError('read gap'); };
          const pending = button('Generate').fire('click'); await settle();
          assert.equal(button('Generate').disabled,true); await button('Generate').fire('click'); assertOnce(1);
          const read = deferred(); nextRead = async () => read.promise;
          await expire(); assert.equal(button('Generate').disabled,true); assert.equal(reuseAvailable(),false);
          await button('Generate').fire('click'); assertOnce(2);
          read.resolve(reply(job())); await pending;
          assert.equal(button('Generate').disabled,false); assertOnce(2);
        """)

    def test_disposal_during_recovery_wait_prevents_additional_get(self) -> None:
        self.check_script("""
          nextRead = async () => { throw new TypeError('read gap'); };
          const pending = button('Generate').fire('click'); await settle();
          const root = container.children[0]; dispose(); const before = root.textContent;
          await expire(); await pending; assert.equal(root.textContent,before);
          assert.equal(container.children.length,0); assertOnce(1);
        """)

    def test_disposal_during_recovery_body_prevents_late_state_application(self) -> None:
        self.check_script("""
          nextRead = async () => { throw new TypeError('read gap'); };
          const pending = button('Generate').fire('click'); await settle();
          const body = deferred(); nextRead = async () => ({ok:true,json:() => body.promise});
          await expire(); const root = container.children[0]; dispose(); const before = root.textContent;
          body.resolve(job()); await pending; assert.equal(root.textContent,before);
          assert.equal(container.children.length,0); assertOnce(2);
        """)

    def test_stale_operation_during_wait_or_body_never_applies_late_state(self) -> None:
        for phase in ('wait', 'body'):
            with self.subTest(phase=phase):
                self.check_script("const phase = " + json.dumps(phase) + ";" + """
                  nextRead = async () => { throw new TypeError('read gap'); };
                  const pending = button('Generate').fire('click'); await settle();
                  const body = deferred(); nextRead = async () => ({ok:true,json:() => body.promise});
                  if (phase === 'body') await expire();
                  globalThis.invalidateOperation(); const before = container.textContent;
                  if (phase === 'wait') await expire(); else body.resolve(job());
                  await pending; assert.equal(container.textContent,before);
                  assert.equal(reuseAvailable(),false); assert.equal(images().length,0);
                  assertOnce(phase === 'wait' ? 1 : 2);
                """, invalidate_operation=True)

    def test_recovered_terminal_success_updates_seed_output_and_normal_run_state(self) -> None:
        self.check_script("""
          nextRead = async () => { throw new TypeError('read gap'); };
          const pending = button('Generate').fire('click'); await settle();
          assert.equal(reuseAvailable(),false); await edit('Base Prompt','Edited during run');
          nextRead = async () => reply(job()); await expire(); await pending;
          assert.match(lastRun(),/completed/); assert.match(lastRun(),/18446744073709551615/);
          assert.match(lastRun(),/Document changed/); assert.equal(reuseAvailable(),true);
          assert.equal(images()[0].src,safeOutput(executionId).view_url);
          assert.equal(button('Generate').disabled,false); assertOnce(2);
        """)

    def test_recovered_terminal_failure_remains_failure_and_preserves_successful_seed(self) -> None:
        for outcome in ('failed', 'rejected'):
            with self.subTest(outcome=outcome):
                self.check_script("const outcome = " + json.dumps(outcome) + ";" + """
                  // A separate deliberate earlier fake run establishes reuse state.
                  const priorId = '11111111111111111111111111111111';
                  nextPost = async () => reply({...job('accepted','7'),execution_id:priorId});
                  nextRead = async () => reply({...job('completed','7'),execution_id:priorId,output:safeOutput(priorId)});
                  await button('Generate').fire('click'); assert.equal(reuseAvailable(),true);
                  nextPost = async () => reply(job('accepted'));
                  nextRead = async () => { throw new TypeError('read gap'); };
                  const pending = button('Generate').fire('click'); await settle();
                  await selectMode('reuse'); assert.match(seedSummary(),/Next seed: 7 /);
                  nextRead = async () => reply({...job(outcome),findings:[{severity:'error',code:'test.failed',message:'Real terminal failure'}]});
                  await expire(); await pending; assert.match(lastRun(),new RegExp(outcome));
                  assert.match(seedSummary(),/Next seed: 7 /); assert.equal(reuseAvailable(),true);
                  assert.equal(images().length,0); assert.equal(button('Generate').disabled,false);
                  assert.equal(posts.length,2); assert.notEqual(posts[0].idempotency_key,posts[1].idempotency_key);
                  assert.deepEqual(reads,[`/conditioning-layers/executions/${priorId}`,executionPath,executionPath]);
                """)

    def test_unknown_initial_submission_is_not_reobserved_or_resubmitted(self) -> None:
        for failure in ('transport', 'parse'):
            with self.subTest(failure=failure):
                self.check_script("const failure = " + json.dumps(failure) + ";" + """
                  nextPost = async () => {
                    if (failure === 'transport') throw new TypeError('POST response lost');
                    return {ok:true,json:async () => { throw new SyntaxError('POST body lost'); }};
                  };
                  await button('Generate').fire('click'); assertBlocked(); assertOnce(0);
                  assert.equal(timers.length,0); await button('Generate').fire('click'); assertOnce(0);
                """)

    def test_invalid_initial_execution_association_is_not_polled(self) -> None:
        for identity in ({'id': 'other'}, 'not-an-execution-id', '../other',
                         '0123456789abcdef0123456789abcdef\n'):
            with self.subTest(identity=identity):
                self.check_script("const identity = " + json.dumps(identity) + ";" + """
                  nextPost = async () => reply({...job('accepted'),execution_id:identity});
                  await button('Generate').fire('click'); assertBlocked(); assertOnce(0);
                  assert.equal(timers.length,0);
                """)

    def test_malformed_successful_initial_acknowledgement_has_no_seed_or_recovery(self) -> None:
        for mutation in ('delete payload.execution_id', 'delete payload.seed',
                         'payload = null', "payload.state = 'impossible'",
                         "payload.state = 'completed'; payload.terminal = true",
                         'payload.terminal = true', 'payload.findings = null'):
            with self.subTest(mutation=mutation):
                self.check_script("nextPost = async () => { let payload = job('accepted');" + mutation +
                                  "; return reply(payload); };" + """
                  await button('Generate').fire('click'); assertBlocked(); assertOnce(0);
                  assert.equal(timers.length,0); assert.equal(reuseAvailable(),false);
                  assert.match(lastRun(),/Seed: not available/);
                  await button('Generate').fire('click'); assertOnce(0);
                """)

    def test_wrong_output_locator_or_view_identity_is_not_retried_or_rendered(self) -> None:
        for mutation in (
            "payload.output.filename = 'other_00001_.png'",
            "payload.output.filename += '\\n'",
            "payload.output.subfolder = 'other'", "payload.output.type = 'input'",
            "payload.output.view_url = '/view?filename=wrong&subfolder=conditioning-layers-panel&type=output'",
            "payload.output.view_url += '&filename=duplicate'", "payload.output.view_url += '#wrong'",
            "payload.output.view_url = 'https://other.example/view?'",
        ):
            with self.subTest(mutation=mutation):
                self.check_script("nextRead = async () => { const payload = job();" + mutation + "; return reply(payload); };" + """
                  await button('Generate').fire('click'); assertBlocked(); assertOnce(1);
                  assert.equal(timers.length,0); assert.equal(reuseAvailable(),false);
                """)

    def test_python_job_and_output_projections_recover_without_contract_changes(self) -> None:
        execution_id = '0123456789abcdef0123456789abcdef'
        filename = f'{execution_id}_00001_.png'
        projected = PanelJobSnapshot(execution_id=execution_id, state='completed',
            seed=18446744073709551615,
            findings=(PanelFinding(code='test.information', severity='information', message='A notice'),),
            output=PanelOutput(filename=filename, subfolder='conditioning-layers-panel', storage_type='output',
                view_url=f'/view?filename={filename}&subfolder=conditioning-layers-panel&type=output')).to_json()
        self.check_script("const projected = " + json.dumps(projected) + ";" + """
          nextRead = async () => { throw new TypeError('read gap'); };
          const pending = button('Generate').fire('click'); await settle();
          nextRead = async () => reply(projected); await expire(); await pending;
          assert.match(lastRun(),/completed/); assert.equal(reuseAvailable(),true);
          assert.equal(images()[0].src,projected.output.view_url); assertOnce(2);
        """)


class H1SaveAcknowledgementTests(unittest.TestCase):
    def assert_rejected_unchanged(self, mutations: list[str]) -> None:
        result = run_node(h1_store_script("""
          let checked = 0;
          for (const mode of ['new', 'save', 'copy']) {
            for (const mutate of MUTATIONS) {
              let {store, snapshot, record, ownership} = fixture(mode);
              record = mutate(record);
              // Edits made after submission must survive every rejected reply.
              store.layers[0].promptText = 'Newer subject';
              const replacement = new File(['newer'], 'newer.png', {type:'image/png'});
              store.assignField(store.layers[1].rowId, replacement);
              const before = store.capture('Newer base', 'Newer name');
              const references = [...store.layers];
              assert.throws(() => store.acceptSaved(snapshot, record, ownership),
                error => error.constructor.name === 'SaveAcknowledgementError');
              assert.deepEqual(store.capture('Newer base', 'Newer name'), before);
              references.forEach((row,i) => {
                assert.equal(store.layers[i], row);
                assert.equal(row.field, before.layers[i].field);
              });
              assert.notEqual(store.fingerprint(before), store.fingerprint(snapshot));
              checked++;
            }
          }
          console.log(JSON.stringify({checked}));
        """.replace("MUTATIONS", "[" + ",".join(
            f"record => {{ {mutation}; return record; }}" for mutation in mutations
        ) + "]")))
        self.assertEqual(result['checked'], 3 * len(mutations))

    def test_short_layer_list_is_atomic(self) -> None:
        self.assert_rejected_unchanged(["record.layers.pop()"])

    def test_extra_layer_is_atomic(self) -> None:
        self.assert_rejected_unchanged(["record.layers.push({...record.layers[0],layer_id:'extra'})"])

    def test_missing_or_non_array_layer_list_is_atomic(self) -> None:
        self.assert_rejected_unchanged([
            "delete record.layers", "record.layers = null", "record.layers = {}",
        ])

    def test_invalid_later_layer_is_atomic(self) -> None:
        self.assert_rejected_unchanged([
            "record.layers[1] = null", "record.layers[1] = []",
            "record.layers[1] = 'layer'", "record.layers[1] = 1",
        ])

    def test_missing_or_invalid_later_identity_is_atomic(self) -> None:
        self.assert_rejected_unchanged([
            "delete record.layers[1].layer_id", "record.layers[1].layer_id = ''",
            "record.layers[1].layer_id = null", "record.layers[1].layer_id = 123",
            "record.layers[1].layer_id = '../other'",
            "record.layers[1].layer_id = 'id'.repeat(65)",
            "record.layers[1].layer_id = 'id\\n'",
        ])

    def test_duplicate_layer_identity_is_atomic(self) -> None:
        self.assert_rejected_unchanged(["record.layers[1].layer_id = record.layers[0].layer_id"])

    def test_invalid_persisted_field_binding_is_atomic(self) -> None:
        self.assert_rejected_unchanged([
            "delete record.layers[1].field_persisted", "record.layers[1].field_persisted = false",
            "record.layers[1].field_persisted = 'true'", "record.layers[1].field_persisted = 1",
            "delete record.layers[1].field_url", "record.layers[1].field_url = null",
            "record.layers[1].field_url = {}", "record.layers[1].field_url = ''",
            "record.layers[1].field_url = record.layers[0].field_url",
            "record.layers[1].field_url = '/conditioning-layers/documents/other/fields/other'",
        ])

    def test_semantic_row_and_base_mismatches_are_atomic(self) -> None:
        self.assert_rejected_unchanged([
            "record.layers.reverse()", "record.layers[1].name = 'Wrong row'",
            "record.layers[1].prompt_text = 'Wrong prompt'", "record.layers[1].strength = 0.5",
            "record.layers[1].active = true", "record.base_prompt = 'Wrong base'",
        ])

    def test_invalid_envelope_or_document_identity_is_atomic(self) -> None:
        self.assert_rejected_unchanged([
            "record = null", "record = []", "record = 'saved'",
            "delete record.document_id", "record.document_id = ''", "record.document_id = 123",
            "record.document_id = '../other'", "record.document_id = 'id\\n'",
            "delete record.document_key", "record.document_key = ''", "record.document_key = '../other'",
            "record.document_key = 'study\\n'", "record.document_key = 123",
            "delete record.display_name", "record.display_name = ''", "record.display_name = 'Other'",
        ])

    def test_save_and_save_as_ownership_mismatches_are_atomic(self) -> None:
        result = run_node(h1_store_script("""
          let checked = 0;
          for (const mode of ['save', 'copy']) {
            for (const defect of ['document-id', 'document-key', 'layer-id']) {
              const {store,snapshot,record,ownership} = fixture(mode);
              if (defect === 'document-id') record.document_id = mode === 'save' ? 'other' : ownership.documentId;
              if (defect === 'document-key') {
                record.document_key = mode === 'save' ? 'other' : ownership.documentKey;
                record.display_name = mode === 'save' ? 'Other' : 'Original';
              }
              if (defect === 'layer-id') record.layers[1].layer_id = 'other';
              for (const layer of record.layers) layer.field_url =
                `/conditioning-layers/documents/${record.document_key}/fields/${layer.layer_id}`;
              const before = store.capture('Base', snapshot.displayName);
              assert.throws(() => store.acceptSaved(snapshot,record,ownership));
              assert.deepEqual(store.capture('Base', snapshot.displayName),before); checked++;
            }
          }
          console.log(JSON.stringify({checked}));
        """))
        self.assertEqual(result['checked'], 6)

    def test_invalid_removed_row_still_rejects_entire_acknowledgement(self) -> None:
        result = run_node(h1_store_script("""
          const {store,snapshot,record,ownership} = fixture();
          store.removeLayer(snapshot.layers[1].rowId); record.layers[1] = null;
          const before = store.capture('Base','Study');
          assert.throws(() => store.acceptSaved(snapshot,record,ownership));
          assert.deepEqual(store.capture('Base','Study'),before);
          console.log(JSON.stringify({rows:store.layers.length}));
        """))
        self.assertEqual(result['rows'], 1)

    def test_valid_merge_binds_all_identities_and_preserves_snapshot_tokens(self) -> None:
        result = run_node(h1_store_script("""
          const modes = [];
          for (const mode of ['new','save','copy']) {
            const {store,snapshot,record,ownership} = fixture(mode);
            const baseline = store.fingerprint(snapshot);
            const ack = store.acceptSaved(snapshot,record,ownership);
            assert.equal(ack.documentId,record.document_id);
            assert.equal(ack.documentKey,record.document_key);
            store.layers.forEach((layer,i) => {
              assert.equal(layer.layerId,record.layers[i].layer_id);
              assert.equal(layer.field,null); assert.equal(layer.persistedField,true);
              assert.equal(layer.fieldUrl,record.layers[i].field_url);
            });
            assert.equal(store.fingerprint(store.capture('Base',snapshot.displayName)),baseline);
            modes.push(mode);
          }
          console.log(JSON.stringify({modes}));
        """))
        self.assertEqual(result['modes'], ['new', 'save', 'copy'])

    def test_valid_response_preserves_reordered_removed_and_added_rows(self) -> None:
        result = run_node(h1_store_script("""
          for (const remove of [false,true]) {
            const {store,snapshot,record,ownership} = fixture();
            store.moveLayer(snapshot.layers[1].rowId,-1);
            if (remove) store.removeLayer(snapshot.layers[0].rowId);
            const added = store.addLayer();
            store.acceptSaved(snapshot,record,ownership);
            assert.equal(store.layers[0].layerId,record.layers[1].layer_id);
            assert.equal(store.layers[0].fieldUrl,record.layers[1].field_url);
            if (!remove) assert.equal(store.layers[1].layerId,record.layers[0].layer_id);
            assert.equal(store.layers.at(-1),added); assert.equal(added.layerId,null);
            assert.equal(store.layers.length,remove ? 2 : 3);
          }
          console.log(JSON.stringify({passed:true}));
        """))
        self.assertTrue(result['passed'])

    def test_real_python_save_responses_remain_compatible(self) -> None:
        # Canonical responses come from the unchanged persistence authority,
        # including Unicode casefold and bounded storage-name normalization.
        cases = []
        for name in ('  Study -- One  ', 'Straße', 'Abc ' * 30):
            with tempfile.TemporaryDirectory() as root:
                documents = PanelDocumentStore(Path(root))
                rows = [draft_row(str(i), name=f'Layer {i + 1}', prompt=f'Subject {i}',
                                  active=i == 0, strength=1 if i == 0 else 0.375)
                        for i in range(2)]
                first = documents.save_as(save_draft(name, rows, base_prompt='Base',
                    uploads={f'field-{i}': upload(str(i)) for i in range(2)}))
                saved = documents.save(first.document_key, save_draft(first.display_name,
                    retained_rows(first), source=first.document_key,
                    document_id=first.document.document_id, base_prompt='Base'))
                copied = documents.save_as(save_draft('Copy', retained_rows(saved),
                    source=saved.document_key, document_id=saved.document.document_id, base_prompt='Base'))
                cases.append({'name': name, 'first': first.to_json(),
                              'saved': saved.to_json(), 'copied': copied.to_json()})
        result = run_node(h1_store_script("const cases = " + json.dumps(cases) + ";" + """
          for (const item of cases) {
            const {store} = fixture();
            store.acceptSaved(store.capture('Base',item.name),item.first,
              {documentKey:null,documentId:null,saveAs:false});
            const ownership = {documentKey:item.first.document_key,documentId:item.first.document_id};
            store.acceptSaved(store.capture('Base',item.first.display_name),item.saved,
              {...ownership,saveAs:false});
            const ack = store.acceptSaved(store.capture('Base','Copy'),item.copied,
              {...ownership,saveAs:true});
            assert.equal(ack.documentId,item.copied.document_id);
            store.layers.forEach((layer,i) => assert.equal(layer.fieldUrl,item.copied.layers[i].field_url));
          }
          console.log(JSON.stringify({checked:cases.length}));
        """))
        self.assertEqual(result['checked'], 3)

    def test_invalid_acknowledgement_preserves_ui_ownership_newer_edits_focus_and_dirty(self) -> None:
        for mode in ('new', 'save', 'copy'):
            with self.subTest(mode=mode):
                result = run_node(m4_script("const mode = " + json.dumps(mode) + ";" + """
                  await prepare(); await button('Add Layer').fire('click');
                  await choosePreset('Right',1);
                  if (mode !== 'new') await button('Save').fire('click');
                  if (mode === 'copy') await edit('Document name','Copy');
                  const gate = deferred(); let submitted;
                  intercept = async (url,options) => {
                    if (options.body) {
                      submitted = await parts(options.body);
                      const response = await defaultFetch(url,options); const payload = await response.json();
                      payload.layers[1] = null; await gate.promise; return reply(payload);
                    }
                  };
                  const action = mode === 'copy' ? 'Save As' : 'Save';
                  const pending = button(action).fire('click'); await settle();
                  await edit('Base Prompt','Newer base'); await edit('Prompt','Newer prompt',row());
                  fileInput().files = [new File(['newer'],'newer.png',{type:'image/png'})];
                  await fileInput().fire('change');
                  const focused = control('Prompt',row()); document.activeElement = focused;
                  focused.selectionStart = 2; focused.selectionEnd = 7;
                  const preview = find(node => node.tagName === 'img').src;
                  const revocations = revoked.length; const requestsBefore = m4Requests.length;
                  gate.resolve(); await pending;
                  const after = {dirty:dirty(),base:control('Base Prompt').value,
                    prompt:control('Prompt',row()).value,selected:selected(),
                    name:control('Document name').value,
                    focused:document.activeElement === focused && control('Prompt',row()) === focused,
                    selection:[focused.selectionStart,focused.selectionEnd],
                    previewUnchanged:preview === find(node => node.tagName === 'img').src,
                    revocations:revoked.length-revocations,requests:m4Requests.length-requestsBefore,
                    status:find(node => node.className === 'cl-status').textContent,
                    saveEnabled:!button(action).disabled};
                  let next;
                  // Inspect serialization without performing a second disk write.
                  intercept = async (url,options) => {
                    if (options.body) {next = await parts(options.body); return reply({findings:[]},false);}
                  };
                  await button(action).fire('click');
                  console.log(JSON.stringify({after,submitted,next}));
                """))
                after = result['after']
                self.assertEqual(after['dirty'], 'true')
                self.assertEqual(after['base'], 'Newer base')
                self.assertEqual(after['prompt'], 'Newer prompt')
                self.assertEqual(after['name'], 'Copy' if mode == 'copy' else 'Study')
                self.assertEqual(after['selected'], 'Selected: newer.png')
                self.assertTrue(after['focused'])
                self.assertEqual(after['selection'], [2, 7])
                self.assertTrue(after['previewUnchanged'])
                self.assertEqual(after['revocations'], 0)
                self.assertEqual(after['requests'], 0)
                self.assertTrue(after['saveEnabled'])
                self.assertIn('invalid acknowledgement', after['status'])
                self.assertIn('current edits are preserved', after['status'])
                self.assertIn('server may have saved', after['status'])
                self.assertIn('check the saved copy before retrying', after['status'])
                before, following = result['submitted']['request'], result['next']['request']
                for key in ('source_document_key', 'document_id'):
                    self.assertEqual(following[key], before[key])
                self.assertEqual([r['layer_id'] for r in following['layers']],
                                 [r['layer_id'] for r in before['layers']])
                self.assertFalse(following['layers'][0]['retained_field'])
                self.assertEqual(following['layers'][1]['retained_field'], mode != 'new')
                self.assertEqual(len(result['next']['uploads']), 2 if mode == 'new' else 1)

    def test_save_as_adopts_new_ownership_for_the_next_save(self) -> None:
        result = run_node(m4_script("""
          await prepare(); await button('Save').fire('click');
          await edit('Document name','Copy'); await button('Save As').fire('click');
          const copied = structuredClone(saved); const clean = dirty();
          await edit('Prompt','Copy revision',row()); await button('Save').fire('click');
          console.log(JSON.stringify({copied,clean,uploads,finalDirty:dirty(),
            writes:m4Requests.filter(call => ['POST','PUT'].includes(call.method))}));
        """))
        self.assertEqual(result['clean'], 'false')
        self.assertEqual(result['finalDirty'], 'false')
        self.assertEqual(result['copied']['document_key'], 'copy')
        self.assertEqual(result['copied']['document_id'], 'document-2')
        final = result['uploads'][-1]
        self.assertEqual(final['request']['source_document_key'], 'copy')
        self.assertEqual(final['request']['document_id'], 'document-2')
        self.assertEqual(final['request']['layers'][0]['layer_id'], 'layer-1')
        self.assertEqual(final['uploads'], [])
        self.assertEqual(result['copied']['layers'][0]['field_url'],
                         '/conditioning-layers/documents/copy/fields/layer-1')
        self.assertEqual([r['method'] for r in result['writes']], ['POST', 'POST', 'PUT'])


class M4DirtyStateTests(unittest.TestCase):
    def test_initial_new_and_opened_baselines_are_clean(self) -> None:
        result = run_node(m4_script("""
          const initial = dirty();
          await button('New Document').fire('click');
          const afterNew = dirty();
          intercept = async url => url.endsWith('/existing') ? reply(record('existing')) : undefined;
          await chooseOpen('existing');
          console.log(JSON.stringify({initial, afterNew, opened:dirty(),
            base:control('Base Prompt').value, confirmations}));
        """))
        self.assertEqual([result['initial'], result['afterNew'], result['opened']],
                         ['false', 'false', 'false'])
        self.assertEqual(result['base'], 'existing')
        self.assertEqual(result['confirmations'], [])

    def test_document_and_layer_content_dirty_comparison_reverts_cleanly(self) -> None:
        result = run_node(m4_script("""
          const changes = [];
          for (const [label, value, scope] of [
            ['Document name','Study',container], ['Base Prompt','Scene',container],
            ['Layer name','Named layer',row()], ['Prompt','Subject',row()],
            ['Strength',0.375,row()],
          ]) {
            const target = control(label, scope); const original = target.value;
            await edit(label, value, scope); const changed = dirty();
            await edit(label, original, scope); changes.push({label,changed,reverted:dirty()});
          }
          const active = control('Active', row());
          active.checked = false; await active.fire('change'); const disabled = dirty();
          active.checked = true; await active.fire('change');
          console.log(JSON.stringify({changes,disabled,restored:dirty()}));
        """))
        for change in result['changes']:
            with self.subTest(label=change['label']):
                self.assertEqual(change['changed'], 'true')
                self.assertEqual(change['reverted'], 'false')
        self.assertEqual(result['disabled'], 'true')
        self.assertEqual(result['restored'], 'false')

    def test_layer_add_remove_order_and_field_replacement_are_dirty(self) -> None:
        result = run_node(m4_script("""
          await prepare(); await button('Save').fire('click');
          await button('Add Layer').fire('click'); const added = dirty();
          await rowButton('Remove',1).fire('click'); const removedAddition = dirty();
          await button('Add Layer').fire('click');
          await choosePreset('Right',1); await button('Save').fire('click');
          const savedTwo = dirty();
          await rowButton('Down').fire('click'); const reordered = dirty();
          await rowButton('Up',1).fire('click'); const orderRestored = dirty();
          await choosePreset('Right'); const starter = dirty();
          await button('Save').fire('click');
          fileInput().files = [new File(['custom'], 'custom.png', {type:'image/png'})];
          await fileInput().fire('change'); const custom = dirty();
          await button('Save').fire('click');
          await rowButton('Remove').fire('click');
          console.log(JSON.stringify({added,removedAddition,savedTwo,reordered,orderRestored,
            starter,custom,removed:dirty()}));
        """))
        for name in ('added', 'reordered', 'starter', 'custom', 'removed'):
            self.assertEqual(result[name], 'true', name)
        for name in ('removedAddition', 'savedTwo', 'orderRestored'):
            self.assertEqual(result[name], 'false', name)

    def test_successful_save_sets_exact_baseline_and_preserves_edits_during_save(self) -> None:
        result = run_node(m4_script("""
          await prepare();
          const saveGate = deferred(); let snapshot;
          intercept = async (url, options) => {
            if (options.body && url.includes('/documents')) {
              const response = await defaultFetch(url,options);
              snapshot = await response.json(); await saveGate.promise; return reply(snapshot);
            }
          };
          const pending = button('Save').fire('click'); await settle();
          const editingAllowed = !control('Base Prompt').disabled;
          await edit('Base Prompt','Newer scene'); await edit('Prompt','Newer subject',row());
          saveGate.resolve(); await pending;
          const after = {base:control('Base Prompt').value,prompt:control('Prompt',row()).value,
            dirty:dirty(), name:control('Document name').value, selected:selected()};
          intercept = null; await button('Save').fire('click');
          console.log(JSON.stringify({editingAllowed,snapshot,after,clean:dirty(),uploads,
            writes:m4Requests.filter(call => ['POST','PUT'].includes(call.method))}));
        """))
        self.assertTrue(result['editingAllowed'])
        self.assertEqual(result['snapshot']['base_prompt'], 'Initial scene')
        self.assertEqual(result['after'], {
            'base': 'Newer scene', 'prompt': 'Newer subject', 'dirty': 'true',
            'name': 'Study', 'selected': 'Saved Influence Field',
        })
        self.assertEqual(result['clean'], 'false')
        self.assertEqual([call['method'] for call in result['writes']], ['POST', 'PUT'])
        self.assertEqual(result['uploads'][1]['request']['document_id'], 'document-1')
        self.assertEqual(result['uploads'][1]['request']['base_prompt'], 'Newer scene')
        self.assertEqual(result['uploads'][1]['uploads'], [])

    def test_save_merge_tracks_rows_and_keeps_later_custom_fields(self) -> None:
        result = run_node(m4_script("""
          await prepare(); await button('Add Layer').fire('click');
          await choosePreset('Right',1);
          await edit('Layer name','First',row()); await edit('Layer name','Second',row(1));
          const saveGate = deferred();
          intercept = async (url, options) => {
            if (options.body && url.includes('/documents')) {
              const response = await defaultFetch(url,options); const payload = await response.json();
              await saveGate.promise; return reply(payload);
            }
          };
          const pending = button('Save').fire('click'); await settle();
          await rowButton('Down').fire('click');
          fileInput().files = [new File(['newer custom'],'newer.png',{type:'image/png'})];
          await fileInput().fire('change');
          await rowButton('Remove',1).fire('click');
          saveGate.resolve(); await pending;
          const after = {dirty:dirty(),rows:container.querySelectorAll('.cl-layer').length,
            name:control('Layer name',row()).value,selected:selected()};
          intercept = null; await button('Save').fire('click');
          console.log(JSON.stringify({after,uploads,clean:dirty()}));
        """))
        self.assertEqual(result['after'], {
            'dirty': 'true', 'rows': 1, 'name': 'Second', 'selected': 'Selected: newer.png',
        })
        request = result['uploads'][1]['request']
        self.assertEqual(request['layers'][0]['layer_id'], 'layer-2')
        self.assertFalse(request['layers'][0]['retained_field'])
        self.assertEqual(len(result['uploads'][1]['uploads']), 1)
        self.assertEqual(result['clean'], 'false')

    def test_save_response_preserves_focused_newer_prompt_and_selection(self) -> None:
        result = run_node(m4_script("""
          Node.prototype.focus = function () { document.activeElement = this; };
          Node.prototype.closest = function (selector) {
            for (let item = this; item; item = item.parent) {
              if (item.className.split(' ').includes(selector.slice(1))) return item;
            }
            return null;
          };
          Node.prototype.setSelectionRange = function (start, end) {
            this.selectionStart = start; this.selectionEnd = end;
          };
          await prepare(); const gate = deferred();
          intercept = async (url,options) => {
            if (options.body && url.includes('/documents')) {
              const response = await defaultFetch(url,options); const payload = await response.json();
              await gate.promise; return reply(payload);
            }
          };
          const pending = button('Save').fire('click'); await settle();
          await edit('Prompt','Newer detailed subject',row());
          const priorPrompt = control('Prompt',row());
          priorPrompt.focus(); priorPrompt.setSelectionRange(6,14);
          gate.resolve(); await pending;
          const restored = control('Prompt',row());
          console.log(JSON.stringify({focused:document.activeElement === restored,
            replaced:restored !== priorPrompt,prompt:restored.value,
            selection:[restored.selectionStart,restored.selectionEnd],dirty:dirty(),
            savedPrompt:uploads[0].request.layers[0].prompt_text}));
        """))
        self.assertTrue(result['focused'])
        self.assertTrue(result['replaced'])
        self.assertEqual(result['prompt'], 'Newer detailed subject')
        self.assertEqual(result['selection'], [6, 14])
        self.assertEqual(result['dirty'], 'true')
        self.assertEqual(result['savedPrompt'], '')

    def test_failed_save_keeps_dirty_content_and_does_not_establish_identity(self) -> None:
        result = run_node(m4_script("""
          await prepare(); saveFailure = {findings:[{code:'save.failed',severity:'error',message:'Failed'}]};
          await button('Save').fire('click');
          const afterFailure = {dirty:dirty(),base:control('Base Prompt').value};
          saveFailure = null; await button('Save').fire('click');
          console.log(JSON.stringify({afterFailure,clean:dirty(),
            writes:m4Requests.filter(call => ['POST','PUT'].includes(call.method))}));
        """))
        self.assertEqual(result['afterFailure'], {'dirty': 'true', 'base': 'Initial scene'})
        self.assertEqual(result['clean'], 'false')
        self.assertEqual([call['method'] for call in result['writes']], ['POST', 'POST'])

    def test_edit_reverted_during_save_matches_saved_snapshot_and_becomes_clean(self) -> None:
        result = run_node(m4_script("""
          await prepare(); const gate = deferred();
          intercept = async (url,options) => {
            if (options.body && url.includes('/documents')) {
              const response = await defaultFetch(url,options); const payload = await response.json();
              await gate.promise; return reply(payload);
            }
          };
          const pending = button('Save').fire('click'); await settle();
          await edit('Base Prompt','Temporary edit'); await edit('Base Prompt','Initial scene');
          gate.resolve(); await pending;
          console.log(JSON.stringify({dirty:dirty(),base:control('Base Prompt').value,selected:selected()}));
        """))
        self.assertEqual(result, {
            'dirty': 'false', 'base': 'Initial scene', 'selected': 'Saved Influence Field',
        })

    def test_changed_saved_name_stays_dirty_until_saved_as(self) -> None:
        result = run_node(m4_script("""
          await prepare(); await button('Save').fire('click');
          await edit('Document name','Copy'); const changed = dirty();
          const before = uploads.length; await button('Save').fire('click');
          const ordinarySave = {writes:uploads.length-before,dirty:dirty(),text:container.textContent};
          await button('Save As').fire('click');
          console.log(JSON.stringify({changed,ordinarySave,clean:dirty(),uploads}));
        """))
        self.assertEqual(result['changed'], 'true')
        self.assertEqual(result['ordinarySave']['writes'], 0)
        self.assertEqual(result['ordinarySave']['dirty'], 'true')
        self.assertIn('Save As', result['ordinarySave']['text'])
        self.assertEqual(result['uploads'][-1]['request']['display_name'], 'Copy')
        self.assertEqual(result['clean'], 'false')


class M4DocumentActionTests(unittest.TestCase):
    def test_initial_document_inventory_survives_new_and_generate_actions(self) -> None:
        before_render = """
          let releaseInitialList; let initialListRequested = false;
          const initialListGate = new Promise(resolve => { releaseInitialList = resolve; });
          const initialBoundary = globalThis.testApi.fetchApi;
          globalThis.testApi.fetchApi = async (url,options = {}) => {
            if (url === '/conditioning-layers/documents' && !options.method && !initialListRequested) {
              initialListRequested = true; await initialListGate;
              return {ok:true,json:async () => ({documents:[{document_key:'existing',display_name:'Existing'}]})};
            }
            return initialBoundary(url,options);
          };
        """
        for action in ('new', 'generate'):
            with self.subTest(action=action):
                result = run_node(m4_script("""
                  intercept = async (url,options) => {
                    if (url === '/conditioning-layers/executions' && options.method === 'POST') return reply({
                      execution_id:'00000000000000000000000000000001',state:'accepted',seed:'0',terminal:false,findings:[],
                    });
                    if (url.startsWith('/conditioning-layers/executions/')) return reply({
                      execution_id:'00000000000000000000000000000001',state:'completed',seed:'0',terminal:true,findings:[],output:safeOutput('00000000000000000000000000000001'),
                    });
                  };
                """ + ("await button('New Document').fire('click');" if action == 'new' else
                       "await prepare(); await button('Generate').fire('click');") + """
                  releaseInitialList(); await settle();
                  console.log(JSON.stringify({options:control('Saved Conditioning Layers document').children
                    .map(option => option.value),confirmations}));
                """, before_render=before_render))
                self.assertIn('existing', result['options'])
                self.assertEqual(result['confirmations'], [])

    def test_newer_saved_document_inventory_wins_over_delayed_initial_list(self) -> None:
        result = run_node(m4_script("""
          await prepare(); await button('Save').fire('click');
          const before = control('Saved Conditioning Layers document').children.map(option => option.value);
          releaseInitialList(); await settle();
          console.log(JSON.stringify({before,after:control('Saved Conditioning Layers document').children
            .map(option => option.value),selected:control('Saved Conditioning Layers document').children
            .find(option => option.selected)?.value}));
        """, before_render="""
          let releaseInitialList; let initialListRequested = false;
          const initialListGate = new Promise(resolve => { releaseInitialList = resolve; });
          const initialBoundary = globalThis.testApi.fetchApi;
          globalThis.testApi.fetchApi = async (url,options = {}) => {
            if (url === '/conditioning-layers/documents' && !options.method && !initialListRequested) {
              initialListRequested = true; await initialListGate;
              return {ok:true,json:async () => ({documents:[{document_key:'old',display_name:'Old'}]})};
            }
            return initialBoundary(url,options);
          };
        """))
        self.assertEqual(result['before'], ['', 'study'])
        self.assertEqual(result['after'], result['before'])
        self.assertEqual(result['selected'], 'study')

    def test_dirty_new_and_open_require_confirmation_and_cancel_preserves_state(self) -> None:
        result = run_node(m4_script("""
          await prepare(); confirmResult = false;
          const before = container.textContent; const preview = find(node => node.tagName === 'img').src;
          await button('New Document').fire('click');
          await chooseOpen('another');
          console.log(JSON.stringify({confirmations,dirty:dirty(),name:control('Document name').value,
            base:control('Base Prompt').value,selected:selected(),
            preview:find(node => node.tagName === 'img').src,sameText:container.textContent === before,
            originalPreview:preview,openRequests:m4Requests.filter(call => call.url.endsWith('/another'))}));
        """))
        self.assertEqual(len(result['confirmations']), 2)
        self.assertEqual(result['dirty'], 'true')
        self.assertEqual(result['name'], 'Study')
        self.assertEqual(result['base'], 'Initial scene')
        self.assertEqual(result['selected'], 'Selected preset: Left')
        self.assertEqual(result['preview'], result['originalPreview'])
        self.assertTrue(result['sameText'])
        self.assertEqual(result['openRequests'], [])

    def test_newer_open_wins_when_older_response_arrives_last(self) -> None:
        result = run_node(m4_script("""
          const first = deferred(); const second = deferred();
          intercept = async url => url.endsWith('/first') ? first.promise
            : url.endsWith('/second') ? second.promise : undefined;
          const oldOpen = chooseOpen('first'); await settle();
          const newerOpen = chooseOpen('second'); await settle();
          second.resolve(reply(record('second'))); await newerOpen;
          first.resolve(reply(record('first'))); await oldOpen;
          console.log(JSON.stringify({base:control('Base Prompt').value,
            name:control('Document name').value,dirty:dirty(),confirmations}));
        """))
        self.assertEqual(result['base'], 'second')
        self.assertEqual(result['name'], 'second')
        self.assertEqual(result['dirty'], 'false')
        self.assertEqual(result['confirmations'], [])

    def test_new_supersedes_open_and_late_open_preserves_subsequent_edits(self) -> None:
        result = run_node(m4_script("""
          const openGate = deferred();
          intercept = async url => url.endsWith('/old') ? openGate.promise : undefined;
          const pending = chooseOpen('old'); await settle();
          await button('New Document').fire('click');
          await edit('Base Prompt','New document edit');
          openGate.resolve(reply(record('old'))); await pending;
          console.log(JSON.stringify({base:control('Base Prompt').value,
            name:control('Document name').value,dirty:dirty(),confirmations}));
        """))
        self.assertEqual(result['base'], 'New document edit')
        self.assertEqual(result['name'], '')
        self.assertEqual(result['dirty'], 'true')
        self.assertEqual(result['confirmations'], [])

    def test_edit_during_open_is_not_discarded_by_late_response(self) -> None:
        result = run_node(m4_script("""
          const openGate = deferred();
          intercept = async url => url.endsWith('/old') ? openGate.promise : undefined;
          const pending = chooseOpen('old'); await settle();
          await edit('Base Prompt','Typed while opening');
          openGate.resolve(reply(record('old'))); await pending;
          console.log(JSON.stringify({base:control('Base Prompt').value,dirty:dirty()}));
        """))
        self.assertEqual(result['base'], 'Typed while opening')
        self.assertEqual(result['dirty'], 'true')

    def test_new_and_open_wait_for_pending_save_while_editor_changes_are_preserved(self) -> None:
        for replacement in ('new', 'open'):
            with self.subTest(replacement=replacement):
                result = run_node(m4_script("""
                  await prepare(); const gate = deferred();
                  intercept = async (url,options) => {
                    if (options.body && url.includes('/documents')) {
                      const response = await defaultFetch(url,options); const payload = await response.json();
                      await gate.promise; return reply(payload);
                    }
                    if (url.endsWith('/replacement')) return reply(record('replacement'));
                  };
                  const pending = button('Save').fire('click'); await settle();
                  const replacementDisabled = button('New Document').disabled && button('Open').disabled
                    && control('Saved Conditioning Layers document').disabled;
                  await edit('Base Prompt','Edit made while saving');
                """ + ("await button('New Document').fire('click');" if replacement == 'new'
                       else "await chooseOpen('replacement');") + """
                  const before = {base:control('Base Prompt').value,name:control('Document name').value,
                    dirty:dirty()};
                  gate.resolve(); await pending;
                  const after = {base:control('Base Prompt').value,name:control('Document name').value,
                    dirty:dirty()};
                  console.log(JSON.stringify({before,after,confirmations,replacementDisabled,
                    replacementEnabled:!button('New Document').disabled && !button('Open').disabled,
                    reads:m4Requests.filter(call => call.url.endsWith('/replacement'))}));
                """))
                self.assertTrue(result['replacementDisabled'])
                self.assertTrue(result['replacementEnabled'])
                self.assertEqual(result['after'], result['before'])
                self.assertEqual(result['after']['base'], 'Edit made while saving')
                self.assertEqual(result['after']['dirty'], 'true')
                self.assertEqual(result['confirmations'], [])
                self.assertEqual(result['reads'], [])

    def test_older_open_completion_does_not_clear_newer_open_pending_state(self) -> None:
        result = run_node(m4_script("""
          const first = deferred(); const second = deferred();
          intercept = async url => url.endsWith('/first') ? first.promise
            : url.endsWith('/second') ? second.promise : undefined;
          const older = chooseOpen('first'); await settle();
          const newer = chooseOpen('second'); await settle();
          first.resolve(reply(record('first'))); await older;
          const midway = {base:control('Base Prompt').value,generateDisabled:button('Generate').disabled};
          second.resolve(reply(record('second'))); await newer;
          console.log(JSON.stringify({midway,base:control('Base Prompt').value,
            generateEnabled:!button('Generate').disabled}));
        """))
        self.assertEqual(result['midway'], {'base': '', 'generateDisabled': True})
        self.assertEqual(result['base'], 'second')
        self.assertTrue(result['generateEnabled'])

    def test_disposal_ignores_late_open_and_save_responses(self) -> None:
        for operation in ('open', 'save'):
            with self.subTest(operation=operation):
                result = run_node(m4_script("""
                  await prepare(); const gate = deferred();
                  intercept = async (url, options) => {
                    if (url.endsWith('/old')) return gate.promise;
                    if (options.body && url.includes('/documents')) {
                      const response = await defaultFetch(url,options); const payload = await response.json();
                      await gate.promise; return reply(payload);
                    }
                  };
                """ + ("const pending = chooseOpen('old');" if operation == 'open'
                       else "const pending = button('Save').fire('click');") + """
                  await settle(); const detachedRoot = container.children[0];
                  dispose(); const before = detachedRoot.textContent;
                  const callCount = m4Requests.length;
                  gate.resolve(reply(record('old'))); await pending; await settle();
                  console.log(JSON.stringify({children:container.children.length,
                    unchanged:detachedRoot.textContent === before,
                    laterRequests:m4Requests.slice(callCount),created:created.length,revoked}));
                """))
                self.assertEqual(result['children'], 0)
                self.assertTrue(result['unchanged'])
                self.assertEqual(result['laterRequests'], [])
                self.assertEqual(len(result['revoked']), result['created'])


class M4SeedRepeatTests(unittest.TestCase):
    def test_seed_rendered_label_and_accessible_name_agree_with_unchanged_options(self) -> None:
        result = run_node(m4_script("""
          const mode = control('Next generation seed');
          console.log(JSON.stringify({label:mode.parent.children[0].textContent,
            name:mode.attributes['aria-label'],value:mode.value,
            options:mode.children.map(option => ({value:option.value,text:option.textContent})),
            reuse:reuseAvailable()}));
        """))
        self.assertEqual(result, {
            'label': 'Next generation seed', 'name': 'Next generation seed', 'value': 'new',
            'options': [{'value': 'new', 'text': 'New seed each run'},
                        {'value': 'reuse', 'text': 'Reuse last successful seed'}], 'reuse': False,
        })

    def test_dirty_discard_cancel_preserves_then_accept_clears_prior_successful_run(self) -> None:
        for action in ('New Document', 'Open'):
            with self.subTest(action=action):
                result = run_node(m4_script('const action = ' + json.dumps(action) + ';' + """
                  const assert = (await import('node:assert/strict')).default;
                  await prepare(); await button('Save').fire('click');
                  const id = '00000000000000000000000000000001';
                  intercept = async (url,options) => {
                    if (url === '/conditioning-layers/executions') return reply({
                      execution_id:id,state:'accepted',seed:'18446744073709551615',terminal:false,findings:[]});
                    if (url.startsWith('/conditioning-layers/executions/')) return reply({
                      execution_id:id,state:'completed',seed:'18446744073709551615',terminal:true,
                      findings:[],output:safeOutput(id)});
                  };
                  // Offline HTTP fixture only; never a real browser or inference.
                  await button('Generate').fire('click'); await selectMode('reuse');
                  await edit('Base Prompt','H4 discard this edit');
                  control('Saved Conditioning Layers document').value = 'study';
                  const prior = lastRun(); const requestsBefore = m4Requests.length;
                  const output = () => descendants(container).filter(node => node.alt === 'Conditioning Layers generated result');
                  assert.equal(output().length,1); assert.equal(reuseAvailable(),true);
                  confirmResult = false; await button(action).fire('click');
                  assert.equal(lastRun(),prior); assert.equal(reuseAvailable(),true);
                  assert.equal(control('Next generation seed').value,'reuse');
                  assert.equal(output().length,1); assert.equal(dirty(),'true');
                  confirmResult = true; await button(action).fire('click');
                  console.log(JSON.stringify({last:lastRun(),reuse:reuseAvailable(),
                    mode:control('Next generation seed').value,outputs:output().length,dirty:dirty(),
                    base:control('Base Prompt').value,confirmations,requests:m4Requests.slice(requestsBefore)}));
                """))
                self.assertEqual(result['last'], 'No run for this document in this panel session.')
                self.assertFalse(result['reuse'])
                self.assertEqual(result['mode'], 'new')
                self.assertEqual(result['outputs'], 0)
                self.assertEqual(result['dirty'], 'false')
                self.assertEqual(result['base'], '' if action == 'New Document' else 'Initial scene')
                self.assertEqual(result['confirmations'],
                                 ['Discard unsaved changes to this Conditioning Document?'] * 2)
                self.assertEqual(result['requests'], [] if action == 'New Document' else
                                 [{'url': '/conditioning-layers/documents/study', 'method': 'GET'}])

    def test_exact_submitted_seed_successful_reuse_new_seed_and_fresh_requests(self) -> None:
        result = run_node(m4_script("""
          await prepare(); await button('Save').fire('click');
          const maximum = '18446744073709551615'; const firstCompletion = deferred();
          const executions = []; let index = 0;
          intercept = async (url,options) => {
            if (url === '/conditioning-layers/executions' && options.method === 'POST') {
              const serialized = await parts(options.body); executions.push(serialized.request); index++;
              return reply({execution_id:`${String(index).padStart(32,'0')}`,state:'accepted',seed:index < 3 ? maximum : '7',
                terminal:false,findings:[]});
            }
            if (url.startsWith('/conditioning-layers/executions/')) {
              if (url.endsWith('/00000000000000000000000000000001')) return firstCompletion.promise;
              return reply({execution_id:`${String(index).padStart(32,'0')}`,state:'completed',seed:index < 3 ? maximum : '7',
                terminal:true,findings:[],output:safeOutput(`${String(index).padStart(32,'0')}`)});
            }
          };
          const before = {reuse:reuseAvailable(),summary:seedSummary(),dirty:dirty()};
          const firstRun = button('Generate').fire('click'); await settle();
          const submitted = {text:lastRun(),reuse:reuseAvailable()};
          await button('Generate').fire('click'); const pendingSubmissions = executions.length;
          await edit('Base Prompt','Revised after submission');
          firstCompletion.resolve(reply({execution_id:'00000000000000000000000000000001',state:'completed',seed:maximum,
            terminal:true,findings:[],output:safeOutput('00000000000000000000000000000001')}));
          await firstRun;
          const completed = {text:lastRun(),reuse:reuseAvailable(),generateEnabled:!button('Generate').disabled};
          await selectMode('reuse'); const reusedSummary = seedSummary();
          await button('Generate').fire('click');
          const repeated = {text:lastRun(),generateEnabled:!button('Generate').disabled,
            image:find(node => node.alt === 'Conditioning Layers generated result').src};
          await selectMode('new'); const newSummary = seedSummary();
          await button('Generate').fire('click');
          console.log(JSON.stringify({before,submitted,pendingSubmissions,completed,reusedSummary,
            repeated,newSummary,executions,last:lastRun(),dirty:dirty()}));
        """))
        maximum = '18446744073709551615'
        self.assertFalse(result['before']['reuse'])
        self.assertEqual(result['before']['dirty'], 'false')
        self.assertIn('new', result['before']['summary'].lower())
        self.assertIn(maximum, result['submitted']['text'])
        self.assertIn('accepted', result['submitted']['text'])
        self.assertFalse(result['submitted']['reuse'])
        self.assertEqual(result['pendingSubmissions'], 1)
        self.assertTrue(result['completed']['reuse'])
        self.assertTrue(result['completed']['generateEnabled'])
        self.assertIn('completed', result['completed']['text'])
        self.assertIn('changed', result['completed']['text'].lower())
        self.assertIn(maximum, result['reusedSummary'])
        self.assertTrue(result['repeated']['generateEnabled'])
        self.assertEqual(result['repeated']['image'], '/view?filename=00000000000000000000000000000002_00001_.png&subfolder=conditioning-layers-panel&type=output')
        self.assertIn('new', result['newSummary'].lower())
        requests = result['executions']
        self.assertEqual(len(requests), 3)
        self.assertNotIn('seed', requests[0])
        self.assertEqual(requests[1]['seed'], maximum)
        self.assertIsInstance(requests[1]['seed'], str)
        self.assertEqual(requests[1]['base_prompt'], 'Revised after submission')
        self.assertNotIn('seed', requests[2])
        self.assertEqual(len({request['idempotency_key'] for request in requests}), 3)
        self.assertIn('7', result['last'])
        self.assertEqual(result['dirty'], 'true')

    def test_failed_and_rejected_runs_keep_last_successful_reusable_seed(self) -> None:
        for outcome in ('failed', 'rejected'):
            with self.subTest(outcome=outcome):
                result = run_node(m4_script("""
                  await prepare(); let index = 0; const executions = [];
                """ + f"const outcome = {outcome!r};" + """
                  intercept = async (url,options) => {
                    if (url === '/conditioning-layers/executions' && options.method === 'POST') {
                      executions.push((await parts(options.body)).request); index++;
                      if (index === 2 && outcome === 'rejected') {
                        return reply({state:'rejected',seed:'99',findings:[]},false);
                      }
                      return reply({execution_id:`${String(index).padStart(32,'0')}`,state:'accepted',seed:index === 2 ? '99' : '0',
                        terminal:false,findings:[]});
                    }
                    if (url.startsWith('/conditioning-layers/executions/')) return reply({
                      execution_id:`${String(index).padStart(32,'0')}`,state:index === 2 ? outcome : 'completed',
                      seed:index === 2 ? '99' : '0',terminal:true,findings:[],
                      ...(index === 2 ? {} : {output:safeOutput(`${String(index).padStart(32,'0')}`)}),
                    });
                  };
                  await button('Generate').fire('click');
                  const afterSuccess = reuseAvailable();
                  await button('Generate').fire('click');
                  const afterFailure = {reuse:reuseAvailable(),text:lastRun()};
                  await selectMode('reuse'); const summary = seedSummary();
                  await button('Generate').fire('click');
                  console.log(JSON.stringify({afterSuccess,afterFailure,summary,executions}));
                """))
                self.assertTrue(result['afterSuccess'])
                self.assertTrue(result['afterFailure']['reuse'])
                self.assertIn(outcome, result['afterFailure']['text'])
                self.assertIn('0', result['summary'])
                self.assertEqual(result['executions'][2]['seed'], '0')
                self.assertEqual(len({request['idempotency_key'] for request in result['executions']}), 3)

    def test_seed_and_last_run_are_transient_save_preserves_run_open_new_reset_it(self) -> None:
        result = run_node(m4_script("""
          await prepare();
          intercept = async (url,options) => {
            if (url === '/conditioning-layers/executions' && options.method === 'POST') return reply({
              execution_id:'00000000000000000000000000000001',state:'accepted',seed:'18446744073709551615',terminal:false,findings:[],
            });
            if (url.startsWith('/conditioning-layers/executions/')) return reply({
              execution_id:'00000000000000000000000000000001',state:'completed',seed:'18446744073709551615',terminal:true,findings:[],
              output:safeOutput('00000000000000000000000000000001'),
            });
          };
          await button('Generate').fire('click'); await selectMode('reuse');
          const prior = lastRun(); await button('Save').fire('click');
          const afterSave = {last:lastRun(),reuse:reuseAvailable(),mode:control('Next generation seed').value,
            dirty:dirty(),image:find(node => node.alt === 'Conditioning Layers generated result').src};
          await button('New Document').fire('click');
          const afterNew = {last:lastRun(),reuse:reuseAvailable(),mode:control('Next generation seed').value,dirty:dirty()};
          await chooseOpen('study');
          const afterOpen = {last:lastRun(),reuse:reuseAvailable(),mode:control('Next generation seed').value,dirty:dirty()};
          console.log(JSON.stringify({prior,afterSave,afterNew,afterOpen,uploads}));
        """))
        self.assertIn('18446744073709551615', result['afterSave']['last'])
        self.assertTrue(result['afterSave']['reuse'])
        self.assertEqual(result['afterSave']['mode'], 'reuse')
        self.assertEqual(result['afterSave']['dirty'], 'false')
        self.assertEqual(result['afterSave']['image'], '/view?filename=00000000000000000000000000000001_00001_.png&subfolder=conditioning-layers-panel&type=output')
        for name in ('afterNew', 'afterOpen'):
            self.assertFalse(result[name]['reuse'])
            self.assertEqual(result[name]['mode'], 'new')
            self.assertEqual(result[name]['dirty'], 'false')
            self.assertNotIn('18446744073709551615', result[name]['last'])
        self.assertNotIn('seed', result['uploads'][0]['request'])
        self.assertTrue(all('seed' not in layer for layer in result['uploads'][0]['request']['layers']))

    def test_disposed_panel_ignores_late_execution_completion(self) -> None:
        result = run_node(m4_script("""
          await prepare(); const completion = deferred();
          intercept = async (url,options) => {
            if (url === '/conditioning-layers/executions' && options.method === 'POST') return reply({
              execution_id:'00000000000000000000000000000001',state:'accepted',seed:'0',terminal:false,findings:[],
            });
            if (url.startsWith('/conditioning-layers/executions/')) return completion.promise;
          };
          const pending = button('Generate').fire('click'); await settle();
          const detachedRoot = container.children[0]; dispose(); const before = detachedRoot.textContent;
          completion.resolve(reply({execution_id:'00000000000000000000000000000001',state:'completed',seed:'0',terminal:true,
            findings:[],output:safeOutput('00000000000000000000000000000001')}));
          await pending;
          console.log(JSON.stringify({children:container.children.length,
            unchanged:detachedRoot.textContent === before,
            images:descendants(detachedRoot).filter(node => node.alt === 'Conditioning Layers generated result').length}));
        """))
        self.assertEqual(result['children'], 0)
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['images'], 0)

    def test_unknown_submission_preserves_successful_seed_but_not_prior_run_association(self) -> None:
        result = run_node(m4_script("""
          await prepare(); let submissions = 0;
          intercept = async (url,options) => {
            if (url === '/conditioning-layers/executions' && options.method === 'POST') {
              submissions++;
              if (submissions > 1) throw new Error('Lost submission response');
              return reply({execution_id:'00000000000000000000000000000001',state:'accepted',seed:'123',terminal:false,findings:[]});
            }
            if (url.startsWith('/conditioning-layers/executions/')) return reply({
              execution_id:'00000000000000000000000000000001',state:'completed',seed:'123',terminal:true,findings:[],output:safeOutput('00000000000000000000000000000001'),
            });
            if (url.endsWith('/existing')) return reply(record('existing'));
          };
          await button('Generate').fire('click');
          await edit('Base Prompt','Revised run'); await button('Generate').fire('click');
          const unknown = lastRun(); await selectMode('reuse'); const summary = seedSummary();
          await button('Generate').fire('click');
          await edit('Base Prompt','Still editable');
          const edited = {base:control('Base Prompt').value,reuse:reuseAvailable()};
          await button('New Document').fire('click'); await button('Generate').fire('click');
          const blockedAfterNew = button('Generate').disabled;
          await chooseOpen('existing'); await button('Generate').fire('click');
          console.log(JSON.stringify({submissions,unknown,summary,blocked:button('Generate').disabled,
            blockedAfterNew,edited,opened:control('Base Prompt').value}));
        """))
        self.assertEqual(result['submissions'], 2)
        self.assertIn('unknown', result['unknown'])
        self.assertIn('not available', result['unknown'])
        self.assertNotIn('123', result['unknown'])
        self.assertIn('123', result['summary'])
        self.assertTrue(result['blocked'])
        self.assertTrue(result['blockedAfterNew'])
        self.assertTrue(result['edited']['reuse'])
        self.assertEqual(result['edited']['base'], 'Still editable')
        self.assertEqual(result['opened'], 'existing')

    def test_numeric_or_noncanonical_job_seed_is_never_made_reusable(self) -> None:
        for seed in (18446744073709551615, '18446744073709551616', '00', '+1', ' 1', '1e2'):
            with self.subTest(seed=seed):
                result = run_node(m4_script("const invalid = " + json.dumps(seed) + ";" + """
                  await prepare();
                  intercept = async (url,options) => {
                    if (url === '/conditioning-layers/executions' && options.method === 'POST') return reply({
                      execution_id:'00000000000000000000000000000001',state:'accepted',seed:invalid,
                      terminal:false,findings:[],
                    });
                    throw new Error('Invalid initial association must not be polled');
                  };
                  await button('Generate').fire('click');
                  console.log(JSON.stringify({reuse:reuseAvailable(),text:lastRun(),blocked:button('Generate').disabled}));
                """))
                self.assertFalse(result['reuse'])
                self.assertIn('Seed: not available', result['text'])
                self.assertTrue(result['blocked'])


if __name__ == '__main__':
    unittest.main()
