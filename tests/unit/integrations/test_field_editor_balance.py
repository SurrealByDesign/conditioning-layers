"""ADR-0035 offline qualification: independent Balance arithmetic, history and UI oracles.

Uses the retained fenced inline Node / fake DOM / graph tracker harnesses. No live host,
browser, timing assertion or product helper as an expected-value oracle: targets come from an
exhaustive scan of the feasible interval, written here in Python and in the Node harness.
"""
import base64
import functools
import hashlib
import json
import math
import random
import re
import unittest

from test_field_editor_custom_tip import CORE, ROOT, run_node, first_difference
from test_field_editor_multi_field import EDITOR, adapter
from test_field_editor_transfer import HistoryModel as RetainedTransferModel


IMPORTS = f"""
const transferModule = await import({json.dumps((CORE / 'transfer.js').as_uri())});
const historyModule = await import({json.dumps((CORE / 'history.js').as_uri())});
const {{TransferLinks,transferReach,transferEngineBrush,transferSource,balanceTarget,balancePartner,balanceSettled,
  BALANCE_LABEL,BALANCE_DEFAULT_SHARE}}=transferModule;
const {{FieldHistory,observeHistory}}=historyModule;
"""

# Independent of the product: every value of [L, H] is scanned for the least exact distance to
# T·P/100, and an exact half goes toward the current active value.
ORACLE = r"""
const nearestCache=new Map();
const nearest=(t,p)=>{const key=t*101+p;let found=nearestCache.get(key);if(found)return found;
 const low=Math.max(0,t-255),high=Math.min(255,t);let best=Infinity;found=[];
 for(let v=low;v<=high;v++){const d=Math.abs(100*v-t*p);if(d<best){best=d;found=[v];}else if(d===best)found.push(v);}
 nearestCache.set(key,found);return found;};
const goal=(a,b,p)=>{const v=nearest(a+b,p);return v.length===1||Math.abs(v[0]-a)<Math.abs(v[1]-a)?v[0]:v[1];};
const goals=(a,b,p)=>Uint8Array.from(a,(v,i)=>goal(v,b[i],p));
const shift=(d,k)=>Math.sign(d)*Math.floor((Math.abs(d)*k+50)/100);
// V1–V3 at every cell: conservation, direction, no overshoot, codes.
const balanced=(a0,b0,a1,b1,p,label='balance')=>{
 if(a0.length!==a1.length||b0.length!==b1.length||a0.length!==b0.length)assert.fail(label+' length');
 for(let i=0;i<a0.length;i++){
  const t=goal(a0[i],b0[i],p),low=Math.min(a0[i],t),high=Math.max(a0[i],t);
  if(a1[i]+b1[i]!==a0[i]+b0[i])assert.fail(`${label} conservation [${i}]`);
  if(a1[i]<low||a1[i]>high)assert.fail(`${label} direction or overshoot [${i}]: ${a0[i]}->${a1[i]}, target ${t}`);
  if(!(a1[i]>=0&&a1[i]<=255&&b1[i]>=0&&b1[i]<=255))assert.fail(`${label} bounds [${i}]`);
 }
};
"""

HELPERS = r"""
const uniform = n => new Uint8Array(16384).fill(n);
const center = 64*128+64;
const heading = text => all().find(e=>e.tagName==='SUMMARY'&&e.textContent.startsWith(text));
const balances = () => all().filter(e=>e.tagName==='BUTTON'&&e.textContent?.startsWith('Balance with '));
const transfers = () => all().filter(e=>e.tagName==='BUTTON'&&e.textContent?.startsWith('Transfer from '));
const textInputs = () => all().filter(e=>e.tagName==='INPUT'&&e.type==='text').length;
const rangeInputs = () => all().filter(e=>e.tagName==='INPUT'&&e.type==='range').length;
const partnerWith = k => press(`Balance with Painted Field #${k}`);
const transferFrom = k => press(`Transfer from Painted Field #${k}`);
const share = (n,commit=true) => type('Active Share (%)',n,commit);
const markState = () => all().filter(e=>e.className==='field-mark').map(e=>e.textContent);
const roles = () => all().filter(e=>e.className==='field-role').map(e=>e.textContent);
const state = () => JSON.stringify(controller.fields().map(f=>({key:f.key,session:snapshot(f.session),changed:f.changed,
 from:f.transferFrom,with:f.balanceWith,share:f.balanceShare,visible:f.visible})));
const assertMessage = (text, neutral=false) => {
 assert.equal(error(),text);assert.equal(find('error').className,'error');
 assert.equal(find('error').attributes.role,'alert');assert.equal(find('error').style.color,neutral?'#cfd8e3':'');
};
const full = () => {for(const f of controller.fields())Object.assign(f.session.settings,{shape:'square',size:128,hardness:100,amount:100});};
const setup = async (values=[20,180]) => {
 controller.cancel();joined.clear();joined.add('1');unavailable.clear();
 values.forEach((v,i)=>{const s=sources.get(String(i+1));s.codes=uniform(v);s.settings={...brushes.BRUSH_DEFAULTS,...brush,size:16};});
 controller=open();dom.flush();
 for(let k=2;k<=values.length;k++)await add(String(k));
 return controller.fields().map(f=>f.session);
};
const balancePair = async (a0=20,b0=180,count=2,p=null) => {
 const sessions=await setup([a0,b0,50,80].slice(0,count));partnerWith('2');if(p!==null)share(p);return sessions;
};
const assertBalance = (a,b,activeKey='1',partnerKey='2') => {
 const ae=a.history.undoEntries.at(-1),pe=b.history.undoEntries.at(-1);
 assert.equal(ae.label,'Balance');assert.equal(pe.label,'Balance');
 assert.ok(Number.isSafeInteger(ae.link.transaction)&&ae.link.transaction>0);
 assert.deepEqual(ae.link,{transaction:pe.link.transaction,kind:'balance',role:'active',partner:partnerKey});
 assert.deepEqual(pe.link,{transaction:ae.link.transaction,kind:'balance',role:'partner',partner:activeKey});
 assert.ok(Object.isFrozen(ae.link)&&Object.isFrozen(pe.link));
 for(let i=0;i<ae.before.length;i++)if(ae.after[i]-ae.before[i]!==pe.before[i]-pe.after[i])assert.fail('linked conservation '+i);
};
"""

HOOK = 'return {get session() { return active.session; }, cancel,'


def editor(body, data=None, *, internal=False):
    script = IMPORTS + ORACLE + EDITOR + HELPERS + body
    if internal:
        source = (CORE / 'editor_ui.js').read_text(encoding='utf-8')
        assert source.count(HOOK) == 1
        source = source.replace(HOOK, 'return {__balance: {records, links, settleSource, settlePartner, chooseTransferSource, '
                                'chooseBalancePartner, get stroke() { return stroke; }, get binding() { return balance; }}, '
                                'get session() { return active.session; }, cancel,')
        source = re.sub(r'"\./([^"\n]+)"', lambda m: json.dumps((CORE / m[1]).as_uri()), source)
        url = 'data:text/javascript;base64,' + base64.b64encode(source.encode()).decode()
        script = f'const testedUi=await import({json.dumps(url)});\n' + script.replace(
            'ui.openInfluenceFieldEditor', 'testedUi.openInfluenceFieldEditor')
    return run_node(script.replace('assert.equal(', 'exact('), data)


def instrumented(body, data=None):
    """Count the editor's calls of the Balance arithmetic and of the engine result, without changing them."""
    source = (CORE / 'editor_ui.js').read_text(encoding='utf-8')
    names = 'BALANCE_DEFAULT_SHARE, balanceTarget, balancePartner, balanceSettled} from "./transfer.js";'
    assert source.count(names) == 1
    source = source.replace(names, 'BALANCE_DEFAULT_SHARE, balanceTarget as realTarget, balancePartner as realPartner, '
                                   'balanceSettled} from "./transfer.js";')
    source = re.sub(r'"\./([^"\n]+)"', lambda m: json.dumps((CORE / m[1]).as_uri()), source)
    source += ('\nfunction balanceTarget(...args) { globalThis.balanceCalls.target++; return realTarget(...args); }'
               '\nfunction balancePartner(...args) { globalThis.balanceCalls.partner++; return realPartner(...args); }\n')
    url = 'data:text/javascript;base64,' + base64.b64encode(source.encode()).decode()
    script = (f'globalThis.balanceCalls={{target:0,partner:0}};const testedUi=await import({json.dumps(url)});\n'
              + IMPORTS + ORACLE + EDITOR.replace('ui.openInfluenceFieldEditor', 'testedUi.openInfluenceFieldEditor')
              + HELPERS + body)
    return run_node(script.replace('assert.equal(', 'exact('), data)


PURE = IMPORTS + ORACLE + r"""
const eq=(a,b,label='codes')=>{assert.equal(a.length,b.length,label);for(let i=0;i<a.length;i++)
 if(a[i]!==b[i])assert.fail(`${label}[${i}]: ${a[i]} != ${b[i]}`);};
let members=[];
const links=new TransferLinks(()=>members);
const makeRecord=(key,value=0)=>{
 const record={key,label:key,transferSource:null,balancePartner:null,session:ui.createEditorSession(Uint8Array.of(value),{})};
 observeHistory(record.session.history,links.discarded);members.push(record);return record;
};
const a=makeRecord('A',10),b=makeRecord('B',200),c=makeRecord('C',50),d=makeRecord('D',80);
const edit=(r,value)=>r.session.replace('Edit',Uint8Array.of(value));
const move=(destination,source,amount=100)=>{
 const db=destination.session.codes,sb=source.session.codes;
 const da=db.map((v,i)=>v+Math.floor((Math.min(sb[i],255-v)*amount+50)/100));
 const sa=sb.map((v,i)=>v-(da[i]-db[i]));
 return links.record(destination,source,db,da,sb,sa);
};
// Independent target and movement; the product coordinator records these snapshots.
const bal=(active,partner,p=50,amount=100)=>{
 const ab=active.session.codes,pb=partner.session.codes,target=goals(ab,pb,p);
 const aa=ab.map((v,i)=>v+shift(target[i]-v,amount)),pa=pb.map((v,i)=>v-(aa[i]-ab[i]));
 return links.recordBalance(active,partner,ab,aa,pb,pa,target);
};
const saved=()=>({members:members.map(r=>({r,codes:r.session.codes,values:[...r.session.codes],
 undo:r.session.history.undoEntries.slice(),redo:r.session.history.redoEntries.slice(),dirty:r.session.changed()})),
 table:[...links.transactions.entries()],next:links.nextTransaction});
const unchanged=(before,ids=true)=>{
 for(const s of before.members){assert.ok(s.r.session.codes===s.codes,'buffer reference');eq(s.r.session.codes,s.values);
  for(const kind of ['undo','redo']){const now=s.r.session.history[kind+'Entries'];assert.equal(now.length,s[kind].length);
   now.forEach((entry,i)=>assert.ok(entry===s[kind][i],'entry identity'));}
  assert.equal(s.r.session.changed(),s.dirty);}
 assert.equal(links.transactions.size,before.table.length);
 for(const [id,pair] of before.table)assert.ok(links.transactions.get(id)===pair,'table identity');
 if(ids)assert.equal(links.nextTransaction,before.next);
};
const OTHER={destination:'source',source:'destination',active:'partner',partner:'active'};
const KIND={destination:'transfer',source:'transfer',active:'balance',partner:'balance'};
const invariants=()=>{
 let halves=0;
 for(const r of members){const h=r.session.history;assert.ok(h.undoEntries.length+h.redoEntries.length<=100);
  if(h.undoEntries.length)eq(r.session.codes,h.undoEntries.at(-1).after);
  if(h.redoEntries.length)eq(r.session.codes,h.redoEntries.at(-1).before);
  for(const kind of ['undo','redo'])for(const entry of h[kind+'Entries'])if(entry.link){
   halves++;const p=links.transactions.get(entry.link.transaction);assert.ok(p,'no orphan');
   assert.equal(p.kind,entry.link.kind,'row kind');assert.equal(KIND[entry.link.role],p.kind,'role of kind');
   const own=p[entry.link.role],other=p[OTHER[entry.link.role]];
   assert.ok(own.record===r&&own.entry===entry,'canonical identities');
   assert.ok(members.includes(other.record)&&other.record!==r);
   assert.ok(other.record.session.history[kind+'Entries'].includes(other.entry),'same stack');
   assert.equal(entry.link.partner,other.record.key);
  }
 }
 assert.equal(halves,links.transactions.size*2);assert.ok(links.transactions.size<=200);
 for(const p of links.transactions.values()){
  const [x,y]=p.kind==='transfer'?[p.destination,p.source]:[p.active,p.partner];
  for(let i=0;i<x.entry.before.length;i++){
   assert.equal(x.entry.after[i]-x.entry.before[i],y.entry.before[i]-y.entry.after[i]);
   if(p.kind==='transfer')assert.ok(x.entry.after[i]>=x.entry.before[i]);
  }
 }
};
"""


def pure(body, data=None):
    return run_node(PURE + body, data)


def half(value):
    lower = math.floor(value)
    return lower + (value - lower >= 0.5)


@functools.lru_cache(maxsize=None)
def nearest(total, share):
    """Every feasible active value whose exact distance to total·share/100 is least."""
    low, high = max(0, total - 255), min(255, total)
    distances = [abs(100 * value - total * share) for value in range(low, high + 1)]
    best = min(distances)
    return tuple(low + i for i, distance in enumerate(distances) if distance == best)


def target(active, partner, share):
    """The feasible split nearest the ratio point; an exact half goes toward the current active value."""
    return min(nearest(active + partner, share), key=lambda value: abs(value - active))


def moved(distance, amount):
    return ((distance > 0) - (distance < 0)) * ((abs(distance) * amount + 50) // 100)


@functools.lru_cache(maxsize=1)
def nearest_table():
    return [[list(nearest(total, share)) for share in range(101)] for total in range(511)]


def sha(value):
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


class MixedModel:
    """Independent scalar model of one shared linked history holding Transfers and Balances.

    Retention is a set closure, not the coordinator's work queue. Balance targets come from the
    exhaustive scan above. Every entry records its kind; a transaction is (kind, two sides).
    """
    START = {'1': 10, '2': 200, '3': 50, '4': 80}
    ROLES = {'transfer': ('destination', 'source'), 'balance': ('active', 'partner')}

    def __init__(self, keys=('1', '2', '3', '4')):
        self.fields, self.entries, self.transactions = {}, {}, {}
        self.next_id = self.next_entry = 1
        self.active = keys[0]
        self.unavailable = set()
        self.control = False
        self.counts = dict(transfers=0, balances=0, cap_linked_roots=0, cap_ended=0, cap_cascade=0, redo_ended=0,
                           mixed_discards=0, paired_steps=0, blocked=0, faults_reached=0)
        for key in keys:
            self.join(key)

    def join(self, key):
        self.fields[key] = dict(code=self.START[key], undo=[], redo=[], source=None, partner=None, share=50, tool='paint')

    def valid(self, key):
        return key != self.active and key in self.fields and key not in self.unavailable

    def settle(self):
        field = self.fields[self.active]
        for name in ('source', 'partner'):
            if field[name] is not None and not self.valid(field[name]):
                field[name] = None

    def discard(self, kind, roots):
        removed = set(roots)
        while True:
            more = set()
            for entry_id in removed:
                transaction = self.entries[entry_id]['transaction']
                if transaction is None:
                    continue
                for key, partner in self.transactions[transaction][1]:
                    history = self.fields[key][kind]
                    if partner in history:
                        more.update(history[:history.index(partner) + 1])
            if more <= removed:
                break
            removed.update(more)
        for field in self.fields.values():
            field[kind] = [entry for entry in field[kind] if entry not in removed]
        ended = {}
        for entry in removed:
            transaction = self.entries[entry]['transaction']
            if transaction is not None:
                ended[transaction] = self.transactions[transaction][0]
        for transaction in ended:
            del self.transactions[transaction]
        return ended

    def record(self, key, after):
        field = self.fields[key]
        before = field['code']
        if before == after:
            return None
        entry_id = self.next_entry
        self.next_entry += 1
        self.entries[entry_id] = dict(before=before, after=after, transaction=None, kind=None, role=None, partner=None)
        field['undo'].append(entry_id)
        kinds = set()
        if len(field['undo']) > 100:
            evicted = field['undo'][0]
            root = self.entries[evicted]['transaction'] is not None
            ended = self.discard('undo', [evicted])
            self.counts['cap_linked_roots'] += root
            self.counts['cap_ended'] += len(ended)
            self.counts['cap_cascade'] += len(ended) - root
            kinds.update(ended.values())
        ended = self.discard('redo', field['redo'][:])
        self.counts['redo_ended'] += len(ended)
        kinds.update(ended.values())
        self.counts['mixed_discards'] += kinds == {'transfer', 'balance'}
        field['code'] = after
        return entry_id

    def link(self, kind, first, second, step, fault):
        if not step:
            return
        transaction = self.next_id
        self.next_id += 1
        if fault:
            self.counts['faults_reached'] += 1
            return
        self.counts[kind + 's'] += 1
        ids = [self.record(*first), self.record(*second)]
        for entry_id, role, other in zip(ids, self.ROLES[kind], (second[0], first[0])):
            self.entries[entry_id].update(transaction=transaction, kind=kind, role=role, partner=other)
        self.transactions[transaction] = (kind, [(first[0], ids[0]), (second[0], ids[1])])

    def transfer(self, destination, source, amount, fault=False):
        d, s = self.fields[destination]['code'], self.fields[source]['code']
        step = (min(s, 255 - d) * amount + 50) // 100
        self.link('transfer', (destination, d + step), (source, s - step), step, fault)

    def balance(self, active, partner, share, amount, fault=False):
        a, b = self.fields[active]['code'], self.fields[partner]['code']
        step = moved(target(a, b, share) - a, amount)
        self.link('balance', (active, a + step), (partner, b - step), step, fault)

    def step(self, kind, key, fault=False):
        field = self.fields[key]
        if not field[kind]:
            return
        top = field[kind][-1]
        transaction = self.entries[top]['transaction']
        if transaction is None:
            sides = [(key, top)]
        else:
            sides = self.transactions[transaction][1]
            if any(not self.fields[k][kind] or self.fields[k][kind][-1] != e for k, e in sides):
                self.counts['blocked'] += 1
                return
            if fault:
                self.counts['faults_reached'] += 1
                return
            self.counts['paired_steps'] += 1
        for k, entry_id in sides:
            side = self.fields[k]
            side[kind].pop()
            side['redo' if kind == 'undo' else 'undo'].append(entry_id)
            side['code'] = self.entries[entry_id]['before' if kind == 'undo' else 'after']

    def undoable(self, key):
        transaction = self.entries[self.fields[key]['undo'][-1]]['transaction']
        return transaction is None or all(self.fields[k]['undo'] and self.fields[k]['undo'][-1] == e
                                          for k, e in self.transactions[transaction][1])

    def apply(self, op):
        """One UI operation on the active field; the editor settles pointers on every render."""
        action, *args = op
        field = self.fields[self.active]
        if action == 'activate':
            if args[0] in self.fields and args[0] not in self.unavailable:
                self.active = args[0]
        elif action == 'available':
            key, available = args
            (self.unavailable.discard if available else self.unavailable.add)(key)
        elif action in ('choose', 'source'):
            if self.valid(args[0]):
                field.update(source=args[0], partner=None, tool='transfer')
        elif action == 'partner':
            if self.valid(args[0]):
                field.update(partner=args[0], source=None, tool='balance')
                self.control = True
        elif action == 'share':
            if self.control:
                field['share'] = args[0]
        elif action == 'tool':
            field.update(tool=args[0], source=None, partner=None)
        elif action == 'reset':
            field.update(tool='paint' if field['tool'] in ('restore', 'transfer', 'balance') else field['tool'],
                         source=None, partner=None, share=50)
        elif action == 'edit':
            self.record(self.active, args[0])
        elif action == 'transfer':
            source, amount, fault = args
            self.apply(['source', source])
            self.transfer(self.active, source, amount, fault)
        elif action == 'balance':
            partner, share, amount, fault = args
            self.apply(['partner', partner])
            self.apply(['share', share])
            self.balance(self.active, partner, share, amount, fault)
        elif action in ('undo', 'redo'):
            self.step(action, self.active, args[0])
        elif action == 'remove':
            key = args[0]
            index = list(self.fields).index(key)
            for transaction, (_, sides) in list(self.transactions.items()):
                if any(k == key for k, _ in sides):
                    for _, entry in sides:
                        self.entries[entry].update(transaction=None, kind=None, role=None, partner=None)
                    del self.transactions[transaction]
            del self.fields[key]
            for other in self.fields.values():
                for name in ('source', 'partner'):
                    if other[name] == key:
                        other[name] = None
            if self.active == key:
                self.active = list(self.fields)[min(index, len(self.fields) - 1)]
        elif action == 'join':
            self.join(args[0])
        self.settle()

    def apply_links(self, op):
        """One coordinator operation with explicit fields: no active field, pointers or availability."""
        action, *args = op
        if action == 'edit':
            self.record(*args)
        elif action == 'transfer':
            self.transfer(*args)
        elif action == 'balance':
            self.balance(*args)
        else:
            self.step(action, args[0])

    def stacks(self, field, keys):
        return [[[self.entries[e][k] for k in keys] for e in field[kind]] for kind in ('undo', 'redo')]

    def digest(self):
        keys = ('before', 'after', 'transaction', 'kind', 'role', 'partner')
        rows = [[key, f['code'], *self.stacks(f, keys), f['source'], f['partner'], f['share'], f['tool'],
                 key not in self.unavailable] for key, f in self.fields.items()]
        return sha([self.active, self.next_id, rows, sorted([t, kind] for t, (kind, _) in self.transactions.items())])

    def links_digest(self):
        keys = ('before', 'after', 'transaction', 'kind', 'role', 'partner')
        rows = [[key, f['code'], *self.stacks(f, keys)] for key, f in self.fields.items()]
        return sha([self.next_id, rows, sorted([t, kind] for t, (kind, _) in self.transactions.items())])

    def transfer_digest(self):
        """The retained E10b model's digest format, for Transfer-only equivalence."""
        keys = ('before', 'after', 'transaction', 'role', 'partner')
        rows = [[key, f['code'], *self.stacks(f, keys), f['source'], f['tool'], key not in self.unavailable]
                for key, f in self.fields.items()]
        return sha([self.active, self.next_id, rows, sorted(self.transactions)])


class BalanceTests(unittest.TestCase):
    def test_01_one_field_has_no_balance_and_stays_e10(self):
        editor(r"""
assert.ok(!all().some(e=>/(balance-|field-balance)/.test(e.className||'')));
assert.equal(balances().length,0);assert.equal(textInputs(),41);assert.equal(rangeInputs(),0);
assert.deepEqual(inventory(),retainedInventory);
assert.equal(heading('Brush Behavior').parent.children.at(-1),heading('Pen Pressure').parent);
assert.deepEqual(heading('Advanced').parent.children.filter(e=>e.className==='group').map(e=>e.children[0].textContent.split(' · ')[0]),
 ['Brush Behavior','Brush Shape & Transform','Value Profile','Field Tools']);
assert.deepEqual(controller.fields().map(f=>[f.balanceWith,f.balanceShare]),[[null,50]]);
const s=controller.session,before=s.codes.slice(),reference=new engine.Stroke(before,128,128,s.settings,64,64,s.initial);
click(64,64);eq(s.codes,reference.result());press('Undo');eq(s.codes,before);press('Redo');eq(s.codes,reference.result());
press('Done');await until(()=>offers.length);eq(offers[0][0].codes,reference.result());
assert.ok(!/balance|partner|share/i.test(JSON.stringify(offers[0][0].settings)));
""")

    def test_02_chooser_two_to_four_fields_order_position_and_inventory(self):
        editor(r"""
for(let n=2;n<=4;n++) {await add(String(n));
 for(let k=1;k<=n;k++){activate(String(k));
  assert.deepEqual(balances().filter(e=>!e.hidden).map(e=>e.textContent),
   Array.from({length:n},(_,i)=>i+1).filter(i=>i!==k).map(i=>`Balance with Painted Field #${i}`));
  assert.equal(textInputs(),41);assert.equal(rangeInputs(),0);
 }
 assert.deepEqual(balances().map(e=>e.textContent),Array.from({length:n},(_,i)=>`Balance with Painted Field #${i+1}`));
 const behavior=heading('Brush Behavior').parent,row=balances()[0].parent,children=behavior.children;
 assert.equal(row.className,'bar balance-partners');assert.equal(row.parent,behavior);assert.equal(children.at(-1),row);
 assert.equal(children.at(-2),heading('Pen Pressure').parent);
 const transferRow=transfers()[0].parent;
 assert.ok(children[children.indexOf(transferRow)-1].textContent.startsWith('Restore paints'));
 assert.equal(children[children.indexOf(transferRow)+3],heading('Pen Pressure').parent);
 assert.ok(!find('balance-share')&&!find('balance-help')&&!find('balance-status'));
}
const strip=find('field-editing').parent;
assert.deepEqual(strip.children.slice(0,3).map(e=>e.className),['field-editing','field-transfer','field-balance']);
assert.equal(find('field-balance').hidden,true);assert.equal(find('field-balance').textContent,'');
assert.equal(heading('Advanced').parent.children.filter(e=>e.className==='group').length,4);
assert.deepEqual(buttons('Paint')[0].parent.children.map(e=>e.textContent),['Paint','Erase']);
""")

    def test_03_partner_never_self_choice_effects_show_and_anchor(self):
        editor(r"""
const [a,b]=await setup([10,200,50]);transferFrom('2');press('Rectangle Select');
all().filter(e=>e.className==='field-show')[1].click();dom.flush();assert.equal(field('2').visible,false);
const self=state();partnerWith('1');assert.equal(state(),self);assert.ok(balances()[0].hidden);
assert.equal(a.settings.tool,'transfer');assert.equal(a.selectTool,'rectangle');
partnerWith('2');assert.equal(a.settings.tool,'balance');assert.equal(field('1').balanceWith,'2');
assert.equal(field('1').transferFrom,null);assert.equal(a.selectTool,null);assert.equal(field('2').visible,true);
assert.equal(balances()[1].attributes['aria-pressed'],'true');assert.equal(balances()[2].attributes['aria-pressed'],'false');
assert.equal(transfers()[1].attributes['aria-pressed'],'false');assert.equal(roles()[1],'partner');
assert.ok(tabs()[1].title.endsWith(' · balance partner'));
// A changed partner clears the line anchor: Shift-click paints a plain stamp, not a line.
click(10,10);partnerWith('3');const before=a.codes.slice();click(110,110,{shiftKey:true});
assert.equal(a.codes[center],before[center]);assert.notEqual(a.codes[110*128+110],before[110*128+110]);
// Choosing the same partner again keeps the anchor.
click(10,10);partnerWith('3');click(20,10,{shiftKey:true});assert.notEqual(a.codes[10*128+15],before[10*128+15]);
""")

    def test_04_unavailable_partner_hidden_removed_partner_gone(self):
        editor(r"""
const [a,b]=await setup([10,200,50,80]);partnerWith('2');unavailable.add('3');redraw();
assert.ok(balances().find(e=>e.textContent.endsWith('#3')).hidden);
const before=state();partnerWith('3');assert.equal(state(),before);assert.equal(field('1').balanceWith,'2');
remove('4');assert.ok(!balances().some(e=>e.textContent.endsWith('#4')));
assert.deepEqual(balances().filter(e=>!e.hidden).map(e=>e.textContent),['Balance with Painted Field #2']);
""")

    def test_05_invalid_remembered_partner_clears_on_activation_render_and_start(self):
        editor(r"""
await setup([10,200,50]);const [r1,r2,r3]=controller.__balance.records;const a=r1.session;
partnerWith('2');r1.balancePartner=r1;redraw();
assert.equal(field('1').balanceWith,null);assert.equal(a.settings.tool,'balance');
assert.equal(find('field-balance').textContent,'Balance: no partner field');
assert.ok(balances().every(e=>e.attributes['aria-pressed']==='false'));
const br2='Choose a field to balance with: Advanced ▸ Brush Behavior ▸ Balance with…';
assert.equal(find('balance-status').textContent,br2);assert.equal(find('balance-status').hidden,false);
let before=state();click(64,64);assertMessage(br2);assert.equal(state(),before);
// A record that is not a member, then activation with an unavailable partner.
r1.balancePartner={key:'2',label:'Painted Field #2',session:r2.session};redraw();assert.equal(field('1').balanceWith,null);
partnerWith('2');activate('3');unavailable.add('2');activate('1');
assert.equal(field('1').balanceWith,null);assert.equal(a.settings.tool,'balance');
// Render with an unavailable partner.
unavailable.delete('2');partnerWith('2');unavailable.add('2');redraw();assert.equal(field('1').balanceWith,null);
// Stroke start: the partner becomes unavailable with no render in between.
unavailable.delete('2');partnerWith('2');unavailable.add('2');
fire(find('viewport'),'pointerdown',{clientX:264,clientY:264});dom.flush();
assert.equal(field('1').balanceWith,null);assert.equal(controller.__balance.stroke,null);assertMessage(br2);
fire(find('viewport'),'pointerup');assert.equal(a.history.undoEntries.length,0);assert.equal(r2.session.history.undoEntries.length,0);
// BR2 precedes BR3; then BR3; then BR1 with one field.
unavailable.add('1');redraw();click(64,64);assertMessage(br2);
unavailable.delete('2');partnerWith('2');const br3='Cannot balance Painted Field #1: it is no longer in this graph.';
assert.equal(find('balance-status').textContent,br3);click(64,64);assertMessage(br3);
unavailable.delete('1');redraw();assertMessage('');remove('2');remove('3');
assert.equal(a.settings.tool,'balance');click(64,64);
assertMessage('Balance needs another field in this session. Add Field…, or choose Paint.');
assert.equal(find('field-balance').textContent,'Balance: no partner field');assert.ok(balances().length===0);
assert.equal(a.history.undoEntries.length,0);
""", internal=True)

    def test_06_active_share_control_created_once_at_first_balance_choice(self):
        editor(r"""
await setup([10,200,50,80]);
for(const k of ['2','3','4']){transferFrom(k);assert.equal(textInputs(),41);}
assert.ok(!find('balance-share')&&!input('Active Share (%)'));
partnerWith('2');assert.equal(textInputs(),42);assert.equal(rangeInputs(),0);
const behavior=heading('Brush Behavior').parent,children=behavior.children,row=find('bar balance-partners');
assert.deepEqual(children.slice(children.indexOf(row)).map(e=>e.className),['bar balance-partners','balance-share','balance-help','balance-status']);
const label=find('balance-share');assert.equal(label.tagName,'LABEL');assert.equal(label.children[0],input('Active Share (%)'));
assert.equal(input('Active Share (%)').title,'Drag to adjust; click to type. Shift: fine, Ctrl/Command: coarse. Enter: commit, Esc: revert.');
assert.equal(input('Active Share (%)').value,'50');
press('Paint');assert.equal(label.hidden,true);assert.equal(find('balance-help').hidden,true);assert.equal(find('balance-status').hidden,true);
partnerWith('3');assert.equal(label.hidden,false);assert.equal(find('balance-help').hidden,false);
assert.ok(!all().some(e=>e.tagName==='BUTTON'&&/^\d+:\d+$/.test(e.textContent||'')));
remove('4');await add('4');activate('4');partnerWith('1');
assert.equal(textInputs(),42);assert.equal(all().filter(e=>e.className==='balance-share').length,1);
""")

    def test_07_default_share_fifty_per_field_join_and_reopen(self):
        editor(r"""
await setup([20,180,50]);assert.deepEqual(controller.fields().map(f=>f.balanceShare),[50,50,50]);
partnerWith('2');assert.equal(find('field-balance').textContent,'Balance: Painted Field #1 ↔ Painted Field #2 · 50:50');
share(75);activate('2');assert.equal(input('Active Share (%)').value,'50');partnerWith('1');
assert.equal(find('field-balance').textContent,'Balance: Painted Field #2 ↔ Painted Field #1 · 50:50');
activate('1');assert.equal(input('Active Share (%)').value,'75');
remove('3');await add('3');assert.equal(field('3').balanceShare,50);
controller.cancel();controller=open();dom.flush();assert.deepEqual(controller.fields().map(f=>[f.balanceShare,f.balanceWith]),[[50,null]]);
""")

    def test_08_fifty_fifty_even_totals_and_odd_totals_settled_from_either_field(self):
        editor(r"""
let [a,b]=await balancePair(40,160);click(64,64);assert.equal(a.codes[center],100);assert.equal(b.codes[center],100);assertBalance(a,b);
for(const [x,y,ex,ey] of [[60,61,60,61],[61,60,61,60],[50,71,60,61],[71,50,61,60]]) {
 [a,b]=await balancePair(x,y);const before=state();click(64,64);
 if(x===ex){assert.equal(state(),before);assert.equal(a.history.undoEntries.length,0);}
 assert.equal(a.codes[center],ex);assert.equal(b.codes[center],ey);
 // The partner's own view of the same pair at 50 names the same split.
 activate('2');partnerWith('1');const again=state();click(64,64);assert.equal(state(),again);
 assert.equal(a.codes[center],ex);assert.equal(b.codes[center],ey);
}
""")

    def test_09_seventy_five_twenty_five_exact(self):
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);click(64,64);
assert.equal(a.codes[center],150);assert.equal(b.codes[center],50);assert.equal(a.codes[0],20);assert.equal(b.codes[0],180);
assertBalance(a,b);balanced(Uint8Array.of(20),Uint8Array.of(180),Uint8Array.of(a.codes[center]),Uint8Array.of(b.codes[center]),75);
""")

    def test_10_twenty_five_seventy_five_and_ties_toward_the_current_value(self):
        editor(r"""
for(const [x,y,ex] of [[10,200,52],[100,110,53],[40,160,50]]) {
 const [a,b]=await balancePair(x,y,2,25);click(64,64);assert.equal(a.codes[center],ex);assert.equal(b.codes[center],x+y-ex);
}
""")

    def test_11_share_100_reaches_min_255_total(self):
        editor(r"""
for(const [x,y] of [[10,200],[100,200],[0,255],[255,0]]) {
 const [a,b]=await balancePair(x,y,2,100);click(64,64);
 assert.equal(a.codes[center],Math.min(255,x+y));assert.equal(b.codes[center],x+y-Math.min(255,x+y));
}
""")

    def test_12_share_0_reaches_max_0_total_minus_255(self):
        editor(r"""
for(const [x,y] of [[100,100],[200,150],[255,0],[0,255]]) {
 const [a,b]=await balancePair(x,y,2,0);click(64,64);
 assert.equal(a.codes[center],Math.max(0,x+y-255));assert.equal(b.codes[center],x+y-Math.max(0,x+y-255));
}
""")

    def test_13_totals_above_255_clamp_only_the_target(self):
        editor(r"""
for(const [x,y,p,ex,ey] of [[200,150,25,95,255],[250,250,100,255,245],[250,250,0,245,255],[200,150,75,255,95],[130,200,50,165,165]]) {
 const [a,b]=await balancePair(x,y,2,p);click(64,64);assert.equal(a.codes[center],ex);assert.equal(b.codes[center],ey);
 for(const k of [50,15]){
  const [c,d]=await balancePair(x,y,2,p);c.settings.amount=k;click(64,64);
  assert.equal(c.codes[center],x+shift(ex-x,k));assert.equal(d.codes[center],y-shift(ex-x,k));
 }
}
""")

    def test_14_total_510_never_moves_and_reports_settled(self):
        editor(r"""
for(const p of [0,25,50,75,100]) {
 const [a,b]=await balancePair(255,255,2,p),before=state(),id=controller.__balance.links.nextTransaction;click(64,64);
 assert.equal(state(),before);assert.equal(controller.__balance.links.nextTransaction,id);
 assertMessage(`Nothing to balance under the brush: Painted Field #1 and Painted Field #2 are already at ${p}:${100-p} there, as closely as whole 0–255 codes allow.`);
}
""", internal=True)

    def test_15_total_0_never_moves_and_reports_settled(self):
        editor(r"""
for(const p of [0,50,100]) {
 const [a,b]=await balancePair(0,0,2,p),before=state();click(64,64);assert.equal(state(),before);
 assertMessage(`Nothing to balance under the brush: Painted Field #1 and Painted Field #2 are already at ${p}:${100-p} there, as closely as whole 0–255 codes allow.`);
}
""")

    def test_16_odd_total_tie_symmetry_every_pair_at_50_from_both_fields(self):
        # Full coverage; every pair, both perspectives. Half up would ping-pong on every odd total.
        result = editor(r"""
let moved=0,pingPong=0;
for(let block=0;block<4;block++) {
 const a0=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256),b0=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 const [a,b]=await balancePair(0,0);full();a.codes=a0.slice();b.codes=b0.slice();click(64,64);
 const fromA=[a.codes.slice(),b.codes.slice()];balanced(a0,b0,fromA[0],fromA[1],50,'from A');
 const [c,d]=await balancePair(0,0);full();c.codes=a0.slice();d.codes=b0.slice();activate('2');partnerWith('1');click(64,64);
 eq(c.codes,fromA[0],'orientation A');eq(d.codes,fromA[1],'orientation B');
 // Balancing the result again from either field moves nothing.
 activate('1');const settled=state();click(64,64);activate('2');click(64,64);assert.equal(state(),settled);
 for(let i=0;i<16384;i++){if(fromA[0][i]!==a0[i])moved++;const t=a0[i]+b0[i];
  if(t%2&&Math.floor((t*50+50)/100)!==t-Math.floor((t*50+50)/100))pingPong++;}
}
console.log(JSON.stringify({moved,pingPong}));
""")
        self.assertEqual(result['pingPong'], 32768)
        self.assertGreater(result['moved'], 30000)

    def test_17_already_balanced_noop_no_entry_no_dirty_bm5_once_and_silent_cases(self):
        editor(r"""
const [a,b]=await balancePair(60,61,2,50),{links}=controller.__balance,id=links.nextTransaction;
const before=state(),marks=markState();click(64,64);assert.equal(state(),before);assert.deepEqual(markState(),marks);
assert.equal(a.history.undoEntries.length+b.history.undoEntries.length,0);assert.equal(links.nextTransaction,id);
const bm5='Nothing to balance under the brush: Painted Field #1 and Painted Field #2 are already at 50:50 there, as closely as whole 0–255 codes allow.';
assertMessage(bm5);pointer('pointerdown',64,64);assertMessage('');pointer('pointermove',70,64);assertMessage('');pointer('pointerup',70,64);assertMessage(bm5);
// Rounding only: d = 40 at Amount 1 moves nothing and says nothing.
a.codes=uniform(0);b.codes=uniform(40);share(100);a.settings.amount=1;redraw();click(64,64);assertMessage('');
eq(a.codes,uniform(0));eq(b.codes,uniform(40));
// No selected cell under the brush: silent.
a.settings.amount=100;a.selection=uniform(0);a.selection[0]=1;redraw();click(64,64);assertMessage('');eq(a.codes,uniform(0));
assert.equal(a.history.undoEntries.length,0);assert.equal(links.nextTransaction,id);
""", internal=True)

    def test_18_active_field_increases_toward_its_share(self):
        editor(r"""
const [a,b]=await balancePair(30,170,2,60);click(64,64);assert.equal(a.codes[center],120);assert.equal(b.codes[center],80);
assert.ok(a.history.undoEntries[0].after[center]>a.history.undoEntries[0].before[center]);
""")

    def test_19_active_field_decreases_and_one_stroke_moves_both_ways(self):
        editor(r"""
let [a,b]=await balancePair(200,40,2,50);click(64,64);assert.equal(a.codes[center],120);assert.equal(b.codes[center],120);
[a,b]=await balancePair(0,0,2,50);full();
a.codes=Uint8Array.from({length:16384},(_,i)=>i<8192?20:200);b.codes=Uint8Array.from({length:16384},(_,i)=>i<8192?180:40);
const a0=a.codes.slice(),b0=b.codes.slice();click(64,64);balanced(a0,b0,a.codes,b.codes,50);
assert.equal(a.codes[0],100);assert.equal(a.codes[16383],120);assert.equal(b.codes[0],100);assert.equal(b.codes[16383],120);
assert.equal(a.history.undoEntries.length,1);assertBalance(a,b);
""")

    def test_20_conservation_every_cell_of_many_soft_strokes(self):
        editor(r"""
const [a,b]=await balancePair(0,0,2,37);Object.assign(a.settings,{size:44,hardness:23,amount:61});
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*73+11)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>(i*29+101)%256);
for(const [p,path] of [[37,[[10,10],[60,70],[118,20]]],[81,[[100,100],[20,40]]],[0,[[64,10],[64,120]]],[100,[[5,64],[123,64]]]]) {
 share(p);const a0=a.codes.slice(),b0=b.codes.slice(),total=a0.map((v,i)=>v+b0[i]);
 pointer('pointerdown',...path[0]);for(const q of path.slice(1))pointer('pointermove',...q);pointer('pointerup',...path.at(-1));
 balanced(a0,b0,a.codes,b.codes,p);for(let i=0;i<16384;i++)if(a.codes[i]+b.codes[i]!==a0[i]+b0[i])assert.fail('total '+i);
}
assert.equal(a.history.undoEntries.length,4);
""")

    def test_21_no_overshoot_long_build_up_strokes_and_repeated_stamps(self):
        editor(r"""
const [a,b]=await balancePair(0,0,2,70);Object.assign(a.settings,{size:24,hardness:0,amount:100,build_up:true,flow:100,spacing:'custom',spacing_percent:5});
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*13+7)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>(i*101+3)%256);
const a0=a.codes.slice(),b0=b.codes.slice(),target=goals(a0,b0,70);
pointer('pointerdown',30,30);for(let r=0;r<12;r++)for(const [x,y] of [[90,30],[90,90],[30,90],[30,30]])pointer('pointermove',x,y);
pointer('pointerup',30,30);balanced(a0,b0,a.codes,b.codes,70);
let reached=0;for(let i=0;i<16384;i++)if(a.codes[i]===target[i]&&a0[i]!==target[i])reached++;assert.ok(reached>500);
""")

    def test_22_amount_100_reaches_the_target_at_full_coverage(self):
        editor(r"""
const [a,b]=await balancePair(0,0,2,33);full();
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
const a0=a.codes.slice(),b0=b.codes.slice(),target=goals(a0,b0,33);click(64,64);
eq(a.codes,target,'active at target');eq(b.codes,Uint8Array.from(target,(v,i)=>a0[i]+b0[i]-v),'partner at complement');
""")

    def test_23_amount_50_moves_half_the_distance_rounded_once(self):
        editor(r"""
let [a,b]=await balancePair(20,180,2,75);a.settings.amount=50;click(64,64);assert.equal(a.codes[center],85);assert.equal(b.codes[center],115);
[a,b]=await balancePair(0,0,2,41);full();a.settings.amount=50;
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*91+5)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>(i*17+200)%256);
const a0=a.codes.slice(),b0=b.codes.slice();click(64,64);
for(let i=0;i<16384;i++){const m=shift(goal(a0[i],b0[i],41)-a0[i],50);if(a.codes[i]!==a0[i]+m||b.codes[i]!==b0[i]-m)assert.fail('half '+i);}
""")

    def test_24_low_amount_rounding_distances_49_50_150_255(self):
        editor(r"""
for(const [d,m] of [[49,0],[50,1],[150,2],[255,3]]) for(const up of [true,false]) {
 // Up: 0 with d at share 100. Down: d with 0 at share 0. Either way the distance to the target is d.
 const [a,b]=await balancePair(up?0:d,up?d:0,2,up?100:0);a.settings.amount=1;click(64,64);
 assert.equal(a.codes[center],up?m:d-m);assert.equal(b.codes[center],up?d-m:m);
}
""")

    def test_25_amount_0_boundary_every_pair_through_the_product_path(self):
        result = editor(r"""
let checked=0;
for(let block=0;block<4;block++) for(const p of [0,50,100]) {
 const [a,b]=await balancePair(0,0,2,p),{links}=controller.__balance;
 a.codes=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 Object.assign(a.settings,{shape:'square',size:128,amount:0});const a0=a.codes.slice(),b0=b.codes.slice(),id=links.nextTransaction;
 // The configured setting stays invalid: the real refusal.
 click(64,64);assertMessage('Invalid brush amount');eq(a.codes,a0);eq(b.codes,b0);assert.equal(controller.__balance.stroke,null);
 a.settings.amount=1;pointer('pointerdown',64,64);const stroke=controller.__balance.stroke;assert.ok(stroke.coverage.every(v=>v===1));
 // Test-only boundary injection after validation; result(), the complement and recording run unchanged.
 stroke.brush.amount=0;pointer('pointerup',64,64);
 eq(a.codes,a0,'zero active');eq(b.codes,b0,'zero partner');assert.equal(links.nextTransaction,id);assert.equal(links.transactions.size,0);
 for(const s of [a,b]){assert.equal(s.history.undoEntries.length,0);assert.equal(s.history.redoEntries.length,0);}
 for(let i=0;i<16384;i++)if(shift(goal(a0[i],b0[i],p)-a0[i],0)!==0)assert.fail('formula '+i);
 checked+=16384;a.settings.amount=100;click(64,64);
 if(a.history.undoEntries.length)assert.equal(a.history.undoEntries.at(-1).link.transaction,id);
}
type('Amount (%)',0);assert.equal(controller.session.settings.amount,1);
console.log(JSON.stringify({checked}));
""", internal=True)
        self.assertEqual(result, {'checked': 196608})

    def check_case(self, settings=None, *, share=75, pressure=False, selection=False, tip=False):
        result = editor(r"""
const [a,b]=await balancePair(20,180,2,data.share);
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256);
b.codes=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
Object.assign(a.settings,data.settings);
if(data.tip){a.tip={width:3,height:2,luminance:Uint8Array.of(255,96,170,41,230,153),alpha:Uint8Array.of(180,255,32,90,210,255)};
 a.settings.custom_tip=await tips.encodeTipDataUrl(a.tip);}
if(data.selection)a.selection=Uint8Array.from({length:16384},(_,i)=>i%3===0?0:1);
b.selection=Uint8Array.from({length:16384},(_,i)=>i%2);const selectionBefore=b.selection.slice();redraw();
const a0=a.codes.slice(),b0=b.codes.slice();
// Coverage and per-cell Amount come from the retained engine; coverage does not depend on the target.
const br={...a.settings,tip:a.tip,tool:'restore',apply_mode:'normal'};
const path=[[20,32,16384],[35,47,32768],[70,64,49151],[103,97,65535]];
const ref=data.pressure?new engine.PressureStroke(a0,128,128,br,...path[0].slice(0,2),a0,a.selection,path[0][2]):
 new engine.Stroke(a0,128,128,br,...path[0].slice(0,2),a0,a.selection);
for(const p of path.slice(1))ref.add(...(data.pressure?p:p.slice(0,2)));
const extra=p=>data.pressure?{pointerType:'pen',pressure:p/65535}:{};
pointer('pointerdown',20,32,extra(path[0][2]));
for(const [x,y,p] of path.slice(1))pointer('pointermove',x,y,extra(p));
pointer('pointerup',103,97,extra(65535));
balanced(a0,b0,a.codes,b.codes,data.share);eq(b.selection,selectionBefore);assertBalance(a,b);
console.log(JSON.stringify({a0:[...a0],b0:[...b0],a1:[...a.codes],b1:[...b.codes],coverage:[...ref.coverage],
 amounts:ref.amounts?[...ref.amounts]:null,selection:a.selection?[...a.selection]:null,amount:br.amount}));
""", {'settings': settings or {}, 'share': share, 'pressure': pressure, 'selection': selection, 'tip': tip})
        active, partner, covered, directions = [], [], 0, set()
        for i, (a, b, coverage) in enumerate(zip(result['a0'], result['b0'], result['coverage'])):
            amount = result['amounts'][i] if result['amounts'] is not None else result['amount']
            delta = ((target(a, b, share) - a) * amount) * coverage / 100
            step = int(math.copysign(half(abs(delta)), delta)) if delta else 0
            if result['selection'] is not None and not result['selection'][i]:
                step = 0
            covered += coverage > 0
            if step:
                directions.add(step > 0)
            active.append(a + step)
            partner.append(b - step)
        self.assertIsNone(first_difference(result['a1'], active))
        self.assertIsNone(first_difference(result['b1'], partner))
        self.assertGreater(covered, 0)
        result['directions'] = directions
        return result

    def test_26_flow_inactive_without_build_up_and_binary64_with_build_up(self):
        one = self.check_case({'hardness': 35, 'flow': 30, 'build_up': False})
        two = self.check_case({'hardness': 35, 'flow': 100, 'build_up': False})
        self.assertIsNone(first_difference(one['a1'], two['a1']))
        for flow in (30, 100):
            self.check_case({'size': 32, 'hardness': 40, 'amount': 37, 'flow': flow, 'build_up': True}, share=40)

    def test_27_build_up_target_fixed_at_stroke_start_never_passed(self):
        result = self.check_case({'size': 30, 'hardness': 20, 'amount': 90, 'flow': 25, 'build_up': True,
                                  'spacing': 'custom', 'spacing_percent': 10}, share=64)
        self.assertEqual(result['directions'], {True, False})
        editor(r"""
// A share typed mid-stroke applies to the next stroke only.
const [a,b]=await balancePair(0,0,2,75);Object.assign(a.settings,{size:40,hardness:30,build_up:true,flow:30});
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*7+3)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>(i*11+9)%256);
const a0=a.codes.slice(),b0=b.codes.slice(),br={...a.settings,tool:'restore',apply_mode:'normal'};
const ref=new engine.Stroke(a0,128,128,br,30,64,goals(a0,b0,75),null);
for(let x=31;x<=100;x+=3)ref.add(x,64);
pointer('pointerdown',30,64);for(let x=31;x<=100;x+=3){pointer('pointermove',x,64);if(x===61)share(10);}
pointer('pointerup',100,64);eq(a.codes,ref.result(),'start target');balanced(a0,b0,a.codes,b.codes,75);
assert.equal(field('1').balanceShare,10);
""")

    def test_28_pressure_size(self):
        self.check_case({'size': 32, 'hardness': 63, 'pressure_enabled': True,
                         'pressure_size': True, 'pressure_amount': False}, pressure=True, share=30)

    def test_29_pressure_amount_per_cell(self):
        self.check_case({'size': 28, 'hardness': 48, 'amount': 67, 'pressure_enabled': True,
                         'pressure_amount': True, 'pressure_size': False}, pressure=True, share=55)

    def test_30_pressure_flow_and_mouse_and_lines_keep_set_values(self):
        self.check_case({'size': 20, 'hardness': 55, 'amount': 63, 'flow': 30, 'build_up': True,
                         'pressure_enabled': True, 'pressure_size': False, 'pressure_flow': True}, pressure=True, share=80)
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);
Object.assign(a.settings,{pressure_enabled:true,pressure_size:true,pressure_amount:true,pressure_flow:true,build_up:true,amount:70,hardness:40});
redraw();const before=state();click(64,64,{pointerType:'pen',pressure:0});assert.equal(state(),before);
let a0=a.codes.slice(),b0=b.codes.slice(),br={...a.settings,tool:'restore',apply_mode:'normal'};
let ref=new engine.Stroke(a0,128,128,br,64,64,goals(a0,b0,75));
click(64,64,{pointerType:'mouse',pressure:0.2});eq(a.codes,ref.result());balanced(a0,b0,a.codes,b.codes,75);
a0=a.codes.slice();b0=b.codes.slice();ref=new engine.Stroke(a0,128,128,br,64,64,goals(a0,b0,75));ref.add(100,90);
click(100,90,{shiftKey:true,pointerType:'pen',pressure:0.1});eq(a.codes,ref.result());balanced(a0,b0,a.codes,b.codes,75);
""")

    def test_31_active_selection_clips_both_fields(self):
        result = self.check_case({'amount': 57, 'hardness': 51}, selection=True, share=35)
        for i, selected in enumerate(result['selection']):
            if not selected:
                self.assertEqual((result['a1'][i], result['b1'][i]), (result['a0'][i], result['b0'][i]))

    def test_32_partner_selection_ignored_and_unchanged(self):
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);b.selection=uniform(0);const mask=b.selection.slice();redraw();
click(64,64);assert.equal(a.codes[center],150);assert.equal(b.codes[center],50);eq(b.selection,mask);
activate('2');assert.equal(controller.session.selection,b.selection);eq(b.selection,mask);
""")
        self.check_case({'amount': 77, 'hardness': 64}, share=20)

    def test_33_value_profile_inactive_uniform_result_coverage_preview_badges(self):
        editor(r"""
const [a,b]=await balancePair(0,0,2,75);
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
Object.assign(a.settings,{size:30,hardness:45,amount:80});
const a0=a.codes.slice(),b0=b.codes.slice(),uniformRef=new engine.Stroke(a0,128,128,{...a.settings,tool:'restore',apply_mode:'normal'},64,64,goals(a0,b0,75));
Object.assign(a.settings,{value_profile:'radial',gradient_start:11,gradient_end:31});redraw();
assert.equal(heading('Value Profile').textContent,'Value Profile · Radial gradient · 11→31 · inactive for Balance');
assert.ok(all().some(e=>e.tagName==='SMALL'&&!e.hidden&&e.textContent==='Inactive: Balance moves this field and its partner toward the set share. The gradient applies to Paint.'));
pointer('pointermove',64,64);const pixels=find('brush-preview').pixels;let tinted=0;
for(let i=0;i<pixels.length;i+=4)if(pixels[i+3]){tinted++;eq(pixels.slice(i,i+3),[64,160,255]);}assert.ok(tinted>100);
click(64,64);eq(a.codes,uniformRef.result(),'uniform result');assert.equal(a.settings.value_profile,'radial');
""")

    def test_34_raise_and_lower_only_inactive_equal_normal_and_stay_stored(self):
        editor(r"""
const results=[];
for(const mode of ['normal','raise_only','lower_only']) {
 const [a,b]=await balancePair(0,0,2,50);
 a.codes=Uint8Array.from({length:16384},(_,i)=>i%2?30:220);b.codes=Uint8Array.from({length:16384},(_,i)=>i%2?200:20);
 Object.assign(a.settings,{size:40,hardness:60,amount:85,apply_mode:mode});redraw();
 if(mode!=='normal')assert.ok(heading('Brush Behavior').textContent.includes((mode==='raise_only'?'Raise Only':'Lower Only')+' (inactive for Balance)'));
 const a0=a.codes.slice(),b0=b.codes.slice();click(64,64);balanced(a0,b0,a.codes,b.codes,50);
 assert.equal(a.settings.apply_mode,mode);results.push([a.codes.slice(),b.codes.slice()]);
 let up=0,down=0;for(let i=0;i<16384;i++){up+=a.codes[i]>a0[i];down+=a.codes[i]<a0[i];}assert.ok(up>100&&down>100);
}
for(const r of results.slice(1)){eq(r[0],results[0][0]);eq(r[1],results[0][1]);}
""")

    def test_35_custom_tip_alpha_luminance_soft(self):
        self.check_case({'shape': 'custom', 'tip_channel': 'alpha_luminance', 'size': 36,
                         'hardness': 37, 'scale_x': 1.3, 'rotation_degrees': 28}, tip=True, share=60)

    def test_36_procedural_scatter(self):
        self.check_case({'shape': 'procedural', 'procedural_type': 'scatter', 'procedural_seed': 723,
                         'size': 44, 'hardness': 46, 'amount': 53}, share=25)

    def test_37_procedural_noise(self):
        self.check_case({'shape': 'procedural', 'procedural_type': 'noise', 'procedural_seed': 911,
                         'size': 52, 'hardness': 66, 'amount': 71, 'procedural_frequency': 3}, share=85)

    def test_38_hotdog_counts_custom_twin_and_no_hotdog_code(self):
        for count in (1, 8, 1024):
            self.check_case({'shape': 'procedural', 'procedural_particle_shape': 'hotdog',
                             'hotdog_count': count, 'size': 48, 'hardness': 70, 'procedural_particle_rotation': 37,
                             'mirror_horizontal': True, 'hotdog_invert': count == 8}, share=45)
        run_node(IMPORTS + ORACLE + r"""
const a0=Uint8Array.from({length:16384},(_,i)=>i%256),b0=Uint8Array.from(a0,v=>(v*7+3)%256);
for(const count of [1,8,1024]) for(const p of [0,45,100]) {
 const br={...brush,...brushes.BRUSH_DEFAULTS,shape:'procedural',procedural_particle_shape:'hotdog',hotdog_count:count,size:48};
 const mask=brushes.proceduralMask(br),tip={width:mask.width,height:mask.height,luminance:mask.codes,alpha:mask.codes};
 const t=balanceTarget(a0,b0,p),h=new engine.Stroke(a0,128,128,transferEngineBrush(br),64,64,t);
 const c=new engine.Stroke(a0,128,128,transferEngineBrush({...br,shape:'custom',tip,tip_channel:'alpha'}),64,64,t);
 const ha=h.result(),ca=c.result();assert.ok(ha.every((v,i)=>v===ca[i]));
 const hb=balancePartner(b0,a0,ha,t),cb=balancePartner(b0,a0,ca,t);assert.ok(hb.every((v,i)=>v===cb[i]));
 balanced(a0,b0,ha,hb,p);assert.ok(ha.some((v,i)=>v!==a0[i]));
}
""")
        self.assertNotIn('hotdog', (CORE / 'transfer.js').read_text(encoding='utf-8').lower())

    def test_39_line_stroke_one_pair_and_collinear_subdivision(self):
        editor(r"""
const [a,b]=await balancePair(0,0,2,65);Object.assign(a.settings,{hardness:43,amount:61});
a.codes=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256);b.codes=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
click(16,32);const a0=a.codes.slice(),b0=b.codes.slice();click(112,32,{shiftKey:true});
assert.equal(a.history.undoEntries.length,2);assert.equal(b.history.undoEntries.length,2);assertBalance(a,b);
const br={...a.settings,tool:'restore',apply_mode:'normal'},t=goals(a0,b0,65);
const split=new engine.Stroke(a0,128,128,br,16,32,t);for(let x=17;x<=112;x++)split.add(x,32);
const one=new engine.Stroke(a0,128,128,br,16,32,t);one.add(112,32);
eq(split.result(),one.result(),'collinear subdivision');eq(a.codes,one.result());balanced(a0,b0,a.codes,b.codes,65);
// A switch clears the line anchor: the partner's Shift-click paints one plain stamp, not a line.
activate('2');assert.equal(controller.session,b);const b0Line=b.codes.slice();
const stamp=new engine.Stroke(b0Line,128,128,b.settings,80,80,b.initial,b.selection);click(80,80,{shiftKey:true});
eq(b.codes,stamp.result(),'plain stamp');assert.equal(b.history.undoEntries.length,3);assert.ok(!b.history.undoEntries.at(-1).link);
""")

    def test_40_one_linked_transaction_per_stroke_and_row_identity(self):
        editor(r"""
const [a,b]=await balancePair(10,200,2,60);a.settings.amount=25;
pointer('pointerdown',20,20);for(let x=21;x<100;x++)pointer('pointermove',x,20);pointer('pointerup',100,20);
assert.equal(a.history.undoEntries.length,1);assert.equal(b.history.undoEntries.length,1);assertBalance(a,b);
const {links,records}=controller.__balance,ae=a.history.undoEntries[0],pe=b.history.undoEntries[0],row=links.transactions.get(ae.link.transaction);
assert.deepEqual(Object.keys(row),['kind','active','partner']);assert.equal(row.kind,'balance');
assert.equal(row.active.record,records[0]);assert.equal(row.partner.record,records[1]);
assert.equal(row.active.entry,ae);assert.equal(row.partner.entry,pe);assert.equal(row[ae.link.role].entry,ae);assert.equal(row[pe.link.role].entry,pe);
assert.equal(links.transactions.size,1);assert.equal(links.kindOf('undo',records[0]),'balance');assert.equal(links.kindOf('undo',records[1]),'balance');
""", internal=True)

    def test_41_one_shared_id_sequence_with_transfer_never_reused(self):
        editor(r"""
const [a,b,c]=await setup([10,200,50]);const {links,records}=controller.__balance;
const ids=s=>s.history.undoEntries.filter(e=>e.link).map(e=>`${e.link.kind[0]}${e.link.transaction}`).join(',');
transferFrom('2');click(30,30);partnerWith('3');click(60,60);transferFrom('2');click(90,90);
activate('2');partnerWith('3');share(30);click(64,64);
assert.equal(ids(a),'t1,b2,t3');assert.equal(ids(b),'t1,t3,b4');assert.equal(ids(c),'b2,b4');assert.equal(links.nextTransaction,5);
// A no-op refused in prepare takes no id; a rolled-back recording takes one, never reused.
activate('1');partnerWith('2');share(50);c.codes=uniform(0);
const fill=(s,v)=>{s.codes=uniform(v);};fill(a,60);fill(b,61);redraw();click(64,64);assert.equal(links.nextTransaction,5);
fill(b,180);const original=b.history.record;b.history.record=function(...args){original.apply(this,args);throw Error('fault');};
click(64,64);b.history.record=original;assert.equal(links.nextTransaction,6);
click(64,64);assert.equal(a.history.undoEntries.at(-1).link.transaction,6);
// Unlinking by removal and eviction never rewinds the counter.
remove('3');assert.equal(ids(a),'t1,t3,b6');transferFrom('2');click(10,100);assert.equal(a.history.undoEntries.at(-1).link.transaction,7);
for(let i=0;i<100;i++){a.settings.influence=i%2?5:6;press('Fill with Influence');}
assert.equal(ids(a),'');partnerWith('2');a.codes=uniform(0);b.codes=uniform(100);redraw();click(64,64);
assert.equal(a.history.undoEntries.at(-1).link.transaction,8);assert.equal(links.nextTransaction,9);
""", internal=True)

    def test_42_paired_undo_from_either_field_buttons_and_ctrl_z(self):
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);const a0=a.codes.slice(),b0=b.codes.slice();click(64,64);
const a1=a.codes.slice(),b1=b.codes.slice();
for(const k of ['1','2']) {
 activate(k);press('Undo');eq(a.codes,a0);eq(b.codes,b0);
 assert.equal(a.history.undoEntries.length+b.history.undoEntries.length,0);assert.deepEqual(markState(),['','']);
 press('Redo');eq(a.codes,a1);eq(b.codes,b1);key('z',{ctrlKey:true});eq(a.codes,a0);eq(b.codes,b0);
 assert.equal(a.history.redoEntries.length,1);assert.equal(b.history.redoEntries.length,1);key('y',{ctrlKey:true});
}
""")

    def test_43_paired_redo_buttons_ctrl_shift_z_and_ctrl_y(self):
        editor(r"""
const [a,b]=await balancePair(200,40,2,50);const a0=a.codes.slice(),b0=b.codes.slice();click(64,64);
const a1=a.codes.slice(),b1=b.codes.slice();assert.equal(a1[center],120);
for(const [k,redo] of [['1',()=>press('Redo')],['2',()=>key('z',{ctrlKey:true,shiftKey:true})],['1',()=>key('y',{ctrlKey:true})]]) {
 activate(k);press('Undo');eq(a.codes,a0);eq(b.codes,b0);redo();eq(a.codes,a1);eq(b.codes,b1);
 assert.equal(a.history.redoEntries.length+b.history.redoEntries.length,0);assertBalance(a,b);
}
""")

    def test_44_mixed_m1_transfer_then_balance_then_partner_edit(self):
        editor(r"""
await setup([10,200,50]);full();const [A,B]=controller.fields().map(f=>f.session);
const v=s=>{if(!s.codes.every(x=>x===s.codes[0]))assert.fail('uniform');return s.codes[0];};
const stacks=s=>['undoEntries','redoEntries'].map(k=>s.history[k].map(e=>e.link?`${e.link.kind==='transfer'?'T':'Bal'}${e.link.transaction}`:'S').join(','));
const expect=(a,b,sa,sb)=>{assert.deepEqual([v(A),v(B)],[a,b]);assert.deepEqual(stacks(A),sa);assert.deepEqual(stacks(B),sb);};
transferFrom('2');click(64,64);expect(210,0,['T1',''],['T1','']);
partnerWith('2');click(64,64);expect(105,105,['T1,Bal2',''],['T1,Bal2','']);
activate('2');B.settings.influence=30;press('Fill with Influence');expect(105,30,['T1,Bal2',''],['T1,Bal2,S','']);
activate('1');const before=state();press('Undo');assert.equal(state(),before);
assertMessage('Undo Balance: first undo the later edits of Painted Field #2.',true);assert.equal(buttons('Undo')[0].disabled,false);
activate('2');press('Undo');expect(105,105,['T1,Bal2',''],['T1,Bal2','S']);
activate('1');press('Undo');expect(210,0,['T1','Bal2'],['T1','S,Bal2']);assertMessage('');
activate('2');press('Undo');expect(10,200,['','Bal2,T1'],['','S,Bal2,T1']);
activate('1');press('Redo');expect(210,0,['T1','Bal2'],['T1','S,Bal2']);
press('Redo');expect(105,105,['T1,Bal2',''],['T1,Bal2','S']);
activate('2');press('Redo');expect(105,30,['T1,Bal2',''],['T1,Bal2,S','']);
""")

    def test_45_mixed_balance_then_transfer_and_blocked_balance_redo(self):
        editor(r"""
await setup([10,200]);full();const [A,B]=controller.fields().map(f=>f.session);
const v=s=>{if(!s.codes.every(x=>x===s.codes[0]))assert.fail('uniform');return s.codes[0];};
const stacks=s=>['undoEntries','redoEntries'].map(k=>s.history[k].map(e=>e.link?`${e.link.kind==='transfer'?'T':'Bal'}${e.link.transaction}`:'S').join(','));
const expect=(a,b,sa,sb)=>{assert.deepEqual([v(A),v(B)],[a,b]);assert.deepEqual(stacks(A),sa);assert.deepEqual(stacks(B),sb);};
partnerWith('2');click(64,64);expect(105,105,['Bal1',''],['Bal1','']);
transferFrom('2');click(64,64);expect(210,0,['Bal1,T2',''],['Bal1,T2','']);
activate('2');B.settings.influence=30;press('Fill with Influence');
activate('1');let before=state();press('Undo');assert.equal(state(),before);
assertMessage('Undo Transfer: first undo the later edits of Painted Field #2.',true);
activate('2');press('Undo');expect(210,0,['Bal1,T2',''],['Bal1,T2','S']);
activate('1');press('Undo');expect(105,105,['Bal1','T2'],['Bal1','S,T2']);
activate('2');press('Undo');expect(10,200,['','T2,Bal1'],['','S,T2,Bal1']);
press('Redo');expect(105,105,['Bal1','T2'],['Bal1','S,T2']);
activate('1');press('Redo');expect(210,0,['Bal1,T2',''],['Bal1,T2','S']);
activate('2');press('Redo');expect(210,30,['Bal1,T2',''],['Bal1,T2,S','']);
// A blocked Balance Redo names the earlier edit to redo first.
await setup([10,200]);full();const [C,D]=controller.fields().map(f=>f.session);
activate('2');D.settings.influence=180;press('Fill with Influence');activate('1');partnerWith('2');click(64,64);
assert.equal(v(C),95);press('Undo');activate('2');press('Undo');activate('1');before=state();press('Redo');assert.equal(state(),before);
assertMessage('Redo Balance: first redo the earlier edits of Painted Field #2.',true);assert.equal(buttons('Redo')[0].disabled,false);
activate('2');press('Redo');press('Redo');assert.deepEqual([v(C),v(D)],[95,95]);assertMessage('');
""")

    def test_46_unrelated_third_field_never_blocks_m3_and_switching_never_reorders(self):
        editor(r"""
await setup([10,200,50,80]);full();const [A,B,C,D]=controller.fields().map(f=>f.session);
partnerWith('2');share(75);click(64,64);assert.equal(A.codes[center],157);assert.equal(B.codes[center],53);
activate('3');press('Invert');press('Clear');const beforeC=snapshot(C),beforeD=snapshot(D);
const ah=JSON.stringify(A.history),bh=JSON.stringify(B.history);
for(const k of ['3','2','4','1','3','1'])activate(k);assert.equal(JSON.stringify(A.history),ah);assert.equal(JSON.stringify(B.history),bh);
press('Undo');assert.equal(A.codes[center],10);assert.equal(B.codes[center],200);assert.equal(snapshot(C),beforeC);
press('Redo');assert.equal(A.codes[center],157);assert.equal(snapshot(C),beforeC);assert.equal(snapshot(D),beforeD);
""")

    def test_47_mixed_three_field_chain_m2(self):
        editor(r"""
await setup([10,200,50]);full();const [A,B,C]=controller.fields().map(f=>f.session);
const v=s=>{if(!s.codes.every(x=>x===s.codes[0]))assert.fail('uniform');return s.codes[0];};
const values=()=>[v(A),v(B),v(C)];
transferFrom('2');click(64,64);assert.deepEqual(values(),[210,0,50]);
activate('2');partnerWith('3');click(64,64);assert.deepEqual(values(),[210,25,25]);
activate('3');C.settings.influence=90;press('Fill with Influence');assert.deepEqual(values(),[210,25,90]);
activate('1');let before=state();press('Undo');assert.equal(state(),before);
assertMessage('Undo Transfer: first undo the later edits of Painted Field #2.',true);
activate('2');before=state();press('Undo');assert.equal(state(),before);
assertMessage('Undo Balance: first undo the later edits of Painted Field #3.',true);
activate('3');press('Undo');assert.deepEqual(values(),[210,25,25]);
press('Undo');assert.deepEqual(values(),[210,0,50]);
activate('2');press('Undo');assert.deepEqual(values(),[10,200,50]);
assert.deepEqual([A,B,C].map(s=>s.history.undoEntries.length),[0,0,0]);
assert.deepEqual([A,B,C].map(s=>s.history.redoEntries.length),[1,2,2]);
""")

    def test_48_cap_evicts_across_kinds_m4(self):
        editor(r"""
await setup([10,200,50]);full();const [A,B,C]=controller.fields().map(f=>f.session),{links}=controller.__balance;
activate('3');partnerWith('2');click(64,64);assert.deepEqual([C.codes[0],B.codes[0]],[125,125]);
activate('1');transferFrom('2');click(64,64);assert.deepEqual([A.codes[0],B.codes[0]],[135,0]);
activate('3');C.settings.influence=7;press('Fill with Influence');activate('1');
for(let i=0;i<100;i++){A.settings.influence=i%2?5:6;press('Fill with Influence');
 for(const row of links.transactions.values())for(const side of Object.values(row).filter(s=>typeof s==='object'))
  assert.ok(side.record.session.history.undoEntries.includes(side.entry),'no one-sided link');}
assert.equal(A.history.undoEntries.length,100);assert.ok(A.history.undoEntries.every(e=>!e.link));
assert.equal(B.history.undoEntries.length,0);assert.equal(C.history.undoEntries.length,1);
assert.ok(!C.history.undoEntries[0].link);assert.equal(C.codes[0],7);assert.equal(links.transactions.size,0);
activate('3');press('Undo');assert.equal(C.codes[0],125);assert.equal(C.history.undoEntries.length,0);
""", internal=True)

    def test_49_paired_redo_invalidation_across_kinds_m5(self):
        editor(r"""
await setup([10,200]);full();const [A,B]=controller.fields().map(f=>f.session),{links}=controller.__balance;
partnerWith('2');click(64,64);assert.deepEqual([A.codes[0],B.codes[0]],[105,105]);
activate('2');B.settings.influence=9;press('Fill with Influence');press('Undo');press('Undo');
assert.deepEqual([A.codes[0],B.codes[0]],[10,200]);assert.equal(B.history.redoEntries.length,2);
activate('1');A.settings.influence=99;press('Fill with Influence');
assert.equal(A.history.redoEntries.length,0);assert.equal(B.history.redoEntries.length,0);assert.equal(links.transactions.size,0);
activate('2');press('Redo');assert.equal(B.codes[0],200);
// Both kinds stacked in Redo end together when one field records.
await setup([10,200]);full();const [C,D]=controller.fields().map(f=>f.session);
partnerWith('2');click(64,64);transferFrom('2');click(64,64);press('Undo');press('Undo');
assert.deepEqual([C.codes[0],D.codes[0]],[10,200]);assert.equal(controller.__balance.links.transactions.size,2);
activate('2');D.settings.influence=1;press('Fill with Influence');
assert.equal(C.history.redoEntries.length,0);assert.equal(controller.__balance.links.transactions.size,0);
""", internal=True)

    def test_50_removal_clears_both_pointer_kinds_and_unlinks_m6(self):
        editor(r"""
await setup([10,200,50,80]);full();
partnerWith('2');activate('3');transferFrom('2');activate('4');partnerWith('2');remove('2');
assert.deepEqual(controller.fields().map(f=>[f.key,f.transferFrom,f.balanceWith]),[['1',null,null],['3',null,null],['4',null,null]]);
assert.deepEqual(controller.fields().map(f=>f.session.settings.tool),['balance','transfer','balance']);
for(const r of controller.__balance.records)for(const p of [r.transferSource,r.balancePartner])assert.ok(p===null||controller.__balance.records.includes(p));
// Removing the active field validates the next one.
await setup([10,200,50]);activate('2');partnerWith('3');activate('1');partnerWith('2');unavailable.add('3');remove('1');
assert.equal(controller.fields().find(f=>f.active).key,'2');assert.equal(field('2').balanceWith,null);
assert.equal(field('2').session.settings.tool,'balance');
// M6.
await setup([10,200]);full();const [A,B]=controller.fields().map(f=>f.session);
partnerWith('2');click(64,64);activate('2');B.settings.influence=9;press('Fill with Influence');activate('1');
const entry=A.history.undoEntries[0],before=entry.before,after=entry.after;remove('2');
assert.deepEqual(confirms.at(-1),['remove','Painted Field #2']);assert.ok(!Object.hasOwn(entry,'link'));
assert.equal(entry.before,before);assert.equal(entry.after,after);assert.equal(controller.__balance.links.transactions.size,0);
press('Undo');assert.equal(A.codes[0],10);assert.ok(!calls.some(c=>c[0]==='commit'));
assert.equal(A.settings.tool,'balance');assert.equal(find('field-balance').textContent,'Balance: no partner field');
click(64,64);assertMessage('Balance needs another field in this session. Add Field…, or choose Paint.');
""", internal=True)

    def test_51_invalid_partner_keeps_balance_refuses_without_entry_or_id(self):
        editor(r"""
const [a,b]=await balancePair(20,180,3,75),{links,records}=controller.__balance,id=links.nextTransaction;
for(const invalidate of [()=>{records[0].balancePartner=records[0];},()=>{unavailable.add('2');},
 ()=>{records[0].balancePartner={key:'9',session:b};}]) {
 unavailable.clear();partnerWith('2');invalidate();const before=state();click(64,64);
 assertMessage('Choose a field to balance with: Advanced ▸ Brush Behavior ▸ Balance with…');
 assert.equal(a.settings.tool,'balance');assert.equal(field('1').balanceWith,null);assert.equal(links.nextTransaction,id);
 assert.equal(a.history.undoEntries.length,0);assert.equal(b.history.undoEntries.length,0);
 assert.ok(records.every(r=>r.balancePartner===null||records.includes(r.balancePartner)));
}
unavailable.clear();partnerWith('3');assertMessage('');click(64,64);assert.equal(links.nextTransaction,id+1);
""", internal=True)

    def test_52_e6_never_captures_tool_partner_or_share_and_apply_keeps_them(self):
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);const before=snapshot(b);
press('Brush Library…');await until(()=>find('library-status')&&!find('library-status').textContent.startsWith('Working'));
input('Preset name').value='Portable';input('Preset category').value='General';press('Save As New');
await until(()=>libraryText!==null&&find('library-status').textContent==='Brush saved.');
const preset=JSON.parse(libraryText).presets[0];assert.equal(preset.version,1);
assert.deepEqual(Object.keys(preset.brush),lib.SNAPSHOT_KEYS);assert.ok(!Object.hasOwn(preset.brush,'tool'));
assert.ok(!/balance|partner|share|transfer|transaction|node/i.test(libraryText));
a.settings.size=39;press('Update from Current Brush');await until(()=>JSON.parse(libraryText).presets[0].brush.size===39);
assert.ok(!/balance|partner|share|transfer|transaction|node/i.test(libraryText));
a.settings.size=16;press('Apply');await until(()=>a.settings.size===39);
assert.equal(a.settings.tool,'balance');assert.equal(field('1').balanceWith,'2');assert.equal(field('1').balanceShare,75);
assert.equal(snapshot(b),before);assert.equal(find('field-balance').textContent,'Balance: Painted Field #1 ↔ Painted Field #2 · 75:25');
""")

    def test_53_persistence_paint_no_partner_share_or_link_and_clean_reopen(self):
        adapter(r"""
controller.cancel();nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));await launch();await join('2');
press('Balance with Painted Field #2');type('Active Share (%)',75);click(64,64);
assert.equal(field('1').session.codes[64*128+64],150);await done();
assert.equal(nodes[0].properties.fieldEditor.tool,'paint');assert.equal(nodes[1].properties.fieldEditor.tool,'paint');
const properties=JSON.stringify(graphSnapshot().map(n=>n.properties));
assert.ok(!/balance|partner|share|transfer|source|transaction|Painted Field/i.test(properties));
assert.ok(!/balance|partner|transaction/i.test(JSON.stringify(graphSnapshot())));
assert.equal(settingsWrites.length,0);await launch();assert.equal(controller.session.settings.tool,'paint');
assert.deepEqual(controller.fields().map(f=>[f.balanceWith,f.balanceShare,f.transferFrom]),[[null,50,null]]);
assert.equal(controller.session.history.undoEntries.length,0);assert.equal(controller.fields().length,1);assert.equal(extension.settings.length,8);
await join('2');press('Balance with Painted Field #2');assert.equal(input('Active Share (%)').value,'50');
""")

    def test_54_share_100_equals_transfer_from_the_partner_bit_for_bit(self):
        run_node(IMPORTS + r"""
const A=Uint8Array.from({length:65536},(_,i)=>i&255),B=Uint8Array.from({length:65536},(_,i)=>i>>8);
const t=balanceTarget(A,B,100),reach=transferReach(B,A);for(let i=0;i<65536;i++)assert.equal(t[i],reach[i]);
""")
        result = editor(r"""
const path=[[20,32,16384],[35,47,32768],[70,64,49151],[103,97,65535]];
const tip={width:3,height:2,luminance:Uint8Array.of(255,96,170,41,230,153),alpha:Uint8Array.of(180,255,32,90,210,255)};
const run=async(kind,settings,a0,b0,{selection=null,pressure=false,useTip=false,at=null}={})=>{
 const [a,b]=await setup([0,0]);a.codes=a0.slice();b.codes=b0.slice();Object.assign(a.settings,settings);a.selection=selection;
 if(useTip){a.tip={...tip};a.settings.custom_tip=await tips.encodeTipDataUrl(tip);}
 if(kind==='transfer')transferFrom('2');else{partnerWith('2');share(100);}redraw();
 const extra=p=>pressure?{pointerType:'pen',pressure:p/65535}:{};
 if(at)click(...at);else{pointer('pointerdown',20,32,extra(path[0][2]));for(const [x,y,p] of path.slice(1))pointer('pointermove',x,y,extra(p));
  pointer('pointerup',103,97,extra(65535));}
 return {a:a.codes.slice(),b:b.codes.slice(),ae:a.history.undoEntries.at(-1),be:b.history.undoEntries.at(-1)};
};
const same=(x,y,label)=>{eq(x.a,y.a,label+' active');eq(x.b,y.b,label+' partner');
 if(x.ae){eq(x.ae.before,y.ae.before);eq(x.ae.after,y.ae.after);eq(x.be.before,y.be.before);eq(x.be.after,y.be.after);
  assert.equal(x.ae.link.kind,'transfer');assert.equal(y.ae.link.kind,'balance');}else assert.equal(y.ae,undefined);};
let cells=0;
for(let block=0;block<4;block++)for(const amount of [1,37,100]) {
 const a0=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256),b0=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 const s={shape:'square',size:128,hardness:100,amount};
 same(await run('transfer',s,a0,b0,{at:[64,64]}),await run('balance',s,a0,b0,{at:[64,64]}),`full ${block} ${amount}`);cells+=16384;
}
const a0=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256),b0=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
const cases=[[{size:30,hardness:35,amount:63}],[{size:32,hardness:40,amount:37,build_up:true,flow:30}],
 [{shape:'diamond',size:40,hardness:70,rotation_degrees:17,scale_x:1.4,amount:81}],
 [{shape:'custom',tip_channel:'alpha_luminance',size:36,hardness:37,amount:70},{useTip:true}],
 [{shape:'procedural',procedural_type:'scatter',procedural_seed:723,size:44,hardness:46,amount:53}],
 [{shape:'procedural',procedural_type:'noise',procedural_seed:911,size:52,hardness:66,amount:71}],
 [{shape:'procedural',procedural_particle_shape:'hotdog',hotdog_count:1024,size:64,hardness:70,amount:90}],
 [{size:28,hardness:48,amount:67,pressure_enabled:true,pressure_amount:true,pressure_size:true},{pressure:true}],
 [{size:24,hardness:55,amount:60,build_up:true,flow:40,pressure_enabled:true,pressure_flow:true},{pressure:true}],
 [{size:34,hardness:50,amount:57},{selection:Uint8Array.from({length:16384},(_,i)=>i%3===0?0:1)}]];
for(const [settings,options] of cases){same(await run('transfer',settings,a0,b0,options),await run('balance',settings,a0,b0,options),JSON.stringify(settings));cells+=16384;}
console.log(JSON.stringify({cells}));
""")
        self.assertEqual(result, {'cells': 16384 * 22})

    def test_55_share_0_equals_the_reverse_transfer_bit_for_bit(self):
        run_node(IMPORTS + r"""
const A=Uint8Array.from({length:65536},(_,i)=>i&255),B=Uint8Array.from({length:65536},(_,i)=>i>>8);
const t=balanceTarget(A,B,0),reach=transferReach(A,B);for(let i=0;i<65536;i++)assert.equal(A[i]+B[i]-t[i],reach[i]);
""")
        result = editor(r"""
// Balance from 1 at share 0 against Transfer into 2 from 1, with 1's brush and selection on 2.
const run=async(kind,settings,a0,b0,selection,at)=>{
 const [a,b]=await setup([0,0]);a.codes=a0.slice();b.codes=b0.slice();
 if(kind==='balance'){Object.assign(a.settings,settings);a.selection=selection;partnerWith('2');share(0);}
 else{activate('2');Object.assign(b.settings,settings);b.selection=selection;transferFrom('1');}
 redraw();if(at)click(...at);else{pointer('pointerdown',20,32);pointer('pointermove',35,47);pointer('pointermove',70,64);pointer('pointerup',103,97);}
 return [a.codes.slice(),b.codes.slice()];
};
let cells=0;
for(let block=0;block<4;block++)for(const amount of [1,37,100]) {
 const a0=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256),b0=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 const s={shape:'square',size:128,hardness:100,amount},x=await run('balance',s,a0,b0,null,[64,64]),y=await run('transfer',s,a0,b0,null,[64,64]);
 eq(x[0],y[0]);eq(x[1],y[1]);cells+=16384;
}
const a0=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256),b0=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
for(const [s,sel] of [[{size:30,hardness:35,amount:63},null],[{size:32,hardness:40,amount:37,build_up:true,flow:30},null],
 [{shape:'procedural',procedural_type:'scatter',procedural_seed:5,size:44,hardness:46,amount:53},Uint8Array.from({length:16384},(_,i)=>i%5?1:0)]]) {
 const x=await run('balance',s,a0,b0,sel),y=await run('transfer',s,a0,b0,sel);eq(x[0],y[0]);eq(x[1],y[1]);cells+=16384;
 assert.ok(x[0].some((v,i)=>v<a0[i]));
}
console.log(JSON.stringify({cells}));
""")
        self.assertEqual(result, {'cells': 16384 * 15})

    def test_56_transfer_unchanged_in_a_session_that_uses_balance(self):
        editor(r"""
const [a,b,c]=await setup([10,200,50]);partnerWith('2');share(75);click(40,40);assertBalance(a,b);
transferFrom('2');assert.equal(field('1').balanceWith,null);Object.assign(a.settings,{hardness:44,amount:63});redraw();
assert.equal(find('field-transfer').textContent,'Transfer: Painted Field #2 → Painted Field #1');assert.equal(find('field-balance').hidden,true);
assert.deepEqual(roles(),['','source','']);assert.ok(tabs()[1].title.endsWith(' · transfer source'));
assert.ok(heading('Brush Behavior').textContent.includes('Transfer'));assert.ok(!heading('Brush Behavior').textContent.includes('Balance'));
const d0=a.codes.slice(),s0=b.codes.slice(),reach=Uint8Array.from(d0,(v,i)=>Math.min(255,v+s0[i]));
const ref=new engine.Stroke(d0,128,128,{...a.settings,tool:'restore',apply_mode:'normal'},64,64,reach);click(64,64);eq(a.codes,ref.result());
for(let i=0;i<16384;i++){const m=a.codes[i]-d0[i];if(b.codes[i]!==s0[i]-m||m<0||m>Math.min(s0[i],255-d0[i]))assert.fail('transfer '+i);}
const de=a.history.undoEntries.at(-1),se=b.history.undoEntries.at(-1);
assert.deepEqual(de.link,{transaction:2,kind:'transfer',role:'destination',partner:'2'});
assert.deepEqual(se.link,{transaction:2,kind:'transfer',role:'source',partner:'1'});assert.equal(de.label,'Transfer');
press('Undo');eq(a.codes,d0);eq(b.codes,s0);press('Undo');assert.equal(a.codes[40*128+40],10);assert.equal(b.codes[40*128+40],200);
press('Redo');press('Redo');eq(a.codes,ref.result());
activate('2');b.settings.influence=0;press('Fill with Influence');activate('1');click(64,64);
assertMessage('Nothing to transfer under the brush: Painted Field #2 is 0 or Painted Field #1 is 255 there.');
""")

    def test_57_copy_from_unchanged_with_balance_active(self):
        editor(r"""
const [a,b]=await balancePair(10,200,3,75);a.selection=Uint8Array.from({length:16384},(_,i)=>i%2);
const before=snapshot(b),c=field('3').session,beforeC=snapshot(c),a0=a.codes.slice();press('Copy from Painted Field #3');
assert.equal(snapshot(b),before);assert.equal(snapshot(c),beforeC);for(let i=0;i<16384;i++)assert.equal(a.codes[i],i%2?50:10);
assert.equal(a.history.undoEntries.length,1);assert.ok(!a.history.undoEntries[0].link);
assert.equal(a.settings.tool,'balance');assert.equal(field('1').balanceWith,'2');press('Undo');eq(a.codes,a0);
""")

    def tool_case(self, tool):
        editor(r"""
const [a,b]=await balancePair(10,200,2,75);click(64,64);press(data);
assert.equal(field('1').balanceWith,null);assert.equal(a.settings.tool,data.toLowerCase());assert.equal(find('field-balance').hidden,true);
Object.assign(a.settings,{amount:63,hardness:44,influence:117});
const before=snapshot(b),a0=a.codes.slice(),ref=new engine.Stroke(a0,128,128,a.settings,70,60,a.initial,a.selection);
click(70,60);eq(a.codes,ref.result());assert.equal(snapshot(b),before);assert.ok(!a.history.undoEntries.at(-1).link);
press('Undo');eq(a.codes,a0);press('Undo');assert.equal(a.codes[center],10);assert.equal(b.codes[center],200);
""", tool)

    def test_58_paint_unchanged_in_a_session_with_balances(self):
        self.tool_case('Paint')

    def test_59_erase_unchanged_in_a_session_with_balances(self):
        self.tool_case('Erase')

    def test_60_restore_unchanged_in_a_session_with_balances(self):
        self.tool_case('Restore')

    def test_61_done_writes_both_participants_in_one_bracket_viewed_field_never(self):
        adapter(r"""
controller.cancel();nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));
await launch();await join('2');await join('3');activate('3');activate('1');
press('Balance with Painted Field #2');type('Active Share (%)',75);click(64,64);
const expectedA=field('1').session.codes.slice(),expectedB=field('2').session.codes.slice();
assert.equal(expectedA[64*128+64],150);assert.equal(expectedB[64*128+64],50);
tracker.reset();await done();
assert.deepEqual(events,['before','write 1','callback 1','write 2','callback 2','after']);assert.equal(tracker.undoStack.length,1);
assert.equal(tracker.changeCount,0);eq(await codec.decodeFieldDataUrl(nodes[0].widgets[0].value),expectedA);
eq(await codec.decodeFieldDataUrl(nodes[1].widgets[0].value),expectedB);assert.deepEqual(nodes[2].properties,{});
assert.equal(nodes[2].widgets[0].value,'');
""")

    def conflict(self, key):
        adapter(r"""
controller.cancel();nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));
await launch();await join('2');press('Balance with Painted Field #2');click(64,64);
nodes[Number(data)-1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(17));
const before=graphSnapshot();tracker.reset();await done();assert.deepEqual(graphSnapshot(),before);
assert.deepEqual(events,[]);assert.equal(tracker.undoStack.length,0);
assert.equal(error(),`Painted Field #${data}: the stored field changed while editing. Remove it from this session to keep the other changes, or Cancel and reopen.`);
""", key)

    def test_62_active_field_conflict_blocks_entire_done(self):
        self.conflict('1')

    def test_63_partner_conflict_blocks_entire_done(self):
        self.conflict('2')

    def test_64_graph_undo_restores_both_redo_reapplies_and_done_finishes_a_stroke(self):
        adapter(r"""
controller.cancel();nodes[1].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(200));
await launch();await join('2');press('Balance with Painted Field #2');click(64,64);
const before=graphSnapshot();tracker.reset();await done();const after=graphSnapshot();
assert.notDeepEqual(after,before);tracker.undo();assert.deepEqual(graphSnapshot(),before);tracker.redo();assert.deepEqual(graphSnapshot(),after);
// Done during a Balance stroke records the pair first, then writes both in one transaction.
nodes[2].widgets[0].value=await codec.encodeFieldDataUrl(new Uint8Array(16384).fill(90));
await launch(nodes[3]);await join('3');press('Balance with Painted Field #3');pointer('pointerdown',64,64);
const start=graphSnapshot();tracker.reset();await done();
assert.deepEqual(events,['before','write 4','callback 4','write 3','callback 3','after']);assert.equal(tracker.undoStack.length,1);
const four=await codec.decodeFieldDataUrl(nodes[3].widgets[0].value),three=await codec.decodeFieldDataUrl(nodes[2].widgets[0].value);
assert.equal(four[64*128+64],45);assert.equal(three[64*128+64],45);tracker.undo();assert.deepEqual(graphSnapshot(),start);
""")

    def test_65_dirty_state_no_op_moving_undo_cancel_and_erase_subtlety(self):
        editor(r"""
const [a,b]=await balancePair(60,61,2,50);const changed=()=>controller.fields().map(f=>f.changed);
assert.deepEqual(changed(),[false,false]);click(64,64);assert.deepEqual(changed(),[false,false]);assert.deepEqual(markState(),['','']);
share(75);partnerWith('2');assert.deepEqual(changed(),[false,false]);
click(64,64);assert.deepEqual(changed(),[true,true]);assert.deepEqual(markState(),['●','●']);
allowDiscard=false;press('Cancel');assert.deepEqual(confirms.at(-1),['discard',2]);
press('Undo');assert.deepEqual(changed(),[false,false]);press('Redo');assert.deepEqual(changed(),[true,true]);
allowDiscard=true;controller.cancel();joined.clear();joined.add('1');sources.get('1').codes=uniform(10);
sources.get('1').settings={...brushes.BRUSH_DEFAULTS,...brush,tool:'erase',amount:37,apply_mode:'lower_only'};
controller=open();dom.flush();await add('2');const s=field('1').session,canonical=ui.editorSettings({...s.settings});
assert.deepEqual(changed(),[false,false]);partnerWith('2');assert.deepEqual(changed(),[true,false]);
assert.deepEqual(ui.editorSettings(s.settings),{...canonical,tool:'paint'});
press('Done');await until(()=>offers.length);assert.deepEqual(offers.at(-1).map(f=>f.key),['1']);
assert.deepEqual(offers.at(-1)[0].settings,{...canonical,tool:'paint'});
""")

    def test_66_active_share_numeric_control_typing_drag_keys_and_memory(self):
        editor(r"""
const [a,b]=await balancePair(20,180);const control=()=>input('Active Share (%)');
for(const [typed,value] of [[0,0],[1,1],[50,50],[99,99],[100,100],['74.5',75],[150,100],[-3,0],[37,37]]) {
 share(typed);assert.equal(field('1').balanceShare,value);assert.equal(control().value,String(value));
}
for(const bad of ['abc','']){share(bad);assert.equal(field('1').balanceShare,37);assert.equal(control().value,'37');}
share(42,false);fire(window,'keydown',{key:'Escape',target:control()});dom.flush();assert.equal(field('1').balanceShare,37);
assert.equal(control().value,'37');assert.ok(find('cl-field-editor'),'Esc in the control does not close the editor');
share(42,false);fire(control(),'blur');dom.flush();assert.equal(field('1').balanceShare,42);
fire(window,'keydown',{key:'ArrowUp',target:control()});dom.flush();assert.equal(field('1').balanceShare,43);
fire(window,'keydown',{key:'ArrowDown',target:control()});dom.flush();assert.equal(field('1').balanceShare,42);
share(10,false);fire(window,'keydown',{key:'ArrowUp',target:control()});dom.flush();assert.equal(field('1').balanceShare,11);
const drag=(dx,extra={})=>{const e=control();fire(e,'pointerdown',{clientX:100});fire(e,'pointermove',{clientX:100+dx,...extra});
 fire(e,'pointerup',{clientX:100+dx});dom.flush();return field('1').balanceShare;};
assert.equal(drag(20),31);assert.equal(drag(20,{shiftKey:true}),33);assert.equal(drag(3,{ctrlKey:true}),63);
assert.equal(drag(-200),0);assert.equal(drag(300,{ctrlKey:true}),100);assert.equal(drag(-2),100);
assert.equal(a.history.undoEntries.length,0);assert.deepEqual(controller.fields().map(f=>f.changed),[false,false]);
press('Paint');assert.equal(find('balance-share').hidden,true);assert.equal(find('balance-help').hidden,true);
partnerWith('2');assert.equal(find('balance-share').hidden,false);
share(64,false);activate('2');assert.equal(field('1').balanceShare,64);assert.equal(control().value,'50');
assert.equal(find('balance-share').hidden,true);partnerWith('1');share(30);activate('1');
assert.equal(control().value,'64');assert.equal(field('2').balanceShare,30);
press('Reset Brush');assert.equal(field('1').balanceShare,50);assert.equal(control().value,'50');
assert.equal(a.settings.tool,'paint');assert.equal(field('1').balanceWith,null);assert.equal(field('2').balanceShare,30);
partnerWith('2');share(75);click(64,64);assert.equal(a.codes[center],150);assert.equal(b.codes[center],50);
""")

    def test_67_single_field_legacy_host_is_unchanged(self):
        from test_field_editor_custom_tip import run_editor
        run_editor(r"""
assert.ok(!all().some(e=>/(balance-|field-balance|transfer-|field-transfer|field-role)/.test(e.className||'')));
assert.ok(!all().some(e=>e.tagName==='BUTTON'&&/^(Balance with|Transfer from) /.test(e.textContent||'')));
assert.equal(all().filter(e=>e.tagName==='INPUT'&&e.type==='text').length,41);
assert.deepEqual(controller.fields().map(f=>[f.balanceWith,f.balanceShare,f.transferFrom]),[[null,50,null]]);
for(const tool of ['Paint','Erase','Restore']) {
 press(tool);Object.assign(settings(),{amount:63,hardness:44,influence:117});
 const s=session(),before=s.codes.slice(),ref=new engine.Stroke(before,128,128,s.settings,64,64,s.initial);
 click(64,64);assert.ok(s.codes.every((v,i)=>v===ref.result()[i]));
 assert.ok(!heading('Brush Behavior').textContent.includes('Balance'));
}
press('Undo');press('Redo');press('Done');
assert.equal(result.settings.tool,'paint');assert.ok(!/balance|partner|share|transfer/i.test(JSON.stringify(result.settings)));
""")

    def test_68_structural_performance_target_once_one_result_and_complement_per_frame(self):
        result = instrumented(r"""
const [a,b]=await balancePair(20,180,2,75);let results=0;
const original=engine.Stroke.prototype.result;engine.Stroke.prototype.result=function(){results++;return original.call(this);};
const counts=()=>[globalThis.balanceCalls.target,globalThis.balanceCalls.partner,results];
const reset=()=>{globalThis.balanceCalls.target=globalThis.balanceCalls.partner=0;results=0;};
reset();redraw();redraw();activate('2');activate('1');partnerWith('2');share(40);share(75);assert.deepEqual(counts(),[0,0,0]);
let frames=0;pointer('pointerdown',30,30);frames++;for(let x=31;x<60;x++){pointer('pointermove',x,30);frames++;}
pointer('pointerup',60,30);assert.deepEqual(counts(),[1,frames+1,frames+1]);
reset();redraw();redraw();assert.deepEqual(counts(),[0,0,0]);
console.log(JSON.stringify({frames}));
""")
        self.assertEqual(result, {'frames': 30})

    def test_69_memory_cap_both_kinds_200_rows_and_cleanup(self):
        result = pure(r"""
for(const r of members){r.session.codes=new Uint8Array(16384).fill(r.session.codes[0]);r.session.initial=r.session.codes.slice();}
for(let i=0;i<100;i++) {
 const [receiver,donor]=i%2?[b,a]:[a,b];
 assert.equal(move(receiver,donor,50),true);assert.equal(bal(c,d,i%2?25:75),true);
}
let bytes=0,kinds={transfer:0,balance:0};for(const row of links.transactions.values())kinds[row.kind]++;
assert.equal(links.transactions.size,200);assert.deepEqual(kinds,{transfer:100,balance:100});
for(const r of members){assert.equal(r.session.history.undoEntries.length,100);
 for(const e of r.session.history.undoEntries)bytes+=e.before.byteLength+e.after.byteLength;
 assert.deepEqual(Object.keys(r.session.history.undoEntries[0]),['label','before','after','link']);}
assert.deepEqual(Object.keys(c.session.history.undoEntries[0].link),['transaction','kind','role','partner']);
assert.deepEqual(Object.keys([...links.transactions.values()].at(-1)),['kind','active','partner']);
for(let i=0;i<150;i++)for(const r of members)r.session.replace('pressure',r.session.codes.map(v=>255-v));
assert.equal(links.transactions.size,0);assert.ok(members.every(r=>r.session.history.undoEntries.length===100));
console.log(JSON.stringify({snapshotBytes:bytes,maxRows:200}));
""")
        self.assertEqual(result, {'snapshotBytes': 13107200, 'maxRows': 200})

    def test_70_ex1_exhaustive_target_6619136_against_python_scan(self):
        result = run_node(IMPORTS + r"""
const A=Uint8Array.from({length:65536},(_,i)=>i&255),B=Uint8Array.from({length:65536},(_,i)=>i>>8);
const T=Uint16Array.from(A,(v,i)=>v+B[i]),forward=[],backward=[];
for(let p=0;p<=100;p++){forward.push(balanceTarget(A,B,p));backward.push(balanceTarget(B,A,p));}
let checked=0,halves=0,pointOutside=0,clampChanged=0,halfUp=0;const halfUpByShare={};
for(let p=0;p<=100;p++){
 const f=forward[p],mirror=backward[100-p],again=balanceTarget(f,Uint8Array.from(f,(v,i)=>T[i]-v),p);
 for(let i=0;i<65536;i++){
  const a=A[i],t=T[i],x=f[i],options=data[t][p],low=Math.max(0,t-255),high=Math.min(255,t);
  const expected=options.length===1||Math.abs(options[0]-a)<Math.abs(options[1]-a)?options[0]:options[1];
  if(x!==expected)assert.fail(`target ${a},${B[i]},${p}: ${x} != ${expected}`);
  if(x<low||x>high||t-x<0||t-x>255)assert.fail(`feasibility ${a},${B[i]},${p}`);
  if(x+mirror[i]!==t)assert.fail(`orientation ${a},${B[i]},${p}`);
  if(again[i]!==x)assert.fail(`idempotence ${a},${B[i]},${p}`);
  if(p&&x<forward[p-1][i])assert.fail(`monotone ${a},${B[i]},${p}`);
  if(p===100&&x!==Math.min(255,t))assert.fail('share 100');
  if(p===0&&x!==Math.max(0,t-255))assert.fail('share 0');
  const n=t*p,floor=Math.floor(n/100),half=n-100*floor===50;
  // The unclamped nearest integer, an exact half toward the current value; and the half-up candidate rule.
  const rounded=n-100*floor>50||(half&&a>floor)?floor+1:floor;
  halves+=half;pointOutside+=n<100*low||n>100*high;clampChanged+=rounded<low||rounded>high;
  const up=s=>Math.min(high,Math.max(low,Math.floor((t*s+50)/100)));
  if(up(p)+up(100-p)!==t){halfUp++;halfUpByShare[p]=(halfUpByShare[p]??0)+1;}
  checked++;
 }
}
console.log(JSON.stringify({checked,halves,pointOutside,clampChanged,halfUp,halfUpByShare}));
""", nearest_table())
        self.assertEqual(result['checked'], 6619136)
        self.assertEqual(result['halves'], 171168)
        self.assertEqual(result['clampChanged'], 1516956)
        self.assertEqual(result['pointOutside'], 1525858)
        self.assertEqual(result['halfUp'], 138238)
        for share, count in {50: 32768, 25: 12729, 75: 12729, 30: 5416, 70: 5416, 10: 3888, 90: 3888}.items():
            self.assertEqual(result['halfUpByShare'][str(share)], count)
        for share in range(101):
            for total in range(511):
                options = nearest(total, share)
                self.assertTrue(1 <= len(options) <= 2 and options[-1] - options[0] <= 1)

    def test_71_ex2_movement_closed_form_51611_against_binary64(self):
        expected = [[moved(distance, amount) for distance in range(-255, 256)] for amount in range(101)]
        result = run_node(IMPORTS + r"""
let n=0;for(let k=0;k<=100;k++)for(let d=-255;d<=255;d++){
 const delta=((d*k)*1)/100,actual=Math.sign(delta)*engine.roundHalf(Math.abs(delta));
 if(actual!==data[k][d+255])assert.fail(`${d} ${k}: ${actual} != ${data[k][d+255]}`);n++;}
console.log(JSON.stringify({n}));
""", expected)
        self.assertEqual(result, {'n': 51611})

    def engine_sweep(self, amounts, shares):
        data = {'table': nearest_table(), 'moves': [[(d * k + 50) // 100 for d in range(256)] for k in range(101)],
                'amounts': amounts, 'shares': shares}
        return run_node(IMPORTS + r"""
const modes=['normal','raise_only','lower_only'];let cells=0,strokes=0,movedCells=0;
for(const k of data.amounts)for(const p of data.shares)for(let block=0;block<4;block++) {
 const a0=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256),b0=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 const target=balanceTarget(a0,b0,p);
 const stroke=new engine.Stroke(a0,128,128,transferEngineBrush({...brush,shape:'square',size:128,amount:k,apply_mode:modes[strokes%3]}),64,64,target);
 const a1=stroke.result(),b1=balancePartner(b0,a0,a1,target);
 for(let i=0;i<16384;i++){
  const t=a0[i]+b0[i],o=data.table[t][p],goal=o.length===1||Math.abs(o[0]-a0[i])<Math.abs(o[1]-a0[i])?o[0]:o[1];
  const d=goal-a0[i],m=Math.sign(d)*data.moves[k][Math.abs(d)];
  if(stroke.coverage[i]!==1||a1[i]!==a0[i]+m||b1[i]!==b0[i]-m||a1[i]+b1[i]!==t)
   assert.fail(`cell ${a0[i]},${b0[i]} share ${p} amount ${k}: ${a1[i]},${b1[i]}`);
  cells++;movedCells+=m!==0;
 }
 strokes++;
}
console.log(JSON.stringify({cells,strokes,movedCells}));
""", data)

    def test_72_ex3_engine_every_pair_every_share_at_five_amounts(self):
        result = self.engine_sweep([1, 15, 50, 99, 100], list(range(101)))
        self.assertEqual((result['cells'], result['strokes']), (33095680, 2020))
        self.assertGreater(result['movedCells'], 20000000)

    def test_73_ex4_engine_every_pair_every_amount_at_five_shares(self):
        result = self.engine_sweep(list(range(1, 101)), [0, 33, 50, 75, 100])
        self.assertEqual((result['cells'], result['strokes']), (32768000, 2000))

    def test_74_orientation_balance_from_either_field_is_identical(self):
        result = editor(r"""
const path=[[20,32,16384],[35,47,32768],[70,64,49151],[103,97,65535]];
const tip={width:3,height:2,luminance:Uint8Array.of(255,96,170,41,230,153),alpha:Uint8Array.of(180,255,32,90,210,255)};
const run=async(from,p,settings,{selection=null,pressure=false,useTip=false}={})=>{
 const [a,b]=await setup([0,0]);a.codes=Uint8Array.from({length:16384},(_,i)=>(i*37+29)%256);
 b.codes=Uint8Array.from({length:16384},(_,i)=>(i*53+7)%256);
 const own=from==='1'?a:b;Object.assign(own.settings,settings);own.selection=selection;
 if(useTip){own.tip={...tip};own.settings.custom_tip=await tips.encodeTipDataUrl(tip);}
 if(from==='2')activate('2');partnerWith(from==='1'?'2':'1');share(from==='1'?p:100-p);redraw();
 const extra=q=>pressure?{pointerType:'pen',pressure:q/65535}:{};
 pointer('pointerdown',20,32,extra(path[0][2]));for(const [x,y,q] of path.slice(1))pointer('pointermove',x,y,extra(q));
 pointer('pointerup',103,97,extra(65535));
 return [a.codes.slice(),b.codes.slice(),a.history.undoEntries.length];
};
const gate=Uint8Array.from({length:16384},(_,i)=>i%7===0?0:1);let strokes=0;
for(const p of [0,13,37,50,75,100])for(const [settings,options] of [[{size:30,hardness:35,amount:63}],
 [{size:32,hardness:40,amount:37,build_up:true,flow:30,falloff_curve:'sharper'},{selection:gate}],
 [{shape:'procedural',procedural_type:'scatter',procedural_seed:723,size:44,hardness:46,amount:53}],
 [{shape:'custom',tip_channel:'alpha_luminance',size:36,hardness:37,amount:70},{useTip:true}],
 [{size:28,hardness:48,amount:67,pressure_enabled:true,pressure_amount:true,pressure_size:true},{pressure:true,selection:gate}]]) {
 const x=await run('1',p,settings,options),y=await run('2',p,settings,options);
 eq(x[0],y[0],`active ${p}`);eq(x[1],y[1],`partner ${p}`);assert.equal(x[2],y[2]);strokes+=2;
}
console.log(JSON.stringify({strokes}));
""")
        self.assertEqual(result, {'strokes': 60})

    def test_75_final_buffers_installed_on_a_pressure_noop_without_entry_or_id(self):
        editor(r"""
for(const [a0,b0,p] of [[0,50,100],[50,0,0]]) {
 const [a,b]=await balancePair(a0,b0,2,p),i=center;
 Object.assign(a.settings,{amount:49,hardness:0,build_up:true,flow:100,spacing:'custom',spacing_percent:50,
  pressure_enabled:true,pressure_size:false,pressure_amount:true});
 a.selection=empty();a.selection[i]=1;redraw();
 const da=a.codes.slice(),db=b.codes.slice(),before=state(),links=controller.__balance.links,id=links.nextTransaction;
 pointer('pointerdown',64.5,64.5,{pointerType:'pen',pressure:1/49});
 const stroke=controller.__balance.stroke;assert.ok(stroke instanceof engine.PressureStroke);
 assert.equal(stroke.amounts[i],1);assert.equal(stroke.coverage[i],1);
 assert.equal(a.codes[i],a0+(p?1:-1));assert.equal(b.codes[i],b0-(p?1:-1));
 pointer('pointermove',64.5,64.5,{pointerType:'pen',pressure:1});pointer('pointerup',65.5,73.5,{pointerType:'pen',pressure:1});
 assert.equal(Math.abs(((((p?50:-50)*stroke.amounts[i])*stroke.coverage[i])/100)),0.49999999999999994);
 eq(a.codes,da,'final active');eq(b.codes,db,'final partner');assert.equal(state(),before);
 assert.equal(links.transactions.size,0);assert.equal(links.nextTransaction,id);assert.equal(controller.__balance.stroke,null);
 assert.equal(controller.__balance.binding,null);assertMessage('');
}
""", internal=True)

    def test_76_tripwire_refuses_and_editor_rolls_back_both(self):
        run_node(IMPORTS + r"""
const bad=/^Error: Balance out of range\.$/;
for(const [b,a,next,t] of [[5,20,21,10],[5,20,9,10],[5,20,31,30],[5,20,19,30],[3,250,255,255],[5,20,20.5,30],[5,20,-1,0]])
 assert.throws(()=>balancePartner(Uint8Array.of(b),Uint8Array.of(a),[next],[t]),bad);
assert.throws(()=>balancePartner(Uint8Array.of(1,2),Uint8Array.of(1),Uint8Array.of(1),Uint8Array.of(1)),bad);
assert.throws(()=>balancePartner(Uint8Array.of(1),Uint8Array.of(1),Uint8Array.of(1),Uint8Array.of(1,2)),bad);
assert.deepEqual([...balancePartner(Uint8Array.of(5),Uint8Array.of(20),Uint8Array.of(10),Uint8Array.of(10))],[15]);
assert.deepEqual([...balancePartner(Uint8Array.of(5),Uint8Array.of(20),Uint8Array.of(25),Uint8Array.of(30))],[0]);
for(const share of [-1,101,50.5,'50',NaN,null])assert.throws(()=>balanceTarget(Uint8Array.of(1),Uint8Array.of(1),share),bad);
assert.throws(()=>balanceTarget(Uint8Array.of(1,2),Uint8Array.of(1),50),bad);
""")
        editor(r"""
for(const failAt of [1,2]) {
 const [a,b]=await balancePair(20,180,2,75),before=state(),result=engine.Stroke.prototype.result;let calls=0;
 // Overshoot one cell on the first rendered frame, then on the final result only.
 engine.Stroke.prototype.result=function(){const next=result.call(this);if(++calls===failAt)next[center]=151;return next;};
 click(64,64);engine.Stroke.prototype.result=result;assert.equal(state(),before);
 assertMessage('Balance stopped: an internal check failed. Nothing was changed.');
 assert.equal(controller.__balance.stroke,null);assert.equal(controller.__balance.binding,null);
 assert.equal(controller.__balance.links.nextTransaction,1);
}
""", internal=True)

    def test_77_kind_of_reads_row_then_link_then_defaults_to_transfer(self):
        pure(r"""
assert.equal(links.kindOf('undo',a),null);move(a,b);assert.equal(links.kindOf('undo',a),'transfer');
assert.equal(links.kindOf('undo',b),'transfer');bal(a,b,25);assert.equal(links.kindOf('undo',a),'balance');
assert.equal(links.kindOf('undo',b),'balance');edit(c,5);assert.equal(links.kindOf('undo',c),'transfer');
const top=a.session.history.undoEntries.at(-1),link=top.link;delete top.link;assert.equal(links.kindOf('undo',a),'balance');
top.link={...link,kind:'transfer'};assert.equal(links.kindOf('undo',a),'balance');top.link=link;
const stack=c.session.history.undoEntries,entry={label:'x',before:Uint8Array.of(1),after:Uint8Array.of(5)};
for(const [stale,kind] of [[{transaction:99,kind:'balance',role:'active',partner:'B'},'balance'],
 [{transaction:99,kind:'transfer',role:'source',partner:'B'},'transfer'],[null,'transfer'],[{},'transfer']]) {
 stack.push({...entry,link:stale});assert.equal(links.kindOf('undo',c),kind);stack.pop();
}
links.step('undo',a);assert.equal(links.kindOf('redo',a),'balance');assert.equal(links.kindOf('undo',a),'transfer');
assert.equal(links.kindOf('redo',d),null);invariants();
""")

    def test_78_broken_balance_links_refused_exactly_with_kind_wording(self):
        pure(r"""
bal(a,b,75);const ae=a.session.history.undoEntries[0],pe=b.session.history.undoEntries[0],al=ae.link,pl=pe.link;
for(const kind of ['undo','redo']) {
 if(kind==='redo')assert.equal(links.step('undo',a).state,'linked');
 for(const [entry,bad] of [[ae,null],[ae,{}],[ae,{...al,transaction:999}],[ae,{...al,kind:'other'}],[ae,{...al,kind:'transfer'}],
  [ae,{...al,role:'partner'}],[ae,{...al,role:'destination'}],[ae,{...al,partner:'A'}],[pe,null],[pe,{...pl,transaction:999}],
  [pe,{...pl,role:'active'}],[pe,{...pl,kind:'transfer',role:'source'}]]) {
  entry.link=bad;const before=saved();const r=links.step(kind,a);assert.equal(r.state,'broken');
  assert.deepEqual(Object.keys(r),['state','reason']);unchanged(before);ae.link=al;pe.link=pl;
 }
 delete ae.link;let before=saved();assert.deepEqual(links.step(kind,a),{state:'broken',reason:'transaction mismatch'});unchanged(before);ae.link=al;
 delete pe.link;before=saved();assert.deepEqual(links.step(kind,a),{state:'broken',reason:'transaction mismatch'});unchanged(before);pe.link=pl;
 const entries=b.session.history[kind+'Entries'];entries.pop();before=saved();
 assert.deepEqual(links.step(kind,a),{state:'broken',reason:'missing partner entry'});unchanged(before);entries.push(pe);
 members=members.filter(r=>r!==b);before=saved();assert.deepEqual(links.step(kind,a),{state:'broken',reason:'missing partner'});unchanged(before);members.push(b);
 a.session.codes=Uint8Array.of(255);before=saved();assert.deepEqual(links.step(kind,a),{state:'broken',reason:'buffer mismatch'});unchanged(before);
 a.session.codes=ae[kind==='undo'?'after':'before'].slice();
}
assert.deepEqual(links.step('redo',a),{state:'linked',partner:b});invariants();
""")
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);click(64,64);b.history.undoEntries.pop();const before=state(),marks=markState();press('Undo');
assert.equal(state(),before);assert.deepEqual(markState(),marks);
assertMessage('Undo refused: a Balance history link is inconsistent (missing partner entry). Nothing was changed.');
assert.equal(buttons('Undo')[0].disabled,false);
""")

    def test_79_balance_recording_faults_restore_everything_and_prepare_takes_no_id(self):
        pure(r"""
for(const stage of ['active-history','partner-history','partner-link','table','active-buffer','partner-buffer']) {
 const before=saved();let reset;
 if(stage.endsWith('-history')) {
  const h=(stage.startsWith('active')?a:b).session.history,original=h.record;
  h.record=function(...args){original.apply(this,args);throw Error('injected');};reset=()=>h.record=original;
 } else if(stage==='partner-link') {
  const original=Object.freeze;let calls=0;Object.freeze=v=>{if(++calls===2)throw Error('injected');return original(v);};reset=()=>Object.freeze=original;
 } else if(stage==='table') {
  const table=links.transactions;table.set=()=>{throw Error('injected');};reset=()=>delete table.set;
 } else {
  const session=(stage.startsWith('active')?a:b).session;let codes=session.codes,once=true;
  Object.defineProperty(session,'codes',{configurable:true,get:()=>codes,set:value=>{codes=value;if(once){once=false;throw Error('injected');}}});
  reset=()=>Object.defineProperty(session,'codes',{configurable:true,writable:true,enumerable:true,value:codes});
 }
 assert.throws(()=>bal(a,b,75),/injected/);reset();unchanged(before,false);assert.equal(links.nextTransaction,before.next+1);
 assert.equal(bal(a,b,75),true);assert.equal(a.session.history.undoEntries.at(-1).link.transaction,before.next+1);
 invariants();links.step('undo',a);
}
// Prepare refusals allocate nothing and change nothing.
const id=links.nextTransaction,ab=a.session.codes,pb=b.session.codes,t=goals(ab,pb,75),aa=ab.map((v,i)=>v+shift(t[i]-v,100));
for(const attempt of [()=>links.recordBalance(a,b,ab,aa,pb,pb,t),()=>links.recordBalance(a,a,ab,aa,pb,pb.map((v,i)=>v-(aa[i]-ab[i])),t),
 ()=>links.recordBalance(a,{key:'X',session:b.session},ab,aa,pb,pb.map((v,i)=>v-(aa[i]-ab[i])),t),
 ()=>links.recordBalance(a,b,ab,Uint8Array.of(t[0]+(t[0]>ab[0]?1:-1)),pb,Uint8Array.of(pb[0]-(t[0]+(t[0]>ab[0]?1:-1)-ab[0])),t)]) {
 const before=saved();assert.throws(attempt,/^Error: Balance out of range\.$/);unchanged(before);
}
const original=links.members;links.members=()=>{throw Error('injected prepare');};
let before=saved();assert.throws(()=>bal(a,b,75),/^Error: injected prepare$/);links.members=original;unchanged(before);
before=saved();assert.equal(links.recordBalance(a,b,ab,ab,pb,pb,t),false);unchanged(before);
assert.equal(links.nextTransaction,id);assert.equal(bal(a,b,75),true);assert.equal(a.session.history.undoEntries.at(-1).link.transaction,id);
invariants();
""")

    def test_80_paired_balance_undo_redo_faults_restore_exactly(self):
        pure(r"""
bal(a,b,75);
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
  assert.deepEqual(links.step(kind,b),{state:'failed'});reset();unchanged(before);invariants();
 }
 assert.equal(links.step(kind,b).state,'linked');invariants();
}
""")

    def test_81_cap_and_redo_cascade_faults_during_balance_recording(self):
        pure(r"""
bal(c,b,25,30);bal(a,b,25,30);edit(c,18);for(let i=0;i<99;i++)edit(a,i%2?5:6);
let before=saved(),entries=c.session.history.undoEntries,original=entries.splice;
entries.splice=function(...args){original.apply(this,args);throw Error('cascade fault');};
assert.throws(()=>bal(a,d,25),/cascade fault/);delete entries.splice;unchanged(before,false);invariants();
assert.equal(bal(a,d,25),true);assert.equal(b.session.history.undoEntries.length,0);
assert.deepEqual(c.session.history.undoEntries.map(e=>e.label),['Edit']);invariants();
""")
        pure(r"""
bal(c,b,25,30);bal(a,b,25,30);edit(c,18);links.step('undo',c);links.step('undo',a);links.step('undo',c);
const before=saved(),entries=a.session.history.redoEntries,original=entries.splice;
entries.splice=function(...args){original.apply(this,args);throw Error('redo cascade');};
assert.throws(()=>bal(c,d,25,30),/redo cascade/);delete entries.splice;unchanged(before,false);invariants();
assert.equal(bal(c,d,25,30),true);assert.equal(a.session.history.redoEntries.length,0);assert.equal(b.session.history.redoEntries.length,0);invariants();
""")

    def test_82_ui_failed_balance_record_and_paired_steps_show_exact_messages(self):
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);const original=b.history.record,before=state();
b.history.record=function(...args){original.apply(this,args);throw Error('injected');};click(64,64);b.history.record=original;
assert.equal(state(),before);assertMessage('Balance stopped: an internal check failed. Nothing was changed.');
click(64,64);assertMessage('');
for(const kind of ['Undo','Redo']) {
 const entries=b.history[kind==='Undo'?'redoEntries':'undoEntries'],original=entries.push,before=state();
 entries.push=function(...args){original.apply(this,args);throw Error('injected');};press(kind);delete entries.push;
 assert.equal(state(),before);assertMessage(`${kind} stopped: an internal check failed. Nothing was changed.`);press(kind);assertMessage('');
}
""")

    def test_83_abort_paths_restore_both_and_record_nothing(self):
        editor(r"""
for(const abort of [()=>pointer('pointercancel',64,64),()=>key('Escape'),()=>fire(window,'blur'),
 ()=>fire(find('viewport'),'lostpointercapture'),()=>press('Cancel')]) {
 const [a,b]=await balancePair(20,180,2,75);const before=state();pointer('pointerdown',64,64);pointer('pointermove',90,90);
 assert.notEqual(a.codes[center],20);abort();dom.flush();assert.equal(state(),before);
 assert.equal(a.history.undoEntries.length+b.history.undoEntries.length,0);
 assert.equal(controller.__balance.binding,null);assert.equal(controller.__balance.links.nextTransaction,1);
}
""", internal=True)

    def test_84_mid_stroke_share_partner_tool_and_availability_cannot_redirect(self):
        editor(r"""
const [a,b]=await balancePair(20,180,3,75),c=field('3').session,beforeC=snapshot(c),{records}=controller.__balance;
pointer('pointerdown',64,64);const binding=controller.__balance.binding;
assert.equal(binding.partner,records[1]);assert.equal(binding.share,75);
// Every current setting now differs from the binding: share 10, tool Paint, partner pointer field 3.
share(10);activate('3');partnerWith('3');press('Paint');records[0].balancePartner=records[2];
pointer('pointermove',66,64);assert.equal(controller.__balance.binding,binding);pointer('pointerup',66,64);
assertBalance(a,b);assert.equal(a.codes[center],150);assert.equal(b.codes[center],50);assert.equal(snapshot(c),beforeC);
assert.equal(controller.session,a);assert.equal(a.settings.tool,'paint');assert.equal(field('1').balanceShare,10);
// The partner leaves the graph mid-stroke: the bound pair still records, then render clears the memory.
partnerWith('2');share(75);pointer('pointerdown',30,30);unavailable.add('2');pointer('pointermove',32,30);pointer('pointerup',32,30);
assert.equal(a.history.undoEntries.length,2);assertBalance(a,b);dom.flush();assert.equal(field('1').balanceWith,null);
assert.equal(a.settings.tool,'balance');
// The settled message names the share bound at stroke start, not one typed during the stroke.
await balancePair(60,61,2,50);pointer('pointerdown',64,64);share(75);pointer('pointerup',64,64);
assertMessage('Nothing to balance under the brush: Painted Field #1 and Painted Field #2 are already at 50:50 there, as closely as whole 0–255 codes allow.');
assert.equal(field('1').balanceShare,75);
""", internal=True)

    def test_85_randomized_ui_history_both_kinds_against_independent_model(self):
        model = MixedModel()
        rng = random.Random(0xE10C35)
        trace = []

        def emit(op):
            model.apply(op)
            trace.append([op, model.digest()])

        # Guaranteed pressure: both kinds interleaved, cap crossings and mixed Redo, then a fixed-seed walk.
        for _ in range(2):
            for key, value in [('1', 10), ('2', 200), ('3', 50), ('4', 80)]:
                emit(['activate', key])
                emit(['edit', value])
            emit(['activate', '3'])
            emit(['balance', '2', 50, 100, False])
            emit(['activate', '1'])
            emit(['transfer', '2', 25, False])
            emit(['balance', '3', 75, 60, False])
            emit(['activate', '4'])
            emit(['balance', '1', 30, 100, False])
            for i in range(105):
                emit(['edit', 5 + i % 2])
        for _ in range(2600):
            members = list(model.fields)
            available = [k for k in members if k not in model.unavailable]
            others = [k for k in available if k != model.active]
            action = rng.randrange(100)
            if action < 22:
                emit(['edit', rng.randrange(256)])
            elif action < 36 and model.active in available and others:
                emit(['transfer', rng.choice(others), rng.randrange(1, 101), rng.randrange(20) == 0])
            elif action < 52 and model.active in available and others:
                emit(['balance', rng.choice(others), rng.randrange(101), rng.randrange(1, 101), rng.randrange(20) == 0])
            elif action < 64:
                emit(['undo', rng.randrange(20) == 0])
            elif action < 72:
                emit(['redo', rng.randrange(20) == 0])
            elif action < 80:
                emit(['activate', rng.choice(members)])
            elif action < 83 and len(members) > 1:
                emit(['remove', rng.choice(members)])
            elif action < 86 and len(members) < 4:
                key = rng.choice([k for k in ('1', '2', '3', '4') if k not in members])
                emit(['available', key, True])
                emit(['join', key])
            elif action < 90:
                key = rng.choice(members)
                emit(['available', key, key in model.unavailable])
            elif action < 93:
                emit(['source', rng.choice(members)])
            elif action < 96:
                emit(['partner', rng.choice(members)])
            elif action < 97:
                emit(['share', rng.randrange(101)])
            elif action < 99:
                emit(['tool', rng.choice(['paint', 'erase', 'restore'])])
            else:
                emit(['reset'])
        # Every field available and joined, deep removal-free mixed histories, then undo in random
        # field order until every Undo is empty: no deadlock.
        for key in sorted(model.unavailable):
            emit(['available', key, True])
        for key in ('1', '2', '3', '4'):
            if key not in model.fields:
                emit(['join', key])
        for _ in range(400):
            keys = list(model.fields)
            emit(['activate', rng.choice(keys)])
            others = [k for k in keys if k != model.active]
            action = rng.randrange(10)
            if action < 3:
                emit(['edit', rng.randrange(256)])
            elif action < 6:
                emit(['transfer', rng.choice(others), rng.randrange(1, 101), False])
            else:
                emit(['balance', rng.choice(others), rng.randrange(101), rng.randrange(1, 101), False])
        # One step per ordinary Undo entry, one per linked transaction: nothing one-sided, no deadlock.
        ordinary = sum(model.entries[e]['transaction'] is None for f in model.fields.values() for e in f['undo'])
        linked = sum(all(e in model.fields[k]['undo'] for k, e in sides) for _, sides in model.transactions.values())
        before = model.counts['paired_steps']
        unwound = 0
        while any(field['undo'] for field in model.fields.values()):
            ready = [k for k, field in model.fields.items() if field['undo'] and model.undoable(k)]
            self.assertTrue(ready, 'deadlock')
            emit(['activate', rng.choice(ready)])
            emit(['undo', False])
            unwound += 1
        result = editor(r"""
const {createHash}=await import('node:crypto');
await setup([10,200,50,80]);press('Paint');
const fullBrush=()=>{for(const f of controller.fields())Object.assign(f.session.settings,{shape:'square',size:128,hardness:100,amount:100});};
fullBrush();const current=()=>controller.__balance,isAvailable=r=>!unavailable.has(r.key);
const OTHER={destination:'source',source:'destination',active:'partner',partner:'active'};
const digest=()=>{
 const {records,links}=current();
 const rows=records.map(r=>[r.key,r.session.codes[0],...['undo','redo'].map(kind=>r.session.history[kind+'Entries'].map(e=>
  [e.before[0],e.after[0],e.link?.transaction??null,e.link?.kind??null,e.link?.role??null,e.link?.partner??null])),
  r.transferSource?.key??null,r.balancePartner?.key??null,r.balanceShare,r.session.settings.tool,isAvailable(r)]);
 const table=[...links.transactions.entries()].map(([id,row])=>[id,row.kind]).sort((x,y)=>x[0]-y[0]);
 return createHash('sha256').update(JSON.stringify([controller.fields().find(f=>f.active).key,links.nextTransaction,rows,table])).digest('hex');
};
let faults=0,paired=0;
for(let index=0;index<data.length;index++) {
 const [op,expected]=data[index],[action,...args]=op;let reset=()=>{};
 if(action==='activate'){if(controller.fields().length>1)activate(args[0]);else redraw();}
 else if(action==='available'){args[1]?unavailable.delete(args[0]):unavailable.add(args[0]);redraw();}
 else if(action==='join'){await add(args[0]);fullBrush();}
 else if(action==='remove')remove(args[0]);
 else if(action==='source'){if(buttons(`Transfer from Painted Field #${args[0]}`).length)transferFrom(args[0]);else redraw();}
 else if(action==='partner'){if(buttons(`Balance with Painted Field #${args[0]}`).length)partnerWith(args[0]);else redraw();}
 else if(action==='share'){if(input('Active Share (%)'))share(args[0]);else redraw();}
 else if(action==='tool')press(args[0][0].toUpperCase()+args[0].slice(1));
 else if(action==='reset'){press('Reset Brush');fullBrush();}
 else if(action==='edit'){controller.session.replace('Edit',uniform(args[0]));redraw();}
 else if(action==='transfer'||action==='balance') {
  const moving=action==='transfer';if(moving)transferFrom(args[0]);else{partnerWith(args[0]);share(args[1]);}
  fullBrush();controller.session.settings.amount=moving?args[1]:args[2];
  if(moving?args[2]:args[3]){const h=field(args[0]).session.history,original=h.record;
   h.record=function(...p){original.apply(this,p);throw Error('record fault');};reset=()=>h.record=original;faults++;}
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
  assert.ok(r.transferSource!==r&&r.balancePartner!==r,'never self');assert.ok(!(r.transferSource&&r.balancePartner),'one pointer');
  for(const p of [r.transferSource,r.balancePartner])assert.ok(!p||records.includes(p),'no removed pointer');
  const s=r.session,h=s.history;assert.ok(h.undoEntries.length+h.redoEntries.length<=100);
  assert.ok(s.codes.every(v=>v===s.codes[0]),'uniform scalar fixture');
  for(const kind of ['undo','redo']){
   if(h[kind+'Entries'].length)eq(s.codes,h[kind+'Entries'].at(-1)[kind==='undo'?'after':'before']);
   for(const e of h[kind+'Entries'])if(e.link){halves++;const p=links.transactions.get(e.link.transaction);assert.ok(p,'no orphan');
    assert.equal(p.kind,e.link.kind);assert.equal(p[e.link.role].record,r);assert.equal(p[e.link.role].entry,e);
    const other=p[OTHER[e.link.role]];assert.ok(other.record.session.history[kind+'Entries'].includes(other.entry),'one-sided link');}
  }
 }
 assert.equal(halves,links.transactions.size*2);assert.equal(digest(),expected,`model step ${index}: ${JSON.stringify(op)}`);
}
assert.ok(faults>0);assert.ok(paired>0);console.log(JSON.stringify({operations:data.length,faults,paired}));
""", trace, internal=True)
        self.assertEqual(result['operations'], len(trace))
        counts = model.counts
        for name in ('transfers', 'balances', 'cap_ended', 'redo_ended', 'paired_steps', 'blocked', 'faults_reached'):
            self.assertGreater(counts[name], 0, name)
        self.assertEqual(unwound, ordinary + linked)
        self.assertEqual(model.counts['paired_steps'] - before, linked)
        self.assertGreater(linked, 50)
        result.update(counts, unwound=unwound)
        print('E10c randomized UI model: ' + json.dumps(result, sort_keys=True))

    def test_86_removal_free_mixed_cap_stress_against_independent_model(self):
        model = MixedModel(('1', '2', '3'))
        rng = random.Random(0xE10CCA)
        keys = list(model.fields)
        trace = []
        for _ in range(24000):
            action = rng.randrange(100)
            key = rng.choice(keys)
            other = rng.choice([k for k in keys if k != key])
            if action < 26:
                op = ['edit', key, rng.randrange(256)]
            elif action < 46:
                op = ['transfer', key, other, rng.randrange(1, 101)]
            elif action < 68:
                op = ['balance', key, other, rng.randrange(101), rng.randrange(1, 101)]
            elif action < 84:
                op = ['undo', key]
            else:
                op = ['redo', key]
            model.apply_links(op)
            trace.append([op, model.links_digest()])
        result = pure(r"""
const {createHash}=await import('node:crypto');
members=members.filter(r=>r!==d);members.forEach((r,i)=>{r.key=String(i+1);r.label=r.key;});
const counts={transfers:0,balances:0,cap_linked_roots:0,cap_ended:0,cap_cascade:0,redo_ended:0,mixed_discards:0,paired_steps:0,blocked:0};
const sidesOf=row=>row.kind==='transfer'?[row.destination,row.source]:[row.active,row.partner];
for(const r of members)observeHistory(r.session.history,(cleared,evicted)=>{
 const before=new Map([...links.transactions].map(([id,row])=>[id,row.kind])),inUndo=new Set();
 for(const [id,row] of links.transactions)if(sidesOf(row).some(s=>s.entry===evicted||s.record.session.history.undoEntries.includes(s.entry)))inUndo.add(id);
 links.discarded(cleared,evicted);
 const ended=[...before.keys()].filter(id=>!links.transactions.has(id)),kinds=new Set(ended.map(id=>before.get(id)));
 const cap=ended.filter(id=>inUndo.has(id)).length,root=evicted?.link?1:0;
 counts.cap_linked_roots+=root;counts.cap_ended+=cap;counts.cap_cascade+=cap-root;counts.redo_ended+=ended.length-cap;
 if(kinds.has('transfer')&&kinds.has('balance'))counts.mixed_discards++;
});
const byKey=k=>members.find(r=>r.key===k);
const digest=()=>{
 const rows=members.map(r=>[r.key,r.session.codes[0],...['undo','redo'].map(kind=>r.session.history[kind+'Entries'].map(e=>
  [e.before[0],e.after[0],e.link?.transaction??null,e.link?.kind??null,e.link?.role??null,e.link?.partner??null]))]);
 const table=[...links.transactions.entries()].map(([id,row])=>[id,row.kind]).sort((x,y)=>x[0]-y[0]);
 return createHash('sha256').update(JSON.stringify([links.nextTransaction,rows,table])).digest('hex');
};
for(let i=0;i<data.length;i++) {
 const [op,expected]=data[i],[action,...args]=op;
 if(action==='edit')edit(byKey(args[0]),args[1]);
 else if(action==='transfer'){if(move(byKey(args[0]),byKey(args[1]),args[2]))counts.transfers++;}
 else if(action==='balance'){if(bal(byKey(args[0]),byKey(args[1]),args[2],args[3]))counts.balances++;}
 else{const state=links.step(action,byKey(args[0])).state;counts.paired_steps+=state==='linked';counts.blocked+=state==='blocked';}
 invariants();assert.equal(digest(),expected,`cap model step ${i}: ${JSON.stringify(op)}`);
}
console.log(JSON.stringify({operations:data.length,...counts}));
""", trace)
        expected = {name: value for name, value in model.counts.items() if name != 'faults_reached'}
        self.assertEqual(result, dict(operations=24000, **expected))
        for name in ('transfers', 'balances', 'cap_linked_roots', 'cap_ended', 'cap_cascade', 'redo_ended',
                     'mixed_discards', 'paired_steps', 'blocked'):
            self.assertGreater(result[name], 0, name)
        print('E10c removal-free mixed cap model: ' + json.dumps(result, sort_keys=True))

    def test_87_edit_guard_ignores_keyboard_actions_during_a_balance_stroke(self):
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);press('Invert');press('Undo');
pointer('pointerdown',64,64);const before=state();
for(const name of ['Undo','Redo','Clear','Fill with Influence','Invert','Flip Horizontal','Rotate 90° CW']) {
 fire(window,'keydown',{key:'Enter',target:buttons(name)[0]});press(name);assert.equal(state(),before,name);
}
key('z',{ctrlKey:true});key('y',{ctrlKey:true});assert.equal(state(),before);
pointer('pointerup',64,64);assert.equal(a.history.undoEntries.length,1);assert.equal(b.history.undoEntries.length,1);assertBalance(a,b);
""")

    def test_88_third_and_fourth_fields_byte_identical(self):
        editor(r"""
const [a,b]=await balancePair(20,180,4,75);activate('3');transferFrom('4');activate('4');partnerWith('3');share(30);
for(const k of ['3','4']){const s=field(k).session;s.selection=Uint8Array.from({length:16384},(_,i)=>i%3===0?1:0);
 s.settings.value_profile='radial';s.settings.shape='diamond';s.replace('Unrelated',uniform(70));}
activate('1');partnerWith('2');
const saved=()=>JSON.stringify(['3','4'].map(k=>[snapshot(field(k).session),field(k).visible,field(k).transferFrom,field(k).balanceWith,field(k).balanceShare]));
const before=saved();click(64,64);assert.equal(saved(),before);press('Undo');assert.equal(saved(),before);press('Redo');assert.equal(saved(),before);
activate('2');press('Undo');assert.equal(saved(),before);
""")

    def test_89_module_boundaries_prefix_hashes_and_tokens(self):
        for path, digest in {
            CORE / 'engine.js': '6366d2b89f8fe8ad791b5a4b96f1c2311559008549cf1eddcf3f3eeb32c28042',
            CORE / 'brush.js': 'd4969ae4528b7cb146c9ed86680d2bf6c45cb852831c79755e793daf3fe346a9',
            CORE / 'history.js': '1b65ef775b17fa8cee83d56b7b315f3149ebeffcef04f552cf0139fa5b5157bf',
            ROOT / 'web/js/painted_field_node.js': 'f13daf18ad81c2ad96be350772e0afbdbc8ec60bf7a8b197f41dbf3e906ab690',
        }.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, path.name)
        transfer = (CORE / 'transfer.js').read_bytes()
        self.assertEqual(hashlib.sha256(transfer[:1589]).hexdigest(),
                         '6854a1d6edcbcb92d65df4c371f77bf9adab13c9f23261c9fcdcb58873e4a287')
        self.assertTrue(transfer[:1589].decode().rstrip().endswith('return covered;\n}'))
        self.assertNotRegex(transfer.decode(), r'(?m)^import\b|hotdog|fetch\(|document\.|window\.|Math\.random|Date\.|'
                                               r'localStorage|sessionStorage')
        history = (CORE / 'history.js').read_text(encoding='utf-8').lower()
        self.assertNotIn('balance', history)
        self.assertNotIn('transfer', history)
        source = (CORE / 'editor_ui.js').read_text(encoding='utf-8')
        self.assertEqual(source.count(HOOK), 1)
        for name in ('function settleSource(', 'function chooseTransferSource(', 'const links = new TransferLinks(',
                     'let stroke = null', 'function settlePartner(', 'function chooseBalancePartner('):
            self.assertIn(name, source)
        hidden = source.index('.cl-field-editor [hidden] {display:none;}')
        for rule in ('.cl-field-editor .balance-help,.cl-field-editor .balance-status {display:block;}',
                     '.cl-field-editor .balance-status {color:#ffb5ab;}', '.cl-field-editor .field-balance {color:#ffd27a;}'):
            self.assertLess(source.index(rule), hidden, rule)
        run_node(IMPORTS + "assert.equal(Object.keys(new FieldHistory()).join(','),'undoEntries,redoEntries');"
                           "assert.equal(BALANCE_LABEL,'Balance');assert.equal(BALANCE_DEFAULT_SHARE,50);")

    def test_90_partner_overlay_live_exact_heat_and_idle_cache(self):
        editor(r"""
const [a,b]=await balancePair(20,180,2,75);const overlay=field('2');pointer('pointerdown',64,64);
const canvas=overlays()[1],pixels=canvas.pixels;assert.equal(b.codes[center],50);
eq(pixels,view.overlayPixels(b.codes,view.OVERLAY_COLORS[overlay.slot]));
pointer('pointerup',64,64);const after=canvas.pixels;press('Heat View');assert.equal(canvas.pixels,after);
redraw();assert.equal(canvas.pixels,after);press('Undo');eq(canvas.pixels,view.overlayPixels(b.codes,view.OVERLAY_COLORS[overlay.slot]));
assert.equal(b.codes[center],180);
""")

    def test_91_exact_strip_role_badge_help_title_and_status_strings(self):
        editor(r"""
await setup([20,180,50]);
assert.equal(balances()[1].title,"Move influence between this field and Painted Field #2, in either direction, toward this field's Active Share of their total where you paint. Each cell's total of the two fields stays the same. One undo step in both fields.");
assert.equal(all().find(e=>e.tagName==='BUTTON'&&e.textContent==='Use Pen Pressure').title,
 "Read a pen's pressure while painting with Paint, Erase, Restore, Transfer or Balance. Mouse, touch and Shift-click lines always paint with the set values.");
partnerWith('2');share(75);
assert.equal(find('balance-help').textContent,"Balance moves influence between this field and its partner, in either direction, until this field holds its Active Share of their total at each cell. Each cell's total of the two fields stays the same; where 0–255 cannot hold that share, Balance stops at the nearest split that fits. Amount is the share of the remaining distance that one stroke moves. Shape, Size, Hardness, Spacing, Build-up, Flow, pen pressure and this field's selection apply; Value Profile, Apply and Influence do not.");
assert.equal(find('balance-share').children[0].attributes['aria-label'],'Active Share (%)');assert.ok(find('balance-share').textContent.startsWith('Active Share (%)'));
assert.equal(find('field-balance').textContent,'Balance: Painted Field #1 ↔ Painted Field #2 · 75:25');
assert.deepEqual(roles(),['','partner','']);assert.equal(tabs()[1].title,'Painted Field #2 · balance partner');
assert.equal(heading('Brush Behavior').textContent,'Brush Behavior · Balance 75:25');
assert.ok(heading('Advanced').textContent.startsWith('Advanced · Balance 75:25'));assert.equal(buttons('Reset Brush')[0].hidden,false);
const first=field('1').session;first.settings.amount=40;first.settings.apply_mode='lower_only';redraw();
assert.equal(heading('Brush Behavior').textContent,'Brush Behavior · Amount 40% · Balance 75:25 · Lower Only (inactive for Balance)');
all().filter(e=>e.className==='field-show')[1].click();dom.flush();
assert.equal(find('field-balance').textContent,'Balance: Painted Field #1 ↔ Painted Field #2 · 75:25 · partner hidden');
assert.equal(find('balance-status').hidden,true);assert.equal(find('balance-status').textContent,'');
for(const [p,text] of [[0,'0:100'],[100,'100:0'],[33,'33:67']]){share(p);assert.ok(find('field-balance').textContent.includes(` · ${text}`));
 assert.equal(heading('Brush Behavior').textContent.split(' · ')[2],`Balance ${text}`);}
const shown=find('field-balance').textContent;click(64,64);assert.equal(find('field-balance').textContent,shown);
assert.ok(!/Balance|partner|Painted Field #2/.test(find('status').textContent));
activate('2');assert.equal(find('field-balance').hidden,true);assert.deepEqual(roles(),['','','']);
partnerWith('3');assert.equal(find('field-balance').textContent,'Balance: Painted Field #2 ↔ Painted Field #3 · 50:50');
""")

    def test_92_transfer_only_extended_model_equals_retained_and_coordinator_replay(self):
        retained, extended = RetainedTransferModel(), MixedModel()
        rng = random.Random(0xE10C0B)
        for _ in range(6000):
            members = list(retained.fields)
            available = [k for k in members if k not in retained.unavailable]
            action = rng.randrange(100)
            if action < 30:
                ops = [['edit', rng.randrange(256)]]
            elif action < 53 and retained.active in available and len(available) > 1:
                ops = [['transfer', rng.choice([k for k in available if k != retained.active]), rng.randrange(1, 101),
                        rng.randrange(20) == 0]]
            elif action < 66:
                ops = [['undo', rng.randrange(20) == 0]]
            elif action < 74:
                ops = [['redo', rng.randrange(20) == 0]]
            elif action < 83:
                ops = [['activate', rng.choice(members)]]
            elif action < 87 and len(members) > 1:
                ops = [['remove', rng.choice(members)]]
            elif action < 91 and len(members) < 4:
                key = rng.choice([k for k in ('1', '2', '3', '4') if k not in members])
                ops = [['available', key, True], ['join', key]]
            elif action < 96:
                key = rng.choice(members)
                ops = [['available', key, key in retained.unavailable]]
            else:
                ops = [['choose', rng.choice(members)]]
            for op in ops:
                retained.apply(op)
                extended.apply(op)
                self.assertEqual(retained.digest(), extended.transfer_digest(), op)
        self.assertEqual(retained.counts['transfers'], extended.counts['transfers'])
        self.assertEqual(retained.counts['paired_steps'], extended.counts['paired_steps'])
        model = MixedModel()
        trace = []
        keys = list(model.fields)
        for _ in range(16000):
            action = rng.randrange(100)
            key = rng.choice(keys)
            other = rng.choice([k for k in keys if k != key])
            op = (['edit', key, rng.randrange(256)] if action < 30 else
                  ['transfer', key, other, rng.randrange(1, 101)] if action < 64 else
                  ['undo', key] if action < 84 else ['redo', key])
            model.apply_links(op)
            trace.append([op, model.links_digest()])
        result = pure(r"""
const {createHash}=await import('node:crypto');
members.forEach((r,i)=>{r.key=String(i+1);r.label=r.key;});const byKey=k=>members.find(r=>r.key===k);
for(let i=0;i<data.length;i++) {
 const [op,expected]=data[i],[action,...args]=op;
 if(action==='edit')edit(byKey(args[0]),args[1]);else if(action==='transfer')move(byKey(args[0]),byKey(args[1]),args[2]);
 else links.step(action,byKey(args[0]));
 invariants();
 const rows=members.map(r=>[r.key,r.session.codes[0],...['undo','redo'].map(kind=>r.session.history[kind+'Entries'].map(e=>
  [e.before[0],e.after[0],e.link?.transaction??null,e.link?.kind??null,e.link?.role??null,e.link?.partner??null]))]);
 const table=[...links.transactions.entries()].map(([id,row])=>[id,row.kind]).sort((x,y)=>x[0]-y[0]);
 assert.ok(table.every(([,kind])=>kind==='transfer'));
 assert.equal(createHash('sha256').update(JSON.stringify([links.nextTransaction,rows,table])).digest('hex'),expected,`step ${i}`);
}
console.log(JSON.stringify({operations:data.length}));
""", trace)
        self.assertEqual(result, {'operations': 16000})
        self.assertGreater(model.counts['cap_ended'], 100)

    def test_93_balance_message_lifecycle_and_owner_rules(self):
        editor(r"""
const bm5='Nothing to balance under the brush: Painted Field #1 and Painted Field #2 are already at 50:50 there, as closely as whole 0–255 codes allow.';
// A successful step clears a blocked Balance note; switching, leaving Balance and choices clear the others.
for(const success of ['linked','single']) {
 const [a,b]=await balancePair(20,180,2,75),{records,links}=controller.__balance;click(64,64);b.replace('Later edit',uniform(7));
 const before=state();press('Undo');assert.equal(state(),before);
 const note='Undo Balance: first undo the later edits of Painted Field #2.';assertMessage(note,true);
 if(success==='linked')assert.equal(links.step('undo',records[1]).state,'single');else a.replace('Ordinary edit',uniform(19));
 redraw();assertMessage(note,true);press('Undo');assertMessage('');redraw();assertMessage('');
}
for(const leave of [()=>press('Paint'),()=>transferFrom('3'),()=>partnerWith('3'),()=>activate('2'),()=>press('Reset Brush')]) {
 const [a,b]=await balancePair(60,61,3,50);click(64,64);assertMessage(bm5);leave();assertMessage('');redraw();assertMessage('');
}
// A refusal clears itself once it no longer applies; a Transfer message is not a Balance message.
let [a,b]=await balancePair(20,180,2,75);unavailable.add('1');redraw();click(64,64);
assertMessage('Cannot balance Painted Field #1: it is no longer in this graph.');unavailable.delete('1');redraw();assertMessage('');
transferFrom('2');b.replace('Zero',uniform(0));click(64,64);
assertMessage('Nothing to transfer under the brush: Painted Field #2 is 0 or Painted Field #1 is 255 there.');
partnerWith('2');assertMessage('');
""", internal=True)

    def test_94_settled_message_uses_only_covered_cells_of_the_active_selection(self):
        editor(r"""
const [a,b]=await balancePair(60,61,2,50);Object.assign(a.settings,{shape:'square',size:128,amount:1});
a.codes[0]=0;b.codes[0]=200;a.codes[2]=40;b.codes[2]=81;
a.selection=empty();a.selection[1]=a.selection[3]=1;b.selection=uniform(1);b.selection[1]=b.selection[3]=0;redraw();
const a0=a.codes.slice(),b0=b.codes.slice(),mask=b.selection.slice(),id=controller.__balance.links.nextTransaction;
const bm5='Nothing to balance under the brush: Painted Field #1 and Painted Field #2 are already at 50:50 there, as closely as whole 0–255 codes allow.';
pointer('pointerdown',64,64);assertMessage('');pointer('pointerup',64,64);assertMessage(bm5);eq(a.codes,a0);eq(b.codes,b0);eq(b.selection,mask);
// A selected cell that is not settled but only rounds to zero keeps it silent.
a.selection[2]=1;pointer('pointerdown',64,64);pointer('pointerup',64,64);assertMessage('');eq(a.codes,a0);
// An unselected movable cell under the brush neither suppresses nor creates the message.
a.selection=empty();a.selection[1]=1;a.settings.amount=100;click(64,64);assertMessage(bm5);eq(a.codes,a0);eq(b.codes,b0);
assert.equal(controller.__balance.links.nextTransaction,id);assert.equal(a.history.undoEntries.length,0);
""", internal=True)

    def test_95_partner_buffer_corruption_refused_before_any_write(self):
        editor(r"""
for(const kind of ['undo','redo'])for(const initiator of ['1','2']) {
 const [a,b]=await balancePair(20,180,2,75);click(64,64);if(kind==='redo')press('Undo');activate(initiator);
 const {records,links}=controller.__balance,own=records.find(r=>r.key===initiator),partner=records.find(r=>r!==own);
 assert.equal(links.classify(kind,own).state,'linked');
 partner.session.codes=partner.session.codes.slice();partner.session.codes[0]^=1;redraw();
 const before=state(),table=[...links.transactions],id=links.nextTransaction;let writes=0;
 for(const r of records){let codes=r.session.codes;Object.defineProperty(r.session,'codes',{configurable:true,enumerable:true,
  get:()=>codes,set:value=>{writes++;codes=value;}});}
 const classification=links.classify(kind,own);assert.equal(classification.state,'broken');assert.equal(classification.reason,'buffer mismatch');
 const action=kind==='undo'?'Undo':'Redo';press(action);assert.equal(writes,0,'refusal before writes');assert.equal(state(),before);
 assert.equal(links.nextTransaction,id);for(const [t,row] of table)assert.equal(links.transactions.get(t),row);
 assertMessage(`${action} refused: a Balance history link is inconsistent (buffer mismatch). Nothing was changed.`);
}
""", internal=True)

    def test_96_no_storage_or_composition_access(self):
        editor(r"""
globalThis.localStorage=new Proxy({},{get(){assert.fail('storage read');},set(){assert.fail('storage write');}});
globalThis.sessionStorage=globalThis.localStorage;
const [a,b]=await balancePair(20,180,2,75);for(const s of [a,b])for(const key of ['Strength','strength','mode','links','composition','order','enabled'])
 Object.defineProperty(s,key,{get(){assert.fail('composition read '+key);}});
click(64,64);press('Undo');press('Redo');press('Done');await until(()=>offers.length);
assert.equal(offers[0].length,2);assert.equal(offers[0][0].settings.tool,'paint');assert.equal(offers[0][1].settings.tool,'paint');
assert.ok(!/balance|partner|share|transaction/i.test(JSON.stringify(offers.map(o=>o.map(f=>f.settings)))));
""")

    def test_97_editor_full_coverage_every_pair_matches_the_closed_form(self):
        data = {'table': nearest_table(), 'moves': [[(d * k + 50) // 100 for d in range(256)] for k in range(101)]}
        result = editor(r"""
let cells=0;
for(let block=0;block<4;block++)for(const p of [0,25,50,75,100])for(const k of [100,37]) {
 const [a,b]=await balancePair(0,0,2,p);full();a.settings.amount=k;
 const a0=Uint8Array.from({length:16384},(_,i)=>(block*16384+i)%256),b0=Uint8Array.from({length:16384},(_,i)=>Math.floor((block*16384+i)/256));
 a.codes=a0.slice();b.codes=b0.slice();redraw();click(64,64);
 for(let i=0;i<16384;i++){const t=a0[i]+b0[i],o=data.table[t][p],goal=o.length===1||Math.abs(o[0]-a0[i])<Math.abs(o[1]-a0[i])?o[0]:o[1];
  const m=Math.sign(goal-a0[i])*data.moves[k][Math.abs(goal-a0[i])];
  if(a.codes[i]!==a0[i]+m||b.codes[i]!==b0[i]-m)assert.fail(`cell ${a0[i]},${b0[i]} share ${p} amount ${k}`);cells++;}
}
console.log(JSON.stringify({cells}));
""", data)
        self.assertEqual(result, {'cells': 655360})

    def test_98_pointer_exclusivity_and_per_field_memory(self):
        editor(r"""
await setup([10,200,50,80]);const pointers=()=>controller.fields().map(f=>[f.key,f.transferFrom,f.balanceWith]);
const one=()=>controller.fields().every(f=>!(f.transferFrom&&f.balanceWith));
transferFrom('2');partnerWith('2');assert.deepEqual(pointers()[0],['1',null,'2']);
transferFrom('2');assert.deepEqual(pointers()[0],['1','2',null]);partnerWith('2');transferFrom('3');assert.deepEqual(pointers()[0],['1','3',null]);
for(const leave of [()=>press('Paint'),()=>press('Erase'),()=>press('Restore'),()=>key('b'),()=>key('e'),()=>press('Reset Brush')])
 for(const choose of [()=>partnerWith('2'),()=>transferFrom('2')]){choose();assert.ok(one());leave();assert.deepEqual(pointers()[0],['1',null,null]);
  assert.ok(!['transfer','balance'].includes(field('1').session.settings.tool));}
// Section 19.2: each field keeps its own memory across switches and never inherits another's.
partnerWith('2');share(75);activate('2');assert.deepEqual(pointers()[1],['2',null,null]);assert.equal(field('2').balanceShare,50);
activate('1');assert.deepEqual(pointers()[0],['1',null,'2']);assert.equal(field('1').balanceShare,75);
activate('2');partnerWith('1');assert.equal(field('2').balanceShare,50);assert.deepEqual(pointers()[0],['1',null,'2']);
activate('3');transferFrom('4');activate('4');partnerWith('3');
assert.deepEqual(pointers(),[['1',null,'2'],['2',null,'1'],['3','4',null],['4',null,'3']]);assert.ok(one());
// A partner deleted from the graph while another field is active clears on the next activation; the tool stays.
unavailable.add('2');activate('1');assert.deepEqual(pointers()[0],['1',null,null]);assert.equal(field('1').session.settings.tool,'balance');
click(64,64);assertMessage('Choose a field to balance with: Advanced ▸ Brush Behavior ▸ Balance with…');
assert.ok(controller.fields().every(f=>f.balanceWith!==f.key&&f.transferFrom!==f.key));
""")

    def test_99_four_field_chain_cap_stress_both_kinds_against_independent_model(self):
        model = MixedModel()
        rng = random.Random(0xE10CC4)
        trace = []
        chain = [('transfer', '1', '2'), ('transfer', '2', '1'), ('balance', '2', '3'), ('balance', '3', '2'),
                 ('transfer', '3', '4'), ('transfer', '4', '3')]
        for _ in range(8000):
            action = rng.randrange(100)
            if action < 30:
                op = ['edit', rng.choice(list(model.fields)), rng.randrange(256)]
            elif action < 70:
                kind, first, second = rng.choice(chain)
                op = ([kind, first, second, rng.randrange(1, 101)] if kind == 'transfer'
                      else [kind, first, second, rng.randrange(101), rng.randrange(1, 101)])
            else:
                op = [rng.choice(['undo', 'redo']), rng.choice(list(model.fields))]
            model.apply_links(op)
            trace.append([op, model.links_digest()])
        result = pure(r"""
const {createHash}=await import('node:crypto');
members.forEach((r,i)=>{r.key=String(i+1);r.label=r.key;});const byKey=k=>members.find(r=>r.key===k);
for(let i=0;i<data.length;i++) {
 const [op,expected]=data[i],[action,...args]=op;
 if(action==='edit')edit(byKey(args[0]),args[1]);else if(action==='transfer')move(byKey(args[0]),byKey(args[1]),args[2]);
 else if(action==='balance')bal(byKey(args[0]),byKey(args[1]),args[2],args[3]);else links.step(action,byKey(args[0]));
 invariants();
 for(const row of links.transactions.values()){
  const keys=(row.kind==='transfer'?[row.destination,row.source]:[row.active,row.partner]).map(s=>s.record.key).sort().join('');
  assert.ok(row.kind==='transfer'?['12','34'].includes(keys):keys==='23',`kind confusion ${row.kind} ${keys}`);
 }
 const rows=members.map(r=>[r.key,r.session.codes[0],...['undo','redo'].map(kind=>r.session.history[kind+'Entries'].map(e=>
  [e.before[0],e.after[0],e.link?.transaction??null,e.link?.kind??null,e.link?.role??null,e.link?.partner??null]))]);
 const table=[...links.transactions.entries()].map(([id,row])=>[id,row.kind]).sort((x,y)=>x[0]-y[0]);
 assert.equal(createHash('sha256').update(JSON.stringify([links.nextTransaction,rows,table])).digest('hex'),expected,`chain step ${i}`);
}
console.log(JSON.stringify({operations:data.length}));
""", trace)
        self.assertEqual(result, {'operations': 8000})
        for name in ('transfers', 'balances', 'cap_ended', 'cap_cascade', 'redo_ended', 'mixed_discards',
                     'paired_steps', 'blocked'):
            self.assertGreater(model.counts[name], 0, name)
        print('E10c four-field chain cap model: ' + json.dumps(model.counts, sort_keys=True))
