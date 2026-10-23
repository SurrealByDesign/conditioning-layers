"""ADR-0038 grouped E10 preview: exact CPU equality and fenced frontend checks."""
import math
import random
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.integrations import composition_preview as preview
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import round_ratio_to_binary32_bits
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition import compose_grouped_field_codes
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.models import LayerMode
from test_composition_preview import GRAPH, MODULE, layer
from test_field_editor_custom_tip import run_node
from test_field_editor_multi_field import EDITOR

GROUPED, LEGACY = preview.GROUPED_COMPOSE, preview.LEGACY_COMPOSE
STRENGTHS = (0.0, 5e-324, 2**-149, 1e-37, 0.1, 0.5, math.nextafter(1.0, 0.0), 1.0)


def request(layers, selected, compose=GROUPED):
    return {"compose": compose, "layers": layers, "selected": selected}


def production(layers):
    """The native node's call on enabled layers, in authored order."""
    active = [item for item in layers if item["enabled"]]
    return compose_grouped_field_codes(
        tuple(tuple(item["codes"]) for item in active), tuple(item["strength"] for item in active),
        tuple(LayerMode(item["mode"]) for item in active), tuple(item["group"] for item in active),
        labels=tuple(item["id"] for item in active))


def assertBits(case, actual, expected, label=""):
    """Report the first difference; difflib over 16,384 samples is prohibitively slow."""
    if list(actual) != list(expected):
        first = next((i for i, (a, b) in enumerate(zip(actual, expected)) if a != b), min(len(actual), len(expected)))
        case.fail(f"{label} differs first at sample {first} (lengths {len(actual)} / {len(expected)})")


class NumericalTests(unittest.TestCase):
    def assertPreviewEqualsProduction(self, layers):
        expected = iter(production(layers))
        for item in layers:
            result = preview.preview_composition(request(layers, item["id"]))
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["disabled"], not item["enabled"])
            assertBits(self, result["bits"], next(expected) if item["enabled"] else [0] * 16384, item["id"])

    def test_randomized_groups_fixed_disabled_and_gaps_equal_production_bits(self):
        rng = random.Random(38)
        for count in (2, 3, 5, 9, 12, 40):
            layers = []
            for i in range(count):
                # Period-64 planes keep 40-layer cases quick yet include local gaps and soft codes.
                codes = [rng.choice((0, 0, 1, 2, 127, 128, 254, 255, rng.randrange(256))) for _ in range(64)]
                codes[i % 64] = 255
                layers.append(layer(f"n{i}", codes, rng.choice(STRENGTHS),
                                    group=rng.choice(("", "A", "B", "A,B", "default", "Group 1"))))
            # One FIXED owner on its own cells, carrying an ignored saved group, and one disabled member.
            layers[0].update(mode="FIXED", group="A", codes=[255 if p % 64 == 63 else 0 for p in range(16384)])
            layers[-1].update(enabled=False, codes={"unread": True}, group="B")
            for item in layers[1:-1]:
                item["codes"][63::64] = [0] * 256
            self.assertPreviewEqualsProduction(layers)

    def test_exp0015_unequal_membership_shares(self):
        layers = [layer(name, (255,), group=group) for name, group in zip("ABCDE", ("", "", "", "D", "D"))]
        sixth, quarter = round_ratio_to_binary32_bits(1, 6), round_ratio_to_binary32_bits(1, 4)
        for item, bits in zip(layers, (sixth,) * 3 + (quarter,) * 2):
            assertBits(self, preview.preview_composition(request(layers, item["id"]))["bits"], [bits] * 16384, item["id"])
        self.assertPreviewEqualsProduction(layers)

    def test_missing_or_single_group_equals_legacy_preview(self):
        for group in ("", "one"):
            layers = [layer(i, (1, 129, 255, 0), strength, group=group)
                      for i, strength in enumerate((1.0, 0.5, 5e-324))]
            plain = [{**item, "group": ""} for item in layers]
            for item in layers:
                grouped = preview.preview_composition(request(layers, item["id"]))
                legacy = preview.preview_composition(request(plain, item["id"], LEGACY))
                self.assertEqual((grouped["status"], grouped["disabled"]), (legacy["status"], legacy["disabled"]))
                assertBits(self, grouped["bits"], legacy["bits"], item["id"])

    def test_legacy_rejects_explicit_assignment_even_disabled_or_fixed(self):
        for change in ({}, {"enabled": False}, {"mode": "FIXED", "codes": [0, 0, 0, 255] * 4096}):
            layers = [layer("a"), {**layer("b", group="A"), **change}]
            with self.assertRaisesRegex(ValueError, '^Layer b: group "A" needs Compose Blend Groups$'):
                preview.preview_composition(request(layers, "a", LEGACY))
            self.assertEqual(preview.preview_composition(request(layers, "a"))["status"], "ready")

    def test_fixed_conflicts_are_global_across_groups(self):
        layers = [layer("a", (1, 0, 1, 0), 0.0, "FIXED", group="A"), layer("b", (1, 1, 0, 0), 1.0, "FIXED", group="B"),
                  layer("c", group="C")]
        result = preview.preview_composition(request(layers, "c"))
        self.assertEqual((result["status"], result["pairs"]), ("conflict", [{"layers": ["a", "b"], "count": 4096}]))
        self.assertEqual(result["cells"], list(range(0, 16384, 4)))

    def test_grouped_import_failure_leaves_legacy_preview_available(self):
        layers = [layer("a"), layer("b", strength=0.5)]
        expected = preview.preview_composition(request(layers, "a", LEGACY))
        name = "conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition"
        with patch.dict(sys.modules, {name: None}):
            assertBits(self, preview.preview_composition(request(layers, "a", LEGACY))["bits"], expected["bits"])
            with self.assertRaises(ImportError):
                preview.preview_composition(request(layers, "a"))


# Native 0.34.6 / frontend 1.49.6 widget-backed optional socket, as in the Stage 1
# Inline native grouped-widget persistence fixture; no external evidence file is read.
GROUPS = GRAPH + r"""
const setGroups=values=>layers.forEach((l,i)=>{
 if(!l.widgets.some(w=>w.name==='blend_group')){l.widgets.push({name:'blend_group',value:''});
  l.inputs.push({name:'blend_group',type:'STRING',link:null,widget:{name:'blend_group'}});}
 l.widgets.find(w=>w.name==='blend_group').value=values[i];});
setGroups(['','','','','','']);
const widget=(i,name)=>layers[i].widgets.find(w=>w.name===name);
"""


class FrontendTests(unittest.TestCase):
    def test_legacy_compose_with_explicit_assignment_fails_closed_and_recovers(self):
        run_node(GROUPS + r"""
const valid=service.inspect('p0',edits,null);assert.equal(valid.error,undefined);assert.equal(valid.choice.groups,null);
assert.equal(valid.choice.label,'Compose #c · Layer #l0');
for(const [i,name,value,restore] of [[3,null],[4,'enabled',false,true],[5,'mode','FIXED','BLENDED']]){
 if(name)widget(i,name).value=value;widget(i,'blend_group').value='A';
 const s=service.inspect('p0',edits,valid.key);
 assert.equal(s.error,`Layer #l${i}: group "A" needs Compose Blend Groups`);
 assert.equal(s.key,valid.key);assert.notEqual(s.fingerprint,valid.fingerprint);
 assert.ok(s.choices.some(c=>c.key===valid.key&&c.label==='Compose #c · Layer #l0'&&c.error===s.error));
 widget(i,'blend_group').value='';if(name)widget(i,name).value=restore;
 assert.equal(service.inspect('p0',edits,valid.key).fingerprint,valid.fingerprint);
}
// An obsolete in-flight legacy success cannot replace the diagnostic; clearing recovers.
const jobs=[],queue=createPreviewQueue(s=>new Promise(resolve=>jobs.push({s,resolve})),()=>{},0);
const wait=()=>new Promise(r=>setTimeout(r,8));
queue.update(valid);await wait();widget(2,'blend_group').value='B';
const invalid=service.inspect('p0',edits,valid.key);queue.update(invalid);
jobs[0].resolve({status:'ready',obsolete:true});await wait();
assert.equal(queue.state.status,'unavailable');assert.equal(queue.state.message,invalid.error);
widget(2,'blend_group').value='';queue.update(service.inspect('p0',edits,valid.key));await wait();
jobs[1].resolve({status:'ready',obsolete:false});await wait();
assert.equal(queue.state.obsolete,false);queue.dispose();assert.equal(requests.length,0);
""")

    def test_grouped_compose_payload_identity_fingerprint_and_membership(self):
        run_node(GROUPS + r"""
const legacy=service.inspect('p0',edits,null);compose.type='ConditioningLayersComposeGroups';
const grouped=service.inspect('p0',edits,legacy.key);
assert.equal(grouped.key,legacy.key);assert.notEqual(grouped.fingerprint,legacy.fingerprint);
assert.equal(grouped.choice.label,'Blend Groups #c · Layer #l0');
setGroups(['','B','A','A','B','A']);widget(1,'enabled').value=false;widget(5,'mode').value='FIXED';
const s=service.inspect('p0',edits,legacy.key);assert.equal(s.error,undefined);
assert.deepEqual(s.choice.groups,{compact:'default group',detail:'Compose Blend Groups · default group: #l0 (selected) · '
 +'group "A": #l2, #l3 · group "B": #l4 · FIXED, global across groups: #l5 · disabled: #l1'});
await service.calculate(s);const sent=requests[0];
assert.equal(sent.compose,'ConditioningLayersComposeGroups');assert.equal(sent.selected,'l0');
assert.deepEqual(sent.layers.map(l=>[l.id,l.group,l.mode,l.enabled]),[['l0','','BLENDED',true],['l1','B','BLENDED',false],
 ['l2','A','BLENDED',true],['l3','A','BLENDED',true],['l4','B','BLENDED',true],['l5','A','FIXED',true]]);
assert.equal(sent.layers[0].codes[0],128);assert.equal(sent.layers[1].codes,null);assert.equal(sent.layers[2].codes[0],3);
for(const [field,compact] of [['p2','group "A"'],['p4','group "B"'],['p5','FIXED · global'],['p1',null]])
 assert.equal(service.inspect(field,edits,null).choice.groups.compact,compact);
// Membership is identity-bearing: any group change invalidates; restoring restores the fingerprint.
widget(3,'blend_group').value='B';const moved=service.inspect('p0',edits,s.key);
assert.notEqual(moved.fingerprint,s.fingerprint);assert.match(moved.choice.groups.detail,/group "A": #l2 · group "B": #l3, #l4/);
widget(3,'blend_group').value='A';assert.equal(service.inspect('p0',edits,s.key).fingerprint,s.fingerprint);
// Literal keys: "default" and "A,B" are names, distinct from the empty default group.
setGroups(['default','A,B','','','','']);widget(1,'enabled').value=true;widget(5,'mode').value='BLENDED';
assert.equal(service.inspect('p0',edits,s.key).choice.groups.detail,
 'Compose Blend Groups · group "default": #l0 (selected) · group "A,B": #l1 · default group: #l2, #l3, #l4, #l5');
""")

    def test_group_metadata_resolution_fails_closed(self):
        run_node(GROUPS + r"""
compose.type='ConditioningLayersComposeGroups';
const socket=layers[0].inputs.find(i=>i.name==='blend_group');
connect(node('dynamic-group','PrimitiveNode'),layers[0],'blend_group');
assert.match(service.inspect('p0',edits,null).error,/Layer #l0: dynamic blend_group/);socket.link=null;
widget(0,'blend_group').value=5;assert.match(service.inspect('p0',edits,null).error,/Layer #l0: invalid Blend Group/);
widget(0,'blend_group').value=' A';assert.equal(service.inspect('p0',edits,null).error,undefined); // Python validates.
widget(0,'blend_group').value='';
const association=socket.widget;delete socket.widget;
assert.match(service.inspect('p0',edits,null).error,/unresolved blend_group/);socket.widget=association;
const groupWidget=layers[0].widgets.pop();assert.match(service.inspect('p0',edits,null).error,/unresolved blend_group/);
layers[0].widgets.push(groupWidget,{...groupWidget});
assert.match(service.inspect('p0',edits,null).error,/unresolved blend_group/);layers[0].widgets.pop();
// Neither socket nor widget: the omitted optional input, i.e. the default group.
layers[0].inputs=layers[0].inputs.filter(i=>i!==socket);layers[0].widgets.pop();
const omitted=service.inspect('p0',edits,null);assert.equal(omitted.error,undefined);
assert.equal(omitted.choice.layers[0].group,'');
layers[0].widgets.push(groupWidget);groupWidget.value='A';
assert.equal(service.inspect('p0',edits,null).choice.layers[0].group,'A'); // Widget-only shape.
assert.equal(requests.length,0);
""")

    def test_compact_group_status_and_full_membership_tooltip(self):
        run_node(EDITOR + r"""
controller.cancel();const {createPreviewQueue}=await import(MODULE);
let revision=0,groups={compact:'group "A"',detail:'Compose Blend Groups · group "A": #3 (selected), #4 · default group: #6'};
let result={status:'ready',bits:Array(16384).fill(0x3f2aaaab)};
host.createCompositionPreview=async()=>({createQueue:(calc,notify)=>createPreviewQueue(calc,notify,0),
 inspect:()=>{const choice={key:'c',label:'Blend Groups #8 · Layer #3',groups};
  return {choices:[choice],key:'c',choice,fingerprint:String(revision)};},
 calculate:async()=>result});
controller=open();dom.flush();press('Contribution');await until(()=>find('status').title.includes('0–100%'));
redraw();assert.match(find('status').textContent,/^66\.66667% contribution · group "A" · x \d+ y \d+$/);
assert.match(find('status').title,/66\.66667% · \d+% zoom · Compose Blend Groups · group "A": #3 \(selected\), #4 · default group: #6$/);
groups={compact:'default group',detail:'Compose Blend Groups · default group: #3 (selected)'};revision++;redraw();
await until(()=>find('status').textContent.startsWith('66.66667% contribution · default group · x'));
result={status:'conflict',cells:[0,1],pairs:[{layers:['3','6'],count:2}]};revision++;redraw();
await until(()=>find('status').textContent==='FIXED conflict · 2 cells · preview unavailable');
assert.equal(find('status').title,'Contribution unavailable · FIXED conflicts: layers 3 / 6 share 2 cells · '+groups.detail);
groups=null;result={status:'ready',bits:Array(16384).fill(0x3f2aaaab)};revision++;redraw();
await until(()=>/^66\.66667% contribution · x \d+ y \d+$/.test(find('status').textContent));
assert.doesNotMatch(find('status').title,/Blend Groups/);
controller.cancel();
""".replace("MODULE", MODULE))


if __name__ == "__main__":
    unittest.main()
