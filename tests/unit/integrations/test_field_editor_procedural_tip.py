"""E7 offline evidence. Oracle transcribed from E7 design §§4,7,16–23.

No JavaScript generator is imported or called by ProceduralOracle. Python binary64
operations retain the normative parentheses; mask comparisons have no tolerance.
"""
import base64
import hashlib
import json
import math
from pathlib import Path
import unittest

from test_field_editor_custom_tip import run_node as retained_node, EDITOR, first_difference

CORE = Path(__file__).resolve().parents[3] / "web/js/field_editor"
PRELUDE = (f"const proc = await import({json.dumps((CORE / 'procedural_tip.js').as_uri())});\n"
           f"const lib = await import({json.dumps((CORE / 'brush_library.js').as_uri())});\n"
           "const full = extra => ({...brush, ...brushes.BRUSH_DEFAULTS, shape:'procedural', ...extra});\n"
           "const mask = extra => proc.proceduralTip(full(extra));\n")


def run_node(body, data=None):
    return retained_node(PRELUDE + body, data)


def run_editor(body):
    return run_node(EDITOR + body)


class ProceduralOracle:
    DEFAULTS = dict(seed=0, grid=6, density=50, particle_shape="circle", particle_size=60,
                    particle_aspect=1, size_jitter=25, position_jitter=75,
                    particle_rotation=0, rotation_jitter=0, frequency=4, octaves=3,
                    persistence=50, noise_low=30, noise_high=70, invert=False, type="scatter")

    @staticmethod
    def mix(x):
        x = (x ^ (x >> 16)) & 0xFFFFFFFF
        x = (x * 0x7FEB352D) & 0xFFFFFFFF
        x = (x ^ (x >> 15)) & 0xFFFFFFFF
        x = (x * 0x846CA68B) & 0xFFFFFFFF
        return (x ^ (x >> 16)) & 0xFFFFFFFF

    @classmethod
    def hash(cls, words):
        h = 0x9E3779B9
        for w in words:
            h = cls.mix(((h ^ w) + 0x9E3779B9) & 0xFFFFFFFF)
        return h

    @staticmethod
    def signed(w):
        return w / 2147483648 - 1

    @staticmethod
    def turn(d):
        a = math.fmod(math.fmod(d, 360) + 360, 360)
        q = math.floor(a / 90 + 0.5)
        r = (a - 90 * q) * (math.pi / 180)
        r2 = r * r
        c = 1 - r2 / 2 * (1 - r2 / 12 * (1 - r2 / 30 * (1 - r2 / 56 * (1 - r2 / 90
            * (1 - r2 / 132 * (1 - r2 / 182 * (1 - r2 / 240)))))))
        s = r * (1 - r2 / 6 * (1 - r2 / 20 * (1 - r2 / 42 * (1 - r2 / 72 * (1 - r2 / 110
            * (1 - r2 / 156 * (1 - r2 / 210 * (1 - r2 / 272))))))))
        return ((c, s), (-s, c), (-c, -s), (s, -c))[q % 4]

    def __init__(self, changes=None):
        self.b = self.DEFAULTS | {(k.removeprefix("procedural_")): v for k, v in (changes or {}).items()}

    def layout(self):
        b = self.b
        g, d, seed = b["grid"], b["density"], b["seed"]
        slots = sorted((self.hash([0x45375343, seed, i, j, 0]), j, i)
                       for j in range(g) for i in range(g))[:math.floor((g * g * d + 50) / 100)]
        particles = []
        for rank, j, i in slots:
            word = lambda draw: self.hash([0x45375343, seed, i, j, draw])
            cx = (2 * i + 1) / g - 1 + b["position_jitter"] * self.signed(word(1)) / (100 * g)
            cy = (2 * j + 1) / g - 1 + b["position_jitter"] * self.signed(word(2)) / (100 * g)
            factor = 1 + b["size_jitter"] * self.signed(word(3)) / 100
            length = 2 * b["particle_size"] * factor / (100 * g)
            aspect = b["particle_aspect"]
            a, half_b = (length / 2, length / (2 * aspect)) if aspect >= 1 else (length * aspect / 2, length / 2)
            angle = 0 if b["particle_shape"] == "circle" and aspect == 1 else b["particle_rotation"] + b["rotation_jitter"] * self.signed(word(4))
            c, s = self.turn(angle)
            vertices = []
            if b["particle_shape"] == "irregular":
                count = 5 + word(5) % 4
                vertices = [self.turn((k + 0.4 * self.signed(word(6 + k))) * 360 / count) for k in range(count)]
            particles.append(dict(i=i, j=j, rank=rank, cx=cx, cy=cy, a=a, b=half_b,
                                  c=c, s=s, angle=angle, factor=factor, vertices=vertices))
        return particles

    @staticmethod
    def inside(shape, u, v, vertices):
        if shape == "circle":
            return u * u + v * v <= 1
        if shape == "rectangle":
            return abs(u) <= 1 and abs(v) <= 1
        if shape == "diamond":
            return abs(u) + abs(v) <= 1
        if shape == "trapezoid":
            return abs(v) <= 1 and 4 * abs(u) <= 3 + v
        for k, (x, y) in enumerate(vertices):
            nx, ny = vertices[(k + 1) % len(vertices)]
            if (nx - x) * (v - y) - (ny - y) * (u - x) < 0:
                return False
        return True

    def scatter(self):
        codes = bytearray(65536)
        for p in self.layout():
            # Conservative half-diagonal bound, permitted by §7. Membership is unoptimized.
            radius = math.sqrt(p["a"] * p["a"] + p["b"] * p["b"])
            lo_x = max(0, math.floor((p["cx"] - radius + 1) * 128) - 1)
            hi_x = min(255, math.floor((p["cx"] + radius + 1) * 128) + 1)
            lo_y = max(0, math.floor((p["cy"] - radius + 1) * 128) - 1)
            hi_y = min(255, math.floor((p["cy"] + radius + 1) * 128) + 1)
            for py in range(lo_y, hi_y + 1):
                for px in range(lo_x, hi_x + 1):
                    dx = (2 * px + 1) / 256 - 1 - p["cx"]
                    dy = (2 * py + 1) / 256 - 1 - p["cy"]
                    u = (p["c"] * dx + p["s"] * dy) / p["a"]
                    v = (-p["s"] * dx + p["c"] * dy) / p["b"]
                    if self.inside(self.b["particle_shape"], u, v, p["vertices"]):
                        codes[px + 256 * py] = 255
        return codes

    def noise(self):
        b = self.b
        lattices, length, amp, total = [], b["frequency"], 1, 0
        for o in range(b["octaves"]):
            values = [self.hash([0x45374E5A, b["seed"], o, ix, iy]) / 4294967295
                      for iy in range(length) for ix in range(length)]
            lattices.append((length, amp, values))
            total = total + amp
            amp = amp * b["persistence"] / 100
            length = 2 * length
        codes = bytearray(65536)
        for py in range(256):
            for px in range(256):
                acc = 0
                for length, amp, t in lattices:
                    xl = (2 * px + 1) * length / 512
                    ix = math.floor(xl)
                    fx = xl - ix
                    sx = fx * fx * (3 - 2 * fx)
                    yl = (2 * py + 1) * length / 512
                    iy = math.floor(yl)
                    fy = yl - iy
                    sy = fy * fy * (3 - 2 * fy)
                    x1, y1 = (ix + 1) % length, (iy + 1) % length
                    top = t[ix + length * iy] + sx * (t[x1 + length * iy] - t[ix + length * iy])
                    bottom = t[ix + length * y1] + sx * (t[x1 + length * y1] - t[ix + length * y1])
                    acc = acc + amp * (top + sy * (bottom - top))
                n = acc / total
                value = (100 * n - b["noise_low"]) / (b["noise_high"] - b["noise_low"])
                value = 0 if value <= 0 else 1 if value >= 1 else value
                codes[px + 256 * py] = math.floor(value * 255) + (1 if value * 255 - math.floor(value * 255) >= 0.5 else 0)
        return codes

    def mask(self):
        codes = self.noise() if self.b["type"] == "noise" else self.scatter()
        return bytes(255 - code for code in codes) if self.b["invert"] else bytes(codes)


def case(**kwargs):
    return {"procedural_" + key: value for key, value in kwargs.items()}


SCATTER = [case(), case(grid=1, density=100, particle_size=200, seed=4294967295),
           case(particle_shape="rectangle", particle_aspect=3, particle_rotation=30, rotation_jitter=180,
                grid=8, density=70, particle_size=120, size_jitter=90, position_jitter=100),
           case(particle_shape="diamond", particle_aspect=0.4, particle_rotation=-123.4, grid=5),
           case(particle_shape="trapezoid", particle_aspect=1.5, grid=1, density=100, size_jitter=0, position_jitter=0),
           case(particle_shape="irregular", grid=6, density=100, rotation_jitter=45, particle_size=150),
           case(particle_shape="irregular", grid=32, density=100, particle_size=200, size_jitter=90),
           case(invert=True), case(grid=10, density=1), case(particle_rotation=77.7, rotation_jitter=180)]
NOISE = [case(type="noise"), case(type="noise", frequency=1, octaves=1),
         case(type="noise", frequency=16, octaves=4, persistence=100, noise_low=0, noise_high=100, seed=4294967295),
         case(type="noise", frequency=7, octaves=2, persistence=0), case(type="noise", noise_low=49, noise_high=50),
         case(type="noise", invert=True), case(type="noise", noise_low=99, noise_high=100),
         case(type="noise", invert=True, noise_low=10, noise_high=60)]


class ProceduralOracleTests(unittest.TestCase):
    def compare_masks(self, cases):
        actual = run_node("console.log(JSON.stringify(data.map(b => Buffer.from(mask(b).codes).toString('base64'))));", cases)
        for settings, encoded in zip(cases, actual):
            expected = ProceduralOracle(settings).mask()
            self.assertIsNone(first_difference(base64.b64decode(encoded), expected), settings)

    def test_scatter_design_fixtures_full_masks(self):
        self.compare_masks(SCATTER)

    def test_noise_design_fixtures_full_masks(self):
        self.compare_masks(NOISE)

    def test_single_particle_all_shapes_aspects_rotations(self):
        self.compare_masks([case(particle_shape=shape, particle_aspect=aspect, particle_rotation=rotation,
                                 grid=1, density=100, size_jitter=0, position_jitter=0)
                            for shape in ("circle", "rectangle", "diamond", "trapezoid", "irregular")
                            for aspect in (0.4, 1, 3) for rotation in (0, 90, 30, -123.4)])

    def test_primitives_10000_exact_and_rank_ties(self):
        source = (CORE / "procedural_tip.js").read_text(encoding="utf-8")
        source = source.replace('"./hotdog_template.js"', json.dumps((CORE / 'hotdog_template.js').as_uri()))
        private = "data:text/javascript;base64," + base64.b64encode((source + "\nexport {mix32, signed, rank};").encode()).decode()
        words = [[i * 429497 & 0xFFFFFFFF, i, 0x45375343] for i in range(10000)]
        degrees = [i / 10 - 500 for i in range(10000)]
        result = run_node("""
const p=await import(data.module);
const ties=[{key:1,row:2,column:0},{key:1,row:1,column:2},{key:1,row:1,column:0},{key:0,row:3,column:3}];
ties.sort(p.rank);assert.deepEqual(ties.map(x=>[x.key,x.row,x.column]),[[0,3,3],[1,1,0],[1,1,2],[1,2,0]]);
assert.equal(p.signed(0),-1);assert.equal(p.signed(4294967295),4294967295/2147483648-1);
const mixed=data.words.map(w=>p.mix32(w[0]));assert.equal(new Set(mixed).size,10000);
for(const d of [0,90,180,270,360,-90])for(const v of p.turn(d))assert.ok(v===0||Math.abs(v)===1);
console.log(JSON.stringify({mixed,hashes:data.words.map(p.hashWords),turns:data.degrees.map(p.turn)}));
""", dict(module=private, words=words, degrees=degrees))
        self.assertIsNone(first_difference(result["mixed"], [ProceduralOracle.mix(w[0]) for w in words]))
        self.assertIsNone(first_difference(result["hashes"], [ProceduralOracle.hash(w) for w in words]))
        self.assertIsNone(first_difference(result["turns"], [list(ProceduralOracle.turn(d)) for d in degrees]))

    def test_layout_exact_placement_jitter_and_identity(self):
        layouts = run_node("console.log(JSON.stringify(data.map(b=>proc.scatterLayout(full(b)))));", SCATTER)
        for changes, actual in zip(SCATTER, layouts):
            expected = ProceduralOracle(changes).layout()
            mapped = [dict(column=p["i"], row=p["j"], key=p["rank"], x=p["cx"], y=p["cy"],
                           a=p["a"], b=p["b"], cos=p["c"], sin=p["s"],
                           vertices=[list(v) for v in p["vertices"]] or None) for p in expected]
            self.assertIsNone(first_difference(actual, mapped), changes)

    def test_oracle_confirmed_version_one_goldens(self):
        hashes = run_node("const {createHash}=await import('node:crypto');console.log(JSON.stringify(data.map(b=>createHash('sha256').update(mask(b).codes).digest('hex'))));",
                          [SCATTER[0], SCATTER[2], SCATTER[5], NOISE[0], NOISE[2]])
        self.assertEqual(hashes, ["1af0f36960ce20ed6fa7c96a7df89da2bf1b47945c8cd4249ff51e8a58685fa9",
            "ee0bac1b75342193049567d98d8a4f46a0c2ee58b6f2e9e4ca4511d8a600f3c4",
            "814d281a66ecdcf10f142b2ff8a3b2baf979f5c9a0fc3207a9fd8817c698205d",
            "cd0cc90a7bd1ca4521459b114003103c9e00fe0df8dff0ab9d4353657091c4ad",
            "d0bd3685385b93f569398b3a562947999ffea23c9d6aca36e346374dc2f35277"])


class ProceduralCoreTests(unittest.TestCase):
    def test_determinism_cache_eviction_inactive_settings_and_entropy_fence(self):
        run_node(r"""
const expected=mask({}), deny=()=>{throw Error('entropy forbidden')};
Math.random=Date.now=performance.now=crypto.getRandomValues=deny;
assert.deepEqual(proc.generateProceduralTip(full({})).codes,expected.codes);
const fresh=await import(new URL('./procedural_tip.js?fresh',@BRUSH_URL@));
assert.deepEqual(fresh.proceduralTip(full({})).codes,expected.codes);
assert.equal(mask({procedural_type:'noise'})===expected,false);assert.equal(mask({}),expected);
for(let seed=1;seed<=9;seed++)mask({procedural_seed:seed});
const again=mask({});assert.notEqual(again,expected);assert.deepEqual(again.codes,expected.codes);
for(const changes of [{size:128},{hardness:0},{crop_left:50},{scale_x:2},{rotation_degrees:30},
 {mirror_horizontal:true},{falloff_curve:'linear'},{value_profile:'square'},{tool:'erase'},{custom_tip:'parked'},
 {procedural_frequency:16},{tip_channel:'luminance',tip_invert:true,tip_trim:true}]){
 assert.equal(mask(changes),again);assert.deepEqual(proc.generateProceduralTip(full(changes)).codes,again.codes);
 assert.equal(brushes.prepareFootprint(full(changes)).mask,again);
}
for(const type of ['scatter','noise']) {
 const tips=[0,1,4294967295].map(procedural_seed=>mask({procedural_type:type,procedural_seed}));
 assert.notDeepEqual(tips[0].codes,tips[1].codes);assert.notDeepEqual(tips[1].codes,tips[2].codes);
 const inverted=mask({procedural_type:type,procedural_invert:true});
 for(let i=0;i<65536;i++)assert.equal(inverted.codes[i],255-tips[0].codes[i]);
}
""".replace("@BRUSH_URL@", json.dumps((CORE / "brush.js").as_uri())))

    def test_density_all_grids_nested_and_selection_independent(self):
        run_node(r"""
const layout=extra=>proc.scatterLayout(full(extra)), ids=l=>l.map(p=>`${p.column},${p.row}`);
for(let g=1;g<=32;g++)for(const D of [0,1,25,49,50,51,99,100])
 assert.equal(layout({procedural_grid:g,procedural_density:D}).length,Math.floor((g*g*D+50)/100));
let previous=[];
for(let D=0;D<=100;D++) {
 const next=layout({procedural_grid:7,procedural_density:D});
 assert.deepEqual(next.slice(0,previous.length),previous);previous=next;
}
const base=layout({});for(const extra of [{procedural_particle_size:200},{procedural_position_jitter:0},
 {procedural_size_jitter:90},{procedural_particle_rotation:123.4},{procedural_rotation_jitter:180},
 {procedural_particle_aspect:0.1},{procedural_particle_shape:'irregular'}])assert.deepEqual(ids(layout(extra)),ids(base));
for(const J of [0,100])for(const p of layout({procedural_grid:32,procedural_density:100,procedural_position_jitter:J})) {
 if(J===0){assert.equal(p.x,(2*p.column+1)/32-1);assert.equal(p.y,(2*p.row+1)/32-1);}
 else {assert.ok(p.x>=2*p.column/32-1&&p.x<2*(p.column+1)/32-1);assert.ok(p.y>=2*p.row/32-1&&p.y<2*(p.row+1)/32-1);}
}
assert.ok(mask({procedural_density:0}).empty);
assert.throws(()=>brushes.prepareFootprint(full({procedural_density:0})),{message:brushes.PROCEDURAL_EMPTY});
""")

    def test_shape_geometry_noise_identities_and_validation(self):
        run_node(r"""
const one={procedural_grid:1,procedural_density:100,procedural_position_jitter:0,procedural_size_jitter:0};
const trapezoid=mask({...one,procedural_particle_shape:'trapezoid'}).codes;
const flipped=mask({...one,procedural_particle_shape:'trapezoid',procedural_particle_rotation:180}).codes;
for(let i=0;i<65536;i++)assert.equal(trapezoid[i],flipped[65535-i]);
const rows=[];for(let y=0;y<256;y++){const n=trapezoid.slice(y*256,(y+1)*256).filter(x=>x).length;if(n)rows.push(n);}
assert.ok(rows[0]<rows.at(-1));
const diamond=mask({...one,procedural_particle_shape:'diamond'}).codes;
for(let y=0;y<256;y++)for(let x=0;x<256;x++)assert.equal(diamond[y*256+x],diamond[y*256+255-x]);
const circle=mask({}).codes;
for(const a of [-360,-123.4,0,30,77.7,90,360])assert.deepEqual(mask({procedural_particle_rotation:a,procedural_rotation_jitter:180}).codes,circle);
for(const p of proc.scatterLayout(full({procedural_particle_shape:'irregular',procedural_grid:32,procedural_density:100})))
 assert.ok(p.vertices.length>=5&&p.vertices.length<=8);
const polygon=mask({...one,procedural_particle_shape:'irregular'}).codes;
for(let k=0;k<256;k++)for(const vertical of [false,true]){
 let runs=0,inside=false;for(let j=0;j<256;j++){const covered=polygon[vertical?j*256+k:k*256+j]>0;if(covered&&!inside)runs++;inside=covered;}assert.ok(runs<=1);
}
assert.deepEqual(mask({procedural_type:'noise',procedural_persistence:0}).codes,mask({procedural_type:'noise',procedural_octaves:1}).codes);
assert.equal(new Set(mask({procedural_type:'noise',procedural_frequency:1,procedural_octaves:1}).codes).size,1);
for(const bad of [{procedural_seed:-1},{procedural_seed:4294967296},{procedural_seed:0.5},{procedural_grid:33},
 {procedural_size_jitter:100},{procedural_frequency:17},{procedural_octaves:5},{procedural_noise_low:70},
 {procedural_version:2},{procedural_particle_shape:'star'},{procedural_type:'other'}])assert.throws(()=>brushes.resolveBrush(full(bad)));
""")

    def test_bounding_box_against_full_raster_without_bounds(self):
        run_node(r"""
function inside(shape,u,v,vertices){
 if(shape==='circle')return u*u+v*v<=1;
 if(shape==='rectangle')return Math.abs(u)<=1&&Math.abs(v)<=1;
 for(let k=0;k<vertices.length;k++) {const [x,y]=vertices[k],[nx,ny]=vertices[(k+1)%vertices.length];
  if((nx-x)*(v-y)-(ny-y)*(u-x)<0)return false;}return true;
}
for(const extra of data){const b=full(extra),actual=mask(extra).codes,want=new Uint8Array(65536),particles=proc.scatterLayout(b);
 for(let py=0;py<256;py++)for(let px=0;px<256;px++)for(const p of particles){
  const dx=(2*px+1)/256-1-p.x,dy=(2*py+1)/256-1-p.y;
  if(inside(b.procedural_particle_shape,(p.cos*dx+p.sin*dy)/p.a,(-p.sin*dx+p.cos*dy)/p.b,p.vertices)){want[px+256*py]=255;break;}
 }
 assert.deepEqual(actual,want);
}
""", [SCATTER[1], SCATTER[2], SCATTER[6]])

    def test_procedural_custom_twins_all_transforms_profiles_and_strokes(self):
        run_node(r"""
for(const extra of data)for(const size of [1,16,33,128])for(const hardness of [0,30,100])
for(const rotation of [0,90,30,-123.4])for(const profile of ['uniform','linear','radial','square']) {
 const b=full({...extra,size,hardness,rotation_degrees:rotation,value_profile:profile,crop_left:13,crop_top:21,
  mirror_horizontal:true,mirror_vertical:true,scale_x:1.5,scale_y:0.5,amount:67,spacing:'custom',spacing_percent:100});
 const m=mask(b),twin={...b,shape:'custom',tip_channel:'alpha',tip_invert:false,tip_trim:false,
  tip:{width:256,height:256,alpha:m.codes,luminance:new Uint8Array(65536).fill(255)}};
 const a=engine.stampPreview(128,128,b,60.3,61.7),c=engine.stampPreview(128,128,twin,60.3,61.7);
 assert.deepEqual(a.coverage,c.coverage);assert.deepEqual(a.targets,c.targets);assert.equal(a.footprint.mask,m);
 const start=Uint8Array.from({length:16384},(_,i)=>i%256);
 const s=new engine.Stroke(start,128,128,b,60.3,61.7),t=new engine.Stroke(start,128,128,twin,60.3,61.7);
 s.add(70,72);t.add(70,72);assert.deepEqual(s.result(),t.result());
}
""", [SCATTER[2], NOISE[0]])

    def test_twin_buildup_flow_modes_tools_and_subdivision(self):
        run_node(r"""
for(const type of ['scatter','noise'])for(const hardness of [30,100])for(const tool of ['paint','erase','restore'])
for(const mode of ['normal','raise_only','lower_only'])for(const build of [false,true]) {
 const b=full({procedural_type:type,hardness,tool,apply_mode:mode,build_up:build,flow:100,amount:50,value_profile:'square'});
 const tip={width:256,height:256,alpha:mask(b).codes,luminance:new Uint8Array(65536).fill(255)};
 const before=new Uint8Array(16384).fill(100),restore=new Uint8Array(16384).fill(200);
 const a=new engine.Stroke(before,128,128,b,32,32,restore),c=new engine.Stroke(before,128,128,{...b,shape:'custom',tip},32,32,restore);
 const divided=new engine.Stroke(before,128,128,b,32,32,restore);
 a.add(82,82);c.add(82,82);for(let i=1;i<=50;i++)divided.add(32+i,32+i);
 assert.deepEqual(a.result(),c.result());assert.deepEqual(a.result(),divided.result());
 for(let i=0;i<20;i++){a.add(i%2?82:32,i%2?82:32);c.add(i%2?82:32,i%2?82:32);}
 assert.deepEqual(a.result(),c.result());
 for(const v of a.result()){assert.ok(v>=50&&v<=178);if(mode==='raise_only')assert.ok(v>=100);if(mode==='lower_only')assert.ok(v<=100);}
}
""")

    def test_hardness_envelope_and_e4_separation(self):
        run_node(r"""
for(const type of ['scatter','noise'])for(const curve of ['smooth','linear','sharper']){
 const b=full({procedural_type:type,size:128,falloff_curve:curve});const m=mask(b);
 const hard=brushes.prepareFootprint(b),soft=brushes.prepareFootprint({...b,hardness:30});assert.equal(hard.mask,soft.mask);
 for(let y=-63.5;y<64;y++)for(let x=-63.5;x<64;x++){
  const w=brushes.localCoverage(hard,x,y),sample=brushes.sampleTip(m,128+x*2,128+y*2)/255;
  assert.equal(w,sample);const r=Math.max(Math.abs(x)/64,Math.abs(y)/64);
  const envelope=r<=.3?1:r>=1?0:brushes.FALLOFF_CURVES[curve]((1-r)/.7);
  assert.equal(brushes.localCoverage(soft,x,y),sample*envelope);
 }
 const previews=['uniform','linear','radial','square'].map(value_profile=>engine.stampPreview(128,128,{...b,value_profile},64,64));
 for(const p of previews)assert.deepEqual(p.coverage,previews[0].coverage);
}
for(const value_profile of ['linear','radial','square']){
 const a=engine.stampPreview(128,128,full({value_profile,size:64}),64,64);
 const n=engine.stampPreview(128,128,full({value_profile,size:64,procedural_type:'noise'}),64,64);
 const swap=engine.stampPreview(128,128,full({value_profile,size:64,gradient_start:0,gradient_end:255}),64,64);
 for(let i=0;i<16384;i++)if(a.coverage[i]>0){assert.equal(a.targets[i]+swap.targets[i],255);if(n.coverage[i]>0)assert.equal(a.targets[i],n.targets[i]);}
}
""")

    def test_workflow_sparse_version_fallback_size_and_roundtrip(self):
        run_node(r"""
const e1=ui.editorSettings();assert.deepEqual(Object.keys(e1),['tool','size','influence','hardness','amount','influenceUnit']);
assert.deepEqual(ui.editorSettings(full({shape:'disk'})),e1);
const stored=ui.editorSettings(full({}));assert.deepEqual(stored,{...e1,shape:'procedural',procedural_version:1});
for(const s of [stored,ui.editorSettings(full({shape:'disk',procedural_seed:12})),ui.editorSettings(full({procedural_type:'noise',procedural_seed:4294967295}))]){
 assert.equal(s.procedural_version,1);assert.equal(JSON.stringify(ui.editorSettings(s)),JSON.stringify(s));
 assert.ok(JSON.stringify(s).length<1000);assert.ok(!JSON.stringify(s).includes('codes'));assert.ok(!JSON.stringify(s).includes('data:'));
 assert.deepEqual(Object.keys(s),Object.keys(e1).concat(Object.keys(brushes.BRUSH_DEFAULTS).filter(k=>k in s)));
}
for(const version of [2,undefined,'1']){
 const bad=ui.createEditorSession(empty(),{shape:'procedural',procedural_seed:99,procedural_version:version});
 assert.equal(bad.settings.shape,'disk');for(const key of brushes.PROCEDURAL_KEYS)assert.equal(bad.settings[key],brushes.BRUSH_DEFAULTS[key]);
}
const invalid=ui.createEditorSession(empty(),{shape:'procedural',procedural_version:1,procedural_seed:-1,procedural_particle_aspect:1.23,
 procedural_noise_low:80,procedural_noise_high:20}).settings;
assert.equal(invalid.shape,'procedural');assert.equal(invalid.procedural_seed,0);assert.equal(invalid.procedural_particle_aspect,1);
assert.equal(invalid.procedural_noise_low,30);assert.equal(invalid.procedural_noise_high,70);
""")

    def test_library_complete_roundtrip_import_export_quarantine_and_thumbnails(self):
        run_node(r"""
assert.deepEqual(lib.PROCEDURAL_SNAPSHOT_KEYS,brushes.PROCEDURAL_KEYS);
let saved=null,id=0;const library=lib.createBrushLibrary({read:async()=>saved,write:async text=>{saved=text;}},()=>`id${++id}`);
for(const type of ['scatter','noise']){
 const settings=full({procedural_type:type,procedural_seed:4294967295,procedural_particle_shape:'rectangle',procedural_particle_aspect:3.2,
 procedural_particle_rotation:32.1,procedural_rotation_jitter:98.7,procedural_invert:true});
 const result=await library.save(settings,'test '+type),preset=result.presets.find(p=>p.id===result.id);
 assert.deepEqual(Object.keys(preset.brush),[...lib.SNAPSHOT_KEYS,...lib.PROCEDURAL_SNAPSHOT_KEYS]);
 for(const key of lib.PROCEDURAL_SNAPSHOT_KEYS)assert.equal(preset.brush[key],settings[key]);
 assert.ok(JSON.stringify(preset.brush).length<2000);assert.ok(!saved.includes('codes')&&!saved.includes('data:'));
 const session=ui.createEditorSession(empty(),full({procedural_seed:25,procedural_grid:32}));await lib.applyBrushPreset(preset,session);
 assert.deepEqual(mask(session.settings).codes,mask(settings).codes);
 const a=new engine.Stroke(empty(),128,128,settings,64,64),b=new engine.Stroke(empty(),128,128,session.settings,64,64);assert.deepEqual(a.result(),b.result());
 const json=JSON.stringify(preset);assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(json))),json);
 const imported=await library.importPreset(json);assert.deepEqual(imported.presets.find(p=>p.id===imported.id).brush,preset.brush);
 const thumb=lib.createPresetThumbnails(),first=await thumb(preset);assert.equal(await thumb(preset),first);
 const changed=await lib.captureBrushPreset({...settings,procedural_seed:41},{id:preset.id,name:preset.name});
 const next=await thumb(changed);assert.notEqual(next,first);assert.notDeepEqual(next.pixels,first.pixels);
 await library.update(preset.id,{...settings,procedural_seed:41});assert.equal((await library.load()).presets.find(p=>p.id===preset.id).brush.procedural_seed,41);
 const future={...preset,brush:{...preset.brush,procedural_version:2}};
 const loaded=await lib.loadBrushLibrary(JSON.stringify({version:1,presets:[future]}));assert.equal(loaded.presets.length,0);
 assert.deepEqual(JSON.parse(lib.serializeBrushLibrary(loaded)).presets,[future]);
 for(const key of lib.PROCEDURAL_SNAPSHOT_KEYS){const bad={...preset,brush:{...preset.brush}};delete bad.brush[key];await assert.rejects(lib.validateBrushPreset(bad));}
 for(const bad of [{procedural_version:2},{procedural_particle_rotation:1.23},{procedural_particle_aspect:1.23},{procedural_rotation_jitter:1.23}])
  await assert.rejects(lib.validateBrushPreset({...preset,brush:{...preset.brush,...bad}}));
 const disk=await lib.captureBrushPreset(full({shape:'disk'}),{id:'disk',name:'Disk'});assert.deepEqual(Object.keys(disk.brush),lib.SNAPSHOT_KEYS);
 await lib.applyBrushPreset(disk,session);for(const key of brushes.PROCEDURAL_KEYS)assert.equal(session.settings[key],brushes.BRUSH_DEFAULTS[key]);
 await assert.rejects(lib.validateBrushPreset({...disk,brush:{...disk.brush,procedural_seed:0}}));
}
await assert.rejects(lib.captureBrushPreset(full({procedural_density:0}),{id:'empty',name:'Empty'}),{message:brushes.PROCEDURAL_EMPTY});
""")

    def test_frontend_architecture_no_generator_entropy_or_math_leakage(self):
        source = (CORE / "procedural_tip.js").read_text(encoding="utf-8")
        code = "\n".join(line.split("//")[0] for line in source.splitlines())
        self.assertEqual([line for line in code.splitlines() if line.startswith("import")],
                         ['import {hotdogCoverage} from "./hotdog_template.js";'])
        for token in ("Math.random", "Math.sin", "Math.cos", "Math.pow", "Math.exp", "Math.log", "Math.hypot", "**", "Date", "performance", "crypto", "window", "document"):
            self.assertNotIn(token, code)
        self.assertEqual(len([line for line in (CORE / "brush.js").read_text().splitlines() if line.startswith("import")]), 2)
        for filename, imports in [('hotdog_template.js', ['import {sampleTip} from "./tip_sampling.js";']),
                                  ('tip_sampling.js', [])]:
            dependency = (CORE / filename).read_text(encoding='utf-8')
            dependency = '\n'.join(line.split('//')[0] for line in dependency.splitlines())
            self.assertEqual([line for line in dependency.splitlines() if line.startswith('import')], imports)
            for token in ('Math.random', 'Math.sin', 'Math.cos', 'Date.', 'crypto.', 'document.', 'window.', 'fetch('):
                self.assertNotIn(token, dependency)
        adapter = (CORE.parent / "painted_field_node.js").read_text(encoding="utf-8")
        self.assertIn('procedural: {id: "ConditioningLayers.InfluenceFieldEditor.ProceduralTipExpanded", name: "Procedural Tip"}', adapter)
        run_node("assert.equal(globalThis.document,undefined);assert.equal(globalThis.window,undefined);")


class ProceduralEditorTests(unittest.TestCase):
    def test_conditional_ui_badges_empty_refusal_and_group_memory(self):
        run_editor(r"""
const group=()=>heading('Procedural Tip').parent;
assert.equal(group().open,false);assert.equal(group().hidden,true);
pressIn(shapeGroup(),'Procedural');assert.equal(group().hidden,false);
assert.equal(heading('Procedural Tip').textContent,'Procedural Tip · Scatter · Circle · Seed 0');
assert.ok(summary().textContent.includes('Procedural Scatter · Circle · Seed 0'));
const scatter=input('Density (%)').parent.parent,noise=input('Noise Low (%)').parent.parent;
assert.equal(scatter.hidden,false);assert.equal(noise.hidden,true);
type('Density (%)',33);pressIn(group(),'Noise');assert.equal(settings().procedural_density,33);
assert.equal(scatter.hidden,true);assert.equal(noise.hidden,false);
assert.equal(heading('Procedural Tip').textContent,'Procedural Tip · Noise · Seed 0');
assert.ok(summary().textContent.includes('Procedural Noise · Seed 0'));
pressIn(group(),'Scatter');type('Density (%)',0);assert.equal(find('procedural-status').textContent,brushes.PROCEDURAL_EMPTY);
click(64,64);assert.equal(error(),brushes.PROCEDURAL_EMPTY);assert.equal(session().history.undoEntries.length,0);
type('Density (%)',50);assert.equal(error(),'');assert.equal(find('procedural-status').hidden,true);
group().open=true;fire(group(),'toggle');assert.deepEqual(writes,[['procedural',true]]);
controller.cancel();controller=open();dom.flush();assert.equal(group().open,true);
assert.ok(!JSON.stringify(ui.editorSettings(settings())).includes('Expanded'));
pressIn(shapeGroup(),'Procedural');pressIn(group(),'Noise');pressIn(shapeGroup(),'Disk');assert.equal(group().hidden,true);
const css=all().find(e=>e.tagName==='STYLE').textContent;
assert.ok(css.indexOf('.procedural-status')<css.indexOf('.cl-field-editor [hidden] {display:none;}'));
""")

    def test_new_seed_commits_visible_render_persists_cancel_and_no_history(self):
        run_editor(r"""
pressIn(shapeGroup(),'Procedural');const initial=session().codes.slice();
let draw=12345;crypto.getRandomValues=array=>{array[0]=draw;return array;};
const before=find('procedural-thumbnail').pixels.slice();press('New Seed');
assert.equal(settings().procedural_seed,12345);assert.equal(input('Seed').value,'12345');
assert.notDeepEqual(find('procedural-thumbnail').pixels,before);assert.deepEqual(session().codes,initial);
assert.equal(session().history.undoEntries.length,0);
const captured=await lib.captureBrushPreset(settings(),{id:'chosen',name:'chosen'});assert.equal(captured.brush.procedural_seed,12345);
press('New Seed');assert.equal(settings().procedural_seed,12346);
const e=input('Seed');fire(e,'pointerdown');fire(e,'pointerup');e.value='4294967295';draw=4294967295;
press('New Seed');assert.equal(settings().procedural_seed,0);assert.equal(e.value,'0');
draw=6789;press('New Seed');const expected=mask({procedural_seed:6789}).codes;
assert.deepEqual(brushes.proceduralMask(settings()).codes,expected);
press('Done');await settle();assert.equal(result.settings.procedural_seed,6789);assert.deepEqual(result.codes,initial);
controller=open(initial,result.settings);dom.flush();assert.equal(settings().procedural_seed,6789);
press('New Seed');controller.cancel();controller=open(initial,result.settings);dom.flush();assert.equal(settings().procedural_seed,6789);
""")

    def test_numeric_all_fourteen_drag_type_escape_arrows_modifiers_limits_and_pairs(self):
        run_editor(r"""
pressIn(shapeGroup(),'Procedural');assert.equal(all().filter(e=>e.type==='text').length,41);
const controls=[['Seed','procedural_seed',0,4294967295,1,true],['Particle Grid (slots per side)','procedural_grid',1,32,1,true],
 ['Density (%)','procedural_density',0,100,1,true],['Particle Size (% of slot)','procedural_particle_size',1,200,1,true],
 ['Particle Aspect (W:H)','procedural_particle_aspect',.1,10,.1,false],['Size Jitter (±%)','procedural_size_jitter',0,90,1,true],
 ['Position Jitter (%)','procedural_position_jitter',0,100,1,true],['Particle Rotation (°)','procedural_particle_rotation',-360,360,1,false],
 ['Rotation Jitter (±°)','procedural_rotation_jitter',0,180,1,false],['Frequency (periods across tip)','procedural_frequency',1,16,1,true],
 ['Octaves','procedural_octaves',1,4,1,true],['Persistence (%)','procedural_persistence',0,100,1,true],
 ['Noise Low (%)','procedural_noise_low',0,99,1,true],['Noise High (%)','procedural_noise_high',1,100,1,true]];
const resetPair=key=>{if(key==='procedural_noise_low')type('Noise High (%)',100);if(key==='procedural_noise_high')type('Noise Low (%)',0);};
for(const [label,key,min,max,step,integer] of controls){
 resetPair(key);const e=input(label),middle=integer?Math.floor((min+max)/2):Math.round((min+max)*5)/10;
 type(label,middle);assert.equal(settings()[key],middle);
 for(const [mods,scale] of [[{},1],[{shiftKey:true},.1],[{ctrlKey:true},10],[{metaKey:true},10]]){
  type(label,middle);fire(e,'pointerdown',{clientX:0});fire(e,'pointermove',{clientX:4,...mods});fire(e,'pointerup',{clientX:4});dom.flush();
  const raw=Math.min(max,Math.max(min,middle+4*step*scale)),want=integer?Math.round(raw):Math.round(raw*10)/10;
  assert.equal(settings()[key],want,label);
 }
 type(label,middle);fire(e,'pointerdown');fire(e,'pointerup');e.value='garbage';fire(window,'keydown',{key:'Enter',target:e});dom.flush();assert.equal(settings()[key],middle);
 fire(e,'pointerdown');fire(e,'pointerup');e.value=String(min);fire(window,'keydown',{key:'Escape',target:e});dom.flush();assert.equal(settings()[key],middle);
 fire(e,'keydown',{key:'ArrowDown'});dom.flush();assert.equal(settings()[key],integer?middle-step:Math.round((middle-step)*10)/10);
 fire(e,'keydown',{key:'ArrowUp'});dom.flush();assert.equal(settings()[key],middle);
 type(label,min);assert.equal(settings()[key],min);type(label,max);assert.equal(settings()[key],max);
 if(!key.startsWith('procedural_noise_')){type(label,min-100);assert.equal(settings()[key],min);type(label,max+100);assert.equal(settings()[key],max);}
 type(label,middle);
}
type('Noise Low (%)',30);type('Noise High (%)',70);type('Noise Low (%)',80);
assert.equal(settings().procedural_noise_low,30);assert.equal(error(),'Noise Low must stay below Noise High. Noise Low 80% was not applied.');
type('Noise High (%)',30);assert.equal(settings().procedural_noise_high,70);
type('Seed',4294967295);assert.equal(settings().procedural_seed,4294967295);
// All one-decimal particle rotations, without generating 7,201 tips: controls remain active under Disk.
pressIn(shapeGroup(),'Disk');for(let n=-3600;n<=3600;n++){type('Particle Rotation (°)',n/10);assert.equal(settings().procedural_particle_rotation,n/10);}
assert.equal(session().history.undoEntries.length,0);
""")

    def test_preview_thumbnail_heat_pan_zoom_and_clicked_stamp_exact(self):
        run_editor(r"""
for(const typeName of ['Scatter','Noise'])for(const hardness of [30,100]){
 await reopen(empty(),full({size:33,hardness,crop_left:20,crop_bottom:15,mirror_horizontal:true,scale_x:1.5,scale_y:.5,
  rotation_degrees:-123.4,value_profile:'linear',procedural_particle_shape:'trapezoid'}));
 pressIn(heading('Procedural Tip').parent,typeName);
 const m=brushes.proceduralMask(settings()),pixels=find('procedural-thumbnail').pixels;
 for(let i=0;i<65536;i++)assert.equal(pixels[i*4],m.codes[i]);
 assert.equal(find('procedural-crop').style.left,'20%');assert.equal(find('procedural-crop').style.bottom,'15%');
 for(const heat of [false,true]){
  if(heat)press('Heat View');pointer('pointermove',64.25,70.5);dom.flush();
  const p=engine.stampPreview(128,128,engineBrush(),64.25,70.5);
  assert.equal(p.footprint.mask,m);
  for(let i=0;i<16384;i++){
   assert.equal(preview().pixels[i*4+3],p.coverage[i]>0?Math.max(1,Math.round(p.coverage[i]*160)):0);
   if(p.coverage[i]>0)assert.deepEqual([...preview().pixels.slice(i*4,i*4+3)],heat?view.heatColor(p.targets[i]):[p.targets[i],p.targets[i],p.targets[i]]);
  }
 }
 click(64.25,70.5);const stroke=new engine.Stroke(empty(),128,128,engineBrush(),64.25,70.5);
 assert.deepEqual(session().codes,stroke.result());assert.equal(session().history.undoEntries.length,1);
 for(let i=0;i<3;i++)fire(find('viewport'),'wheel',{clientX:300,clientY:200,deltaY:-1});
 fire(find('viewport'),'pointerdown',{button:1,clientX:50,clientY:50});fire(find('viewport'),'pointermove',{clientX:90,clientY:20});fire(find('viewport'),'pointerup',{button:1});dom.flush();
 const [px,py,z]=canvas().style.transform.match(/translate\(([-\d.]+)px,([-\d.]+)px\) scale\(([-\d.]+)\)/).slice(1).map(Number);
 fire(find('viewport'),'pointermove',{clientX:px+64.25*z,clientY:py+70.5*z});dom.flush();
 const zoomed=engine.stampPreview(128,128,engineBrush(),64.25,70.5);
 for(let i=0;i<16384;i++)assert.equal(preview().pixels[i*4+3],zoomed.coverage[i]>0?Math.max(1,Math.round(zoomed.coverage[i]*160)):0);
}
""")

    def test_reset_every_parameter_default_e1_and_erase_restore_shift_history(self):
        run_editor(r"""
const {createHash}=await import('node:crypto');
for(const tool of ['Paint','Erase','Restore']){
 const initial=new Uint8Array(16384).fill(100);await reopen(initial,full({size:33,procedural_type:'noise',procedural_seed:123,procedural_invert:true}));
 session().codes.fill(70);press(tool);click(40,40);
 const stroke=new engine.Stroke(new Uint8Array(16384).fill(70),128,128,engineBrush(),40,40,initial);
 assert.deepEqual(session().codes,stroke.result());assert.equal(session().history.undoEntries.length,1);
 const before=session().codes.slice();pointer('pointerdown',80,80,{shiftKey:true});dom.flush();
 const line=new engine.Stroke(before,128,128,engineBrush(),40,40,initial);line.add(80,80);
 assert.deepEqual(session().codes,line.result());assert.equal(session().history.undoEntries.length,2);
}
await reopen(empty(),full({procedural_seed:4294967295,procedural_type:'noise',procedural_invert:true,procedural_particle_shape:'irregular',
 procedural_grid:32,procedural_density:100,procedural_particle_size:200,procedural_particle_aspect:10,procedural_size_jitter:90,
 procedural_position_jitter:100,procedural_particle_rotation:360,procedural_rotation_jitter:180,procedural_frequency:16,
 procedural_octaves:4,procedural_persistence:100,procedural_noise_low:0,procedural_noise_high:100}));
press('Reset Brush');for(const key of Object.keys(brushes.BRUSH_DEFAULTS))assert.equal(settings()[key],brushes.BRUSH_DEFAULTS[key],key);
assert.deepEqual(ui.editorSettings(settings()),ui.editorSettings());
click(64,64);const baseline=new engine.Stroke(empty(),128,128,brush,64,64);assert.deepEqual(session().codes,baseline.result());
""")


if __name__ == "__main__":
    unittest.main()
