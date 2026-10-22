"""ADR-0033 offline session checks using real editor modules and the fenced DOM.

No live host or browser qualification. Array comparisons report the first cell
difference, so a failed isolation check cannot produce an enormous diff.
"""
import base64
import json
import re
import unittest

from test_field_editor_custom_tip import CORE, ROOT, run_node, png, b64


COMMON = r"""
const codec = await import(CORE_URL + 'png_codec.js');
const selection = await import(CORE_URL + 'selection.js');
const lib = await import(CORE_URL + 'brush_library.js');
// Identity and long snapshot failures must not inspect the entire cyclic DOM.
const exact = (actual,expected,label='exact equality') => {
  if(!Object.is(actual,expected)){
    const brief=v=>(v!==null&&typeof v==='object')?'[object]':String(v).slice(0,160);
    assert.fail(`${label}: ${brief(actual)} != ${brief(expected)}`);
  }
};
const eq = (a,b,label='codes') => {
  assert.equal(a.length,b.length,label+' length');
  for(let i=0;i<a.length;i++) if(a[i]!==b[i]) assert.fail(`${label}[${i}]: ${a[i]} != ${b[i]}`);
};
const dom = installDOM();
const all = () => descendants(document.body);
const find = cls => all().find(e=>e.className===cls);
const buttons = text => all().filter(e=>e.tagName==='BUTTON'&&e.textContent===text);
const press = text => {const b=buttons(text)[0];assert.ok(b,text);b.click();dom.flush();};
const until = async (predicate,label='operation') => {
  for(let i=0;i<3000;i++){dom.flush();if(predicate())return;await new Promise(r=>setTimeout(r,1));}
  assert.fail('timed out: '+label);
};
const input = label => all().find(e=>e.attributes['aria-label']===label);
const type = (label,value,commit=true) => {
  const e=input(label);assert.ok(e,label);fire(e,'pointerdown');fire(e,'pointerup');e.value=String(value);
  if(commit)fire(window,'keydown',{key:'Enter',target:e});dom.flush();
};
const key = (value,extra={}) => {fire(window,'keydown',{key:value,...extra});dom.flush();};
const pointer = (name,x,y,extra={}) => {
  fire(find('viewport'),name,{clientX:8+x*4,clientY:8+y*4,...extra});dom.flush();
};
const click = (x,y,extra={}) => {pointer('pointerdown',x,y,extra);pointer('pointerup',x,y,extra);};
const overlays = () => all().filter(e=>e.className==='field-overlay');
const tabs = () => all().filter(e=>e.className==='field-select');
const error = () => find('error').textContent||'';
const snapshot = s => JSON.stringify({codes:[...s.codes],initial:[...s.initial],settings:s.settings,
  selection:s.selection&&[...s.selection],selectTool:s.selectTool,selectionMode:s.selectionMode,
  history:s.history,tip:s.tip});
const field = k => controller.fields().find(f=>f.key===String(k));
const activate = k => {const i=controller.fields().findIndex(f=>f.key===String(k));assert.ok(i>=0);tabs()[i].click();dom.flush();};
const remove = k => {const i=controller.fields().findIndex(f=>f.key===String(k));
  all().filter(e=>e.className==='field-remove')[i].click();dom.flush();};
const add = async k => {
  const n=controller.fields().length;press('Add Field…');await until(()=>find('cl-field-chooser'));
  const row=all().find(e=>e.className==='field-candidate'&&e.children.some(c=>c.textContent===`Painted Field #${k}`));
  assert.ok(row,'candidate '+k);row.click();await until(()=>controller.fields().length===n+1||error());
};
const redraw = () => {pointer('pointermove',60,60);dom.flush();};
const inventory = () => find('viewport').children.map(e=>e.className||e.tagName);
const retainedInventory = ['reference','CANVAS','selection-veil','brush-preview','cell-grid',
  'selection-outline','selection-candidate','target-cell','brush-outline'];
""".replace('CORE_URL', json.dumps(CORE.as_uri() + '/'))


EDITOR = COMMON + r"""
const sources = new Map(Array.from({length:5},(_,i)=>{const k=String(i+1);return [k,{key:k,label:`Painted Field #${k}`,
  codes:Uint8Array.from({length:16384},(_,j)=>(j*(i+3)+i*41)%256),
  settings:{tool:i%2?'erase':'paint',size:11+i,influence:61+i*29,hardness:31+i,amount:71+i,
    influenceUnit:i%2?'code':'percent',pressure_enabled:!!(i%2),pressure_size:!!(i%2)}}];}));
const joined = new Set(['1']), unavailable = new Set(), calls = [], offers = [], confirms = [];
let allowDiscard=true, allowRemove=true, cancelled=0, joinError=null, commitError=null;
let libraryText=null;
const library=lib.createBrushLibrary({read:async()=>libraryText,write:async text=>{libraryText=text;}},()=> 'test-preset');
const host = {getAdvancedExpanded:()=>false,setAdvancedExpanded:()=>{},getGroupExpanded:()=>false,setGroupExpanded:()=>{},
  getBrushLibrary:async()=>library,
  confirmDiscard:n=>{confirms.push(['discard',n]);return allowDiscard;},
  confirmRemove:label=>{confirms.push(['remove',label]);return allowRemove;},
  fields:{openingKey:'1',openingLabel:'Painted Field #1',
    candidates:async()=>{calls.push(['candidates']);return [...sources.values()].filter(s=>!joined.has(s.key));},
    join:async k=>{calls.push(['join',k]);if(joinError)throw Error(joinError);joined.add(k);return sources.get(k);},
    leave:k=>{calls.push(['leave',k]);joined.delete(k);},available:k=>!unavailable.has(k),
    commit:async offer=>{offers.push(offer);if(commitError)throw Error(commitError);}}};
const open = () => ui.openInfluenceFieldEditor({codes:sources.get('1').codes,settings:sources.get('1').settings,host,
  onCancel:()=>cancelled++,onDone:()=>assert.fail('legacy callback in multi-field host')});
let controller=open();dom.flush();
"""


def editor(body, data=None):
    return run_node((EDITOR + body).replace('assert.equal(', 'exact('), data)


def instrumented_editor(body):
    """Observe codec calls and delay tip decoding, without changing editor logic."""
    source = (CORE / 'editor_ui.js').read_text(encoding='utf-8')
    source = source.replace('import {decodeFieldPng, encodeFieldPng}',
                            'import {decodeFieldPng as realDecode, encodeFieldPng as realEncode}')
    source = source.replace('import {decodeTipDataUrl, importTipFile, storedTipValid}',
                            'import {decodeTipDataUrl as realTipDecode, importTipFile, storedTipValid}')
    source = re.sub(r'"\./([^"\n]+)"', lambda m: json.dumps((CORE / m[1]).as_uri()), source)
    source += r"""
function decodeFieldPng(...args){globalThis.codecCalls.push('decode');return realDecode(...args);}
function encodeFieldPng(...args){globalThis.codecCalls.push('encode');return realEncode(...args);}
async function decodeTipDataUrl(...args){if(globalThis.tipGate)await globalThis.tipGate();return realTipDecode(...args);}
"""
    encoded = 'data:text/javascript;base64,' + base64.b64encode(source.encode()).decode()
    setup = f'globalThis.codecCalls=[];const testedUi=await import({json.dumps(encoded)});\n'
    script = setup + EDITOR.replace('ui.openInfluenceFieldEditor', 'testedUi.openInfluenceFieldEditor') + body
    return run_node(script.replace('assert.equal(', 'exact('))


class AEditorTests(unittest.TestCase):
    def test_01_single_field_exact_view_and_actions(self):
        editor(r"""
assert.equal(find('field-editing').textContent,'Editing: Painted Field #1');
assert.equal(tabs().length,0);assert.equal(overlays().length,0);assert.deepEqual(inventory(),retainedInventory);
assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='text').length,49);
assert.equal(all().filter(e=>e.type==='range').length,0);
assert.equal(all().filter(e=>e.textContent?.startsWith('Copy from')).length,0);
const reference=ui.createEditorSession(sources.get('1').codes,sources.get('1').settings);
for(const [label,operation] of [['Fill with Influence','fill'],['Invert','invert'],['Clear','clear']]){
  press(label);reference.operation(operation);eq(controller.session.codes,reference.codes);
  assert.equal(JSON.stringify(controller.session.history),JSON.stringify(reference.history));
}
press('Undo');reference.undo();eq(controller.session.codes,reference.codes);
press('Redo');reference.redo();eq(controller.session.codes,reference.codes);
controller.cancel();assert.equal(offers.length,0);
""")

    def test_02_membership_cap_removal_slots_and_fresh_join(self):
        editor(r"""
const first=controller.session, before=snapshot(first);
for(const k of ['2','3','4'])await add(k);
assert.equal(controller.session,first);assert.equal(snapshot(first),before);
assert.deepEqual(controller.fields().map(f=>[f.key,f.slot,f.visible,f.active]),
  [['1',0,true,true],['2',1,true,false],['3',2,true,false],['4',3,true,false]]);
assert.equal(find('field-add').disabled,true);
assert.equal(find('field-add').title,'A session holds at most 4 fields. Remove one to add another.');
press('Add Field…');assert.equal(find('cl-field-chooser'),undefined);assert.equal(controller.fields().length,4);
activate('2');assert.equal(controller.session.history.undoEntries.length,0);
eq(controller.session.initial,sources.get('2').codes);assert.equal(controller.session.settings.size,12);
press('Clear');allowRemove=false;remove('2');assert.ok(field('2'));
allowRemove=true;remove('2');assert.equal(field('2'),undefined);assert.equal(controller.session,field('3').session);
await add('2');assert.equal(field('2').slot,1);eq(field('2').session.codes,sources.get('2').codes);
assert.equal(field('2').session.history.undoEntries.length,0);
remove('3');assert.equal(controller.session,field('4').session);
remove('2');remove('4');assert.equal(controller.session,first);
assert.deepEqual(inventory(),retainedInventory);assert.equal(overlays().length,0);assert.equal(tabs().length,0);
assert.equal(offers.length,0);
""")

    def test_03_switch_state_and_pending_numeric_owner(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
a.selection=selection.rectangleSelection({x:1,y:2},{x:5,y:8});a.selectTool='rectangle';a.selectionMode='add';
b.selection=selection.ellipseSelection({x:30,y:40},{x:50,y:60});b.selectTool='ellipse';b.selectionMode='subtract';
const sa=snapshot(a),sb=snapshot(b),ha=a.history,hb=b.history;
activate('2');assert.equal(controller.session,b);assert.equal(input('Size (cells)').value,'12');
assert.ok(input('Influence (0–255)'));assert.equal(tabs().filter(t=>t.attributes['aria-pressed']==='true').length,1);
activate('1');assert.ok(input('Influence (%)'));assert.equal(snapshot(a),sa);assert.equal(snapshot(b),sb);
assert.equal(a.history,ha);assert.equal(b.history,hb);
type('Size (cells)',37,false);activate('2');assert.equal(a.settings.size,37);assert.equal(b.settings.size,12);
assert.equal(input('Size (cells)').value,'12');assert.equal(offers.length,0);
""")

    def test_04_isolation_interleaved_equivalence_and_pressure(self):
        editor(r"""
await add('2');await add('3');
const references=new Map(controller.fields().map(f=>[f.key,ui.createEditorSession(f.session.codes,f.session.settings)]));
for(const k of ['1','2','3','2','1']){
  activate(k);const s=controller.session,reference=references.get(k);
  const others=controller.fields().filter(f=>f.key!==k).map(f=>[f.key,snapshot(f.session)]);
  press('Paint');reference.settings.tool='paint';
  type('Size (cells)',Number(k)*7);reference.settings.size=Number(k)*7;
  const stroke=new engine.Stroke(reference.codes,128,128,{...reference.settings,tip:reference.tip},31,43,reference.initial,reference.selection);
  click(31,43);reference.replace('Stroke',stroke.result());eq(s.codes,reference.codes,'stroke '+k);
  for(const [label,operation] of [['Fill with Influence','fill'],['Invert','invert']]){
    press(label);reference.operation(operation);eq(s.codes,reference.codes,k);
  }
  press('Undo');reference.undo();press('Redo');reference.redo();eq(s.codes,reference.codes);
  assert.deepEqual(s.settings,reference.settings);assert.equal(s.history.undoEntries.length,reference.history.undoEntries.length);
  for(const [other,state] of others)assert.equal(snapshot(field(other).session),state,'inactive '+other);
}
""")

    def test_05_history_independent_undo_redo(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
press('Clear');activate('2');press('Invert');const editedB=b.codes.slice();press('Undo');eq(b.codes,b.initial);
activate('1');press('Undo');eq(a.codes,a.initial);press('Redo');eq(a.codes,empty());
assert.equal(b.history.redoEntries.length,1);activate('2');press('Redo');eq(b.codes,editedB);
assert.equal(a.history.undoEntries.length,1);assert.equal(b.history.undoEntries.length,1);
""")

    def test_06_restore_join_baselines(self):
        editor(r"""
press('Clear');sources.get('2').codes.fill(199);await add('2');
const a=field('1').session,b=field('2').session;assert.equal(b.initial[0],199);
for(const k of ['1','2']){
  activate(k);press('Clear');press('Restore');const s=controller.session,other=snapshot(k==='1'?b:a);
  const expected=new engine.Stroke(s.codes,128,128,{...s.settings,tool:'restore'},42,51,s.initial,s.selection).result();
  click(42,51);eq(s.codes,expected);assert.equal(snapshot(k==='1'?b:a),other);
}
eq(a.initial,sources.get('1').codes);assert.ok(b.initial.every(c=>c===199));
""")

    def test_07_selection_isolation_and_veil(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
a.selection=selection.rectangleSelection({x:4,y:5},{x:9,y:12});redraw();const mask=a.selection;
const veil=find('selection-veil').pixels.slice();activate('2');assert.equal(b.selection,null);
press('Select All');assert.ok(b.selection.every(c=>c===1));activate('1');assert.equal(a.selection,mask);
eq(find('selection-veil').pixels,veil,'veil');
for(let i=0;i<16384;i++)assert.equal(veil[i*4+3],mask[i]?0:view.SELECTION_VEIL[3]);
assert.equal(field('1').changed,false);assert.equal(field('2').changed,false);
""")

    def test_08_line_anchor_cleared_on_switch(self):
        editor(r"""
await add('2');click(20,20);const a=controller.session,before=a.codes.slice(),n=a.history.undoEntries.length;
const expected=new engine.Stroke(before,128,128,{...a.settings,tip:a.tip},80,80,a.initial,a.selection).result();
const staleLine=new engine.Stroke(before,128,128,{...a.settings,tip:a.tip},20,20,a.initial,a.selection);
staleLine.add(80,80);const connected=staleLine.result();
assert.ok(expected.some((c,i)=>c!==before[i]),'the local dab must change this fixture');
assert.ok(connected.some((c,i)=>c!==expected[i]),'the old-anchor line must differ from the dab');
activate('2');activate('1');click(80,80,{shiftKey:true});eq(a.codes,expected,'exact retained local dab');
for(let y=35;y<=65;y++)for(let x=35;x<=65;x++)
  assert.equal(a.codes[y*128+x],before[y*128+x],'no connection through the intervening region');
assert.equal(a.history.undoEntries.length,n+1);
const next=new engine.Stroke(expected,128,128,{...a.settings,tip:a.tip},80,80,a.initial,a.selection);
next.add(105,95);click(105,95,{shiftKey:true});eq(a.codes,next.result(),'new dab endpoint anchors the next line');
assert.equal(a.history.undoEntries.length,n+2);
""")

    def test_09_gesture_switch_guards(self):
        editor(r"""
await add('2');const a=controller.session;
for(const extra of [{},{pointerType:'pen',pressure:0.6},{button:1}]){
  pointer('pointerdown',15,15,extra);activate('2');assert.equal(controller.session,a);
  pointer('pointerup',18,18,extra);activate('2');assert.equal(controller.session,field('2').session);activate('1');
}
press('Rectangle Select');pointer('pointerdown',10,10);activate('2');assert.equal(controller.session,a);
pointer('pointerup',20,20);activate('2');assert.equal(controller.session,field('2').session);activate('1');
press('Add Field…');await until(()=>find('cl-field-chooser'));activate('2');assert.equal(controller.session,a);press('Close');
unavailable.add('2');activate('2');assert.equal(controller.session,a);
""")

    def test_10_overlays_python_oracle_and_display_only(self):
        alpha = [0 if c == 0 else 32 + (192 * c + 255) // 510 for c in range(256)]
        editor(r"""
const palette=[[249,100,241],[184,254,96],[9,135,119],[215,25,8]];
assert.deepEqual(view.OVERLAY_COLORS,palette);
for(let c=0;c<256;c++)assert.equal(view.overlayAlpha(c),data[c]);
for(const color of palette){const codes=Uint8Array.from({length:16384},(_,i)=>i%256),before=codes.slice();
  const pixels=view.overlayPixels(codes,color);eq(codes,before);
  for(let i=0;i<16384;i++)eq(pixels.slice(i*4,i*4+4),[...color,data[i%256]],'rgba');}
await add('2');await add('3');await add('4');
assert.equal(overlays().length,4);assert.deepEqual(inventory().slice(0,6),['reference','CANVAS',...Array(4).fill('field-overlay')]);
assert.equal(overlays()[0].hidden,true);assert.equal(overlays()[1].hidden,false);
const before=controller.fields().map(f=>snapshot(f.session)), pixels=overlays()[1].pixels;
press('Heat View');assert.equal(overlays()[1].pixels,pixels);
for(let i=0;i<4;i++)assert.equal(snapshot(controller.fields()[i].session),before[i]);
const show=all().filter(e=>e.className==='field-show')[1];show.click();dom.flush();assert.equal(overlays()[1].hidden,true);
press('Reset View');assert.equal(overlays()[1].hidden,true);show.click();dom.flush();assert.equal(overlays()[1].pixels,pixels);
redraw();assert.equal(overlays()[1].pixels,pixels);
""", alpha)

    def test_11_copy_exact_selection_source_and_history(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
activate('2');press('Invert');b.selection=selection.rectangleSelection({x:50,y:50},{x:70,y:70});activate('1');
const source=snapshot(b),before=a.codes.slice();press('Copy from Painted Field #2');eq(a.codes,b.codes);
assert.equal(a.history.undoEntries.length,1);assert.equal(snapshot(b),source);
press('Copy from Painted Field #2');assert.equal(a.history.undoEntries.length,1);
press('Undo');eq(a.codes,before);press('Redo');eq(a.codes,b.codes);press('Undo');
a.selection=selection.rectangleSelection({x:1,y:3},{x:6,y:9});
const expected=before.slice();for(let i=0;i<16384;i++)if(a.selection[i])expected[i]=b.codes[i];
press('Copy from Painted Field #2');eq(a.codes,expected);assert.equal(snapshot(b),source);
assert.equal(a.history.undoEntries.length,1);assert.equal(field('1').changed,true);
""")

    def test_12_library_active_only_and_preset_excludes_session(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
const preset=await lib.captureBrushPreset({...a.settings,size:39},{id:'saved',name:'Saved',category:'General',favorite:false});
assert.deepEqual(Object.keys(preset.brush),lib.SNAPSHOT_KEYS);
libraryText=JSON.stringify({version:1,presets:[preset]});
activate('2');const before=snapshot(a);press('Brush Library…');
await until(()=>find('library-status')&&!find('library-status').textContent.startsWith('Working'));
activate('1');assert.equal(controller.session,b);
const row=all().find(e=>e.className==='preset-select'&&e.textContent==='Saved · General');assert.ok(row);row.click();dom.flush();
press('Apply');await until(()=>b.settings.size===39);assert.equal(snapshot(a),before);
const captured=await lib.captureBrushPreset(b.settings,{id:'captured',name:'Captured',category:'General',favorite:false});
assert.deepEqual(Object.keys(captured.brush),lib.SNAPSHOT_KEYS);
""")

    def test_13_import_mask_bound_to_opening_active_field(self):
        image = b64(png(2, 2, 0, 8, [(11,), (55,), (173,), (251,)]))
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session,before=snapshot(b);
const bytes=bytesOf(data),picker=all().find(e=>e.accept==='image/png');
let resolve;picker.files=[{size:bytes.length,arrayBuffer:()=>new Promise(r=>resolve=r)}];fire(picker,'change');
activate('2');assert.equal(controller.session,a);resolve(bytes.buffer);
await until(()=>find('cl-mask-import')||error().startsWith('Cannot import the mask:'));
assert.ok(find('cl-mask-import'),error());
activate('2');assert.equal(controller.session,a);assert.equal(a.history.undoEntries.length,0);
const preview=descendants(find('cl-mask-import')).find(e=>e.tagName==='CANVAS').pixels;
const expected=Uint8Array.from({length:16384},(_,i)=>preview[i*4]);press('Apply Import');
eq(a.codes,expected);assert.equal(a.history.undoEntries.length,1);assert.equal(snapshot(b),before);
activate('2');assert.equal(controller.session,b);
""", image)

    def test_14_dirty_cancel_offer_set_and_reopen(self):
        editor(r"""
await add('2');await add('3');const a=field('1').session,b=field('2').session;
press('Select All');assert.equal(field('1').changed,false);activate('2');type('Size (cells)',48);
activate('1');press('Clear');allowDiscard=false;press('Cancel');assert.deepEqual(confirms.at(-1),['discard',2]);
assert.ok(find('cl-field-editor'));assert.equal(offers.length,0);allowDiscard=true;press('Cancel');
assert.equal(cancelled,1);assert.equal(offers.length,0);assert.equal(find('cl-field-editor'),undefined);
assert.equal(a.selection,null);assert.equal(b.selection,null);
joined.clear();joined.add('1');controller=open();dom.flush();assert.equal(controller.fields().length,1);
await add('2');await add('3');activate('2');type('Size (cells)',48);press('Done');await until(()=>!find('cl-field-editor'));
assert.deepEqual(offers[0].map(o=>o.key),['1','2']);assert.equal(offers[0][1].settings.size,48);
assert.notEqual(offers[0][1].codes,b.codes);
""")

    def test_26_pressure_mapping_and_live_stroke_isolation(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
activate('2');press('Paint');b.settings.pressure_amount=true;b.settings.pressure_size=true;
const before=snapshot(a),codes=b.codes.slice();
const expected=new engine.PressureStroke(codes,128,128,b.settings,25,35,b.initial,b.selection,engine.pressureCode(.2));
expected.add(40,50,engine.pressureCode(.7));
pointer('pointerdown',25,35,{pointerType:'pen',pressure:.2});activate('1');assert.equal(controller.session,b);
pointer('pointermove',40,50,{pointerType:'pen',pressure:.7});activate('1');assert.equal(controller.session,b);
pointer('pointerup',40,50,{pointerType:'pen',pressure:0});eq(b.codes,expected.result(),'B pressure');
assert.equal(snapshot(a),before);activate('1');
const mouse=new engine.Stroke(a.codes,128,128,a.settings,60,70,a.initial,a.selection).result();
click(60,70);eq(a.codes,mouse,'A mouse after B pen');
assert.equal(a.settings.pressure_enabled,false);assert.equal(b.settings.pressure_enabled,true);
""")

    def test_27_shared_view_compare_transforms_and_overlay_cache(self):
        editor(r"""
await add('2');await add('3');const original=controller.fields().map(f=>snapshot(f.session));
let reads=0;dom.Element.prototype.getImageData=()=>{reads++;assert.fail('display readback');};
const canvas=find('viewport').children[1];const old=overlays()[1].pixels;
URL.createObjectURL=()=> 'blob:reference';URL.revokeObjectURL=()=>{};
const picker=all().find(e=>e.accept==='image/*');picker.files=[new Blob(['reference'])];fire(picker,'change');
await until(()=>!find('reference').hidden);
press('Heat View');press('Grid (at ≥8 px/cell)');type('Reference Opacity (%)',63);
fire(find('viewport'),'wheel',{clientX:72,clientY:72,deltaY:-1});dom.flush();
pointer('pointerdown',30,30,{button:1});pointer('pointermove',40,50,{button:1});pointer('pointerup',40,50,{button:1});
const transform=canvas.style.transform,reference=find('reference').src;
activate('2');assert.equal(canvas.style.transform,transform);assert.equal(find('reference').src,reference);
assert.equal(find('reference').style.opacity,'0.63');assert.equal(buttons('Heat View')[0].attributes['aria-pressed'],'true');
for(const overlay of overlays())assert.equal(overlay.style.transform,transform);
activate('1');assert.equal(overlays()[1].pixels,old,'no unchanged overlay redraw');
const compare=buttons('Hold to Compare')[0];fire(compare,'pointerdown');dom.flush();
assert.ok(overlays().every(o=>o.hidden));fire(compare,'pointerup');dom.flush();assert.equal(overlays()[1].hidden,false);
press('Fit');for(const overlay of overlays())assert.equal(overlay.style.transform,canvas.style.transform);
for(let i=0;i<3;i++)assert.equal(snapshot(controller.fields()[i].session),original[i]);assert.equal(reads,0);
const previous=overlays()[0].pixels;press('Clear');activate('2');assert.notEqual(overlays()[0].pixels,previous);
const redrawn=overlays()[0].pixels;redraw();redraw();assert.equal(overlays()[0].pixels,redrawn);
""")

    def test_28_pending_png_tip_and_join_switch_guards(self):
        image = b64(png(128, 128, 0, 8, [(i % 251,) for i in range(16384)]))
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session,before=snapshot(b),bytes=bytesOf(data);
for(const accept of ['.png','.png,image/png']){
  const picker=all().find(e=>e.accept===accept);let resolve;
  picker.files=[{size:bytes.length,arrayBuffer:()=>new Promise(r=>resolve=r)}];fire(picker,'change');
  activate('2');assert.equal(controller.session,a);resolve(bytes.slice().buffer);
  await until(()=>accept==='.png'?a.history.undoEntries.length===1:!!a.tip);
  assert.equal(snapshot(b),before);activate('2');assert.equal(controller.session,b);activate('1');
}
eq(a.codes,Uint8Array.from({length:16384},(_,i)=>i%251));
let resolve;host.fields.join=k=>new Promise(r=>resolve=()=>{joined.add(k);r(sources.get(k));});
press('Add Field…');await until(()=>find('cl-field-chooser'));
all().find(e=>e.className==='field-candidate'&&e.children.some(c=>c.textContent==='Painted Field #3')).click();
activate('2');assert.equal(controller.session,a);resolve();await until(()=>field('3'));activate('2');assert.equal(controller.session,b);
""", image)

    def test_29_custom_tips_per_field_and_library_capture(self):
        editor(r"""
const tipA={width:2,height:2,luminance:Uint8Array.of(1,4,9,16),alpha:Uint8Array.of(255,200,150,100)};
const tipB={width:2,height:2,luminance:Uint8Array.of(25,36,49,64),alpha:Uint8Array.of(30,60,90,120)};
controller.cancel();sources.get('1').settings={...sources.get('1').settings,shape:'custom',custom_tip:await tips.encodeTipDataUrl(tipA)};
sources.get('2').settings={...sources.get('2').settings,shape:'custom',custom_tip:await tips.encodeTipDataUrl(tipB)};
controller=open();dom.flush();await until(()=>controller.session.tip);await add('2');await until(()=>field('2').session.tip);
const a=field('1').session,b=field('2').session,identityA=a.tip,identityB=b.tip;
eq(a.tip.luminance,tipA.luminance);eq(b.tip.alpha,tipB.alpha);activate('2');activate('1');
assert.equal(a.tip,identityA);assert.equal(b.tip,identityB);
activate('2');const before=snapshot(a);press('Brush Library…');
await until(()=>find('library-status')&&!find('library-status').textContent.startsWith('Working'));
input('Preset name').value='Field B';press('Save As New');await until(()=>libraryText!==null);
const saved=JSON.parse(libraryText).presets[0];assert.equal(saved.brush.custom_tip,b.settings.custom_tip);
for(const forbidden of ['fields','membership','active','slot','visible','selection','history','label'])
  assert.equal(Object.hasOwn(saved.brush,forbidden),false);
assert.equal(snapshot(a),before);
""")

    def test_30_join_errors_unavailable_ui_remove_opening_and_dirty(self):
        editor(r"""
joinError='join unavailable';await add('2');assert.equal(controller.fields().length,1);
assert.equal(error(),'Cannot add Painted Field #2: join unavailable');joinError=null;
find('error').textContent='';await add('2');await add('3');
unavailable.add('2');redraw();assert.equal(tabs()[1].disabled,true);
assert.equal(buttons('Copy from Painted Field #2')[0].disabled,true);
assert.equal(all().filter(e=>e.className==='field-name')[1].textContent,'Painted Field #2 (unavailable)');
assert.equal(overlays()[1].hidden,false);const unchanged=snapshot(controller.session);
press('Copy from Painted Field #2');assert.equal(snapshot(controller.session),unchanged);
press('Restore');assert.equal(field('1').changed,false,'Restore stores canonically as Paint');
remove('1');assert.equal(controller.session,field('2').session,'removal keeps same index even unavailable');
press('Clear');assert.equal(field('2').changed,true);remove('2');assert.equal(controller.fields().length,1);
assert.ok(confirms.some(c=>c[0]==='remove'&&c[1]==='Painted Field #2'));
press('Done');await until(()=>offers.length===1);assert.deepEqual(offers[0],[]);
""")

    def test_31_message_reset_copy_select_all_and_selection_equivalence(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
press('Rectangle Select');pointer('pointerdown',4,5);pointer('pointermove',20,25);pointer('pointerup',20,25);
const oracle=ui.createEditorSession(a.initial,a.settings);oracle.selection=selection.rectangleSelection({x:4,y:5},{x:20,y:25});
for(const [label,op] of [['Fill with Influence','fill'],['Invert','invert'],['Clear','clear']]){
  activate('2');activate('1');press(label);oracle.operation(op);eq(a.codes,oracle.codes);}
press('Clear Selection');oracle.selection=null;press('Flip Horizontal');oracle.transform('flip_horizontal');eq(a.codes,oracle.codes);
find('error').textContent='message for A';activate('2');assert.equal(error(),'');activate('1');assert.equal(error(),'');
press('Select All');const before=snapshot(b);press('Copy from Painted Field #2');eq(a.codes,b.codes);assert.equal(snapshot(b),before);
""")

    def test_32_delayed_custom_tip_updates_bound_record_only(self):
        instrumented_editor(r"""
const image=await tips.encodeTipDataUrl({width:1,height:1,luminance:Uint8Array.of(73),alpha:Uint8Array.of(111)});
sources.get('2').settings={shape:'custom',custom_tip:image};let release;
globalThis.tipGate=()=>new Promise(r=>release=r);await add('2');const a=field('1').session,b=field('2').session;
const unchanged=snapshot(a);assert.equal(b.tip,null);release();await until(()=>b.tip);
assert.equal(controller.session,a);assert.equal(snapshot(a),unchanged);assert.equal(b.tip.alpha[0],111);
activate('2');assert.ok(!find('tip-status').textContent.includes('loading'));activate('1');
remove('2');await add('2');const discarded=field('2').session;remove('2');release();await settle();dom.flush();
assert.equal(discarded.tip,null,'late decoder cannot revive a removed record');assert.equal(snapshot(a),unchanged);
""")

    def test_33_switch_idle_show_no_codec_or_history_copy(self):
        instrumented_editor(r"""
await add('2');press('Clear');const a=field('1').session,b=field('2').session;
const history=a.history,entry=history.undoEntries[0],before=entry.before,after=entry.after;
activate('2');activate('1');const pixels=overlays()[1].pixels,tab=tabs()[1];
for(let i=0;i<5;i++){redraw();const show=all().filter(e=>e.className==='field-show')[1];show.click();dom.flush();}
assert.equal(overlays()[1].pixels,pixels);assert.equal(tabs()[1],tab,'idle render does not rebuild tabs');
assert.deepEqual(globalThis.codecCalls,[]);assert.equal(a.history,history);assert.equal(history.undoEntries[0],entry);
assert.equal(entry.before,before);assert.equal(entry.after,after);assert.notEqual(a.history,b.history);
""")

    def test_34_chooser_disabled_rows_thumbnails_close_and_dispose(self):
        editor(r"""
host.fields.candidates=async()=>[
  {key:'2',label:'Painted Field #2',codes:sources.get('2').codes,error:null},
  {key:'3',label:'Painted Field #3',codes:null,error:'invalid field'}];
press('Add Field…');await until(()=>find('cl-field-chooser'));const chooser=find('cl-field-chooser');
const rows=all().filter(e=>e.className==='field-candidate');assert.equal(rows.length,2);assert.equal(rows[1].disabled,true);
assert.equal(rows[1].children.length,1);assert.equal(rows[1].children[0].textContent,'Painted Field #3 — cannot be read: invalid field');
const thumb=rows[0].children[0];assert.equal(thumb.width,128);assert.equal(thumb.height,128);
for(let i=0;i<16384;i++)eq(thumb.pixels.slice(i*4,i*4+4),[...Array(3).fill(sources.get('2').codes[i]),255]);
rows[1].click();assert.equal(controller.fields().length,1);key('Escape');assert.equal(find('cl-field-chooser'),undefined);
rows[0].click();await settle();assert.equal(controller.fields().length,1);assert.equal(chooser.children.length,0);
host.fields.candidates=async()=>[];press('Add Field…');await until(()=>find('cl-field-chooser'));
assert.ok(all().some(e=>e.textContent==='No other Painted Field node in this graph.'));controller.cancel();
assert.ok(!find('cl-field-editor'));assert.ok(!find('cl-field-chooser'));
""")


ADAPTER = COMMON + r"""
let extension, controller, opened, failOpen=false, codecGate=null, decodeGate=null;
const codecCounts={decode:0,encode:0};
const events=[], settingsWrites=[], confirmations=[];
const graph={nodes:[],getNodeById(id){return this.nodes.find(n=>String(n.id)===String(id));}};
const graphSnapshot=()=>JSON.parse(JSON.stringify(graph.nodes.map(n=>({id:n.id,properties:n.properties,
  widgets_values:n.widgets.map(w=>w.value)}))));
// Port of the documented host tracker: nested counter, capture suppression,
// whole-graph equality, previous snapshots, and whole-snapshot undo/redo.
const tracker={changeCount:0,restoring:false,loading:false,undoStack:[],redoStack:[],current:null,
  before(){this.changeCount++;},after(){this.changeCount--;assert.ok(this.changeCount>=0);if(!this.changeCount)this.capture();},
  capture(){if(this.changeCount>0||this.restoring||this.loading)return;
    const next=graphSnapshot();if(JSON.stringify(next)===JSON.stringify(this.current))return;
    this.undoStack.push(this.current);this.redoStack=[];this.current=next;},
  restore(state){this.restoring=true;try{for(const item of state){const n=graph.getNodeById(item.id);
    n.properties=structuredClone(item.properties);item.widgets_values.forEach((v,i)=>n.widgets[i].value=v);}
    this.current=graphSnapshot();}finally{this.restoring=false;}},
  undo(){assert.ok(this.undoStack.length);this.redoStack.push(this.current);this.restore(this.undoStack.pop());},
  redo(){assert.ok(this.redoStack.length);this.undoStack.push(this.current);this.restore(this.redoStack.pop());},
  reset(){this.current=graphSnapshot();this.undoStack=[];this.redoStack=[];events.length=0;}};
globalThis.testApp={registerExtension:e=>extension=e,ui:{settings:{getSettingValue:()=>false,
  setSettingValue:(...args)=>settingsWrites.push(args)}},canvas:{graph,
  emitBeforeChange(){events.push('before');tracker.before();},emitAfterChange(){events.push('after');tracker.after();}}};
globalThis.loadEditorModule=async name=>name==='codec'?{...codec,
  decodeFieldDataUrl:async value=>{codecCounts.decode++;if(decodeGate)await decodeGate();return codec.decodeFieldDataUrl(value);},
  encodeFieldDataUrl:async codes=>{codecCounts.encode++;
  if(codecGate)await codecGate();return codec.encodeFieldDataUrl(codes);}}:{...ui,openInfluenceFieldEditor:options=>{
    if(failOpen)throw Error('core unavailable');opened=options;controller=ui.openInfluenceFieldEditor(options);return controller;}};
const adapterModule = await import(ADAPTER_URL);
const makeNode=(id,settings=undefined,title='Painted Field')=>{
  const n={id,title,graph,properties:settings===undefined?{}:{fieldEditor:settings},widgets:[],setDirtyCanvas(){},
    addDOMWidget(name,type,element,opts){const w={name,type,element,refuse:false,
      callback(){events.push('callback '+id);if(w.callbackError)throw Error('callback '+id);}};
      Object.defineProperty(w,'value',{get:opts.getValue,set:value=>{events.push('write '+id);
        if(!w.refuse)opts.setValue(value);w.callback?.(w.value);tracker.capture();}});
      this.widgets.push(w);return w;}};
  graph.nodes.push(n);extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(n,'field',['STRING',{default:''}]);return n;
};
const nodes=[makeNode(1),makeNode(2),makeNode(3),makeNode(4),makeNode(5)];
const launch=async(n=nodes[0])=>{await extension.getNodeMenuItems(n)[0].callback();dom.flush();};
const join=async k=>{await add(k);assert.ok(field(k),error());};
const done=async()=>{press('Done');await until(()=>!find('cl-field-editor')||error(),'Done');};
const editCodes=k=>{activate(k);press('Fill with Influence');};
window.confirm=message=>{confirmations.push(message);return true;};
tracker.reset();await launch();
"""


def adapter(body, data=None):
    source = (ROOT / 'web/js/painted_field_node.js').read_text(encoding='utf-8')
    source += '\nexport {compareNodeIds};\n'  # Test-only access; no production export.
    source = source.replace('import {app} from "../../../scripts/app.js";',
                            'const app=globalThis.testApp;')
    source = source.replace('import("./field_editor/png_codec.js")',
                            'globalThis.loadEditorModule("codec")')
    source = source.replace('import("./field_editor/editor_ui.js")',
                            'globalThis.loadEditorModule("ui")')
    encoded = 'data:text/javascript;base64,' + base64.b64encode(source.encode()).decode()
    script = ADAPTER.replace('ADAPTER_URL', json.dumps(encoded)) + body
    return run_node(script.replace('assert.equal(', 'exact('), data)


class BAdapterTests(unittest.TestCase):
    def test_15_single_field_commit_exactness(self):
        adapter(r"""
press('Fill with Influence');tracker.reset();await done();
assert.deepEqual(events,['before','write 1','callback 1','after']);assert.equal(tracker.undoStack.length,1);
const value=nodes[0].widgets[0].value;assert.ok(value);await launch();tracker.reset();await done();
assert.deepEqual(events,[]);assert.equal(nodes[0].widgets[0].value,value);
await launch();press('Clear');tracker.reset();await done();assert.equal(nodes[0].widgets[0].value,'');
assert.equal(tracker.undoStack.length,1);
await launch();type('Size (cells)',35);tracker.reset();await done();assert.deepEqual(events,[]);
assert.equal(nodes[0].properties.fieldEditor.size,35);assert.equal(tracker.undoStack.length,0);
tracker.capture();assert.equal(tracker.undoStack.length,1);
""")

    def test_16_discovery_identity_titles_and_cap(self):
        adapter(r"""
nodes[1].title=nodes[2].title='Same';nodes[3].title='';nodes[4].title=42;
const text=makeNode('z',undefined,'<b>label</b>'),numeric=makeNode(10),early=makeNode('a',undefined,'😀'.repeat(41));
const wrong=makeNode(6);wrong.widgets[0].type='OTHER';const sub=makeNode(7);sub.graph={};
const duplicate=makeNode(8);duplicate.widgets.push({...duplicate.widgets[0]});
for(const n of graph.nodes)for(const name of ['mode','links','pos','strength'])
  Object.defineProperty(n,name,{get(){assert.fail('forbidden discovery read '+name);}});
const list=await opened.host.fields.candidates();assert.deepEqual(list.map(i=>i.key),['2','3','4','5','10','a','z']);
assert.equal(list[0].label,'Same #2');assert.equal(list[1].label,'Same #3');
assert.equal(list[2].label,'Painted Field #4');assert.equal(list[3].label,'Painted Field #5');
assert.equal(list[5].label,'😀'.repeat(39)+'… #a');assert.equal(list[6].label,'<b>label</b> #z');
await opened.host.fields.join('2');await opened.host.fields.join('3');await opened.host.fields.join('4');
await assert.rejects(opened.host.fields.join('2'),/already in this session/);
await assert.rejects(opened.host.fields.join('5'),/at most 4 fields/);
assert.deepEqual(events,[]);
""")

    def test_17_prewrite_conflicts_no_partial_commit(self):
        adapter(r"""
await join('2');await join('3');editCodes('1');editCodes('2');editCodes('3');
nodes[2].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(17));
const before=graphSnapshot();tracker.reset();await done();assert.deepEqual(graphSnapshot(),before);
assert.deepEqual(events,[]);assert.equal(tracker.undoStack.length,0);
assert.equal(error(),'Painted Field #3: the stored field changed while editing. Remove it from this session to keep the other changes, or Cancel and reopen.');
remove('3');await done();assert.equal(tracker.undoStack.length,1);
""")

    def test_18_postencode_conflict_and_graph_replacement(self):
        for kind in ['value', 'graph']:
            with self.subTest(kind=kind):
                adapter(r"""
await join('2');editCodes('1');editCodes('2');let once=true;
codecGate=async()=>{if(!once)return;once=false;if(data==='value')nodes[1].widgets[0].value='external';
  else globalThis.testApp.canvas.graph={};};
const original=graphSnapshot();tracker.reset();await done();
assert.equal(nodes[0].widgets[0].value,'');assert.deepEqual(nodes[0].properties,original[0].properties);
assert.ok(!events.includes('before'));assert.ok(find('cl-field-editor'));
assert.match(error(),data==='value'?/Painted Field #2: the stored field changed while saving/:/The active graph changed while editing/);
""", kind)

    def test_19_deletion_replacement_and_untouched_deleted_field(self):
        for kind in ['deleted', 'node', 'widget', 'untouched']:
            with self.subTest(kind=kind):
                adapter(r"""
await join('2');editCodes('1');if(data!=='untouched')editCodes('2');
const victim=nodes[1];if(data==='widget')victim.widgets=[{...victim.widgets[0]}];
else if(data==='node')graph.nodes[1]={...victim};else graph.nodes=graph.nodes.filter(n=>n!==victim);
tracker.reset();await done();
if(data==='untouched'){assert.equal(tracker.undoStack.length,1);assert.equal(find('cl-field-editor'),undefined);}
else{assert.equal(nodes[0].widgets[0].value,'');assert.deepEqual(events,[]);
  assert.equal(error(),'Painted Field #2: the field is no longer in this graph. Remove it from this session to keep the other changes, or Cancel and reopen.');}
""", kind)

    def test_20_callback_exception_keeps_all_values_and_retry_refuses(self):
        adapter(r"""
await join('2');await join('3');for(const k of ['1','2','3'])editCodes(k);
nodes[1].widgets[0].callbackError=true;tracker.reset();await done();
assert.deepEqual(events,['before','write 1','callback 1','write 2','callback 2','write 3','callback 3','after']);
for(const n of nodes.slice(0,3))assert.ok((await codec.decodeFieldDataUrl(n.widgets[0].value)).every(c=>c===255));
assert.equal(tracker.undoStack.length,1);assert.equal(tracker.changeCount,0);
assert.equal(error(),'Saved, but a host notification failed: callback 2 Cancel closes the editor; graph Undo reverts the save.');
const saved=graphSnapshot();find('error').textContent='';events.length=0;await done();
assert.match(error(),/Painted Field #1: the stored field changed while editing/);assert.deepEqual(events,[]);
assert.deepEqual(graphSnapshot(),saved);nodes[1].widgets[0].callbackError=false;controller.cancel();
tracker.undo();assert.ok(nodes.slice(0,3).every(n=>n.widgets[0].value===''));
""")

    def test_21_value_failure_rolls_back_all_properties_and_values(self):
        adapter(r"""
await join('2');await join('3');for(const k of ['1','2','3'])editCodes(k);
nodes[1].widgets[0].refuse=true;const before=graphSnapshot();tracker.reset();await done();
assert.deepEqual(graphSnapshot(),before);assert.equal(tracker.undoStack.length,0);assert.equal(tracker.changeCount,0);
assert.equal(events.filter(e=>e==='before').length,1);assert.equal(events.filter(e=>e==='after').length,1);
assert.equal(error(),'Painted Field #2: the stored value did not take the new field. Nothing was changed.');
assert.ok(find('cl-field-editor'));
""")

    def test_22_atomic_graph_tracker_undo_redo_all_fields(self):
        adapter(r"""
await join('2');await join('3');await join('4');editCodes('1');editCodes('2');activate('3');type('Size (cells)',44);
const before=graphSnapshot();tracker.reset();await done();const after=graphSnapshot();
assert.deepEqual(events,['before','write 1','callback 1','write 2','callback 2','after']);
assert.equal(tracker.undoStack.length,1);assert.equal(tracker.changeCount,0);
assert.equal(nodes[2].properties.fieldEditor.size,44);assert.deepEqual(nodes[3].properties,{});
tracker.undo();assert.deepEqual(graphSnapshot(),before);tracker.redo();assert.deepEqual(graphSnapshot(),after);
assert.equal(settingsWrites.length,0);
""")

    def test_23_settings_only_and_nested_tracker(self):
        adapter(r"""
await join('2');type('Size (cells)',33);activate('2');type('Size (cells)',44);
const before=graphSnapshot();tracker.reset();await done();assert.deepEqual(events,[]);assert.equal(tracker.undoStack.length,0);
tracker.capture();assert.equal(tracker.undoStack.length,1);tracker.undo();assert.deepEqual(graphSnapshot(),before);
await launch();await join('2');editCodes('1');editCodes('2');tracker.reset();tracker.before();
await done();assert.equal(tracker.undoStack.length,0);assert.equal(tracker.changeCount,1);
tracker.after();assert.equal(tracker.undoStack.length,1);tracker.undo();assert.deepEqual(graphSnapshot(),before);
""")

    def test_24_cancel_and_nonpersistence(self):
        adapter(r"""
await join('2');editCodes('1');editCodes('2');const before=graphSnapshot();tracker.reset();press('Cancel');
assert.equal(confirmations.at(-1),'Discard changes to 2 fields and their brush settings?');
assert.deepEqual(graphSnapshot(),before);assert.deepEqual(events,[]);assert.equal(tracker.undoStack.length,0);
await launch(nodes[1]);assert.equal(controller.fields().length,1);assert.equal(controller.fields()[0].key,'2');
assert.equal(controller.fields()[0].slot,0);assert.equal(controller.session.selection,null);assert.equal(overlays().length,0);
press('Fill with Influence');press('Cancel');assert.equal(confirmations.at(-1),'Discard field and brush-setting changes?');
assert.equal(extension.settings.length,8);assert.equal(settingsWrites.length,0);
""")

    def test_25_session_guard_stale_release_and_open_failure(self):
        adapter(r"""
const original=controller,stale=opened.onCancel;await launch(nodes[1]);assert.equal(controller,original);
assert.match(nodes[1].widgets[0].element.children[2].textContent,/another Influence Field Editor is open/);
controller.cancel();await launch(nodes[1]);const second=controller;stale();await launch(nodes[2]);assert.equal(controller,second);
controller.cancel();failOpen=true;await launch(nodes[2]);assert.match(nodes[2].widgets[0].element.children[2].textContent,/core unavailable/);
failOpen=false;await launch(nodes[2]);assert.equal(controller.fields()[0].key,'3');controller.cancel();
""")

    def test_35_discovery_join_fresh_value_and_exact_decode_counts(self):
        adapter(r"""
const baseline=codecCounts.decode;await opened.host.fields.candidates();assert.equal(codecCounts.decode-baseline,4);
const image=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(77));nodes[1].widgets[0].value=image;
await settle();const atJoin=codecCounts.decode;const joined=await opened.host.fields.join('2');
assert.equal(codecCounts.decode-atJoin,1);assert.ok(joined.codes.every(c=>c===77));
await assert.rejects(opened.host.fields.join('2'),/already in this session/);
nodes[2].widgets[0].value='not a PNG';await settle();const items=await opened.host.fields.candidates();
const invalid=items.find(i=>i.key==='3');assert.equal(invalid.codes,null);assert.ok(invalid.error);
assert.equal(nodes[2].widgets[0].value,'not a PNG');
// Change the value after capture but before decoding completes, without a setter recursion.
nodes[3].widgets[0].value=image;await settle();
decodeGate=async()=>{decodeGate=null;nodes[3].widgets[0].value='';};
await assert.rejects(opened.host.fields.join('4'),/stored field changed while it was being read/);
""")

    def test_36_prewrite_encode_failure_missing_notifications_and_single_messages(self):
        for case in ['encode', 'notifications', 'unknown', 'conflict', 'graph']:
            with self.subTest(case=case):
                adapter(r"""
press('Fill with Influence');const initial=graphSnapshot();tracker.reset();
if(data==='unknown')await assert.rejects(opened.host.fields.commit([{key:'unknown',codes:empty(),settings:{}}]),/^Error: Unknown session field\.$/);
else{
  if(data==='encode')codecGate=async()=>{throw Error('encoding refused');};
  if(data==='notifications')globalThis.testApp.canvas.emitAfterChange=null;
  if(data==='conflict')nodes[0].widgets[0].value='external';
  if(data==='graph')globalThis.testApp.canvas.graph={};
  events.length=0;await done();
  const messages={encode:'encoding refused',notifications:'Graph undo notifications are unavailable. Stored value preserved.',
    conflict:'The stored field changed while editing. Cancel and reopen.',graph:'The active graph changed while editing. Cancel and reopen.'};
  assert.equal(error(),messages[data]);assert.ok(find('cl-field-editor'));
}
assert.deepEqual(events,[]);assert.deepEqual(nodes[0].properties,initial[0].properties);
""", case)

    def test_37_opening_canonicalization_and_unoffered_conflicts(self):
        adapter(r"""
await join('2');await join('3');nodes[1].properties.fieldEditor={size:-1,extra:'unchanged'};
nodes[2].widgets[0].value='external';await settle();tracker.reset();await done();
assert.deepEqual(nodes[0].properties.fieldEditor,ui.editorSettings());
assert.deepEqual(nodes[1].properties.fieldEditor,{size:-1,extra:'unchanged'});
assert.equal(nodes[2].widgets[0].value,'external');assert.deepEqual(events,[]);
await launch();await join('2');remove('1');assert.equal(controller.session,field('2').session);press('Fill with Influence');
const original=structuredClone(nodes[0].properties);tracker.reset();await done();
assert.deepEqual(nodes[0].properties,original);assert.deepEqual(events,['before','write 2','callback 2','after']);
""")

    def test_38_per_field_settings_write_order_and_schema(self):
        adapter(r"""
await join('2');await join('3');const trace=[];
for(const n of nodes.slice(0,3)){
  n.properties=new Proxy(n.properties,{set(target,key,value){trace.push('settings '+n.id);target[key]=value;return true;}});
  n.widgets[0].callback=()=>trace.push('value '+n.id);
}
type('Size (cells)',21);press('Fill with Influence');activate('2');type('Size (cells)',32);press('Fill with Influence');
activate('3');type('Size (cells)',43);tracker.reset();await done();
assert.deepEqual(trace,['settings 1','value 1','settings 2','value 2','settings 3']);
for(let i=0;i<3;i++){
  assert.equal(nodes[i].properties.fieldEditor.size,21+11*i);
  assert.deepEqual(Object.keys(nodes[i].properties),['fieldEditor']);
  assert.deepEqual(Object.keys(nodes[i].properties.fieldEditor),Object.keys(ui.editorSettings()));
}
assert.deepEqual(nodes[3].properties,{});assert.equal(settingsWrites.length,0);
assert.equal(tracker.undoStack.length,1);
""")

    def test_39_available_identity_and_no_codec_on_switch(self):
        adapter(r"""
await join('2');const counts={...codecCounts};
for(let i=0;i<5;i++){activate('2');activate('1');redraw();}
assert.deepEqual(codecCounts,counts);
const f=opened.host.fields,n=nodes[1],w=n.widgets[0];assert.equal(f.available('2'),true);
n.graph={};assert.equal(f.available('2'),false);n.graph=graph;
n.widgets=[];assert.equal(f.available('2'),false);n.widgets=[w];
graph.nodes[1]={...n};assert.equal(f.available('2'),false);graph.nodes[1]=n;
globalThis.testApp.canvas.graph={};assert.equal(f.available('2'),false);globalThis.testApp.canvas.graph=graph;
assert.equal(f.available('2'),true);assert.equal(f.available('missing'),false);
""")

    def test_40_no_import_time_host_work_or_session_storage(self):
        for filename in ['field_chooser_ui.js', 'view.js']:
            source = (CORE / filename).read_text(encoding='utf-8')
            for forbidden in ['scripts/app', 'scripts/api', 'localStorage', 'sessionStorage',
                              'indexedDB', 'node.properties', 'getImageData']:
                self.assertNotIn(forbidden, source)
        adapter(r"""
for(const name of ['localStorage','sessionStorage','indexedDB'])Object.defineProperty(globalThis,name,
  {get(){assert.fail('session storage '+name);}});
await join('2');activate('2');press('Fill with Influence');await done();
await launch();assert.equal(controller.fields().length,1);assert.equal(settingsWrites.length,0);
controller.cancel();assert.equal(document.body.children.length,0);
""")


class CReviewRegressionTests(unittest.TestCase):
    def test_41_exact_integer_node_id_sort_and_stable_ties(self):
        adapter(r"""
const compare=adapterModule.compareNodeIds;
for(const pair of [[2,10],['2','10'],[2,'10'],['2',10],['02','10'],
  ['9007199254740992','9007199254740993']]){
  assert.ok(compare(...pair)<0);assert.ok(compare(pair[1],pair[0])>0);
}
for(const pair of [[2,'2'],['02',2],['0002','2']])assert.equal(compare(...pair),0);
assert.deepEqual(['10','02',2,'2','0002'].sort(compare),['02',2,'2','0002','10']);
assert.deepEqual(['z','2abc','a','1.5','-2',' 2','+2','2e1'].sort(compare),
  [' 2','+2','-2','1.5','2abc','2e1','a','z']);
assert.ok(compare('2abc','10')>0);assert.ok(compare(' 2','10')<0);
assert.ok(compare(10,'2abc')<0);assert.ok(compare('2abc',10)>0);
""")

    def test_42_real_host_string_ids_render_numeric_chooser_order(self):
        # Both reviewed frontend versions use string NodeId at runtime.
        for frontend in ['1.49.6', '1.52.7']:
            with self.subTest(frontend=frontend):
                adapter(r"""
controller.cancel();for(const n of nodes)n.id=String(n.id);
const ten=makeNode('10'),nine=makeNode('9');
graph.nodes=[nodes[0],ten,nodes[1],nine,nodes[4],nodes[2],nodes[3]];
await launch();const identities=graph.nodes.slice(),ids=graph.nodes.map(n=>n.id);
press('Add Field…');await until(()=>find('cl-field-chooser'));
const rows=all().filter(e=>e.className==='field-candidate');
assert.deepEqual(rows.map(r=>r.children.at(-1).textContent),
 ['Painted Field #2','Painted Field #3','Painted Field #4','Painted Field #5','Painted Field #9','Painted Field #10']);
rows[0].click();await until(()=>field('2'));
assert.equal(field('2').key,'2');assert.equal(opened.host.fields.available('2'),true);
assert.deepEqual(graph.nodes.map(n=>n.id),ids);
graph.nodes.forEach((n,i)=>assert.equal(n,identities[i]));
controller.cancel();
""")

    def test_43_rendered_overlay_pixels_independent_oracle(self):
        alpha = [0 if c == 0 else 32 + (64 * c + 85) // 170 for c in range(256)]
        editor(r"""
const palette=[[249,100,241],[184,254,96],[9,135,119],[215,25,8]];
// Fixtures and expected pixels never call the product overlay helpers.
const expected=new Map([...sources].map(([k,s])=>[k,s.codes.slice()]));
const verify=()=>{
 const fields=controller.fields(),canvases=overlays();assert.equal(canvases.length,fields.length);
 fields.forEach((f,index)=>{
  const canvas=canvases[index];assert.equal(canvas.hidden,f.active||!f.visible);
  if(canvas.hidden)return;
  const codes=expected.get(f.key),rgb=palette[f.slot];assert.ok(canvas.pixels,'rendered overlay pixels');
  assert.equal(canvas.pixels.length,65536);
  for(let i=0;i<16384;i++)for(let channel=0;channel<4;channel++)
   assert.equal(canvas.pixels[4*i+channel],channel===3?data[codes[i]]:rgb[channel],`field ${f.key} pixel ${i} channel ${channel}`);
 });
};
await add('2');await add('3');await add('4');verify();
activate('2');verify();activate('4');verify();
// Fresh rendering while Heat View is already on, not just a cached-image comparison.
press('Heat View');remove('2');await add('2');
assert.deepEqual(controller.fields().map(f=>[f.key,f.slot]),[['1',0],['3',2],['4',3],['2',1]]);verify();
activate('1');verify();remove('2');remove('3');remove('4');assert.equal(overlays().length,0);
await add('2');activate('2');verify();remove('2');
press('Clear');expected.set('1',new Uint8Array(16384));await add('2');activate('2');verify();
await add('3');verify();activate('3');verify();
""", alpha)

    def test_44_remove_and_copy_keyboard_guards_during_destructive_gestures(self):
        for gesture in ['mouse', 'pressure', 'selection', 'chooser', 'pending', 'library']:
            with self.subTest(gesture=gesture):
                adapter(r"""
nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(177));
await join('2');controller.session.settings.pressure_enabled=true;controller.session.settings.pressure_size=true;
let release;const extra=data==='pressure'?{pointerType:'pen',pressure:0.6}:{};
if(data==='selection')press('Rectangle Select');
if(['mouse','pressure','selection'].includes(data))pointer('pointerdown',20,20,extra);
if(data==='chooser'){press('Add Field…');await until(()=>find('cl-field-chooser'));}
if(data==='pending'){decodeGate=()=>new Promise(r=>release=r);press('Add Field…');await until(()=>release);}
if(data==='library'){
 opened.host.getBrushLibrary=async()=>lib.createBrushLibrary({read:async()=>null,write:async()=>{}},()=> 'guard');
 press('Brush Library…');await until(()=>find('library-status')&&!find('library-status').textContent.startsWith('Working'));
}
const before=controller.fields().map(f=>snapshot(f.session)),members=controller.fields().map(f=>f.key);
const graphBefore=graphSnapshot();tracker.reset();
const targets=[...all().filter(e=>e.className==='field-remove'),buttons('Copy from Painted Field #2')[0]];
for(const target of targets)for(const activation of ['keyboard','mouse']){
 // The fake DOM has no native defaults. Deliver Enter, then the browser's
 // default keyboard click (detail=0) unless keydown prevented it.
 if(activation==='keyboard'){
  target.focus();const event=fire(window,'keydown',{key:'Enter',target});
  if(!event.prevented&&!target.disabled)fire(target,'click',{detail:0});
 }else target.click();
 dom.flush();
 assert.deepEqual(controller.fields().map(f=>f.key),members);
 assert.deepEqual(controller.fields().map(f=>snapshot(f.session)),before);
 assert.deepEqual(graphSnapshot(),graphBefore);assert.deepEqual(events,[]);
 assert.equal(tracker.undoStack.length,0);assert.equal(confirmations.length,0);
}
if(release){decodeGate=null;release();await until(()=>find('cl-field-chooser'));}
controller.cancel();
""", gesture)

    def test_45_dirty_markers_history_and_offer_are_independent(self):
        editor(r"""
sources.get('2').codes=sources.get('1').codes.slice();await add('2');
const mark=k=>all().filter(e=>e.className==='field-mark')[controller.fields().findIndex(f=>f.key===k)].textContent;
const check=(k,dirty)=>{assert.equal(field(k).changed,dirty);assert.equal(mark(k),dirty?'●':'');
 assert.equal(tabs()[controller.fields().findIndex(f=>f.key===k)].title,`Painted Field #${k}`+(dirty?' · changed':''));};
check('1',false);check('2',false);press('Select All');check('1',false);press('Clear Selection');
all().filter(e=>e.className==='field-show')[1].click();dom.flush();check('2',false);
activate('2');activate('1');check('1',false);check('2',false);
press('Copy from Painted Field #2');check('1',false);assert.equal(controller.session.history.undoEntries.length,0);
press('Clear');check('1',true);press('Undo');check('1',false);
assert.equal(controller.session.history.redoEntries.length,1);
// Also clear dirty with nonempty undo history: two edits return to original codes.
press('Invert');press('Invert');check('1',false);assert.equal(controller.session.history.undoEntries.length,2);
type('Size (cells)',38);check('1',true);type('Size (cells)',11);check('1',false);
press('Restore');check('1',false);press('Paint');
activate('2');press('Clear');check('2',true);activate('1');press('Copy from Painted Field #2');
check('1',true);check('2',true);eq(controller.session.codes,new Uint8Array(16384));
press('Undo');check('1',false);activate('2');press('Undo');check('2',false);
press('Done');await until(()=>offers.length===1);
assert.deepEqual(offers[0].map(f=>f.key),['1'],'clean opening offered for compatibility; clean added omitted');
eq(offers[0][0].codes,sources.get('1').codes);assert.equal(confirms.length,0);
""")

    def test_46_chooser_to_join_captures_current_codes_restore_and_widget(self):
        adapter(r"""
const w=nodes[1].widgets[0];w.value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(19));
press('Add Field…');await until(()=>find('cl-field-chooser'));
const row=all().find(e=>e.className==='field-candidate'&&e.children.at(-1).textContent==='Painted Field #2');
assert.equal(row.children[0].pixels[0],19);
const joinedCodes=new Uint8Array(16384).fill(173),joinedValue=await codec.encodeFieldDataUrl(joinedCodes);
w.value=joinedValue;nodes[1].properties.fieldEditor={size:1,hardness:100,amount:100,tool:'paint'};
row.click();await until(()=>field('2'));const b=field('2').session;
eq(b.codes,joinedCodes);eq(b.initial,joinedCodes);assert.equal(b.settings.size,1);
activate('2');press('Clear');press('Restore');click(40.5,50.5);
assert.equal(b.codes[50*128+40],173);eq(b.initial,joinedCodes);
// A settings-only write must compare with the join widget, not the chooser widget.
press('Undo');press('Undo');eq(b.codes,joinedCodes);type('Size (cells)',7);
tracker.reset();await done();assert.equal(find('cl-field-editor'),undefined);
assert.equal(w.value,joinedValue);assert.equal(nodes[1].properties.fieldEditor.size,7);assert.deepEqual(events,[]);
""")

    def test_47_unchanged_codes_still_conflict_on_widget_identity(self):
        # Independently encode a zero PNG: same codes as empty-string value,
        # different widget representation. Authority is exact stored value.
        zero_url = 'data:image/png;base64,' + b64(png(128, 128, 0, 8, [(0,)] * 16384))
        for phase in ['editing', 'saving']:
            for target in ['opening', 'added']:
                with self.subTest(phase=phase, target=target):
                    adapter(r"""
await join('2');await join('3');const victim=data.target==='opening'?nodes[0]:nodes[1];
activate(String(victim.id));type('Size (cells)',37);editCodes('3');
const beforeValue=victim.widgets[0].value;assert.equal(beforeValue,'');
eq(await codec.decodeFieldDataUrl(data.value),new Uint8Array(16384));
let expected;
const change=()=>{victim.widgets[0].value=data.value;victim.properties.fieldEditor={size:61};expected=graphSnapshot();tracker.reset();};
if(data.phase==='editing')change();else codecGate=async()=>{codecGate=null;change();};
tracker.reset();await done();assert.deepEqual(graphSnapshot(),expected);
assert.deepEqual(events,[]);assert.equal(tracker.undoStack.length,0);
assert.equal(error(),`Painted Field #${victim.id}: the stored field changed while ${data.phase}. Remove it from this session to keep the other changes, or Cancel and reopen.`);
assert.ok(find('cl-field-editor'));controller.cancel();
""", {'phase': phase, 'target': target, 'value': zero_url})

    def test_48_refused_done_retains_token_until_cancel_or_recovery(self):
        for failure in ['conflict', 'unavailable', 'validation']:
            for exit_path in ['cancel', 'retry']:
                with self.subTest(failure=failure, exit_path=exit_path):
                    adapter(r"""
await join('2');editCodes('1');editCodes('2');
const victim=nodes[1],value=victim.widgets[0].value,notify=globalThis.testApp.canvas.emitAfterChange;
if(data.failure==='conflict')victim.widgets[0].value='external';
if(data.failure==='unavailable')graph.nodes=graph.nodes.filter(n=>n!==victim);
if(data.failure==='validation')globalThis.testApp.canvas.emitAfterChange=null;
const before=graphSnapshot();tracker.reset();await done();assert.ok(error());assert.ok(find('cl-field-editor'));
assert.deepEqual(graphSnapshot(),before);assert.deepEqual(events,[]);
const owner=controller,ownerOptions=opened;await launch(nodes[2]);assert.equal(controller,owner);assert.equal(opened,ownerOptions);
assert.equal(nodes[2].widgets[0].element.children[2].textContent,
 'Cannot open Influence Field Editor: another Influence Field Editor is open. Stored value preserved.');
assert.equal(all().filter(e=>e.className==='cl-field-editor').length,1);
if(data.exit==='cancel')controller.cancel();else{
 if(data.failure==='conflict')victim.widgets[0].value=value;
 if(data.failure==='unavailable')graph.nodes.push(victim);
 globalThis.testApp.canvas.emitAfterChange=notify;find('error').textContent='';tracker.reset();await done();
 assert.equal(find('cl-field-editor'),undefined);assert.equal(tracker.undoStack.length,1);
}
await launch(nodes[2]);assert.notEqual(controller,owner);assert.equal(controller.fields()[0].key,'3');controller.cancel();
""", {'failure': failure, 'exit': exit_path})

    def test_49_real_adapter_remove_readd_discards_all_field_state(self):
        adapter(r"""
const tip=await tips.encodeTipDataUrl({width:1,height:1,luminance:Uint8Array.of(73),alpha:Uint8Array.of(111)});
nodes[1].properties.fieldEditor={shape:'custom',custom_tip:tip,pressure_enabled:true,pressure_size:true};
nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(31));
await join('2');await until(()=>field('2').session.tip);activate('2');
const old=controller.session;press('Clear');old.selection=new Uint8Array(16384).fill(1);
old.selectTool='ellipse';old.selectionMode='subtract';old.settings.shape='procedural';old.settings.procedural_seed=981;
const graphBefore=graphSnapshot();tracker.reset();remove('2');assert.deepEqual(graphSnapshot(),graphBefore);assert.deepEqual(events,[]);
assert.equal(controller.fields().length,1);assert.equal(overlays().length,0);
assert.ok((await opened.host.fields.candidates()).some(i=>i.key==='2'));
const freshCodes=new Uint8Array(16384).fill(219),freshValue=await codec.encodeFieldDataUrl(freshCodes);
nodes[1].widgets[0].value=freshValue;nodes[1].properties.fieldEditor={tool:'erase',size:29,pressure_enabled:false};
await join('2');assert.equal(controller.fields().filter(f=>f.key==='2').length,1);
const fresh=field('2').session;assert.notEqual(fresh,old);eq(fresh.codes,freshCodes);eq(fresh.initial,freshCodes);
assert.equal(fresh.selection,null);assert.equal(fresh.selectTool,null);assert.equal(fresh.selectionMode,'replace');
assert.equal(fresh.history.undoEntries.length,0);assert.equal(fresh.history.redoEntries.length,0);assert.equal(fresh.tip,null);
assert.equal(Object.hasOwn(fresh.settings,'custom_tip'),false);assert.equal(fresh.settings.shape,'disk');
assert.equal(fresh.settings.pressure_enabled,false);assert.equal(fresh.settings.tool,'erase');assert.equal(fresh.settings.size,29);
assert.notEqual(fresh.settings.procedural_seed,981);assert.equal(overlays().length,2);assert.equal(new Set(overlays()).size,2);
assert.equal(opened.host.fields.available('2'),true);assert.equal(graph.getNodeById('2'),nodes[1]);
activate('2');type('Size (cells)',30);tracker.reset();await done();assert.equal(find('cl-field-editor'),undefined);
assert.equal(nodes[1].widgets[0].value,freshValue);assert.equal(nodes[1].properties.fieldEditor.size,30);assert.deepEqual(events,[]);
""")

    def test_50_switch_refreshes_incoming_rendered_controls_and_status(self):
        editor(r"""
sources.get('2').codes=new Uint8Array(16384).fill(73);
sources.get('2').settings={tool:'erase',size:29,hardness:43,amount:67,influence:101,influenceUnit:'code',
 shape:'custom',custom_tip:null,pressure_enabled:true,pressure_size:true,pressure_amount:true};
await add('2');const a=controller.session;
const image=await tips.encodeTipDataUrl({width:1,height:1,luminance:Uint8Array.of(73),alpha:Uint8Array.of(111)});
a.settings.custom_tip=image;a.settings.shape='custom';a.tip=await tips.decodeTipDataUrl(image);press('Clear');
assert.equal(buttons('Undo')[0].disabled,false);assert.equal(buttons('Redo')[0].disabled,true);
assert.equal(find('tip-status').textContent,'');
const heading=prefix=>all().find(e=>e.tagName==='SUMMARY'&&e.textContent.startsWith(prefix));
const verifyB=()=>{
 assert.equal(buttons('Undo')[0].disabled,true);assert.equal(buttons('Redo')[0].disabled,false);
 assert.ok(find('status').textContent.endsWith('16384 cells · 16384 nonzero · 0 zero · binary no · min 73 · max 73 · mean 73.00 · 1 distinct'));
 assert.equal(find('tip-status').textContent,'No custom tip is loaded. Import a PNG under Custom Tip.');
 assert.equal(find('tip-status').hidden,false);assert.equal(heading('Custom Tip').textContent,'Custom Tip · none loaded');
 assert.equal(buttons('Erase')[0].attributes['aria-pressed'],'true');assert.equal(buttons('Paint')[0].attributes['aria-pressed'],'false');
 for(const [label,value] of [['Size (cells)','29'],['Hardness (%)','43'],['Amount (%)','67'],['Influence (0–255)','101']])
  assert.equal(input(label).value,value);
 assert.equal(buttons('Use Pen Pressure')[0].attributes['aria-pressed'],'true');
 assert.equal(heading('Pen Pressure').textContent,'Pen Pressure · Size · Amount');
 assert.ok(heading('Brush Behavior').textContent.includes('Pen Pressure (Size, Amount)'));
};
activate('2');assert.equal(buttons('Undo')[0].disabled,true);assert.equal(buttons('Redo')[0].disabled,true);
press('Clear');press('Undo');verifyB();activate('1');
assert.equal(buttons('Undo')[0].disabled,false);assert.equal(buttons('Redo')[0].disabled,true);
assert.equal(find('tip-status').textContent,'');assert.equal(buttons('Use Pen Pressure')[0].attributes['aria-pressed'],'false');
assert.ok(find('status').textContent.includes('16384 cells · 0 nonzero · 16384 zero · binary yes · min 0 · max 0 · mean 0.00 · 1 distinct'));
activate('2');verifyB();
""")
