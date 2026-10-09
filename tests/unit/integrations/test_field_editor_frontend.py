"""Fenced inline Node E1 logic tests; not real-browser interaction evidence."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import unittest

from conditioning_layers.assets.field_png import decode_field_data_url, encode_field_png, PREFIX

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/unit/assets"))
from field_png_fixtures import CODES, fixtures

CORE = ROOT / "web/js/field_editor"
ADAPTER = ROOT / "web/js/painted_field_node.js"
DOM = Path(__file__).with_name("field_editor_fake_dom.js")


def run_node(body):
    source = f'''
import assert from 'node:assert/strict';
const engine = await import({json.dumps((CORE / 'engine.js').as_uri())});
const codec = await import({json.dumps((CORE / 'png_codec.js').as_uri())});
const {{FieldHistory}} = await import({json.dumps((CORE / 'history.js').as_uri())});
const {{createNumberControl}} = await import({json.dumps((CORE / 'number_control.js').as_uri())});
const ui = await import({json.dumps((CORE / 'editor_ui.js').as_uri())});
const {{installDOM, fire, descendants, settle}} = await import({json.dumps(DOM.as_uri())});
const brush = {{tool:'paint', size:1, influence:255, hardness:100, amount:100}};
const empty = () => new Uint8Array(16384);
{body}
'''
    result = subprocess.run(["node", "--input-type=module"], input=source, cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode: raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout or "null")


class FieldEditorFrontendTests(unittest.TestCase):
    def e2_script(self, body):
        return run_node(f'''
const view = await import({json.dumps((CORE / 'view.js').as_uri())});
const dom=installDOM();let result,cancelled=0;
const host={{getAdvancedExpanded:()=>false,setAdvancedExpanded:()=>{{}},getGroupExpanded:()=>false,
 setGroupExpanded:()=>{{}},confirmDiscard:()=>true}};
const initial=empty();initial[0]=173;initial[16383]=255;
const open=()=>ui.openInfluenceFieldEditor({{codes:initial,settings:{{...brush}},host,
 onDone:(codes,settings)=>{{result={{codes,settings}};}},onCancel:()=>cancelled++}});
let controller=open();dom.flush();
const all=()=>descendants(document.body),find=cls=>all().find(e=>e.className===cls);
const press=text=>all().find(e=>e.tagName==='BUTTON'&&e.textContent===text).click();
const input=label=>all().find(e=>e.attributes['aria-label']===label);
const type=(label,value)=>{{const e=input(label);fire(e,'pointerdown');fire(e,'pointerup');e.value=String(value);
 fire(window,'keydown',{{key:'Enter',target:e}});dom.flush();}};
const viewport=find('viewport'),canvas=all().find(e=>e.tagName==='CANVAS');
const pointer=(name,x,y,extra={{}})=>fire(viewport,name,{{clientX:8+x*4,clientY:8+y*4,...extra}});
const stroke=(x,y)=>{{pointer('pointerdown',x,y);pointer('pointerup',x,y);dom.flush();}};
const urls=[],revoked=[];
URL.createObjectURL=blob=>{{const url='blob:test-'+urls.length;urls.push({{url,blob}});return url;}};
URL.revokeObjectURL=url=>revoked.push(url);
const load=async()=>{{const picker=all().find(e=>e.accept==='image/*');picker.files=[new Blob(['reference'])];
 fire(picker,'change');await settle();dom.flush();}};
{body}
''')

    def test_e2_heat_mapping_monotonic_endpoints_and_display_only(self):
        self.e2_script('''
assert.deepEqual(view.heatColor(0),[0,0,0]);assert.deepEqual(view.heatColor(85),[255,0,0]);
assert.deepEqual(view.heatColor(128),[255,129,0]);assert.deepEqual(view.heatColor(170),[255,255,0]);
assert.deepEqual(view.heatColor(255),[255,255,255]);
for(let code=1;code<256;code++) {
 const a=view.heatColor(code-1),b=view.heatColor(code);
 assert.ok(b.every((v,i)=>v>=a[i]));assert.ok(b.some((v,i)=>v>a[i]));
}
const before=controller.session.codes.slice();press('Heat View');dom.flush();
assert.deepEqual([...canvas.pixels.slice(0,3)],view.heatColor(173));
assert.deepEqual(controller.session.codes,before);assert.equal(controller.session.history.undoEntries.length,0);
press('Heat View');dom.flush();assert.deepEqual([...canvas.pixels.slice(0,3)],[173,173,173]);
''')

    def test_e2_reference_picker_drop_remove_and_session_disposal(self):
        self.e2_script('''
const settings={...controller.session.settings};await load();
const reference=find('reference');assert.equal(reference.hidden,false);assert.equal(reference.src,'blob:test-0');
assert.equal(reference.style.transform,canvas.style.transform);assert.equal(reference.style.opacity,'0.5');
assert.equal(canvas.style.opacity,'0.5');assert.deepEqual(controller.session.codes,initial);
const event=fire(find('reference-drop'),'drop',{dataTransfer:{files:[new Blob(['second'])]}});
await settle();dom.flush();assert.ok(event.stopped&&event.prevented);assert.equal(reference.src,'blob:test-1');
assert.ok(revoked.includes('blob:test-0'));assert.equal(controller.session.history.undoEntries.length,0);
assert.deepEqual(controller.session.settings,settings);
press('Remove Reference');dom.flush();assert.equal(reference.hidden,true);assert.equal(canvas.style.opacity,'1');
assert.ok(revoked.includes('blob:test-1'));
await load();controller.cancel();assert.ok(revoked.includes('blob:test-2'));assert.equal(reference.src,undefined);
controller=open();dom.flush();assert.equal(find('reference').hidden,true);
assert.equal(input('Reference Opacity (%)').value,'50');assert.equal(controller.session.history.undoEntries.length,0);
''')

    def test_e2_reference_decode_failure_races_and_close_in_flight(self):
        self.e2_script('''
await load();const original=find('reference').src;
const pending=[];dom.Element.prototype.decode=function(){return new Promise((resolve,reject)=>pending.push({resolve,reject}));};
await load();pending[0].reject(Error('bad image'));await settle();dom.flush();
assert.equal(find('reference').src,original);assert.match(find('error').textContent,/bad image/);
assert.ok(revoked.includes('blob:test-1'));
await load();await load();pending[2].resolve();await settle();pending[1].resolve();await settle();dom.flush();
assert.equal(find('reference').src,'blob:test-3');assert.ok(revoked.includes('blob:test-2'));
await load();controller.cancel();assert.ok(revoked.includes('blob:test-4'));
pending[3].resolve();await settle();assert.equal(document.body.children.length,0);
assert.deepEqual(controller.session.codes,initial);
''')

    def test_e2_reference_opacity_drag_type_clamp_and_reset(self):
        self.e2_script('''
await load();const opacity=input('Reference Opacity (%)');assert.equal(opacity.type,'text');
fire(opacity,'pointerdown',{clientX:100});fire(opacity,'pointermove',{clientX:80});fire(opacity,'pointerup',{clientX:80});dom.flush();
assert.equal(opacity.value,'30');assert.equal(find('reference').style.opacity,'0.3');
type('Reference Opacity (%)',73);assert.equal(find('reference').style.opacity,'0.73');
type('Reference Opacity (%)',999);assert.equal(opacity.value,'100');
type('Reference Opacity (%)',-1);assert.equal(opacity.value,'0');
press('Reset View');dom.flush();assert.equal(opacity.value,'50');assert.equal(find('reference').hidden,true);
assert.equal(controller.session.history.undoEntries.length,0);assert.deepEqual(controller.session.codes,initial);
''')

    def test_e2_grid_native_boundaries_threshold_and_shared_transform(self):
        self.e2_script('''
const path=view.gridPath();assert.equal((path.match(/M/g)||[]).length,258);
for(let i=0;i<=128;i++){assert.ok(path.includes(`M${i} 0V128`));assert.ok(path.includes(`M0 ${i}H128`));}
assert.equal(view.gridVisible(true,7.999),false);assert.equal(view.gridVisible(true,8),true);
assert.equal(view.gridVisible(false,64),false);
const grid=find('cell-grid');assert.equal(Number(grid.children[0].attributes['stroke-width'])*4,1);
assert.equal(grid.style.display,'none');press('Grid (at ≥8 px/cell)');dom.flush();assert.equal(grid.style.display,'none');
await load();for(let i=0;i<4;i++)fire(viewport,'wheel',{clientX:72,clientY:72,deltaY:-1});dom.flush();
assert.equal(grid.style.display,'');
assert.ok(Math.abs(Number(grid.children[0].attributes['stroke-width'])*4*1.2*1.2*1.2*1.2-1)<1e-12);
const aligned=()=>{assert.equal(grid.style.transform,canvas.style.transform);assert.equal(find('reference').style.transform,canvas.style.transform);};
aligned();fire(viewport,'pointerdown',{button:1,clientX:20,clientY:20});
fire(viewport,'pointermove',{clientX:111,clientY:87});fire(viewport,'pointerup',{button:1});dom.flush();aligned();
fire(window,'resize');dom.flush();aligned();assert.equal(grid.style.display,'none');
assert.deepEqual(controller.session.codes,initial);assert.equal(controller.session.history.undoEntries.length,0);
''')

    def test_e2_compare_hold_release_interrupts_and_exact_restoration(self):
        self.e2_script('''
await load();type('Reference Opacity (%)',73);press('Heat View');dom.flush();
const compare=all().find(e=>e.textContent==='Hold to Compare');const pixels=canvas.pixels.slice();
for(const release of ['pointerup','pointercancel','lostpointercapture','blur']) {
 fire(compare,'pointerdown');dom.flush();assert.equal(canvas.style.opacity,'0');
 assert.equal(find('reference').style.opacity,'0.73');fire(compare,release);dom.flush();
 assert.equal(canvas.style.opacity,'0.5');assert.deepEqual(canvas.pixels,pixels);
}
fire(compare,'pointerdown');fire(window,'blur');dom.flush();assert.equal(canvas.style.opacity,'0.5');
for(const key of [' ','Enter']) {
 const e=fire(window,'keydown',{key,target:compare});dom.flush();assert.ok(e.stopped&&e.prevented);
 assert.equal(canvas.style.opacity,'0');fire(window,'keyup',{key,target:viewport});dom.flush();
 assert.equal(canvas.style.opacity,'0.5');
}
assert.deepEqual(controller.session.codes,initial);assert.equal(controller.session.history.undoEntries.length,0);
''')

    def test_e2_cursor_boundary_cells_zoom_pan_and_high_zoom_highlight(self):
        self.e2_script(r'''
for(const [p,want] of [[{x:0,y:0},[0,0,173]],[{x:127.999,y:127.999},[127,127,255]]]) {
 const r=view.cellReadout(initial,p);assert.deepEqual([r.x,r.y,r.code],want);
 assert.equal(r.percent,r.code*100/255);
}
for(const p of [{x:-.001,y:0},{x:128,y:0},{x:0,y:128}])assert.equal(view.cellReadout(initial,p),null);
assert.deepEqual(view.fieldPosition(132,251,{left:20,top:30},8,-12,17),{x:15.5,y:25.5});
pointer('pointermove',.5,.5);dom.flush();assert.match(find('status').textContent,/x 0 y 0.*173 \(67.8%\)/);
assert.equal(find('target-cell').hidden,true);
for(let i=0;i<4;i++)fire(viewport,'wheel',{clientX:10,clientY:10,deltaY:-1});dom.flush();
assert.equal(find('target-cell').hidden,false);
const transform=canvas.style.transform.match(/translate\(([-\d.]+)px,([-\d.]+)px\) scale\(([-\d.]+)\)/).slice(1).map(Number);
assert.equal(find('target-cell').style.left,`${transform[0]}px`);
assert.equal(find('target-cell').style.width,`${transform[2]}px`);
fire(viewport,'pointerdown',{button:1,clientX:100,clientY:100});
fire(viewport,'pointermove',{clientX:125,clientY:135});fire(viewport,'pointerup',{button:1});dom.flush();
const [px,py,z]=canvas.style.transform.match(/translate\(([-\d.]+)px,([-\d.]+)px\) scale\(([-\d.]+)\)/).slice(1).map(Number);
fire(viewport,'pointermove',{clientX:px+127.5*z,clientY:py+127.5*z});dom.flush();
assert.match(find('status').textContent,/x 127 y 127.*255 \(100.0%\)/);
assert.equal(find('target-cell').style.left,`${px+127*z}px`);
fire(viewport,'pointerdown',{clientX:px+127.5*z,clientY:py+127.5*z,altKey:true});dom.flush();
assert.equal(controller.session.settings.influence,255);assert.equal(controller.session.history.undoEntries.length,0);
''')

    def test_e2_eyedropper_exact_codes_both_units_without_paint(self):
        self.e2_script('''
for(const unit of ['percent','code']) {
 if(unit==='code')press('% ⇄ 0–255');dom.flush();
 for(const [x,y,code] of [[.5,.5,173],[127.5,127.5,255],[50.5,60.5,0]]) {
  pointer('pointerdown',x,y,{altKey:true,shiftKey:true});pointer('pointerup',x,y);dom.flush();
  assert.equal(controller.session.settings.influence,code);
  assert.equal(input(unit==='percent'?'Influence (%)':'Influence (0–255)').value,
    String(unit==='percent'?Math.round(code*1000/255)/10:code));
 }
 pointer('pointerdown',128,128,{altKey:true});dom.flush();assert.equal(controller.session.settings.influence,0);
}
assert.deepEqual(controller.session.codes,initial);assert.equal(controller.session.history.undoEntries.length,0);
''')

    def test_e2_shift_line_matches_existing_engine_all_brush_controls_one_history(self):
        self.e2_script('''
for(const tool of ['paint','erase'])for(const size of [1,16])for(const hardness of [0,37,100])for(const amount of [29,100]) {
 controller.cancel();controller=open();dom.flush();
 const vp=find('viewport');const p=(name,x,y,extra={})=>fire(vp,name,{clientX:8+x*4,clientY:8+y*4,...extra});
 const s=controller.session;Object.assign(s.settings,{tool,size,hardness,amount,influence:173});
 s.codes.fill(tool==='erase'?255:12);
 p('pointerdown',5.125,7.25);p('pointerup',5.125,7.25);dom.flush();
 const before=s.codes.slice(),count=s.history.undoEntries.length;
 const direct=new engine.Stroke(before,128,128,s.settings,5.125,7.25);direct.add(105.125,57.25);
 p('pointerdown',105.125,57.25,{shiftKey:true});
 // Moving after the click cannot append a curved tail or another history entry.
 p('pointermove',30,99);p('pointerup',30,99);dom.flush();
 assert.deepEqual(s.codes,direct.result());assert.equal(s.history.undoEntries.length,count+1);
 s.undo();assert.deepEqual(s.codes,before);s.redo();assert.deepEqual(s.codes,direct.result());
}
''')

    def test_e2_line_anchor_reset_and_aborted_stroke_preserves_prior_anchor(self):
        self.e2_script('''
stroke(10.5,10.5);const before=controller.session.codes.slice();
pointer('pointerdown',30,80);fire(viewport,'pointercancel');dom.flush();
const direct=new engine.Stroke(before,128,128,controller.session.settings,10.5,10.5);direct.add(30.5,10.5);
pointer('pointerdown',30.5,10.5,{shiftKey:true});dom.flush();assert.deepEqual(controller.session.codes,direct.result());
for(const action of ['Undo','Redo','Clear','Fill with Influence','Invert','Erase','Paint']) {
 stroke(10.5,10.5);press(action);dom.flush();
 const s=controller.session,expected=new engine.Stroke(s.codes,128,128,s.settings,90.5,90.5).result();
 pointer('pointerdown',90.5,90.5,{shiftKey:true});pointer('pointerup',90.5,90.5);dom.flush();
 assert.deepEqual(s.codes,expected,action);
}
''')

    def test_e2_statistics_empty_binary_grayscale_operations_stroke_history_import(self):
        self.e2_script('''
assert.deepEqual(view.fieldStatistics(empty()),{total:16384,nonzero:0,zero:16384,binary:true,min:0,max:0,mean:0,distinct:1});
const binary=empty();binary[10]=255;assert.equal(view.fieldStatistics(binary).binary,true);
assert.equal(view.fieldStatistics(binary).mean,255/16384);
const check=()=>{dom.flush();const stats=view.fieldStatistics(controller.session.codes),text=find('status').textContent;
 for(const fragment of [`${stats.total} cells`,`${stats.nonzero} nonzero`,`${stats.zero} zero`,
 `binary ${stats.binary?'yes':'no'}`,`min ${stats.min}`,`max ${stats.max}`,`mean ${stats.mean.toFixed(2)}`])assert.ok(text.includes(fragment),fragment);};
check();press('Clear');check();controller.session.settings.influence=173;press('Fill with Influence');check();
assert.equal(view.fieldStatistics(controller.session.codes).mean,173);press('Invert');check();
assert.equal(view.fieldStatistics(controller.session.codes).mean,82);stroke(40.5,40.5);check();
press('Undo');check();press('Redo');check();
const bytes=await codec.encodeFieldPng(binary),picker=all().find(e=>e.accept==='.png');
picker.files=[{size:bytes.length,arrayBuffer:async()=>bytes.buffer}];fire(picker,'change');
for(let i=0;i<100&&controller.session.codes[10]!==255;i++)await new Promise(r=>setTimeout(r,1));
check();assert.deepEqual(controller.session.codes,binary);
''')

    def test_e2_reference_heat_grid_export_and_done_pass_only_codes_and_brush_settings(self):
        self.e2_script('''
await load();press('Heat View');press('Grid (at ≥8 px/cell)');type('Reference Opacity (%)',73);
press('Export PNG');for(let i=0;i<100&&urls.length<2;i++)await new Promise(r=>setTimeout(r,1));
assert.deepEqual(await codec.decodeFieldPng(new Uint8Array(await urls[1].blob.arrayBuffer())),initial);
press('Done');await settle();assert.deepEqual(result.codes,initial);
assert.deepEqual(result.settings,{...brush,influenceUnit:'percent'});
assert.equal(controller.session.history.undoEntries.length,0);assert.ok(revoked.includes('blob:test-0'));
''')

    def test_e2_actual_editor_adapter_view_changes_never_write_widget_or_graph_history(self):
        self.adapter_script('''
node.properties.fieldEditor=ui.editorSettings();const settings=JSON.stringify(node.properties);
realEditor=true;await launch();dom.flush();
URL.createObjectURL=()=> 'blob:reference';URL.revokeObjectURL=()=>{};
let all=()=>descendants(document.body),picker=all().find(e=>e.accept==='image/*');
picker.files=[new Blob(['reference'])];fire(picker,'change');await settle();dom.flush();
for(const label of ['Heat View','Grid (at ≥8 px/cell)'])all().find(e=>e.textContent===label).click();
dom.flush();assert.equal(widget.value,'');assert.equal(writes,0);assert.equal(JSON.stringify(node.properties),settings);
all().find(e=>e.textContent==='Done').click();await settle();
assert.equal(writes,0);assert.equal(before,0);assert.equal(after,0);assert.equal(JSON.stringify(node.properties),settings);
await launch();dom.flush();assert.equal(descendants(document.body).find(e=>e.className==='reference').hidden,true);
controller.cancel();assert.equal(writes,0);assert.equal(JSON.stringify(node.properties),settings);
''')

    def test_e3_restore_baseline_is_the_current_widget_value_on_each_open(self):
        self.adapter_script('''
realEditor=true;
const first=Uint8Array.from({length:16384},(_,i)=>(i*5)%256);
widget.value=await codec.encodeFieldDataUrl(first);resetObservers();await launch();dom.flush();
assert.deepEqual(controller.session.initial,first);
const whole=s=>({...s,tool:'restore',shape:'square',size:128});
// After painting, Restore returns covered cells to this session's opening field.
controller.session.settings.influence=9;controller.session.operation('fill');
let back=new engine.Stroke(controller.session.codes,128,128,whole(controller.session.settings),64,64,controller.session.initial);
assert.deepEqual(back.result(),first);assert.deepEqual(controller.session.initial,first);
// Done commits another field (Restore stores as Paint); the next open restores toward it instead.
const second=engine.fieldOperation(first,'invert');controller.session.settings.tool='restore';
await opened.onDone(second,ui.editorSettings(controller.session.settings));controller.cancel();
assert.equal(writes,1);assert.equal(node.properties.fieldEditor.tool,'paint');
await launch();dom.flush();assert.deepEqual(controller.session.initial,second);
back=new engine.Stroke(new Uint8Array(16384),128,128,whole(controller.session.settings),64,64,controller.session.initial);
assert.deepEqual(back.result(),second);controller.cancel();assert.equal(writes,1);
''')

    def test_shared_reader_fixtures_and_bidirectional_code_agreement(self):
        cases = fixtures()
        cases.append({"name": "python-writer", "value": PREFIX + base64.b64encode(encode_field_png(CODES)).decode(),
                      "codes": list(CODES)})
        result = run_node(f'''
const fixtures = {json.dumps(cases)};
for (const test of fixtures) {{
  if (test.codes === null) await assert.rejects(() => codec.decodeFieldDataUrl(test.value), test.name);
  else assert.deepEqual([...await codec.decodeFieldDataUrl(test.value)], test.codes, test.name);
}}
const codes = Uint8Array.from({json.dumps(list(CODES))});
const encoded = await codec.encodeFieldDataUrl(codes);
assert.equal(encoded, await codec.encodeFieldDataUrl(codes));
assert.deepEqual(await codec.decodeFieldDataUrl(encoded), codes);
assert.equal(await codec.encodeFieldDataUrl(empty()), '');
console.log(JSON.stringify(encoded));
''')
        self.assertEqual(decode_field_data_url(result), CODES)

    def test_hard_disk_counts_and_stroke_arithmetic(self):
        run_node('''
for (const [index, count] of [1,4,9,12,21,32].entries()) {
 const s = new engine.Stroke(empty(),128,128,{...brush,size:index+1},64.5,64.5);
 assert.equal(s.result().filter(v=>v).length,count);
}
const stamp = (codes, options={}) => new engine.Stroke(codes,128,128,{...brush,...options},64.5,64.5).result();
const i = 64*128+64;
let codes=stamp(empty(),{amount:50}); assert.equal(codes[i],128);
codes=stamp(codes,{amount:50}); assert.equal(codes[i],192);
assert.equal(stamp(new Uint8Array(16384).fill(255),{tool:'erase',amount:50})[i],127);
assert.equal(stamp(empty(),{influence:50,amount:29})[i],15);
for(let target=1;target<=255;target++) for(let amount=1;amount<=100;amount++) {
 const s=new engine.Stroke(new Uint8Array(1),1,1,{...brush,influence:target,amount},.5,.5);
 assert.equal(s.result()[0],Math.floor((target*amount+50)/100));
}
assert.deepEqual(stamp(stamp(empty())),stamp(empty()));
const s=new engine.Stroke(empty(),128,128,{...brush,amount:50,size:8},20,20);
for(const [x,y] of [[70,20],[20,20],[70,20]]) s.add(x,y);
assert.equal(Math.max(...s.result()),128);
assert.deepEqual(engine.fieldOperation(codes,'invert'),codes.map(v=>255-v));
assert.deepEqual(engine.fieldOperation(codes,'clear'),empty());
assert.ok(engine.fieldOperation(codes,'fill',173).every(v=>v===173));
''')

    def test_exact_collinear_subdivision_duplicates_frames_and_run_remainder(self):
        run_node('''
for(const hardness of [0,37,99,100]) for(const size of [1,2,9,16]) {
 const start=[5.125,7.25], end=[105.125,57.25];
 const direct=new engine.Stroke(empty(),128,128,{...brush,size,hardness,amount:73},...start);
 const split=new engine.Stroke(empty(),128,128,{...brush,size,hardness,amount:73},...start);
 direct.add(...end);
 for(let k=1;k<=50;k++) {split.add(start[0]+2*k,start[1]+k);split.result();split.add(start[0]+2*k,start[1]+k);}
 assert.deepEqual(split.coverage,direct.coverage);
 assert.deepEqual(split.result(),direct.result());
 // Continue through turns and reversals, retaining distance across runs.
 for(const p of [[110,70],[60,80],[10,10]]) {direct.add(...p);split.add(...p);}
 assert.deepEqual(split.coverage,direct.coverage);
 assert.deepEqual(split.result(),direct.result());
}
// Different geometry need not match.
const a=new engine.Stroke(empty(),128,128,brush,2,2), b=new engine.Stroke(empty(),128,128,brush,2,2);
a.add(90,90); b.add(90,2);b.add(90,90); assert.notDeepEqual(a.result(),b.result());
''')

    def test_size_one_sparse_paths_are_one_eight_connected_set(self):
        run_node('''
for(const path of [[[1.1,1.1],[126.9,126.9]],[[2.25,70.75],[125.75,4.25],[17.25,125.25]]]) {
 const s=new engine.Stroke(empty(),128,128,brush,...path[0]);
 for(const p of path.slice(1))s.add(...p);
 const codes=s.result(), first=Math.floor(path[0][1])*128+Math.floor(path[0][0]);
 assert.equal(codes[first],255);
 const seen=new Set([first]), queue=[first];
 for(let at=0;at<queue.length;at++) {
  const i=queue[at], x=i%128,y=Math.floor(i/128);
  for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++) {
   const nx=x+dx,ny=y+dy,j=ny*128+nx;
   if(nx>=0&&nx<128&&ny>=0&&ny<128&&codes[j]&&!seen.has(j)){seen.add(j);queue.push(j);}
  }
 }
 assert.equal(seen.size,codes.filter(v=>v).length);
 const end=path.at(-1); assert.ok([...seen].some(i=>Math.abs(i%128-Math.floor(end[0]))<=1&&Math.abs(Math.floor(i/128)-Math.floor(end[1]))<=1));
}
''')

    def test_history_cap_redo_new_edits_and_session_setting_isolation(self):
        run_node('''
const settings={size:32,amount:40,advanced:true};
const s=ui.createEditorSession(empty(),settings); s.settings.size=12;
assert.equal(settings.size,32);assert.equal(s.settings.advanced,undefined);
for(let i=1;i<=110;i++)s.replace('fill',new Uint8Array(16384).fill(i));
assert.equal(s.history.undoEntries.length,100);
for(let i=0;i<100;i++)s.undo();assert.equal(s.codes[0],10);
s.redo();assert.equal(s.codes[0],11);s.operation('invert');assert.equal(s.codes[0],244);
assert.equal(s.history.redoEntries.length,0);s.undo();assert.equal(s.codes[0],11);
const h=new FieldHistory(); const a=empty(),b=empty();b[0]=2;h.record('stroke',a,b);a[0]=9;b[0]=9;
assert.equal(h.undo()[0],0);assert.equal(h.redo()[0],2);
''')

    def test_every_numeric_control_supports_drag_and_exact_type_in_same_element(self):
        run_node('''
installDOM();
for(const [label,min,max,value,integer] of [['Size',1,128,16,true],['Influence code',0,255,255,true],
 ['Influence percent',0,100,100,false],['Hardness',0,100,100,true],['Amount',1,100,100,true]]) {
 let current=value;
 const c=createNumberControl({label,min,max,value,integer,step:integer?1:.1,onChange:v=>current=v});
 const input=c.element;assert.equal(input.type,'text');
 fire(input,'pointerdown',{clientX:100});fire(input,'pointermove',{clientX:80});fire(input,'pointerup',{clientX:80});
 assert.ok(current<value);assert.equal(input.readOnly,true);
 fire(input,'pointerdown');fire(input,'pointerup');assert.equal(input.readOnly,false);
 input.value=label==='Influence code'?'173':label==='Influence percent'?'67.8':'37';fire(input,'keydown',{key:'Enter'});
 assert.equal(current,label==='Influence code'?173:label==='Influence percent'?67.8:37);
 fire(input,'pointerdown');fire(input,'pointerup');input.value='12';fire(input,'keydown',{key:'Escape'});
 assert.equal(c.value,current);
 fire(input,'pointerdown');fire(input,'pointerup');input.value='9999';fire(input,'keydown',{key:'Enter'});assert.equal(current,max);
 fire(input,'pointerdown');fire(input,'pointerup');input.value='NaN';fire(input,'keydown',{key:'Enter'});assert.equal(current,max);
}
for(let code=0;code<256;code++)assert.equal(engine.percentToCode(Number((code*100/255).toFixed(1))),code);
assert.equal(engine.percentToCode(67.8),173);
''')

    def adapter_script(self, body):
        source = ADAPTER.read_text(encoding="utf-8")
        source = source.replace('import {app} from "../../../scripts/app.js";', 'const app = globalThis.testApp;')
        source = source.replace('import("./field_editor/png_codec.js")', 'globalThis.loadEditorModule("codec")')
        source = source.replace('import("./field_editor/editor_ui.js")', 'globalThis.loadEditorModule("ui")')
        encoded = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        return run_node(f'''
const dom=installDOM(); let extension, loads=0, fail=false, opened, calls=0, writes=0, before=0,after=0,dirty=0;
let realEditor=false, controller;
const loadedModules=[];
let testCodec=codec;
const events=[], commits=[];
globalThis.testApp={{registerExtension:e=>extension=e,ui:{{settings:{{getSettingValue:()=>false,setSettingValue:()=>{{}}}}}}}};
globalThis.loadEditorModule=async name=>{{loads++;loadedModules.push(name);if(fail)throw Error('offline core failure');
 return name==='codec'?testCodec:{{openInfluenceFieldEditor:options=>{{opened=options;
 if(realEditor) controller=ui.openInfluenceFieldEditor(options);}}}};}};
await import({json.dumps(encoded)});
assert.equal(loads,0);assert.equal(extension.settings[0].defaultValue,false);
let options,container;
const graph={{getNodeById:id=>id===activeNode?.id?activeNode:null,
 beforeChange:()=>assert.fail('legacy graph notification'),afterChange:()=>assert.fail('legacy graph notification')}};
const node={{id:1,properties:{{fieldEditor:{{size:16,amount:100}}}},graph,
setDirtyCanvas(){{dirty++;}},addDOMWidget(name,type,element,opts){{options=opts;container=element;
 const widget={{name,type,callback:v=>{{calls++;events.push(['callback',v]);}}}};
 // Match BaseDOMWidgetImpl.value in frontend 1.49.6 and 1.52.7, including its callback.
 Object.defineProperty(widget,'value',{{get:opts.getValue,set:v=>{{writes++;events.push(['write',v]);opts.setValue(v);widget.callback?.(widget.value);}}}});
 this.widgets=[widget];return widget;}}}};
let activeNode=node;
const {{widget}}=extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(node,'field',['STRING',{{default:''}}]);
assert.equal(loads,0);
const snapshot=()=>JSON.parse(JSON.stringify({{value:activeNode.widgets[0].value,properties:activeNode.properties}}));
let pending;
const canvas=globalThis.testApp.canvas={{graph,
 emitBeforeChange(){{assert.equal(this,canvas);assert.equal(pending,undefined);before++;events.push(['before',widget.value]);pending=snapshot();}},
 emitAfterChange(){{assert.equal(this,canvas);assert.ok(pending);after++;events.push(['after',widget.value]);commits.push({{before:pending,after:snapshot()}});pending=undefined;}}
}};
// Snapshot replay tests adapter serialization/setter restoration only, not ComfyUI's undo stack.
const restore=state=>{{node.properties=structuredClone(state.properties);widget.value=state.value;}};
const resetObservers=()=>{{calls=writes=before=after=dirty=0;events.length=commits.length=0;}};
assert.equal(options.socketless,true);
const launch=async()=>{{await extension.getNodeMenuItems(node)[0].callback();}};
// Model a restored node/widget while the visible launcher still belongs to the old DOM.
const replaceActive=value=>{{
 const previous=activeNode;
 activeNode={{...node,graph,properties:{{fieldEditor:{{size:23,amount:100}}}}}};
 const restored=extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(activeNode,'field',['STRING',{{default:''}}]).widget;
 restored.value=value;previous.graph=null;return restored;
}};
{body}
''')

    def test_adapter_reopen_current_widget_exact_codes_and_fresh_history(self):
        self.adapter_script('''
realEditor=true;
const painted=new engine.Stroke(empty(),128,128,{...brush,size:16},64,64).result();
assert.equal(painted.filter(v=>v).length,208);
const encoded=await codec.encodeFieldDataUrl(painted);
const prior=[];
for(const value of ['',encoded,'',encoded]) {
 widget.value=value;resetObservers();await launch();dom.flush();
 const session=controller.session,expected=value?painted:empty();
 assert.deepEqual(opened.codes,expected);assert.deepEqual(session.codes,expected);
 assert.equal(session.changed(),false);
 assert.deepEqual(session.history.undoEntries,[]);assert.deepEqual(session.history.redoEntries,[]);
 for(const old of prior) {
  assert.notEqual(session.codes.buffer,old.codes.buffer);assert.notEqual(session.history,old.history);
 }
 session.undo();session.redo();assert.deepEqual(session.codes,expected);
 session.operation('invert');session.operation('clear');session.undo();
 assert.equal(session.history.undoEntries.length,1);assert.equal(session.history.redoEntries.length,1);
 session.settings.size=37;prior.push(session);controller.cancel();
 assert.equal(widget.value,value);assert.equal(node.properties.fieldEditor.size,16);
 assert.deepEqual(events,[]);assert.equal(document.body.children.length,0);
}
''')

    def test_adapter_visible_old_launcher_reads_restored_node_and_done_baseline(self):
        self.adapter_script('''
realEditor=true;
const {createHash}=await import('node:crypto');
const hash=codes=>createHash('sha256').update(codes).digest('hex');
const painted=new engine.Stroke(empty(),128,128,{...brush,size:16},64,64).result();
const other=Uint8Array.from({length:16384},(_,i)=>i%256);
const encoded=await codec.encodeFieldDataUrl(painted);
const otherEncoded=await codec.encodeFieldDataUrl(other);
const visibleButton=descendants(container).find(e=>e.tagName==='BUTTON');
await launch();controller.session.replace('paint',painted);
await opened.onDone(controller.session.codes,controller.session.settings);controller.cancel();
assert.equal(widget.value,encoded);
// Undo, redo, then a nonempty-to-nonempty workflow/programmatic restoration.
for(const [value,expected] of [['',empty()],[encoded,painted],[otherEncoded,other]]) {
 const current=replaceActive(value);resetObservers();
 const previousOpen=opened;visibleButton.click();
 for(let i=0;i<100&&opened===previousOpen;i++) await new Promise(r=>setTimeout(r,1));
 assert.notEqual(opened,previousOpen);dom.flush();
 const session=controller.session;
 assert.deepEqual(session.codes,expected);assert.equal(hash(session.codes),hash(expected));
 const display=descendants(document.body).find(e=>e.tagName==='CANVAS');
 assert.equal(hash(Uint8Array.from({length:16384},(_,i)=>display.pixels[i*4])),hash(expected));
 assert.equal(session.settings.size,23);assert.equal(session.changed(),false);
 assert.deepEqual(session.history.undoEntries,[]);assert.deepEqual(session.history.redoEntries,[]);
 session.undo();session.redo();assert.deepEqual(session.codes,expected);
 // Settings-only Done compares against the restored starting field and never rewrites it.
 await opened.onDone(session.codes,{...session.settings,size:29});controller.cancel();
 assert.equal(current.value,value);assert.equal(activeNode.properties.fieldEditor.size,29);
 assert.equal(writes,0);assert.equal(before,0);assert.equal(after,0);
 // Cancel edits must leave the restored executable value and saved settings alone.
 await launch();controller.session.operation('invert');controller.session.settings.size=37;
 controller.cancel();assert.equal(current.value,value);assert.equal(activeNode.properties.fieldEditor.size,29);
 // Changed Done writes the current widget exactly once using the retained lifecycle.
 await launch();const changed=engine.fieldOperation(expected,'invert');
 controller.session.replace('invert',changed);
 resetObservers();await opened.onDone(controller.session.codes,controller.session.settings);controller.cancel();
 assert.deepEqual(await codec.decodeFieldDataUrl(current.value),changed);
 assert.equal(hash(await codec.decodeFieldDataUrl(current.value)),hash(changed));
 assert.deepEqual(events.map(e=>e[0]),['before','write','callback','after']);
 assert.equal(writes,1);assert.equal(calls,1);assert.equal(commits.length,1);
 assert.equal(commits[0].before.value,value);assert.equal(commits[0].after.value,current.value);
 assert.equal(widget.value,encoded); // The obsolete widget is never written again.
}
''')

    def test_adapter_replaced_widget_on_same_node_and_lazy_loading(self):
        self.adapter_script('''
const oldWidget=widget;
const oldButton=descendants(container).find(e=>e.tagName==='BUTTON');
const oldOpen=async()=>{
 const previous=opened;oldButton.click();
 for(let i=0;i<100&&opened===previous;i++) await new Promise(r=>setTimeout(r,1));
 assert.notEqual(opened,previous);
};
const painted=Uint8Array.from({length:16384},(_,i)=>i%256);
const encoded=await codec.encodeFieldDataUrl(painted);
const current=extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(node,'field',['STRING',{default:''}]).widget;
assert.deepEqual(loadedModules,[]);
current.value=encoded;await settle();assert.ok(loadedModules.every(name=>name==='codec'));
// Retain the original visible button even though node.widgets now holds a new widget.
await oldOpen();assert.deepEqual(opened.codes,painted);opened.onCancel();
assert.ok(loadedModules.includes('ui'));assert.equal(oldWidget.value,'');
current.value='';await oldOpen();assert.deepEqual(opened.codes,empty());
await opened.onDone(painted,{size:22});assert.equal(current.value,encoded);assert.equal(oldWidget.value,'');
''')

    def test_adapter_current_binding_failures_preserve_executable_value(self):
        self.adapter_script('''
const launcherContainer=container;
const current=replaceActive('invalid restored value');resetObservers();
await launch();assert.equal(opened,undefined);assert.equal(current.value,'invalid restored value');
assert.deepEqual(events,[]);
assert.ok(descendants(launcherContainer).some(e=>e.textContent?.includes('Cannot open Influence Field Editor')));
current.value='';await launch();assert.deepEqual(opened.codes,empty());
// Replacement during async Done must not write the now-obsolete session widget.
let release;opened.onCancel();
testCodec={...codec,encodeFieldDataUrl:()=>new Promise(resolve=>release=resolve)};
await launch();const done=opened.onDone(new Uint8Array(16384).fill(173),{size:37});
const replacement=extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(activeNode,'field',['STRING',{default:''}]).widget;
resetObservers();release('must not be committed');
await assert.rejects(()=>done,/active graph changed/);opened.onCancel();
assert.equal(current.value,'');assert.equal(replacement.value,'');assert.deepEqual(events,[]);
// A stale visible launcher has no authority when its field widget is absent.
activeNode.widgets=[];opened=undefined;await launch();
assert.equal(opened,undefined);assert.deepEqual(events,[]);
assert.ok(descendants(launcherContainer).some(e=>e.textContent?.includes('current Painted Field widget is unavailable')));
''')

    def test_adapter_done_once_settings_only_cancel_and_zero_canonicalization(self):
        self.adapter_script('''
const original=codec.pngDataUrl(await codec.encodeFieldPng(new Uint8Array(16384).fill(173)));
widget.value=original;resetObservers();await settle();await launch();
assert.ok(opened);await opened.onDone(opened.codes,{size:22});
assert.equal(widget.value,original);assert.equal(writes,0);assert.equal(calls,0);
assert.deepEqual(node.properties.fieldEditor,{size:22});
assert.equal(before,0);assert.equal(after,0);
await launch();const props=JSON.stringify(node.properties);opened.onCancel();
assert.equal(JSON.stringify(node.properties),props);assert.equal(writes,0);
await launch();await opened.onDone(empty(),{size:22});assert.equal(widget.value,'');assert.equal(writes,1);assert.equal(calls,1);
assert.equal(before,1);assert.equal(after,1);assert.equal(commits.length,1);
// A decodable, noncanonical zero PNG is preserved on unchanged Done.
widget.value=codec.pngDataUrl(await codec.encodeFieldPng(empty()));const zero=widget.value;resetObservers();
await launch();await opened.onDone(empty(),{size:22});assert.equal(widget.value,zero);assert.equal(writes,0);
assert.equal(calls,0);assert.equal(before,0);assert.equal(after,0);
''')

    def test_adapter_changed_done_one_public_lifecycle_and_one_callback(self):
        self.adapter_script('''
await launch();const session=ui.createEditorSession(opened.codes,opened.settings);
session.settings.influence=173;session.operation('fill');
assert.equal(widget.value,'');assert.deepEqual(events,[]);
await opened.onDone(session.codes,session.settings);
assert.deepEqual(events.map(e=>e[0]),['before','write','callback','after']);
assert.equal(events[0][1],'');assert.equal(events[3][1],widget.value);
assert.equal(writes,1);assert.equal(calls,1);assert.equal(dirty,1);
assert.equal(before,1);assert.equal(after,1);assert.equal(commits.length,1);
assert.ok((await codec.decodeFieldDataUrl(widget.value)).every(v=>v===173));
''')

    def test_adapter_unchanged_done_and_cancel_have_no_lifecycle(self):
        self.adapter_script('''
await launch();const settings={...node.properties.fieldEditor};
await opened.onDone(opened.codes,settings);
assert.deepEqual(events,[]);assert.equal(dirty,0);
await launch();const session=ui.createEditorSession(opened.codes,opened.settings);
session.operation('fill',173);session.settings.size=37;opened.onCancel();
assert.deepEqual(node.properties.fieldEditor,settings);assert.equal(widget.value,'');
assert.deepEqual(events,[]);assert.equal(commits.length,0);
// Editing and reverting locally also creates no graph change on Done.
await launch();session.operation('clear');
await opened.onDone(session.codes,settings);
assert.deepEqual(events,[]);assert.equal(writes,0);assert.equal(calls,0);
''')

    def test_adapter_group_expansion_is_a_per_user_setting_never_node_or_graph_state(self):
        self.adapter_script('''
realEditor=true;
const ids={advanced:'ConditioningLayers.InfluenceFieldEditor.AdvancedExpanded',
 behavior:'ConditioningLayers.InfluenceFieldEditor.BrushBehaviorExpanded',
 shape:'ConditioningLayers.InfluenceFieldEditor.BrushShapeExpanded',
 profile:'ConditioningLayers.InfluenceFieldEditor.ValueProfileExpanded',
 fieldTools:'ConditioningLayers.InfluenceFieldEditor.FieldToolsExpanded',
 tip:'ConditioningLayers.InfluenceFieldEditor.CustomTipExpanded',
 procedural:'ConditioningLayers.InfluenceFieldEditor.ProceduralTipExpanded',
 pressure:'ConditioningLayers.InfluenceFieldEditor.PenPressureExpanded'};
assert.deepEqual(extension.settings.map(s=>[s.id,s.name,s.type,s.defaultValue]),[
 [ids.advanced,'Influence Field Editor: expand Advanced','boolean',false],
 [ids.behavior,'Influence Field Editor: expand Brush Behavior','boolean',false],
 [ids.shape,'Influence Field Editor: expand Brush Shape & Transform','boolean',false],
 [ids.profile,'Influence Field Editor: expand Value Profile','boolean',false],
 [ids.fieldTools,'Influence Field Editor: expand Field Tools','boolean',false],
 [ids.tip,'Influence Field Editor: expand Custom Tip','boolean',false],
 [ids.procedural,'Influence Field Editor: expand Procedural Tip','boolean',false],
 [ids.pressure,'Influence Field Editor: expand Pen Pressure','boolean',false]]);
const store=new Map(),settingWrites=[];
globalThis.testApp.ui.settings={getSettingValue:(id,fallback)=>store.has(id)?store.get(id):fallback,
 setSettingValue:(id,v)=>{settingWrites.push([id,v]);store.set(id,v);}};
const group=title=>descendants(document.body).find(e=>e.tagName==='SUMMARY'&&e.textContent.startsWith(title)).parent;
const states=()=>['Advanced','Brush Behavior','Brush Shape'].map(t=>group(t).open);
const toggle=(title,open)=>{const d=group(title);d.open=open;fire(d,'toggle');dom.flush();};
const node2={...node,id:2,properties:{fieldEditor:ui.editorSettings({size:23})}};
const widget2=extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(node2,'field',['STRING',{default:''}]).widget;
graph.getNodeById=id=>({1:node,2:node2})[id];
const launch2=async()=>{await extension.getNodeMenuItems(node2)[0].callback();dom.flush();};
node.properties.fieldEditor=ui.editorSettings({size:16});
widget.value=await codec.encodeFieldDataUrl(Uint8Array.from({length:16384},(_,i)=>i%256));await settle();
const state=()=>JSON.stringify([widget.value,node.properties,widget2.value,node2.properties]),baseline=state();
resetObservers();
// First use: defaults collapse every level; nothing is written.
await launch();dom.flush();assert.deepEqual(states(),[false,false,false]);assert.deepEqual(settingWrites,[]);
toggle('Advanced',true);toggle('Brush Behavior',true);toggle('Brush Shape',true);
assert.deepEqual(settingWrites,[[ids.advanced,true],[ids.behavior,true],[ids.shape,true]]);
assert.equal(controller.session.history.undoEntries.length,0);
// Cancel keeps the preference; a different node opens with the same user-level state.
controller.cancel();assert.deepEqual([...store.values()],[true,true,true]);
await launch2();assert.deepEqual(states(),[true,true,true]);assert.equal(controller.session.settings.size,23);
toggle('Brush Behavior',false);controller.cancel();
await launch();dom.flush();assert.deepEqual(states(),[true,false,true]);
toggle('Brush Shape',false);
// Done with only expansion changes commits nothing to the node, widget or graph history.
descendants(document.body).find(e=>e.tagName==='BUTTON'&&e.textContent==='Done').click();await settle();
assert.equal(document.body.children.length,0);
await launch2();assert.deepEqual(states(),[true,false,false]);controller.cancel();
assert.equal(state(),baseline);assert.deepEqual(events,[]);assert.equal(commits.length,0);
assert.equal(writes,0);assert.equal(calls,0);assert.equal(dirty,0);
assert.ok(!/xpand/.test(JSON.stringify([node.properties,node2.properties])));
assert.deepEqual(settingWrites.map(([id])=>id),[ids.advanced,ids.behavior,ids.shape,ids.behavior,ids.shape]);
''')

    def test_e4_value_profile_expansion_and_settings_through_the_adapter(self):
        self.adapter_script('''
realEditor=true;
const id='ConditioningLayers.InfluenceFieldEditor.ValueProfileExpanded';
const store=new Map(),settingWrites=[];
globalThis.testApp.ui.settings={getSettingValue:(key,fallback)=>store.has(key)?store.get(key):fallback,
 setSettingValue:(key,v)=>{settingWrites.push([key,v]);store.set(key,v);}};
const all=()=>descendants(document.body);
const group=()=>all().find(e=>e.tagName==='SUMMARY'&&e.textContent.startsWith('Value Profile')).parent;
const press=text=>{all().find(e=>e.tagName==='BUTTON'&&e.textContent===text).click();dom.flush();};
const node2={...node,id:2,properties:{fieldEditor:ui.editorSettings({size:23})}};
const widget2=extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(node2,'field',['STRING',{default:''}]).widget;
graph.getNodeById=id=>({1:node,2:node2})[id];
const launch2=async()=>{await extension.getNodeMenuItems(node2)[0].callback();dom.flush();};
node.properties.fieldEditor=ui.editorSettings({size:16});resetObservers();
// Default collapsed; one toggle is one per-user write, shared by every Painted Field node.
await launch();dom.flush();assert.equal(group().open,false);assert.deepEqual(settingWrites,[]);
group().open=true;fire(group(),'toggle');dom.flush();assert.deepEqual(settingWrites,[[id,true]]);
controller.cancel();await launch2();assert.equal(group().open,true);
// A gradient chosen on one node is stored sparsely in its settings on Done; no field or graph change.
press('Radial Gradient');press('Swap Start/End');
all().find(e=>e.tagName==='BUTTON'&&e.textContent==='Done').click();await settle();
assert.deepEqual(node2.properties.fieldEditor,{...ui.editorSettings({size:23}),value_profile:'radial',gradient_start:0,gradient_end:255});
assert.equal(widget2.value,'');assert.deepEqual(events,[]);assert.equal(writes,0);assert.equal(before,0);assert.equal(after,0);
assert.ok(!/xpand/.test(JSON.stringify([node.properties,node2.properties])));
await launch();dom.flush();assert.equal(group().open,true);assert.equal(controller.session.settings.value_profile,'uniform');
controller.cancel();assert.deepEqual(settingWrites,[[id,true]]);
''')

    def test_e5_custom_tip_is_kept_in_node_settings_through_the_adapter(self):
        self.adapter_script('''
realEditor=true;
const tips=await import(TIP_MODULE);
const id='ConditioningLayers.InfluenceFieldEditor.CustomTipExpanded';
const store=new Map(),settingWrites=[];
globalThis.testApp.ui.settings={getSettingValue:(key,fallback)=>store.has(key)?store.get(key):fallback,
 setSettingValue:(key,v)=>{settingWrites.push([key,v]);store.set(key,v);}};
const all=()=>descendants(document.body);
const heading=title=>all().find(e=>e.tagName==='SUMMARY'&&e.textContent?.startsWith(title));
const tipGroup=()=>heading('Custom Tip').parent;
const loaded=async()=>{for(let i=0;i<2000&&!controller.session.tip;i++)await new Promise(r=>setTimeout(r,1));dom.flush();};
const tip={width:5,height:3,luminance:Uint8Array.from({length:15},(_,i)=>i*17),alpha:Uint8Array.from({length:15},(_,i)=>i%4?255:0)};
const bytes=await tips.encodeTipPng(tip);
node.properties.fieldEditor=ui.editorSettings({size:16});resetObservers();
await launch();dom.flush();
descendants(heading('Brush Shape').parent).find(e=>e.tagName==='BUTTON'&&e.textContent==='Custom').click();dom.flush();
tipGroup().open=true;fire(tipGroup(),'toggle');dom.flush();
const picker=all().find(e=>e.accept==='.png,image/png');
picker.files=[{name:'C:/Users/someone/Brushes/secret-tip.png',size:bytes.length,arrayBuffer:async()=>bytes.slice().buffer}];
fire(picker,'change');await loaded();assert.ok(tips.sameTip(controller.session.tip,tip));
all().find(e=>e.tagName==='BUTTON'&&e.textContent==='Done').click();await settle();
// The tip is a brush setting: node.properties only, as its canonical PNG data URL, never a name or path.
const stored=node.properties.fieldEditor;
assert.equal(stored.shape,'custom');assert.ok(tips.storedTipValid(stored.custom_tip));
assert.deepEqual(Object.keys(stored),[...Object.keys(ui.editorSettings({size:16})),'shape','custom_tip']);
assert.ok(!/secret|someone|Brushes/.test(JSON.stringify(node.properties)));
// Settings-only Done: no widget write, callback or graph lifecycle; expansion stays a per-user setting.
assert.equal(widget.value,'');assert.deepEqual(events,[]);assert.equal(writes,0);assert.equal(calls,0);
assert.equal(before,0);assert.equal(after,0);assert.deepEqual(settingWrites,[[id,true]]);
assert.ok(!/xpand/.test(JSON.stringify(node.properties)));
// A workflow save and load keeps it: the next open reads the same tip back.
node.properties=JSON.parse(JSON.stringify(node.properties));
await launch();dom.flush();await loaded();
assert.ok(tips.sameTip(controller.session.tip,tip));assert.equal(tipGroup().open,true);
assert.equal(heading('Custom Tip').textContent,'Custom Tip · 5×3');
controller.cancel();assert.equal(JSON.stringify(node.properties.fieldEditor),JSON.stringify(stored));
assert.deepEqual(events,[]);assert.equal(writes,0);
'''.replace("TIP_MODULE", json.dumps((CORE / "custom_tip.js").as_uri())))

    def test_adapter_undo_redo_snapshot_replay_preserves_exact_values_and_codes(self):
        self.adapter_script('''
const {createHash}=await import('node:crypto');
const measure=async value=>{const codes=await codec.decodeFieldDataUrl(value);return {
 text:value,hash:createHash('sha256').update(codes).digest('hex'),nonzero:codes.filter(v=>v).length};};
const codesA=empty();codesA[42]=173;
const codesB=codesA.slice();codesB[513]=255;
for(const initial of ['',codec.pngDataUrl(await codec.encodeFieldPng(codesA))]) {
 widget.value=initial;resetObservers();const a=await measure(initial);
 await launch();await opened.onDone(codesB,{size:22});const b=await measure(widget.value);
 assert.equal(b.nonzero,2);assert.notEqual(a.hash,b.hash);
 assert.equal(commits.length,1);const commit=commits[0];
 assert.equal(commit.before.value,initial);assert.equal(commit.after.value,b.text);
 restore(commit.before);assert.deepEqual(await measure(widget.value),a);
 restore(commit.after);assert.deepEqual(await measure(widget.value),b);
 assert.equal(before,1);assert.equal(after,1);assert.equal(commits.length,1);
}
''')

    def test_adapter_clear_done_snapshot_undo_redo_and_empty_serialization(self):
        self.adapter_script('''
await launch();const painted=empty();painted[42]=173;
await opened.onDone(painted,{size:22});const original=widget.value;
await launch();const session=ui.createEditorSession(opened.codes,opened.settings);session.operation('clear');
await opened.onDone(session.codes,{size:22});assert.equal(widget.value,'');
assert.equal(commits.length,2);assert.equal(writes,2);assert.equal(calls,2);
const clear=commits[1];assert.equal(clear.before.value,original);assert.equal(clear.after.value,'');
restore(clear.before);assert.equal(widget.value,original);assert.deepEqual(await codec.decodeFieldDataUrl(widget.value),painted);
restore(clear.after);assert.equal(widget.value,'');assert.deepEqual(await codec.decodeFieldDataUrl(widget.value),empty());
// JSON save/restore projection preserves the canonical empty string and painted codes.
for(const state of [clear.before,clear.after]) {
 restore(JSON.parse(JSON.stringify(state)));assert.equal(widget.value,state.value);
 assert.deepEqual(await codec.decodeFieldDataUrl(widget.value),state.value?painted:empty());
}
assert.equal(before,2);assert.equal(after,2);assert.equal(commits.length,2);
''')

    def test_adapter_encoding_finishes_before_lifecycle_and_failures_are_neutral(self):
        self.adapter_script('''
let release;
testCodec={...codec,encodeFieldDataUrl:()=>new Promise(resolve=>release=resolve)};
await launch();const done=opened.onDone(new Uint8Array(16384).fill(173),{size:22});
assert.deepEqual(events,[]);assert.equal(widget.value,'');assert.equal(node.properties.fieldEditor.size,16);
release(await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(173)));await done;
assert.deepEqual(events.map(e=>e[0]),['before','write','callback','after']);
resetObservers();testCodec={...codec,encodeFieldDataUrl:async()=>{throw Error('encode failed');}};
await launch();const original=widget.value,props=JSON.stringify(node.properties);
await assert.rejects(()=>opened.onDone(empty(),{size:37}),/encode failed/);
assert.equal(widget.value,original);assert.equal(JSON.stringify(node.properties),props);assert.deepEqual(events,[]);
''')

    def test_adapter_rejects_stale_graph_node_or_unavailable_lifecycle(self):
        self.adapter_script('''
const cases=[()=>canvas.graph={},()=>node.graph=null,()=>graph.getNodeById=()=>({id:1}),
 ()=>canvas.emitBeforeChange=undefined,()=>canvas.emitAfterChange=undefined];
const beforeMethod=canvas.emitBeforeChange,afterMethod=canvas.emitAfterChange;
for(const invalidate of cases) {
 node.graph=canvas.graph=graph;graph.getNodeById=()=>node;
 canvas.emitBeforeChange=beforeMethod;canvas.emitAfterChange=afterMethod;
 await launch();invalidate();
 await assert.rejects(()=>opened.onDone(new Uint8Array(16384).fill(173),{size:22}),/active graph changed|undo notifications/);
 assert.equal(widget.value,'');assert.equal(node.properties.fieldEditor.size,16);
 assert.deepEqual(events,[]);opened.onCancel();
}
''')

    def test_adapter_pairs_lifecycle_when_widget_callback_throws(self):
        self.adapter_script('''
widget.callback=()=>{calls++;throw Error('callback failed');};
await launch();await assert.rejects(()=>opened.onDone(new Uint8Array(16384).fill(173),{size:22}),/callback failed/);
assert.equal(before,1);assert.equal(after,1);assert.equal(pending,undefined);
assert.equal(writes,1);assert.equal(calls,1);assert.equal(commits.length,1);assert.equal(dirty,1);
assert.ok((await codec.decodeFieldDataUrl(widget.value)).every(v=>v===173));
''')

    def test_adapter_rechecks_value_and_active_graph_after_async_encoding(self):
        self.adapter_script('''
let release;
testCodec={...codec,encodeFieldDataUrl:()=>new Promise(resolve=>release=resolve)};
for(const conflict of ['value','graph']) {
 canvas.graph=graph;widget.value='';resetObservers();await launch();
 const done=opened.onDone(new Uint8Array(16384).fill(173),{size:22});
 assert.deepEqual(events,[]);
 if(conflict==='value') widget.value='external edit';else canvas.graph={};
 resetObservers();release('encoded result must not be committed');
 await assert.rejects(()=>done,/stored field changed while saving|active graph changed/);
 assert.equal(widget.value,conflict==='value'?'external edit':'');
 assert.equal(node.properties.fieldEditor.size,16);assert.deepEqual(events,[]);opened.onCancel();
}
''')

    def test_adapter_failed_core_and_invalid_value_preserve_stored_string(self):
        self.adapter_script('''
const original=codec.pngDataUrl(await codec.encodeFieldPng(new Uint8Array(16384).fill(173)));
widget.value=original;writes=0;fail=true;await launch();
assert.equal(widget.value,original);assert.equal(writes,0);assert.equal(opened,undefined);
assert.ok(descendants(container).some(e=>e.textContent?.includes('Stored value preserved')));
fail=false;widget.value='undecodable value';writes=0;await launch();
assert.equal(widget.value,'undecodable value');assert.equal(writes,0);assert.equal(opened,undefined);
''')

    def test_real_editor_fake_dom_keyboard_pointer_cancel_and_exact_controls(self):
        run_node('''
const dom=installDOM();let done,cancelled=0,advanced=false;
const host={getAdvancedExpanded:()=>advanced,setAdvancedExpanded:v=>advanced=v,getGroupExpanded:()=>false,
 setGroupExpanded:()=>{},confirmDiscard:()=>true};
const settings={size:1};const controller=ui.openInfluenceFieldEditor({codes:empty(),settings,host,
 onDone:(codes,settings)=>{done={codes,settings};},onCancel:()=>cancelled++});dom.flush();
const dialog=document.body.children[0], all=()=>descendants(dialog);
const viewport=all().find(e=>e.className==='viewport');
const press=label=>all().find(e=>e.tagName==='BUTTON'&&e.textContent===label).click();
assert.equal(all().find(e=>e.tagName==='SUMMARY'&&e.textContent==='Advanced').parent.open,false);
// E1 four, E2 Reference Opacity, E3 Flow, Spacing, Scale X/Y, Rotation and four crops, E4 thirteen.
assert.equal(all().filter(e=>e.type==='text').length,41);
// Fit gives four screen pixels per cell plus an eight-pixel margin.
fire(viewport,'pointerdown',{clientX:50,clientY:50});
fire(viewport,'pointermove',{clientX:450,clientY:450,getCoalescedEvents:()=>[{clientX:250,clientY:250}]});
dom.flush();assert.ok(controller.session.codes.some(v=>v));
fire(window,'keydown',{key:'Escape'});dom.flush();assert.ok(controller.session.codes.every(v=>v===0));
fire(viewport,'pointerdown',{clientX:50,clientY:50});fire(viewport,'pointerup',{clientX:450,clientY:450});dom.flush();
assert.equal(controller.session.history.undoEntries.length,1);
const e=fire(window,'keydown',{key:'z',ctrlKey:true});assert.ok(e.stopped);dom.flush();assert.ok(controller.session.codes.every(v=>v===0));
fire(window,'keydown',{key:'y',ctrlKey:true});dom.flush();assert.ok(controller.session.codes.some(v=>v));
press('% ⇄ 0–255');dom.flush();
const influence=all().find(e=>e.attributes['aria-label']==='Influence (0–255)');
fire(influence,'pointerdown');fire(influence,'pointerup');influence.value='173';
fire(window,'keydown',{key:'Enter',target:influence});dom.flush();assert.equal(controller.session.settings.influence,173);
press('Fill with Influence');dom.flush();assert.ok(controller.session.codes.every(v=>v===173));
press('Done');await settle();assert.ok(done.codes.every(v=>v===173));assert.equal(settings.size,1);
assert.equal(document.body.children.length,0);assert.equal(window.listeners.keydown.length,0);
assert.equal(cancelled,0);
''')

    def test_core_architecture_and_adapter_has_only_public_static_import(self):
        source = ADAPTER.read_text(encoding="utf-8")
        static = [line for line in source.splitlines() if line.startswith("import ")]
        self.assertEqual(static, ['import {app} from "../../../scripts/app.js";'])
        for path in CORE.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("scripts/app", "scripts/api", "fetch(", "toBlob(", "getImageData(", "new Image("):
                self.assertNotIn(forbidden, text, (path.name, forbidden))
        engine = (CORE / "engine.js").read_text()
        for forbidden in ("Math.random", "Math.pow", "Math.hypot", "Math.exp", "Math.log", "Math.sin", "Math.cos", "**", "Date."):
            self.assertNotIn(forbidden, engine)
        run_node("assert.equal(globalThis.document,undefined);assert.equal(globalThis.window,undefined);")

    def test_editor_import_one_undo_view_only_pan_zoom_advanced_and_cancel(self):
        run_node('''
const dom=installDOM();let cancelled=0,confirms=0,advanced=false;
const host={getAdvancedExpanded:()=>advanced,setAdvancedExpanded:v=>advanced=v,getGroupExpanded:()=>false,
 setGroupExpanded:()=>{},confirmDiscard:()=>{confirms++;return confirms>1;}};
const c=ui.openInfluenceFieldEditor({codes:empty(),settings:{size:16},host,
 onDone:()=>assert.fail('Cancel must never call Done'),onCancel:()=>cancelled++});dom.flush();
const dialog=document.body.children[0],all=()=>descendants(dialog),viewport=all().find(e=>e.className==='viewport');
const press=text=>all().find(e=>e.tagName==='BUTTON'&&e.textContent===text).click();
const canvas=all().find(e=>e.tagName==='CANVAS'),initialView=canvas.style.transform;
fire(viewport,'wheel',{clientX:50,clientY:50,deltaY:-1});dom.flush();assert.notEqual(canvas.style.transform,initialView);
fire(viewport,'pointerdown',{button:1,clientX:10,clientY:10});fire(viewport,'pointermove',{clientX:60,clientY:70});
fire(viewport,'pointerup',{button:1,clientX:60,clientY:70});dom.flush();
assert.ok(c.session.codes.every(v=>v===0));assert.equal(c.session.history.undoEntries.length,0);
press('Fit');dom.flush();assert.equal(canvas.style.transform,initialView);
fire(viewport,'pointerdown',{pointerType:'pen',clientX:50,clientY:50});fire(viewport,'pointerup',{pointerType:'pen',clientX:50,clientY:50});
assert.equal(c.session.history.undoEntries.length,1);
assert.deepEqual(c.session.codes,new engine.Stroke(empty(),128,128,{...c.session.settings},10.5,10.5).result());
c.session.undo();assert.ok(c.session.codes.every(v=>v===0));
fire(window,'keydown',{key:'{',code:'BracketLeft',shiftKey:true});dom.flush();assert.equal(c.session.settings.hardness,99);
const amount=all().find(e=>e.attributes['aria-label']==='Amount (%)');
fire(amount,'pointerdown');fire(amount,'pointerup');amount.value='40';fire(window,'keydown',{key:'Enter',target:amount});dom.flush();
const summary=all().find(e=>e.tagName==='SUMMARY'&&e.textContent.startsWith('Advanced'));
assert.equal(summary.textContent,'Advanced · Amount 40%');assert.equal(summary.parent.open,false);
summary.parent.open=true;fire(summary.parent,'toggle');assert.equal(advanced,true);
assert.equal(c.session.settings.advanced,undefined);
press('Reset Brush');dom.flush();assert.equal(c.session.settings.amount,100);
const bytes=await codec.encodeFieldPng(new Uint8Array(16384).fill(173));
const picker=all().find(e=>e.type==='file');let read=false;
picker.files=[{size:bytes.length,arrayBuffer:async()=>{read=true;return bytes.buffer;}}];fire(picker,'change');
for(let i=0;i<100&&!c.session.history.undoEntries.length;i++)await new Promise(r=>setTimeout(r,1));
assert.ok(read);assert.equal(c.session.history.undoEntries.length,1);assert.ok(c.session.codes.every(v=>v===173));
c.session.undo();assert.ok(c.session.codes.every(v=>v===0));c.session.redo();
// Invalid oversized import is rejected before reading and never changes codes/history.
picker.files=[{size:65537,arrayBuffer:()=>assert.fail('oversized read')}];fire(picker,'change');await settle();
assert.ok(c.session.codes.every(v=>v===173));assert.equal(c.session.history.undoEntries.length,1);
press('Cancel');assert.equal(cancelled,0);assert.equal(document.body.children.length,1);
press('Cancel');assert.equal(cancelled,1);assert.equal(document.body.children.length,0);
assert.equal(window.listeners.keydown.length,0);
''')
