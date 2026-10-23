"""ADR-0036 exact CPU and fenced frontend checks. No live host/visual acceptance."""
import asyncio
import base64
import copy
import json
import math
import runpy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from conditioning_layers.integrations import composition_preview as preview
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.composition import compose_field_codes
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.models import LayerMode
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import normalize_sample_codes_bits
from test_field_editor_custom_tip import ROOT, run_node
from test_field_editor_multi_field import ADAPTER, EDITOR


LEGACY = preview.LEGACY_COMPOSE


def layer(identity, codes=(1, 128, 255, 0), strength=1.0, mode="BLENDED", enabled=True, group=""):
    return {"id": str(identity), "codes": list(codes) * (16384 // len(codes)),
            "strength": strength, "mode": mode, "enabled": enabled, "group": group}


class NumericalTests(unittest.TestCase):
    def test_optional_registration_failure_cannot_disable_native_nodes(self):
        panel = SimpleNamespace(register_routes=lambda: None)
        with patch.dict(sys.modules, {"conditioning_layers.integrations.comfyui_panel.routes": panel}), \
                patch.object(preview, "register_preview_route", side_effect=RuntimeError("preview unavailable")):
            root = runpy.run_path(str(ROOT / "__init__.py"))
        self.assertEqual(root["COMPOSITION_PREVIEW_REGISTRATION_ERROR"], "RuntimeError")
        for name in ("ConditioningLayersLayer", "ConditioningLayersAddLayer", "ConditioningLayersCompose",
                     "ConditioningLayersPaintedField"):
            self.assertIn(name, root["NODE_CLASS_MAPPINGS"])
        self.assertNotIn("torch", sys.modules)

    def test_exact_equivalence_arbitrary_n_and_full_strength_domain(self):
        for count in (1, 2, 3, 5, 12, 17, 40):
            strengths = (0.0, 5e-324, 1e-37, 0.1, 0.5, 1.0)
            layers = [layer(i, (1, 129, 255, 0), strengths[i % len(strengths)]) for i in range(count)]
            expected = compose_field_codes(tuple(tuple(l["codes"]) for l in layers),
                                           tuple(l["strength"] for l in layers), (LayerMode.BLENDED,) * count)
            original = copy.deepcopy(layers)
            for i in {0, count - 1}:
                result = preview.preview_composition({"compose": LEGACY, "layers":layers, "selected": str(i)})
                self.assertEqual(result["bits"], list(expected[i]))
            self.assertEqual(layers, original)

    def test_rounding_boundary_and_tiny_solo(self):
        for strengths in ((1.0, 0.5), (5e-324, 5e-324), (5e-324, 0.0),
                          (1.0, math.nextafter(1.0, 0.0)), (1.0, 2**-149), (1.0, 2**-150)):
            layers = [layer(i, (1,), strength) for i, strength in enumerate(strengths)]
            expected = normalize_sample_codes_bits((1, 1), strengths)
            for i in (0, 1):
                self.assertEqual(preview.preview_composition({"compose": LEGACY, "layers":layers, "selected": str(i)})["bits"],
                                 [expected[i]] * 16384)
        self.assertEqual(normalize_sample_codes_bits((1, 1), (5e-324, 0.0)), (0x3f800000, 0))

    def test_fixed_zero_suppresses_blended_without_refill(self):
        for strength in (0.0, 5e-324, 0.01):
            layers = [layer("owner", (0, 1, 64, 255), strength, "FIXED"), layer("blend", (0, 255, 255, 255))]
            a = preview.preview_composition({"compose": LEGACY, "layers":layers, "selected": "owner"})
            b = preview.preview_composition({"compose": LEGACY, "layers":layers, "selected": "blend"})
            self.assertEqual(a["bits"][:4], [0] + [0 if strength == 0 else 0x3f800000] * 3)
            self.assertEqual(b["bits"], [0] * 16384)

    def test_fixed_conflicts_independent_of_strength_order_and_identical_data(self):
        layers = [layer("a", (1, 0, 1, 0), 0.0, "FIXED"), layer("b", (1, 1, 0, 0), 0.0, "FIXED")]
        for values in (layers, list(reversed(layers))):
            result = preview.preview_composition({"compose": LEGACY, "layers":values, "selected": "a"})
            self.assertEqual(result["status"], "conflict")
            self.assertEqual(result["cells"], list(range(0, 16384, 4)))
            self.assertEqual(result["pairs"][0]["count"], 4096)
            self.assertEqual(set(result["pairs"][0]["layers"]), {"a", "b"})
            self.assertNotIn("bits", result)
        layers = [layer("a"), layer("b")]
        self.assertEqual(preview.preview_composition({"compose": LEGACY, "layers":layers, "selected": "a"})["bits"][:4],
                         [0x3f000000] * 3 + [0])

    def test_disabled_fields_not_read_and_empty_support(self):
        disabled = layer("off", mode="FIXED", enabled=False); disabled["codes"] = {"invalid": True}
        layers = [disabled, layer("on", strength=0.0)]
        for selected in ("on", "off"):
            result = preview.preview_composition({"compose": LEGACY, "layers":layers, "selected": selected})
            self.assertEqual(result["bits"], [0] * 16384)
            self.assertEqual(result["disabled"], selected == "off")
        with self.assertRaisesRegex(ValueError, "no enabled"):
            preview.preview_composition({"compose": LEGACY, "layers":[disabled], "selected": "off"})

    def test_malformed_and_incomplete_inputs_fail_closed(self):
        base = {"compose": LEGACY, "layers":[layer("a")], "selected": "a"}
        mutations = [lambda p: p.update(selected="missing"), lambda p: p["layers"].append(layer("a")),
                     lambda p: p["layers"][0].update(codes=[0] * 16384),
                     lambda p: p["layers"][0].update(codes=[1] * 128),
                     lambda p: p["layers"][0].update(codes=[0.5] * 16384),
                     lambda p: p["layers"][0].update(strength=float("nan")),
                     lambda p: p["layers"][0].update(enabled=1),
                     lambda p: p["layers"][0].update(mode="OTHER"),
                     lambda p: p.pop("compose"), lambda p: p.update(compose="ConditioningLayersLayer"),
                     lambda p: p.update(compose=["ConditioningLayersCompose"]), lambda p: p["layers"][0].pop("group"),
                     lambda p: p["layers"][0].update(group=None), lambda p: p["layers"][0].update(group=" A")]
        for mutate in mutations:
            payload = copy.deepcopy(base); mutate(payload)
            with self.assertRaises(ValueError):
                preview.preview_composition(payload)

    def test_route_transient_payload_errors_and_registration(self):
        handlers = {}
        routes = SimpleNamespace(post=lambda path: lambda handler: handlers.setdefault(path, handler))
        server = SimpleNamespace(PromptServer=SimpleNamespace(instance=SimpleNamespace(routes=routes)))
        web = SimpleNamespace(json_response=lambda data, status=200: (status, data))
        class Content:
            def __init__(self, data): self.data = data
            async def iter_chunked(self, size):
                for start in range(0, len(self.data), size): yield self.data[start:start + size]
        async def check():
            handler = handlers[preview.PREVIEW_PATH]
            payload = {"compose": LEGACY, "layers":[layer("a")], "selected": "a"}
            status, result = await handler(SimpleNamespace(content=Content(json.dumps(payload).encode())))
            self.assertEqual(status, 200); self.assertEqual(result, preview.preview_composition(payload))
            for data in (b"{", b"{}", b" " * (preview.MAX_REQUEST_BYTES + 1)):
                status, result = await handler(SimpleNamespace(content=Content(data)))
                self.assertEqual(status, 400); self.assertEqual(result["status"], "unavailable")
        with patch.dict(sys.modules, {"server": server, "aiohttp": SimpleNamespace(web=web)}), \
                patch.object(preview, "_REGISTERED", False):
            preview.register_preview_route(); preview.register_preview_route()
            self.assertEqual(len(handlers), 1)
            asyncio.run(check())


MODULE = json.dumps((ROOT / "web/js/composition_preview.js").as_uri())
GRAPH = r"""
const {createCompositionPreview,createPreviewQueue}=await import(MODULE);
const graph={nodes:[],links:{},getNodeById(k){return this.nodes.find(n=>String(n.id)===String(k));}};
let linkSequence=0,current=graph,requests=[];
const node=(id,type,inputs=[],widgets=[])=>{const n={id,type,mode:0,graph,inputs:inputs.map(name=>({name,link:null})),widgets};graph.nodes.push(n);return n;};
const connect=(source,target,name)=>{const slot=target.inputs.findIndex(i=>i.name===name);const id=++linkSequence;
 graph.links[id]={origin_id:source.id,origin_slot:0,target_id:target.id,target_slot:slot};target.inputs[slot].link=id;};
const values=(strength=1,mode='BLENDED',enabled=true)=>[{name:'strength',value:strength},{name:'mode',value:mode},{name:'enabled',value:enabled}];
const fields=[],layers=[],adds=[];
for(let i=0;i<6;i++){
 fields.push(node('p'+i,'ConditioningLayersPaintedField',[],[{type:'CONDITIONING_LAYERS_PAINTED_FIELD',value:'stored'+i}]));
 layers.push(node('l'+i,'ConditioningLayersLayer',['conditioning','mask'],values()));
 // Captured ComfyUI 0.34.6 / frontend 1.49.6 native literal-widget shape:
 // Inline fixture of the native ComfyUI 0.34.6 literal-widget representation.
 layers[i].inputs.push(...[['strength','FLOAT'],['mode','COMBO'],['enabled','BOOLEAN']]
   .map(([name,type])=>({name,type,link:null,widget:{name}})));
 connect(node('text'+i,'CLIPTextEncode'),layers[i],'conditioning');
 adds.push(node('a'+i,'ConditioningLayersAddLayer',['layer','layers']));
 connect(fields[i],layers[i],'mask');connect(layers[i],adds[i],'layer');if(i)connect(adds[i-1],adds[i],'layers');
}
const compose=node('c','ConditioningLayersCompose',['layers']);connect(adds[5],compose,'layers');
const edits=new Map([['p0',new Uint8Array(16384).fill(128)]]);
const service=createCompositionPreview({graph,currentGraph:()=>current,validateEdits:()=>{},
 decode:async text=>new Uint8Array(16384).fill(Number(text.slice(6))+1),
 request:async payload=>{requests.push(payload);return {status:'ready',bits:Array(16384).fill(0x3f000000)};}});
""".replace("MODULE", MODULE)


class FrontendTests(unittest.TestCase):
    def test_selected_context_keeps_validation_error_and_recovers_without_reselection(self):
        run_node(GRAPH + r"""
const valid=service.inspect('p0',edits,null),key=valid.key;
const other=node('c2','ConditioningLayersCompose',['layers']);connect(adds[0],other,'layers');
for(const [index,bad] of [[0,NaN],[1,'OTHER'],[2,undefined]]){
 const original=layers[5].widgets[index].value;layers[5].widgets[index].value=bad;
 const invalid=service.inspect('p0',edits,key);
 assert.equal(invalid.key,key);assert.match(invalid.error,/Layer #l5: invalid metadata/);
 assert.ok(invalid.choices.some(c=>c.key===key&&c.label==='Compose #c · Layer #l0'&&c.error===invalid.error));
 assert.notEqual(invalid.fingerprint,valid.fingerprint);
 // Another valid stack and unknown selection retain explicit selection semantics.
 assert.equal(service.inspect('p0',edits,JSON.stringify(['c2','l0'])).error,undefined);
 for(const selection of [null,'not-json',JSON.stringify(['missing','l0'])])
   assert.match(service.inspect('p0',edits,selection).error,/Select a Compose\/layer context/);
 layers[5].widgets[index].value=original;
 const recovered=service.inspect('p0',edits,key);
 assert.equal(recovered.error,undefined);assert.equal(recovered.key,key);assert.equal(recovered.choice.selected,'l0');
}
assert.equal(requests.length,0);
""")

    def test_invalid_transition_rejects_inflight_success_then_recovers(self):
        run_node(GRAPH + r"""
const jobs=[],queue=createPreviewQueue(s=>new Promise(resolve=>jobs.push({s,resolve})),()=>{},0);
const wait=()=>new Promise(r=>setTimeout(r,8));
const valid=service.inspect('p0',edits,null);queue.update(valid);await wait();
layers[0].widgets[0].value=undefined;
const invalid=service.inspect('p0',edits,valid.key);queue.update(invalid);
assert.equal(queue.state.status,'unavailable');assert.equal(queue.state.message,invalid.error);
jobs[0].resolve({status:'ready',obsolete:true});await wait();
assert.equal(queue.state.status,'unavailable');assert.equal(queue.state.message,invalid.error);
layers[0].widgets[0].value=1;queue.update(service.inspect('p0',edits,valid.key));await wait();
assert.equal(jobs.length,2);jobs[1].resolve({status:'ready',obsolete:false});await wait();
assert.equal(queue.state.status,'ready');assert.equal(queue.state.obsolete,false);queue.dispose();
""")

    def test_compact_status_prioritizes_weight_and_keeps_full_tooltip(self):
        run_node(EDITOR + r"""
controller.cancel();const {createPreviewQueue}=await import(MODULE);
let revision=0,previewError=null,result={status:'ready',bits:Array(16384).fill(0x3f2aaaab)};
host.createCompositionPreview=async()=>({createQueue:(calc,notify)=>createPreviewQueue(calc,notify,0),
 inspect:()=>({choices:[{key:'c',label:'Compose #8 · Layer #3'}],key:'c',fingerprint:String(revision),error:previewError}),
 calculate:async()=>result});
controller=open();dom.flush();press('Contribution');await until(()=>find('status').title.includes('0–100%'));
redraw();assert.match(find('status').textContent,/^66\.66667% contribution/);
assert.match(find('status').title,/prepared weight 0–100% · edits change raw field/);
assert.match(find('status').title,/66\.66667%/);
result={status:'ready',bits:Array(16384).fill(0x3eaaaaab)};revision++;redraw();
await until(()=>find('status').textContent.startsWith('33.33333% contribution'));
result={status:'conflict',cells:[0,1],pairs:[{layers:['3','6'],count:2}]};revision++;redraw();
await until(()=>find('status').textContent==='FIXED conflict · 2 cells · preview unavailable');
assert.match(find('status').title,/layers 3 \/ 6 share 2 cells/);
previewError='Layer #6: invalid metadata';revision++;redraw();
await until(()=>find('status').textContent==='Unavailable · Layer #6: invalid metadata');
assert.equal(find('status').title,'Preview unavailable · Layer #6: invalid metadata');
controller.cancel();
""".replace("MODULE", MODULE))

    def test_native_literal_widgets_resolve_two_layer_stack(self):
        run_node(GRAPH + r"""
connect(adds[1],compose,'layers');layers[1].widgets[0].value=0.5;
const full=new Uint8Array(16384).fill(255);edits.set('p0',full);edits.set('p1',full);
const s=service.inspect('p0',edits,null);assert.equal(s.error,undefined);
await service.calculate(s);
assert.deepEqual(requests[0].layers.map(l=>[l.id,l.strength,l.mode,l.enabled]),
 [['l0',1,'BLENDED',true],['l1',0.5,'BLENDED',true]]);
assert.ok(requests[0].layers.every(l=>l.codes.every(c=>c===255)));
// Disabled remains a literal boolean and changes participation, never a default.
layers[1].widgets[2].value=false;
const off=service.inspect('p0',edits,s.key);await service.calculate(off);
assert.equal(requests[1].layers[1].enabled,false);assert.equal(requests[1].layers[1].codes,null);
// Retain the previously supported widget-only representation.
layers[0].inputs=layers[0].inputs.filter(i=>!i.widget);
assert.equal(service.inspect('p0',edits,s.key).error,undefined);
""")

    def test_connected_native_metadata_never_uses_stale_literal(self):
        run_node(GRAPH + r"""
for(const name of ['strength','mode','enabled']){
 const socket=layers[0].inputs.find(i=>i.name===name);
 connect(node('dynamic-'+name,'PrimitiveNode'),layers[0],name);
 assert.match(service.inspect('p0',edits,null).error,new RegExp('dynamic '+name));
 socket.link=null;
 assert.equal(service.inspect('p0',edits,null).error,undefined);
 // Dangling links are also dynamic/unresolved, never permission to fall back.
 socket.link=99999;assert.ok(service.inspect('p0',edits,null).error);socket.link=null;
}
assert.equal(requests.length,0);
""")

    def test_native_literal_metadata_missing_invalid_or_ambiguous_fails_closed(self):
        run_node(GRAPH + r"""
for(const [index,name,bad] of [[0,'strength',[undefined,null,'1',NaN,Infinity,-1,1.01]],
 [1,'mode',[undefined,null,'OTHER',1]], [2,'enabled',[undefined,null,0,1,'false']]]){
 const layer=layers[0],widget=layer.widgets[index],socket=layer.inputs.find(i=>i.name===name),value=widget.value;
 for(const invalid of bad){widget.value=invalid;assert.match(service.inspect('p0',edits,null).error,/invalid metadata/);}
 widget.value=value;
 layer.widgets.splice(index,1);assert.ok(service.inspect('p0',edits,null).error);layer.widgets.splice(index,0,widget);
 layer.widgets.push({...widget});assert.ok(service.inspect('p0',edits,null).error);layer.widgets.pop();
 layer.inputs.push({...socket});assert.ok(service.inspect('p0',edits,null).error);layer.inputs.pop();
 const association=socket.widget;delete socket.widget;
 assert.match(service.inspect('p0',edits,null).error,/unresolved/);
 socket.widget={name:'wrong'};assert.match(service.inspect('p0',edits,null).error,/unresolved/);
 socket.widget=association;delete socket.link;assert.match(service.inspect('p0',edits,null).error,/unresolved/);
 socket.link=null;assert.equal(service.inspect('p0',edits,null).error,undefined);
}
assert.equal(requests.length,0);
""")

    def test_real_adapter_opt_in_transport_and_external_change_guard(self):
        source = (ROOT / 'web/js/painted_field_node.js').read_text(encoding='utf-8')
        source = source.replace('import {app} from "../../../scripts/app.js";', 'const app=globalThis.testApp;')
        source = source.replace('import("./field_editor/png_codec.js")', 'globalThis.loadEditorModule("codec")')
        source = source.replace('import("./field_editor/editor_ui.js")', 'globalThis.loadEditorModule("ui")')
        source = source.replace('import("./composition_preview.js")', f'import({MODULE})')
        source = source.replace('import("../../../scripts/api.js")', 'Promise.resolve({api:globalThis.previewApi})')
        encoded = 'data:text/javascript;base64,' + base64.b64encode(source.encode()).decode()
        run_node(ADAPTER.replace('ADAPTER_URL', json.dumps(encoded)) + r"""
let sent=null;globalThis.previewApi={fetchApi:async(path,options)=>{
 assert.equal(path,'/conditioning-layers/composition-preview');assert.equal(options.method,'POST');
 sent=JSON.parse(options.body);return {ok:true,json:async()=>({status:'ready',bits:Array(16384).fill(0x3f800000)})};}};
nodes[0].type='ConditioningLayersPaintedField';nodes[0].mode=0;
const addNode=(id,type,inputs=[],widgets=[])=>{const n={id,type,mode:0,graph,inputs:inputs.map(name=>({name,link:null})),widgets};graph.nodes.push(n);return n;};
graph.links={};let sequence=0;
const wire=(a,b,name)=>{const slot=b.inputs.findIndex(i=>i.name===name),id=++sequence;
 graph.links[id]={origin_id:a.id,origin_slot:0,target_id:b.id,target_slot:slot};b.inputs[slot].link=id;};
const text=addNode(10,'CLIPTextEncode');
const layer=addNode(11,'ConditioningLayersLayer',['conditioning','mask'],
 [{name:'strength',value:1},{name:'mode',value:'BLENDED'},{name:'enabled',value:true}]);
const addLayer=addNode(12,'ConditioningLayersAddLayer',['layer','layers']),compose=addNode(13,'ConditioningLayersCompose',['layers']);
wire(text,layer,'conditioning');wire(nodes[0],layer,'mask');wire(layer,addLayer,'layer');wire(addLayer,compose,'layers');
const service=await opened.host.createCompositionPreview();
const edits=new Map([['1',new Uint8Array(16384).fill(73)]]),s=service.inspect('1',edits,null);
await service.calculate(s);assert.equal(sent.layers[0].codes[0],73);assert.equal(nodes[0].widgets[0].value,'');
nodes[0].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(9));
assert.throws(()=>service.inspect('1',edits,s.key),/outside this editor/);
globalThis.previewApi.fetchApi=async()=>({ok:false,status:404,json:async()=>({})});
await assert.rejects(service.calculate(s),/unavailable.*404/);
controller.cancel();
""")

    def test_complete_stack_hidden_participants_and_unsaved_buffers(self):
        run_node(GRAPH + r"""
const s=service.inspect('p0',edits,null);assert.equal(s.choices.length,1);
await service.calculate(s);assert.equal(requests[0].layers.length,6);
assert.equal(requests[0].layers[0].codes[0],128);assert.equal(requests[0].layers[5].codes[0],6);
assert.equal(fields[0].widgets[0].value,'stored0');assert.equal(s.choice.selected,'l0');
const f=service.inspect('p0',edits,s.key).fingerprint;assert.equal(f,s.fingerprint);
layers[5].widgets[0].value=0;assert.notEqual(service.inspect('p0',edits,s.key).fingerprint,f);
layers[5].widgets[2].value=false;fields[5].widgets[0].value={bad:true};
const off=service.inspect('p0',edits,s.key);await service.calculate(off);assert.equal(requests[1].layers[5].codes,null);
""")

    def test_shared_field_keeps_distinct_layers_and_ambiguity_requires_selection(self):
        run_node(GRAPH + r"""
connect(fields[0],layers[1],'mask');
const s=service.inspect('p0',edits,null);assert.equal(s.choices.length,2);assert.ok(s.error);assert.equal(s.key,null);
const chosen=service.inspect('p0',edits,s.choices[1].key);await service.calculate(chosen);
assert.equal(requests[0].selected,'l1');assert.equal(requests[0].layers[0].codes[0],128);
assert.equal(requests[0].layers[1].codes[0],128);assert.notEqual(requests[0].layers[0].id,requests[0].layers[1].id);
const other=node('c2','ConditioningLayersCompose',['layers']);connect(adds[5],other,'layers');
assert.equal(service.inspect('p0',edits,null).choices.length,4);
""")

    def test_unsupported_shapes_and_metadata_fail_closed(self):
        run_node(GRAPH + r"""
const rejects=(change,restore)=>{change();assert.ok(service.inspect('p0',edits,null).error);restore();};
rejects(()=>fields[5].type='ConditioningLayersFieldBlur',()=>fields[5].type='ConditioningLayersPaintedField');
rejects(()=>layers[5].widgets[0].value=NaN,()=>layers[5].widgets[0].value=1);
rejects(()=>layers[5].inputs.push({name:'strength',link:null}),()=>layers[5].inputs.pop());
const conditioningLink=layers[5].inputs[0].link;
rejects(()=>layers[5].inputs[0].link=null,()=>layers[5].inputs[0].link=conditioningLink);
rejects(()=>adds[4].mode=4,()=>adds[4].mode=0);
const link=adds[4].inputs[1].link;
rejects(()=>adds[4].inputs[1].link=9999,()=>adds[4].inputs[1].link=link);
rejects(()=>connect(adds[5],adds[0],'layers'),()=>adds[0].inputs[1].link=null);
const layerLink=adds[1].inputs[0].link;
rejects(()=>connect(layers[0],adds[1],'layer'),()=>adds[1].inputs[0].link=layerLink);
current={};assert.throws(()=>service.inspect('p0',edits,null),/graph changed/);
assert.equal(requests.length,0);
""")

    def test_latest_snapshot_wins_no_visual_requests_and_disposal(self):
        run_node(r"""
const {createPreviewQueue}=await import(MODULE);
const jobs=[],notices=[];const queue=createPreviewQueue(s=>new Promise(resolve=>jobs.push({s,resolve})),()=>notices.push(1),0);
const wait=()=>new Promise(r=>setTimeout(r,8));
queue.update({fingerprint:'a'});await wait();assert.equal(jobs.length,1);
for(let i=0;i<10;i++)queue.update({fingerprint:'a'});assert.equal(jobs.length,1);
queue.update({fingerprint:'b'});jobs[0].resolve({status:'ready',value:'a'});await wait();
assert.equal(notices.length,0);assert.equal(jobs.length,2);
queue.update({fingerprint:'c'},true);assert.equal(queue.state.status,'stale');
jobs[1].resolve({status:'ready',value:'b'});await wait();assert.equal(notices.length,0);
queue.update({fingerprint:'c'});await wait();jobs[2].resolve({status:'ready',value:'c'});await wait();
assert.equal(queue.state.value,'c');assert.equal(notices.length,1);
queue.update({fingerprint:'d'});await wait();queue.dispose();jobs[3].resolve({status:'ready',value:'d'});await wait();
assert.equal(notices.length,1);
""".replace("MODULE", MODULE))

    def test_view_rendering_conflicts_and_no_authored_code_quantization(self):
        run_node(r"""
const dom=installDOM(),canvas=document.createElement('canvas');
const bits=Array(16384).fill(0x3eaaaaab),weights=view.drawContribution(canvas,{status:'ready',bits});
assert.equal(weights[0],Math.fround(1/3));assert.equal(bits[0],0x3eaaaaab);
view.drawContribution(canvas,{status:'conflict',cells:[0,3]});
assert.deepEqual([...canvas.pixels.slice(0,4)],[255,80,80,255]);
assert.deepEqual([...canvas.pixels.slice(12,16)],[255,255,255,255]);
assert.deepEqual([...canvas.pixels.slice(4,8)],[0,0,0,255]);
""")

    def test_editor_preview_is_ephemeral_and_preserves_editing(self):
        run_node(EDITOR + r"""
controller.cancel();
const {createPreviewQueue}=await import(MODULE);let reads=0,calculations=0;
const tokens=new WeakMap();let serial=0;
host.createCompositionPreview=async()=>({createQueue:(calc,notify)=>createPreviewQueue(calc,notify,0),
 inspect:(active,edits,selected)=>{reads++;const codes=edits.get(active);if(!tokens.has(codes))tokens.set(codes,++serial);
 const choice={key:'context',label:'Compose #C · Layer #L'};
 return {key:'context',choices:[choice],choice,fingerprint:active+':'+tokens.get(codes)};},
 calculate:async()=>{calculations++;return {status:'ready',bits:Array(16384).fill(0x3f000000),disabled:false};}});
controller=open();dom.flush();await add('2');const before=snapshot(controller.session);
assert.equal(reads,0);press('Contribution');await until(()=>find('status').title.includes('0–100%'));
assert.equal(snapshot(controller.session),before);assert.equal(calculations,1);
for(let i=0;i<5;i++)redraw();press('Fit');press('Heat View');
all().filter(e=>e.className==='field-show')[1].click();dom.flush();await settle();assert.equal(calculations,1);
press('Invert');await until(()=>calculations===2);press('Undo');await until(()=>calculations===3);
assert.equal(snapshot(controller.session).includes('contribution'),false);
press('Fields');assert.ok(overlays()[1].hidden); // Original hidden-overlay choice persists.
press('Redo');press('Undo');press('Contribution');await until(()=>calculations===4);
press('Done');await until(()=>document.body.children.length===0);
assert.equal(offers.length,1);for(const offered of offers[0])assert.equal('contribution' in offered.settings,false);
assert.equal(sources.get('1').codes[0],offers[0][0].codes[0]);
""".replace("MODULE", MODULE))

    def test_live_edits_pair_history_polling_and_cancel_dispose_preview(self):
        run_node(EDITOR + r"""
controller.cancel();const {createPreviewQueue}=await import(MODULE);
let calculations=0,metadata=1,inspections=0;const tokens=new WeakMap();let serial=0;
host.createCompositionPreview=async()=>({createQueue:(calc,notify)=>createPreviewQueue(calc,notify,0),
 inspect:(active,edits)=>{inspections++;const versions=[...edits].map(([key,codes])=>{
   if(!tokens.has(codes))tokens.set(codes,++serial);return [key,tokens.get(codes)];});
 const choice={key:'c',label:'Compose #C · Layer #L'};
 return {choices:[choice],key:'c',choice,fingerprint:JSON.stringify([active,versions,metadata])};},
 calculate:async()=>{calculations++;return {status:'ready',bits:Array(16384).fill(0x3f000000)};}});
controller=open();dom.flush();await add('2');
field('1').session.replace('Setup',new Uint8Array(16384).fill(20));
field('2').session.replace('Setup',new Uint8Array(16384).fill(180));
press('Contribution');await until(()=>find('status').title.includes('0–100%'));
const start=calculations;press('Transfer from Painted Field #2');
pointer('pointerdown',40,40);pointer('pointermove',50,50);
assert.ok(find('status').textContent.includes('stale'));assert.equal(calculations,start);
pointer('pointerup',50,50);await until(()=>calculations===start+1);
for(let i=0;i<16384;i++)assert.equal(field('1').session.codes[i]+field('2').session.codes[i],200);
press('Undo');await until(()=>calculations===start+2);press('Redo');await until(()=>calculations===start+3);
press('Balance with Painted Field #2');click(70,70);await until(()=>calculations===start+4);
for(let i=0;i<16384;i++)assert.equal(field('1').session.codes[i]+field('2').session.codes[i],200);
metadata=0;await until(()=>calculations===start+5,'idle metadata polling');
controller.cancel();assert.equal(offers.length,0);const stopped=inspections;
await new Promise(r=>setTimeout(r,550));dom.flush();assert.equal(inspections,stopped);
assert.equal(document.body.children.length,0);
""".replace("MODULE", MODULE))


if __name__ == "__main__":
    unittest.main()
