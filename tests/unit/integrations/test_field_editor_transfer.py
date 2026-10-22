"""ADR-0034 offline qualification: independent transfer arithmetic and history oracles.

Uses the retained fenced inline Node / fake DOM / graph tracker harnesses.
No live host, browser, timing assertions or product helper as an expected-value oracle.
"""
import base64
import hashlib
import json
import math
import random
import re
import unittest

from test_field_editor_custom_tip import CORE, ROOT, run_node, first_difference
from test_field_editor_multi_field import EDITOR, adapter


IMPORTS = f"""
const transferModule = await import({json.dumps((CORE / 'transfer.js').as_uri())});
const historyModule = await import({json.dumps((CORE / 'history.js').as_uri())});
const {{TransferLinks,transferReach,transferEngineBrush,transferSource,nothingMovable}}=transferModule;
const {{FieldHistory,observeHistory}}=historyModule;
"""

HELPERS = r"""
const uniform = n => new Uint8Array(16384).fill(n);
const choose = k => press(`Transfer from Painted Field #${k}`);
const heading = text => all().find(e=>e.tagName==='SUMMARY'&&e.textContent.startsWith(text));
const transfers = () => all().filter(e=>e.tagName==='BUTTON'&&e.textContent?.startsWith('Transfer from '));
const conserve = (s0,d0,s1,d1) => {
 eq(s0.map((v,i)=>0),s1.map((v,i)=>0),'length');
 for(let i=0;i<s0.length;i++) {
  assert.equal(s0[i]+d0[i],s1[i]+d1[i],`conservation ${i}`);
  assert.ok(d1[i]-d0[i]>=0&&d1[i]-d0[i]<=Math.min(s0[i],255-d0[i]),`bounds ${i}`);
 }
};
const pair = async (d=40,s=200,count=2) => {
 controller.cancel();joined.clear();joined.add('1');unavailable.clear();sources.get('1').codes=uniform(d);
 sources.get('1').settings={...brushes.BRUSH_DEFAULTS,...brush,size:16};
 controller=open();dom.flush();
 for(let k=2;k<=count;k++) {
  sources.get(String(k)).codes=uniform(k===2?s:50);
  sources.get(String(k)).settings={...brushes.BRUSH_DEFAULTS,...brush,size:16};await add(String(k));
 }
 choose('2');return [field('1').session,field('2').session];
};
const pairSnapshot = () => controller.fields().map(f=>({key:f.key,session:snapshot(f.session),changed:f.changed,from:f.transferFrom}));
const markState = () => all().filter(e=>e.className==='field-mark').map(e=>e.textContent);
const assertMessage = (text, neutral=false) => {
 assert.equal(error(),text);assert.equal(find('error').className,'error');
 assert.equal(find('error').attributes.role,'alert');
 assert.equal(find('error').style.color,neutral?'#cfd8e3':'');
};
const assertPair = (a,b) => {
 const de=a.history.undoEntries.at(-1),se=b.history.undoEntries.at(-1);
 assert.equal(de.label,'Transfer');assert.equal(se.label,'Transfer');
 assert.ok(Number.isSafeInteger(de.link.transaction)&&de.link.transaction>0);
 assert.deepEqual(de.link,{transaction:se.link.transaction,kind:'transfer',role:'destination',partner:'2'});
 assert.deepEqual(se.link,{transaction:de.link.transaction,kind:'transfer',role:'source',partner:'1'});
 assert.ok(Object.isFrozen(de.link)&&Object.isFrozen(se.link));
 conserve(se.before,de.before,se.after,de.after);
};
"""


def editor(body, data=None, *, internal=False):
    script = IMPORTS + EDITOR + HELPERS + body
    if internal:
        source = (CORE / 'editor_ui.js').read_text(encoding='utf-8')
        source = source.replace('return {get session() { return active.session; }, cancel,',
                                'return {__transfer: {records, links, settleSource, chooseTransferSource, '
                                'get stroke() { return stroke; }}, '
                                'get session() { return active.session; }, cancel,')
        source = re.sub(r'"\./([^"\n]+)"', lambda m: json.dumps((CORE / m[1]).as_uri()), source)
        url = 'data:text/javascript;base64,' + base64.b64encode(source.encode()).decode()
        script = f'const testedUi=await import({json.dumps(url)});\n' + script.replace(
            'ui.openInfluenceFieldEditor', 'testedUi.openInfluenceFieldEditor')
    return run_node(script.replace('assert.equal(', 'exact('), data)


PURE = IMPORTS + r"""
const eq=(a,b,label='codes')=>{assert.equal(a.length,b.length,label);for(let i=0;i<a.length;i++)
 if(a[i]!==b[i])assert.fail(`${label}[${i}]: ${a[i]} != ${b[i]}`);};
let members=[];
const links=new TransferLinks(()=>members);
const makeRecord=(key,value=0)=>{
 const record={key,label:key,transferSource:null,session:ui.createEditorSession(Uint8Array.of(value),{})};
 observeHistory(record.session.history,links.discarded);members.push(record);return record;
};
const a=makeRecord('A',10),b=makeRecord('B',200),c=makeRecord('C',50),d=makeRecord('D',80);
const edit=(r,value)=>r.session.replace('Edit',Uint8Array.of(value));
const move=(destination,source,amount=100)=>{
 const db=destination.session.codes,sb=source.session.codes;
 // Independent integer formula; the product coordinator records these snapshots.
 const da=db.map((v,i)=>v+Math.floor((Math.min(sb[i],255-v)*amount+50)/100));
 const sa=sb.map((v,i)=>v-(da[i]-db[i]));
 return links.record(destination,source,db,da,sb,sa);
};
const saved=()=>({members:members.map(r=>({r,codes:r.session.codes,values:[...r.session.codes],
 undo:r.session.history.undoEntries.slice(),redo:r.session.history.redoEntries.slice(),dirty:r.session.changed()})),
 table:[...links.transactions.entries()]});
const unchanged=before=>{
 for(const s of before.members){assert.ok(s.r.session.codes===s.codes,'buffer reference');eq(s.r.session.codes,s.values);
  for(const kind of ['undo','redo']){const now=s.r.session.history[kind+'Entries'];assert.equal(now.length,s[kind].length);
   now.forEach((entry,i)=>assert.ok(entry===s[kind][i],'entry identity'));}
  assert.equal(s.r.session.changed(),s.dirty);}
 assert.equal(links.transactions.size,before.table.length);
 for(const [id,pair] of before.table)assert.ok(links.transactions.get(id)===pair,'table identity');
};
const invariants=()=>{
 let halves=0;
 for(const r of members){const h=r.session.history;assert.ok(h.undoEntries.length+h.redoEntries.length<=100);
  if(h.undoEntries.length)eq(r.session.codes,h.undoEntries.at(-1).after);
  if(h.redoEntries.length)eq(r.session.codes,h.redoEntries.at(-1).before);
  for(const kind of ['undo','redo'])for(const entry of h[kind+'Entries'])if(entry.link){
   halves++;const p=links.transactions.get(entry.link.transaction);assert.ok(p,'no orphan');
   const own=p[entry.link.role],other=p[entry.link.role==='source'?'destination':'source'];
   assert.ok(own.record===r&&own.entry===entry,'canonical identities');
   assert.ok(members.includes(other.record)&&other.record!==r);
   assert.ok(other.record.session.history[kind+'Entries'].includes(other.entry),'same stack');
   assert.equal(entry.link.partner,other.record.key);
  }
 }
 assert.equal(halves,links.transactions.size*2);assert.ok(links.transactions.size<=200);
 for(const p of links.transactions.values())for(let i=0;i<p.source.entry.before.length;i++)
  assert.equal(p.destination.entry.after[i]-p.destination.entry.before[i],p.source.entry.before[i]-p.source.entry.after[i]);
};
"""


def pure(body, data=None):
    return run_node(PURE + body, data)


def half(value):
    lower = math.floor(value)
    return lower + (value - lower >= 0.5)


class HistoryModel:
    """Independent scalar model: retention is a set closure, not the JS work queue."""

    def __init__(self):
        self.fields = {}
        self.entries = {}
        self.transactions = {}
        self.next_id = 1
        self.next_entry = 1
        self.active = '1'
        self.unavailable = set()
        self.counts = dict(transfers=0, cap_linked_roots=0, cap_paired_evictions=0,
                           cap_cascade_evictions=0, redo_invalidations=0, paired_steps=0, faults_reached=0)
        for key in ('1', '2', '3', '4'):
            self.join(key)

    def join(self, key):
        self.fields[key] = dict(code={'1': 10, '2': 200, '3': 50, '4': 80}[key],
                                undo=[], redo=[], source=None, tool='paint')

    def settle(self):
        field = self.fields[self.active]
        source = field['source']
        if source is not None and (source == self.active or source not in self.fields or source in self.unavailable):
            field['source'] = None

    def activate(self, key):
        if key in self.fields and key not in self.unavailable:
            self.active = key
        self.settle()

    def discard(self, kind, roots):
        removed = set(roots)
        while True:
            more = set()
            for entry_id in removed:
                transaction = self.entries[entry_id]['transaction']
                if transaction is None:
                    continue
                for key, partner in self.transactions[transaction]:
                    history = self.fields[key][kind]
                    if partner in history:
                        more.update(history[:history.index(partner) + 1])
            if more <= removed:
                break
            removed.update(more)
        for field in self.fields.values():
            field[kind] = [entry for entry in field[kind] if entry not in removed]
        transactions = {self.entries[entry]['transaction'] for entry in removed} - {None}
        if kind == 'undo':
            roots_linked = {self.entries[entry]['transaction'] for entry in roots} - {None}
            self.counts['cap_linked_roots'] += len(roots_linked)
            self.counts['cap_paired_evictions'] += len(transactions)
            self.counts['cap_cascade_evictions'] += len(transactions - roots_linked)
        else:
            self.counts['redo_invalidations'] += len(transactions)
        for transaction in transactions:
            self.transactions.pop(transaction)

    def record(self, key, after):
        field = self.fields[key]
        before = field['code']
        if before == after:
            return None
        entry_id = self.next_entry
        self.next_entry += 1
        self.entries[entry_id] = dict(before=before, after=after, transaction=None, role=None, partner=None)
        field['undo'].append(entry_id)
        if len(field['undo']) > 100:
            self.discard('undo', [field['undo'][0]])
        self.discard('redo', field['redo'][:])
        field['code'] = after
        return entry_id

    def transfer(self, destination, source, amount, fault=False):
        d, s = self.fields[destination]['code'], self.fields[source]['code']
        moved = (min(s, 255 - d) * amount + 50) // 100
        if not moved:
            return
        transaction = self.next_id
        self.next_id += 1
        if fault:
            self.counts['faults_reached'] += 1
            return
        self.counts['transfers'] += 1
        de = self.record(destination, d + moved)
        se = self.record(source, s - moved)
        self.entries[de].update(transaction=transaction, role='destination', partner=source)
        self.entries[se].update(transaction=transaction, role='source', partner=destination)
        self.transactions[transaction] = [(destination, de), (source, se)]

    def step(self, kind, key, fault=False):
        field = self.fields[key]
        if not field[kind]:
            return
        entry = self.entries[field[kind][-1]]
        transaction = entry['transaction']
        if transaction is None:
            sides = [(key, field[kind][-1])]
        else:
            sides = self.transactions[transaction]
            if any(not self.fields[k][kind] or self.fields[k][kind][-1] != e for k, e in sides):
                return
            if fault:
                self.counts['faults_reached'] += 1
                return
            self.counts['paired_steps'] += 1
        for key, entry_id in sides:
            side = self.fields[key]
            side[kind].pop()
            side['redo' if kind == 'undo' else 'undo'].append(entry_id)
            side['code'] = self.entries[entry_id]['before' if kind == 'undo' else 'after']

    def apply(self, op):
        action, *args = op
        if action == 'activate':
            self.activate(args[0])
        elif action == 'available':
            key, available = args
            if available:
                self.unavailable.discard(key)
            else:
                self.unavailable.add(key)
        elif action == 'choose':
            source = args[0]
            if source != self.active and source in self.fields and source not in self.unavailable:
                self.fields[self.active].update(source=source, tool='transfer')
        elif action == 'edit':
            self.record(self.active, args[0])
        elif action == 'transfer':
            source, amount, fault = args
            self.apply(['choose', source])
            self.transfer(self.active, source, amount, fault)
        elif action in ('undo', 'redo'):
            self.step(action, self.active, args[0])
        elif action == 'remove':
            key = args[0]
            order = list(self.fields)
            index = order.index(key)
            for transaction, sides in list(self.transactions.items()):
                if any(k == key for k, _ in sides):
                    for _, entry in sides:
                        self.entries[entry].update(transaction=None, role=None, partner=None)
                    del self.transactions[transaction]
            del self.fields[key]
            for field in self.fields.values():
                if field['source'] == key:
                    field['source'] = None
            if self.active == key:
                self.active = list(self.fields)[min(index, len(self.fields) - 1)]
        elif action == 'join':
            self.join(args[0])
        self.settle()

    def digest(self):
        rows = []
        for key, field in self.fields.items():
            histories = []
            for kind in ('undo', 'redo'):
                histories.append([[self.entries[e][k] for k in ('before', 'after', 'transaction', 'role', 'partner')]
                                  for e in field[kind]])
            rows.append([key, field['code'], *histories, field['source'], field['tool'], key not in self.unavailable])
        value = [self.active, self.next_id, rows, sorted(self.transactions)]
        return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


class TransferTests(unittest.TestCase):
    def test_01_one_field_exact_dom_actions_done(self):
        editor(r"""
assert.ok(!all().some(e=>/(transfer-sources|transfer-help|transfer-status|field-transfer|field-role)/.test(e.className||'')));
assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='text').length,49);
assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='range').length,0);
assert.deepEqual(inventory(),retainedInventory);
assert.deepEqual(heading('Advanced').parent.children.filter(e=>e.className==='group').map(e=>e.children[0].textContent.split(' · ')[0]),
 ['Brush Behavior','Brush Shape & Transform','Value Profile','Field Tools']);
const s=controller.session,before=s.codes.slice(),reference=new engine.Stroke(before,128,128,s.settings,64,64,s.initial);
click(64,64);eq(s.codes,reference.result());press('Undo');eq(s.codes,before);press('Redo');eq(s.codes,reference.result());
press('Done');await until(()=>offers.length);eq(offers[0][0].codes,reference.result());
""")

    def test_02_chooser_two_three_four_available_only_order(self):
        editor(r"""
for(let n=2;n<=4;n++) {await add(String(n));
 for(let k=1;k<=n;k++){activate(String(k));
  assert.deepEqual(transfers().filter(e=>!e.hidden).map(e=>e.textContent),
   Array.from({length:n},(_,i)=>i+1).filter(i=>i!==k).map(i=>`Transfer from Painted Field #${i}`));
  assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='text').length,49);
  assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='range').length,0);
 }}
unavailable.add('2');redraw();assert.ok(transfers().find(e=>e.textContent.endsWith('#2')).hidden);
remove('3');assert.ok(!transfers().some(e=>e.textContent.endsWith('#3')));
assert.equal(heading('Advanced').parent.children.filter(e=>e.className==='group').length,4);
""")

    def test_03_choice_self_guards_visibility_roles_and_leaving(self):
        editor(r"""
const [a,b]=await pair();const state=pairSnapshot();choose('1');assert.deepEqual(pairSnapshot(),state);
assert.ok(transfers()[0].hidden);assert.equal(find('field-transfer').textContent,'Transfer: Painted Field #2 → Painted Field #1');
assert.equal(tabs()[1].children.at(-1).textContent,'source');assert.ok(tabs()[1].title.endsWith(' · transfer source'));
assert.equal(transfers()[1].attributes['aria-pressed'],'true');
all().filter(e=>e.className==='field-show')[1].click();dom.flush();
assert.ok(find('field-transfer').textContent.endsWith(' · source hidden'));choose('2');assert.equal(field('2').visible,true);
press('Rectangle Select');choose('2');assert.equal(a.selectTool,null);
for(const leave of [()=>press('Paint'),()=>press('Erase'),()=>press('Restore'),()=>key('b'),()=>key('e'),()=>press('Reset Brush')]) {
 choose('2');leave();assert.equal(field('1').transferFrom,null);assert.notEqual(a.settings.tool,'transfer');
 assert.equal(find('field-transfer').hidden,true);assert.equal(tabs()[1].children.at(-1).textContent,'');
}
choose('2');assert.ok(heading('Brush Behavior').textContent.includes('Transfer'));assert.equal(buttons('Reset Brush')[0].hidden,false);
assert.equal(buttons('Paint')[0].attributes['aria-pressed'],'false');assert.equal(buttons('Erase')[0].attributes['aria-pressed'],'false');
const row=transfers()[1].parent;assert.equal(row.parent,heading('Brush Behavior').parent);
const children=row.parent.children;assert.ok(children[children.indexOf(row)-1].textContent.startsWith('Restore paints'));
assert.equal(children[children.indexOf(row)+3],heading('Pen Pressure').parent);
""")

    def test_04_per_destination_memory_switches_and_self_validation(self):
        editor(r"""
await pair(10,200,4);activate('3');choose('4');activate('1');assert.equal(field('1').transferFrom,'2');
activate('2');assert.equal(field('2').transferFrom,null);assert.notEqual(controller.session.settings.tool,'transfer');
activate('3');assert.equal(field('3').transferFrom,'4');activate('1');
const r=controller.__transfer.records[0];r.transferSource=r;redraw();assert.equal(field('1').transferFrom,null);
assert.equal(controller.session.settings.tool,'transfer');assert.equal(find('field-transfer').textContent,'Transfer: no source field');
const before=pairSnapshot();click(64,64);assert.deepEqual(pairSnapshot(),before);
assert.equal(error(),'Choose a field to transfer from: Advanced ▸ Brush Behavior ▸ Transfer from…');
""", internal=True)

    def test_05_invalid_source_activation_render_and_start_stays_transfer(self):
        editor(r"""
await pair(10,200,3);activate('3');unavailable.add('2');activate('1');
assert.equal(field('1').transferFrom,null);assert.equal(controller.session.settings.tool,'transfer');
assert.ok(transfers().every(e=>e.attributes['aria-pressed']==='false'));
click(64,64);assert.equal(error(),'Choose a field to transfer from: Advanced ▸ Brush Behavior ▸ Transfer from…');
unavailable.delete('2');choose('2');unavailable.add('2');redraw();assert.equal(field('1').transferFrom,null);
unavailable.delete('2');choose('2');unavailable.add('2');
fire(find('viewport'),'pointerdown',{clientX:264,clientY:264});dom.flush();
assert.equal(field('1').transferFrom,null);assert.equal(controller.session.history.undoEntries.length,0);
fire(find('viewport'),'pointerup');unavailable.delete('2');choose('2');unavailable.add('1');click(64,64);
assert.equal(error(),'Cannot transfer into Painted Field #1: it is no longer in this graph.');
assert.equal(controller.session.history.undoEntries.length,0);
""")

    def test_06_removal_clears_inactive_pointers_and_one_field_refusal(self):
        editor(r"""
await pair(10,200,4);activate('3');choose('2');remove('2');
assert.equal(field('1').transferFrom,null);assert.equal(field('3').transferFrom,null);
assert.equal(field('1').session.settings.tool,'transfer');assert.equal(field('3').session.settings.tool,'transfer');
click(64,64);assert.equal(error(),'Choose a field to transfer from: Advanced ▸ Brush Behavior ▸ Transfer from…');
remove('4');remove('1');assert.equal(field('3').transferFrom,null);click(64,64);
assert.equal(error(),'Transfer needs another field in this session. Add Field…, or choose Paint.');
assert.ok(transfers().every(e=>e.hidden));assert.equal(find('field-transfer').textContent,'Transfer: no source field');
""")

    def test_07_source_choice_clears_line_anchor_and_refuses_mid_stroke(self):
        editor(r"""
const [a,b]=await pair(10,200,3);click(10,10);choose('3');
const before=a.codes.slice();click(110,110,{shiftKey:true});assert.equal(a.codes[64*128+64],before[64*128+64]);
choose('2');pointer('pointerdown',64,64);activate('2');choose('3');remove('2');
assert.equal(controller.session,a);assert.equal(field('1').transferFrom,'2');assert.equal(controller.fields().length,3);
pointer('pointerup',80,64);assertPair(a,b);
activate('2');choose('1');click(90,90,{shiftKey:true});assert.equal(controller.session.settings.tool,'transfer');
""")


    def check_case(self, settings=None, *, pressure=False, selection=False, tip=False):
        result = editor(r"""
const [a,b]=await pair();
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256);
b.codes=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
Object.assign(a.settings,data.settings);
if(data.tip){a.tip={width:3,height:2,luminance:Uint8Array.of(255,96,170,41,230,153),alpha:Uint8Array.of(180,255,32,90,210,255)};
 a.settings.custom_tip=await tips.encodeTipDataUrl(a.tip);}
if(data.selection)a.selection=Uint8Array.from({length:16384},(_,i)=>i%3===0?0:1);
b.selection=Uint8Array.from({length:16384},(_,i)=>i%2);const selectionBefore=b.selection.slice();
const d0=a.codes.slice(),s0=b.codes.slice();
// Coverage oracle is the retained engine, independently wired to a Restore target.
const reach=Uint8Array.from(d0,(v,i)=>Math.min(255,v+s0[i]));
const br={...a.settings,tip:a.tip,tool:'restore',apply_mode:'normal'};
const path=[[20,32,16384],[35,47,32768],[70,64,49151],[103,97,65535]];
const ref=data.pressure?new engine.PressureStroke(d0,128,128,br,...path[0].slice(0,2),reach,a.selection,path[0][2]):
 new engine.Stroke(d0,128,128,br,...path[0].slice(0,2),reach,a.selection);
for(const p of path.slice(1))ref.add(...(data.pressure?p:p.slice(0,2)));
const extra=p=>data.pressure?{pointerType:'pen',pressure:p/65535}:{};
pointer('pointerdown',20,32,extra(path[0][2]));
for(const [x,y,p] of path.slice(1))pointer('pointermove',x,y,extra(p));
pointer('pointerup',103,97,extra(65535));
eq(a.codes,ref.result(),'retained target path');conserve(s0,d0,b.codes,a.codes);eq(b.selection,selectionBefore);
console.log(JSON.stringify({d0:[...d0],s0:[...s0],d1:[...a.codes],s1:[...b.codes],coverage:[...ref.coverage],
 amounts:ref.amounts?[...ref.amounts]:null,selection:a.selection?[...a.selection]:null,amount:br.amount}));
""", {'settings': settings or {}, 'pressure': pressure, 'selection': selection, 'tip': tip})
        destination, source = [], []
        for i, (s, d, coverage) in enumerate(zip(result['s0'], result['d0'], result['coverage'])):
            amount = result['amounts'][i] if result['amounts'] is not None else result['amount']
            moved = half(((min(s, 255 - d) * amount) * coverage) / 100)
            if result['selection'] is not None and not result['selection'][i]:
                moved = 0
            destination.append(d + moved)
            source.append(s - moved)
        self.assertIsNone(first_difference(result['d1'], destination))
        self.assertIsNone(first_difference(result['s1'], source))
        return result

    def test_08_basic_source_headroom_and_equal_constraints(self):
        editor(r"""
for(const [s,d,k] of [[200,40,100],[200,40,15],[10,40,100],[100,250,100],[128,127,50],[5,250,15]]) {
 const [a,b]=await pair(d,s);a.settings.amount=k;const beforeA=a.codes.slice(),beforeB=b.codes.slice();click(64,64);
 const moved=Math.floor((Math.min(s,255-d)*k+50)/100);
 assert.equal(a.codes[64*128+64],d+moved);assert.equal(b.codes[64*128+64],s-moved);
 assert.equal(a.codes[0],d);assert.equal(b.codes[0],s);conserve(beforeB,beforeA,b.codes,a.codes);assertPair(a,b);
}
""")


    def test_59_randomized_ui_history_against_independent_python_model(self):
        model = HistoryModel()
        rng = random.Random(0xE10B34)
        trace = []

        def emit(op):
            model.apply(op)
            trace.append([op, model.digest()])

        # Guaranteed history pressure and mixed linked Redo, then a fixed-seed walk.
        for _ in range(3):
            for key, value in [('1', 10), ('2', 200), ('3', 50), ('4', 80)]:
                emit(['activate', key])
                emit(['edit', value])
            emit(['activate', '3'])
            emit(['transfer', '2', 25, False])
            emit(['activate', '1'])
            emit(['transfer', '2', 25, False])
            for i in range(105):
                emit(['edit', 5 + i % 2])
        for _ in range(2400):
            members = list(model.fields)
            available = [k for k in members if k not in model.unavailable]
            action = rng.randrange(100)
            if action < 30:
                emit(['edit', rng.randrange(256)])
            elif action < 53 and model.active in available and len(available) > 1:
                emit(['transfer', rng.choice([k for k in available if k != model.active]), rng.randrange(1, 101),
                      rng.randrange(20) == 0])
            elif action < 66:
                emit(['undo', rng.randrange(20) == 0])
            elif action < 74:
                emit(['redo', rng.randrange(20) == 0])
            elif action < 83:
                emit(['activate', rng.choice(members)])
            elif action < 87 and len(members) > 1:
                emit(['remove', rng.choice(members)])
            elif action < 91 and len(members) < 4:
                key = rng.choice([k for k in ('1', '2', '3', '4') if k not in members])
                emit(['available', key, True])
                emit(['join', key])
            elif action < 96:
                key = rng.choice(members)
                emit(['available', key, key in model.unavailable])
            else:
                emit(['choose', rng.choice(members)])
        result = editor(r"""
const {createHash}=await import('node:crypto');
await pair(10,200,4);press('Paint');field('4').session.codes.fill(80);field('4').session.initial.fill(80);sources.get('4').codes.fill(80);
const fullBrush=()=>{for(const f of controller.fields())Object.assign(f.session.settings,{shape:'square',size:128,hardness:100,amount:100});};fullBrush();
const current=()=>controller.__transfer;
const digest=()=>{
 const {records,links}=current();
 const rows=records.map(r=>[r.key,r.session.codes[0],...['undo','redo'].map(kind=>r.session.history[kind+'Entries'].map(e=>
  [e.before[0],e.after[0],e.link?.transaction??null,e.link?.role??null,e.link?.partner??null])),r.transferSource?.key??null,r.session.settings.tool,isAvailable(r)]);
 return createHash('sha256').update(JSON.stringify([controller.fields().find(f=>f.active).key,links.nextTransaction,rows,[...links.transactions.keys()].sort((a,b)=>a-b)])).digest('hex');
};
const isAvailable=r=>!unavailable.has(r.key);
let faults=0,paired=0;
for(let index=0;index<data.length;index++) {
 const [op,expected]=data[index],[action,...args]=op;let reset=()=>{};
 if(action==='activate'){if(controller.fields().length>1)activate(args[0]);else redraw();}
 else if(action==='available'){args[1]?unavailable.delete(args[0]):unavailable.add(args[0]);redraw();}
 else if(action==='join'){await add(args[0]);fullBrush();}
 else if(action==='remove')remove(args[0]);
 else if(action==='choose'){if(buttons(`Transfer from Painted Field #${args[0]}`).length)choose(args[0]);else redraw();}
 else if(action==='edit'){controller.session.replace('Edit',uniform(args[0]));redraw();}
 else if(action==='transfer') {
  choose(args[0]);controller.session.settings.amount=args[1];
  if(args[2]) {const h=field(args[0]).session.history,original=h.record;
   h.record=function(...params){original.apply(this,params);throw Error('record fault');};reset=()=>h.record=original;faults++;}
  click(64,64);reset();
 } else {
  const {records,links}=current(),r=records.find(r=>r.session===controller.session),classification=links.classify(action,r);
  if(classification.state==='linked') {
   paired++;
   if(args[0]){const entries=classification.partner.session.history[action==='undo'?'redoEntries':'undoEntries'],original=entries.push;
    entries.push=function(...items){original.apply(this,items);throw Error('step fault');};reset=()=>delete entries.push;faults++;}
  }
  press(action==='undo'?'Undo':'Redo');reset();
 }
 const {records,links}=current();let halves=0;
 for(const r of records){
  assert.ok(r.transferSource!==r);assert.ok(!r.transferSource||records.includes(r.transferSource),'no removed pointer');
  const s=r.session,h=s.history;assert.ok(h.undoEntries.length+h.redoEntries.length<=100);
  assert.ok(s.codes.every(v=>v===s.codes[0]),'uniform scalar fixture');
  for(const kind of ['undo','redo']){
   if(h[kind+'Entries'].length)eq(s.codes,h[kind+'Entries'].at(-1)[kind==='undo'?'after':'before']);
   for(const e of h[kind+'Entries'])if(e.link){halves++;const p=links.transactions.get(e.link.transaction);assert.ok(p,'no orphan');
    assert.equal(p[e.link.role].record,r);assert.equal(p[e.link.role].entry,e);
    const partner=p[e.link.role==='source'?'destination':'source'];assert.ok(partner.record.session.history[kind+'Entries'].includes(partner.entry));
   }
  }
 }
 assert.equal(halves,links.transactions.size*2);assert.equal(digest(),expected,`model step ${index}: ${JSON.stringify(op)}`);
}
assert.ok(faults>0);assert.ok(paired>0);console.log(JSON.stringify({operations:data.length,faults,paired}));
""", trace, internal=True)
        self.assertEqual(result['operations'], len(trace))
        self.assertGreater(result['faults'], 0)
        result.update(model.counts)
        print('E10b randomized model: ' + json.dumps(result, sort_keys=True))

    def test_60_memory_cap_and_live_table_bound(self):
        result = pure(r"""
// Four full-size histories at their maximum; a table row owns references, no snapshots.
for(const r of members){r.session.codes=new Uint8Array(16384).fill(r.session.codes[0]);r.session.initial=r.session.codes.slice();}
for(let i=0;i<100;i++)for(const [destination,source] of [[a,b],[c,d]]) {
 const [receiver,donor]=i%2?[source,destination]:[destination,source];
 const db=receiver.session.codes.slice(),sb=donor.session.codes.slice();
 const da=db.map((v,j)=>v+Math.floor((Math.min(sb[j],255-v)*50+50)/100)),sa=sb.map((v,j)=>v-(da[j]-db[j]));
 links.record(receiver,donor,db,da,sb,sa);
}
assert.equal(links.transactions.size,200);let bytes=0;
for(const r of members){assert.equal(r.session.history.undoEntries.length,100);
 for(const e of r.session.history.undoEntries)bytes+=e.before.byteLength+e.after.byteLength;}
assert.equal(bytes,13107200);
for(let i=0;i<150;i++)for(const r of members)r.session.replace('pressure',r.session.codes.map(v=>255-v));
assert.equal(links.transactions.size,0);assert.ok(members.every(r=>r.session.history.undoEntries.length===100));
console.log(JSON.stringify({snapshotBytes:bytes,maxRows:200}));
""")
        self.assertEqual(result, {'snapshotBytes': 13107200, 'maxRows': 200})

    def test_61_import_and_retained_module_boundaries(self):
        for path, digest in {
            CORE / 'engine.js': '70d767a642ea7cda612c241aa9d9aeb364295a8d121cc33a2adb92a311c9a1de',
            CORE / 'brush.js': 'fc6cff66902efa3ad4d0fec7085f93f88996504f97e56ea29a947b6898b95afe',
            ROOT / 'web/js/painted_field_node.js': 'f13daf18ad81c2ad96be350772e0afbdbc8ec60bf7a8b197f41dbf3e906ab690',
        }.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, path.name)
        source = (CORE / 'transfer.js').read_text(encoding='utf-8')
        self.assertNotRegex(source, r'(?m)^import\b|hotdog|fetch\(|document\.|window\.|Math\.random|Date\.|localStorage|sessionStorage')
        history = (CORE / 'history.js').read_text(encoding='utf-8')
        self.assertIn('OBSERVERS.get(this)?.(cleared, evicted);', history)
        self.assertNotIn('transfer', history.lower())
        run_node(IMPORTS + "assert.equal(Object.keys(new FieldHistory()).join(','),'undoEntries,redoEntries');")

    def test_09_zero_source_full_destination_and_rounding_noops(self):
        editor(r"""
for(const [s,d] of [[0,40],[90,255]]) {
 const [a,b]=await pair(d,s);const before=pairSnapshot();click(64,64);assert.deepEqual(pairSnapshot(),before);
 assert.equal(a.history.undoEntries.length,0);assert.equal(b.history.undoEntries.length,0);
 assert.equal(error(),'Nothing to transfer under the brush: Painted Field #2 is 0 or Painted Field #1 is 255 there.');
}
const [a,b]=await pair(0,1);a.settings.amount=1;redraw();const before=pairSnapshot();click(64,64);
assert.deepEqual(pairSnapshot(),before);assert.equal(error(),'');assert.equal(a.history.undoEntries.length,0);
a.selection=new Uint8Array(16384);a.selection[0]=1;click(64,64);assert.equal(error(),'');
""")

    def test_10_exhaustive_full_coverage_6553600_and_zero_extension(self):
        # Python creates the integer oracle independently; JS checks the real engine
        # over four full 128-square grids for each retained Amount (1..100).
        expected = [[(gap * k + 50) // 100 for gap in range(256)] for k in range(101)]
        result = run_node(IMPORTS + r"""
let checked=0;
for(let k=1;k<=100;k++)for(let block=0;block<4;block++) {
 const db=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256);
 const sb=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 const reach=transferReach(sb,db),stroke=new engine.Stroke(db,128,128,
  transferEngineBrush({...brush,shape:'square',size:128,amount:k}),64,64,reach);
 const da=stroke.result(),sa=transferSource(sb,db,da);
 for(let i=0;i<16384;i++) {
  const m=data[k][Math.min(sb[i],255-db[i])];
  assert.equal(da[i],db[i]+m);assert.equal(sa[i],sb[i]-m);assert.equal(sa[i]+da[i],sb[i]+db[i]);checked++;
 }
}
let zero=0;for(let s=0;s<256;s++)for(let d=0;d<256;d++){
 assert.equal(data[0][Math.min(s,255-d)],0);zero++;
}
// Amount 0 is mathematical boundary coverage, not a new UI/engine setting.
assert.throws(()=>new engine.Stroke(empty(),128,128,{...brush,amount:0},64,64),/Invalid brush amount/);
console.log(JSON.stringify({checked,zero}));
""", expected)
        self.assertEqual(result, {'checked': 6553600, 'zero': 65536})

    def test_11_amount_soft_binary64(self):
        self.check_case({'amount': 15, 'hardness': 31, 'shape': 'diamond', 'rotation_degrees': 17})

    def test_12_flow_off_is_inactive(self):
        one = self.check_case({'hardness': 35, 'flow': 30, 'build_up': False})
        two = self.check_case({'hardness': 35, 'flow': 100, 'build_up': False})
        self.assertIsNone(first_difference(one['d1'], two['d1']))

    def test_13_flow_build_up_binary64_and_stroke_start_bound(self):
        for flow in (30, 100):
            result = self.check_case({'size': 32, 'hardness': 40, 'amount': 37, 'flow': flow, 'build_up': True})
            for s, d, after in zip(result['s0'], result['d0'], result['d1']):
                self.assertLessEqual(after - d, (min(s, 255 - d) * 37 + 50) // 100)

    def test_14_pressure_amount(self):
        self.check_case({'size': 28, 'hardness': 48, 'amount': 67, 'pressure_enabled': True,
                         'pressure_amount': True, 'pressure_size': False}, pressure=True)

    def test_15_pressure_size(self):
        self.check_case({'size': 32, 'hardness': 63, 'pressure_enabled': True,
                         'pressure_size': True, 'pressure_amount': False}, pressure=True)

    def test_16_pressure_flow(self):
        self.check_case({'size': 20, 'hardness': 55, 'amount': 63, 'flow': 30, 'build_up': True,
                         'pressure_enabled': True, 'pressure_size': False, 'pressure_flow': True}, pressure=True)

    def test_17_selection_destination_only_source_ignored(self):
        self.check_case({'amount': 57, 'hardness': 51}, selection=True)

    def test_18_custom_tip_alpha_luminance(self):
        self.check_case({'shape': 'custom', 'tip_channel': 'alpha_luminance', 'size': 36,
                         'hardness': 37, 'scale_x': 1.3, 'rotation_degrees': 28}, tip=True)

    def test_19_procedural_scatter_noise(self):
        for kind in ('scatter', 'noise'):
            self.check_case({'shape': 'procedural', 'procedural_type': kind, 'procedural_seed': 723,
                             'size': 44, 'hardness': 46, 'amount': 53})

    def test_20_hotdog_counts_and_custom_mask_twin(self):
        for count in (1, 8, 1024):
            self.check_case({'shape': 'procedural', 'procedural_particle_shape': 'hotdog',
                             'hotdog_count': count, 'size': 48, 'hardness': 70, 'hotdog_rotation': 37,
                             'mirror_horizontal': True, 'hotdog_invert': count == 8})
        run_node(IMPORTS + r"""
const db=Uint8Array.from({length:16384},(_,i)=>i%256),sb=Uint8Array.from(db,v=>255-v);
for(const count of [1,8,1024]) {
 const br={...brush,...brushes.BRUSH_DEFAULTS,shape:'procedural',procedural_particle_shape:'hotdog',hotdog_count:count,size:48};
 const mask=brushes.proceduralMask(br),tip={width:mask.width,height:mask.height,luminance:mask.codes,alpha:mask.codes};
 const reach=Uint8Array.from(db,(v,i)=>Math.min(255,v+sb[i]));
 const p=new engine.Stroke(db,128,128,transferEngineBrush(br),64,64,reach);
 const t=new engine.Stroke(db,128,128,transferEngineBrush({...br,shape:'custom',tip,tip_channel:'alpha'}),64,64,reach);
 const pd=p.result(),td=t.result();assert.ok(pd.every((v,i)=>v===td[i]));
 const ps=transferSource(sb,db,pd),ts=transferSource(sb,db,td);assert.ok(ps.every((v,i)=>v===ts[i]));
}
""")

    def test_21_gradient_apply_badges_preview_and_influence_inactive(self):
        editor(r"""
const [a,b]=await pair();a.settings.value_profile='radial';a.settings.gradient_start=11;a.settings.gradient_end=31;
for(const mode of ['raise_only','lower_only']) {
 a.settings.apply_mode=mode;redraw();
 assert.ok(heading('Brush Behavior').textContent.includes((mode==='raise_only'?'Raise Only':'Lower Only')+' (inactive for Transfer)'));
 assert.ok(heading('Value Profile').textContent.includes('inactive for Transfer'));
 assert.ok(all().some(e=>e.textContent==='Inactive: Transfer moves influence from its source field. The gradient applies to Paint.'));
 const pixels=find('brush-preview').pixels;for(let i=0;i<pixels.length;i+=4)if(pixels[i+3])eq(pixels.slice(i,i+3),[64,160,255]);
 const d0=a.codes.slice(),s0=b.codes.slice();click(64,64);assert.equal(a.codes[64*128+64],240);conserve(s0,d0,b.codes,a.codes);
 assert.equal(a.settings.apply_mode,mode);press('Undo');
}
""")

    def test_22_line_one_pair_and_collinear_subdivision(self):
        editor(r"""
const [a,b]=await pair();a.settings.hardness=43;a.settings.amount=61;click(16,32);
const db=a.codes.slice(),sb=b.codes.slice();click(112,32,{shiftKey:true});
assert.equal(a.history.undoEntries.length,2);assert.equal(b.history.undoEntries.length,2);assertPair(a,b);
const br={...a.settings,tool:'restore',apply_mode:'normal'},reach=Uint8Array.from(db,(v,i)=>Math.min(255,v+sb[i]));
const reference=new engine.Stroke(db,128,128,br,16,32,reach);for(let x=17;x<=112;x++)reference.add(x,32);
eq(a.codes,reference.result());conserve(sb,db,b.codes,a.codes);
""")


    def test_23_one_pair_per_stroke_exact_identity_and_monotone_id(self):
        editor(r"""
const [a,b]=await pair(10,200);a.settings.amount=25;
pointer('pointerdown',20,20);for(let x=21;x<100;x++)pointer('pointermove',x,20);pointer('pointerup',100,20);
assert.equal(a.history.undoEntries.length,1);assert.equal(b.history.undoEntries.length,1);assertPair(a,b);
const links=controller.__transfer.links,records=controller.__transfer.records,de=a.history.undoEntries[0],se=b.history.undoEntries[0];
const entry=links.transactions.get(de.link.transaction);
assert.equal(entry.destination.record,records[0]);assert.equal(entry.source.record,records[1]);
assert.equal(entry.destination.entry,de);assert.equal(entry.source.entry,se);
click(64,64);assertPair(a,b);assert.ok(a.history.undoEntries.at(-1).link.transaction>de.link.transaction);
const id=a.history.undoEntries.at(-1).link.transaction;remove('2');await add('2');choose('2');click(48,48);
assert.ok(a.history.undoEntries.at(-1).link.transaction>id);
""", internal=True)

    def test_24_paired_undo_redo_from_either_field_buttons_and_keys(self):
        editor(r"""
const [a,b]=await pair();const da=a.codes.slice(),sb=b.codes.slice();click(64,64);
const afterA=a.codes.slice(),afterB=b.codes.slice();
for(const k of ['1','2']) {
 activate(k);press('Undo');eq(a.codes,da);eq(b.codes,sb);
 assert.equal(a.history.undoEntries.length,0);assert.equal(b.history.undoEntries.length,0);
 assert.deepEqual(markState(),['','']);press('Redo');eq(a.codes,afterA);eq(b.codes,afterB);
 key('z',{ctrlKey:true});eq(a.codes,da);eq(b.codes,sb);key('z',{ctrlKey:true,shiftKey:true});eq(a.codes,afterA);eq(b.codes,afterB);
 key('z',{ctrlKey:true});key('y',{ctrlKey:true});eq(a.codes,afterA);eq(b.codes,afterB);
}
""")


    def test_45_e6_save_update_apply_never_captures_tool_or_source(self):
        editor(r"""
const [a,b]=await pair();const before=snapshot(b);
press('Brush Library…');await until(()=>find('library-status')&&!find('library-status').textContent.startsWith('Working'));
input('Preset name').value='Portable';input('Preset category').value='General';press('Save As New');
await until(()=>libraryText!==null&&find('library-status').textContent==='Brush saved.');
const saved=JSON.parse(libraryText),preset=saved.presets[0];assert.equal(preset.version,1);
assert.deepEqual(Object.keys(preset.brush),lib.SNAPSHOT_KEYS);
assert.ok(!/transfer|source|partner|transaction|node/i.test(libraryText));assert.ok(!Object.hasOwn(preset.brush,'tool'));
a.settings.size=39;press('Update from Current Brush');await until(()=>JSON.parse(libraryText).presets[0].brush.size===39);
a.settings.size=16;press('Apply');await until(()=>a.settings.size===39);
assert.equal(a.settings.tool,'transfer');assert.equal(field('1').transferFrom,'2');assert.equal(snapshot(b),before);
assert.ok(!/transfer|source|partner|transaction|node/i.test(libraryText));
""")

    def test_46_copy_from_is_ordinary_and_leaves_source_unchanged(self):
        editor(r"""
const [a,b]=await pair(10,200);a.selection=Uint8Array.from({length:16384},(_,i)=>i%2);
const db=a.codes.slice(),before=snapshot(b);press('Copy from Painted Field #2');
assert.equal(snapshot(b),before);for(let i=0;i<16384;i++)assert.equal(a.codes[i],i%2?200:10);
assert.equal(a.history.undoEntries.length,1);assert.ok(!a.history.undoEntries[0].link);assert.equal(a.settings.tool,'transfer');
assert.equal(field('1').transferFrom,'2');press('Undo');eq(a.codes,db);assert.equal(snapshot(b),before);
""")

    def test_47_paint_erase_restore_keep_retained_single_field_meaning(self):
        editor(r"""
const [a,b]=await pair(10,200);click(64,64);
for(const tool of ['Paint','Erase','Restore']) {
 press(tool);Object.assign(a.settings,{amount:63,hardness:44,influence:117});
 const before=snapshot(b),db=a.codes.slice();const ref=new engine.Stroke(db,128,128,a.settings,64,64,a.initial,a.selection);
 click(64,64);eq(a.codes,ref.result());assert.equal(snapshot(b),before);
 assert.ok(!a.history.undoEntries.at(-1).link);assert.equal(field('1').transferFrom,null);
}
""")

    def test_48_dirty_noop_cancel_count_and_erase_persistence_subtlety(self):
        editor(r"""
const [a,b]=await pair();assert.deepEqual(controller.fields().map(f=>f.changed),[false,false]);
click(64,64);assert.deepEqual(controller.fields().map(f=>f.changed),[true,true]);
allowDiscard=false;press('Cancel');assert.deepEqual(confirms.at(-1),['discard',2]);
press('Undo');assert.deepEqual(controller.fields().map(f=>f.changed),[false,false]);
press('Redo');assert.deepEqual(controller.fields().map(f=>f.changed),[true,true]);
allowDiscard=true;controller.cancel();joined.clear();joined.add('1');
sources.get('1').settings={...brushes.BRUSH_DEFAULTS,...brush,tool:'erase',amount:37,flow:23,build_up:true,
 value_profile:'linear',gradient_start:173,gradient_end:29,apply_mode:'lower_only',pressure_enabled:true,pressure_amount:true};
controller=open();dom.flush();await add('2');
const destination=field('1').session,source=field('2').session;
const settings={...destination.settings},canonical=ui.editorSettings(settings),db=destination.codes.slice(),sb=source.codes.slice();
assert.equal(settings.tool,'erase');assert.equal(field('1').changed,false);assert.equal(field('2').changed,false);
choose('2');assert.deepEqual(destination.settings,{...settings,tool:'transfer'});
assert.equal(field('1').changed,true);assert.equal(field('2').changed,false);
assert.equal(field('1').transferFrom,'2');assert.equal(field('2').visible,true);
assert.deepEqual(ui.editorSettings(destination.settings),{...canonical,tool:'paint'});
assert.equal(transferEngineBrush(destination.settings).apply_mode,'normal');
assert.equal(heading('Value Profile').textContent,'Value Profile · Linear gradient · 173→29 · inactive for Transfer');
eq(destination.codes,db);eq(source.codes,sb);
assert.equal(destination.history.undoEntries.length,0);assert.equal(source.history.undoEntries.length,0);
press('Done');await until(()=>offers.length);
assert.deepEqual(offers.at(-1).map(f=>f.key),['1']);
assert.deepEqual(offers.at(-1)[0].settings,{...canonical,tool:'paint'});eq(offers.at(-1)[0].codes,db);
""")

    def test_49_overlays_live_exact_heat_and_idle_cache(self):
        editor(r"""
const [a,b]=await pair();const overlay=field('2');pointer('pointerdown',64,64);
const canvas=overlays()[1],pixels=canvas.pixels;
eq(pixels,view.overlayPixels(b.codes,view.OVERLAY_COLORS[overlay.slot]));
pointer('pointerup',64,64);const after=canvas.pixels;press('Heat View');assert.equal(canvas.pixels,after);
redraw();assert.equal(canvas.pixels,after);press('Undo');eq(canvas.pixels,view.overlayPixels(b.codes,view.OVERLAY_COLORS[overlay.slot]));
""")

    def test_50_ui_fault_status_not_sticky_refusal_and_tip_priority(self):
        editor(r"""
const [a,b]=await pair();remove('2');click(64,64);assert.ok(error().startsWith('Transfer needs another field'));
await add('2');choose('2');assert.equal(error(),'');
unavailable.add('2');a.settings.shape='custom';click(64,64);
assert.ok(error().startsWith('No custom tip is loaded'));assert.equal(a.history.undoEntries.length,0);
a.settings.shape='disk';redraw();click(64,64);assert.ok(error().startsWith('Choose a field to transfer from:'));
unavailable.delete('2');choose('2');assert.equal(error(),'');
""")

    def test_51_workflow_no_source_tool_or_link_reopen_clean(self):
        adapter(r"""
controller.cancel();nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));await launch();await join('2');
press('Transfer from Painted Field #2');click(64,64);await done();
assert.equal(nodes[0].properties.fieldEditor.tool,'paint');
const workflow=JSON.stringify(graphSnapshot());assert.ok(!/transfer|source|partner|transaction|Painted Field/i.test(workflow));
assert.equal(settingsWrites.length,0);await launch();assert.equal(controller.session.settings.tool,'paint');
assert.equal(controller.fields()[0].transferFrom,null);assert.equal(controller.session.history.undoEntries.length,0);
assert.equal(controller.fields().length,1);assert.equal(extension.settings.length,8);
""")

    def test_52_done_write_set_one_graph_transaction_and_undo_redo(self):
        adapter(r"""
controller.cancel();nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));
await launch();await join('2');await join('3');activate('3');activate('1');
press('Transfer from Painted Field #2');click(64,64);const expectedA=field('1').session.codes.slice(),expectedB=field('2').session.codes.slice();
const before=graphSnapshot();tracker.reset();await done();
assert.deepEqual(events,['before','write 1','callback 1','write 2','callback 2','after']);assert.equal(tracker.undoStack.length,1);
assert.equal(tracker.changeCount,0);eq(await codec.decodeFieldDataUrl(nodes[0].widgets[0].value),expectedA);
eq(await codec.decodeFieldDataUrl(nodes[1].widgets[0].value),expectedB);assert.deepEqual(nodes[2].properties,{});
const after=graphSnapshot();tracker.undo();assert.deepEqual(graphSnapshot(),before);tracker.redo();assert.deepEqual(graphSnapshot(),after);
""")

    def test_53_source_conflict_blocks_entire_done(self):
        self.conflict('2')

    def test_54_destination_conflict_blocks_entire_done(self):
        self.conflict('1')

    def conflict(self, key):
        adapter(r"""
controller.cancel();nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));
await launch();await join('2');press('Transfer from Painted Field #2');click(64,64);
nodes[Number(data)-1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(17));
const before=graphSnapshot();tracker.reset();await done();assert.deepEqual(graphSnapshot(),before);
assert.deepEqual(events,[]);assert.equal(tracker.undoStack.length,0);
assert.equal(error(),`Painted Field #${data}: the stored field changed while editing. Remove it from this session to keep the other changes, or Cancel and reopen.`);
""", key)

    def test_55_done_finishes_transfer_stroke_and_opening_offer(self):
        adapter(r"""
controller.cancel();nodes[2].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));
await launch();await join('2');await join('3');await join('4');activate('2');press('Transfer from Painted Field #3');
pointer('pointerdown',64,64);const before=graphSnapshot();tracker.reset();await done();
assert.deepEqual(events,['before','write 2','callback 2','write 3','callback 3','after']);assert.equal(tracker.undoStack.length,1);
assert.equal(nodes[0].widgets[0].value,'');assert.deepEqual(nodes[3].properties,{});tracker.undo();assert.deepEqual(graphSnapshot(),before);
""")

    def test_56_no_storage_or_composition_access(self):
        editor(r"""
globalThis.localStorage=new Proxy({},{get(){assert.fail('storage read');},set(){assert.fail('storage write');}});
globalThis.sessionStorage=globalThis.localStorage;
const [a,b]=await pair();for(const s of [a,b])for(const key of ['Strength','strength','mode','links','composition','order','enabled'])
 Object.defineProperty(s,key,{get(){assert.fail('composition read '+key);}});
click(64,64);press('Undo');press('Redo');press('Done');await until(()=>offers.length);
assert.equal(offers[0].length,2);assert.equal(offers[0][0].settings.tool,'paint');
assert.ok(!/transfer|source|partner|transaction/i.test(JSON.stringify(offers)));
""")

    def test_57_pressure_zero_mouse_and_line_do_not_gain_pen_behavior(self):
        editor(r"""
const [a,b]=await pair();Object.assign(a.settings,{pressure_enabled:true,pressure_size:true,pressure_amount:true,pressure_flow:true,build_up:true});
const before=pairSnapshot();click(64,64,{pointerType:'pen',pressure:0});assert.deepEqual(pairSnapshot(),before);
const db=a.codes.slice(),sb=b.codes.slice(),br={...a.settings,tool:'restore',apply_mode:'normal'};
const ref=new engine.Stroke(db,128,128,br,64,64,Uint8Array.from(db,(v,i)=>Math.min(255,v+sb[i])));
click(64,64,{pointerType:'mouse',pressure:0.2});eq(a.codes,ref.result());conserve(sb,db,b.codes,a.codes);
""")

    def test_58_single_field_settings_json_restored_history_shape(self):
        pure(r"""
const settings={...a.session.settings};settings.tool='transfer';settings.transferSource='forbidden';settings.transaction=81;
assert.deepEqual(ui.editorSettings(settings),ui.editorSettings({...settings,tool:'paint'}));
assert.ok(!/transfer|transaction|source/.test(JSON.stringify(ui.editorSettings(settings))));
assert.deepEqual(Object.keys(a.session.history),['undoEntries','redoEntries']);
""")

    def test_25_mixed_history_example_1_later_source_neutral_block(self):
        editor(r"""
const [a,b]=await pair(10,200);a.settings.influence=40;press('Fill with Influence');click(64,64);
activate('2');b.settings.influence=5;press('Fill with Influence');activate('1');
const before=pairSnapshot(),marks=markState();press('Undo');assert.deepEqual(pairSnapshot(),before);assert.deepEqual(markState(),marks);
assert.equal(error(),'Undo Transfer: first undo the later edits of Painted Field #2.');
assert.equal(find('error').style.color,'#cfd8e3');assert.equal(buttons('Undo')[0].disabled,false);
activate('2');press('Undo');assert.equal(b.codes[64*128+64],0);assert.equal(a.codes[64*128+64],240);
activate('1');press('Undo');assert.equal(a.codes[64*128+64],40);assert.equal(b.codes[64*128+64],200);
assert.equal(a.history.undoEntries.length,1);assert.equal(b.history.undoEntries.length,0);
assert.equal(a.history.redoEntries.length,1);assert.equal(b.history.redoEntries.length,2);
press('Redo');assert.equal(a.codes[64*128+64],240);assert.equal(b.codes[64*128+64],0);
activate('2');press('Redo');assert.equal(b.codes[64*128+64],5);
""")

    def test_26_mixed_history_examples_2_and_3_both_sides_block(self):
        pure(r"""
move(a,b);edit(a,7);const before=saved();assert.equal(links.step('undo',b).state,'blocked');unchanged(before);
assert.equal(links.step('undo',a).state,'single');assert.equal(a.session.codes[0],210);
assert.equal(links.step('undo',b).state,'linked');assert.equal(a.session.codes[0],10);assert.equal(b.session.codes[0],200);
move(a,b);edit(a,7);edit(b,9);assert.equal(links.step('undo',a).state,'single');
const blocked=saved();assert.equal(links.step('undo',a).state,'blocked');unchanged(blocked);
assert.equal(links.step('undo',b).state,'single');assert.equal(links.step('undo',a).state,'linked');
assert.equal(a.session.codes[0],10);assert.equal(b.session.codes[0],200);invariants();
""")

    def test_27_unrelated_fields_and_switches_do_not_block_or_reorder(self):
        editor(r"""
const [a,b]=await pair(10,200,4);click(64,64);activate('3');press('Invert');press('Clear');
const beforeC=snapshot(field('3').session),beforeD=snapshot(field('4').session);
const ah=JSON.stringify(a.history),bh=JSON.stringify(b.history);
for(const k of ['3','2','1','3','1'])activate(k);assert.equal(JSON.stringify(a.history),ah);assert.equal(JSON.stringify(b.history),bh);
press('Undo');assert.equal(a.codes[64*128+64],10);assert.equal(b.codes[64*128+64],200);
assert.equal(snapshot(field('3').session),beforeC);assert.equal(snapshot(field('4').session),beforeD);
press('Redo');assert.equal(snapshot(field('3').session),beforeC);assert.equal(snapshot(field('4').session),beforeD);
""")

    def test_28_redo_top_of_both_and_dependency_note(self):
        editor(r"""
const [a,b]=await pair(10,200);b.replace('Before Transfer',uniform(180));click(64,64);press('Undo');
activate('2');press('Undo');activate('1');const before=pairSnapshot();press('Redo');assert.deepEqual(pairSnapshot(),before);
assert.equal(error(),'Redo Transfer: first redo the earlier edits of Painted Field #2.');assert.equal(find('error').style.color,'#cfd8e3');
assert.equal(buttons('Redo')[0].disabled,false);activate('2');press('Redo');activate('1');press('Redo');
assert.equal(a.codes[64*128+64],190);assert.equal(b.codes[64*128+64],0);assert.equal(find('error').style.color,'');
""")

    def test_29_missing_malformed_and_mismatched_links_refuse(self):
        pure(r"""
move(a,b);const de=a.session.history.undoEntries[0],se=b.session.history.undoEntries[0],dl=de.link,sl=se.link;
for(const kind of ['undo','redo']) {
 if(kind==='redo')assert.equal(links.step('undo',a).state,'linked');
 for(const [entry,bad] of [[de,null],[de,{}],[de,{...dl,transaction:999}],[de,{...dl,kind:'other'}],
  [de,{...dl,role:'source'}],[de,{...dl,partner:'A'}],[se,null],[se,{...sl,transaction:999}],[se,{...sl,role:'destination'}]]) {
  entry.link=bad;const before=saved();assert.equal(links.step(kind,a).state,'broken');unchanged(before);de.link=dl;se.link=sl;
 }
 delete de.link;let before=saved();assert.equal(links.step(kind,a).state,'broken');unchanged(before);de.link=dl;
 delete se.link;before=saved();assert.equal(links.step(kind,a).state,'broken');unchanged(before);se.link=sl;
 const entries=b.session.history[kind+'Entries'];entries.pop();before=saved();
 assert.deepEqual(links.step(kind,a),{state:'broken',reason:'missing partner entry'});unchanged(before);entries.push(se);
 members=members.filter(r=>r!==b);before=saved();assert.deepEqual(links.step(kind,a),{state:'broken',reason:'missing partner'});unchanged(before);members.push(b);
 a.session.codes=Uint8Array.of(255);before=saved();assert.deepEqual(links.step(kind,a),{state:'broken',reason:'buffer mismatch'});unchanged(before);
 a.session.codes=de[kind==='undo'?'after':'before'].slice();
}
invariants();
""")

    def test_30_corrupt_ui_error_strings_dirty_cursors_unchanged(self):
        editor(r"""
const [a,b]=await pair();click(64,64);b.history.undoEntries.pop();const before=pairSnapshot(),marks=markState();press('Undo');
assert.deepEqual(pairSnapshot(),before);assert.deepEqual(markState(),marks);
assert.equal(error(),'Undo refused: a Transfer history link is inconsistent (missing partner entry). Nothing was changed.');
assert.equal(find('error').style.color,'');assert.equal(buttons('Undo')[0].disabled,false);
""")

    def test_31_cap_paired_eviction_example_8_preserves_newer_entries(self):
        pure(r"""
for(let i=0;i<5;i++)edit(b,100+i);move(a,b);const transaction=a.session.history.undoEntries.at(-1).link.transaction;
for(let i=0;i<3;i++)edit(b,20+i);for(let i=0;i<100;i++){edit(a,i%2?5:6);invariants();}
assert.equal(a.session.history.undoEntries.length,100);assert.equal(b.session.history.undoEntries.length,3);
assert.ok(!links.transactions.has(transaction));assert.ok(b.session.history.undoEntries.every(e=>!e.link));
assert.equal(b.session.history.undoEntries[0].before[0],0);invariants();
""")

    def test_32_cap_cascade_example_9_disjoint_stamps(self):
        # T1 and T2 use disjoint brush footprints, so B has influence for both.
        # The section 32 sequence, Amount 100 and all join codes are unchanged.
        editor(r"""
const [a,b]=await pair(10,200,3);const c=field('3').session;
activate('3');choose('2');click(24,24);activate('1');click(100,100);
assert.equal(b.history.undoEntries.length,2);activate('3');press('Invert');activate('1');
for(let i=0;i<100;i++){press('Invert');
 const links=controller.__transfer.links;
 for(const pair of links.transactions.values())for(const side of [pair.destination,pair.source])
  assert.ok(side.record.session.history.undoEntries.includes(side.entry));
}
assert.equal(a.history.undoEntries.length,100);assert.equal(b.history.undoEntries.length,0);
assert.equal(c.history.undoEntries.length,1);assert.equal(c.history.undoEntries[0].label,'invert');
assert.equal(controller.__transfer.links.transactions.size,0);
activate('3');press('Undo');assert.equal(c.codes[24*128+24],250);
""", internal=True)

    def test_33_redo_invalidation_example_6_and_preserve_above_partner(self):
        pure(r"""
move(a,b);edit(b,9);links.step('undo',b);links.step('undo',b);edit(a,99);
assert.equal(b.session.history.redoEntries.length,0);assert.equal(links.transactions.size,0);invariants();
// Older steps undone after a Transfer remain above it on Redo and stay redoable.
edit(b,201);edit(a,10);move(a,b);edit(b,7);links.step('undo',b);links.step('undo',b);links.step('undo',b);
edit(a,5);assert.equal(b.session.history.redoEntries.length,1);
assert.equal(links.step('redo',b).state,'single');assert.equal(b.session.codes[0],201);invariants();
""")

    def test_34_removal_unlinks_undo_redo_keeps_surviving_snapshots(self):
        editor(r"""
for(const redo of [false,true]) {
 const [a,b]=await pair(10,200);click(64,64);if(redo)press('Undo');
 const entries=redo?a.history.redoEntries:a.history.undoEntries,entry=entries[0],before=entry.before,after=entry.after;
 remove('2');assert.equal(entry.before,before);assert.equal(entry.after,after);assert.ok(!Object.hasOwn(entry,'link'));
 assert.equal(controller.__transfer.links.transactions.size,0);assert.equal(field('1').transferFrom,null);
 assert.equal(a.settings.tool,'transfer');press(redo?'Redo':'Undo');assert.equal(a.codes[64*128+64],redo?210:10);
 assert.ok(!calls.some(c=>c[0]==='commit'));assert.equal(b.settings.tool,'paint');
}
""", internal=True)

    def test_35_destination_removal_clears_all_relationships(self):
        editor(r"""
await pair(10,200,4);click(64,64);activate('3');choose('1');activate('2');choose('1');remove('1');
assert.equal(field('2').transferFrom,null);assert.equal(field('3').transferFrom,null);
assert.ok(!field('2').session.history.undoEntries[0].link);assert.equal(controller.__transfer.links.transactions.size,0);
for(const r of controller.__transfer.records)assert.ok(!r.transferSource||controller.__transfer.records.includes(r.transferSource));
""", internal=True)

    def test_36_mid_stroke_edit_guard_mouse_pen_transfer(self):
        editor(r"""
for(const mode of ['mouse','pen','transfer']) {
 const [a,b]=await pair();if(mode!=='transfer')press('Paint');
 a.settings.pressure_enabled=true;a.settings.pressure_size=true;
 press('Invert');press('Undo');
 pointer('pointerdown',64,64,mode==='pen'?{pointerType:'pen',pressure:0.5}:{});
 const before=pairSnapshot();
 for(const name of ['Undo','Redo','Clear','Fill with Influence','Invert','Flip Horizontal','Rotate 90° CW']) {
  fire(window,'keydown',{key:'Enter',target:buttons(name)[0]});press(name);assert.deepEqual(pairSnapshot(),before,name);
 }
 pointer('pointerup',64,64);assert.equal(a.history.undoEntries.length,1);
 assert.equal(b.history.undoEntries.length,mode==='transfer'?1:0);
}
""")

    def test_37_abort_all_paths_restore_both_and_binding_survives_tool_change(self):
        editor(r"""
for(const abort of [()=>pointer('pointercancel',64,64),()=>key('Escape'),()=>fire(window,'blur'),
 ()=>fire(find('viewport'),'lostpointercapture'),()=>press('Cancel')]) {
 const [a,b]=await pair();const before=pairSnapshot();pointer('pointerdown',64,64);pointer('pointermove',90,90);
 abort();dom.flush();assert.deepEqual(pairSnapshot(),before);assert.equal(a.history.undoEntries.length,0);assert.equal(b.history.undoEntries.length,0);
}
const [a,b]=await pair(10,200,3);const c=field('3').session,beforeC=snapshot(c);
pointer('pointerdown',64,64);press('Paint');controller.__transfer.records[0].transferSource=controller.__transfer.records[2];
pointer('pointerup',80,64);assertPair(a,b);assert.equal(snapshot(c),beforeC);
""", internal=True)

    def test_38_tripwire_refuses_bounds_and_editor_rolls_back(self):
        run_node(IMPORTS + r"""
for(const [s,d,next] of [[5,20,19],[5,20,26],[200,250,256],[5,20,20.5]])
 assert.throws(()=>transferSource(Uint8Array.of(s),Uint8Array.of(d),[next]),/^Error: Transfer out of range\.$/);
""")
        editor(r"""
const [a,b]=await pair(20,5);const before=pairSnapshot(),result=engine.Stroke.prototype.result;
engine.Stroke.prototype.result=function(){const next=result.call(this);next[64*128+64]=30;return next;};
click(64,64);assert.deepEqual(pairSnapshot(),before);
assert.equal(error(),'Transfer stopped: an internal check failed. Nothing was changed.');engine.Stroke.prototype.result=result;
""")

    def test_39_recording_faults_restore_all_and_never_reuse_ids(self):
        pure(r"""
for(const stage of ['destination-history','source-history','partner-link','destination-buffer','source-buffer']) {
 const before=saved(),id=links.nextTransaction;let reset;
 if(stage.endsWith('-history')) {
  const h=(stage.startsWith('destination')?a:b).session.history,original=h.record;
  h.record=function(...args){original.apply(this,args);throw Error('injected');};reset=()=>h.record=original;
 } else if(stage==='partner-link') {
  const original=Object.freeze;let calls=0;Object.freeze=v=>{if(++calls===2)throw Error('injected');return original(v);};reset=()=>Object.freeze=original;
 } else {
  const session=(stage.startsWith('destination')?a:b).session;let codes=session.codes,once=true;
  Object.defineProperty(session,'codes',{configurable:true,get:()=>codes,set:value=>{codes=value;if(once){once=false;throw Error('injected');}}});
  reset=()=>Object.defineProperty(session,'codes',{configurable:true,writable:true,enumerable:true,value:codes});
 }
 assert.throws(()=>move(a,b),/injected/);reset();unchanged(before);assert.ok(links.nextTransaction>id);
 move(a,b);assert.ok(a.session.history.undoEntries.at(-1).link.transaction>=id+1);links.step('undo',a);invariants();
}
// Prepare failure has made no allocation or history change.
const before=saved();assert.throws(()=>links.record(a,b,a.session.codes,Uint8Array.of(11),b.session.codes,b.session.codes),/Transfer out of range/);unchanged(before);
""")

    def test_40_undo_redo_faults_restore_buffers_histories_table_and_dirty(self):
        pure(r"""
move(a,b);
for(const kind of ['undo','redo']) {
 for(const stage of ['first-history','second-history','first-buffer','second-buffer','prepare']) {
  const before=saved();let reset;
  if(stage.endsWith('history')) {
   const entries=(stage.startsWith('first')?a:b).session.history[(kind==='undo'?'redo':'undo')+'Entries'];
   const original=entries.push;entries.push=function(...args){original.apply(this,args);throw Error('injected');};reset=()=>delete entries.push;
  } else if(stage==='prepare') {
   const bytes=a.session.history[kind+'Entries'].at(-1)[kind==='undo'?'before':'after'];
   bytes.slice=()=>{throw Error('injected');};reset=()=>delete bytes.slice;
  } else {
   const session=(stage.startsWith('first')?a:b).session;let codes=session.codes,once=true;
   Object.defineProperty(session,'codes',{configurable:true,get:()=>codes,set:value=>{codes=value;if(once){once=false;throw Error('injected');}}});
   reset=()=>Object.defineProperty(session,'codes',{configurable:true,writable:true,enumerable:true,value:codes});
  }
  assert.deepEqual(links.step(kind,a),{state:'failed'});reset();unchanged(before);invariants();
 }
 assert.equal(links.step(kind,a).state,'linked');invariants();
}
""")

    def test_41_fault_during_cascade_recording_restores_third_history(self):
        pure(r"""
move(c,b,25);move(a,b,25);edit(c,18);
for(let i=0;i<99;i++)edit(a,i%2?5:6);
const before=saved(),entries=c.session.history.undoEntries,original=entries.splice;
entries.splice=function(...args){original.apply(this,args);throw Error('cascade fault');};
assert.throws(()=>move(a,d,25),/cascade fault/);delete entries.splice;unchanged(before);invariants();
""")

    def test_42_ui_failed_record_and_paired_steps_show_exact_messages(self):
        editor(r"""
const [a,b]=await pair();const original=b.history.record,before=pairSnapshot();
b.history.record=function(...args){original.apply(this,args);throw Error('injected');};click(64,64);b.history.record=original;
assert.deepEqual(pairSnapshot(),before);assert.equal(error(),'Transfer stopped: an internal check failed. Nothing was changed.');
click(64,64);
for(const kind of ['Undo','Redo']) {
 const entries=b.history[kind==='Undo'?'redoEntries':'undoEntries'],original=entries.push,before=pairSnapshot();
 entries.push=function(...args){original.apply(this,args);throw Error('injected');};press(kind);delete entries.push;
 assert.deepEqual(pairSnapshot(),before);assert.equal(error(),`${kind} stopped: an internal check failed. Nothing was changed.`);
 assert.equal(find('error').style.color,'');press(kind);
}
""")

    def test_43_observer_timing_exact_discards_noop_no_callback(self):
        run_node(IMPORTS + r"""
const h=new FieldHistory(),events=[];observeHistory(h,(cleared,evicted)=>{
 assert.equal(h.redoEntries.length,0);assert.ok(h.undoEntries.length<=100);
 if(evicted)assert.ok(!h.undoEntries.includes(evicted));for(const entry of cleared)assert.ok(!h.redoEntries.includes(entry));
 assert.equal(h.undoEntries.at(-1).label,'new');events.push({cleared,evicted});
});
assert.equal(h.record('new',Uint8Array.of(1),Uint8Array.of(1)),false);assert.equal(events.length,0);
for(let i=0;i<100;i++)h.record('new',Uint8Array.of(i),Uint8Array.of(i+1));
const oldest=h.undoEntries[0];h.record('new',Uint8Array.of(100),Uint8Array.of(101));assert.equal(events.at(-1).evicted,oldest);
h.undo();h.undo();const redo=h.redoEntries;h.record('new',Uint8Array.of(99),Uint8Array.of(10));
assert.equal(events.length,102);assert.equal(events.at(-1).cleared,redo);assert.equal(events.at(-1).evicted,null);
""")

    def test_62_third_fourth_entire_state_unchanged_by_pair(self):
        editor(r"""
const [a,b]=await pair(10,200,4);
for(const k of ['3','4']) {const s=field(k).session;s.selection=Uint8Array.from({length:16384},(_,i)=>i%3===0?1:0);
 s.settings.value_profile='radial';s.settings.shape='diamond';s.replace('Unrelated',uniform(70));}
const saved=()=>['3','4'].map(k=>[snapshot(field(k).session),field(k).visible,field(k).transferFrom]);
const before=saved();click(64,64);assert.deepEqual(saved(),before);press('Undo');assert.deepEqual(saved(),before);
press('Redo');assert.deepEqual(saved(),before);
""")

    def test_63_invalid_self_on_activation_and_unknown_member_choice(self):
        editor(r"""
await pair(10,200,3);const [a,b,c]=controller.__transfer.records;
activate('3');a.transferSource=a;activate('1');assert.equal(field('1').transferFrom,null);assert.equal(a.session.settings.tool,'transfer');
const before=pairSnapshot();controller.__transfer.chooseTransferSource({key:'2',label:'Painted Field #2',session:b.session});redraw();
assert.deepEqual(pairSnapshot(),before);a.transferSource={key:'2',session:b.session};redraw();assert.equal(field('1').transferFrom,null);
assert.equal(a.session.settings.tool,'transfer');
""", internal=True)

    def test_64_redo_cascade_and_record_failure_restores_every_stack(self):
        pure(r"""
move(c,b,25);move(a,b,25);edit(c,18);links.step('undo',c);links.step('undo',a);links.step('undo',c);
const before=saved(),entries=a.session.history.redoEntries,original=entries.splice;
entries.splice=function(...args){original.apply(this,args);throw Error('redo cascade');};
assert.throws(()=>move(c,d,25),/redo cascade/);delete entries.splice;unchanged(before);invariants();
move(c,d,25);assert.equal(a.session.history.redoEntries.length,0);invariants();
""")

    def test_65_duplicate_labels_never_resolve_identity(self):
        pure(r"""
for(const r of members)r.label='same';move(a,b);edit(c,17);assert.equal(links.step('undo',a).state,'linked');
assert.equal(c.session.codes[0],17);assert.equal(links.step('redo',b).state,'linked');
const pair=[...links.transactions.values()][0];members=members.filter(r=>r!==b);links.forget(b);
const replacement=makeRecord('B',200);assert.ok(replacement!==pair.source.record);
assert.equal(links.step('undo',a).state,'single');assert.equal(replacement.session.history.undoEntries.length,0);invariants();
""")

    def test_66_prepare_fault_and_empty_steps_are_exactly_neutral(self):
        pure(r"""
let before=saved();assert.equal(links.step('undo',a).state,'empty');assert.equal(links.step('redo',b).state,'empty');unchanged(before);
const original=a.session.history.record;a.session.history.record=()=>{throw Error('before first mutation');};
before=saved();assert.throws(()=>move(a,b),/before first mutation/);unchanged(before);a.session.history.record=original;
assert.equal(links.nextTransaction,2);move(a,b);assert.equal(a.session.history.undoEntries[0].link.transaction,2);invariants();
""")

    def test_44_no_hook_exact_retained_behavior_and_json_20000_steps(self):
        run_node(IMPORTS + r"""
// Literal retained FieldHistory contract: independent of the optional-hook implementation.
class RetainedHistory {
 constructor(){this.undoEntries=[];this.redoEntries=[];}
 record(label,before,after){if(before.length===after.length&&before.every((v,i)=>v===after[i]))return false;
  this.undoEntries.push({label,before:before.slice(),after:after.slice()});
  if(this.undoEntries.length>100)this.undoEntries.shift();this.redoEntries=[];return true;}
 undo(){const entry=this.undoEntries.pop();if(!entry)return null;this.redoEntries.push(entry);return entry.before.slice();}
 redo(){const entry=this.redoEntries.pop();if(!entry)return null;this.undoEntries.push(entry);return entry.after.slice();}
}
const current=new FieldHistory(),old=new RetainedHistory();let seed=0xE10B;
for(let i=0;i<20000;i++) {
 seed=(Math.imul(seed,1664525)+1013904223)>>>0;const action=i<150?0:seed%5;
 const before=Uint8Array.of(seed%256),after=Uint8Array.of(action===4?seed%256:(seed>>>8)%256);
 const x=action===1?current.undo():action===2?current.redo():current.record('edit',before,after);
 const y=action===1?old.undo():action===2?old.redo():old.record('edit',before,after);
 assert.deepEqual(x,y);assert.equal(JSON.stringify(current),JSON.stringify(old));assert.deepEqual(Object.keys(current),Object.keys(old));
}
""")

    def test_67_final_noop_pressure_boundary_synchronizes_both_fields(self):
        editor(r"""
const [a,b]=await pair(0,50),i=64*128+64;
Object.assign(a.settings,{amount:49,hardness:0,build_up:true,flow:100,spacing:'custom',spacing_percent:50,
 pressure_enabled:true,pressure_size:false,pressure_amount:true});
a.selection=empty();a.selection[i]=1;redraw();
const db=a.codes.slice(),sb=b.codes.slice(),before=JSON.stringify(pairSnapshot()),links=controller.__transfer.links,id=links.nextTransaction;
pointer('pointerdown',64.5,64.5,{pointerType:'pen',pressure:1/49});
const stroke=controller.__transfer.stroke;
assert.ok(stroke instanceof engine.PressureStroke);assert.equal(stroke.amounts[i],1);assert.equal(stroke.coverage[i],1);
assert.equal(((50*stroke.amounts[i])*stroke.coverage[i])/100,0.5);
assert.equal(a.codes[i],1);assert.equal(b.codes[i],49);conserve(sb,db,b.codes,a.codes);
// Change pressure without a stamp, then release beyond the next 8-cell stamp.
// Its soft edge has tiny positive coverage; retained renormalization crosses the tie.
pointer('pointermove',64.5,64.5,{pointerType:'pen',pressure:1});
assert.equal(a.codes[i],1);assert.equal(b.codes[i],49);
pointer('pointerup',65.5,73.5,{pointerType:'pen',pressure:1});
assert.equal(stroke.amounts[i],49);assert.equal(((50*stroke.amounts[i])*stroke.coverage[i])/100,0.49999999999999994);
eq(stroke.result(),db);eq(a.codes,db,'final destination');eq(b.codes,sb,'final source');conserve(sb,db,b.codes,a.codes);
assert.equal(JSON.stringify(pairSnapshot()),before);assert.equal(links.transactions.size,0);assert.equal(links.nextTransaction,id);
for(const s of [a,b]){assert.equal(s.history.undoEntries.length,0);assert.equal(s.history.redoEntries.length,0);}
assert.equal(controller.__transfer.stroke,null);assertMessage('');
""", internal=True)

    def test_68_dependency_note_clears_after_successful_undo_and_redo(self):
        editor(r"""
for(const kind of ['undo','redo'])for(const success of ['linked','single']) {
 const [a,b]=await pair(10,200),{records,links}=controller.__transfer,[ar,br]=records;
 if(kind==='redo')b.replace('Before Transfer',uniform(180));
 click(64,64);
 if(kind==='undo')b.replace('Later edit',uniform(7));
 else {press('Undo');assert.equal(links.step('undo',br).state,'single');}
 redraw();const action=kind==='undo'?'Undo':'Redo',before=JSON.stringify(pairSnapshot());press(action);
 assert.equal(JSON.stringify(pairSnapshot()),before);
 const note=kind==='undo'?'Undo Transfer: first undo the later edits of Painted Field #2.':'Redo Transfer: first redo the earlier edits of Painted Field #2.';
 assertMessage(note,true);assert.equal(buttons(action)[0].disabled,false);
 // Unblock without switching fields: switching would itself clear the message.
 if(success==='linked')assert.equal(links.step(kind,br).state,'single');
 else {a.replace('Ordinary edit',uniform(19));if(kind==='redo')assert.equal(links.step('undo',ar).state,'single');}
 redraw();assertMessage(note,true);assert.equal(links.classify(kind,ar).state,success);
 const count=a.history[kind+'Entries'].length;press(action);
 assert.equal(a.history[kind+'Entries'].length,count-1);assertMessage('');redraw();assertMessage('');
}
""", internal=True)

    def test_69_leaving_transfer_clears_m5_and_dependency_note(self):
        editor(r"""
for(const note of [false,true]) {
 const [a,b]=await pair(0,note?200:0);click(64,64);
 if(note){b.replace('Later edit',uniform(7));press('Undo');}
 assertMessage(note?'Undo Transfer: first undo the later edits of Painted Field #2.':
  'Nothing to transfer under the brush: Painted Field #2 is 0 or Painted Field #1 is 255 there.',note);
 press('Paint');assert.equal(a.settings.tool,'paint');assert.equal(field('1').transferFrom,null);
 assertMessage('');redraw();assertMessage('');
}
""")

    def test_70_valid_source_choice_clears_no_source_m5_and_note(self):
        editor(r"""
for(const condition of ['no-source','m5','note']) {
 const [a,b]=await pair(0,condition==='note'?200:0,3);
 if(condition==='no-source') {
  unavailable.add('2');redraw();click(64,64);
  assertMessage('Choose a field to transfer from: Advanced ▸ Brush Behavior ▸ Transfer from…');
  assert.equal(find('transfer-status').textContent,error());assert.equal(find('field-transfer').textContent,'Transfer: no source field');
 } else {
  click(64,64);if(condition==='note'){b.replace('Later edit',uniform(7));press('Undo');}
  assertMessage(condition==='note'?'Undo Transfer: first undo the later edits of Painted Field #2.':
   'Nothing to transfer under the brush: Painted Field #2 is 0 or Painted Field #1 is 255 there.',condition==='note');
 }
 choose('3');assert.equal(a.settings.tool,'transfer');assert.equal(field('1').transferFrom,'3');assertMessage('');
 assert.equal(find('transfer-status').textContent,'');redraw();assertMessage('');
}
""")

    def test_71_no_source_r2_precedes_unavailable_destination_r3(self):
        editor(r"""
const [a,b]=await pair();unavailable.add('1');unavailable.add('2');redraw();
const r2='Choose a field to transfer from: Advanced ▸ Brush Behavior ▸ Transfer from…';
assert.equal(find('transfer-status').textContent,r2);assert.equal(find('field-transfer').textContent,'Transfer: no source field');
const before=JSON.stringify(pairSnapshot());click(64,64);assertMessage(r2);assert.equal(JSON.stringify(pairSnapshot()),before);
unavailable.delete('2');choose('2');
const r3='Cannot transfer into Painted Field #1: it is no longer in this graph.';
assert.equal(find('transfer-status').textContent,r3);assertMessage('');click(64,64);assertMessage(r3);
unavailable.delete('1');redraw();assertMessage('');assert.equal(find('transfer-status').textContent,'');
assert.equal(a.history.undoEntries.length,0);assert.equal(b.history.undoEntries.length,0);
""")

    def test_72_m5_uses_only_covered_destination_selection(self):
        editor(r"""
const [a,b]=await pair(0,200);Object.assign(a.settings,{shape:'square',size:128,amount:1});
b.codes[0]=0;a.codes[1]=255;b.codes[2]=1;
a.selection=empty();a.selection[0]=a.selection[1]=1;
// The source selects movable cells instead; its selection must have no effect.
b.selection=uniform(1);b.selection[0]=b.selection[1]=0;redraw();
const db=a.codes.slice(),sb=b.codes.slice(),selectionBefore=b.selection.slice(),id=controller.__transfer.links.nextTransaction;
pointer('pointerdown',64,64);assertMessage('');pointer('pointerup',64,64);
assertMessage('Nothing to transfer under the brush: Painted Field #2 is 0 or Painted Field #1 is 255 there.');
eq(a.codes,db);eq(b.codes,sb);eq(b.selection,selectionBefore);
// Selected positive capacity that only rounds to zero must be silent.
a.selection[2]=1;pointer('pointerdown',64,64);assertMessage('');pointer('pointerup',64,64);assertMessage('');
eq(a.codes,db);eq(b.codes,sb);
// An unselected movable cell under the brush cannot suppress or create M5.
a.settings.size=16;a.selection=empty();a.selection[0]=1;click(64,64);assertMessage('');
eq(a.codes,db);eq(b.codes,sb);conserve(sb,db,b.codes,a.codes);
assert.equal(a.history.undoEntries.length,0);assert.equal(b.history.undoEntries.length,0);
assert.equal(controller.__transfer.links.nextTransaction,id);assert.equal(controller.__transfer.links.transactions.size,0);
""", internal=True)

    def test_73_partner_buffer_corruption_refused_before_any_mutation(self):
        editor(r"""
for(const kind of ['undo','redo'])for(const initiator of ['1','2']) {
 const [a,b]=await pair();click(64,64);if(kind==='redo')press('Undo');activate(initiator);
 const {records,links}=controller.__transfer,own=records.find(r=>r.key===initiator),partner=records.find(r=>r!==own);
 assert.equal(links.classify(kind,own).state,'linked');
 partner.session.codes=partner.session.codes.slice();partner.session.codes[0]^=1;redraw();
 const before=JSON.stringify(pairSnapshot()),table=[...links.transactions],id=links.nextTransaction,marks=markState();
 const saved=records.map(r=>({r,codes:r.session.codes,undo:r.session.history.undoEntries,redo:r.session.history.redoEntries,
  ue:r.session.history.undoEntries.slice(),re:r.session.history.redoEntries.slice()}));
 let writes=0;
 for(const r of records){let codes=r.session.codes;Object.defineProperty(r.session,'codes',{configurable:true,enumerable:true,
  get:()=>codes,set:value=>{writes++;codes=value;}});}
 const classification=links.classify(kind,own);
 // Keep failures bounded: a wrong linked result carries a cyclic DOM record.
 assert.equal(classification.state,'broken');assert.equal(classification.reason,'buffer mismatch');assert.equal(writes,0);
 const action=kind==='undo'?'Undo':'Redo';press(action);
 assert.equal(writes,0,'refusal must precede buffer writes');assert.equal(JSON.stringify(pairSnapshot()),before);
 assert.deepEqual(markState(),marks);assert.equal(links.nextTransaction,id);assert.equal(links.transactions.size,table.length);
 for(const [id,pair] of table)assert.equal(links.transactions.get(id),pair);
 for(const s of saved){assert.equal(s.r.session.codes,s.codes);for(const [kind,entries] of [['undo',s.ue],['redo',s.re]]) {
  assert.equal(s.r.session.history[kind+'Entries'],s[kind]);assert.equal(s[kind].length,entries.length);
  entries.forEach((entry,i)=>assert.equal(s[kind][i],entry));}}
 assertMessage(`${action} refused: a Transfer history link is inconsistent (buffer mismatch). Nothing was changed.`);
 assert.equal(buttons(action)[0].disabled,false);
}
""", internal=True)

    def test_74_failed_prepare_does_not_allocate_transaction_id(self):
        pure(r"""
move(a,b,25);links.step('undo',a);
for(const fault of ['invalid-complement','injected-prepare']) {
 const before=saved(),id=links.nextTransaction,original=links.members;
 if(fault==='injected-prepare')links.members=()=>{throw Error('injected prepare');};
 try {
  if(fault==='injected-prepare')assert.throws(()=>move(a,b,25),/^Error: injected prepare$/);
  else assert.throws(()=>links.record(a,b,a.session.codes,Uint8Array.of(a.session.codes[0]+1),b.session.codes,b.session.codes),/^Error: Transfer out of range\.$/);
 } finally {links.members=original;}
 unchanged(before);assert.equal(links.nextTransaction,id,'prepare cannot consume ID');
 assert.equal(move(a,b,25),true);assert.equal(a.session.history.undoEntries.at(-1).link.transaction,id);
 assert.equal(b.session.history.undoEntries.at(-1).link.transaction,id);assert.equal(links.nextTransaction,id+1);
 invariants();links.step('undo',a);
}
""")

    def test_75_randomized_cap_retention_20000_operations_without_removals(self):
        model = HistoryModel()
        rng = random.Random(0xE10BCA)
        trace = []
        keys = list(model.fields)
        # No removals: histories must reach the cap repeatedly. The independent
        # set-closure model still compares every stack and transaction after every op.
        for _ in range(20000):
            action = rng.randrange(100)
            if action < 26:
                op = ['edit', rng.randrange(256)]
            elif action < 60:
                op = ['transfer', rng.choice([k for k in keys if k != model.active]), rng.randrange(1, 101), False]
            elif action < 75:
                op = ['activate', rng.choice(keys)]
            elif action < 87:
                op = ['undo', False]
            elif action < 95:
                op = ['redo', False]
            else:
                op = ['edit', rng.randrange(256)]
            model.apply(op)
            trace.append([op, model.digest()])
        result = pure(r"""
const {createHash}=await import('node:crypto');
members.forEach((r,i)=>{r.key=String(i+1);r.label=r.key;});let active=a;
const counts={transfers:0,cap_linked_roots:0,cap_paired_evictions:0,cap_cascade_evictions:0,
 redo_invalidations:0,paired_steps:0,faults_reached:0};
for(const r of members)observeHistory(r.session.history,(cleared,evicted)=>{
 const before=links.transactions.size;links.discarded(cleared,evicted);const removed=before-links.transactions.size;
 if(evicted){const root=evicted.link?1:0;counts.cap_linked_roots+=root;counts.cap_paired_evictions+=removed;
  counts.cap_cascade_evictions+=removed-root;}else counts.redo_invalidations+=removed;
});
const digest=()=>{
 const rows=members.map(r=>[r.key,r.session.codes[0],...['undo','redo'].map(kind=>r.session.history[kind+'Entries'].map(e=>
  [e.before[0],e.after[0],e.link?.transaction??null,e.link?.role??null,e.link?.partner??null])),r.transferSource?.key??null,r.session.settings.tool,true]);
 return createHash('sha256').update(JSON.stringify([active.key,links.nextTransaction,rows,[...links.transactions.keys()].sort((a,b)=>a-b)])).digest('hex');
};
for(let i=0;i<data.length;i++) {
 const [op,expected]=data[i],[action,...args]=op;
 if(action==='activate')active=members.find(r=>r.key===args[0]);
 else if(action==='edit')edit(active,args[0]);
 else if(action==='transfer') {
  const source=members.find(r=>r.key===args[0]);active.transferSource=source;active.session.settings.tool='transfer';
  if(move(active,source,args[1]))counts.transfers++;
 } else {if(links.step(action,active).state==='linked')counts.paired_steps++;}
 invariants();assert.equal(digest(),expected,`cap model step ${i}: ${JSON.stringify(op)}`);
}
console.log(JSON.stringify({operations:data.length,...counts,divergences:0}));
""", trace)
        self.assertEqual(result, dict(operations=20000, **model.counts, divergences=0))
        self.assertGreaterEqual(result['cap_linked_roots'], 100)
        self.assertGreaterEqual(result['cap_paired_evictions'], 100)
        self.assertGreaterEqual(result['cap_cascade_evictions'], 30)
        self.assertGreaterEqual(result['redo_invalidations'], 100)
        self.assertGreaterEqual(result['paired_steps'], 100)
        print('E10b randomized cap model: ' + json.dumps(result, sort_keys=True))

    def test_76_amount_zero_product_boundary_65536_pairs_and_setting_refusal(self):
        result = editor(r"""
let checked=0;
for(let block=0;block<4;block++) {
 const [a,b]=await pair(0,0),{links}=controller.__transfer;
 a.codes=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256);
 b.codes=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 Object.assign(a.settings,{shape:'square',size:128,amount:0});
 const db=a.codes.slice(),sb=b.codes.slice(),id=links.nextTransaction;
 // Zero is still invalid as a configured setting; exercise the actual UI refusal.
 click(64,64);assertMessage('Invalid brush amount');eq(a.codes,db);eq(b.codes,sb);
 assert.equal(controller.__transfer.stroke,null);assert.equal(links.nextTransaction,id);
 a.settings.amount=1;pointer('pointerdown',64,64);
 const stroke=controller.__transfer.stroke;assert.ok(stroke instanceof engine.Stroke);
 assert.ok(stroke.coverage.every(v=>v===1));
 // Test-only boundary injection after validation. Real result(), complement,
 // endStroke and linked-history code execute unchanged; no runtime API is added.
 stroke.brush.amount=0;pointer('pointerup',64,64);
 eq(a.codes,db,'zero destination');eq(b.codes,sb,'zero source');conserve(sb,db,b.codes,a.codes);
 for(const s of [a,b]){assert.equal(s.history.undoEntries.length,0);assert.equal(s.history.redoEntries.length,0);}
 assert.equal(links.transactions.size,0);assert.equal(links.nextTransaction,id);checked+=db.length;
 // A real subsequent stroke commits the same next ID.
 a.settings.amount=100;click(64,64);assert.equal(a.history.undoEntries.at(-1).link.transaction,id);
 assert.equal(b.history.undoEntries.at(-1).link.transaction,id);
}
console.log(JSON.stringify({checked}));
""", internal=True)
        self.assertEqual(result, {'checked': 65536})
