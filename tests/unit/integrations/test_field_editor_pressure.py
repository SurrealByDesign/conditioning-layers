"""E9 offline pressure contracts. Oracles derive from design §§5,10,12–18.

Python owns the independent slot sequence. JS replays those slots through only
retained footprint/profile primitives, with an independent per-cell reference.
No browser, host, device or live qualification is claimed.
"""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import re
import tempfile
import unittest

from test_field_editor_field_tools import run_node as retained_node, UI, CORE
from test_field_editor_custom_tip import png, b64


def half(value):
    floor = math.floor(value)
    return floor + (value - floor >= 0.5)


def scaled(base, code):
    return max(1, (2 * base * code + 65535) // 131070)


def slots(path, brush):
    """Normative run lattice and reduced pressure pieces, independent of JS."""
    out = []
    active, last, held, run, gap = False, None, 0, None, None

    def emit(x, y, code):
        out.append([x, y, code])
        size = scaled(brush['size'], code) if brush.get('pressure_size', True) else brush['size']
        return half(size * brush.get('spacing_percent', 25) * 256 / 100) if brush.get('spacing') == 'custom' else 64

    for x, y, code in path:
        end = [math.floor(max(-4096, min(4096, v)) * 256 + 0.5) for v in [x, y]]
        if not active:
            held = code
            if code > 0:
                active, last = True, end
                gap = emit(end[0] / 256, end[1] / 256, code)
            continue
        dx, dy = end[0] - last[0], end[1] - last[1]
        n = math.gcd(dx, dy)
        if not n:
            if code != held:
                held = code
                if run is not None:
                    run['piece'] = None
            continue
        ux, uy = dx // n, dy // n
        if run is None or (ux, uy) != run['direction']:
            remainder = run['next'] - run['n'] * run['length'] if run else gap
            run = dict(start=last, direction=(ux, uy), length=math.sqrt(ux*ux + uy*uy),
                       next=remainder, n=0, piece=None)
        p = run['piece']
        if p is None or (code - p[1]) * p[3] != p[2] * (run['n'] + n - p[0]):
            divisor = math.gcd(code - held, n)
            p = run['piece'] = (run['n'], held, (code-held)//divisor, n//divisor)
        run['n'] += n
        while run['next'] <= run['n'] * run['length']:
            along = run['next'] / run['length']
            value = p[1] + p[2] * (along - p[0]) / p[3]
            pressure = max(0, min(65535, half(value)))
            run['next'] += emit((run['start'][0] + along*ux)/256,
                                (run['start'][1] + along*uy)/256, pressure)
        last, held = end, code
    return out


REFERENCE = r"""
const profiles = await import(new URL('./value_profile.js', @ENGINE@));
const full = b => ({...brush,...brushes.BRUSH_DEFAULTS,pressure_enabled:true,...b});
const scaleRef = (base,p) => Math.max(1,Math.floor((2*base*p+65535)/131070));
const halfRef = v => {const n=Math.floor(v);return n+(v-n>=0.5?1:0);};
const make = (b,path,before=empty(),selection=null,restore=empty()) => {
 const s=new engine.PressureStroke(before,128,128,full(b),path[0][0],path[0][1],restore,selection,path[0][2]);
 for(const p of path.slice(1))s.add(...p);return s;
};
// Deliberately no PressureStroke, pressureCode, scaledControl, slot or stampPreview calls.
function reference(b,slots,before=empty(),selection=null,restore=empty()) {
 b=full(b);const n=before.length,C=new Float64Array(n),K=b.pressure_amount?new Uint8Array(n):null;
 const T=b.tool==='paint'&&b.value_profile!=='uniform'?new Uint8Array(n):null;
 const W=b.build_up?new Float64Array(n):C,KS=K?(b.build_up?new Uint8Array(n):K):null,Z=new Float64Array(n);
 const local=[0,0],prepared=new Map();
 for(let [x,y,p] of slots){
  if(p===0)continue;
  const size=b.pressure_size?scaleRef(b.size,p):b.size,a=b.pressure_amount?scaleRef(b.amount,p):b.amount;
  if(!prepared.has(size)){
   const sb={...b,size},fp=brushes.prepareFootprint(sb);
   prepared.set(size,{fp,profile:T?profiles.prepareProfile(sb,fp):null,spacing:engine.stampSpacing(sb)});
  }
  const {fp,profile,spacing}=prepared.get(size);
  const f=b.build_up?engine.flowFactor(b.pressure_flow?scaleRef(b.flow,p):b.flow,spacing,size):0;
  if(fp.hard)[x,y]=brushes.snapAnchor(fp,x,y);
  const [ex,ey]=fp.extent;
  for(let row=Math.max(0,Math.floor(y-ey)-1);row<Math.min(128,Math.ceil(y+ey)+1);row++)
   for(let col=Math.max(0,Math.floor(x-ex)-1);col<Math.min(128,Math.ceil(x+ex)+1);col++){
    brushes.footprintLocal(fp,col+0.5-x,row+0.5-y,local);
    const w=brushes.localCoverage(fp,...local);if(!(w>0))continue;
    const i=row*128+col,m=C[i],k=K?K[i]:a;
    if(b.build_up){
     if(a===k)C[i]=Math.min(1,m+(1-m)*(f*w));
     else if(a>k){const c=m*k/a;C[i]=Math.min(1,c+(1-c)*(f*w));K[i]=a;}
     else {const r=a/k;if(m<r)C[i]=Math.min(r,m+(r-m)*(f*w));}
    }
    if(T){
     const key=KS?KS[i]:a,s=W[i];
     const lhs=key===a?w:a*w,rhs=key===a?s:key*s;
     const d=(col+0.5-x)*(col+0.5-x)+(row+0.5-y)*(row+0.5-y);
     if(lhs>rhs||(lhs===rhs&&d<Z[i])){W[i]=w;if(KS)KS[i]=a;Z[i]=d;T[i]=profiles.profileTarget(profile,...local);}
    }else if(!b.build_up&& (a===k?w>m:a*w>k*m)){C[i]=w;if(K)K[i]=a;}
   }
 }
 const result=before.map((v,i)=>{
  if(selection!==null&&!selection[i])return v;
  const target=T?T[i]:b.tool==='erase'?0:b.tool==='restore'?restore[i]:b.influence;
  const d=((target-v)*(K?K[i]:b.amount))*C[i]/100,next=v+Math.sign(d)*halfRef(Math.abs(d));
  return b.apply_mode==='raise_only'?Math.max(v,next):b.apply_mode==='lower_only'?Math.min(v,next):next;
 });return {result,coverage:C,targets:T,amounts:K};
}
const compareReference=(b,path,slots,before=empty(),selection=null,restore=empty())=>{
 const s=make(b,path,before,selection,restore),r=reference(b,slots,before,selection,restore);
 eq(s.result(),r.result);eq(s.coverage,r.coverage,'coverage');
 if(r.targets)eq(s.targets,r.targets,'targets');if(r.amounts)eq(s.amounts,r.amounts,'amounts');return s;
};
""".replace('@ENGINE@', json.dumps((CORE / 'engine.js').as_uri()))


def run_node(body, data=None):
    return retained_node(REFERENCE + body, data)


def run_editor(body, data=None):
    return run_node(UI + body, data)


def fixtures(count, seed=901):
    rng = random.Random(seed)
    cases = []
    for i in range(count):
        brush = dict(size=rng.randint(1, 24), amount=rng.randint(1, 100), flow=rng.randint(1, 100),
                     hardness=rng.choice([0, 45, 100]), build_up=bool(i % 2),
                     pressure_size=bool((i % 7 + 1) & 1), pressure_amount=bool((i % 7 + 1) & 2),
                     pressure_flow=bool((i % 7 + 1) & 4),
                     value_profile=rng.choice(['uniform', 'linear', 'radial', 'square']),
                     shape=rng.choice(['disk', 'square', 'diamond']),
                     spacing=rng.choice(['auto', 'custom']), spacing_percent=rng.choice([1, 25, 100, 1000]))
        # Flow alone without Build-up has no pressure path, per §9.
        if not brush['pressure_size'] and not brush['pressure_amount']:
            brush['build_up'] = True
        path = [[rng.randrange(10, 35), rng.randrange(10, 35), rng.randrange(65536)] for _ in range(4)]
        cases.append(dict(brush=brush, path=path, slots=slots(path, brush)))
    return cases


class PressureTests(unittest.TestCase):
    def test_t01_engine_prefix_and_architecture(self):
        source = (CORE / 'engine.js').read_bytes()
        self.assertEqual(hashlib.sha256(source[:10323]).hexdigest(),
                         '2c3f4aba3aaa2dadf28f9e4f84d7d0598f5339c450b6869fc3bc414051dd159d')
        text = source.decode('utf-8')
        self.assertNotIn('visitStamp', text.split('export class PressureStroke')[1])
        self.assertEqual(len(re.findall(r'^import ', text, re.M)), 2)
        for filename, count in [('brush.js', 2), ('view.js', 1)]:
            self.assertEqual(len(re.findall(r'^import ', (CORE/filename).read_text(encoding='utf-8'), re.M)), count)
        for name in ['engine.js', 'editor_ui.js']:
            source = (CORE/name).read_text(encoding='utf-8')
            for forbidden in ['tiltX', 'tiltY', 'twist', 'tangentialPressure', 'altitudeAngle',
                              'azimuthAngle', 'getPredictedEvents', 'pointerrawupdate']:
                self.assertNotIn(forbidden, source)
        run_node('assert.equal(globalThis.document,undefined);assert.equal(globalThis.window,undefined);')

    def test_t04_canonicalization(self):
        run_node(r"""
for(const [raw,code] of [[0,0],[-1,0],[2,65535],[0.5,32768],[1,65535],[1e-12,0],
 [NaN,65535],[Infinity,65535],[-Infinity,65535],[undefined,65535],[null,65535],['0',65535]])assert.equal(engine.pressureCode(raw),code);
for(let c=0;c<=65535;c++)assert.equal(engine.pressureCode(c/65535),c);
for(const L of [255,256,1024,2047,2048,4095,4096,8191,8192]){
 let last=-1;for(let n=0;n<=L;n++){const c=engine.pressureCode(n/L);assert.ok(c>last);last=c;}
}
""")

    def test_t05_exhaustive_fixed_point(self):
        # Fraction establishes the rounding rule; integer numerators exhaust its domain.
        for base in range(1, 129):
            for code in [0, 1, 6143, 6144, 32767, 32768, 63488, 65534, 65535]:
                q = Fraction(base * code, 65535)
                self.assertEqual(scaled(base, code), max(1, (q + Fraction(1, 2)).numerator // (q + Fraction(1, 2)).denominator))
        expected = hashlib.sha256(bytes(scaled(base, code) for base in range(1, 129) for code in range(65536))).hexdigest()
        percents = hashlib.sha256(bytes((200*c+65535)//131070 for c in range(65536))).hexdigest()
        run_node(r"""
const {createHash}=await import('node:crypto');const values=new Uint8Array(128*65536);let i=0;
for(let b=1;b<=128;b++){let last=0;for(let p=0;p<=65535;p++){
 const v=engine.scaledControl(b,p);assert.ok(v>=last&&v>=1&&v<=b);last=v;values[i++]=v;
}assert.equal(last,b);}
assert.equal(createHash('sha256').update(values).digest('hex'),data.expected);
const percents=Uint8Array.from({length:65536},(_,p)=>engine.pressurePercent(p));
assert.equal(createHash('sha256').update(percents).digest('hex'),data.percents);
""", dict(expected=expected, percents=percents))

    def test_t06_contact_zero_and_stationary(self):
        paths = [[[10, 10, 0], [10, 10, 30000]], [[1, 1, 0], [5, 5, 0], [10, 10, 30000]],
                 [[10, 10, 0], [30, 30, 0]], [[10, 10, 65535], [20, 10, 0], [25, 10, 0], [30, 10, 65535]],
                 [[10, 10, 1000], [20, 10, 30000], [20, 10, 60000], [30, 10, 1000]]]
        b = dict(size=16, spacing='custom', spacing_percent=25)
        run_node(r"""
for(const c of data)compareReference(c.brush,c.path,c.slots);
eq(make(data[0].brush,data[0].path).result(),make(data[0].brush,[[10,10,30000]]).result());
eq(make(data[1].brush,data[1].path).result(),make(data[1].brush,[[10,10,30000]]).result());
eq(make(data[2].brush,data[2].path).result(),empty());
const original=engine.PressureStroke.prototype.slot;let calls=0;
engine.PressureStroke.prototype.slot=function(...args){calls++;return original.apply(this,args);};
const s=make({},[[10,10,30000],[10,10,60000]]);assert.equal(calls,1);assert.equal(s.pressure,60000);
""", [dict(brush=b, path=p, slots=slots(p, b)) for p in paths])

    def test_t06b_stationary_piece_reset_exact_field(self):
        # §§12,15: first establish a piece, then change pressure at EXACTLY
        # the same position. The last endpoint is on the OLD line, so only
        # the mandatory reset makes the next segment start at code 50000.
        path = [[10.5, 10.5, 10000], [12.5, 10.5, 20000],
                [12.5, 10.5, 50000], [14.5, 10.5, 30000]]
        b = dict(shape='square', size=1, hardness=100, influence=255, amount=100,
                 build_up=False, pressure_size=False, pressure_amount=True,
                 spacing='custom', spacing_percent=100)
        expected_slots = [[10.5, 10.5, 10000], [11.5, 10.5, 15000],
                          [12.5, 10.5, 20000], [13.5, 10.5, 40000],
                          [14.5, 10.5, 30000]]
        self.assertEqual(slots(path, b), expected_slots)
        # Exact integer formula, no product pressure helper: effective Amount
        # [15,23,31,61,46], full coverage on five isolated cell centres.
        amounts = [scaled(100, p) for _, _, p in expected_slots]
        self.assertEqual(amounts, [15, 23, 31, 61, 46])
        codes = [(2 * 255 * a + 100) // 200 for a in amounts]
        self.assertEqual(codes, [38, 59, 79, 156, 117])
        run_editor(r"""
const expected=empty();data.codes.forEach((v,j)=>expected[10*128+10+j]=v);
const original=engine.PressureStroke.prototype.slot,actual=[];
engine.PressureStroke.prototype.slot=function(x,y,p){actual.push([x,y,p]);return original.call(this,x,y,p);};
const s=make(data.brush,data.path);
// Field first: a missing reset paints (13,10) to 97 instead of 156.
eq(s.result(),expected);assert.deepEqual(actual,data.slots);
engine.PressureStroke.prototype.slot=original;
compareReference(data.brush,data.path,data.slots);
const prefix=make(data.brush,data.path.slice(0,2)),before=prefix.result();
assert.deepEqual(prefix.run.piece,{n0:0,p0:10000,num:625,den:32});
prefix.add(...data.path[2]);eq(prefix.result(),before);assert.equal(prefix.run.piece,null);
prefix.add(...data.path[3]);assert.deepEqual(prefix.run.piece,{n0:512,p0:50000,num:-625,den:16});
const fine=[data.path[0],data.slots[1],data.path[1],data.path[2],data.path[2],data.slots[3],data.path[3]];
eq(make(data.brush,fine).result(),expected);
const noResetPath=[data.path[0],data.path[1],data.path[3]];
const oldLine=make(data.brush,noResetPath).result();assert.equal(oldLine[10*128+13],97);
assert.equal(expected[10*128+13],156);
await reopen(empty(),{...brush,...data.brush,pressure_enabled:true});
for(let i=0;i<data.path.length;i++){
 const [x,y,p]=data.path[i];assert.equal(engine.pressureCode(p/65535),p);
 pointer(i?'pointermove':'pointerdown',x,y,{pointerType:'pen',pressure:p/65535});
}
pointer('pointerup',14.5,10.5,{pointerType:'pen',pressure:0});dom.flush();eq(session().codes,expected);
""", dict(brush=b, path=path, slots=expected_slots, codes=codes))

    def test_t07_constant_pressure_all_brushes(self):
        run_node(r"""
const tip={width:9,height:5,luminance:Uint8Array.from({length:45},(_,i)=>i*5+20),alpha:new Uint8Array(45).fill(255)};
let cases=0;
for(const kind of ['disk','square','diamond','custom','scatter','noise'])for(const hardness of [0,100])
for(const build_up of [false,true])for(const value_profile of ['uniform','linear','radial'])for(const p of [1,700,4100,12345,32768,50000,65534,65535]){
 const shape=['scatter','noise'].includes(kind)?'procedural':kind;
 const b=full({shape,procedural_type:kind==='noise'?'noise':'scatter',tip,hardness,build_up,value_profile,size:17,amount:63,flow:37,
 pressure_amount:true,pressure_flow:true,spacing:'custom',spacing_percent:25});
 const path=[[10,10,p],[23,14,p],[20,28,p]],s=make(b,path);
 const ordinary=new engine.Stroke(empty(),128,128,{...b,size:scaleRef(b.size,p),amount:scaleRef(b.amount,p),flow:build_up?scaleRef(b.flow,p):b.flow},10,10);
 for(const [x,y] of path.slice(1))ordinary.add(x,y);
 eq(s.result(),ordinary.result());eq(s.coverage,ordinary.coverage);if(s.targets)eq(s.targets,ordinary.targets);cases++;
}assert.equal(cases,576);
""")

    def test_t08_amount_ceiling_recurrence(self):
        run_node(r"""
let seed=801;const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
for(let trial=0;trial<200000;trial++){
 let C=0,K=0,E=0;
 for(let j=0;j<1+trial%30;j++){
  const a=1+Math.floor(random()*100),f=random(),w=random(),m=C,k=K;
  E=E+Math.max(0,a/100-E)*f*w;
  if(a===k)C=Math.min(1,m+(1-m)*(f*w));
  else if(a>k){const c=m*k/a;C=Math.min(1,c+(1-c)*(f*w));K=a;}
  else {const r=a/k;if(m<r)C=Math.min(r,m+(r-m)*(f*w));}
  assert.ok(Math.abs(K*C/100-E)<1e-12);
 }
}
for(const build_up of [false,true])for(const pressures of [[60000,10000],[10000,60000],[16000,16000]]){
 const b=full({size:9,amount:100,flow:50,build_up,pressure_size:false,pressure_amount:true});
 const s=make(b,[[20,20,pressures[0]],[24,20,pressures[1]],[20,20,pressures[1]],[24,20,pressures[1]]]);
 const limit=halfRef(255*scaleRef(100,Math.max(...pressures))/100);
 assert.ok(s.result().every(v=>v<=limit));
}
const b={size:1,amount:80,pressure_size:false,pressure_amount:true};
const s=make(b,[[10,10,60000]]),before=s.result();s.slot(10,10,1000);eq(s.result(),before);
""")

    def test_t09_flow_inert_and_distance(self):
        run_node(r"""
assert.equal(engine.pressureMappings(full({pressure_size:false,pressure_flow:true})),null);
assert.equal(engine.pressureMappings(full({pressure_size:false})),null);
assert.equal(engine.pressureMappings(full({pressure_enabled:false,pressure_amount:true})),null);
const b=full({pressure_size:false,pressure_amount:true});
eq(make(b,[[10,10,12000],[30,10,50000]]).result(),make({...b,pressure_flow:true},[[10,10,12000],[30,10,50000]]).result());
""")

    def test_t14_lower_ceiling_binary64_clamp(self):
        # §18 binds binary64 evaluation, not just the real-number recurrence.
        # Seed a valid per-cell (K,C) state to isolate the lower-ceiling branch;
        # this is a state-level unit fixture, not a claimed pointer-path replay.
        run_node(r"""
const b={shape:'square',size:1,hardness:100,amount:100,flow:100,build_up:true,
 pressure_size:false,pressure_amount:true,pressure_flow:false};
const s=make(b,[[10.5,10.5,65535]]),i=10*128+10;
const m=3/36028797018963968,r=1/3;
assert.ok(m+(r-m)>r,'binary64 overshoot must be exercised');
s.amounts[i]=3;s.coverage[i]=m;
// Code 655 gives Amount 1 by the independent integer formula; Flow 100,
// full coverage give f*w=1. The normative ceiling is exactly 1/3.
assert.equal(scaleRef(100,655),1);
s.slot(10.5,10.5,655);
assert.equal(s.amounts[i],3);assert.equal(s.coverage[i],r);
assert.equal(s.result()[i],3);
""")

    def test_t10_thousand_independent_field_oracles(self):
        run_node('for(const c of data)compareReference(c.brush,c.path,c.slots);', fixtures(1000))

    def test_t11_python_slots_and_t13_spacing(self):
        cases = fixtures(300, 119)
        for percent in [1, 25, 1000]:
            b = dict(size=64, spacing='custom', spacing_percent=percent)
            for path in [[[4, 4, 1], [124, 4, 65535]], [[4, 4, 65535], [124, 4, 1]],
                         [[4, 4, 1], [4, 124, 65535]], [[4, 4, 1], [124, 124, 65535]]]:
                cases.append(dict(brush=b, path=path, slots=slots(path, b)))
        run_node(r"""
const original=engine.PressureStroke.prototype.slot;let actual;
engine.PressureStroke.prototype.slot=function(x,y,p){actual.push([x,y,p]);return original.call(this,x,y,p);};
for(const c of data){actual=[];make(c.brush,c.path);assert.equal(actual.length,c.slots.length);
 for(let i=0;i<actual.length;i++)eq(actual[i],c.slots[i],'slot '+i);
}
""", cases)

    def test_t12_subdivision_1500(self):
        rng = random.Random(912)
        cases = []
        for i in range(1500):
            x, y, p = 20*256, 20*256, 30000
            coarse, fine = [[x/256, y/256, p]], [[x/256, y/256, p]]
            for _ in range(rng.randint(1, 4)):
                ux, uy = rng.choice([(1, 0), (0, 1), (1, 1), (3, 4), (5, 12), (255, 1), (-5, 12)])
                den, slope = rng.randint(1, 16), rng.randint(-100, 100)
                steps = rng.randint(2, 8)
                for k in range(1, steps+1):
                    fine.append([(x+k*den*ux)/256, (y+k*den*uy)/256, p+k*slope])
                    if rng.random()<0.2:
                        fine.append(fine[-1])
                x, y, p = x+steps*den*ux, y+steps*den*uy, p+steps*slope
                coarse.append([x/256, y/256, p])
            b = dict(size=1+i%16, pressure_amount=True, pressure_flow=True, build_up=bool(i%2),
                     hardness=100 if i%3 else 30, value_profile=['uniform', 'linear', 'radial', 'square'][i%4],
                     shape=['disk', 'square', 'diamond', 'custom', 'procedural'][i%5],
                     procedural_type='noise' if i%2 else 'scatter',
                     spacing='custom', spacing_percent=[1,25,100,1000][i%4])
            cases.append(dict(brush=b, coarse=coarse, fine=fine))
        run_node(r"""
const tip={width:9,height:5,luminance:Uint8Array.from({length:45},(_,i)=>i*5+20),alpha:new Uint8Array(45).fill(200)};
for(const c of data){const brush={...c.brush,tip},a=make(brush,c.coarse),b=make(brush,c.fine);
 eq(a.result(),b.result());eq(a.coverage,b.coverage);eq(a.amounts,b.amounts);if(a.targets)eq(a.targets,b.targets);}
""", cases)

    def test_t12b_exact_five_twelve_tie(self):
        run_node(r"""
const b={size:1,amount:9,spacing:'custom',spacing_percent:1,pressure_size:false,pressure_amount:true};
const coarse=[[10,10,1000],[2730/256,2968/256,10945]],fine=[coarse[0],[2590/256,2632/256,2755],coarse[1]];
const a=make(b,coarse),c=make(b,fine);eq(a.result(),c.result());eq(a.coverage,c.coverage);eq(a.amounts,c.amounts);
assert.equal(a.result()[11*128+10],3);
""")

    def test_t15_targets_tools_profiles(self):
        cases = fixtures(45, 915)
        run_node(r"""
const before=Uint8Array.from({length:16384},(_,i)=>i%256),restore=before.map(v=>255-v);
for(const c of data)for(const tool of ['paint','erase','restore'])for(const apply_mode of ['normal','raise_only','lower_only']){
 const b={...c.brush,tool,apply_mode};compareReference(b,c.path,c.slots,before,null,restore);
}
for(const value_profile of ['linear','radial','square']){
 const b={size:17,pressure_amount:true,gradient_start:117,gradient_end:117,value_profile};
 const path=[[10,10,1000],[30,15,50000]];
 eq(make(b,path).result(),make({...b,value_profile:'uniform',influence:117},path).result());
}
""", cases)

    def test_t16_custom_and_t17_procedural_oracle(self):
        cases = fixtures(24, 916)
        run_node(r"""
const tip={width:9,height:5,luminance:Uint8Array.from({length:45},(_,i)=>i*5+20),alpha:new Uint8Array(45).fill(200)};
for(const c of data)for(const shape of ['custom','procedural'])for(const channel of ['alpha','luminance','alpha_luminance']){
 const b={...c.brush,shape,tip,tip_channel:channel,procedural_type:c.brush.build_up?'noise':'scatter'};
 const s=compareReference(b,c.path,c.slots);assert.ok(s.prepared.size<=b.size);
 for(const [size,e]of s.prepared){assert.equal(e,s.prepare(size));}
}
""", cases)

    def test_t16b_tip_decode_and_generation_spies(self):
        # ESM bindings cannot be monkey-patched. Instrument scratch modules
        # with entry counters only, preserving the real repository source.
        with tempfile.TemporaryDirectory(prefix='conditioning-e9-tip-spies-') as directory:
            scratch = Path(directory)
            for source in CORE.glob('*.js'):
                (scratch / source.name).write_bytes(source.read_bytes())
            for filename, signature, counter in [
                ('custom_tip.js', 'export async function decodeTipDataUrl(text) {', 'e9Decode'),
                ('procedural_tip.js', 'export function generateProceduralTip(b) {', 'e9Generate'),
            ]:
                target = scratch / filename
                source = target.read_text(encoding='utf-8')
                self.assertEqual(source.count(signature), 1)
                target.write_text(source.replace(signature, signature +
                                  f' globalThis.{counter}++;'), encoding='utf-8')
            tip = 'data:image/png;base64,' + b64(png(2, 2, 4, 8, [(255, 255)] * 4))
            run_node(r"""
globalThis.e9Decode=0;globalThis.e9Generate=0;
const probe=await import(data.engine),decoder=await import(data.tipModule);
const tip=await decoder.decodeTipDataUrl(data.tip);assert.equal(globalThis.e9Decode,1);
for(const kind of ['custom','scatter','noise']){
 const count=globalThis.e9Generate;
 const b=full({shape:kind==='custom'?'custom':'procedural',procedural_type:kind==='noise'?'noise':'scatter',
  procedural_seed:123456,tip,size:24,pressure_amount:true,pressure_flow:true,build_up:true});
 const s=new probe.PressureStroke(empty(),128,128,b,10,10,null,null,1000);
 for(const [x,y,p] of [[30,10,65535],[40,20,1000],[50,20,65535]])s.add(x,y,p);
 assert.ok(s.prepared.size>2);
 const masks=[...s.prepared.values()].map(e=>e.footprint.mask);
 assert.ok(masks.every(m=>m===masks[0]),'one tip shared by every effective Size');
 assert.equal(globalThis.e9Decode,1,'no per-stamp or per-Size decoding');
 assert.equal(globalThis.e9Generate-count,kind==='custom'?0:1,'one procedural generation');
}
""", dict(engine=(scratch / 'engine.js').as_uri(),
          tipModule=(scratch / 'custom_tip.js').as_uri(), tip=tip))

    def test_t18_selection_final_gate(self):
        run_node(r"""
const before=Uint8Array.from({length:16384},(_,i)=>i%200),selection=rect(12,12,18,18),snapshot=selection.slice();
const path=[[10,10,1000],[20,20,60000]],b={size:17,pressure_amount:true,build_up:true,pressure_flow:true};
const a=make(b,path,before),c=make(b,path,before,selection);selection.fill(0);
eq(c.result(),engine.withinSelection(before,a.result(),snapshot));eq(make(b,path,before,sel.selectAll()).result(),a.result());
""")

    def test_t26_invalid_engine_codes(self):
        run_node(r"""
for(const p of [-1,65536,0.5,NaN,Infinity,null,'1']){
 assert.throws(()=>make({},[[10,10,p]]),/Invalid pressure\./);
 const s=make({},[[10,10,1]]);assert.throws(()=>s.add(20,20,p),/Invalid pressure\./);
}
assert.throws(()=>make({pressure_enabled:false},[[10,10,1]]),/Pen pressure is not active for this brush\./);
""")

    def test_t02_disabled_pen_and_t03_nonpen_never_read_pressure(self):
        run_editor(r"""
const original=engine.PressureStroke.prototype.slot;
engine.PressureStroke.prototype.slot=()=>assert.fail('retained gesture constructed pressure stroke');
for(const pointerType of ['pen','mouse','touch','',undefined,'PEN'])for(const raw of [0,0.3,0.5,1,NaN,undefined]){
 await reopen(empty(),{...brush,pressure_enabled:pointerType!=='pen',pressure_amount:true,pressure_flow:true,build_up:true});
 const b=engineBrush(),s=new engine.Stroke(empty(),128,128,b,10,10);s.add(15,12);s.add(20,14);s.add(25,16);
 const direct=(name,x,y,more={})=>{
  const event={button:0,pointerId:1,pointerType,clientX:8+x*4,clientY:8+y*4,preventDefault(){},...more};
  Object.defineProperty(event,'pressure',{get(){assert.fail('pressure read on retained path');}});
  for(const fn of find('viewport').listeners[name])fn(event);
 };
 const coalesced={clientX:8+15*4,clientY:8+12*4};
 Object.defineProperty(coalesced,'pressure',{get(){assert.fail('coalesced non-pen pressure read');}});
 direct('pointerdown',10,10);direct('pointermove',20,14,{getCoalescedEvents:()=>[coalesced]});
 dom.flush();assert.ok(!find('status').textContent.startsWith('pressure '));direct('pointerup',25,16);
 eq(session().codes,s.result());assert.equal(session().history.undoEntries.length,1);
}
engine.PressureStroke.prototype.slot=original;
// Inert pen settings keep the ordinary path, including zero-pressure taps.
for(const pressure_flow of [false,true]){
 await reopen(empty(),{...brush,pressure_enabled:true,pressure_size:false,pressure_flow});
 click(10,10,{pointerType:'pen',pressure:0});assert.ok(session().codes.some(v=>v));
}
""")

    def test_t19_shift_click_no_pressure(self):
        run_editor(r"""
for(const pointerType of ['pen','mouse','touch'])for(const pressure of [0,0.3,1]){
 await reopen(empty(),{...brush,pressure_enabled:true,pressure_amount:true,pressure_flow:true,build_up:true});
 click(10,10);const before=session().codes.slice();
 const expected=new engine.Stroke(before,128,128,engineBrush(),10,10);expected.add(30,20);
 const original=engine.PressureStroke.prototype.slot;engine.PressureStroke.prototype.slot=()=>assert.fail('pressure line');
 click(30,20,{pointerType,pressure,shiftKey:true});eq(session().codes,expected.result());
 assert.equal(session().history.undoEntries.length,2);engine.PressureStroke.prototype.slot=original;
}
""")

    def test_t20_workflow_sparse_roundtrip(self):
        run_editor(r"""
const defaults={pressure_enabled:false,pressure_size:true,pressure_amount:false,pressure_flow:false};
const baseline=ui.editorSettings(brush);
for(const key of Object.keys(defaults))assert.equal(baseline[key],undefined);
assert.equal(JSON.stringify(ui.editorSettings(ui.createEditorSession(empty(),baseline).settings)),JSON.stringify(baseline));
const changed={pressure_enabled:true,pressure_size:false,pressure_amount:true,pressure_flow:true};
const stored=ui.editorSettings({...brush,...changed,pressure:123,pointerType:'pen',pointerId:2,samples:[[1,2,3]]});
assert.deepEqual(Object.keys(stored).slice(-4),brushes.PRESSURE_KEYS);
for(const key of brushes.PRESSURE_KEYS){assert.equal(stored[key],changed[key]);
 assert.equal(ui.createEditorSession(empty(),{...brush,[key]:'bad'}).settings[key],defaults[key]);}
assert.equal(JSON.stringify(ui.editorSettings(ui.createEditorSession(empty(),stored).settings)),JSON.stringify(stored));
for(const key of ['pressure','pointerType','pointerId','samples'])assert.equal(stored[key],undefined);
await reopen(empty(),{...brush,...changed});click(10,10,{pointerType:'pen',pressure:0.3});press('Done');
assert.deepEqual(result.settings,stored);
""")

    def test_t21_preset_versions_operations_and_safety(self):
        run_node(r"""
assert.deepEqual(lib.PRESSURE_SNAPSHOT_KEYS,brushes.PRESSURE_KEYS);
const meta={id:'preset',name:'Taper'},s=full({pressure_amount:true,pressure_flow:true});
const p=await lib.captureBrushPreset(s,meta),v1=await lib.captureBrushPreset({...s,pressure_enabled:false},meta);
assert.equal(p.version,2);assert.equal(v1.version,1);
assert.deepEqual(Object.keys(v1.brush),lib.SNAPSHOT_KEYS);
assert.deepEqual(Object.keys(p.brush).slice(-4),brushes.PRESSURE_KEYS);
const session=ui.createEditorSession(empty(),s);await lib.applyBrushPreset(p,session);
assert.equal(JSON.stringify(await lib.captureBrushPreset(session.settings,meta)),JSON.stringify(p));
await lib.applyBrushPreset(v1,session);for(const key of brushes.PRESSURE_KEYS)assert.equal(session.settings[key],brushes.BRUSH_DEFAULTS[key]);
const thumbnail=lib.createPresetThumbnails();assert.equal(await thumbnail(p),await thumbnail({...p,brush:{...p.brush,pressure_amount:false}}));
let text=null,n=0;const library=lib.createBrushLibrary({read:async()=>text,write:async v=>{text=v;}},()=>`p${++n}`);
const saved=await library.save(s,'Taper');let id=saved.id;
assert.equal((await library.load()).presets[0].version,2);
await library.update(id,{...s,pressure_enabled:false});assert.equal((await library.load()).presets[0].version,1);
await library.update(id,s);assert.equal((await library.load()).presets[0].version,2);
await library.metadata(id,{name:'Renamed',favorite:true});await library.duplicate(id);
assert.ok((await library.load()).presets.every(v=>v.version===2));
const exported=JSON.stringify(p);assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(exported))),exported);
await library.importPreset(exported);assert.equal((await library.load()).presets.length,3);
const future={...p,id:'future',version:3,unknown:{keep:true}},oldFuture={version:2};
text=JSON.stringify({version:1,presets:[p,future,oldFuture]});await library.metadata('preset',{name:'Changed'});
const loaded=await library.load();assert.deepEqual(loaded.rejected,[future,oldFuture]);
assert.ok(loaded.warnings.every(w=>w.includes('version')));
await assert.rejects(()=>lib.validateBrushPreset({version:3}),{message:'Unsupported preset version; expected v1 or v2.'});
await assert.rejects(()=>lib.validateBrushPreset({version:2}),{message:'A version 2 preset must use pen pressure.'});
await assert.rejects(()=>lib.validateBrushPreset({...v1,brush:{...v1.brush,pressure_size:true}}),{message:'Only version 2 presets contain pen pressure settings.'});
for(const key of brushes.PRESSURE_KEYS){
 const b={...p.brush};delete b[key];
 await assert.rejects(()=>lib.validateBrushPreset({...p,brush:b}),{message:key==='pressure_enabled'?'A version 2 preset must use pen pressure.':`Missing brush ${key}.`});
 if(key!=='pressure_enabled')await assert.rejects(()=>lib.validateBrushPreset({...p,brush:{...p.brush,[key]:1}}),new RegExp('Invalid brush '+key));
}
""")

    def test_t22_reset(self):
        run_editor(r"""
press('Use Pen Pressure');press('Amount');press('Build-up');press('Flow');
assert.equal(button('Reset Brush').hidden,false);
assert.equal(button('Reset Brush').title,'Return Amount and every Brush Behavior (Pen Pressure included), Brush Shape & Transform (with how a custom tip is read and every Procedural Tip setting, Seed included) and Value Profile setting to its default. An imported custom tip is kept; Clear Custom Tip removes it.');
session().selection=rect();const selection=session().selection;
press('Reset Brush');for(const key of brushes.PRESSURE_KEYS)assert.equal(settings()[key],brushes.BRUSH_DEFAULTS[key]);
assert.equal(session().selection,selection);assert.ok(!find('status').textContent.startsWith('pressure '));
const replay=new engine.Stroke(empty(),128,128,engineBrush(),20,25,null,selection);click(20,25);eq(session().codes,replay.result());
""")

    def test_t23_ui_preview_status_and_numeric(self):
        run_editor(r"""
const group=heading('Pen Pressure').parent,behavior=heading('Brush Behavior').parent;
assert.equal(behavior.children.at(-1),group);assert.equal(group.open,false);
assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='text').length,49);
assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='range').length,0);
const row=button('Size').parent,note=group.children.find(e=>e.textContent?.startsWith('Pen pressure changes nothing'));
assert.equal(row.hidden,true);assert.equal(note.hidden,true);assert.equal(button('Flow').hidden,true);
press('Use Pen Pressure');assert.equal(row.hidden,false);assert.equal(heading('Pen Pressure').textContent,'Pen Pressure · Size');
assert.ok(summary().textContent.includes('Pen Pressure (Size)'));
press('Size');assert.equal(note.hidden,false);assert.equal(heading('Pen Pressure').textContent,'Pen Pressure · no effect');
press('Amount');press('Build-up');assert.equal(button('Flow').hidden,false);press('Flow');press('Size');
assert.equal(heading('Pen Pressure').textContent,'Pen Pressure · Size · Amount · Flow');
pointer('pointermove',20,20,{pointerType:'pen',pressure:0});dom.flush();const base=outline().children[0].attributes.d;
assert.ok(!find('status').textContent.startsWith('pressure '));
pointer('pointerdown',20,20,{pointerType:'pen',pressure:0.25});dom.flush();
assert.ok(find('status').textContent.startsWith('pressure 25% · '));assert.equal(preview().hidden,true);
assert.notEqual(outline().children[0].attributes.d,base);
const assertOutline=size=>{
 const fp=brushes.prepareFootprint({...engineBrush(),size});
 const anchor=fp.hard?brushes.snapAnchor(fp,20,20):[20,20];
 assert.equal(outline().children[0].attributes.d,view.outlinePath(view.footprintOutline(fp),anchor));
};
assertOutline(scaleRef(settings().size,16384));
for(const code of [0,1,32768,65535]){
 pointer('pointermove',20,20,{pointerType:'pen',pressure:code/65535});dom.flush();
 assertOutline(scaleRef(settings().size,code));
}
pointer('pointerup',20,20,{pointerType:'pen',pressure:0});dom.flush();
assert.equal(outline().children[0].attributes.d,base);assert.ok(!find('status').textContent.startsWith('pressure '));
assertOutline(settings().size);
""")

    def test_t24_group_memory(self):
        run_editor(r"""
const group=heading('Pen Pressure').parent;assert.equal(group.open,false);group.open=true;fire(group,'toggle');
assert.deepEqual(writes,[['pressure',true]]);controller.cancel();controller=open();dom.flush();
assert.equal(heading('Pen Pressure').parent.open,true);controller.cancel();controller=open(empty(),{size:33});dom.flush();
assert.equal(heading('Pen Pressure').parent.open,true);
assert.equal(ui.editorSettings(settings()).pressure,undefined);assert.equal(session().history.undoEntries.length,0);
""")

    def test_t25_cancel_finish_and_pointerup_hold(self):
        run_editor(r"""
for(const action of ['pointercancel','lostpointercapture','blur','Escape']){
 await reopen(empty(),{...brush,pressure_enabled:true});
 pointer('pointerdown',10,10,{pointerType:'pen',pressure:0.3});pointer('pointermove',20,20,{pointerType:'mouse',pressure:0.7});dom.flush();
 assert.ok(session().codes.some(v=>v));
 if(action==='Escape')key('Escape');else if(action==='blur')fire(window,'blur');else fire(find('viewport'),action);
 dom.flush();eq(session().codes,empty());assert.equal(session().history.undoEntries.length,0);
 assert.ok(!find('status').textContent.startsWith('pressure '));
 click(10,10,{pointerType:'pen',pressure:0});eq(session().codes,empty());
 // A following positive stroke must have fresh pressure, pieces and pointer ownership.
 pointer('pointerdown',30,30,{pointerType:'pen',pointerId:7,pressure:12000/65535});
 pointer('pointermove',40,30,{pointerType:'pen',pointerId:7,pressure:50000/65535});
 pointer('pointerup',40,30,{pointerType:'pen',pointerId:7,pressure:0});dom.flush();
 eq(session().codes,make(engineBrush(),[[30,30,12000],[40,30,50000]]).result());
 assert.equal(session().history.undoEntries.length,1);
}
await reopen(empty(),{...brush,pressure_enabled:true,pressure_amount:true});
pointer('pointerdown',10,10,{pointerType:'pen',pressure:0});pointer('pointermove',20,20,{pointerType:'pen',pressure:30000/65535});
pointer('pointerup',30,20,{pressure:0});dom.flush();
eq(session().codes,make(engineBrush(),[[20,20,30000],[30,20,30000]]).result());assert.equal(session().history.undoEntries.length,1);
assert.equal(find('viewport').captured,null);
await reopen(empty(),{...brush,pressure_enabled:true});pointer('pointerdown',10,10,{pointerType:'pen',pressure:0.5});
press('Done');assert.ok(result.codes.some(v=>v));
""")

    def test_t27_pen_viewport_gestures(self):
        run_editor(r"""
press('Rectangle Select');drag(10,10,12,12,{pointerType:'pen'});eq(session().selection,rect(10,10,12,12));
press('Paint');press('Clear Selection');session().codes[10*128+10]=137;
click(10,10,{pointerType:'pen',altKey:true});assert.equal(settings().influence,137);
const before=canvas().style.transform;key(' ');drag(10,10,20,20,{pointerType:'pen'});fire(window,'keyup',{key:' '});dom.flush();
assert.notEqual(canvas().style.transform,before);press('Fit');
for(const b of [2,5]){const before=session().codes.slice();click(10,10,{pointerType:'pen',button:b});eq(session().codes,before);}
await reopen(empty(),{...brush,pressure_enabled:true});
pointer('pointerdown',10,10,{pointerType:'pen',pressure:1});pointer('pointerdown',90,90,{pointerType:'pen',pointerId:2,pressure:1});
pointer('pointermove',95,95,{pointerType:'pen',pointerId:2,pressure:1});pointer('pointerup',10,10);dom.flush();
eq(session().codes,make({},[[10,10,65535]]).result());
""")

    def test_t28_coalesced_pressure_samples(self):
        run_editor(r"""
await reopen(empty(),{...brush,pressure_enabled:true,pressure_amount:true});
const sample=(x,y,p)=>({clientX:8+x*4,clientY:8+y*4,pressure:p/65535});
pointer('pointerdown',10,10,{pointerType:'pen',pressure:1000/65535});
pointer('pointermove',30,20,{pointerType:'mouse',pressure:50000/65535,
 getCoalescedEvents:()=>[sample(15,13,20000),sample(20,16,0),sample(30,20,50000)]});
const up=sample(35,20,0);Object.defineProperty(up,'pressure',{get(){assert.fail('pointer-up pressure read');}});
const event={pointerId:1,clientX:168,clientY:88,getCoalescedEvents:()=>[up]};
Object.defineProperty(event,'pressure',{get(){assert.fail('dispatched pointer-up pressure read');}});
find('viewport').listeners.pointerup[0](event);dom.flush();
eq(session().codes,make(engineBrush(),[[10,10,1000],[15,13,20000],[20,16,0],[30,20,50000],[30,20,50000],[35,20,50000],[40,20,50000]]).result());
""")
