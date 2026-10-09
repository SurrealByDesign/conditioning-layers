"""E6 offline contracts and fake-DOM integration; no live host or browser."""
import base64
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "web/js/field_editor"
PRELUDE = "\n".join(
    f"const {name} = await import({json.dumps(path.as_uri())});"
    for name, path in {
        "lib": CORE / "brush_library.js", "ui": CORE / "editor_ui.js",
        "engine": CORE / "engine.js", "tips": CORE / "custom_tip.js",
        "brushes": CORE / "brush.js",
        "domTools": Path(__file__).with_name("field_editor_fake_dom.js"),
    }.items()
) + r"""
import assert from 'node:assert/strict';
const {installDOM, descendants, fire, settle} = domTools;
const empty = () => new Uint8Array(16384);
const base = () => ui.createEditorSession(empty()).settings;
const meta = {id:'preset-1', name:'Soft', category:'General', favorite:false};
const preset = extra => lib.captureBrushPreset({...base(), ...extra}, meta);
const tip = {width:3,height:2,luminance:Uint8Array.of(0,60,255,125,185,25),alpha:Uint8Array.of(0,200,255,20,99,0)};
const custom = async () => ({...base(),shape:'custom',custom_tip:await tips.encodeTipDataUrl(tip),
 size:27,influence:173,hardness:42,amount:67,scale_x:1.7,scale_y:0.8,rotation_degrees:-32.5,
 mirror_horizontal:true,mirror_vertical:true,crop_left:7,crop_right:19,crop_top:11,crop_bottom:23,
 falloff_curve:'linear',build_up:true,flow:61,spacing:'custom',spacing_percent:13,apply_mode:'raise_only',
 value_profile:'radial',gradient_start:219,gradient_end:41,gradient_curve:2.3,gradient_angle:17.5,
 gradient_start_position:13,gradient_end_position:87,gradient_center_x:31,gradient_center_y:73,
 gradient_inner:17,gradient_outer:123,gradient_aspect_x:0.7,gradient_aspect_y:1.6,gradient_rotation:-27.3,
 tip_channel:'alpha_luminance',tip_invert:true,tip_trim:true});
const fixture = (text = null) => {
 let stored = text, writes = 0, reads = 0, sequence = 0, fail = false;
 const storage = {read:async()=>{reads++;return stored;},write:async value=>{if(fail)throw Error('disk full');stored=value;writes++;}};
 return {storage, library:lib.createBrushLibrary(storage,()=>`id-${++sequence}`), get text(){return stored;},
 get writes(){return writes;},get reads(){return reads;},set fail(v){fail=v;}};
};
const painted = (settings, decoded, initial = empty()) => {
 const stroke = new engine.Stroke(initial,128,128,{...settings,tool:'paint',tip:decoded},22.5,37.25);
 stroke.add(47.5,64.25);stroke.add(62.25,57.5);return stroke.result();
};
const until = async predicate => {for(let i=0;i<3000;i++){if(predicate())return;await new Promise(r=>setTimeout(r,1));}assert.fail('timeout');};
"""


def run_node(source):
    result = subprocess.run(["node", "--input-type=module"], input=PRELUDE + source,
                            cwd=ROOT, text=True, capture_output=True, encoding="utf-8", timeout=90)
    if result.returncode:
        raise AssertionError(result.stderr + result.stdout)
    return result.stdout


EDITOR = r"""
const dom = installDOM(), f = fixture();let done, cancelled=0;
const host = {getAdvancedExpanded:()=>true,setAdvancedExpanded:()=>{},getGroupExpanded:()=>false,
 setGroupExpanded:()=>{},confirmDiscard:()=>true,getBrushLibrary:async()=>f.library};
const open = settings => ui.openInfluenceFieldEditor({codes:empty(),settings,host,
 onDone:(codes,settings)=>{done={codes,settings};},onCancel:()=>cancelled++});
let editor = open(base());dom.flush();
const all=()=>descendants(document.body), button=t=>all().find(e=>e.tagName==='BUTTON'&&e.textContent===t);
const field=t=>all().find(e=>e.attributes['aria-label']===t);
const press=t=>{assert.ok(button(t),t);button(t).click();dom.flush();};
const status=()=>all().find(e=>e.className==='library-status');
const idle=async()=>{await until(()=>status()&&!status().textContent.startsWith('Working'));dom.flush();};
const library=async()=>{press('Brush Library…');await idle();};
const act=async title=>{press(title);await idle();};
const neutral=()=>{assert.deepEqual(editor.session.codes,empty());assert.equal(editor.session.history.undoEntries.length,0);
 assert.equal(editor.session.history.redoEntries.length,0);};
"""


class BrushLibraryTests(unittest.TestCase):
    def test_complete_snapshot_reset_apply_bit_exact_all_profiles_and_apply_modes(self):
        run_node(r"""
for(const value_profile of ['uniform','linear','radial','square'])for(const apply_mode of ['normal','raise_only','lower_only']) {
 const source={...await custom(),value_profile,apply_mode}, p=await lib.captureBrushPreset(source,meta);
 assert.equal(Object.keys(p.brush).length,lib.SNAPSHOT_KEYS.length+1);
 for(const key of lib.SNAPSHOT_KEYS)assert.equal(p.brush[key],source[key],key);
 const initial=Uint8Array.from({length:16384},(_,i)=>i%256);
 const before=painted(source,tip,initial), session=ui.createEditorSession(initial);
 Object.assign(session.settings,brushes.BRUSH_DEFAULTS,{amount:100});
 await lib.applyBrushPreset(p,session);
 assert.deepEqual(await lib.captureBrushPreset(session.settings,meta),p);
 assert.deepEqual(painted(session.settings,session.tip,initial),before);
 assert.deepEqual(session.codes,initial);assert.equal(session.history.undoEntries.length,0);
 assert.deepEqual(ui.editorSettings(session.settings),ui.editorSettings(source));
}
""")

    def test_builtin_shapes_round_trip_without_custom_asset(self):
        run_node(r"""
for(const shape of ['disk','square','diamond']) {
 const source={...await custom(),shape};const p=await lib.captureBrushPreset(source,meta);
 assert.ok(!('custom_tip' in p.brush));const session=ui.createEditorSession(empty());
 await lib.applyBrushPreset(p,session);assert.equal(session.tip,null);assert.ok(!('custom_tip' in session.settings));
 assert.deepEqual(painted(source),painted(session.settings));
}
""")

    def test_snapshot_excludes_tool_view_history_and_session_state(self):
        run_node(r"""
for(const tool of ['paint','erase','restore']) {
 const s={...base(),tool,panX:27,zoom:3,reference:'file:test',codes:empty(),history:{},advanced:true,
  influenceUnit:'code',library:{},appliedPresetId:'old',status:'hello',initial:empty()};
 const p=await lib.captureBrushPreset(s,meta);
 assert.deepEqual(Object.keys(p.brush),lib.SNAPSHOT_KEYS);
 const target=ui.createEditorSession(empty(),{tool:'erase',influenceUnit:'code'});target.settings.tool=tool;
 await lib.applyBrushPreset(p,target);assert.equal(target.settings.tool,tool);assert.equal(target.settings.influenceUnit,'code');
}
""")

    def test_every_required_field_missing_rejected_transactionally(self):
        run_node(r"""
const p=await preset(),target=ui.createEditorSession(empty(),{size:37});
for(const key of lib.SNAPSHOT_KEYS) {
 const bad=structuredClone(p);delete bad.brush[key];const before=JSON.stringify(target);
 await assert.rejects(lib.applyBrushPreset(bad,target),new RegExp(key));assert.equal(JSON.stringify(target),before);
}
""")

    def test_numeric_enum_pairs_precision_and_metadata_validation(self):
        run_node(r"""
const p=await preset();
for(const change of [{size:0},{amount:0},{hardness:101},{influence:256},{flow:0},{scale_x:Infinity},
 {gradient_curve:NaN},{gradient_rotation:1.23},{gradient_start_position:100},{gradient_inner:100},
 {crop_left:99,crop_right:1},{shape:'noise'},{value_profile:'conical'},{spacing:'wrong'},
 {apply_mode:'multiply'},{tip_channel:'rgb'},{mirror_horizontal:1}])
 await assert.rejects(lib.validateBrushPreset({...p,brush:{...p.brush,...change}}));
for(const change of [{id:''},{id:'../path'},{name:' '},{name:'x'.repeat(81)},{category:null},{favorite:1}])
 await assert.rejects(lib.validateBrushPreset({...p,...change}));
const future=await lib.validateBrushPreset({...p,extra:'ignored',brush:{...p.brush,noise:'ignored'}});
assert.deepEqual(future,p);
""")

    def test_custom_tip_missing_invalid_empty_and_noncanonical_rejected(self):
        run_node(r"""
const s=await custom();
for(const value of [undefined,'file:///tip.png','blob:foo','data:image/png;base64,YWJj'])
 await assert.rejects(lib.captureBrushPreset({...s,custom_tip:value},meta));
const zero={...tip,alpha:new Uint8Array(6)}, url=await tips.encodeTipDataUrl(zero);
await assert.rejects(lib.captureBrushPreset({...s,custom_tip:url,tip_channel:'alpha',tip_invert:false},meta),/empty/);
const codec=await import(@CODEC@);const field=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(255));
await assert.rejects(lib.captureBrushPreset({...s,custom_tip:field},meta),/gray\+alpha/);
""".replace("@CODEC@", json.dumps((CORE / "png_codec.js").as_uri())))

    def test_custom_tip_clear_replace_and_mutable_decoded_tip_independence(self):
        run_node(r"""
const f=fixture(),s=await custom(),a=await f.library.save(s,'A'),original=a.presets[0];
s.custom_tip=await tips.encodeTipDataUrl({...tip,luminance:new Uint8Array(6).fill(7)});
delete s.custom_tip;s.tip_invert=false;
const target=ui.createEditorSession(empty(),s);await lib.applyBrushPreset(original,target);
assert.equal(target.settings.custom_tip,original.brush.custom_tip);assert.deepEqual(target.tip,tip);
target.tip.alpha.fill(1);target.settings.tip_channel='alpha';
const reloaded=(await f.library.load()).presets[0];assert.deepEqual(reloaded,original);
await lib.applyBrushPreset(reloaded,target);assert.deepEqual(target.tip,tip);
""")

    def test_update_preserves_identity_and_metadata_replaces_exact_snapshot(self):
        run_node(r"""
const f=fixture();let result=await f.library.save(base(),'Brush','Soft');const id=result.id;
await f.library.metadata(id,{favorite:true});const changed=await custom();
result=await f.library.update(id,changed);assert.equal(result.presets.length,1);const p=result.presets[0];
assert.equal(p.id,id);assert.equal(p.name,'Brush');assert.equal(p.category,'Soft');assert.equal(p.favorite,true);
assert.deepEqual(p.brush,(await lib.captureBrushPreset(changed,meta)).brush);assert.notEqual(p.brush.size,16);
""")

    def test_rename_category_favorite_and_delete_metadata_only(self):
        run_node(r"""
const f=fixture(),session=ui.createEditorSession(empty());const a=await f.library.save(session.settings,'A');
const b=await f.library.save(session.settings,'B');const brush=a.presets[0].brush,before=JSON.stringify(session);
const r=await f.library.metadata(a.id,{name:' Renamed ',category:' Texture ',favorite:true});
assert.deepEqual(r.presets[0].brush,brush);assert.equal(r.presets[0].id,a.id);assert.equal(r.presets[0].name,'Renamed');
const d=await f.library.remove(a.id);assert.equal(d.presets.length,1);assert.equal(d.presets[0].id,b.id);
assert.equal(JSON.stringify(session),before);
""")

    def test_duplicate_safe_names_and_duplicate_new_identity(self):
        run_node(r"""
const f=fixture();const a=await f.library.save(base(),' Pencil ',' Soft ');
let r=await f.library.save(base(),'pencil','soft');assert.equal(r.presets[1].name,'pencil (2)');
r=await f.library.save(base(),'Pencil','Other');assert.equal(r.presets[2].name,'Pencil');
r=await f.library.duplicate(a.id);const copy=r.presets.at(-1);assert.notEqual(copy.id,a.id);
assert.equal(copy.name,'Pencil (3)');assert.deepEqual(copy.brush,r.presets[0].brush);
const long='a'.repeat(80);await f.library.save(base(),long);r=await f.library.save(base(),long);
assert.equal(r.presets.at(-1).name.length,80);assert.ok(r.presets.at(-1).name.endsWith(' (2)'));
""")

    def test_reload_cross_node_workflow_and_fresh_instances(self):
        run_node(r"""
const f=fixture();const a=await f.library.save(await custom(),'Custom');
const other=lib.createBrushLibrary(f.storage,()=> 'other');assert.deepEqual((await other.load()).presets,a.presets);
const exported=f.text;const restart=fixture(exported);const p=(await restart.library.load()).presets[0];
for(const target of [ui.createEditorSession(empty()),ui.createEditorSession(empty(),{size:99})]) {
 await lib.applyBrushPreset(p,target);assert.equal(target.settings.custom_tip,a.presets[0].brush.custom_tip);
 assert.deepEqual(target.codes,empty());
}
""")

    def test_corrupt_entries_are_reported_valid_kept_and_raw_preserved(self):
        run_node(r"""
const p=await preset(),bad={version:1,id:'broken',name:'broken',brush:{size:-1}};
const f=fixture(JSON.stringify({version:1,presets:[bad,p,null,{...p,id:'future',version:2}]}));
const loaded=await f.library.load();assert.equal(loaded.presets.length,1);assert.equal(loaded.warnings.length,3);
assert.ok(loaded.warnings.every(w=>w.startsWith('Preset ')));
await f.library.metadata(p.id,{favorite:true});assert.deepEqual(JSON.parse(f.text).presets.slice(1),[bad,null,{...p,id:'future',version:2}]);
""")

    def test_unknown_library_versions_and_parse_failure_never_overwritten(self):
        run_node(r"""
for(const text of ['{bad','null','[]',JSON.stringify({version:2,presets:[]}),JSON.stringify({version:1,presets:{}})]) {
 const f=fixture(text);await assert.rejects(f.library.load());await assert.rejects(f.library.save(base(),'A'));
 assert.equal(f.text,text);assert.equal(f.writes,0);
}
const p=await preset();await assert.rejects(lib.applyBrushPreset({...p,version:2},ui.createEditorSession(empty())),/version/);
""")

    def test_duplicate_ids_are_quarantined(self):
        run_node(r"""
const p=await preset(),result=await lib.loadBrushLibrary(JSON.stringify({version:1,presets:[p,{...p,name:'Duplicate'}]}));
assert.equal(result.presets.length,0);assert.equal(result.rejected.length,2);
assert.ok(result.warnings.every(w=>/Duplicate preset ID/.test(w)));
""")

    def test_canonical_serialization_stable_order_and_defaults_explicit(self):
        run_node(r"""
const a=await preset(),b=await lib.captureBrushPreset(base(),{...meta,id:'another'});
const forward=lib.serializeBrushLibrary({presets:[a,b]}),reverse=lib.serializeBrushLibrary({presets:[b,a]});
assert.equal(forward,reverse);assert.equal(lib.serializeBrushLibrary(await lib.loadBrushLibrary(forward)),forward);
assert.deepEqual(Object.keys(a.brush),lib.SNAPSHOT_KEYS);assert.equal(a.brush.value_profile,'uniform');
assert.equal(a.brush.gradient_curve,1);assert.ok(!forward.includes('timestamp'));
""")

    def test_search_category_favorites_and_stable_sort(self):
        run_node(r"""
const p=await preset(),entries=[{...p,id:'z',name:'Zulu',favorite:true},{...p,id:'b',name:'alpha',category:'Texture'},
 {...p,id:'a',name:'Alpha',category:'Texture'},{...p,id:'c',name:'Beta',category:''}];
assert.deepEqual(lib.filterBrushPresets(entries).map(p=>p.id),['z','a','b','c']);
assert.equal(lib.filterBrushPresets(entries,{search:' ALPHA '}).length,2);
assert.equal(lib.filterBrushPresets(entries,{search:'TEXTURE'}).length,2);
assert.equal(lib.filterBrushPresets(entries,{search:'nothing'}).length,0);
assert.equal(lib.filterBrushPresets(entries,{search:'texture',favorites:true}).length,0);
assert.equal(lib.filterBrushPresets(entries,{category:''})[0].id,'c');
assert.deepEqual(lib.filterBrushPresets(entries.reverse()).map(p=>p.id),['z','a','b','c']);
""")

    def test_failed_write_and_queued_mutations_do_not_publish_or_lose_entries(self):
        run_node(r"""
const f=fixture();await Promise.all([f.library.save(base(),'A'),f.library.save(base(),'B')]);
assert.equal((await f.library.load()).presets.length,2);const before=f.text;
f.fail=true;await assert.rejects(f.library.remove('id-1'),/disk full/);assert.equal(f.text,before);
f.fail=false;await f.library.metadata('id-2',{favorite:true});assert.equal((await f.library.load()).presets.length,2);
""")

    def test_import_export_validation_identity_and_embedded_tip(self):
        run_node(r"""
const f=fixture(),p=await lib.captureBrushPreset(await custom(),meta),text=JSON.stringify(p);
assert.ok(!text.includes('file:')&&!text.includes('blob:'));let a=await f.library.importPreset(text),b=await f.library.importPreset(text);
assert.notEqual(a.id,b.id);assert.equal(b.presets[1].name,'Soft (2)');assert.deepEqual(a.presets[0].brush,p.brush);
const before=f.text;
for(const value of ['{bad',JSON.stringify({...p,version:2}),JSON.stringify({...p,brush:{}})])
 await assert.rejects(f.library.importPreset(value));
assert.equal(f.text,before);
""")

    def test_thumbnail_builtin_custom_gradient_and_cache_invalidation(self):
        run_node(r"""
const thumb=lib.createPresetThumbnails(),p=await preset({size:32,value_profile:'linear'}),a=await thumb(p);
assert.equal(a.pixels.length,48*48*4);assert.ok(a.pixels.some((v,i)=>i%4===3&&v>0));
const targets=new Set([...a.pixels].filter((v,i)=>i%4===0&&a.pixels[i+3]>0));assert.ok(targets.size>10);
assert.equal(await thumb({...p,name:'Rename',favorite:true,category:'new'}),a);
const changed=await preset({size:32,value_profile:'linear',gradient_angle:90});const b=await thumb(changed);
assert.notEqual(a,b);assert.notDeepEqual(a.pixels,b.pixels);
const c=await thumb(await lib.captureBrushPreset(await custom(),meta));assert.ok(c.pixels.some((v,i)=>i%4===3&&v>0));
for(const shape of ['disk','square','diamond'])assert.ok((await thumb(await preset({shape}))).pixels.some(v=>v));
""")

    def test_ui_management_and_apply_never_change_field_or_history(self):
        run_node(EDITOR + r"""
await library();field('Preset name').value='First';field('Preset category').value='Texture';
await act('Save As New');const id=JSON.parse(f.text).presets[0].id;neutral();
field('Preset name').value='Renamed';field('Preset category').value='Soft';await act('Rename / Set Category');
assert.equal(JSON.parse(f.text).presets[0].id,id);await act('Duplicate');neutral();
await act('Delete');assert.equal(JSON.parse(f.text).presets.length,1);neutral();
press('Renamed · Soft');editor.session.settings.size=43;await act('Update from Current Brush');
editor.session.settings.size=12;editor.session.settings.tool='restore';await act('Apply');
assert.equal(editor.session.settings.size,43);assert.equal(editor.session.settings.tool,'restore');neutral();
press('Close Library');press('Done');await settle();assert.ok(done);assert.equal(done.settings.size,43);
assert.ok(!JSON.stringify(done.settings).includes('presets'));assert.deepEqual(done.codes,empty());
""")

    def test_ui_text_shortcuts_and_filters_do_not_edit_brush(self):
        run_node(EDITOR + r"""
await library();field('Preset name').value='Alpha';field('Preset category').value='Texture';await act('Save As New');
const before=JSON.stringify(editor.session.settings);
for(const key of ['b','e','f','1',' ','[','Delete','z','c']) {
 const e=fire(window,'keydown',{key,target:field('Preset name'),ctrlKey:key==='z'||key==='c'});
 assert.equal(e.stopped,true);assert.equal(e.prevented,undefined);
}
assert.equal(JSON.stringify(editor.session.settings),before);neutral();
field('Search').value='TEXTURE';fire(field('Search'),'input');assert.ok(button('Alpha · Texture'));
press('Favorites only');assert.ok(!button('Alpha · Texture'));press('Favorites only');
field('Favorite Alpha').click();await idle();press('Favorites only');assert.ok(button('Alpha · Texture'));
field('Search').value='missing';fire(field('Search'),'input');assert.ok(!button('Alpha · Texture'));
const event=fire(window,'keydown',{key:'Escape'});assert.equal(event.prevented,true);assert.ok(!status());
assert.equal(cancelled,0);editor.cancel();
""")

    def test_ui_clear_and_reset_keep_library_then_custom_apply_restores(self):
        run_node(EDITOR + r"""
editor.cancel();editor=open(await custom());dom.flush();await until(()=>editor.session.tip);dom.flush();
await library();field('Preset name').value='Custom';await act('Save As New');const saved=f.text;press('Close Library');
press('Clear Custom Tip');assert.ok(!editor.session.settings.custom_tip);assert.equal(f.text,saved);
press('Reset Brush');assert.equal(f.text,saved);neutral();
await library();press('Custom · Uncategorized');await act('Apply');assert.deepEqual(editor.session.tip,tip);
assert.equal(editor.session.settings.value_profile,'radial');neutral();press('Close Library');editor.cancel();
assert.equal(f.text,saved);
""")

    def test_ui_invalid_preset_load_and_failed_save_remain_usable(self):
        run_node(EDITOR + r"""
await f.storage.write(JSON.stringify({version:1,presets:[{version:2}]}));await library();assert.match(status().textContent,/version/);
field('Preset name').value='Valid';await act('Save As New');assert.ok(button('Valid · Uncategorized'));
const before=f.text;f.fail=true;await act('Delete');assert.match(status().textContent,/disk full/);assert.equal(f.text,before);
assert.ok(button('Valid · Uncategorized'));f.fail=false;await act('Delete');neutral();press('Close Library');editor.cancel();
""")

    def test_ui_save_custom_without_tip_fails_cleanly(self):
        run_node(EDITOR + r"""
editor.session.settings.shape='custom';await library();field('Preset name').value='Broken';await act('Save As New');
assert.match(status().textContent,/embedded tip/);assert.equal(f.writes,0);neutral();press('Close Library');editor.cancel();
""")

    def test_no_engine_edits_or_workflow_library_hooks(self):
        source = (CORE / "brush_library.js").read_text(encoding="utf-8")
        self.assertNotIn("new Stroke", source)
        self.assertNotIn("localStorage", source)
        self.assertNotIn("node.properties", source)
        adapter = (ROOT / "web/js/painted_field_node.js").read_text(encoding="utf-8")
        self.assertIn('import("../../../scripts/api.js")', adapter)
        self.assertIn("stringify: false", adapter)
        self.assertNotIn("brushLibrary", adapter[adapter.index("onDone: async"):])

    def test_adapter_userdata_contract_lazy_errors_and_cross_node_workflow_separation(self):
        source = (ROOT / "web/js/painted_field_node.js").read_text(encoding="utf-8")
        source = source.replace('import {app} from "../../../scripts/app.js";', 'const app=globalThis.testApp;')
        source = source.replace('import("../../../scripts/api.js")', 'globalThis.loadApi()')
        source = source.replace('import("./field_editor/editor_ui.js")', 'Promise.resolve(globalThis.testUi)')
        for name in ("png_codec", "brush_library"):
            source = source.replace(f'import("./field_editor/{name}.js")',
                                    f'import({json.dumps((CORE / (name + ".js")).as_uri())})')
        encoded = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        run_node(r"""
installDOM();let extension,opened,apiLoads=0,stored=null,writes=0,graphWrites=0,readStatus=200,writeStatus=200;
const paths=[],api={getUserData:async file=>{paths.push(file);return {status:stored===null?404:readStatus,
 ok:readStatus===200,text:async()=>stored};},storeUserData:async(file,text,options)=>{
 assert.deepEqual(options,{overwrite:true,stringify:false,throwOnError:true});assert.equal(file,lib.LIBRARY_FILE);
 assert.equal(typeof text,'string');if(writeStatus===200){stored=text;writes++;}return {status:writeStatus,ok:writeStatus===200};}};
globalThis.loadApi=async()=>{apiLoads++;return {api};};globalThis.testUi={openInfluenceFieldEditor:o=>opened=o};
let activeNode;const graph={getNodeById:id=>id===activeNode?.id?activeNode:null};
globalThis.testApp={registerExtension:e=>extension=e,ui:{settings:{getSettingValue:()=>false,setSettingValue:()=>assert.fail()}},
 canvas:{graph,emitBeforeChange:()=>graphWrites++,emitAfterChange:()=>graphWrites++}};
await import(@ADAPTER@);assert.equal(apiLoads,0);
const makeNode=id=>{const node={id,graph,properties:{fieldEditor:ui.editorSettings(base())},setDirtyCanvas:()=>graphWrites++,
 addDOMWidget(name,type,element,options){const w={name,type};Object.defineProperty(w,'value',{get:options.getValue,
 set:value=>{graphWrites++;options.setValue(value);}});this.widgets=[w];return w;}};
 extension.getCustomWidgets().CONDITIONING_LAYERS_PAINTED_FIELD(node,'field',['STRING',{default:''}]);return node;};
activeNode=makeNode(1);await extension.getNodeMenuItems(activeNode)[0].callback();assert.equal(apiLoads,0);
const original=JSON.stringify(activeNode.properties),first=await opened.host.getBrushLibrary();assert.equal(apiLoads,1);
const a=await first.save(base(),'A');await first.metadata(a.id,{favorite:true,name:'Renamed',category:'Soft'});
await first.duplicate(a.id);await first.update(a.id,{...base(),size:37});await first.remove(a.id);
assert.equal(graphWrites,0);assert.equal(activeNode.widgets[0].value,'');assert.equal(JSON.stringify(activeNode.properties),original);
opened.onCancel();activeNode=makeNode(2);await extension.getNodeMenuItems(activeNode)[0].callback();
const second=await opened.host.getBrushLibrary();assert.equal(first,second);assert.equal((await second.load()).presets.length,1);
assert.ok(paths.every(p=>p===lib.LIBRARY_FILE));assert.equal(apiLoads,1);
const before=stored;writeStatus=413;await assert.rejects(second.save(base(),'Large'),/413/);assert.equal(stored,before);
writeStatus=200;readStatus=403;await assert.rejects(second.load(),/403/);assert.equal(stored,before);
readStatus=200;await opened.onDone(empty(),ui.editorSettings(base()));assert.equal(graphWrites,0);
assert.ok(!JSON.stringify(activeNode.properties).includes('presets'));assert.ok(writes>=5);
""".replace("@ADAPTER@", json.dumps(encoded)))

    def test_ui_import_export_and_delete_confirmation(self):
        run_node(EDITOR + r"""
await library();let exported,revoked=0;URL.createObjectURL=blob=>{exported=blob;return 'blob:test';};URL.revokeObjectURL=()=>revoked++;
const p=await lib.captureBrushPreset(await custom(),meta),picker=all().find(e=>e.accept==='.json,application/json');
picker.files=[{text:async()=>JSON.stringify(p)}];fire(picker,'change');await idle();
assert.equal(JSON.parse(f.text).presets.length,1);await act('Export Preset JSON');
const exportedPreset=JSON.parse(await exported.text());assert.deepEqual(exportedPreset.brush,p.brush);
await until(()=>revoked===1);const before=f.text;window.confirm=()=>false;press('Delete');assert.equal(f.text,before);
picker.files=[{text:async()=>JSON.stringify({...p,version:2})}];fire(picker,'change');await idle();
assert.match(status().textContent,/version/);assert.equal(f.text,before);neutral();press('Close Library');editor.cancel();
""")


if __name__ == "__main__":
    unittest.main()
