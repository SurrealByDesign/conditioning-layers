"""E8 exact, fenced offline checks; no browser or host qualification.

FieldToolsOracle is transcribed from E8 §§7–10,16–18,25–27. It never calls
product JavaScript. Fraction overlaps use destination coordinates, independently
of the product's separable integer implementation. Comparisons stop at the first
differing cell; no long-sequence difflib comparisons.
"""
from fractions import Fraction as Q
import hashlib
import itertools
import json
from pathlib import Path
import random
import re
import struct
import unittest
import zlib

from test_field_editor_custom_tip import (
    run_node as retained_node, EDITOR, CORE, first_difference, png, b64,
    expected_planes, chunk, E1_GOLDEN,
)

PRELUDE = "\n".join(
    f"const {name} = await import({json.dumps((CORE / file).as_uri())});"
    for name, file in [("sel", "selection.js"), ("imports", "field_import.js"),
                       ("importUI", "field_import_ui.js"), ("lib", "brush_library.js")]
) + r"""
const eq = (a,b,label='codes') => {
  assert.equal(a.length,b.length,label+' length');
  for(let i=0;i<a.length;i++) if(a[i]!==b[i]) assert.fail(`${label} cell ${i}: ${a[i]} != ${b[i]}`);
};
const sourceOf = d => ({width:d.w,height:d.h,luminance:bytesOf(d.y),alpha:bytesOf(d.a)});
const count = s => s === null ? 0 : s.reduce((n,v)=>n+v,0);
const rect = (x0=10,y0=20,x1=40,y1=30) => sel.rectangleSelection({x:x0,y:y0},{x:x1,y:y1});
const ellipse = () => sel.ellipseSelection({x:5,y:5},{x:36,y:24});
const encode = a => Buffer.from(a).toString('base64');
"""

UI = EDITOR + r"""
const key = (key, extra={}) => {fire(window,'keydown',{key,...extra});dom.flush();};
const drag = (x0,y0,x1,y1,extra={}) => {pointer('pointerdown',x0,y0,extra);pointer('pointermove',x1,y1,extra);pointer('pointerup',x1,y1,extra);dom.flush();};
const maskPicker = () => all().find(e=>e.accept==='image/png');
const maskDialog = () => find('cl-mask-import');
const maskFile = async text => {
  maskPicker().files=[fileOf(text)];fire(maskPicker(),'change');
  await until(()=>maskDialog() || error().startsWith('Cannot import the mask:'),'mask dialog');
};
const pixels = e => Uint8Array.from({length:16384},(_,i)=>e.pixels[i*4]);
const maskPress = label => pressIn(maskDialog(),label);
"""


def run_node(body, data=None):
    return retained_node(PRELUDE + body, data)


def run_editor(body, data=None):
    return run_node(UI + body, data)


class FieldToolsOracle:
    @staticmethod
    def rectangle(a, b):
        ax, ay = [min(127, max(0, int(v // 1))) for v in a]
        bx, by = [min(127, max(0, int(v // 1))) for v in b]
        return {(x, y) for y in range(min(ay, by), max(ay, by) + 1)
                for x in range(min(ax, bx), max(ax, bx) + 1)}

    @staticmethod
    def ellipse(a, b, rational=False):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if rational:
            cx, cy, rx, ry = Q(x0 + x1 + 1, 2), Q(y0 + y1 + 1, 2), Q(w, 2), Q(h, 2)
            return {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
                    if ((Q(2*x+1, 2) - cx)/rx)**2 + ((Q(2*y+1, 2) - cy)/ry)**2 <= 1}
        return {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
                if (2*x + 1 - 2*x0 - w)**2 * h*h + (2*y + 1 - 2*y0 - h)**2 * w*w <= w*w*h*h}

    @staticmethod
    def mask(cells):
        out = bytearray(16384)
        for x, y in cells:
            out[y * 128 + x] = 1
        return out

    @staticmethod
    def outline(cells):
        horizontal, vertical = set(), set()
        for x, y in cells:
            for edge in [(x, y), (x, y+1)]:
                horizontal.symmetric_difference_update([edge])
            for edge in [(x, y), (x+1, y)]:
                vertical.symmetric_difference_update([edge])
        result = []
        for edges, swapped in [(horizontal, False), (vertical, True)]:
            lines = {}
            for x, y in edges:
                line, pos = (x, y) if swapped else (y, x)
                lines.setdefault(line, []).append(pos)
            for line, positions in sorted(lines.items()):
                positions.sort()
                start = end = positions[0]
                for pos in positions[1:] + [1000]:
                    if pos == end + 1:
                        end = pos
                        continue
                    result.append(f"M{line} {start}V{end+1}" if swapped else f"M{start} {line}H{end+1}")
                    start = end = pos
        return " ".join(result)

    @staticmethod
    def placement(w, h, mode):
        x0 = y0 = ox = oy = 0
        sw, sh, rw, rh = w, h, 128, 128
        if mode == "fit":
            if w >= h:
                rh = max(1, (256*h+w)//(2*w))
                oy = (128-rh)//2
            else:
                rw = max(1, (256*w+h)//(2*h))
                ox = (128-rw)//2
        elif mode == "fill":
            sw = sh = min(w, h)
            x0, y0 = (w-sw)//2, (h-sh)//2
        return dict(x0=x0, y0=y0, sw=sw, sh=sh, ox=ox, oy=oy, rw=rw, rh=rh)

    @classmethod
    def averages(cls, w, h, samples, mode):
        g = cls.placement(w, h, mode)
        sw, sh, rw, rh = [g[k] for k in ("sw", "sh", "rw", "rh")]
        def overlaps(size, target):
            axis = [[] for _ in range(target)]
            for i in range(size):
                low, high = Q(i*target, size), Q((i+1)*target, size)
                for j in range(low.numerator//low.denominator, min(target, -(-high.numerator//high.denominator))):
                    weight = min(high, j+1) - max(low, j)
                    if weight:
                        axis[j].append((i, weight))
            return axis
        xs, ys = overlaps(sw, rw), overlaps(sh, rh)
        out = [None] * 16384
        for y in range(rh):
            for x in range(rw):
                out[(g['oy']+y)*128+g['ox']+x] = sum(
                    a*b*samples[(g['y0']+r)*w+g['x0']+i] for i, a in xs[x] for r, b in ys[y])
        return out

    @staticmethod
    def quantize(averages, invert=False, binary=False):
        out = bytearray(16384)
        for i, value in enumerate(averages):
            if value is None:
                continue
            if invert:
                value = 255-value
            code = (value + Q(1, 2)).numerator // (value + Q(1, 2)).denominator
            out[i] = (255 if value >= Q(255, 2) else 0) if binary else code
        return out


def source(w, h, luminance, alpha=None):
    return dict(w=w, h=h, y=b64(bytes(luminance)), a=b64(bytes(alpha if alpha is not None else [255]*(w*h))))


class FieldToolsTests(unittest.TestCase):
    def test_rectangle_exact_random_directions_and_clamping(self):
        rng = random.Random(8003)
        cases = [[a, b] for a, b in itertools.product([(10, 20), (40, 30), (10, 30), (40, 20)], repeat=2)]
        cases += [[(rng.randrange(-100, 220)/2, rng.randrange(-100, 220)/2),
                   (rng.randrange(-100, 440)/2, rng.randrange(-100, 440)/2)] for _ in range(200)]
        actual = run_node("console.log(JSON.stringify(data.map(([a,b])=>encode(sel.rectangleSelection({x:a[0],y:a[1]},{x:b[0],y:b[1]})))));", cases)
        for case, encoded in zip(cases, actual):
            self.assertEqual(encoded, b64(FieldToolsOracle.mask(FieldToolsOracle.rectangle(*case))), case)
        self.assertEqual(len(FieldToolsOracle.rectangle((10, 20), (40, 30))), 341)

    def test_ellipse_all_sizes_hashes_and_seeded_rational_placements(self):
        actual = run_node(r"""
const {createHash}=await import('node:crypto');const hashes=[];
for(let h=1;h<=128;h++)for(let w=1;w<=128;w++) hashes.push(createHash('sha256').update(sel.ellipseSelection({x:0,y:0},{x:w-1,y:h-1})).digest('hex'));
console.log(JSON.stringify(hashes));
""")
        for index, (h, w) in enumerate(itertools.product(range(1, 129), repeat=2)):
            mask = FieldToolsOracle.mask(FieldToolsOracle.ellipse((0, 0), (w-1, h-1)))
            self.assertEqual(actual[index], hashlib.sha256(mask).hexdigest(), (w, h))
        rng = random.Random(8004)
        cases = []
        for _ in range(200):
            x, y = rng.randrange(100), rng.randrange(100)
            cases.append([(x, y), (x+rng.randrange(1, 28), y+rng.randrange(1, 28))])
        actual = run_node("console.log(JSON.stringify(data.map(([a,b])=>encode(sel.ellipseSelection({x:a[0],y:a[1]},{x:b[0],y:b[1]})))));", cases)
        for case, encoded in zip(cases, actual):
            rational = FieldToolsOracle.ellipse(*case, rational=True)
            self.assertEqual(rational, FieldToolsOracle.ellipse(*case))
            self.assertEqual(encoded, b64(FieldToolsOracle.mask(rational)))

    def test_ellipse_disk_crosscheck_all_odd_even_sizes(self):
        run_node(r"""
for(let n=1;n<=128;n++) {
 const s=sel.ellipseSelection({x:0,y:0},{x:n-1,y:n-1});
 const p=engine.stampPreview(128,128,{...brush,size:n},n/2,n/2);
 eq(s,p.coverage.map(v=>Number(v>0)),`disk ${n}`);assert.ok(count(s)>0);
 if(n<=6)assert.equal(count(s),[1,4,9,12,21,32][n-1]);
 if(n===128)assert.equal(count(s),12892);
}
for(let n=1;n<=128;n++)assert.equal(count(sel.ellipseSelection({x:0,y:0},{x:0,y:n-1})),n);
""")

    def test_modes_commands_random_set_algebra_and_refusals(self):
        rng = random.Random(8005)
        cases, expected = [], []
        for _ in range(200):
            current = set()
            actions = []
            for _ in range(6):
                a, b = [(rng.randrange(128), rng.randrange(128)) for _ in range(2)]
                shape, mode = rng.choice(["rectangle", "ellipse"]), rng.choice(["replace", "add", "subtract"])
                region = getattr(FieldToolsOracle, shape)(a, b)
                new = region if mode == "replace" else current | region if mode == "add" else current - region
                if new:
                    current = new
                actions.append([a, b, shape, mode])
            cases.append(actions)
            expected.append(b64(FieldToolsOracle.mask(current)) if current else None)
        actual = run_node(r"""
assert.equal(sel.combineSelection(null,rect(),'subtract'),null);
assert.equal(sel.invertSelection(sel.selectAll()),null);
eq(sel.invertSelection(null),sel.selectAll());assert.equal(count(sel.selectAll()),16384);
console.log(JSON.stringify(data.map(actions=>{let s=null;
 for(const [a,b,shape,mode] of actions){const before=s?.slice();const next=sel.combineSelection(s,sel[shape+'Selection']({x:a[0],y:a[1]},{x:b[0],y:b[1]}),mode);
 if(before)eq(s,before,'immutable');if(next){assert.notEqual(next,s);s=next;}}
 if(s && count(s)<16384)eq(sel.invertSelection(sel.invertSelection(s)),s);
 return s===null?null:encode(s);
})));
""", cases)
        self.assertEqual(actual, expected)

    def test_outline_exact_independent_edges(self):
        rng = random.Random(8007)
        s2 = FieldToolsOracle.rectangle((10, 20), (40, 30))
        shapes = [{(3, 5)}, s2, FieldToolsOracle.ellipse((5, 5), (36, 24)) - FieldToolsOracle.ellipse((13, 10), (28, 19)),
                  FieldToolsOracle.rectangle((0, 0), (127, 127))]
        shapes.append(shapes[3] - s2)
        shapes += [{(rng.randrange(128), rng.randrange(128)) for _ in range(600)} for _ in range(20)]
        actual = run_node("assert.equal(view.selectionOutlinePath(null),''); console.log(JSON.stringify(data.map(s=>view.selectionOutlinePath(bytesOf(s)))));",
                          [b64(FieldToolsOracle.mask(s)) for s in shapes])
        for s, path in zip(shapes, actual):
            self.assertEqual(path, FieldToolsOracle.outline(s))

    def test_clipping_all_brush_variants_copy_and_validation(self):
        run_node(r"""
const before=Uint8Array.from({length:16384},(_,i)=>(i*71+13)&255),initial=before.map(v=>255-v),selection=ellipse();
const tip={width:2,height:2,luminance:Uint8Array.of(1,128,200,255),alpha:Uint8Array.of(255,64,128,255)};
const variants=[{}, {tool:'erase'},{tool:'restore'},{build_up:true,flow:30},{apply_mode:'raise_only'},
 {apply_mode:'lower_only'},{shape:'square'},{shape:'diamond'},{shape:'custom',tip},
 {shape:'procedural',procedural_type:'scatter'},{shape:'procedural',procedural_type:'noise'},
 ...['linear','radial','square'].map(value_profile=>({value_profile,gradient_start:11,gradient_end:231}))];
for(const extra of variants)for(const selected of [null,selection,sel.selectAll()]){
 const b={...brush,size:33,hardness:50,amount:73,...extra};
 const plain=new engine.Stroke(before,128,128,b,8,8,initial),clipped=new engine.Stroke(before,128,128,b,8,8,initial,selected);
 for(const [x,y] of [[12,12],[45,24],[18,14]]){plain.add(x,y);clipped.add(x,y);}
 eq(clipped.result(),engine.withinSelection(before,plain.result(),selected));eq(clipped.coverage,plain.coverage);
 if(plain.targets)eq(clipped.targets,plain.targets);assert.equal(clipped.target,plain.target);
}
const copy=selection.slice(),stroke=new engine.Stroke(before,128,128,brush,20,15,null,copy),expected=stroke.result();copy.fill(0);eq(stroke.result(),expected);
for(const bad of [[],new Uint8Array(3),new Uint8Array(16384).fill(2)])assert.throws(()=>new engine.Stroke(before,128,128,brush,1,1,null,bad),/Invalid selection/);
""")

    def test_value_tools_history_and_no_selection_identity(self):
        run_node(r"""
for(const selection of [null,rect(),ellipse(),sel.selectAll()])for(const name of ['clear','fill','invert']){
 const before=Uint8Array.from({length:16384},(_,i)=>(i*37)&255),s=ui.createEditorSession(before,{influence:73,value_profile:'linear'});
 s.selection=selection;s.operation(name);eq(s.codes,before.map((v,i)=>selection!==null&&!selection[i]?v:name==='clear'?0:name==='fill'?73:255-v));
 assert.equal(s.selection,selection);assert.equal(s.history.undoEntries.length,1);assert.equal(s.history.undoEntries[0].label,name);
 if(name!=='invert'){s.operation(name);assert.equal(s.history.undoEntries.length,1);}
 s.undo();eq(s.codes,before);assert.equal(s.selection,selection);s.redo();assert.equal(s.selection,selection);
}
const a=empty(),b=empty();assert.equal(engine.withinSelection(a,b,null),b);
const s=ui.createEditorSession(a,{});s.operation('clear');assert.equal(s.history.undoEntries.length,0);
""")

    def test_spatial_exact_permutations_identities_and_policy(self):
        run_node(r"""
let seed=80012;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed&255;};
const fields=[Uint8Array.from({length:16384},(_,i)=>2*(i%128)),Uint8Array.from({length:16384},(_,i)=>2*Math.floor(i/128)),...Array.from({length:3},()=>Uint8Array.from({length:16384},random))];
for(const before of fields){
 for(const [j,name] of engine.FIELD_TRANSFORMS.entries()){
  const actual=engine.transformField(before,name),expected=empty();
  for(let y=0;y<128;y++)for(let x=0;x<128;x++){
   const dx=x+.5-64,dy=y+.5-64;
   const [sx,sy]=j===0?[-dx,dy]:j===1?[dx,-dy]:j===2?[dy,-dx]:[-dy,dx];
   expected[y*128+x]=before[Math.floor(sy+64)*128+Math.floor(sx+64)];
  }eq(actual,expected,name);
  let roundtrip=before;for(let k=0;k<(j<2?2:4);k++)roundtrip=engine.transformField(roundtrip,name);eq(roundtrip,before);
  const s=ui.createEditorSession(before,{});s.transform(name);eq(s.codes,actual);
  const changed=!engine.sameCodes(actual,before);assert.equal(s.history.undoEntries.length,Number(changed));
  if(changed)assert.equal(s.history.undoEntries[0].label,['Flip Horizontal','Flip Vertical','Rotate 90° CW','Rotate 90° CCW'][j]);
  s.undo();eq(s.codes,before);
 }
 eq(engine.transformField(engine.transformField(before,'rotate_cw'),'rotate_ccw'),before);
 eq(engine.transformField(engine.transformField(before,'rotate_cw'),'rotate_cw'),engine.transformField(engine.transformField(before,'flip_horizontal'),'flip_vertical'));
}
for(const selection of [rect(),sel.selectAll()]){const s=ui.createEditorSession(fields[0],{});s.selection=selection;
 for(const name of engine.FIELD_TRANSFORMS)assert.throws(()=>s.transform(name),{message:'Clear the selection to flip or rotate the whole field.'});
 eq(s.codes,fields[0]);assert.equal(s.selection,selection);assert.equal(s.history.undoEntries.length,0);}
const s=ui.createEditorSession(empty(),{});for(const name of engine.FIELD_TRANSFORMS)s.transform(name);assert.equal(s.history.undoEntries.length,0);
assert.throws(()=>engine.transformField(empty(),'unknown'));
""")

    def test_selection_lifetime_settings_reset_and_library_exclusion(self):
        run_editor(r"""
assert.equal(session().selection,null);assert.equal(session().selectTool,null);assert.equal(session().selectionMode,'replace');
const stored=ui.editorSettings(settings()),initial=session().codes.slice();
const capture=()=>lib.captureBrushPreset(settings(),{id:'e8',name:'E8 exclusion'});const preset=await capture();
press('Rectangle Select');drag(10.1,20.1,40.9,30.9);const selection=session().selection;
assert.equal(count(selection),341);press('Add');
assert.deepEqual(await capture(),preset);assert.deepEqual(ui.editorSettings(settings()),stored);
press('Restore');press('Ellipse Select');press('Reset Brush');
assert.equal(settings().tool,'paint');assert.equal(session().selectTool,'ellipse');assert.equal(session().selection,selection);
press('Reset View');press('Heat View');press('Grid (at ≥8 px/cell)');assert.equal(session().selection,selection);
const prepared=await lib.prepareBrushPreset(preset);lib.applyPreparedBrush(prepared,session());
assert.equal(session().selection,selection);assert.equal(session().selectTool,'ellipse');
press('Clear Custom Tip');assert.equal(session().selection,selection);assert.equal(session().selectTool,'ellipse');
assert.equal(session().history.undoEntries.length,0);eq(session().codes,initial);
press('Done');await settle();assert.equal(session().selection,null);assert.deepEqual(result.settings,stored);
controller=open(result.codes,result.settings);dom.flush();assert.equal(session().selection,null);assert.equal(session().selectionMode,'replace');assert.equal(session().selectTool,null);
let prompts=0;host.confirmDiscard=()=>{prompts++;return false;};press('Select All');controller.cancel();assert.equal(prompts,0);assert.equal(session().selection,null);
controller=open();dom.flush();assert.equal(session().selection,null);
""")

    def test_gestures_modes_modifiers_and_interruptions(self):
        run_editor(r"""
const initial=session().codes.slice(),settingsBefore=JSON.stringify(settings());press('Rectangle Select');
assert.equal(settings().tool,'paint');assert.equal(JSON.stringify(settings()),settingsBefore);
drag(-1,2,20,30);assert.equal(session().selection,null);
drag(10.1,20.1,40.9,30.9,{altKey:true,shiftKey:true,ctrlKey:true});eq(session().selection,rect());
assert.equal(JSON.stringify(settings()),settingsBefore);eq(session().codes,initial);assert.equal(session().history.undoEntries.length,0);
const first=session().selection;press('Subtract');drag(0,0,127,127);assert.equal(session().selection,first);
assert.equal(error(),'That would leave no cells selected, so the selection is unchanged.');
press('Replace');click(3.8,5.2);eq(session().selection,rect(3,5,3,5));assert.equal(error(),'');
press('Add');drag(2,5,3,5);assert.equal(count(session().selection),2);
press('Subtract');click(2,5);assert.equal(count(session().selection),1);
press('Clear Selection');press('Subtract');click(2,5);assert.equal(session().selection,null);assert.ok(error());
press('Select All');assert.equal(error(),'');press('Invert Selection');assert.equal(count(session().selection),16384);assert.ok(error());
find('error').textContent='another owner';press('Clear Selection');assert.equal(error(),'another owner');
press('Invert Selection');assert.equal(count(session().selection),16384);press('Replace');
for(const event of ['pointercancel','lostpointercapture','blur','Escape']){
 const before=session().selection;pointer('pointerdown',5,5);pointer('pointermove',20,20);dom.flush();
 assert.equal(find('selection-candidate').style.display,'');
 const transform=canvas().style.transform;fire(find('viewport'),'wheel',{clientX:88,clientY:88,deltaY:-1});dom.flush();assert.equal(canvas().style.transform,transform);
 if(event==='Escape')key('Escape');else if(event==='blur')fire(window,'blur');else pointer(event,20,20);
 pointer('pointerup',20,20);dom.flush();assert.equal(session().selection,before);assert.equal(find('selection-candidate').style.display,'none');assert.ok(find('cl-field-editor'));
}
drag(10,10,12,12,{pointerType:'pen'});eq(session().selection,rect(10,10,12,12));const before=session().selection;
for(const tool of ['Paint','Erase','Restore']){press(tool);assert.equal(session().selectTool,null);press('Rectangle Select');}
key('b');assert.equal(session().selectTool,null);press('Ellipse Select');key('e');assert.equal(session().selectTool,null);
press('Rectangle Select');const beforePan=canvas().style.transform;drag(10,10,12,12,{button:1});assert.notEqual(canvas().style.transform,beforePan);assert.equal(session().selection,before);
key(' ');const pan=canvas().style.transform;drag(10,10,14,14);assert.notEqual(canvas().style.transform,pan);fire(window,'keyup',{key:' '});
assert.equal(session().history.undoEntries.length,0);key('Escape');assert.equal(find('cl-field-editor'),undefined);
""")

    def _check_shortcut_cancellation(self, shape, shortcut, target):
        run_editor(r"""
// Seed both history directions; cancellation must preserve their entries too.
press('Fill with Influence');press('Invert');press('Undo');
for(const prior of [false,true]){
 press('Clear Selection');
 if(prior){press('Rectangle Select');drag(2,3,4,5);}
 const committed=session().selection,mask=committed?.slice();
 const states=[];
 for(const route of ['keyboard','button']){
  press(data.shape);
  const before=session().codes.slice(),undo=session().history.undoEntries.slice(),redo=session().history.redoEntries.slice();
  const preferences=JSON.stringify(writes);
  pointer('pointerdown',10,20);pointer('pointermove',40,30);dom.flush();
  assert.equal(find('selection-candidate').style.display,'');
  if(route==='keyboard')key(data.shortcut);else press(data.target);
  const unchanged=()=>{
   assert.equal(session().selection,committed);
   if(mask)eq(session().selection,mask);
   eq(session().codes,before);
   assert.deepEqual(session().history.undoEntries,undo);assert.deepEqual(session().history.redoEntries,redo);
   assert.equal(result,undefined);assert.equal(cancelled,0);assert.equal(JSON.stringify(writes),preferences);
   assert.equal(find('selection-candidate').style.display,'none');
   assert.equal(find('viewport').captured,null);
   assert.equal(session().selectTool,null);assert.equal(settings().tool,data.target.toLowerCase());
   assert.equal(button(data.target).attributes['aria-pressed'],'true');
  };
  unchanged();
  pointer('pointermove',70,80);pointer('pointerup',70,80);dom.flush();unchanged();
  states.push({tool:settings().tool,selectTool:session().selectTool,selection:session().selection,codes:session().codes.slice()});
 }
 assert.deepEqual(states[0],states[1]);
}
""", {"shape": shape, "shortcut": shortcut, "target": target})

    def test_rectangle_drag_b_cancels_before_release(self):
        self._check_shortcut_cancellation("Rectangle Select", "b", "Paint")

    def test_ellipse_drag_b_cancels_before_release(self):
        self._check_shortcut_cancellation("Ellipse Select", "B", "Paint")

    def test_erase_shortcut_matches_ui_cancellation(self):
        self._check_shortcut_cancellation("Rectangle Select", "e", "Erase")

    def test_tool_shortcuts_keep_input_and_stroke_guards(self):
        run_editor(r"""
press('Rectangle Select');
const numeric=input('Size (cells)');fire(numeric,'pointerdown');fire(numeric,'pointerup');
assert.equal(numeric.readOnly,false);
pointer('pointerdown',10,20);pointer('pointermove',40,30);dom.flush();
for(const k of ['b','e']){
 const event=fire(window,'keydown',{key:k,target:numeric});dom.flush();
 assert.ok(!event.prevented);assert.equal(session().selectTool,'rectangle');
 assert.equal(find('selection-candidate').style.display,'');
}
for(const extra of [{ctrlKey:true},{metaKey:true}]){
 key('b',extra);key('e',extra);assert.equal(session().selectTool,'rectangle');
}
key('Escape');assert.equal(session().selection,null);
press('Paint');pointer('pointerdown',30,30);key('e');assert.equal(settings().tool,'paint');
pointer('pointerup',30,30);dom.flush();assert.equal(session().history.undoEntries.length,1);
// The retained editable library fields own their keyboard events.
host.getBrushLibrary=async()=>({load:async()=>({presets:[],warnings:[]})});
press('Brush Library…');await until(()=>find('cl-brush-library'),'library');
for(const label of ['Search','Preset name','Preset category']){
 const field=input(label);
 assert.ok(field,label);
 for(const k of ['b','e']){
  const event=fire(window,'keydown',{key:k,target:field});dom.flush();
  assert.ok(!event.prevented);assert.equal(settings().tool,'paint');
 }
}
""")

    def test_tool_switch_cancels_unfinished_selection(self):
        run_editor(r"""
for(const shape of ['Rectangle Select','Ellipse Select']){
 for(const target of ['Paint','Erase','Restore',shape==='Rectangle Select'?'Ellipse Select':'Rectangle Select']){
  for(const committed of [null,rect(2,3,4,5)]){
   press(shape);session().selection=committed;
   const before=session().codes.slice(),undo=session().history.undoEntries.slice(),redo=session().history.redoEntries.slice();
   pointer('pointerdown',10,20);pointer('pointermove',40,30);dom.flush();
   assert.equal(find('selection-candidate').style.display,'');
   press(target);
   assert.equal(find('selection-candidate').style.display,'none');assert.equal(find('viewport').captured,null);
   assert.equal(session().selection,committed);
   pointer('pointermove',70,80);pointer('pointerup',70,80);dom.flush();
   assert.equal(session().selection,committed);eq(session().codes,before);
   assert.deepEqual(session().history.undoEntries,undo);assert.deepEqual(session().history.redoEntries,redo);
   assert.equal(button(target).attributes['aria-pressed'],'true');
   // The cancelled press leaves no stale gesture that could block the next one.
   press('Rectangle Select');drag(6,7,8,9);eq(session().selection,rect(6,7,8,9));
  }
 }
}
""")

    def test_wheel_zoom_during_middle_button_pan(self):
        run_editor(r"""
for(const selectionTool of [null,'Rectangle Select','Ellipse Select']){
 press('Fit');if(selectionTool)press(selectionTool);else press('Paint');
 const before=session().codes.slice(),selection=session().selection;
 pointer('pointerdown',10,10,{button:1});pointer('pointermove',12,14,{button:1});dom.flush();
 assert.equal(canvas().style.transform,'translate(16px,24px) scale(4)');
 const wheel=fire(find('viewport'),'wheel',{clientX:88,clientY:88,deltaY:-1});dom.flush();
 assert.equal(wheel.prevented,true);
 assert.equal(canvas().style.transform,`translate(${16+18*(4-4.8)}px,${24+16*(4-4.8)}px) scale(4.8)`);
 // Retained pan movement continues from the pointer-down pan origin.
 pointer('pointermove',15,18,{button:1});dom.flush();
 assert.equal(canvas().style.transform,'translate(28px,40px) scale(4.8)');
 pointer('pointerup',15,18,{button:1});dom.flush();
 eq(session().codes,before);assert.equal(session().selection,selection);assert.equal(session().history.undoEntries.length,0);
}
""")

    def test_selection_press_exact_boundary_and_clamped_release(self):
        run_editor(r"""
for(const shape of ['Rectangle Select','Ellipse Select']){
 press(shape);const before=rect(2,3,4,5);session().selection=before;
 for(const [x,y] of [[128,20],[20,128]]){
  pointer('pointerdown',x,y);dom.flush();assert.equal(find('selection-candidate').style.display,'none');
  pointer('pointermove',50,50);pointer('pointerup',50,50);dom.flush();assert.equal(session().selection,before);
 }
 click(127.999,20);eq(session().selection,rect(127,20,127,20));
 click(20,127.999);eq(session().selection,rect(20,127,20,127));
 drag(127.999,20,128,22);eq(session().selection,rect(127,20,127,22));
 click(0,0);eq(session().selection,rect(0,0,0,0));
 eq(session().codes,empty());assert.equal(session().history.undoEntries.length,0);
}
""")

    def test_vertical_only_selection_drags_both_directions(self):
        run_editor(r"""
const expected=new Uint8Array(16384);for(let y=20;y<=30;y++)expected[y*128+10]=1;
for(const shape of ['Rectangle Select','Ellipse Select'])for(const [a,b] of [[20.1,30.9],[30.9,20.1]]){
 press(shape);pointer('pointerdown',10.4,a);pointer('pointermove',10.4,b);dom.flush();
 assert.equal(find('selection-candidate').children[0].attributes.d,view.selectionOutlinePath(expected));
 pointer('pointerup',10.4,b);dom.flush();eq(session().selection,expected);
 assert.equal(count(session().selection),11);eq(session().codes,empty());assert.equal(session().history.undoEntries.length,0);
}
""")

    def test_apply_import_clears_shift_click_line_anchor(self):
        run_editor(r"""
click(20,20);assert.equal(session().history.undoEntries.length,1);
await maskFile(data.png);maskPress('Apply Import');assert.equal(session().history.undoEntries.length,2);
assert.ok(session().codes.every(v=>v===73));
const before=session().codes.slice();
const expected=new engine.Stroke(before,128,128,engineBrush(),100,100,session().initial).result();
click(100,100,{shiftKey:true});eq(session().codes,expected);
assert.equal(session().codes[60*128+60],73);assert.equal(session().history.undoEntries.length,3);
""", dict(png=b64(png(1,1,0,8,[(73,)]))))

    def test_selection_overlay_stats_alignment_and_redraw(self):
        run_editor(r"""
assert.equal(find('selection-veil').hidden,true);press('Rectangle Select');pointer('pointerdown',10.2,20.2);pointer('pointermove',40.9,30.9);dom.flush();
assert.ok(find('status').textContent.startsWith('Rectangle Select · Rectangle x 10–40 · y 20–30 · 31×11 · 341 cells · '));
pointer('pointerup',40.9,30.9);dom.flush();
const veil=find('selection-veil'),paths=find('selection-outline').children,selection=session().selection;
assert.equal(find('viewport').style.cursor,'crosshair');assert.equal(outline().style.display,'none');assert.equal(preview().hidden,true);
for(let i=0;i<16384;i++)eq(veil.pixels.slice(i*4,i*4+4),selection[i]?[0,0,0,0]:view.SELECTION_VEIL);
assert.equal(paths[0].attributes.d,view.selectionOutlinePath(selection));assert.equal(paths[1].attributes.stroke,'#ffd400');
assert.equal(paths[0].attributes['shape-rendering'],'crispEdges');
assert.ok(find('status').textContent.includes('selection 341 cells (2.1%) · x 10–40 · y 20–30 · '));
assert.ok(find('status').textContent.includes('selected · '));
assert.equal(heading('Field Tools').textContent,'Field Tools · Rectangle Select · Selection 341 cells');
assert.equal(summary().textContent,'Advanced · Rectangle Select · Selection 341 cells');
const children=find('viewport').children;
assert.deepEqual(children.map(e=>e.className??'field'),['reference','field','selection-veil','brush-preview','cell-grid','selection-outline','selection-candidate','target-cell','brush-outline']);
const veilPixels=veil.pixels;press('Heat View');press('Grid (at ≥8 px/cell)');
for(let i=0;i<5;i++){fire(find('viewport'),'wheel',{clientX:128,clientY:128,deltaY:-1});dom.flush();}
const aligned=()=>{for(const e of children.filter(e=>!['target-cell'].includes(e.className)))assert.equal(e.style.transform,canvas().style.transform);};
aligned();assert.equal(veil.pixels,veilPixels);const zoom=Number(canvas().style.transform.match(/scale\(([^)]+)\)/)[1]);
assert.equal(paths[0].attributes['stroke-width'],String(3/zoom));assert.equal(paths[1].attributes['stroke-width'],String(1/zoom));
assert.equal(paths[1].attributes['stroke-dasharray'],`${4/zoom} ${4/zoom}`);
drag(20,20,30,30,{button:1});aligned();assert.equal(veil.pixels,veilPixels);press('Fit');aligned();assert.equal(veil.pixels,veilPixels);
const rp=all().find(e=>e.accept==='image/*');rp.files=[new Blob(['reference'])];fire(rp,'change');await settle();dom.flush();aligned();
fire(button('Hold to Compare'),'pointerdown');dom.flush();assert.equal(veil.hidden,true);assert.equal(find('selection-outline').style.display,'none');
fire(button('Hold to Compare'),'pointerup');dom.flush();assert.equal(veil.hidden,false);
const [panX,panY,z]=canvas().style.transform.match(/translate\(([^p]+)px,([^p]+)px\) scale\(([^)]+)\)/).slice(1).map(Number);
const vp=find('viewport');fire(vp,'pointerdown',{clientX:panX+3.5*z,clientY:panY+5.5*z});fire(vp,'pointerup',{clientX:panX+3.5*z,clientY:panY+5.5*z});dom.flush();eq(session().selection,rect(3,5,3,5));
press('Clear Selection');assert.equal(veil.hidden,true);eq(session().codes,empty());
""")

    def test_clipped_preview_shift_click_and_outside_history(self):
        run_editor(r"""
settings().size=9;
session().selection=rect(10,10,20,20);pointer('pointermove',10,15);dom.flush();
const shown=engine.stampPreview(128,128,engineBrush(),10,15);
for(let i=0;i<16384;i++)assert.equal(preview().pixels[i*4+3]>0,shown.coverage[i]>0&&!!session().selection[i]);
const d=outline().children[0].attributes.d;session().selection=null;pointer('pointermove',10,15);dom.flush();assert.equal(outline().children[0].attributes.d,d);
session().selection=rect(10,10,20,20);click(15,15);const before=session().codes.slice();
const expected=new engine.Stroke(before,128,128,engineBrush(),15,15,session().initial,session().selection);expected.add(30,15);
click(30,15,{shiftKey:true});eq(session().codes,expected.result());assert.equal(session().history.undoEntries.length,2);
const countBefore=session().history.undoEntries.length;click(100,100);assert.equal(session().history.undoEntries.length,countBefore);
press('Rectangle Select');press('Paint');const old=session().codes.slice();click(110,110,{shiftKey:true});eq(session().codes,old);
""")

    def test_history_selection_never_records_or_clips_undo(self):
        run_editor(r"""
press('Fill with Influence');const filled=session().codes.slice();assert.equal(session().history.undoEntries.length,1);
press('Rectangle Select');drag(10,20,40,30);const selected=session().selection;
key('z',{ctrlKey:true});eq(session().codes,empty());assert.equal(session().selection,selected);
const redoEntries=session().history.redoEntries.slice();press('Select All');press('Clear Selection');press('Invert Selection');
assert.deepEqual(session().history.redoEntries,redoEntries);assert.equal(session().history.undoEntries.length,0);
const allSelected=session().selection;key('y',{ctrlKey:true});eq(session().codes,filled);assert.equal(session().selection,allSelected);
press('Clear Selection');press('Rectangle Select');drag(10,20,40,30);press('Invert');assert.equal(session().history.undoEntries.length,2);
press('Undo');press('Clear');assert.equal(session().history.redoEntries.length,0);
for(let n=0;n<105;n++)session().operation('invert');assert.equal(session().history.undoEntries.length,100);
""")

    def test_ui_transform_disabled_and_exact_labels(self):
        run_editor(r"""
const labels=['Flip Horizontal','Flip Vertical','Rotate 90° CW','Rotate 90° CCW'];
for(const label of labels)assert.equal(button(label).disabled,false);
press('Select All');for(const label of labels){assert.equal(button(label).disabled,true);assert.equal(button(label).title,'Flip and rotate move every cell, so they are unavailable while a selection is active. Clear Selection first.');}
press('Clear Selection');for(const label of labels)assert.equal(button(label).disabled,false);
session().codes=Uint8Array.from({length:16384},(_,i)=>(i*73+Math.floor(i/128))&255);const before=session().codes.slice();
for(const [i,label] of labels.entries()){press(label);assert.equal(session().history.undoEntries.at(-1).label,label);press('Undo');eq(session().codes,before);}
assert.equal(button('Clear').title,'Set cells to 0: every cell, or only the selected cells while a selection is active.');
assert.equal(button('Fill with Influence').title,'Set cells to Influence: every cell, or only the selected cells while a selection is active.');
assert.equal(button('Invert').title,'Replace each code with 255 − code: every cell, or only the selected cells while a selection is active.');
""")

    def test_placement_all_examples_odd_and_degenerate(self):
        sizes = [(1024,512),(512,1024),(257,193),(193,257),(4096,1),(1,4096),(64,64),
                 (1,1),(4096,4096),(129,128),(128,129),(127,128)]
        cases = [(w,h,p) for w,h in sizes for p in ('stretch','fit','fill')]
        actual = run_node("console.log(JSON.stringify(data.map(([w,h,p])=>imports.maskPlacement(w,h,p))));", cases)
        for case, result in zip(cases, actual):
            self.assertEqual(result, FieldToolsOracle.placement(*case), case)

    def test_fraction_import_oracle_all_options_and_mixed_axes(self):
        rng = random.Random(8017)
        cases, expected = [], []
        for w,h in [(1,1),(1,7),(2,3),(3,2),(63,64),(64,64),(65,63),(128,128),
                    (129,127),(200,50),(50,200),(257,193),(193,257),(300,7),(5,300)]:
            y = bytes(rng.randrange(256) for _ in range(w*h))
            a = bytes(rng.randrange(256) for _ in range(w*h))
            channels = ('luminance','alpha','alpha_luminance') if w*h < 20 or (w,h)==(257,193) else ('luminance',)
            for read in channels:
                samples = y if read=='luminance' else a if read=='alpha' else bytes((v*t+127)//255 for v,t in zip(y,a))
                for mode in ('stretch','fit','fill'):
                    averages = FieldToolsOracle.averages(w,h,samples,mode)
                    for invert,binary in itertools.product((False,True),repeat=2):
                        cases.append(dict(source=source(w,h,y,a),options=dict(read=read,placement=mode,invert=invert,binary=binary)))
                        expected.append(b64(FieldToolsOracle.quantize(averages,invert,binary)))
        actual = run_node("console.log(JSON.stringify(data.map(c=>encode(imports.reduceMask(sourceOf(c.source),c.options)))));", cases)
        for index,(got,want) in enumerate(zip(actual,expected)):
            self.assertEqual(got,want,(index,cases[index]['options'],cases[index]['source']['w'],cases[index]['source']['h']))

    def test_analytic_import_patterns_identity_enlargement_and_ties(self):
        run_node(r"""
const make=(w,h,fn)=>({width:w,height:h,luminance:Uint8Array.from({length:w*h},(_,i)=>fn(i%w,Math.floor(i/w))),alpha:new Uint8Array(w*h).fill(255)});
for(const [w,h,fn,expected] of [
 [128,128,(x,y)=>(x*71+y*19)&255,(x,y)=>(x*71+y*19)&255],
 [256,256,(x,y)=>(x+y)%2*255,()=>128],
 [512,512,x=>x%2*255,()=>128],
 [1024,512,(x,y)=>(Math.floor(x/8)*11+Math.floor(y/8)*13)&255,(x,y)=>(x*11+Math.floor(y/2)*13)&255],
 [512,1024,(x,y)=>(Math.floor(x/8)*13+Math.floor(y/8)*11)&255,(x,y)=>(Math.floor(x/2)*13+y*11)&255],
 [64,64,(x,y)=>(x-32)*(x-32)+(y-32)*(y-32)<=400?255:0,(x,y)=>(Math.floor(x/2)-32)*(Math.floor(x/2)-32)+(Math.floor(y/2)-32)*(Math.floor(y/2)-32)<=400?255:0],
 [4096,4096,(x,y)=>(Math.floor(x/32)*13+Math.floor(y/32)*7)&255,(x,y)=>(x*13+y*7)&255]
]){
 const s=make(w,h,fn),result=imports.reduceMask(s,imports.MASK_DEFAULTS);
 eq(result,Uint8Array.from({length:16384},(_,i)=>expected(i%128,Math.floor(i/128))),`${w}x${h}`);
 if(w===256){eq(imports.reduceMask(s,{...imports.MASK_DEFAULTS,invert:true}),result);assert.ok(imports.reduceMask(s,{...imports.MASK_DEFAULTS,binary:true}).every(v=>v===255));}
}
for(const [values,want] of [[[127,127],0],[[127,128],255],[[128,128],255]]){
 const s=make(256,128,x=>values[x%2]);assert.ok(imports.reduceMask(s,{...imports.MASK_DEFAULTS,binary:true}).every(v=>v===want));
}
""")

    def test_odd_large_one_dimensional_fraction_oracle(self):
        w,h = 4095,4093
        row = bytes((x*71+13)&255 for x in range(w))
        expected = FieldToolsOracle.quantize(FieldToolsOracle.averages(w,1,row,'stretch'))
        actual = run_node(r"""
const row=bytesOf(data.row),s={width:4095,height:4093,luminance:new Uint8Array(4095*4093),alpha:new Uint8Array(4095*4093).fill(255)};
for(let y=0;y<4093;y++)s.luminance.set(row,y*4095);console.log(JSON.stringify(encode(imports.reduceMask(s,imports.MASK_DEFAULTS))));
""",dict(row=b64(row)))
        self.assertEqual(actual,b64(expected))

    def test_mask_png_all_color_depths_and_channel_formulas(self):
        fixtures = []
        rng = random.Random(8015)
        for color, depths, channels in [(0,(1,2,4,8,16),1),(2,(8,16),3),(3,(1,2,4,8),1),(4,(8,16),2),(6,(8,16),4)]:
            for depth in depths:
                pixels = [tuple(rng.randrange(1<<depth) for _ in range(channels)) for _ in range(6)]
                palette = [(i*71%256,i*37%256,i*113%256) for i in range(1<<depth)] if color==3 else None
                trns = bytes((i*47+1)%256 for i in range(1<<depth)) if color==3 else None
                y,a = expected_planes(color,depth,pixels,palette,trns)
                fixtures.append(dict(png=b64(png(3,2,color,depth,pixels,palette=palette,trns=trns,filters=(0,1))),
                                     y=y,a=a))
        run_node(r"""
for(const f of data){const bytes=bytesOf(f.png);const s=await imports.readMaskFile({size:bytes.length,arrayBuffer:async()=>bytes.buffer});
 eq(s.luminance,f.y);eq(s.alpha,f.a);
 for(const read of imports.MASK_READS){
  const expected=f.y.map((y,i)=>read==='luminance'?y:read==='alpha'?f.a[i]:Math.floor((f.a[i]*y+127)/255));
  eq(brushes.tipMask(s,read,false,false).codes,expected);
  const r=imports.reduceMask(s,{...imports.MASK_DEFAULTS,read});assert.equal(r[0],expected[0]);
 }
}
assert.equal(imports.MASK_DEFAULTS.read,'luminance');
""", fixtures)

    def test_decoder_all_filters_exact_planes_and_channels(self):
        fixtures, rng = [], random.Random(804)
        for color, depths, channels in [(0,(1,2,4,8,16),1),(2,(8,16),3),(3,(1,2,4,8),1),(4,(8,16),2),(6,(8,16),4)]:
            for depth in depths:
                for w,h in [(1,9),(7,5)]:
                    pixels = [tuple(rng.randrange(1 << depth) for _ in range(channels)) for _ in range(w*h)]
                    palette = [(i*71%256,i*37%256,i*113%256) for i in range(1 << depth)] if color == 3 else None
                    transparency = (bytes((i*47+1)%256 for i in range(1 << depth)) if color == 3 else
                                    struct.pack('>H',pixels[0][0]) if color == 0 else
                                    struct.pack('>HHH',*pixels[0]) if color == 2 else None)
                    for trns in ([None,transparency] if transparency else [None]):
                        y,a = expected_planes(color,depth,pixels,palette,trns)
                        for filters in [(0,),(1,),(2,),(3,),(4,),(4,0,3,1,2)]:
                            fixtures.append(dict(label=[color,depth,w,h,bool(trns),filters],y=y,a=a,
                                png=b64(png(w,h,color,depth,pixels,palette=palette,trns=trns,filters=filters))))
        self.assertEqual(len(fixtures),312)
        run_node(r"""
for(const f of data){
 const bytes=bytesOf(f.png),label=JSON.stringify(f.label);
 const s=await imports.readMaskFile({size:bytes.length,arrayBuffer:async()=>bytes.buffer});
 eq(s.luminance,f.y,label+' luminance');eq(s.alpha,f.a,label+' alpha');
 const tip=await tips.decodeTipPng(bytes);eq(tip.luminance,f.y,label+' E5 luminance');eq(tip.alpha,f.a,label+' E5 alpha');
 for(const read of imports.MASK_READS){
  const expected=f.y.map((v,i)=>read==='luminance'?v:read==='alpha'?f.a[i]:Math.floor((v*f.a[i]+127)/255));
  eq(brushes.tipMask(s,read,false,false).codes,expected,label+' '+read);
 }
}
""", fixtures)

    def test_specialized_rows_boundaries_and_raw_transparency_keys(self):
        fixtures = []
        for color, depth, pixels, trns in [
            (6,16,[(65535,257,128,32896),(1,65534,32768,0),(257,258,259,65535)],None),
            (0,1,[(1,),(0,),(1,)],struct.pack('>H',257)),
            (0,16,[(256,),(257,),(258,)],struct.pack('>H',257)),
            (2,16,[(256,512,768),(257,512,768),(256,513,768)],struct.pack('>HHH',256,512,768)),
        ]:
            for filters in [(2,3,4),(3,4,2),(4,3,2)]:
                y,a = expected_planes(color,depth,pixels,None,trns)
                fixtures.append(dict(y=y,a=a,png=b64(png(1,3,color,depth,pixels,trns=trns,filters=filters))))
        for depth in (1,2,4):
            pixels = [(i % (1 << depth),) for i in range(15)]
            y,a = expected_planes(0,depth,pixels)
            fixtures.append(dict(y=y,a=a,png=b64(png(5,3,0,depth,pixels,filters=(4,3,2)))))
        bad = [png(1,3,6,16,[(1,2,3,4)]*3,filters=(4,3,5)),
               png(1,3,3,2,[(0,),(0,),(1,)],palette=[(20,30,40)],filters=(4,3,2))]
        run_node(r"""
for(const f of data.fixtures){
 const bytes=bytesOf(f.png);
 for(const s of [await tips.decodeTipPng(bytes),await imports.readMaskFile({size:bytes.length,arrayBuffer:async()=>bytes.buffer})]){
  eq(s.luminance,f.y,'row luminance');eq(s.alpha,f.a,'row alpha');
 }
}
for(const encoded of data.bad){const bytes=bytesOf(encoded);
 await assert.rejects(()=>tips.decodeTipPng(bytes),/damaged or incomplete/);
 await assert.rejects(()=>imports.readMaskFile({size:bytes.length,arrayBuffer:async()=>bytes.buffer}),/damaged or incomplete/);
}
""",dict(fixtures=fixtures,bad=[b64(b) for b in bad]))

    def test_specialized_channels_match_e5_every_pair_without_redecode(self):
        run_node(r"""
const dom=installDOM();
const saved=globalThis.DecompressionStream;
globalThis.DecompressionStream=class {constructor(){assert.fail('option change decoded PNG again');}};
try{
 for(let block=0;block<4;block++){
  const y=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)>>8);
  const a=Uint8Array.from({length:16384},(_,i)=>i&255);
  const s={width:128,height:128,luminance:y,alpha:a};
  for(const read of ['alpha_luminance','alpha','luminance','alpha_luminance']){
   eq(imports.reduceMask(s,{...imports.MASK_DEFAULTS,read}),brushes.tipMask(s,read,false,false).codes,read);
  }
  let preview;
  const dialog=importUI.openMaskImport({source:s,codes:empty(),selection:null,options:{...imports.MASK_DEFAULTS},
   draw:(canvas,codes)=>{preview=codes;},apply:()=>{},onClose:()=>{}});
  for(const [label,read] of [['Alpha','alpha'],['Alpha × Luminance','alpha_luminance'],['Luminance','luminance']]){
   descendants(document.body).find(e=>e.tagName==='BUTTON'&&e.textContent===label).click();
   eq(preview,brushes.tipMask(s,read,false,false).codes,'preview '+read);
  }
  dialog.dispose();
 }
}finally{globalThis.DecompressionStream=saved;}
""")

    def test_specialized_accumulator_bounds_and_final_alpha(self):
        run_node(r"""
const full=new Uint8Array(4096*4096).fill(255),s={width:4096,height:4096,luminance:full,alpha:full};
for(const placement of imports.MASK_PLACEMENTS)for(const invert of [false,true])for(const binary of [false,true]){
 const result=imports.reduceMask(s,{...imports.MASK_DEFAULTS,placement,invert,binary});
 assert.ok(result.every(v=>v===(invert?0:255)),'maximum numerator and signed bound');
}
installDOM();
for(const transparent of [false,true]){
 const a=new Uint8Array(16384).fill(255);if(transparent)a[a.length-1]=254;
 const dialog=importUI.openMaskImport({source:{width:128,height:128,luminance:a,alpha:a},codes:empty(),selection:null,
  options:{...imports.MASK_DEFAULTS},draw:()=>{},apply:()=>{},onClose:()=>{}});
 assert.ok(descendants(document.body).find(e=>e.className==='import-source').textContent.endsWith(transparent?'with transparency':'opaque'));
 dialog.dispose();
}
""")

    def test_paeth_import_pipeline_fraction_oracle(self):
        cases, expected, rng = [], [], random.Random(80432)
        for w,h,color,depth,channels in [(3,2,4,8,2),(7,5,6,16,4)]:
            pixels = [tuple(rng.randrange(1 << depth) for _ in range(channels)) for _ in range(w*h)]
            y,a = expected_planes(color,depth,pixels)
            encoded = b64(png(w,h,color,depth,pixels,filters=(4,)))
            for read in ('luminance','alpha','alpha_luminance'):
                samples = y if read == 'luminance' else a if read == 'alpha' else [(v*t+127)//255 for v,t in zip(y,a)]
                for mode in ('stretch','fit','fill'):
                    averages = FieldToolsOracle.averages(w,h,samples,mode)
                    for invert,binary in itertools.product((False,True),repeat=2):
                        cases.append(dict(png=encoded,options=dict(read=read,placement=mode,invert=invert,binary=binary)))
                        expected.append(b64(FieldToolsOracle.quantize(averages,invert,binary)))
        actual = run_node(r"""
const results=[];
for(const c of data){const bytes=bytesOf(c.png),s=await imports.readMaskFile({size:bytes.length,arrayBuffer:async()=>bytes.buffer});
 results.push(encode(imports.reduceMask(s,c.options)));}
console.log(JSON.stringify(results));
""", cases)
        self.assertEqual(len(actual),72)
        for index,(got,want) in enumerate(zip(actual,expected)):
            self.assertEqual(got,want,(index,cases[index]['options']))

    def test_reader_bounds_before_read_and_inflate_legacy_limits(self):
        header = lambda w,h: b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR",struct.pack('>IIBBBBB',w,h,8,0,0,0,0))
        raw = (b'\0' + bytes([73])*4096)*4096
        large = header(4096,4096) + chunk(b'IDAT',zlib.compress(raw)) + chunk(b'IEND',b'')
        data = dict(headers=[b64(header(w,h)) for w,h in [(4097,1),(1,4097),(4097,4097)]],large=b64(large),
                    small=b64(png(1,1,0,8,[(77,)])))
        run_node(r"""
const fileMessage='PNG files for mask import may be at most 33,554,432 bytes.';
assert.deepEqual(imports.MASK_LIMITS,{fileBytes:33554432,side:4096,pixels:16777216});
let reads=0;await assert.rejects(()=>imports.readMaskFile({size:33554433,arrayBuffer:()=>{reads++;throw Error('read');}}),{message:fileMessage});assert.equal(reads,0);
const small=bytesOf(data.small);await imports.readMaskFile({size:33554432,arrayBuffer:async()=>{reads++;return small.buffer;},get name(){throw Error('name read');}});assert.equal(reads,1);
await assert.rejects(()=>imports.readMaskFile({size:1,arrayBuffer:async()=>new Uint8Array(33554433).buffer}),{message:fileMessage});
const original=globalThis.DecompressionStream;let inflates=0;globalThis.DecompressionStream=class{constructor(){inflates++;throw Error('inflate');}};
for(const [i,text] of data.headers.entries()){
 const bytes=bytesOf(text);await assert.rejects(()=>imports.readMaskFile({size:bytes.length,arrayBuffer:async()=>bytes.buffer}),
 {message:`Masks may be at most 4,096 pixels a side and 16,777,216 pixels in all; this PNG is ${[[4097,1],[1,4097],[4097,4097]][i].join('×')}.`});
}assert.equal(inflates,0);globalThis.DecompressionStream=original;
const bytes=bytesOf(data.large),s=await imports.readMaskFile({size:bytes.length,arrayBuffer:async()=>bytes.buffer});assert.equal(s.width,4096);assert.equal(s.height,4096);assert.ok(s.luminance.every(v=>v===73));
assert.deepEqual(tips.TIP_LIMITS,{fileBytes:8388608,side:1024,pixels:262144,stored:1048576});
await assert.rejects(()=>tips.decodeTipPng(bytes),/Custom tips may be at most 1,024/);
""", data)

    def test_import_dialog_preview_options_cancel_memory_and_errors(self):
        data = dict(png=b64(png(3,2,4,8,[(0,255),(127,64),(255,0),(41,9),(128,128),(73,200)])))
        run_editor(r"""
const initial=session().codes.slice(),stored=JSON.stringify(settings());
const p=maskPicker(),bytes=bytesOf(data.png);let resolve;
p.files=[{size:bytes.length,arrayBuffer:()=>new Promise(r=>resolve=r)}];fire(p,'change');assert.equal(error(),'Reading PNG…');
press('Fill with Influence');eq(session().codes,initial);assert.equal(maskDialog(),undefined);
resolve(bytes.buffer);await until(()=>maskDialog(),'loaded');assert.equal(error(),'');
assert.equal(find('import-source').textContent,'Source 3×2 pixels · with transparency');
const pressed=label=>descendants(maskDialog()).find(e=>e.textContent===label&&e.tagName==='BUTTON').attributes['aria-pressed'];
assert.equal(pressed('Luminance'),'true');assert.equal(pressed('Stretch'),'true');assert.equal(pressed('Graded'),'true');assert.equal(pressed('Invert Mask'),'false');
assert.ok(find('import-notes').textContent.includes('This PNG has transparency, which Luminance ignores. Alpha or Alpha × Luminance reads it.'));
const beforePreview=pixels(find('import-preview'));maskPress('Alpha');assert.notEqual(encode(pixels(find('import-preview'))),encode(beforePreview));
maskPress('Fit (pad 0)');maskPress('Binary');maskPress('Invert Mask');
assert.ok(find('import-notes').textContent.includes("Inverted before averaging; Fit's empty cells stay 0."));
assert.ok(find('import-notes').textContent.includes('Fit: all 3×2 pixels fill 128×85 cells at x 0, y 21; the other cells are 0.'));
assert.equal(session().history.undoEntries.length,0);eq(session().codes,initial);assert.equal(JSON.stringify(settings()),stored);
const drop=fire(maskDialog(),'drop',{dataTransfer:{files:[fileOf(data.png)]}});assert.equal(drop.stopped,true);assert.equal(drop.prevented,true);eq(session().codes,initial);
key('Escape');assert.equal(maskDialog(),undefined);eq(session().codes,initial);assert.equal(session().history.undoEntries.length,0);
await maskFile(data.png);assert.equal(pressed('Alpha'),'true');assert.equal(pressed('Fit (pad 0)'),'true');assert.equal(pressed('Binary'),'true');assert.equal(pressed('Invert Mask'),'true');
maskPress('Cancel Import');eq(session().codes,initial);assert.equal(maskDialog(),undefined);
controller.cancel();controller=open();dom.flush();await maskFile(data.png);assert.equal(pressed('Luminance'),'true');assert.equal(pressed('Stretch'),'true');assert.equal(pressed('Graded'),'true');assert.equal(pressed('Invert Mask'),'false');
maskPress('Cancel Import');p.files=[];
maskPicker().files=[{size:33554433,arrayBuffer:()=>{throw Error('must not read');}}];fire(maskPicker(),'change');await until(()=>error().startsWith('Cannot import'),'refused');
assert.equal(error(),'Cannot import the mask: PNG files for mask import may be at most 33,554,432 bytes.');assert.equal(maskDialog(),undefined);
await maskFile(data.png);assert.equal(error(),'');maskPress('Cancel Import');assert.equal(error(),'');
""", data)

    def test_import_apply_selected_composite_history_done_and_noop(self):
        data = dict(png=b64(png(2,2,0,8,[(0,),(64,),(128,),(255,)])))
        run_editor(r"""
session().codes.fill(37);session().selection=ellipse();const before=session().codes.slice(),selection=session().selection;
await maskFile(data.png);const previewCodes=pixels(find('import-preview'));
assert.ok(find('import-summary').textContent.startsWith(`Apply replaces only the ${count(selection)} selected cells; `));
assert.equal(descendants(maskDialog()).filter(e=>e.tagName==='CANVAS').length,1);assert.equal(descendants(maskDialog()).filter(e=>e.tagName==='IMG').length,0);
const source=await imports.readMaskFile(fileOf(data.png));const imported=imports.reduceMask(source,imports.MASK_DEFAULTS);
eq(previewCodes,engine.withinSelection(before,imported,selection));maskPress('Apply Import');
eq(session().codes,previewCodes);assert.equal(session().selection,selection);assert.equal(session().history.undoEntries.length,1);assert.equal(session().history.undoEntries[0].label,'Import Mask');assert.equal(maskDialog(),undefined);
await maskFile(data.png);assert.ok(find('import-summary').textContent.endsWith('; 0 change.'));maskPress('Apply Import');assert.equal(session().history.undoEntries.length,1);
press('Undo');eq(session().codes,before);assert.equal(session().selection,selection);press('Redo');eq(session().codes,previewCodes);
assert.ok(!Object.keys(session()).some(k=>/source|dialog|preview/i.test(k)));assert.ok(!Object.keys(settings()).some(k=>/selection|import|fieldTools/i.test(k)));
press('Done');await settle();eq(result.codes,previewCodes);assert.equal(session().selection,null);
assert.ok(!/selection|selectTool|selectionMode|luminance|alpha|placement|fieldTools/i.test(JSON.stringify(result.settings)));
controller=open();dom.flush();await maskFile(data.png);maskPress('Apply Import');controller.cancel();assert.equal(cancelled,1);
""", data)

    def test_import_ui_disposal_no_source_retention_and_modal_isolation(self):
        run_editor(r"""
const initial=session().codes.slice();let closed=0,applied=0;
const importOptions={...imports.MASK_DEFAULTS};const source={width:1,height:1,luminance:Uint8Array.of(73),alpha:Uint8Array.of(255)};
const d=importUI.openMaskImport({source,codes:initial,selection:null,options:importOptions,draw:ui.drawCodes,apply:()=>applied++,onClose:()=>closed++});
assert.equal(find('import-source').textContent,'Source 1×1 pixels · opaque');maskPress('Alpha');
assert.ok(find('import-notes').textContent.includes('This PNG has no transparency: Alpha is 255 everywhere.'));
const old=maskDialog();d.dispose();assert.equal(closed,1);d.dispose();assert.equal(closed,1);assert.equal(applied,0);
for(const e of descendants(old).filter(e=>e.tagName==='BUTTON'))e.click();assert.equal(applied,0);assert.equal(maskDialog(),undefined);
eq(session().codes,initial);
""")

    def test_legacy_import_exact_selection_and_no_redirect(self):
        data = dict(native=b64(png(128,128,0,8,[(i%256,) for i in range(16384)])),
                    other=b64(png(129,128,0,8,[(255,)]*(129*128))))
        run_editor(r"""
const picker=all().find(e=>e.accept==='.png');session().codes.fill(91);session().selection=rect();const before=session().codes.slice();
picker.files=[fileOf(data.native)];fire(picker,'change');await until(()=>session().history.undoEntries.length===1,'field import');
eq(session().codes,before.map((v,i)=>session().selection[i]?i%256:v));assert.equal(session().history.undoEntries[0].label,'Import');
const after=session().codes.slice();picker.files=[fileOf(data.other)];fire(picker,'change');await until(()=>error(),'field rejection');
assert.ok(error().endsWith('For another size or format, use Advanced ▸ Field Tools ▸ Import Mask…'));eq(session().codes,after);assert.equal(maskDialog(),undefined);assert.equal(session().history.undoEntries.length,1);
press('Clear Selection');fire(find('cl-field-editor'),'drop',{dataTransfer:{files:[fileOf(data.native)]}});await until(()=>session().history.undoEntries.length===2,'field drop');
eq(session().codes,Uint8Array.from({length:16384},(_,i)=>i%256));assert.equal(maskDialog(),undefined);
""", data)

    def test_group_memory_and_numeric_inventory(self):
        run_editor(r"""
const group=heading('Field Tools').parent;assert.equal(group.open,false);group.open=true;fire(group,'toggle');
assert.deepEqual(writes,[['fieldTools',true]]);controller.cancel();controller=open();dom.flush();assert.equal(heading('Field Tools').parent.open,true);
assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='text').length,41);assert.equal(all().filter(e=>e.type==='range').length,0);
assert.ok(!Object.hasOwn(settings(),'fieldTools'));assert.ok(!Object.hasOwn(ui.editorSettings(settings()),'fieldTools'));
""")

    def test_core_boundaries_imports_and_no_persistent_e8_state(self):
        imports_expected = {
            'selection.js': [],
            'field_import.js': ['import {decodePngPlanes} from "./custom_tip.js";'],
            'field_import_ui.js': ['import {maskPlacement, reduceMask} from "./field_import.js";', 'import {withinSelection} from "./engine.js";'],
            'engine.js': ['import {footprintLocal, localCoverage, prepareFootprint, resolveBrush, snapAnchor} from "./brush.js";',
                          'import {prepareProfile, profileTarget} from "./value_profile.js";'],
            'view.js': ['import {footprintToCell} from "./brush.js";'],
            'custom_tip.js': [],
        }
        for file, expected in imports_expected.items():
            text = (CORE/file).read_text(encoding='utf-8')
            self.assertEqual(re.findall(r'^import .*;',text,re.M),expected,file)
        selection = (CORE/'selection.js').read_text(encoding='utf-8')
        self.assertNotIn('/*',selection)
        for token in ['Math.random','Math.pow','**','Date.','document','window']:
            self.assertNotIn(token,selection)
        text = (CORE/'field_import.js').read_text(encoding='utf-8')
        for token in ['.name','path','getImageData','drawImage','createImageBitmap','new Image(','toBlob','fetch(']:
            self.assertNotIn(token,text)
        self.assertIn('import {decodeTipDataUrl, importTipFile, storedTipValid} from "./custom_tip.js";',
                      (CORE/'editor_ui.js').read_text(encoding='utf-8'))
        run_node(r"""
const s=ui.createEditorSession(empty(),{selection:sel.selectAll(),selectTool:'ellipse',selectionMode:'subtract',fieldTools:true,source:{width:4},placement:'fit'});
assert.equal(s.selection,null);assert.equal(s.selectTool,null);assert.equal(s.selectionMode,'replace');
for(const key of ['selection','selectTool','selectionMode','fieldTools','source','placement']){assert.ok(!Object.hasOwn(s.settings,key));assert.ok(!lib.SNAPSHOT_KEYS.includes(key));}
assert.equal(globalThis.document,undefined);assert.equal(globalThis.window,undefined);
""")

    def test_e1_golden_hashes_no_selection_and_select_all(self):
        actual = run_node(r"""
const {createHash}=await import('node:crypto');const output=[];
const initial=Uint8Array.from({length:16384},(_,i)=>(i*37+(i>>7)*11)%256);
const path=[[105.125,57.25],[110,70],[60,80],[10,10],[-5,64.3],[130,64.3],[64.5,64.5]];
for(const selected of [null,sel.selectAll()]){const hashes={};
 for(const tool of ['paint','erase'])for(const size of [1,9,33]){const hash=createHash('sha256');
  for(const hardness of [0,37,99,100])for(const amount of [1,29,50,100]){
   const s=new engine.Stroke(initial,128,128,{tool,size,influence:173,hardness,amount},5.125,7.25,null,selected);
   for(const p of path)s.add(...p);hash.update(s.result());hash.update(new Uint8Array(s.coverage.buffer));
  }hashes[`${tool}-${size}`]=hash.digest('hex');
 }output.push(hashes);
}console.log(JSON.stringify(output));
""")
        for hashes in actual:
            self.assertEqual(hashes,E1_GOLDEN)
