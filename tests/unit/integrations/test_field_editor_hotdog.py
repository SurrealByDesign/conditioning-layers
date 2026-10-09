"""Hotdog offline qualification: independent asset/rotation oracles and retained engine twins."""
import base64
import hashlib
import json
import math
from pathlib import Path
import struct
import unittest
import zlib

from test_field_editor_custom_tip import run_node as retained_node, CORE, ROOT, EDITOR
from test_field_editor_multi_field import editor
from test_field_editor_procedural_tip import ProceduralOracle

ASSET_SHA = "5be8b4e24d59adc934b89ecd9d8b4b875dc43b6093470f23b46e75f6c5eb817a"
PRELUDE = f"const proc=await import({json.dumps((CORE / 'procedural_tip.js').as_uri())});\n"
PRELUDE += f"const template=await import({json.dumps((CORE / 'hotdog_template.js').as_uri())});\n"
PRELUDE += f"const lib=await import({json.dumps((CORE / 'brush_library.js').as_uri())});\n"
PRELUDE += r"""
const hot = extra => ({...brush,...brushes.BRUSH_DEFAULTS,shape:'procedural',procedural_particle_shape:'hotdog',
  procedural_size_jitter:0,procedural_position_jitter:0,...extra});
const codes = extra => proc.generateProceduralTip(hot(extra)).codes;
const eq=(a,b)=>{if(a===null||b===null){assert.equal(a,b);return;}assert.equal(a.length,b.length);for(let i=0;i<a.length;i++)if(a[i]!==b[i])assert.fail(`pixel ${i}: ${a[i]} != ${b[i]}`);};
const twin = b => ({...b,shape:'custom',tip_channel:'alpha',tip_invert:false,tip_trim:false,
  tip:{width:256,height:256,alpha:proc.proceduralTip(b).codes,luminance:new Uint8Array(65536).fill(255)}});
"""


def run_node(body, data=None):
    return retained_node(PRELUDE + body, data)


def canonical():
    raw = (ROOT / "assets/brush-templates/hotdog.png").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ASSET_SHA
    offset, chunks, packed = 8, [], b""
    while offset < len(raw):
        size = struct.unpack_from(">I", raw, offset)[0]
        kind, value = raw[offset+4:offset+8], raw[offset+8:offset+8+size]
        assert zlib.crc32(kind + value) == struct.unpack_from(">I", raw, offset+8+size)[0]
        chunks.append(kind)
        if kind == b"IHDR":
            assert struct.unpack(">IIBBBBB", value) == (256, 256, 8, 0, 0, 0, 0)
        if kind == b"IDAT":
            packed += value
        offset += size + 12
    assert chunks == [b"IHDR", b"IDAT", b"IEND"]
    scan = zlib.decompress(packed)
    assert len(scan) == 256 * 257 and all(scan[y*257] == 0 for y in range(256))
    return b"".join(scan[y*257+1:(y+1)*257] for y in range(256))


class HotdogTests(unittest.TestCase):
    def test_01_asset_identity_polarity_all_pixels_and_metadata(self):
        # Public snapshot verifies the canonical PNG and embedded runtime coverage.
        pixels = canonical()
        self.assertEqual(pixels[0], 255)
        self.assertIn(0, pixels)
        self.assertTrue(any(0 < p < 255 for p in pixels))
        run_node(r"""
const white=bytesOf(data);
for(let y=0;y<256;y++)for(let x=0;x<256;x++) {
 const u=(2*x+1)/256-1,v=(2*y+1)/256-1,i=x+y*256;
 assert.equal(template.hotdogCoverage(u,v,false),255-white[i]);
 assert.equal(template.hotdogCoverage(u,v,true),white[i]);
}
assert.equal(template.hotdogCoverage(1.001,0,true),0);
""", base64.b64encode(pixels).decode())

    def test_02_exact_count_and_centred_single_default(self):
        run_node(r"""
for(let n=1;n<=1024;n++) {
 const p=proc.scatterLayout(hot({hotdog_count:n}));assert.equal(p.length,n);
 assert.equal(new Set(p.map(p=>`${p.row},${p.column}`)).size,n);
}
const b={...brush,...brushes.BRUSH_DEFAULTS,shape:'procedural',procedural_particle_shape:'hotdog'};
for(const seed of [0,1,4294967295]) {
 const p=proc.scatterLayout({...b,procedural_seed:seed});assert.equal(p.length,1);
 assert.equal(p[0].x,0);assert.equal(p[0].y,0);assert.ok(codes(b).some(x=>x>0));
}
for(const n of [0,1025,1.5,NaN])assert.throws(()=>brushes.resolveBrush(hot({hotdog_count:n})));
""")

    def test_03_independent_placement_size_spread_seed_jitter_oracle(self):
        cases = []
        for n in (1, 2, 8, 32, 1024):
            for spread in (0, 25, 100):
                g = math.ceil(n ** .5)
                rows = (n + g - 1) // g
                expected = []
                for i in range(n):
                    row, col = divmod(i, g)
                    word = lambda d: ProceduralOracle.hash([0x45375343, 178, col, row, d])
                    signed = ProceduralOracle.signed
                    x = 0 if n == 1 else spread/100 * ((2*col+1-min(g,n-row*g))/g + 75/(100*g)*signed(word(1)))
                    y = 0 if n == 1 else spread/100 * ((2*row+1-rows)/g + 75/(100*g)*signed(word(2)))
                    c, s = ProceduralOracle.turn(90 + 53 * signed(word(4)))
                    expected.append([x, y, 60*(1+25*signed(word(3))/100)/(100*g), c, s])
                cases.append(dict(n=n, spread=spread, expected=expected))
        run_node(r"""
for(const c of data) {
 const b=hot({hotdog_count:c.n,hotdog_spread:c.spread,procedural_seed:178,procedural_position_jitter:75,
 procedural_size_jitter:25,procedural_particle_rotation:90,procedural_rotation_jitter:53});
 assert.deepEqual(proc.scatterLayout(b).map(p=>[p.x,p.y,p.a,p.cos,p.sin]),c.expected);
}
""", cases)

    def test_04_quarter_turn_images_invert_and_zero_jitter(self):
        pixels = canonical()
        run_node(r"""
const white=bytesOf(data), base=Uint8Array.from(white,v=>255-v);
for(const angle of [0,90,180,270])for(const invert of [false,true]) {
 const got=codes({procedural_particle_size:100,procedural_particle_rotation:angle,hotdog_invert:invert});
 const want=new Uint8Array(65536);
 for(let y=0;y<256;y++)for(let x=0;x<256;x++) {
  const [sx,sy]=angle===0?[x,y]:angle===90?[y,255-x]:angle===180?[255-x,255-y]:[255-y,x];
  want[x+256*y]=invert?white[sx+256*sy]:base[sx+256*sy];
 }
 eq(got,want);
 eq(got,codes({procedural_particle_size:100,procedural_particle_rotation:angle,hotdog_invert:invert,procedural_seed:123}));
}
for(const p of proc.scatterLayout(hot({hotdog_count:32,procedural_particle_rotation:90}))) {
 assert.ok(p.cos===0);assert.equal(p.sin,1);
}
""", base64.b64encode(pixels).decode())

    def test_05_size_and_overall_footprint_are_distinct(self):
        run_node(r"""
for(const n of [1,8]) {
 const b=hot({hotdog_count:n}),a=proc.scatterLayout(b),c=proc.scatterLayout({...b,procedural_particle_size:120});
 for(let i=0;i<n;i++){assert.equal(c[i].a,2*a[i].a);assert.equal(c[i].x,a[i].x);assert.equal(c[i].y,a[i].y);}
 assert.notDeepEqual(codes(b),codes({...b,procedural_particle_size:120}));
 eq(codes(b),codes({...b,size:128}));
 assert.deepEqual(brushes.prepareFootprint({...b,size:64}).extent,[32,32]);
 assert.deepEqual(brushes.prepareFootprint({...b,size:128}).extent,[64,64]);
}
""")

    def test_06_spread_changes_positions_not_count_or_size(self):
        run_node(r"""
for(const count of [2,8,32]) {
 const a=proc.scatterLayout(hot({hotdog_count:count,hotdog_spread:100}));
 const b=proc.scatterLayout(hot({hotdog_count:count,hotdog_spread:25}));
 const c=proc.scatterLayout(hot({hotdog_count:count,hotdog_spread:0}));
 assert.equal(a.length,b.length);assert.equal(b.length,c.length);
 for(let i=0;i<count;i++){assert.equal(b[i].x,a[i].x/4);assert.equal(b[i].y,a[i].y/4);
 assert.ok(c[i].x===0);assert.ok(c[i].y===0);assert.equal(c[i].a,a[i].a);}
 assert.notDeepEqual(codes({hotdog_count:count}),codes({hotdog_count:count,hotdog_spread:25}));
}
""")

    def test_07_seed_determinism_no_entropy_cache_eviction(self):
        run_node(r"""
const b=hot({hotdog_count:8,procedural_position_jitter:75,procedural_rotation_jitter:90});
const expected=codes(b);assert.notDeepEqual(expected,codes({...b,procedural_seed:1}));
Math.random=Date.now=crypto.getRandomValues=()=>{throw Error('entropy forbidden');};
for(let seed=0;seed<12;seed++)proc.proceduralTip({...b,procedural_seed:seed});
eq(expected,proc.proceduralTip(b).codes);eq(expected,codes(b));
const fresh=await import(new URL('./procedural_tip.js?fresh', @CORE@));eq(expected,fresh.generateProceduralTip(b).codes);
for(const extra of [{hotdog_count:2},{hotdog_spread:15},{hotdog_invert:true},{procedural_particle_size:120},
 {procedural_particle_rotation:90},{procedural_rotation_jitter:0}]) {
 const changed=proc.proceduralTip({...b,...extra});eq(changed.codes,codes({...b,...extra}));assert.notDeepEqual(changed.codes,expected);
}
""".replace('@CORE@', json.dumps((CORE / 'brush.js').as_uri())))

    def test_08_mirror_h_v_both_invert_rotation_independent_pixels(self):
        run_node(r"""
const white=bytesOf(data);
for(const h of [false,true])for(const v of [false,true])for(const invert of [false,true])for(const angle of [0,90,180,270]) {
 const b=hot({size:128,procedural_particle_size:100,mirror_horizontal:h,mirror_vertical:v,
   hotdog_invert:invert,rotation_degrees:angle});
 const p=engine.stampPreview(128,128,b,64,64);
 for(let y=0;y<128;y++)for(let x=0;x<128;x++) {
  let [sx,sy]=angle===0?[x,y]:angle===90?[y,127-x]:angle===180?[127-x,127-y]:[127-y,x];
  if(h)sx=127-sx;if(v)sy=127-sy;
  let sum=0;for(let j=0;j<2;j++)for(let i=0;i<2;i++)sum+=white[(2*sy+j)*256+2*sx+i];
  const want=(invert?sum/4:255-sum/4)/255;
  assert.equal(p.coverage[y*128+x],want);
 }
}
""", base64.b64encode(canonical()).decode())

    def test_09_paint_erase_restore_amount_flow_modes_spacing_selection_profiles(self):
        run_node(r"""
const initial=Uint8Array.from({length:16384},(_,i)=>i%256), restore=new Uint8Array(16384).fill(173);
const selected=Uint8Array.from({length:16384},(_,i)=>i%128<64?1:0);
for(const n of [1,8])for(const invert of [false,true])for(const tool of ['paint','erase','restore'])
for(const mode of ['normal','raise_only','lower_only'])for(const build of [false,true]) {
 const b=hot({hotdog_count:n,hotdog_invert:invert,size:64,tool,apply_mode:mode,amount:47,flow:63,build_up:build,
  spacing:'custom',spacing_percent:25,procedural_particle_size:95});
 const a=new engine.Stroke(initial,128,128,b,35,35,restore,selected),
 c=new engine.Stroke(initial,128,128,twin(b),35,35,restore,selected),
 divided=new engine.Stroke(initial,128,128,b,35,35,restore,selected);
 a.add(90,90);c.add(90,90);for(let i=36;i<=90;i++)divided.add(i,i);
 const result=a.result();eq(result,c.result());eq(result,divided.result());
 for(let i=0;i<16384;i++)if(!selected[i])assert.equal(result[i],initial[i]);
}
for(const profile of ['uniform','linear','radial','square']) {
 const b=hot({hotdog_count:8,size:64,value_profile:profile,hardness:35,mirror_horizontal:true,rotation_degrees:30});
 const p=engine.stampPreview(128,128,b,64,64), q=engine.stampPreview(128,128,twin(b),64,64);
 eq(p.coverage,q.coverage);eq(p.targets,q.targets);
}
// Independent ordinary paint Amount equation, and Build-up/Flow materially change output.
const b=hot({size:128,procedural_particle_size:100,amount:50});
const p=engine.stampPreview(128,128,b,64,64),s=new engine.Stroke(empty(),128,128,b,64,64).result();
for(let i=0;i<16384;i++) {
 const delta=(255*50)*p.coverage[i]/100, floor=Math.floor(delta);
 assert.equal(s[i],floor+(delta-floor>=.5?1:0));
}
const slow=new engine.Stroke(empty(),128,128,{...b,build_up:true,flow:10},64,64).result();
const fast=new engine.Stroke(empty(),128,128,{...b,build_up:true,flow:90},64,64).result();
assert.notDeepEqual(slow,fast);assert.notDeepEqual(s,fast);
""")

    def test_10_pressure_uses_overall_size_and_retained_pipeline(self):
        run_node(r"""
for(const n of [1,8])for(const invert of [false,true])for(const build of [false,true]) {
 const b=hot({hotdog_count:n,hotdog_invert:invert,size:64,pressure_enabled:true,pressure_size:true,
  pressure_amount:true,pressure_flow:true,build_up:build,mirror_vertical:true,procedural_particle_rotation:90});
 const a=new engine.PressureStroke(empty(),128,128,b,30,30,null,null,32768),
 c=new engine.PressureStroke(empty(),128,128,twin(b),30,30,null,null,32768);
 a.add(90,90,65535);c.add(90,90,65535);eq(a.result(),c.result());
 eq(codes(b),codes({...b,size:32}));
}
const b=hot({size:64,pressure_enabled:true});
eq(new engine.PressureStroke(empty(),128,128,b,64,64,null,null,32768).result(),
 new engine.Stroke(empty(),128,128,{...b,size:32},64,64).result());
""")

    def test_11_e6_save_apply_round_trip_versions_and_thumbnails(self):
        run_node(r"""
for(const pressure of [false,true]) {
 const b=hot({hotdog_count:8,hotdog_spread:23,hotdog_invert:true,mirror_horizontal:true,mirror_vertical:true,
  procedural_particle_size:120,procedural_position_jitter:55,procedural_particle_rotation:90,procedural_rotation_jitter:73,
  procedural_seed:999,pressure_enabled:pressure});
 const p=await lib.captureBrushPreset(b,{id:'hotdog',name:'Hotdog'});assert.equal(p.version,3);
 for(const key of [...lib.HOTDOG_SNAPSHOT_KEYS,...lib.PROCEDURAL_SNAPSHOT_KEYS,...lib.PRESSURE_SNAPSHOT_KEYS,
 'mirror_horizontal','mirror_vertical'])assert.equal(p.brush[key],b[key],key);
 const text=lib.serializeBrushLibrary({presets:[p]}), loaded=await lib.loadBrushLibrary(text);
 assert.equal(loaded.rejected.length,0);assert.equal(lib.serializeBrushLibrary(loaded),text);
 const session=ui.createEditorSession(empty(),{});await lib.applyBrushPreset(loaded.presets[0],session);
 assert.deepEqual(await lib.captureBrushPreset(session.settings,{id:'hotdog',name:'Hotdog'}),p);
 eq(codes(session.settings),codes(b));
 const thumbs=lib.createPresetThumbnails(), first=await thumbs(p);
 const q=await lib.captureBrushPreset({...b,hotdog_invert:false},{id:'hotdog',name:'Hotdog'});
 assert.notDeepEqual(first.pixels,(await thumbs(q)).pixels);
 for(const key of lib.HOTDOG_SNAPSHOT_KEYS){const bad=JSON.parse(JSON.stringify(p));delete bad.brush[key];await assert.rejects(()=>lib.validateBrushPreset(bad),/Missing/);}
 await assert.rejects(()=>lib.validateBrushPreset({...p,version:pressure?2:1}),/version/);
 const ordinary=await lib.captureBrushPreset(brush,{id:'plain',name:'Plain'});assert.equal(ordinary.version,1);
 await lib.applyBrushPreset(ordinary,session);for(const k of lib.HOTDOG_SNAPSHOT_KEYS)assert.equal(session.settings[k],brushes.BRUSH_DEFAULTS[k]);
}
""")

    def test_12_workflow_roundtrip_and_per_field_preset_isolation(self):
        editor(r"""
await add('2');const a=field('1').session,b=field('2').session;
activate('1');press('Procedural');press('Hotdog');
type('Hotdog Count',8);type('Spread (%)',25);type('Hotdog Size (% of slot)',120);
type('Hotdog Rotation (°)',90);type('Rotation Jitter (±°)',45);type('Seed',987);
press('Invert Template');press('Mirror H');press('Mirror V');
const saved=ui.editorSettings(a.settings), before=snapshot(b);
const reopened=ui.createEditorSession(a.codes,saved);assert.equal(JSON.stringify(ui.editorSettings(reopened.settings)),JSON.stringify(saved));
activate('2');assert.equal(snapshot(b),before);assert.equal(b.settings.hotdog_invert,false);assert.equal(b.settings.hotdog_count,1);
const p=await lib.captureBrushPreset({...a.settings,hotdog_count:32,hotdog_spread:60},{id:'hotdog',name:'Hotdog'});
// Exercise the actual E6 UI apply action (active target resolution).
libraryText=lib.serializeBrushLibrary({presets:[p]});press('Brush Library…');
await until(()=>find('library-status')&&!find('library-status').textContent.startsWith('Working'));
all().find(e=>e.className==='preset-select'&&e.textContent.startsWith('Hotdog')).click();dom.flush();
press('Apply');await until(()=>b.settings.hotdog_count===32);press('Close Library');
assert.equal(JSON.stringify(ui.editorSettings(a.settings)),JSON.stringify(saved));
assert.equal(b.settings.hotdog_count,32);assert.equal(b.settings.hotdog_invert,true);
type('Hotdog Count',2);press('Invert Template');press('Mirror H');
activate('1');assert.equal(JSON.stringify(ui.editorSettings(a.settings)),JSON.stringify(saved));
assert.equal(input('Hotdog Count').value,'8');assert.equal(a.settings.hotdog_invert,true);
activate('2');assert.equal(input('Hotdog Count').value,'2');assert.equal(b.settings.hotdog_invert,false);
assert.equal(b.settings.mirror_horizontal,false);assert.equal(b.settings.mirror_vertical,true);
controller.cancel();
""")

    def test_13_ui_numeric_drag_type_bounds_progressive_disclosure(self):
        run_node(EDITOR + r"""
assert.equal(find('hotdog-controls'),undefined);press('Procedural');press('Hotdog');
assert.ok(find('hotdog-controls'));assert.equal(find('hotdog-controls').hidden,false);
for(const [label,key,value] of [['Hotdog Count','hotdog_count',32],['Spread (%)','hotdog_spread',40],
 ['Hotdog Size (% of slot)','procedural_particle_size',80],['Hotdog Rotation (°)','procedural_particle_rotation',90],
 ['Rotation Jitter (±°)','procedural_rotation_jitter',45]]) {
 type(label,value);assert.equal(settings()[key],value);const e=input(label);assert.equal(e.type,'text');
 fire(e,'pointerdown',{clientX:10});fire(e,'pointermove',{clientX:15});fire(e,'pointerup',{clientX:15});dom.flush();
 assert.equal(settings()[key],value+5);
}
type('Hotdog Count',0);assert.equal(settings().hotdog_count,1);type('Hotdog Count',2048);assert.equal(settings().hotdog_count,1024);
type('Hotdog Count',1);type('Hotdog Size (% of slot)',100);type('Size Jitter (±%)',0);
click(64,64);assert.ok(session().codes.some(x=>x>0));
press('Circle');assert.equal(find('hotdog-controls').hidden,true);assert.equal(all().filter(e=>e.type==='range').length,0);
controller.cancel();
""")

    def test_14_invert_is_template_local_not_whole_tip(self):
        run_node(r"""
for(const n of [1,8]) {
 const b=hot({hotdog_count:n,procedural_particle_size:60,hotdog_invert:true});
 const a=codes(b);assert.equal(a[0],0);assert.ok(a.some(x=>x===255));assert.ok(a.some(x=>x===0));
 eq(a,codes({...b,procedural_invert:true})); // Hidden legacy whole-tip invert does not reinterpret this motif.
}
""")

    def test_15_multi_motif_images_independent_raster_oracle(self):
        white = canonical()
        cases = []
        for n, spread, invert in [(2, 100, False), (8, 100, False), (8, 25, True)]:
            g, rows = math.ceil(n ** .5), math.ceil(n / math.ceil(n ** .5))
            half = 80 / (100 * g)
            positions = [((spread / 100) * ((2 * (i % g) + 1 - min(g, n - (i // g) * g)) / g),
                          (spread / 100) * ((2 * (i // g) + 1 - rows) / g)) for i in range(n)]
            output = bytearray(65536)
            for y in range(256):
                for x in range(256):
                    best = 0
                    for cx, cy in positions:
                        u, v = ((2*x+1)/256-1-cx)/half, ((2*y+1)/256-1-cy)/half
                        if abs(u) > 1 or abs(v) > 1:
                            continue
                        fx, fy = (u+1)*128-.5, (v+1)*128-.5
                        ix, iy = math.floor(fx), math.floor(fy)
                        tx, ty = fx-ix, fy-iy
                        def value(dx, dy):
                            p = white[max(0, min(255, iy+dy))*256+max(0, min(255, ix+dx))]
                            return 255-p
                        top = value(0, 0) + tx*(value(1, 0)-value(0, 0))
                        bottom = value(0, 1) + tx*(value(1, 1)-value(0, 1))
                        sample = top + ty*(bottom-top)
                        best = max(best, math.floor((255-sample if invert else sample)+.5))
                    output[y*256+x] = best
            cases.append(dict(count=n, spread=spread, invert=invert, image=base64.b64encode(output).decode()))
        run_node(r"""
for(const c of data)eq(codes({hotdog_count:c.count,hotdog_spread:c.spread,hotdog_invert:c.invert,
 procedural_particle_size:80}),bytesOf(c.image));
""", cases)
