"""Brush dynamics offline contracts: spacing, pressure size and strength, stroke smoothing.

Spacing and pressure Amount exercise the retained engine; Minimum Size and smoothing are new.
The smoothing oracle below is independent Python; the product's smoothing uses only exactly
specified arithmetic, so both must agree bit for bit. No browser, host or device is claimed.
"""
import json
import math
import random
import unittest

from test_field_editor_pressure import run_node as pressure_node, scaled, CORE
from test_field_editor_field_tools import UI
from test_field_editor_procedural_tip import ProceduralOracle

SMOOTHING = (f"const smoothing = await import({json.dumps((CORE / 'stroke_smoothing.js').as_uri())});\n"
             f"const angles = await import({json.dumps((CORE / 'angle_jitter.js').as_uri())});\n") + r"""
const stamps = (b, path) => {  // Raw stamp positions of a plain stroke, before any hard snapping.
  const original = engine.Stroke.prototype.stamp, seen = [];
  engine.Stroke.prototype.stamp = function(x, y) { seen.push([x, y]); return original.call(this, x, y); };
  try { const s = new engine.Stroke(empty(), 128, 128, {...brush, ...b}, ...path[0]); for (const p of path.slice(1)) s.add(...p);
    return {stamps: seen, result: s.result(), coverage: s.coverage}; }
  finally { engine.Stroke.prototype.stamp = original; }
};
const stroked = (b, path) => { const s = new engine.Stroke(empty(), 128, 128, {...brush, ...b}, ...path[0]);
  for (const p of path.slice(1)) s.add(...p); return s.result(); };
const smoothed = (s, path) => { const out = [];
  const sm = new smoothing.StrokeSmoother(s, path[0][0], path[0][1], path[0][2] ?? null, (...p) => out.push(p));
  for (const p of path.slice(1)) sm.add(p[0], p[1], p[2] ?? null); sm.finish(); return out; };
"""


def run_node(body, data=None):
    return pressure_node(SMOOTHING + "{\n" + body + "\n}", data)


def run_editor(body, data=None):
    return pressure_node(SMOOTHING + UI + "{\n" + body + "\n}", data)


def smooth_oracle(path, smoothing):
    """Distance-based follower, transcribed from the stroke_smoothing.js contract."""
    reach = smoothing * 8 / 100
    px, py, pressure = path[0]
    sx, sy, out = px, py, []
    for x, y, p in path[1:]:
        if reach == 0:
            out.append([x, y, p]); px, py, sx, sy, pressure = x, y, x, y, p
            continue
        dx, dy = x - px, y - py
        distance = math.sqrt(dx * dx + dy * dy)
        steps = math.ceil(distance / 0.25)
        if steps == 0:
            if p != pressure:
                pressure = p; out.append([sx, sy, p])
            continue
        h = distance / steps
        share = h / (reach + h)
        for i in range(1, steps + 1):
            sx += (px + dx * i / steps - sx) * share
            sy += (py + dy * i / steps - sy) * share
            out.append([sx, sy, None if p is None else pressure + math.floor((p - pressure) * i / steps + 0.5)])
        px, py, pressure = x, y, p
    if (sx, sy) != (px, py):
        out.append([px, py, pressure])
    return out


def jitter_path(seed=7, count=240):
    rng = random.Random(seed)
    path = [[12.0, 64.0, None]]
    for i in range(1, count):
        path.append([12 + i * 0.4, 64 + rng.uniform(-0.7, 0.7), None])
    path.append([12 + count * 0.4, 64.0, None])
    return path


class SpacingTests(unittest.TestCase):
    def test_dabs_fall_at_equal_distances_along_the_path(self):
        run_node(r"""
for (const [b, gap] of [[{spacing: 'custom', spacing_percent: 25}, 4], [{spacing: 'custom', spacing_percent: 100}, 16], [{}, 0.25]]) {
  const {stamps: s} = stamps(b, [[10, 64], [90, 64]]);
  assert.equal(s.length, Math.floor(80 / gap) + 1);
  s.forEach(([x, y], k) => { assert.equal(y, 64); assert.equal(x, 10 + k * gap); });
}
// A bent path: each dab sits a whole number of spacings along it, the remainder carried across bends.
const path = [[10, 10], [40, 10], [40, 50], [70, 80]], ends = [0, 30, 70, 70 + 30 * Math.SQRT2];
const {stamps: s} = stamps({spacing: 'custom', spacing_percent: 25}, path);
assert.equal(s.length, Math.floor(ends[3] / 4) + 1);
s.forEach(([x, y], k) => {
  const seg = [0, 1, 2].find(j => { const [a, b] = [path[j], path[j + 1]];
    return Math.abs((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) < 1e-9
      && Math.min(a[0], b[0]) - 1e-9 <= x && x <= Math.max(a[0], b[0]) + 1e-9 && Math.min(a[1], b[1]) - 1e-9 <= y && y <= Math.max(a[1], b[1]) + 1e-9; });
  const along = ends[seg] + Math.hypot(x - path[seg][0], y - path[seg][1]);
  assert.ok(Math.abs(along - 4 * k) < 1e-9, `dab ${k} at ${along}`);
});
""")

    def test_event_density_does_not_change_dabs_or_field(self):
        run_node(r"""
const path = [[10, 10], [40, 10], [40, 50], [70, 80]];
const dense = [path[0]];  // Every segment split into 37 collinear events: a slow stroke.
for (let j = 0; j < 3; j++) for (let k = 1; k <= 37; k++)
  dense.push([path[j][0] + (path[j + 1][0] - path[j][0]) * k / 37, path[j][1] + (path[j + 1][1] - path[j][1]) * k / 37]);
const crawl = [[10, 64]]; for (let x = 10.01; x < 90; x += 0.01) crawl.push([x, 64]); crawl.push([90, 64]);
for (const b of [{}, {spacing: 'custom', spacing_percent: 25}, {hardness: 40, spacing: 'custom', spacing_percent: 60},
  {build_up: true, flow: 30, hardness: 0}]) {
  const fast = stamps(b, path), slow = stamps(b, dense);
  assert.deepEqual(slow.stamps, fast.stamps); eq(slow.result, fast.result);
  eq(stamps(b, crawl).result, stamps(b, [[10, 64], [90, 64]]).result, 'crawl');
}
""")

    def test_continuous_strokes_leave_no_gaps(self):
        run_node(r"""
for (const b of [{size: 1}, {size: 3, spacing: 'custom', spacing_percent: 100}, {size: 8, spacing: 'custom', spacing_percent: 100},
  {size: 5, hardness: 0}, {size: 16, spacing: 'custom', spacing_percent: 50}]) {
  // One fast event across the field: every cell from the first dab to the last is reached.
  const row = stamps(b, [[5.5, 64.5], [120.5, 64.5]]), rowEnd = Math.floor(row.stamps.at(-1)[0]);
  assert.ok(rowEnd >= 113, rowEnd);
  for (let x = 6; x <= rowEnd; x++) assert.ok(row.result[64 * 128 + x] > 0, `size ${b.size} gap at ${x}`);
  const diagonal = stamps(b, [[10.5, 10.5], [110.5, 110.5]]), end = Math.floor(diagonal.stamps.at(-1)[0]);
  assert.ok(end >= 104, end);
  for (let k = 11; k <= end; k++) assert.ok(diagonal.result[k * 128 + k] > 0, `size ${b.size} diagonal gap at ${k}`);
}
""")

    def test_near_zero_movement_does_not_restamp(self):
        run_node(r"""
const b = {spacing: 'custom', spacing_percent: 25};
const still = [[64, 64]]; for (let i = 0; i < 1000; i++) still.push([64, 64]);
assert.equal(stamps(b, still).stamps.length, 1);
const quantum = [[64, 64]]; for (let i = 0; i < 1000; i++) quantum.push([64 + (i % 2 ? 1e-4 : -1e-4), 64 - 1e-4]);
assert.equal(stamps(b, quantum).stamps.length, 1);  // Below the 1/256-cell position grid.
assert.equal(stamps({}, quantum).stamps.length, 1);
// Hand tremor in place: dabs stay bounded by distance travelled, and a hard brush's field is one dab's.
const tremor = [[64, 64]]; for (let i = 0; i < 400; i++) tremor.push([64 + (i % 2 ? 0.05 : -0.05), 64]);
const shaken = stamps(b, tremor);
assert.ok(shaken.stamps.length <= Math.floor(400 * 0.1 / 4) + 2, `${shaken.stamps.length} dabs`);
eq(shaken.result, stroked(b, [[64, 64]]));
""")


class PressureSizeTests(unittest.TestCase):
    def test_minimum_size_arithmetic(self):
        expected = [[max(1, (size * percent + 50) // 100) for percent in range(101)] for size in range(1, 129)]
        run_node(r"""
for (let size = 1; size <= 128; size++) for (let percent = 0; percent <= 100; percent++)
  assert.equal(engine.pressureMinSize(size, percent), data[size - 1][percent]);
""", expected)

    def test_disabled_minimum_keeps_the_retained_size_curve(self):
        run_node(r"""
for (const size of [1, 2, 7, 16, 63, 128]) {
  const s = make({size}, [[30, 30, 65535]]);
  for (let code = 0; code <= 65535; code += 97) assert.equal(s.sizeAt(code), engine.scaledControl(size, code));
  // Size off: Minimum Size has nothing to hold.
  const off = make({size, pressure_size: false, pressure_amount: true, pressure_min_size: 80}, [[30, 30, 65535]]);
  for (const code of [0, 1, 30000, 65535]) assert.equal(off.sizeAt(code), size);
}
// pressure_min_size 0 is bit-identical to a brush without the key, through a varying-pressure stroke.
const path = [[20, 20, 4000], [60, 30, 60000], [80, 70, 9000], [40, 90, 30000]];
for (const b of [{}, {hardness: 30, build_up: true, flow: 40}, {pressure_amount: true, value_profile: 'radial'}]) {
  const a = make(b, path), z = make({...b, pressure_min_size: 0}, path);
  eq(a.result(), z.result()); eq(a.coverage, z.coverage, 'coverage');
}
""")

    def test_pressure_changes_size_and_minimum_holds(self):
        run_node(r"""
const covered = r => r.reduce((n, v) => n + (v > 0), 0);
for (const hardness of [100, 35]) {
  let last = 0;
  for (const code of [6554, 19661, 39321, 65535]) {
    const s = make({size: 32, hardness}, [[64, 64, code], [64.5, 64, code]]);
    // Constant pressure paints exactly as a plain stroke at that size.
    eq(s.result(), stroked({size: engine.scaledControl(32, code), hardness}, [[64, 64], [64.5, 64]]));
    const n = covered(s.result()); assert.ok(n > last, `code ${code}`); last = n;
  }
  for (const [percent, floor] of [[25, 8], [50, 16], [100, 32]]) {
    for (const code of [1, 6554, 19661]) {
      const s = make({size: 32, hardness, pressure_min_size: percent}, [[64, 64, code], [70, 64, code]]);
      const size = Math.max(floor, engine.scaledControl(32, code));
      assert.equal(s.sizeAt(code), size);
      eq(s.result(), stroked({size, hardness}, [[64, 64], [70, 64]]));
    }
    assert.equal(make({size: 32, pressure_min_size: percent}, [[64, 64, 65535]]).sizeAt(65535), 32);
  }
}
// Zero pressure still paints nothing, whatever the floor.
eq(make({pressure_min_size: 100}, [[20, 20, 0], [60, 20, 0]]).result(), empty());
""")

    def test_editor_pen_uses_minimum_and_mouse_falls_back(self):
        run_editor(r"""
press('Use Pen Pressure'); type('Minimum Size (% of Size)', 50); type('Size (cells)', 16);
assert.equal(settings().pressure_min_size, 50);
click(40, 40, {pointerType: 'pen', pressure: 0.2});  // scaled 3 cells, held at 8
eq(session().codes, stroked({...engineBrush(), size: 8}, [[40, 40]]));
await reopen(empty(), {size: 16, pressure_enabled: true, pressure_min_size: 50});
for (const extra of [{pointerType: 'mouse', pressure: 0.2}, {pointerType: 'touch', pressure: 0.2}, {}]) {
  const before = session().codes.slice(); click(70, 70, extra);
  eq(session().codes, stroked(engineBrush(), [[70, 70]]).map((v, i) => Math.max(v, before[i])), JSON.stringify(extra));
  press('Undo');
}
click(90, 90, {pointerType: 'pen'});  // A pen that reports no pressure paints at full size.
eq(session().codes, stroked(engineBrush(), [[90, 90]]));
""")


class PressureStrengthTests(unittest.TestCase):
    def test_disabled_strength_keeps_amount(self):
        run_node(r"""
for (const code of [3000, 30000, 65535]) {
  const s = make({amount: 70, pressure_size: true, pressure_amount: false}, [[50, 50, code], [60, 55, code]]);
  eq(s.result(), stroked({amount: 70, size: engine.scaledControl(16, code)}, [[50, 50], [60, 55]]));
  assert.equal(s.amounts, null);
}
""")

    def test_enabled_strength_scales_deposit_within_range(self):
        cases = []
        rng = random.Random(53)
        for i in range(40):
            cases.append(dict(brush=dict(size=rng.randint(2, 20), amount=rng.randint(1, 100), hardness=rng.choice([0, 50, 100]),
                                         influence=rng.randint(0, 255), tool=rng.choice(['paint', 'erase']),
                                         build_up=bool(i % 3 == 0), flow=rng.randint(1, 100),
                                         pressure_size=bool(i % 2), pressure_amount=True,
                                         pressure_min_size=rng.choice([0, 30, 100])),
                              before=rng.randrange(256),
                              path=[[rng.uniform(10, 110), rng.uniform(10, 110), rng.randrange(65536)] for _ in range(5)]))
        run_node(r"""
for (const code of [6554, 32768, 65535]) {  // Constant pressure: Amount itself is scaled.
  const s = make({amount: 80, pressure_size: false, pressure_amount: true}, [[50, 50, code], [70, 60, code]]);
  eq(s.result(), stroked({amount: engine.scaledControl(80, code)}, [[50, 50], [70, 60]]));
}
const sum = r => r.reduce((a, v) => a + v, 0);
let last = -1;
for (const code of [1, 6554, 26214, 45875, 65535]) {
  const total = sum(make({hardness: 0, pressure_size: false, pressure_amount: true}, [[30, 64, code], [100, 64, code]]).result());
  assert.ok(total > last, `code ${code}`); last = total;
}
for (const c of data) {
  const before = new Uint8Array(16384).fill(c.before);
  const result = make(c.brush, c.path, before).result(), target = c.brush.tool === 'erase' ? 0 : c.brush.influence;
  for (let i = 0; i < result.length; i++) {
    const v = result[i];
    assert.ok(Number.isInteger(v) && v >= 0 && v <= 255, `cell ${i}: ${v}`);
    assert.ok(v >= Math.min(c.before, target) && v <= Math.max(c.before, target), `cell ${i} overshoots`);
  }
}
""", cases)

    def test_editor_strength_fallback(self):
        run_editor(r"""
press('Use Pen Pressure'); press('Size'); press('Amount'); type('Amount (%)', 90);
click(40, 40, {pointerType: 'pen', pressure: 0.25});
eq(session().codes, stroked({...engineBrush(), amount: engine.scaledControl(90, engine.pressureCode(0.25))}, [[40, 40]]));
press('Undo'); click(40, 40, {pointerType: 'mouse', pressure: 0.25});
eq(session().codes, stroked(engineBrush(), [[40, 40]]));
""")


class SmoothingTests(unittest.TestCase):
    def test_matches_independent_oracle(self):
        rng = random.Random(11)
        cases = []
        for smoothing in [0, 1, 13, 50, 100]:
            path = [[rng.uniform(10, 110), rng.uniform(10, 110), rng.randrange(65536)]]
            for _ in range(30):
                x, y, p = path[-1]
                if rng.random() < 0.15:
                    path.append([x, y, rng.randrange(65536)])  # At rest, pressure changes.
                else:
                    path.append([x + rng.uniform(-3, 3), y + rng.uniform(-3, 3), rng.randrange(65536)])
            cases.append(dict(smoothing=smoothing, path=path, expected=smooth_oracle(path, smoothing)))
            plain = [[x, y, None] for x, y, _ in path]
            cases.append(dict(smoothing=smoothing, path=plain, expected=smooth_oracle(plain, smoothing)))
        run_node(r"""
for (const c of data) assert.deepEqual(smoothed(c.smoothing, c.path), c.expected, `smoothing ${c.smoothing}`);
for (const bad of [-1, 101, 2.5, '10', null]) assert.throws(() => new smoothing.StrokeSmoother(bad, 0, 0, null, () => {}), /Invalid smoothing/);
""", cases)

    def test_zero_smoothing_is_the_raw_path(self):
        run_editor(r"""
const path = [[20, 30], [24.5, 31], [24.5, 31], [40, 52.25], [41, 52], [70, 40]];
assert.deepEqual(smoothed(0, path), path.slice(1).map(p => [...p, null]));
// Coalesced pointer samples reach the stroke exactly as before.
const events = path.slice(1).map(([x, y]) => ({clientX: 8 + x * 4, clientY: 8 + y * 4}));
pointer('pointerdown', ...path[0]); pointer('pointermove', 70, 40, {getCoalescedEvents: () => events.slice(0, -1)});
pointer('pointerup', 70, 40); dom.flush();
eq(session().codes, stroked(engineBrush(), [...path, [70, 40], [70, 40]]));
assert.equal(settings().smoothing, 0);
""")

    def test_smoothing_reduces_jitter(self):
        run_node(r"""
const rms = s => { const p = smoothed(s, data).filter(([x]) => x > 30 && x < 100);
  return Math.sqrt(p.reduce((a, [, y]) => a + (y - 64) ** 2, 0) / p.length); };
const raw = rms(0), light = rms(10), medium = rms(30), heavy = rms(60);
assert.ok(raw > 0.3, raw); assert.ok(light < raw * 0.6, light); assert.ok(medium < light, medium); assert.ok(heavy < medium, heavy);
assert.ok(medium < raw / 2.5, medium);
// The deposited line is straighter: with the path centred on row 64, far fewer cells leave that row.
const strayCells = s => { const centred = data.map(([x, y]) => [x, y + 0.5]);
  const st = new engine.Stroke(empty(), 128, 128, {...brush, size: 1}, ...centred[0]);
  const sm = new smoothing.StrokeSmoother(s, ...centred[0], null, (x, y) => st.add(x, y));
  for (const p of centred.slice(1)) sm.add(...p); sm.finish();
  const r = st.result(); return [...r.keys()].filter(i => r[i] && i >> 7 !== 64).length; };
const rawStray = strayCells(0), smoothStray = strayCells(30);
assert.ok(rawStray > 40 && smoothStray * 3 < rawStray, `${smoothStray} vs ${rawStray}`);
""", jitter_path())

    def test_endpoints_and_lag_are_bounded(self):
        run_node(r"""
for (const s of [1, 25, 50, 100]) {
  const out = smoothed(s, data);
  assert.deepEqual(out.at(-1), [...data.at(-1).slice(0, 2), null]);  // The stroke ends at the release point.
  const reach = s * smoothing.SMOOTHING_REACH / 100;
  // Along a straight line the follower trails by less than its reach; it starts at the press point.
  const sm = new smoothing.StrokeSmoother(s, 10, 64, null, () => {});
  for (let x = 11; x <= 110; x++) { sm.add(x, 64); assert.ok(x - sm.point[0] <= reach + 1e-9 && sm.point[0] < x, `${s} at ${x}`); }
  assert.ok(Math.hypot(out[0][0] - data[0][0], out[0][1] - data[0][1]) < 0.3, 'start');
}
// A pointer at rest emits nothing, and an unmoved stroke emits nothing on release.
const quiet = []; const sm = new smoothing.StrokeSmoother(40, 50, 50, null, (...p) => quiet.push(p));
for (let i = 0; i < 100; i++) sm.add(50, 50); sm.finish(); assert.equal(quiet.length, 0);
""", jitter_path())

    def test_deterministic_and_insensitive_to_event_density(self):
        run_editor(r"""
const dragPath = (path, extra = {}) => {
  pointer('pointerdown', ...path[0], extra);
  for (const p of path.slice(1, -1)) pointer('pointermove', ...p, extra);
  pointer('pointerup', ...path.at(-1)); dom.flush(); return session().codes.slice();
};
const line = n => Array.from({length: n + 1}, (_, k) => [10 + 90 * k / n, 20 + 60 * k / n]);
type('Smoothing (%)', 40); type('Hardness (%)', 0);
const first = dragPath(data); press('Clear'); const second = dragPath(data); eq(second, first, 'repeat');
await reopen(empty(), {size: 16, hardness: 0, smoothing: 40}); eq(dragPath(data), first, 'reopened');
for (const s of [25, 50, 100]) {
  await reopen(empty(), {size: 6, hardness: 0, smoothing: s});
  const sparse = dragPath(line(2)); press('Clear'); const dense = dragPath(line(60));
  let cells = 0; for (let i = 0; i < 16384; i++) { assert.ok(Math.abs(sparse[i] - dense[i]) <= 1); cells += sparse[i] !== dense[i]; }
  assert.ok(cells <= 64, `${s}: ${cells} cells differ`);
}
// The smoothed path is what was painted, and a Shift-click line starts from the release point.
await reopen(empty(), {size: 4, smoothing: 50});
const codes = dragPath(data), st = new engine.Stroke(empty(), 128, 128, engineBrush(), ...data[0]);
const sm = new smoothing.StrokeSmoother(50, ...data[0], null, (x, y) => st.add(x, y));
for (const p of data.slice(1)) sm.add(...p); sm.add(...data.at(-1)); sm.finish(); eq(codes, st.result());
const end = data.at(-1); click(end[0], 100, {shiftKey: true});
eq(session().codes, stroked(engineBrush(), [end, [end[0], 100]]).map((v, i) => Math.max(v, codes[i])), 'line');
""", [[x, y] for x, y, _ in jitter_path(count=120)])

    def test_pen_pressure_is_carried_through_smoothing(self):
        run_editor(r"""
press('Use Pen Pressure'); press('Amount'); type('Smoothing (%)', 30);
const pen = p => ({pointerType: 'pen', pressure: p});
pointer('pointerdown', 20, 64, pen(0.2)); pointer('pointermove', 60, 64, pen(1)); pointer('pointermove', 90, 64, pen(0.5));
pointer('pointerup', 90, 64, pen(0)); dom.flush();
const s = new engine.PressureStroke(empty(), 128, 128, engineBrush(), 20, 64, empty(), null, engine.pressureCode(0.2));
const sm = new smoothing.StrokeSmoother(30, 20, 64, engine.pressureCode(0.2), (x, y, p) => s.add(x, y, p));
sm.add(60, 64, engine.pressureCode(1)); sm.add(90, 64, engine.pressureCode(0.5)); sm.add(90, 64, s.pressure); sm.finish();
eq(session().codes, s.result()); assert.ok(session().codes[64 * 128 + 89] > 0, 'end reached');
""")


class DynamicsSettingsTests(unittest.TestCase):
    def test_controls_visibility_badges_and_reset(self):
        run_editor(r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'range').length, 0);
const smooth = input('Smoothing (%)'), minimum = input('Minimum Size (% of Size)');
assert.equal(smooth.value, '0'); assert.equal(minimum.value, '0');
assert.equal(smooth.parent.parent, heading('Brush Behavior').parent);
assert.equal(minimum.parent.parent, heading('Pen Pressure').parent);
assert.equal(heading('Brush Behavior').parent.children.at(-1), heading('Pen Pressure').parent);
assert.equal(minimum.parent.hidden, true);
press('Use Pen Pressure'); assert.equal(minimum.parent.hidden, false);
press('Size'); assert.equal(minimum.parent.hidden, true); press('Size');
assert.equal(button('Reset Brush').hidden, false); press('Use Pen Pressure'); assert.equal(button('Reset Brush').hidden, true);
type('Smoothing (%)', 35); assert.equal(settings().smoothing, 35);
assert.ok(summary().textContent.includes('Smoothing 35%')); assert.equal(button('Reset Brush').hidden, false);
type('Smoothing (%)', 250); assert.equal(settings().smoothing, 100);
press('Use Pen Pressure'); type('Minimum Size (% of Size)', 40);
assert.equal(heading('Pen Pressure').textContent, 'Pen Pressure · Size ≥ 40%');
assert.ok(summary().textContent.includes('Pen Pressure (Size ≥ 40%)'));
press('Reset Brush'); assert.equal(settings().smoothing, 0); assert.equal(settings().pressure_min_size, 0);
assert.ok(!summary().textContent.includes('Smoothing'));
""")

    def test_sparse_storage(self):
        run_editor(r"""
const stored = ui.editorSettings(brush);
assert.equal(stored.smoothing, undefined); assert.equal(stored.pressure_min_size, undefined);
const changed = ui.editorSettings({...brush, smoothing: 20, pressure_min_size: 35});
assert.equal(changed.smoothing, 20); assert.equal(changed.pressure_min_size, 35);
for (const bad of [-1, 101, 2.5, '20', true, null])
  for (const key of ['smoothing', 'pressure_min_size']) assert.equal(ui.editorSettings({...brush, [key]: bad})[key], undefined);
await reopen(empty(), {...brush, smoothing: 20, pressure_min_size: 35});
assert.equal(input('Smoothing (%)').value, '20'); press('Done');
assert.equal(result.settings.smoothing, 20); assert.equal(result.settings.pressure_min_size, 35);
await reopen(empty(), {size: 16}); press('Done'); assert.equal(JSON.stringify(result.settings), JSON.stringify(ui.editorSettings({size: 16})));
assert.deepEqual(brushes.PRESSURE_KEYS, lib.PRESSURE_SNAPSHOT_KEYS);
""")


class DynamicsPresetTests(unittest.TestCase):
    def test_capture_writes_only_nondefault_dynamics(self):
        run_node(r"""
const meta = {id: 'p', name: 'P'}, base = {...brush, ...brushes.BRUSH_DEFAULTS};
const plainPreset = await lib.captureBrushPreset(base, meta);
assert.deepEqual(Object.keys(plainPreset.brush), lib.SNAPSHOT_KEYS);  // Defaults: the retained v1 schema exactly.
const smooth = await lib.captureBrushPreset({...base, smoothing: 30}, meta);
assert.equal(smooth.version, 1); assert.equal(smooth.brush.smoothing, 30); assert.equal('pressure_min_size' in smooth.brush, false);
const floor = await lib.captureBrushPreset(full({pressure_min_size: 45}), meta);
assert.equal(floor.version, 2); assert.equal(floor.brush.pressure_min_size, 45); assert.equal('smoothing' in floor.brush, false);
assert.deepEqual(Object.keys(floor.brush).slice(-5), [...lib.PRESSURE_SNAPSHOT_KEYS, 'pressure_min_size']);
const both = await lib.captureBrushPreset({...full({pressure_min_size: 45}), smoothing: 30}, meta);
assert.deepEqual(Object.keys(both.brush).slice(-2), ['smoothing', 'pressure_min_size']);
// Deterministic: identical text from a capture, a re-validation and a reorder of the source keys.
const text = JSON.stringify(both);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(text))), text);
const shuffled = Object.fromEntries(Object.entries({...full({pressure_min_size: 45}), smoothing: 30}).reverse());
assert.equal(JSON.stringify(await lib.captureBrushPreset(shuffled, meta)), text);
""")

    def test_old_presets_load_and_new_ones_round_trip(self):
        run_editor(r"""
const meta = {id: 'p', name: 'P'};
const old = await lib.captureBrushPreset({...brush, size: 9}, meta), oldPen = await lib.captureBrushPreset(full({size: 9}), meta);
for (const preset of [old, oldPen]) {  // Presets from before dynamics keys: unchanged text, still valid.
  const text = JSON.stringify(preset);
  assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(text))), text);
  Object.assign(session().settings, {smoothing: 40, pressure_min_size: 60});
  await lib.applyBrushPreset(JSON.parse(text), session());
  assert.equal(settings().smoothing, 0); assert.equal(settings().pressure_min_size, 0); assert.equal(settings().size, 9);
}
const saved = await lib.captureBrushPreset({...full({size: 9, pressure_min_size: 45}), smoothing: 30}, meta);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(saved)), session()); pointer('pointermove', 1, 1); dom.flush();
assert.equal(settings().smoothing, 30); assert.equal(settings().pressure_min_size, 45);
assert.equal(input('Smoothing (%)').value, '30'); assert.equal(input('Minimum Size (% of Size)').value, '45');
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(saved));
// The live brush paints with the loaded values: Minimum Size holds a light pen stamp at 45% of 9 cells.
click(40, 40, {pointerType: 'pen', pressure: 0.1});
eq(session().codes, stroked({...engineBrush(), size: 4}, [[40, 40]]));
// A library save and reload keeps both keys.
let text = null; const library = lib.createBrushLibrary({read: async () => text, write: async v => { text = v; }}, () => 'x');
await library.save(settings(), 'Dyn'); const loaded = (await library.load()).presets[0];
assert.equal(loaded.brush.smoothing, 30); assert.equal(loaded.brush.pressure_min_size, 45);
""")

    def test_invalid_dynamics_values_are_rejected(self):
        run_node(r"""
const preset = await lib.captureBrushPreset({...brush}, {id: 'p', name: 'P'});
for (const key of ['smoothing', 'pressure_min_size'])
  for (const bad of [-1, 101, 2.5, '20', true, null])
    await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, [key]: bad}}), new RegExp('Invalid brush ' + key));
// An explicit in-range value is accepted as written.
assert.equal((await lib.validateBrushPreset({...preset, brush: {...preset.brush, smoothing: 0}})).brush.smoothing, 0);
""")


def jitter_offset(rng, x0, y0, k):
    return ProceduralOracle.hash([0x414E474C, x0 & 0xFFFFFFFF, y0 & 0xFFFFFFFF, k]) * (2 * rng + 1) // 2**32 - rng


JITTER = r"""
const square = {size: 12, shape: 'square', spacing: 'custom', spacing_percent: 150};
const jittered = (b, path) => { const s = new angles.JitterStroke(empty(), 128, 128, {...brush, ...b}, ...path[0]);
  for (const p of path.slice(1)) s.add(...p); return s; };
// Independent of the jitter strokes: each stamp painted alone at its turned Rotation, then combined by maximum.
const perStamp = (b, path, range) => {
  const {stamps: at} = stamps(b, path), out = empty(), x0 = Math.round(path[0][0] * 256), y0 = Math.round(path[0][1] * 256);
  at.forEach(([x, y], k) => {
    const turned = angles.jitteredRotation(b.rotation_degrees ?? 0, angles.jitterOffset(range, x0, y0, k));
    const r = stroked({...b, rotation_degrees: turned}, [[x, y]]);
    for (let i = 0; i < r.length; i++) out[i] = Math.max(out[i], r[i]);
  });
  return out;
};
const dragLine = path => { pointer('pointerdown', ...path[0]); for (const p of path.slice(1)) pointer('pointermove', ...p);
  pointer('pointerup', ...path.at(-1)); dom.flush(); };
"""


class AngleJitterTests(unittest.TestCase):
    def test_offsets_match_oracle_stay_in_bounds_and_are_symmetric(self):
        samples = [[rng, x0, y0, k, jitter_offset(rng, x0, y0, k)]
                   for rng in [0, 1, 7, 45, 180] for x0, y0 in [(0, 0), (2560, 16384), (-256, 32767)]
                   for k in range(0, 400, 7)]
        run_node(r"""
for (const [r, x0, y0, k, expected] of data) assert.equal(angles.jitterOffset(r, x0, y0, k), expected);
for (const r of [0, 1, 7, 45, 180]) for (let k = 0; k < 20000; k++) {
  const o = angles.jitterOffset(r, 5000, 9000, k); assert.ok(Number.isInteger(o) && o >= -r && o <= r, `${r}: ${o}`);
}
// Uniform over the 2N+1 whole degrees, so symmetric about Rotation.
const counts = new Map(); let sum = 0; const n = 210000;
for (let k = 0; k < n; k++) { const o = angles.jitterOffset(10, 1234, 5678, k); counts.set(o, (counts.get(o) ?? 0) + 1); sum += o; }
assert.equal(counts.size, 21); for (const c of counts.values()) assert.ok(Math.abs(c - n / 21) < 0.04 * n / 21, c);
assert.ok(Math.abs(sum / n) < 0.05, sum / n);
for (const [base, off, turned] of [[0, -180, -180], [359.9, 5, 359.9 + 5 - 360], [-350, -20, -350 - 20 + 360], [350, 180, 170], [-90, 90, 0]])
  assert.equal(angles.jitteredRotation(base, off), turned);
""", samples)

    def test_zero_and_round_disks_keep_prior_behavior(self):
        run_editor(JITTER + r"""
assert.equal(angles.angleJitterActive({...brush, ...square}), false);
for (const b of [{}, {angle_jitter: 90}, {angle_jitter: 90, hardness: 0}, {angle_jitter: 90, value_profile: 'radial'}])
  assert.equal(angles.angleJitterActive({...brush, ...b}), false, JSON.stringify(b));
for (const b of [{shape: 'square'}, {shape: 'diamond'}, {scale_x: 2}, {crop_left: 10}, {value_profile: 'linear'},
  {value_profile: 'radial', gradient_center_x: 30}, {value_profile: 'radial', gradient_aspect_y: 2}])
  assert.equal(angles.angleJitterActive({...brush, angle_jitter: 5, ...b}), true, JSON.stringify(b));
// Editor: a round Disk with jitter paints exactly as without; a Square at 0 paints exactly as before.
const path = [[20, 30], [90, 60]];
await reopen(empty(), {size: 12, angle_jitter: 120}); dragLine(path); eq(session().codes, stroked(engineBrush(), [...path, path[1]]));
await reopen(empty(), {...square}); dragLine(path); eq(session().codes, stroked(engineBrush(), [...path, path[1]]));
""")

    def test_jitter_turns_each_stamp_within_bounds(self):
        run_node(JITTER + r"""
const path = [[20, 30], [100, 30], [100, 90]];
for (const b of [{...square, angle_jitter: 45}, {...square, angle_jitter: 180, rotation_degrees: 30, hardness: 40},
  {...square, shape: 'diamond', scale_x: 2, angle_jitter: 20, rotation_degrees: -15.5}]) {
  const result = jittered(b, path).result(), unturned = stroked(b, path);
  eq(result, perStamp(b, path, b.angle_jitter));
  assert.ok(result.some((v, i) => v !== unturned[i]), 'orientation changed');
}
// Hard stamps snapped to the same cell repeat only when their angle differs.
const tight = {...square, angle_jitter: 45, spacing_percent: 1, size: 9}, still = [[64.05, 64], [64.45, 64]];
assert.ok(stamps(tight, still).stamps.length >= 4);
const expected = perStamp(tight, still, 45);
eq(jittered(tight, still).result(), expected);
const pen = new angles.JitterPressureStroke(empty(), 128, 128, full(tight), 64.05, 64, empty(), null, 65535);
pen.add(64.45, 64, 65535); eq(pen.result(), expected, 'pressure');
""")

    def test_deterministic_and_independent_of_event_density(self):
        run_node(JITTER + r"""
const b = {...square, angle_jitter: 60, hardness: 50}, path = [[10, 10], [40, 10], [40, 50], [70, 80]];
const dense = [path[0]];
for (let j = 0; j < 3; j++) for (let k = 1; k <= 29; k++)
  dense.push([path[j][0] + (path[j + 1][0] - path[j][0]) * k / 29, path[j][1] + (path[j + 1][1] - path[j][1]) * k / 29]);
const a = jittered(b, path), again = jittered(b, path), slow = jittered(b, dense);
eq(again.result(), a.result()); eq(slow.result(), a.result()); assert.equal(slow.jitter.k, a.jitter.k);
// Pressure strokes draw the same offsets: at full pressure they match the plain jitter stroke.
const p = new angles.JitterPressureStroke(empty(), 128, 128, full(b), 10, 10, empty(), null, 65535);
for (const q of path.slice(1)) p.add(...q, 65535);
eq(p.result(), a.result()); assert.equal(p.jitter.k, a.jitter.k);
""")

    def test_editor_settings_presets_and_reset(self):
        run_editor(r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
const control = input('Angle Jitter (±°)');
assert.equal(control.parent.parent, heading('Brush Shape').parent); assert.equal(control.value, '0');
assert.equal(ui.editorSettings(brush).angle_jitter, undefined);
for (const bad of [-1, 181, 2.5, '9', true]) assert.equal(ui.editorSettings({...brush, angle_jitter: bad}).angle_jitter, undefined);
pressIn(heading('Brush Shape').parent, 'Square'); type('Angle Jitter (±°)', 30); assert.equal(settings().angle_jitter, 30);
assert.ok(summary().textContent.includes('Angle Jitter ±30°'));
// The editor paints the jittered stroke.
pointer('pointerdown', 20, 40); pointer('pointermove', 90, 40); pointer('pointerup', 90, 40); dom.flush();
const replay = new angles.JitterStroke(empty(), 128, 128, engineBrush(), 20, 40); replay.add(90, 40); replay.add(90, 40);
eq(session().codes, replay.result());
press('Done'); assert.equal(result.settings.angle_jitter, 30);
await reopen(empty(), result.settings); assert.equal(settings().angle_jitter, 30);
// Presets: optional key, written only when not 0; old presets unchanged; bad values rejected.
const meta = {id: 'p', name: 'P'};
const preset = await lib.captureBrushPreset(settings(), meta);
assert.equal(preset.version, 1); assert.equal(preset.brush.angle_jitter, 30);
const old = await lib.captureBrushPreset({...brush, shape: 'square'}, meta);
assert.equal('angle_jitter' in old.brush, false); assert.deepEqual(Object.keys(old.brush), lib.SNAPSHOT_KEYS);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(JSON.stringify(old)))), JSON.stringify(old));
await lib.applyBrushPreset(old, session()); assert.equal(settings().angle_jitter, 0);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(preset)), session()); assert.equal(settings().angle_jitter, 30);
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(preset));
for (const bad of [-1, 181, 2.5, '9', null])
  await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, angle_jitter: bad}}), /Invalid brush angle_jitter/);
pointer('pointermove', 1, 1); dom.flush(); press('Reset Brush'); assert.equal(settings().angle_jitter, 0);
""")

def size_offset(rng, x0, y0, k):
    return ProceduralOracle.hash([0x53495A45, x0 & 0xFFFFFFFF, y0 & 0xFFFFFFFF, k]) * (2 * rng + 1) // 2**32 - rng


SIZED = JITTER + r"""
// Independent of the jitter strokes: each stamp painted alone at its jittered size and Rotation,
// then combined by maximum. base is the unjittered stamp size (pressure and Minimum Size applied).
const bothStamps = (b, path, base = b.size) => {
  const {stamps: at} = stamps({...b, size: base}, path), out = empty();
  const x0 = Math.round(path[0][0] * 256), y0 = Math.round(path[0][1] * 256);
  const turns = angles.angleJitterActive({...brush, ...b}) ? b.angle_jitter ?? 0 : 0;
  at.forEach(([x, y], k) => {
    const size = Math.max(1, Math.floor((base * (100 + angles.sizeJitterOffset(b.size_jitter, x0, y0, k)) + 50) / 100));
    const r = stroked({...b, size, rotation_degrees: angles.jitteredRotation(b.rotation_degrees ?? 0, angles.jitterOffset(turns, x0, y0, k))}, [[x, y]]);
    for (let i = 0; i < r.length; i++) out[i] = Math.max(out[i], r[i]);
  });
  return out;
};
"""


class SizeJitterTests(unittest.TestCase):
    def test_offsets_and_sizes_match_oracle_and_bounds(self):
        samples = [[rng, x0, y0, k, size_offset(rng, x0, y0, k)]
                   for rng in [0, 1, 20, 100] for x0, y0 in [(0, 0), (2560, 16384), (-256, 32767)]
                   for k in range(0, 400, 7)]
        sizes = [[max(1, (b * (100 + p) + 50) // 100) for p in range(-100, 101)] for b in range(1, 129)]
        run_node(r"""
for (const [r, x0, y0, k, expected] of data.samples) assert.equal(angles.sizeJitterOffset(r, x0, y0, k), expected);
for (let b = 1; b <= 128; b++) for (let p = -100; p <= 100; p++) {
  const s = angles.jitteredSize(b, p); assert.equal(s, data.sizes[b - 1][p + 100]);
  assert.ok(s >= 1 && s >= Math.floor(b * (100 - Math.abs(p)) / 100) && s <= Math.ceil(b * (100 + Math.abs(p)) / 100), `${b} ${p}`);
}
for (const r of [0, 1, 20, 100]) for (let k = 0; k < 20000; k++) {
  const o = angles.sizeJitterOffset(r, 5000, 9000, k); assert.ok(Number.isInteger(o) && o >= -r && o <= r);
}
const counts = new Map(); let sum = 0; const n = 210000;
for (let k = 0; k < n; k++) { const o = angles.sizeJitterOffset(10, 1234, 5678, k); counts.set(o, (counts.get(o) ?? 0) + 1); sum += o; }
assert.equal(counts.size, 21); for (const c of counts.values()) assert.ok(Math.abs(c - n / 21) < 0.04 * n / 21, c);
assert.ok(Math.abs(sum / n) < 0.05, sum / n);
// Its own channel: the size sequence is not the angle sequence.
let same = 0; for (let k = 0; k < 1000; k++) same += angles.sizeJitterOffset(45, 777, 888, k) === angles.jitterOffset(45, 777, 888, k);
assert.ok(same < 60, same);
""", dict(samples=samples, sizes=sizes))

    def test_zero_keeps_prior_behavior_and_round_disks_resize(self):
        run_editor(SIZED + r"""
assert.equal(angles.stampJitterActive({...brush, ...square}), false);
assert.equal(angles.stampJitterActive({...brush, angle_jitter: 90}), false);
assert.equal(angles.stampJitterActive({...brush, size_jitter: 10}), true);
const path = [[20, 30], [90, 60]];
await reopen(empty(), {...square, angle_jitter: 0, size_jitter: 0}); dragLine(path); eq(session().codes, stroked(engineBrush(), [...path, path[1]]));
// A round Disk ignores Angle Jitter but takes Size Jitter.
const disk = {size: 10, spacing: 'custom', spacing_percent: 150, size_jitter: 40, angle_jitter: 90};
const diskStroke = jittered(disk, path), r = diskStroke.result();
assert.ok([...diskStroke.jitter.footprints.keys()].every(k => k.endsWith(' 0')), 'disk not turned');
eq(r, bothStamps(disk, path)); assert.ok(r.some((v, i) => v !== stroked(disk, path)[i]), 'sizes changed');
""")

    def test_jitter_resizes_each_stamp_independently_of_angle(self):
        run_node(SIZED + r"""
const path = [[20, 30], [100, 30], [100, 90]];
for (const b of [{...square, size_jitter: 30}, {...square, size_jitter: 30, angle_jitter: 45},
  {...square, size_jitter: 100, angle_jitter: 180, rotation_degrees: 30, hardness: 40}, {...square, size: 2, size_jitter: 100}]) {
  const result = jittered(b, path).result();
  eq(result, bothStamps(b, path), JSON.stringify(b));
}
// Changing Angle Jitter leaves the size sequence, and changing Size Jitter leaves the angles.
eq(jittered({...square, angle_jitter: 45}, path).result(), bothStamps({...square, angle_jitter: 45, size_jitter: 0}, path), 'angles');
// A gradient's profile scales with each stamp's size: one stamp equals a plain stamp at the jittered size.
for (const b of [{...square, size_jitter: 60, value_profile: 'linear'}, {...square, size_jitter: 60, value_profile: 'radial', gradient_inner: 20}]) {
  const x0 = 64 * 256, y0 = 64 * 256, size = angles.jitteredSize(12, angles.sizeJitterOffset(60, x0, y0, 0));
  assert.notEqual(size, 12, 'fixture stamp is resized');
  eq(jittered(b, [[64, 64]]).result(), stroked({...b, size}, [[64, 64]]), b.value_profile);
}
""")

    def test_pressure_size_is_the_base_and_minimum_holds(self):
        run_node(SIZED + r"""
const path = [[20, 40], [100, 40]];
for (const [code, minimum] of [[65535, 0], [19661, 0], [6554, 50], [1, 50]]) {
  const b = {...square, size: 24, size_jitter: 50, pressure_min_size: minimum};
  const p = new angles.JitterPressureStroke(empty(), 128, 128, full(b), ...path[0], empty(), null, code);
  p.add(...path[1], code);
  const base = p.sizeAt(code);
  assert.equal(base, Math.max(engine.pressureMinSize(24, minimum), engine.scaledControl(24, code)));
  eq(p.result(), bothStamps(b, path, base), `${code} ${minimum}`);
}
""")

    def test_deterministic_and_independent_of_event_density(self):
        run_node(SIZED + r"""
const b = {...square, size_jitter: 45, angle_jitter: 30, hardness: 50}, path = [[10, 10], [40, 10], [40, 50], [70, 80]];
const dense = [path[0]];
for (let j = 0; j < 3; j++) for (let k = 1; k <= 23; k++)
  dense.push([path[j][0] + (path[j + 1][0] - path[j][0]) * k / 23, path[j][1] + (path[j + 1][1] - path[j][1]) * k / 23]);
const a = jittered(b, path);
eq(jittered(b, path).result(), a.result()); const slow = jittered(b, dense);
eq(slow.result(), a.result()); assert.equal(slow.jitter.k, a.jitter.k);
assert.deepEqual([...slow.jitter.footprints.keys()], [...a.jitter.footprints.keys()]);
""")

    def test_editor_settings_presets_and_reset(self):
        run_editor(r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
const control = input('Size Jitter (%)'), shapeGroup = heading('Brush Shape').parent;
assert.equal(control.parent.parent, shapeGroup); assert.equal(control.value, '0');
const rows = shapeGroup.children;
assert.equal(rows.indexOf(control.parent), rows.indexOf(input('Angle Jitter (±°)').parent) + 1);
assert.equal(ui.editorSettings(brush).size_jitter, undefined);
for (const bad of [-1, 101, 2.5, '9', true]) assert.equal(ui.editorSettings({...brush, size_jitter: bad}).size_jitter, undefined);
type('Size Jitter (%)', 25); assert.equal(settings().size_jitter, 25);
assert.ok(summary().textContent.includes('Size Jitter ±25%'));
pointer('pointerdown', 20, 40); pointer('pointermove', 90, 40); pointer('pointerup', 90, 40); dom.flush();
const replay = new angles.JitterStroke(empty(), 128, 128, engineBrush(), 20, 40); replay.add(90, 40); replay.add(90, 40);
eq(session().codes, replay.result());
press('Done'); assert.equal(result.settings.size_jitter, 25);
await reopen(empty(), result.settings); assert.equal(settings().size_jitter, 25);
const meta = {id: 'p', name: 'P'};
const preset = await lib.captureBrushPreset(settings(), meta);
assert.equal(preset.version, 1); assert.equal(preset.brush.size_jitter, 25);
const old = await lib.captureBrushPreset({...brush}, meta);
assert.equal('size_jitter' in old.brush, false); assert.deepEqual(Object.keys(old.brush), lib.SNAPSHOT_KEYS);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(JSON.stringify(old)))), JSON.stringify(old));
await lib.applyBrushPreset(old, session()); assert.equal(settings().size_jitter, 0);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(preset)), session()); assert.equal(settings().size_jitter, 25);
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(preset));
for (const bad of [-1, 101, 2.5, '9', null])
  await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, size_jitter: bad}}), /Invalid brush size_jitter/);
pointer('pointermove', 1, 1); dom.flush(); press('Reset Brush'); assert.equal(settings().size_jitter, 0);
""")

def amount_offset(rng, x0, y0, k):
    return ProceduralOracle.hash([0x414D4E54, x0 & 0xFFFFFFFF, y0 & 0xFFFFFFFF, k]) * (2 * rng + 1) // 2**32 - rng


AMOUNTS = SIZED + r"""
// Independent of the jitter strokes: each stamp painted alone with its jittered size, Rotation and
// Amount; stamps here never overlap, so the field combines them by maximum (Paint) or minimum (Erase).
// base is the unjittered stamp size and amountBase(k) its Amount before jitter.
const allStamps = (b, path, {base = b.size, amountBase = () => b.amount ?? 100, before = empty(), combine = Math.max} = {}) => {
  const {stamps: at} = stamps({...b, size: base}, path), out = before.slice();
  const x0 = Math.round(path[0][0] * 256), y0 = Math.round(path[0][1] * 256);
  const turns = angles.angleJitterActive({...brush, ...b}) ? b.angle_jitter ?? 0 : 0, seed = b.jitter_seed ?? 0;
  at.forEach(([x, y], k) => {
    const size = angles.jitteredSize(base, angles.sizeJitterOffset(b.size_jitter ?? 0, x0, y0, k, seed));
    const amount = Math.min(100, Math.max(1, Math.floor((amountBase(k) * (100 + angles.amountJitterOffset(b.amount_jitter ?? 0, x0, y0, k, seed)) + 50) / 100)));
    const one = new engine.Stroke(before.slice(), 128, 128, {...brush, ...b, size, amount,
      rotation_degrees: angles.jitteredRotation(b.rotation_degrees ?? 0, angles.jitterOffset(turns, x0, y0, k, seed))}, x, y).result();
    for (let i = 0; i < one.length; i++) if (one[i] !== before[i]) out[i] = combine(out[i], one[i]);
  });
  return out;
};
const mouse = (b, path, before = empty()) => { const s = new angles.JitterPressureStroke(before, 128, 128, {...brush, ...b}, ...path[0], empty(), null, null);
  for (const p of path.slice(1)) s.add(...p); return s; };
const apart = {...square, size: 8, spacing_percent: 300};
"""


class AmountJitterTests(unittest.TestCase):
    def test_offsets_and_amounts_match_oracle_and_bounds(self):
        samples = [[rng, x0, y0, k, amount_offset(rng, x0, y0, k)]
                   for rng in [0, 1, 20, 100] for x0, y0 in [(0, 0), (2560, 16384), (-256, 32767)]
                   for k in range(0, 400, 7)]
        amounts = [[min(100, max(1, (a * (100 + p) + 50) // 100)) for p in range(-100, 101)] for a in range(1, 101)]
        run_node(r"""
for (const [r, x0, y0, k, expected] of data.samples) assert.equal(angles.amountJitterOffset(r, x0, y0, k), expected);
for (let a = 1; a <= 100; a++) for (let p = -100; p <= 100; p++) {
  const v = angles.jitteredAmount(a, p); assert.equal(v, data.amounts[a - 1][p + 100]); assert.ok(Number.isInteger(v) && v >= 1 && v <= 100);
}
const counts = new Map(); let sum = 0; const n = 210000;
for (let k = 0; k < n; k++) { const o = angles.amountJitterOffset(10, 1234, 5678, k); counts.set(o, (counts.get(o) ?? 0) + 1); sum += o; }
assert.equal(counts.size, 21); for (const c of counts.values()) assert.ok(Math.abs(c - n / 21) < 0.04 * n / 21, c);
assert.ok(Math.abs(sum / n) < 0.05, sum / n);
for (const other of [angles.jitterOffset, angles.sizeJitterOffset]) {
  let same = 0; for (let k = 0; k < 1000; k++) same += angles.amountJitterOffset(45, 777, 888, k) === other(45, 777, 888, k);
  assert.ok(same < 60, same);
}
""", dict(samples=samples, amounts=amounts))

    def test_zero_keeps_prior_behavior(self):
        run_editor(AMOUNTS + r"""
// Pressure strokes at Amount Jitter 0 paint exactly as before, with or without pressure Amount.
const path = [[20, 30, 5000], [70, 40, 60000], [90, 90, 20000]];
for (const b of [{}, {pressure_amount: true}, {pressure_amount: true, build_up: true, flow: 30, hardness: 20}]) {
  const p = new angles.JitterPressureStroke(empty(), 128, 128, full({...b, size_jitter: 10}), ...path[0].slice(0, 2), empty(), null, path[0][2]);
  for (const q of path.slice(1)) p.add(...q);
  const s = new angles.JitterPressureStroke(empty(), 128, 128, full({...b, size_jitter: 10, amount_jitter: 0}), ...path[0].slice(0, 2), empty(), null, path[0][2]);
  for (const q of path.slice(1)) s.add(...q);
  eq(p.result(), s.result()); eq(p.coverage, s.coverage, 'coverage');
}
await reopen(empty(), {...square, amount: 60}); dragLine([[20, 30], [90, 60]]);
eq(session().codes, stroked(engineBrush(), [[20, 30], [90, 60], [90, 60]]));
""")

    def test_jitter_changes_each_stamp_amount_in_every_mode(self):
        run_node(AMOUNTS + r"""
const path = [[10, 20], [110, 20], [110, 100]], full255 = new Uint8Array(16384).fill(255), ramp = Uint8Array.from({length: 16384}, (_, i) => i % 256);
for (const b of [{...apart, amount_jitter: 60}, {...apart, amount: 40, amount_jitter: 100, hardness: 30},
  {...apart, amount_jitter: 50, size_jitter: 30, angle_jitter: 45}]) {
  const result = mouse(b, path).result();
  eq(result, allStamps(b, path), JSON.stringify(b));
  assert.ok(result.some((v, i) => v !== stroked(b, path)[i]), 'amounts changed');
  for (const v of result) assert.ok(v >= 0 && v <= 255);
}
// Erase lowers each stamp by its own Amount; Restore moves toward the opening field by it.
const erase = {...apart, tool: 'erase', amount_jitter: 70};
eq(mouse(erase, path, full255).result(), allStamps(erase, path, {before: full255, combine: Math.min}), 'erase');
const restore = {...apart, tool: 'restore', amount_jitter: 70};
const r = new angles.JitterPressureStroke(empty(), 128, 128, {...brush, ...restore}, ...path[0], ramp, null, null);
for (const p of path.slice(1)) r.add(...p);
const {stamps: at} = stamps({...restore, tool: 'paint'}, path), x0 = 10 * 256, y0 = 20 * 256, expected = empty();
at.forEach(([x, y], k) => { const amount = angles.jitteredAmount(100, angles.amountJitterOffset(70, x0, y0, k));
  const one = new engine.Stroke(empty(), 128, 128, {...brush, ...restore, amount}, x, y, ramp).result();
  for (let i = 0; i < one.length; i++) expected[i] = Math.max(expected[i], one[i]); });
eq(r.result(), expected, 'restore');
""")

    def test_pressure_amount_is_the_base(self):
        run_node(AMOUNTS + r"""
const path = [[10, 40], [110, 40]];
for (const [code, mapped] of [[65535, true], [19661, true], [3277, true], [19661, false]]) {
  const b = {...apart, amount: 80, amount_jitter: 40, pressure_size: false, pressure_amount: mapped};
  const p = new angles.JitterPressureStroke(empty(), 128, 128, full(b), ...path[0], empty(), null, code);
  p.add(...path[1], code);
  const base = mapped ? engine.scaledControl(80, code) : 80;
  eq(p.result(), allStamps(b, path, {amountBase: () => base}), `${code} ${mapped}`);
  assert.equal(p.mouse, false);
}
// Pressure size and Minimum Size still set the base size the other jitters use.
const sized = {...apart, size: 16, amount_jitter: 40, size_jitter: 20, pressure_min_size: 50};
const q = new angles.JitterPressureStroke(empty(), 128, 128, full(sized), ...path[0], empty(), null, 3277);
q.add(...path[1], 3277); eq(q.result(), allStamps(sized, path, {base: 8}), 'min size');
""")

    def test_sequences_are_independent_deterministic_and_density_free(self):
        run_node(AMOUNTS + r"""
const path = [[10, 10], [60, 10], [60, 70], [110, 120]];  // Exactly collinear subdivisions on the 1/256 grid.
const keys = s => [...s.jitter.footprints.keys()].join('|');
// Amount Jitter does not move the angle or size sequences, and neither moves Amount's.
const turned = {...apart, angle_jitter: 60, size_jitter: 30};
assert.equal(keys(mouse({...turned, amount_jitter: 80}, path)), keys(jittered(turned, path)));
eq(mouse({...turned, amount_jitter: 80}, path).result(), allStamps({...turned, amount_jitter: 80}, path));
eq(mouse({...apart, amount_jitter: 80}, path).result(), allStamps({...apart, amount_jitter: 80}, path));
const dense = [path[0]];
for (let j = 0; j < 3; j++) for (let k = 1; k <= 19; k++)
  dense.push([path[j][0] + (path[j + 1][0] - path[j][0]) * k / 19, path[j][1] + (path[j + 1][1] - path[j][1]) * k / 19]);
const b = {...apart, amount_jitter: 50, size_jitter: 20, angle_jitter: 30, spacing_percent: 40, hardness: 50};
const a = mouse(b, path);
eq(mouse(b, path).result(), a.result()); const slow = mouse(b, dense);
eq(slow.result(), a.result()); eq(slow.amounts, a.amounts, 'amounts'); assert.equal(slow.jitter.k, a.jitter.k);
""")

    def test_editor_settings_presets_and_reset(self):
        run_editor(AMOUNTS + r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
const control = input('Amount Jitter (%)'), behavior = heading('Brush Behavior').parent;
assert.equal(control.parent.parent, behavior); assert.equal(control.value, '0');
assert.equal(behavior.children.indexOf(control.parent), behavior.children.indexOf(input('Amount (%)').parent) + 1);
assert.equal(behavior.children.at(-1), heading('Pen Pressure').parent);
assert.equal(ui.editorSettings(brush).amount_jitter, undefined);
for (const bad of [-1, 101, 2.5, '9', true]) assert.equal(ui.editorSettings({...brush, amount_jitter: bad}).amount_jitter, undefined);
type('Amount (%)', 60); type('Amount Jitter (%)', 35); assert.equal(settings().amount_jitter, 35);
assert.ok(summary().textContent.includes('Amount Jitter ±35%'));
assert.ok(heading('Brush Behavior').textContent.includes('Amount Jitter ±35%'));
// A mouse drag paints the jittered stroke, shows no pressure, and a Shift-click line works.
pointer('pointerdown', 20, 40, {pressure: 0}); pointer('pointermove', 90, 40, {pressure: 0}); dom.flush();
assert.ok(find('status').textContent.length > 0 && !find('status').textContent.startsWith('pressure')); pointer('pointerup', 90, 40); dom.flush();
const replay = mouse(engineBrush(), [[20, 40], [90, 40], [90, 40]]);
eq(session().codes, replay.result());
click(90, 80, {shiftKey: true}); assert.equal(session().history.undoEntries.length, 2);
eq(session().codes, mouse(engineBrush(), [[90, 40], [90, 80]], replay.result()).result(), 'line');
press('Done'); assert.equal(result.settings.amount_jitter, 35);
await reopen(empty(), result.settings); assert.equal(settings().amount_jitter, 35);
const meta = {id: 'p', name: 'P'};
const preset = await lib.captureBrushPreset(settings(), meta);
assert.equal(preset.version, 1); assert.equal(preset.brush.amount_jitter, 35);
const old = await lib.captureBrushPreset({...brush}, meta);
assert.equal('amount_jitter' in old.brush, false); assert.deepEqual(Object.keys(old.brush), lib.SNAPSHOT_KEYS);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(JSON.stringify(old)))), JSON.stringify(old));
await lib.applyBrushPreset(old, session()); assert.equal(settings().amount_jitter, 0);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(preset)), session()); assert.equal(settings().amount_jitter, 35);
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(preset));
for (const bad of [-1, 101, 2.5, '9', null])
  await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, amount_jitter: bad}}), /Invalid brush amount_jitter/);
pointer('pointermove', 1, 1); dom.flush(); press('Reset Brush'); assert.equal(settings().amount_jitter, 0);
""")

SEED_TAGS = {'angle': 0x414E474C, 'size': 0x53495A45, 'amount': 0x414D4E54}


def seeded_offset(channel, rng, x0, y0, k, seed):
    """Independent of angle_jitter.js: seed 0 hashes the four retained words, any other seed a fifth."""
    words = [SEED_TAGS[channel], x0 & 0xFFFFFFFF, y0 & 0xFFFFFFFF, k] + ([seed] if seed else [])
    return ProceduralOracle.hash(words) * (2 * rng + 1) // 2**32 - rng


SEEDED = AMOUNTS + r"""
const offsets = {angle: angles.jitterOffset, size: angles.sizeJitterOffset, amount: angles.amountJitterOffset};
// Raw stamp positions and pressure codes of a jitter pressure stroke, recorded where the engine slots each stamp.
const slots = (b, path) => {
  const original = engine.PressureStroke.prototype.slot, seen = [];
  engine.PressureStroke.prototype.slot = function(x, y, code) { seen.push([x, y, code]); return original.call(this, x, y, code); };
  try { const s = new angles.JitterPressureStroke(empty(), 128, 128, {...brush, ...b}, path[0][0], path[0][1], empty(), null, path[0][2]);
    for (const p of path.slice(1)) s.add(...p); return {slots: seen, stroke: s}; }
  finally { engine.PressureStroke.prototype.slot = original; }
};
const plainStamps = (b, path) => {
  const original = engine.Stroke.prototype.stamp, seen = [];
  engine.Stroke.prototype.stamp = function(x, y) { seen.push([x, y]); return original.call(this, x, y); };
  try { const s = jittered(b, path); return {stamps: seen, stroke: s}; } finally { engine.Stroke.prototype.stamp = original; }
};
"""


class JitterSeedTests(unittest.TestCase):
    def test_offsets_match_oracle_and_seed_zero_keeps_every_sequence(self):
        retained_oracles = {'angle': jitter_offset, 'size': size_offset, 'amount': amount_offset}
        places = [(0, 0), (2560, 16384), (-256, 32767)]
        samples = [[channel, rng, x0, y0, k, seed, seeded_offset(channel, rng, x0, y0, k, seed)]
                   for channel in SEED_TAGS for rng in [1, 45, 100] for seed in [0, 1, 2, 7919, 4294967295]
                   for x0, y0 in places for k in range(0, 300, 11)]
        retained = [[channel, rng, x0, y0, k, retained_oracles[channel](rng, x0, y0, k)]
                    for channel in SEED_TAGS for rng in [1, 45, 100] for x0, y0 in places for k in range(0, 300, 11)]
        run_node(SEEDED + r"""
for (const [c, r, x0, y0, k, seed, expected] of data.samples) assert.equal(offsets[c](r, x0, y0, k, seed), expected, `${c} ${seed}`);
// Seed 0 and no seed are the retained sequences exactly, on every channel.
for (const [c, r, x0, y0, k, expected] of data.retained) {
  assert.equal(offsets[c](r, x0, y0, k), expected); assert.equal(offsets[c](r, x0, y0, k, 0), expected);
}
const agree = (f, g) => { let n = 0; for (let k = 0; k < 1000; k++) n += f(k) === g(k); return n; };
for (const c of Object.keys(offsets)) {
  // A nonzero seed rerolls the channel, different seeds differ, and each seed stays uniform and in bounds.
  for (const [s, t] of [[0, 1], [0, 4294967295], [1, 2], [7919, 7920]])
    assert.ok(agree(k => offsets[c](45, 777, 888, k, s), k => offsets[c](45, 777, 888, k, t)) < 60, `${c} ${s} ${t}`);
  const counts = new Map(); const n = 105000;
  for (let k = 0; k < n; k++) { const o = offsets[c](10, 1234, 5678, k, 31337); assert.ok(o >= -10 && o <= 10); counts.set(o, (counts.get(o) ?? 0) + 1); }
  assert.equal(counts.size, 21); for (const v of counts.values()) assert.ok(Math.abs(v - n / 21) < 0.05 * n / 21, v);
}
// Under one seed the three channels stay independent.
for (const seed of [1, 7919, 4294967295]) for (const [a, b] of [['angle', 'size'], ['angle', 'amount'], ['size', 'amount']])
  assert.ok(agree(k => offsets[a](45, 777, 888, k, seed), k => offsets[b](45, 777, 888, k, seed)) < 60, `${a} ${b} ${seed}`);
""", dict(samples=samples, retained=retained))

    def test_seed_zero_strokes_are_unchanged(self):
        run_node(SEEDED + r"""
const path = [[10, 20], [110, 20], [110, 100]];
const b = {...apart, angle_jitter: 60, size_jitter: 30, amount_jitter: 50, hardness: 40};
// An explicit 0 paints bit for bit as a brush without the key, plain, mouse and pen.
eq(jittered({...b, jitter_seed: 0}, path).result(), jittered(b, path).result(), 'plain');
eq(mouse({...b, jitter_seed: 0}, path).result(), mouse(b, path).result(), 'mouse');
eq(mouse(b, path).result(), allStamps(b, path), 'retained oracle');
const pen = [[10, 20, 9000], [110, 20, 60000], [110, 100, 30000]];
const p0 = slots(full({...b, pressure_amount: true}), pen), p1 = slots(full({...b, pressure_amount: true, jitter_seed: 0}), pen);
eq(p1.stroke.result(), p0.stroke.result(), 'pen'); eq(p1.stroke.coverage, p0.stroke.coverage, 'coverage');
// With every jitter at 0 a seed changes nothing at all: no jitter stroke is needed.
assert.equal(angles.stampJitterActive({...brush, ...square, jitter_seed: 99}), false);
""")

    def test_seed_rerolls_jitter_and_keeps_positions_pressure_and_bases(self):
        run_node(SEEDED + r"""
const path = [[10, 20], [110, 20], [110, 100]];
const b = {...apart, angle_jitter: 60, size_jitter: 30, amount_jitter: 50, hardness: 40};
const runs = [0, 1, 2, 4294967295].map(jitter_seed => ({jitter_seed, plain: plainStamps({...b, jitter_seed}, path),
  mouse: mouse({...b, jitter_seed}, path)}));
for (const run of runs) {
  // Each seed paints exactly its own per-stamp oracle, and replays exactly.
  eq(run.mouse.result(), allStamps({...b, jitter_seed: run.jitter_seed}, path), `seed ${run.jitter_seed}`);
  eq(mouse({...b, jitter_seed: run.jitter_seed}, path).result(), run.mouse.result(), 'replay');
  // Stamp positions do not move with the seed.
  assert.deepEqual(run.plain.stamps, runs[0].plain.stamps);
  assert.equal(run.mouse.jitter.k, runs[0].mouse.jitter.k);
}
for (let i = 0; i < runs.length; i++) for (let j = i + 1; j < runs.length; j++)
  assert.ok(runs[i].mouse.result().some((v, n) => v !== runs[j].mouse.result()[n]), `seeds ${runs[i].jitter_seed} ${runs[j].jitter_seed}`);
// Each channel alone is rerolled by the seed.
for (const only of [{angle_jitter: 60}, {size_jitter: 30}, {amount_jitter: 50}]) {
  const run = c => (c.amount_jitter ? mouse : jittered)(c, path).result();
  const c = {...apart, ...only}, a = run(c), z = run({...c, jitter_seed: 5});
  eq(z, allStamps({...c, jitter_seed: 5}, path), JSON.stringify(only)); assert.ok(a.some((v, n) => v !== z[n]), JSON.stringify(only));
}
// Pen strokes: the seed leaves every slot's position and pressure code, the base size and the base Amount.
const pen = [[10, 20, 9000], [60, 20, 60000], [110, 20, 3277], [110, 100, 30000]];
const pb = full({...b, pressure_amount: true, pressure_min_size: 25});
const p0 = slots(pb, pen), p7 = slots({...pb, jitter_seed: 7}, pen);
assert.deepEqual(p7.slots, p0.slots);
for (const code of [1, 3277, 9000, 30000, 65535]) {
  assert.equal(p7.stroke.sizeAt(code), p0.stroke.sizeAt(code));
  assert.equal(engine.PressureStroke.prototype.amountAt.call(p7.stroke, code), engine.PressureStroke.prototype.amountAt.call(p0.stroke, code));
}
assert.ok(p7.stroke.result().some((v, n) => v !== p0.stroke.result()[n]), 'pen rerolled');
""")

    def test_editor_settings_reroll_presets_and_reset(self):
        run_editor(SEEDED + r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
const control = input('Jitter Seed'), shapeGroup = heading('Brush Shape').parent, rows = shapeGroup.children;
assert.equal(control.parent.parent, shapeGroup); assert.equal(control.value, '0');
assert.equal(rows.indexOf(control.parent), rows.indexOf(input('Scatter (%)').parent) + 1);
assert.equal(rows[rows.indexOf(control.parent) + 1], button('New Jitter Seed'));
// Workflow settings: sparse at 0, nonzero kept, invalid values dropped to the default.
assert.equal(ui.editorSettings(brush).jitter_seed, undefined);
assert.equal(ui.editorSettings({...brush, jitter_seed: 4294967295}).jitter_seed, 4294967295);
for (const bad of [-1, 4294967296, 2.5, '9', true, null]) assert.equal(ui.editorSettings({...brush, jitter_seed: bad}).jitter_seed, undefined);
pressIn(shapeGroup, 'Square'); type('Angle Jitter (±°)', 40); type('Size Jitter (%)', 30); type('Jitter Seed', 4242);
assert.equal(settings().jitter_seed, 4242); assert.ok(summary().textContent.includes('Jitter Seed 4242'));
type('Jitter Seed', 5000000000); assert.equal(settings().jitter_seed, 4294967295); type('Jitter Seed', 4242);
// The editor paints the seeded stroke, and replays it exactly.
pointer('pointerdown', 20, 40); pointer('pointermove', 90, 40); pointer('pointerup', 90, 40); dom.flush();
const replay = new angles.JitterStroke(empty(), 128, 128, engineBrush(), 20, 40); replay.add(90, 40); replay.add(90, 40);
eq(session().codes, replay.result()); assert.equal(replay.jitter.seed, 4242);
const unseeded = new angles.JitterStroke(empty(), 128, 128, {...engineBrush(), jitter_seed: 0}, 20, 40); unseeded.add(90, 40); unseeded.add(90, 40);
assert.ok(unseeded.result().some((v, i) => v !== session().codes[i]), 'seed changes the stroke');
press('Undo');
// New Jitter Seed draws once at the click and stores it; it never repeats the current seed and adds no history.
let draw = 12345; crypto.getRandomValues = array => { array[0] = draw; return array; };
press('New Jitter Seed'); assert.equal(settings().jitter_seed, 12345); assert.equal(input('Jitter Seed').value, '12345');
press('New Jitter Seed'); assert.equal(settings().jitter_seed, 12346);
draw = 4294967295; press('New Jitter Seed'); assert.equal(settings().jitter_seed, 4294967295);
press('New Jitter Seed'); assert.equal(settings().jitter_seed, 0);
assert.equal(session().history.undoEntries.length, 0);
draw = 777; press('New Jitter Seed');
crypto.getRandomValues = () => { throw Error('entropy forbidden while painting'); };
pointer('pointerdown', 20, 40); pointer('pointermove', 90, 40); pointer('pointerup', 90, 40); dom.flush();
const again = new angles.JitterStroke(empty(), 128, 128, engineBrush(), 20, 40); again.add(90, 40); again.add(90, 40);
eq(session().codes, again.result());
press('Done'); assert.equal(result.settings.jitter_seed, 777);
await reopen(empty(), result.settings); assert.equal(settings().jitter_seed, 777); assert.equal(input('Jitter Seed').value, '777');
// Presets: optional key written only when nonzero; old presets byte-identical; bad values rejected.
const meta = {id: 'p', name: 'P'};
const preset = await lib.captureBrushPreset(settings(), meta);
assert.equal(preset.version, 1); assert.equal(preset.brush.jitter_seed, 777);
const old = await lib.captureBrushPreset({...brush, shape: 'square', angle_jitter: 40}, meta);
assert.equal('jitter_seed' in old.brush, false);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(JSON.stringify(old)))), JSON.stringify(old));
const zero = await lib.captureBrushPreset({...brush, jitter_seed: 0}, meta);
assert.deepEqual(Object.keys(zero.brush), lib.SNAPSHOT_KEYS);
await lib.applyBrushPreset(old, session()); assert.equal(settings().jitter_seed, 0);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(preset)), session()); assert.equal(settings().jitter_seed, 777);
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(preset));
let text = null; const library = lib.createBrushLibrary({read: async () => text, write: async v => { text = v; }}, () => 'x');
await library.save(settings(), 'Seeded'); assert.equal((await library.load()).presets[0].brush.jitter_seed, 777);
for (const bad of [-1, 4294967296, 2.5, '9', null])
  await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, jitter_seed: bad}}), /Invalid brush jitter_seed/);
pointer('pointermove', 1, 1); dom.flush(); press('Reset Brush'); assert.equal(settings().jitter_seed, 0);
assert.equal(input('Jitter Seed').value, '0'); assert.ok(!summary().textContent.includes('Jitter Seed'));
""")


FLOW_TAG = 0x464C4F57


def flow_offset(rng, x0, y0, k, seed=0):
    """Independent of angle_jitter.js: the fourth channel, with the Jitter Seed as a fifth word when nonzero."""
    words = [FLOW_TAG, x0 & 0xFFFFFFFF, y0 & 0xFFFFFFFF, k] + ([seed] if seed else [])
    return ProceduralOracle.hash(words) * (2 * rng + 1) // 2**32 - rng


def jittered_flow(flow, percent):
    return min(100, max(1, (flow * (100 + percent) + 50) // 100))


def flow_sequence(flow, rng, x0, y0, seed=0, count=400):
    return [jittered_flow(flow, flow_offset(rng, x0, y0, k, seed)) for k in range(count)]


FLOWS = SEEDED + r"""
// The Flow factor each plain stamp used, recorded where the engine stamps.
const stampFlows = (b, path) => {
  const original = engine.Stroke.prototype.stamp, seen = [];
  engine.Stroke.prototype.stamp = function(x, y) { seen.push(this.flow); return original.call(this, x, y); };
  try { const s = jittered(b, path); return {flows: seen, stroke: s}; } finally { engine.Stroke.prototype.stamp = original; }
};
// Independent of the jitter strokes: a plain stroke whose stamp k uses Flow percents[k].
const flowReference = (b, path, percents) => {
  class Reference extends engine.Stroke {
    stamp(x, y) { this.k = (this.k ?? -1) + 1; this.flow = engine.flowFactor(percents[this.k], this.spacing, this.brush.size); super.stamp(x, y); }
  }
  const s = new Reference(empty(), 128, 128, {...brush, ...b}, ...path[0]); for (const p of path.slice(1)) s.add(...p); return s;
};
// Each pressure slot's position, code and effective Flow, recorded where the engine slots it.
const slotFlows = (b, path) => {
  const original = engine.PressureStroke.prototype.slot, seen = [];
  engine.PressureStroke.prototype.slot = function(x, y, code) {
    seen.push([x, y, code, this.flowAt(code), this.offset, this.percent, this.amountPercent]); return original.call(this, x, y, code); };
  try { const s = new angles.JitterPressureStroke(empty(), 128, 128, {...brush, ...b}, path[0][0], path[0][1], empty(), null, path[0][2]);
    for (const p of path.slice(1)) s.add(...p); return {slots: seen, stroke: s}; }
  finally { engine.PressureStroke.prototype.slot = original; }
};
const soft = {size: 10, hardness: 30, spacing: 'custom', spacing_percent: 40, build_up: true, flow: 40};
"""


class FlowJitterTests(unittest.TestCase):
    def test_offsets_and_flows_match_oracle_bounds_and_channels(self):
        samples = [[rng, x0, y0, k, seed, flow_offset(rng, x0, y0, k, seed)]
                   for rng in [0, 1, 20, 100] for seed in [0, 7919] for x0, y0 in [(0, 0), (2560, 16384), (-256, 32767)]
                   for k in range(0, 400, 7)]
        flows = [[jittered_flow(f, p) for p in range(-100, 101)] for f in range(1, 101)]
        run_node(SEEDED + r"""
for (const [r, x0, y0, k, seed, expected] of data.samples) assert.equal(angles.flowJitterOffset(r, x0, y0, k, seed), expected);
for (let f = 1; f <= 100; f++) for (let p = -100; p <= 100; p++) {
  const v = angles.jitteredFlow(f, p); assert.equal(v, data.flows[f - 1][p + 100]); assert.ok(Number.isInteger(v) && v >= 1 && v <= 100);
}
const counts = new Map(); let sum = 0; const n = 210000;
for (let k = 0; k < n; k++) { const o = angles.flowJitterOffset(10, 1234, 5678, k); counts.set(o, (counts.get(o) ?? 0) + 1); sum += o; }
assert.equal(counts.size, 21); for (const c of counts.values()) assert.ok(Math.abs(c - n / 21) < 0.04 * n / 21, c);
assert.ok(Math.abs(sum / n) < 0.05, sum / n);
// Its own channel, under seed 0 and a nonzero seed; the seed rerolls it.
const agree = (f, g) => { let m = 0; for (let k = 0; k < 1000; k++) m += f(k) === g(k); return m; };
for (const seed of [0, 7919]) for (const other of [angles.jitterOffset, angles.sizeJitterOffset, angles.amountJitterOffset])
  assert.ok(agree(k => angles.flowJitterOffset(45, 777, 888, k, seed), k => other(45, 777, 888, k, seed)) < 60, `${other.name} ${seed}`);
assert.ok(agree(k => angles.flowJitterOffset(45, 777, 888, k), k => angles.flowJitterOffset(45, 777, 888, k, 7919)) < 60, 'seed');
""", dict(samples=samples, flows=flows))

    def test_zero_and_no_build_up_keep_prior_output(self):
        run_editor(FLOWS + r"""
const path = [[10, 20], [110, 20], [110, 100]], pen = [[10, 20, 9000], [110, 20, 60000], [110, 100, 30000]];
assert.equal(angles.stampJitterActive({...brush, ...soft, flow_jitter: 0}), false);
assert.equal(angles.stampJitterActive({...brush, ...soft, flow_jitter: 50}), true);
for (const b of [{...soft}, {...soft, build_up: false}]) {
  // 0 paints bit for bit as a brush without the key, plain and pen, alone or with the other jitters.
  for (const extra of [{}, {size_jitter: 30, angle_jitter: 40, shape: 'square'}]) {
    eq(jittered({...b, ...extra, flow_jitter: 0}, path).result(), jittered({...b, ...extra}, path).result(), JSON.stringify(extra));
    const p0 = slotFlows(full({...b, ...extra, pressure_flow: true}), pen), p1 = slotFlows(full({...b, ...extra, pressure_flow: true, flow_jitter: 0}), pen);
    eq(p1.stroke.result(), p0.stroke.result(), 'pen'); eq(p1.stroke.coverage, p0.stroke.coverage, 'coverage');
  }
}
// Without Build-up Flow has no meaning, and Flow Jitter changes nothing at all.
const off = {...soft, build_up: false, flow_jitter: 90};
assert.equal(angles.stampJitterActive({...brush, ...off}), false); assert.equal(angles.flowJitterRange({...brush, ...off}), 0);
eq(jittered({...off, size_jitter: 30}, path).result(), jittered({...soft, build_up: false, size_jitter: 30}, path).result(), 'no build-up');
const q0 = slotFlows(full({...off, size_jitter: 30}), pen), q1 = slotFlows(full({...soft, build_up: false, size_jitter: 30}), pen);
eq(q0.stroke.result(), q1.stroke.result(), 'no build-up pen');
await reopen(empty(), {...off}); dragLine([[20, 30], [90, 60]]);
eq(session().codes, stroked(engineBrush(), [[20, 30], [90, 60], [90, 60]]), 'editor');
""")

    def test_each_build_up_stamp_uses_its_jittered_flow(self):
        cases = []
        for flow, rng, seed in [(40, 60, 0), (100, 100, 0), (1, 100, 0), (73, 25, 0), (40, 60, 5)]:
            cases.append(dict(flow=flow, rng=rng, seed=seed, percents=flow_sequence(flow, rng, 2560, 5120, seed)))
        run_node(FLOWS + r"""
const path = [[10, 20], [110, 20], [110, 100]];
for (const c of data) {
  const b = {...soft, flow: c.flow, flow_jitter: c.rng, jitter_seed: c.seed}, {flows, stroke} = stampFlows(b, path);
  const tag = JSON.stringify([c.flow, c.rng, c.seed]);
  // The set Flow is the base; each stamp's Flow stays within 1–100 and gives exactly its factor.
  flows.forEach((f, k) => assert.equal(f, engine.flowFactor(c.percents[k], stroke.spacing, b.size), `${tag} stamp ${k}`));
  for (const p of c.percents.slice(0, flows.length)) assert.ok(p >= 1 && p <= 100);
  eq(stroke.result(), flowReference(b, path, c.percents).result(), tag);
  if (c.flow < 100) assert.ok(new Set(flows).size > 1, `${tag} varies`);
  else assert.ok(c.percents.slice(0, flows.length).every(p => p <= 100) && flows.some(f => f < 1), `${tag} clamped above, lowered below`);
}
// Nonzero jitter changes the deposit; the stamps are the unjittered stroke's.
const b = {...soft, flow_jitter: 60};
const a = stampFlows(b, path).stroke.result(), plain = stroked(soft, path);
assert.ok(a.some((v, i) => v !== plain[i]), 'deposit changed');
assert.deepEqual(stamps(b, path).stamps, stamps(soft, path).stamps);
""", cases)

    def test_pressure_flow_is_the_base_and_other_dynamics_stay(self):
        run_node(FLOWS + r"""
const pen = [[10, 20, 9000], [60, 20, 60000], [110, 20, 3277], [110, 100, 30000]];
for (const mapped of [true, false]) {
  const b = full({...soft, flow: 70, flow_jitter: 50, pressure_flow: mapped, pressure_amount: true, pressure_min_size: 25});
  const {slots: got, stroke} = slotFlows(b, pen), {slots: base} = slotFlows({...b, flow_jitter: 0}, pen);
  assert.equal(got.length, base.length);
  got.forEach(([x, y, code, flow], k) => {
    const before = mapped ? engine.scaledControl(70, code) : 70;
    assert.equal(base[k][3], before);  // Flow Jitter 0: pen pressure's Flow exactly as before.
    assert.equal(flow, angles.jitteredFlow(before, angles.flowJitterOffset(50, 2560, 5120, k)), `${mapped} slot ${k}`);
    assert.deepEqual([x, y, code], base[k].slice(0, 3));  // Same positions and pressure.
  });
  for (const code of [1, 3277, 30000, 65535]) {
    assert.equal(stroke.sizeAt(code), engine.PressureStroke.prototype.sizeAt.call(stroke, code));
    assert.equal(stroke.amountAt(code), engine.scaledControl(soft.amount ?? 100, code));
  }
}
""")

    def test_other_channels_deterministic_density_free_and_seeded(self):
        run_node(FLOWS + r"""
const path = [[10, 10], [60, 10], [60, 70], [110, 120]];
const all3 = {...apart, ...soft, size: 8, spacing_percent: 40, angle_jitter: 60, size_jitter: 30, amount_jitter: 50};
// Flow Jitter leaves the angle, size and Amount sequences of every stamp, seeded or not.
for (const seed of [0, 9]) {
  const pen = [[10, 10, 65535], [60, 10, 40000], [60, 70, 20000], [110, 120, 65535]];
  const without = slotFlows(full({...all3, jitter_seed: seed}), pen).slots, withFlow = slotFlows(full({...all3, jitter_seed: seed, flow_jitter: 80}), pen).slots;
  assert.deepEqual(withFlow.map(s => [s[0], s[1], s[2], s[4], s[5], s[6]]), without.map(s => [s[0], s[1], s[2], s[4], s[5], s[6]]), `seed ${seed}`);
  assert.ok(withFlow.some((s, k) => s[3] !== without[k][3]), 'flows changed');
  for (const range of [10, 100]) {
    const other = slotFlows(full({...all3, jitter_seed: seed, flow_jitter: range}), pen).slots;
    assert.deepEqual(other.map(s => s[5]), without.map(s => s[5]), `size ${range}`);
  }
}
// Deterministic, and the same at any pointer-event density.
const b = {...soft, flow_jitter: 70, size_jitter: 20};
const dense = [path[0]];
for (let j = 0; j < 3; j++) for (let k = 1; k <= 19; k++)
  dense.push([path[j][0] + (path[j + 1][0] - path[j][0]) * k / 19, path[j][1] + (path[j + 1][1] - path[j][1]) * k / 19]);
const a = stampFlows(b, path), again = stampFlows(b, path), slow = stampFlows(b, dense);
assert.deepEqual(again.flows, a.flows); eq(again.stroke.result(), a.stroke.result());
assert.deepEqual(slow.flows, a.flows); eq(slow.stroke.result(), a.stroke.result()); assert.equal(slow.stroke.jitter.k, a.stroke.jitter.k);
// The Jitter Seed rerolls Flow repeatably.
const s5 = stampFlows({...b, jitter_seed: 5}, path), s5again = stampFlows({...b, jitter_seed: 5}, path);
assert.deepEqual(s5again.flows, s5.flows); assert.notDeepEqual(s5.flows, a.flows);
s5.flows.forEach((f, k) => assert.equal(f, engine.flowFactor(angles.jitteredFlow(40, angles.flowJitterOffset(70, 2560, 2560, k, 5)), s5.stroke.spacing, 10)));
""")

    def test_editor_settings_presets_and_reset(self):
        run_editor(FLOWS + r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
const control = input('Flow Jitter (%)'), behavior = heading('Brush Behavior').parent;
assert.equal(control.parent.parent, behavior); assert.equal(control.value, '0');
assert.equal(behavior.children.indexOf(control.parent), behavior.children.indexOf(input('Flow (%)').parent) + 1);
assert.equal(behavior.children.at(-1), heading('Pen Pressure').parent);
// Shown with Flow: only while Build-up is on.
assert.equal(control.parent.hidden, true); press('Build-up'); assert.equal(control.parent.hidden, false);
assert.equal(input('Flow (%)').parent.hidden, false);
assert.equal(ui.editorSettings(brush).flow_jitter, undefined);
assert.equal(ui.editorSettings({...brush, flow_jitter: 100}).flow_jitter, 100);
for (const bad of [-1, 101, 2.5, '9', true, null]) assert.equal(ui.editorSettings({...brush, flow_jitter: bad}).flow_jitter, undefined);
type('Flow (%)', 40); type('Hardness (%)', 30); type('Flow Jitter (%)', 45); assert.equal(settings().flow_jitter, 45);
assert.ok(summary().textContent.includes('Flow Jitter ±45%')); assert.ok(heading('Brush Behavior').textContent.includes('Flow Jitter ±45%'));
type('Flow Jitter (%)', 250); assert.equal(settings().flow_jitter, 100); type('Flow Jitter (%)', 45);
pointer('pointerdown', 20, 40); pointer('pointermove', 90, 40); pointer('pointerup', 90, 40); dom.flush();
const replay = new angles.JitterStroke(empty(), 128, 128, engineBrush(), 20, 40); replay.add(90, 40); replay.add(90, 40);
eq(session().codes, replay.result()); assert.equal(replay.jitter.flowRange, 45);
// Build-up off: the setting is kept but hidden, inactive and out of the summary.
press('Build-up'); assert.equal(control.parent.hidden, true); assert.equal(settings().flow_jitter, 45);
assert.ok(!summary().textContent.includes('Flow Jitter')); press('Build-up');
press('Done'); assert.equal(result.settings.flow_jitter, 45);
await reopen(empty(), result.settings); assert.equal(settings().flow_jitter, 45); assert.equal(input('Flow Jitter (%)').value, '45');
const meta = {id: 'p', name: 'P'};
const preset = await lib.captureBrushPreset(settings(), meta);
assert.equal(preset.version, 1); assert.equal(preset.brush.flow_jitter, 45);
const old = await lib.captureBrushPreset({...brush, build_up: true, flow: 40}, meta);
assert.equal('flow_jitter' in old.brush, false); assert.deepEqual(Object.keys(old.brush), lib.SNAPSHOT_KEYS);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(JSON.stringify(old)))), JSON.stringify(old));
await lib.applyBrushPreset(old, session()); assert.equal(settings().flow_jitter, 0);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(preset)), session()); assert.equal(settings().flow_jitter, 45);
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(preset));
let text = null; const library = lib.createBrushLibrary({read: async () => text, write: async v => { text = v; }}, () => 'x');
await library.save(settings(), 'Flowing'); assert.equal((await library.load()).presets[0].brush.flow_jitter, 45);
for (const bad of [-1, 101, 2.5, '9', null])
  await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, flow_jitter: bad}}), /Invalid brush flow_jitter/);
pointer('pointermove', 1, 1); dom.flush(); press('Reset Brush'); assert.equal(settings().flow_jitter, 0);
assert.equal(input('Flow Jitter (%)').value, '0');
""")


SCATTER_TAGS = (0x53435458, 0x53435459)


def scatter_oracle(scatter, size, x0, y0, k, seed=0):
    """Independent of angle_jitter.js: the first of 16 hashed points in the unit disk, scaled to scatter% of size."""
    reach = scatter * size / 100
    tail = [seed] if seed else []
    for a in range(16):
        u, v = ((2 * ProceduralOracle.hash([tag, x0 & 0xFFFFFFFF, y0 & 0xFFFFFFFF, k, a] + tail) + 1) / 2**32 - 1
                for tag in SCATTER_TAGS)
        if u * u + v * v <= 1:
            return [reach * u, reach * v]
    return [0.0, 0.0]


def round_half(value):
    floor = math.floor(value)
    return floor + (1 if value - floor >= 0.5 else 0)


def straight_scatter(size, percent, scatter, size_jitter=0, seed=0, x_start=10, x_end=110, y=40):
    """Base stamps of a straight Custom-spacing stroke from (x_start, y) to (x_end, y), then each one scattered."""
    spacing = round_half(size * percent * 256 / 100)
    x0, y0 = x_start * 256, y * 256
    out = []
    for k in range((x_end - x_start) * 256 // spacing + 1):
        base = (x0 + spacing * k) / 256
        stamp = size if not size_jitter else max(1, (size * (100 + seeded_offset('size', size_jitter, x0, y0, k, seed)) + 50) // 100)
        dx, dy = scatter_oracle(scatter, stamp, x0, y0, k, seed)
        assert dx * dx + dy * dy <= (scatter * stamp / 100) ** 2 * (1 + 1e-12)
        out.append(dict(base=[base, y], at=[base + dx, y + dy], offset=[dx, dy], size=stamp))
    return out


SCATTERED = FLOWS + f"const transfers = await import({json.dumps((CORE / 'transfer.js').as_uri())});\n" + r"""
// Independent of the jitter strokes: retained strokes whose stamp or slot k lands moved by offsets[k].
const scatteredReference = (b, path, offsets, before = empty(), restore = null) => {
  class Reference extends engine.Stroke {
    stamp(x, y) { this.k = (this.k ?? -1) + 1; super.stamp(x + offsets[this.k][0], y + offsets[this.k][1]); }
  }
  const s = new Reference(before.slice(), 128, 128, {...brush, ...b}, ...path[0], restore); for (const p of path.slice(1)) s.add(...p); return s;
};
const scatteredPen = (b, path, before = empty(), restore = empty()) => {
  class Reference extends engine.PressureStroke {
    slot(x, y, code) {
      this.k = (this.k ?? -1) + 1;
      if (code === 0) return super.slot(x, y, code);
      const [dx, dy] = angles.scatterOffset(b.scatter, this.sizeAt(code), path[0][0] * 256, path[0][1] * 256, this.k, b.jitter_seed ?? 0);
      return super.slot(x + dx, y + dy, code);
    }
  }
  const s = new Reference(before.slice(), 128, 128, {...brush, ...b, scatter: 0}, path[0][0], path[0][1], restore, null, path[0][2]);
  for (const p of path.slice(1)) s.add(...p); return s;
};
const penJitter = (b, path, before = empty(), restore = empty()) => {
  const s = new angles.JitterPressureStroke(before.slice(), 128, 128, {...brush, ...b}, path[0][0], path[0][1], restore, null, path[0][2]);
  for (const p of path.slice(1)) s.add(...p); return s;
};
const plainJitter = (b, path, before = empty(), restore = null) => {
  const s = new angles.JitterStroke(before.slice(), 128, 128, {...brush, ...b}, ...path[0], restore); for (const p of path.slice(1)) s.add(...p); return s;
};
const moved = (got, base) => got.map((p, k) => [p[0] - base[k][0], p[1] - base[k][1]]);
"""


class ScatterTests(unittest.TestCase):
    def test_offsets_match_oracle_bounds_and_distribution(self):
        samples = [[scatter, size, x0, y0, k, seed, scatter_oracle(scatter, size, x0, y0, k, seed)]
                   for scatter in [1, 50, 200] for size in [1, 16, 128] for seed in [0, 7919]
                   for x0, y0 in [(0, 0), (2560, 16384), (-256, 32767)] for k in range(0, 200, 13)]
        run_node(SCATTERED + r"""
for (const [s, size, x0, y0, k, seed, expected] of data) assert.deepEqual(angles.scatterOffset(s, size, x0, y0, k, seed), expected);
// Over many stamps: inside the disk, every direction, unbiased, and uniform by area rather than piled at the rim.
const R = 10, n = 40000, quadrants = [0, 0, 0, 0], octants = new Array(8).fill(0);
let sx = 0, sy = 0, sxy = 0, sxx = 0, syy = 0, inner = 0, far = 0, unmoved = 0;
for (let k = 0; k < n; k++) {
  const [dx, dy] = angles.scatterOffset(100, 10, 3333, 4444, k), d2 = dx * dx + dy * dy;
  assert.ok(d2 <= R * R, `${k}: ${Math.sqrt(d2)}`);
  sx += dx; sy += dy; sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
  inner += d2 <= R * R / 4; far = Math.max(far, d2); unmoved += dx === 0 && dy === 0;
  quadrants[(dx < 0) * 2 + (dy < 0)]++; octants[Math.floor((Math.atan2(dy, dx) + Math.PI) / (Math.PI / 4)) % 8]++;
}
assert.ok(Math.abs(sx / n) < 0.02 * R && Math.abs(sy / n) < 0.02 * R, `${sx / n} ${sy / n}`);
for (const q of quadrants) assert.ok(Math.abs(q / n - 0.25) < 0.015, q);
for (const o of octants) assert.ok(Math.abs(o / n - 0.125) < 0.012, o);
assert.ok(Math.abs(inner / n - 0.25) < 0.015, inner / n);  // A rim-heavy radius would put about half inside R/2.
assert.ok(Math.sqrt(far) > 0.99 * R); assert.equal(unmoved, 0);
assert.ok(Math.abs(sxy / Math.sqrt(sxx * syy)) < 0.03, 'x and y independent');
// The reach scales with the stamp size; the seed rerolls repeatably; seed 0 is no seed.
const unit = angles.scatterOffset(100, 1, 3333, 4444, 7);
assert.deepEqual(angles.scatterOffset(50, 64, 3333, 4444, 7), unit.map(v => 32 * v));
let same = 0;
for (let k = 0; k < 500; k++) {
  assert.deepEqual(angles.scatterOffset(80, 12, 3333, 4444, k, 0), angles.scatterOffset(80, 12, 3333, 4444, k));
  assert.deepEqual(angles.scatterOffset(80, 12, 3333, 4444, k, 5), angles.scatterOffset(80, 12, 3333, 4444, k, 5));
  same += angles.scatterOffset(80, 12, 3333, 4444, k, 5).join() === angles.scatterOffset(80, 12, 3333, 4444, k).join();
}
assert.equal(same, 0);
""", samples)

    def test_zero_keeps_prior_output_and_jitter_sequences(self):
        run_editor(SCATTERED + r"""
const path = [[10, 20], [110, 20], [110, 100]], pen = [[10, 20, 9000], [110, 20, 60000], [110, 100, 30000]];
assert.equal(angles.stampJitterActive({...brush, ...square, scatter: 0}), false);
assert.equal(angles.stampJitterActive({...brush, scatter: 30}), true);
const every = {...square, angle_jitter: 40, size_jitter: 30, amount_jitter: 20, build_up: true, flow: 40, flow_jitter: 50, hardness: 40};
for (const b of [{...square}, every, {...every, jitter_seed: 77}]) {
  // 0 paints bit for bit as a brush without the key: plain, mouse and pen.
  eq(jittered({...b, scatter: 0}, path).result(), jittered(b, path).result(), 'plain');
  if (b.amount_jitter) eq(mouse({...b, scatter: 0}, path).result(), mouse(b, path).result(), 'mouse');
  const p0 = slotFlows(full(b), pen), p1 = slotFlows(full({...b, scatter: 0}), pen);
  eq(p1.stroke.result(), p0.stroke.result(), 'pen'); eq(p1.stroke.coverage, p0.stroke.coverage, 'coverage');
  assert.deepEqual(p1.slots, p0.slots);
  // Scatter leaves every slot's pressure, Flow, angle, size and Amount offsets exactly; only positions move.
  const s = slotFlows(full({...b, scatter: 150}), pen).slots;
  assert.deepEqual(s.map(v => v.slice(2)), p0.slots.map(v => v.slice(2)), JSON.stringify(b));
  assert.ok(s.some((v, k) => v[0] !== p0.slots[k][0] || v[1] !== p0.slots[k][1]), 'moved');
}
await reopen(empty(), {...square, scatter: 0}); dragLine([[20, 30], [90, 60]]);
eq(session().codes, stroked(engineBrush(), [[20, 30], [90, 60], [90, 60]]), 'editor');
""")

    def test_each_stamp_moves_by_its_offset_without_changing_spacing(self):
        cases = [dict(b=dict(size=12, shape='square', spacing='custom', spacing_percent=150, scatter=50), stamps=straight_scatter(12, 150, 50)),
                 dict(b=dict(size=12, hardness=40, spacing='custom', spacing_percent=150, scatter=200, jitter_seed=5),
                      stamps=straight_scatter(12, 150, 200, seed=5)),
                 dict(b=dict(size=9, shape='square', spacing='custom', spacing_percent=60, scatter=120, size_jitter=50),
                      stamps=straight_scatter(9, 60, 120, size_jitter=50)),
                 dict(b=dict(size=1, spacing='custom', spacing_percent=300, scatter=200), stamps=straight_scatter(1, 300, 200))]
        # Size Jitter case: the reach follows each stamp's jittered size, which differs from Size somewhere.
        self.assertTrue(any(s['size'] != 9 for s in cases[2]['stamps']))
        run_node(SCATTERED + r"""
const path = [[10, 40], [110, 40]];
for (const c of data) {
  const tag = JSON.stringify(c.b), {stamps: got, stroke} = plainStamps(c.b, path), base = stamps({...c.b, scatter: 0, size_jitter: 0}, path);
  assert.deepEqual(base.stamps, c.stamps.map(s => s.base), `${tag} base`);
  assert.deepEqual(got, c.stamps.map(s => s.at), `${tag} scattered`);
  // No feedback into spacing: the same stamp count and spacing as the unscattered stroke.
  assert.equal(stroke.spacing, engine.stampSpacing({...brush, ...c.b})); assert.equal(stroke.jitter.k, c.stamps.length);
  for (const sign of [1, -1]) for (const axis of [0, 1]) assert.ok(c.stamps.some(s => sign * s.offset[axis] > 0), `${tag} axis ${axis} ${sign}`);
  if (!c.b.size_jitter) eq(stroke.result(), scatteredReference(c.b, path, c.stamps.map(s => s.offset)).result(), tag);
}
""", cases)

    def test_pen_slots_keep_pressure_and_use_the_effective_size(self):
        run_node(SCATTERED + r"""
const pen = [[10, 40, 9000], [60, 40, 60000], [110, 40, 3277], [110, 90, 0], [110, 120, 40000]];
const b = full({...square, size: 16, spacing_percent: 50, scatter: 80, size_jitter: 30, pressure_min_size: 25, angle_jitter: 20});
const base = slotFlows({...b, scatter: 0}, pen), got = slotFlows(b, pen);
assert.equal(got.slots.length, base.slots.length); assert.ok(got.slots.some(s => s[2] === 0), 'a lifted stretch');
got.slots.forEach(([x, y, code], k) => {
  assert.equal(code, base.slots[k][2]);  // Pressure comes from the unscattered path.
  const size = angles.jitteredSize(got.stroke.sizeAt(code), angles.sizeJitterOffset(30, 2560, 10240, k));
  const [dx, dy] = code === 0 ? [0, 0] : angles.scatterOffset(80, size, 2560, 10240, k);
  assert.deepEqual([x, y], [base.slots[k][0] + dx, base.slots[k][1] + dy], `slot ${k}`);
  assert.ok(Math.hypot(x - base.slots[k][0], y - base.slots[k][1]) <= 0.8 * size + 1e-9);
});
// Pressure Size alone: the pen stroke is the retained pressure engine with each slot moved.
for (const tool of ['paint', 'erase', 'restore']) for (const build_up of [false, true]) {
  const c = full({...square, size: 20, spacing_percent: 60, hardness: 50, scatter: 70, tool, build_up, flow: 35, pressure_amount: true});
  const before = tool === 'paint' ? empty() : new Uint8Array(16384).fill(200), restore = Uint8Array.from({length: 16384}, (_, i) => i % 256);
  eq(penJitter(c, pen, before, restore).result(), scatteredPen(c, pen, before, restore).result(), `${tool} ${build_up}`);
}
""")

    def test_tools_build_up_edges_and_transfer_brushes(self):
        run_node(SCATTERED + r"""
const ramp = Uint8Array.from({length: 16384}, (_, i) => (i * 7) % 256), high = new Uint8Array(16384).fill(220);
// Positions never depend on the tool, so Paint's stamps give every tool's offsets.
const offsetsOf = (b, path) => { const p = {...b, tool: 'paint'}; return moved(plainStamps(p, path).stamps, stamps({...p, scatter: 0}, path).stamps); };
const path = [[10, 30], [110, 30], [110, 100]];
for (const tool of ['paint', 'erase', 'restore']) for (const build_up of [false, true]) {
  const b = {...square, size: 14, spacing_percent: 80, hardness: 60, scatter: 90, tool, build_up, flow: 45, value_profile: tool === 'paint' ? 'linear' : 'uniform'};
  const before = tool === 'paint' ? empty() : high;
  eq(plainJitter(b, path, before, ramp).result(), scatteredReference(b, path, offsetsOf(b, path), before, ramp).result(), `${tool} ${build_up}`);
}
// Transfer and Balance paint with their engine brush (Restore toward a per-cell target): scattered the same way.
const engineBrush = transfers.transferEngineBrush({...brush, ...square, size: 14, spacing_percent: 80, scatter: 90});
assert.equal(engineBrush.scatter, 90); assert.equal(angles.stampJitterActive(engineBrush), true);
eq(plainJitter(engineBrush, path, high, ramp).result(), scatteredReference(engineBrush, path, offsetsOf(engineBrush, path), high, ramp).result(), 'transfer');
// Along the edge: centres leave the field, footprints clip as any stamp does, nothing wraps.
const edge = [[1, 1], [1, 126], [126, 126]], wide = {...square, size: 12, spacing_percent: 50, scatter: 200};
const at = plainStamps(wide, edge).stamps, result = plainJitter(wide, edge).result();
assert.ok(at.some(([x, y]) => x < 0) && at.some(([x, y]) => y > 128), 'centres outside');
eq(result, scatteredReference(wide, edge, offsetsOf(wide, edge)).result(), 'edge');
assert.ok(result[64 * 128] > 0, 'clipped stamps still paint inside');
for (let row = 0; row < 90; row++) for (let col = 40; col < 128; col++) assert.equal(result[row * 128 + col], 0, `${col} ${row} wrapped`);
""")

    def test_deterministic_density_free_seeded_and_independent(self):
        run_node(SCATTERED + r"""
const path = [[10, 10], [60, 10], [60, 70], [110, 120]];
const dense = [path[0]];
for (let j = 0; j < 3; j++) for (let k = 1; k <= 23; k++)
  dense.push([path[j][0] + (path[j + 1][0] - path[j][0]) * k / 23, path[j][1] + (path[j + 1][1] - path[j][1]) * k / 23]);
const b = {...square, size: 10, spacing_percent: 70, hardness: 50, scatter: 90};
const a = plainStamps(b, path), again = plainStamps(b, path), slow = plainStamps(b, dense);
assert.deepEqual(again.stamps, a.stamps); eq(again.stroke.result(), a.stroke.result());
assert.deepEqual(slow.stamps, a.stamps); eq(slow.stroke.result(), a.stroke.result()); assert.equal(slow.stroke.jitter.k, a.stroke.jitter.k);
// The Jitter Seed rerolls Scatter repeatably.
const s5 = plainStamps({...b, jitter_seed: 5}, path);
assert.deepEqual(plainStamps({...b, jitter_seed: 5}, path).stamps, s5.stamps);
assert.ok(s5.stamps.every((p, k) => p[0] !== a.stamps[k][0] || p[1] !== a.stamps[k][1]), 'every stamp rerolled');
// Other jitters never move the Scatter sequence: positions are the same with Angle and Flow Jitter on…
const others = {...b, angle_jitter: 45, build_up: true, flow: 40, flow_jitter: 60};
assert.deepEqual(plainStamps(others, path).stamps, a.stamps);
// …with Amount Jitter (a pressure stroke at full pressure)…
const mouseSlots = c => { const original = engine.PressureStroke.prototype.slot, seen = [];
  engine.PressureStroke.prototype.slot = function(x, y, code) { seen.push([x, y]); return original.call(this, x, y, code); };
  try { mouse(c, path); return seen; } finally { engine.PressureStroke.prototype.slot = original; } };
assert.deepEqual(mouseSlots({...others, amount_jitter: 70}), a.stamps);
// …and with Size Jitter the same unit offsets scale with each stamp's size.
const base = stamps({...b, scatter: 0}, path).stamps, sized = plainStamps({...b, size_jitter: 60}, path).stamps;
const unit = moved(a.stamps, base).map(([dx, dy]) => [dx / 9, dy / 9]);
moved(sized, base).forEach(([dx, dy], k) => {
  const reach = 0.9 * angles.jitteredSize(10, angles.sizeJitterOffset(60, 2560, 2560, k));
  assert.ok(Math.abs(dx / reach - unit[k][0]) < 1e-12 && Math.abs(dy / reach - unit[k][1]) < 1e-12, `stamp ${k}`);
});
""")

    def test_editor_settings_shift_line_presets_and_reset(self):
        run_editor(SCATTERED + r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
const control = input('Scatter (%)'), shapeGroup = heading('Brush Shape').parent, rows = shapeGroup.children;
assert.equal(control.parent.parent, shapeGroup); assert.equal(control.value, '0');
assert.equal(rows.indexOf(control.parent), rows.indexOf(input('Size Jitter (%)').parent) + 1);
assert.equal(rows.indexOf(input('Jitter Seed').parent), rows.indexOf(control.parent) + 1);
assert.equal(ui.editorSettings(brush).scatter, undefined);
assert.equal(ui.editorSettings({...brush, scatter: 200}).scatter, 200);
for (const bad of [-1, 201, 2.5, '9', true, null]) assert.equal(ui.editorSettings({...brush, scatter: bad}).scatter, undefined);
pressIn(shapeGroup, 'Square'); type('Scatter (%)', 60); assert.equal(settings().scatter, 60);
assert.ok(summary().textContent.includes('Scatter 60%')); assert.ok(heading('Brush Shape').textContent.includes('Scatter 60%'));
type('Scatter (%)', 500); assert.equal(settings().scatter, 200); type('Scatter (%)', 60);
// A drag paints the scattered stroke, and a Shift-click line scatters through the same stamp pipeline.
pointer('pointerdown', 20, 40); pointer('pointermove', 90, 40); pointer('pointerup', 90, 40); dom.flush();
const replay = plainJitter(engineBrush(), [[20, 40], [90, 40], [90, 40]]);
eq(session().codes, replay.result()); assert.ok(replay.result().some((v, i) => v !== stroked(engineBrush(), [[20, 40], [90, 40], [90, 40]])[i]));
click(90, 80, {shiftKey: true}); assert.equal(session().history.undoEntries.length, 2);
eq(session().codes, plainJitter(engineBrush(), [[90, 40], [90, 80]], replay.result()).result(), 'line');
press('Done'); assert.equal(result.settings.scatter, 60);
await reopen(empty(), result.settings); assert.equal(settings().scatter, 60); assert.equal(input('Scatter (%)').value, '60');
const meta = {id: 'p', name: 'P'};
const preset = await lib.captureBrushPreset(settings(), meta);
assert.equal(preset.version, 1); assert.equal(preset.brush.scatter, 60);
const old = await lib.captureBrushPreset({...brush, shape: 'square'}, meta);
assert.equal('scatter' in old.brush, false); assert.deepEqual(Object.keys(old.brush), lib.SNAPSHOT_KEYS);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(JSON.stringify(old)))), JSON.stringify(old));
await lib.applyBrushPreset(old, session()); assert.equal(settings().scatter, 0);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(preset)), session()); assert.equal(settings().scatter, 60);
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(preset));
let text = null; const library = lib.createBrushLibrary({read: async () => text, write: async v => { text = v; }}, () => 'x');
await library.save(settings(), 'Scattered'); assert.equal((await library.load()).presets[0].brush.scatter, 60);
for (const bad of [-1, 201, 2.5, '9', null])
  await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, scatter: bad}}), /Invalid brush scatter/);
pointer('pointermove', 1, 1); dom.flush(); press('Reset Brush'); assert.equal(settings().scatter, 0);
assert.equal(input('Scatter (%)').value, '0'); assert.ok(!summary().textContent.includes('Scatter'));
""")



def direction_oracle(dx, dy, gap):
    """Independent of angle_jitter.js: whole degrees of travel (dx, dy), y down, or None below half the gap."""
    if 4 * (dx * dx + dy * dy) < gap * gap:
        return None
    degrees = round_half(math.atan2(dy, dx) * 180 / math.pi)
    return degrees + 360 if degrees < 0 else degrees


def follow_oracle(stamps, gap):
    """Each base stamp's direction: the chord from the anchor, kept only when at least half the gap long."""
    anchor, direction, out = None, None, []
    for x, y in stamps:
        if anchor is None:
            anchor = (x, y)
        else:
            found = direction_oracle(x - anchor[0], y - anchor[1], gap)
            if found is not None:
                direction, anchor = found, (x, y)
        out.append(direction)
    return out


def followed_rotations(stamps, gap, rotation=0, angle_jitter=0, x0=0, y0=0, seed=0):
    """Each stamp's Rotation as passed to its footprint: Rotation, then Angle Jitter, then the direction.
    Stamps before the first direction take it; with none, Rotation alone."""
    out, directions = [], follow_oracle(stamps, gap)
    first = next((d for d in directions if d is not None), None)
    for k, direction in enumerate(directions):
        direction = first if direction is None else direction
        turned = rotation + seeded_offset('angle', angle_jitter, x0, y0, k, seed)
        turned = turned - 360 if turned > 360 else turned + 360 if turned < -360 else turned
        out.append(turned if direction is None else math.fmod(turned + direction, 360))
    return out


def same_angles(test, got, expected, tag=''):
    """got: footprint angles in [0, 360); expected: rotations within ±360."""
    test.assertEqual(len(got), len(expected), tag)
    for k, (a, b) in enumerate(zip(got, expected)):
        if a is None or b is None:
            test.assertIs(a, b, f'{tag} stamp {k}')
            continue
        d = abs(a - b % 360)
        test.assertLess(min(d, 360 - d), 2e-6, f'{tag} stamp {k}: {a} != {b}')


FOLLOW = SCATTERED + r"""
// The angle in [0, 360), to a millionth of a degree, that a prepared footprint turns its stamp.
const angleOf = f => f.quarter !== null ? f.quarter * 90 : Math.round((Math.atan2(f.sin, f.cos) * 180 / Math.PI + 360) % 360 * 1e6) / 1e6;
// Each plain stamp's position as painted (after Scatter) and its footprint's angle.
const turns = (b, path) => {
  const original = engine.Stroke.prototype.stamp, seen = [];
  engine.Stroke.prototype.stamp = function(x, y) { seen.push([x, y, angleOf(this.footprint)]); return original.call(this, x, y); };
  try { const s = jittered(b, path); s.result(); return {stamps: seen.map(v => v.slice(0, 2)), angles: seen.map(v => v[2]), stroke: s}; }
  finally { engine.Stroke.prototype.stamp = original; }
};
// The same for each pressure slot (a null third coordinate: a mouse stroke). A slot at pressure 0 has no angle.
const penTurns = (b, path) => {
  const original = engine.PressureStroke.prototype.slot, seen = [];
  engine.PressureStroke.prototype.slot = function(x, y, code) {
    seen.push([x, y, code === 0 ? null : angleOf(this.prepare(this.sizeAt(code)).footprint)]); return original.call(this, x, y, code); };
  try { const s = new angles.JitterPressureStroke(empty(), 128, 128, {...brush, ...b}, path[0][0], path[0][1], empty(), null, path[0][2]);
    for (const p of path.slice(1)) s.add(...p); s.result(); return {stamps: seen.map(v => v.slice(0, 2)), angles: seen.map(v => v[2]), stroke: s}; }
  finally { engine.PressureStroke.prototype.slot = original; }
};
// Independent of the jitter strokes: each stamp painted alone at its given Rotation, combined by maximum.
const atRotations = (b, at, rotations) => { const out = empty();
  at.forEach(([x, y], k) => { const r = stroked({...b, rotation_degrees: rotations[k], angle_jitter: 0, follow_direction: false}, [[x, y]]);
    for (let i = 0; i < r.length; i++) out[i] = Math.max(out[i], r[i]); }); return out; };
const base = (b, path) => stamps({...b, follow_direction: false, scatter: 0}, path).stamps;
// A directional tip: a hard bar 2.5 times as long as it is wide, unlike itself after a quarter turn.
const bar = {size: 10, shape: 'square', scale_x: 2.5, spacing: 'custom', spacing_percent: 60, follow_direction: true};
"""

LINES = [(40, 0), (0, 40), (-40, 0), (0, -40), (30, 30), (-30, 30), (-30, -30), (30, -30), (40, 10), (10, -40), (-35, 17), (7, 29)]


class FollowDirectionTests(unittest.TestCase):
    def test_directions_match_oracle_and_brush_convention(self):
        rng = random.Random(41)
        vectors = [(1, 0, 1), (0, 1, 1), (-1, 0, 1), (0, -1, 1), (1, 1, 1), (-1, 1, 1), (-1, -1, 1), (1, -1, 1), (3, -4, 1),
                   (0, 0, 1), (0, 0, 0.25), (0.1, 0, 1), (0.5, 0, 1), (0.49, 0, 1), (-1, -0.0, 1), (-5, -1e-12, 1), (1e-3, 1e-3, 0)]
        vectors += [(rng.uniform(-9, 9), rng.uniform(-9, 9), rng.choice([0.25, 1, 6])) for _ in range(300)]
        samples = [[dx, dy, gap, direction_oracle(dx, dy, gap)] for dx, dy, gap in vectors]
        self.assertEqual([s[3] for s in samples[:10]], [0, 90, 180, 270, 45, 135, 225, 315, 307, None])
        rotations = [[r, d, math.fmod(r + d, 360)] for r in [0, 17.5, -359.9, 360, -90, 359.9] for d in [0, 45, 180, 359]]
        got = run_node(FOLLOW + r"""
for (const [dx, dy, gap, expected] of data.samples) assert.equal(angles.strokeDirection(dx, dy, gap), expected, `${dx} ${dy} ${gap}`);
for (const [r, d, expected] of data.rotations) assert.equal(angles.followedRotation(r, d), expected);
// A bar drawn left to right looks exactly as with the setting off: moving right is Rotation 0, no fixed correction.
const right = [[20, 64], [100, 64]];
eq(jittered(bar, right).result(), stroked({...bar, follow_direction: false}, right), 'right');
const out = {};
for (const rotation of [0, 30]) out[rotation] = data.lines.map(([vx, vy]) => turns({...bar, rotation_degrees: rotation}, [[64, 64], [64 + vx, 64 + vy]]).angles);
console.log(JSON.stringify(out));
""", dict(samples=samples, rotations=rotations, lines=LINES))
        named = {(40, 0): 0, (0, 40): 90, (-40, 0): 180, (0, -40): 270, (30, 30): 45, (-30, 30): 135, (-30, -30): 225, (30, -30): 315}
        for (vx, vy), plain, turned in zip(LINES, got['0'], got['30']):
            exact = math.atan2(vy, vx) * 180 / math.pi
            self.assertGreater(abs(exact - math.floor(exact) - 0.5), 0.01)  # Far from a rounding tie.
            expected = direction_oracle(vx, vy, 1)
            if (vx, vy) in named:
                self.assertEqual(expected, named[vx, vy])
            self.assertGreaterEqual(len(plain), 5)
            # The first stamp takes the line's direction too.
            same_angles(self, plain, [expected] * len(plain), f'{vx},{vy}')
            same_angles(self, turned, [(expected + 30) % 360] * len(turned), f'{vx},{vy} +30')

    def test_rotation_and_angle_jitter_offset_the_direction_and_reversal_turns_180(self):
        paths = [[[20, 30], [100, 30], [100, 100], [40, 60], [100, 60]], [[20, 64], [100, 64], [30, 64]],
                 [[60, 10], [60, 90], [20, 50]], [[100, 100], [30, 30], [30, 110]], [[110, 20], [20, 20]]]
        brushes = [{}, {'rotation_degrees': 17.5}, {'rotation_degrees': -40, 'angle_jitter': 25}, {'angle_jitter': 25, 'jitter_seed': 9},
                   {'rotation_degrees': 300, 'angle_jitter': 180, 'hardness': 40}]
        got = run_node(FOLLOW + r"""
console.log(JSON.stringify(data.paths.map(path => data.brushes.map(b => {
  const t = turns({...bar, ...b}, path); return {base: base({...bar, ...b}, path), stamps: t.stamps, angles: t.angles};
}))));
""", dict(paths=paths, brushes=brushes))
        checks = []
        gap = round_half(10 * 60 * 256 / 100) / 256
        for path, runs in zip(paths, got):
            for b, run in zip(brushes, runs):
                self.assertEqual(run['stamps'], run['base'])  # Recorded before any hard snapping.
                expected = followed_rotations(run['base'], gap, b.get('rotation_degrees', 0), b.get('angle_jitter', 0),
                                              path[0][0] * 256, path[0][1] * 256, b.get('jitter_seed', 0))
                same_angles(self, run['angles'], expected, json.dumps(b))
                if 'hardness' not in b:
                    checks.append([path, b, run['base'], expected])
        # Reversal: the return leg of the second path points the bar the other way, exactly 180° round.
        plain = follow_oracle(got[1][0]['base'], gap)
        self.assertEqual(plain[0], None)
        # Started down, up-left and left, the first stamp follows those directions.
        for path, first in zip(got[2:], [90, 225, 180]):
            self.assertEqual(follow_oracle(path[0]['base'], gap)[1], first)
            self.assertEqual(path[0]['angles'][:2], [first, first])
        self.assertEqual(sorted(set(plain[1:])), [0, 180])
        self.assertEqual(plain[-1], 180)
        run_node(FOLLOW + r"""
for (const [path, b, at, rotations] of data) eq(jittered({...bar, ...b}, path).result(), atRotations({...bar, ...b}, at, rotations), JSON.stringify(b));
// A linear gradient along the bar: drawn right it paints as Rotation 0; drawn left it points the other way.
const ramp = {...bar, value_profile: 'linear'}, still = {...ramp, follow_direction: false}, right = [[20, 64], [100, 64]], left = [[100, 64], [20, 64]];
eq(jittered(ramp, right).result(), jittered(still, right).result(), 'right');
const back = jittered(ramp, left).result();
assert.ok(back.some((v, i) => v !== jittered(still, left).result()[i]), 'reversed stroke turned');
eq(back, jittered({...still, rotation_degrees: 180}, left).result(), 'reversed is Rotation 180, first stamp included');
""", checks)

    def test_off_preserves_output_and_the_jitter_sequences(self):
        run_editor(FOLLOW + r"""
const path = [[10, 20], [110, 20], [110, 100]], pen = [[10, 20, 9000], [110, 20, 60000], [110, 100, 30000]];
const long = {...square, scale_x: 2};
assert.equal(angles.followDirectionActive({...brush, ...long}), false);
assert.equal(angles.followDirectionActive({...brush, ...long, follow_direction: true}), true);
assert.equal(angles.stampJitterActive({...brush, ...long, follow_direction: false}), false);
assert.equal(angles.stampJitterActive({...brush, ...long, follow_direction: true}), true);
for (const b of [{}, {hardness: 0}, {value_profile: 'radial'}])
  assert.equal(angles.followDirectionActive({...brush, follow_direction: true, ...b}), false, JSON.stringify(b));
for (const b of [{shape: 'square'}, {scale_x: 2}, {crop_left: 10}, {value_profile: 'linear'}])
  assert.equal(angles.followDirectionActive({...brush, follow_direction: true, ...b}), true, JSON.stringify(b));
const every = {...long, angle_jitter: 40, size_jitter: 30, amount_jitter: 20, build_up: true, flow: 40, flow_jitter: 50, hardness: 40, scatter: 60};
for (const b of [{...long}, every, {...every, jitter_seed: 77}]) {
  // Off paints bit for bit as a brush without the key: plain, mouse and pen.
  eq(jittered({...b, follow_direction: false}, path).result(), jittered(b, path).result(), 'plain');
  if (b.amount_jitter) eq(mouse({...b, follow_direction: false}, path).result(), mouse(b, path).result(), 'mouse');
  const p0 = slotFlows(full(b), pen), p1 = slotFlows(full({...b, follow_direction: false}), pen);
  eq(p1.stroke.result(), p0.stroke.result(), 'pen'); assert.deepEqual(p1.slots, p0.slots);
  // On: every slot keeps its position, pressure, Flow and angle, size and Amount offsets; only footprints turn.
  const on = slotFlows(full({...b, follow_direction: true}), pen);
  assert.deepEqual(on.slots, p0.slots, JSON.stringify(b)); assert.equal(on.stroke.jitter.k, p0.stroke.jitter.k);
  assert.ok(on.stroke.result().some((v, i) => v !== p0.stroke.result()[i]), 'turned');
  const plainOn = turns({...b, follow_direction: true}, path), plainOff = turns(b, path);
  assert.deepEqual(plainOn.stamps, plainOff.stamps); assert.equal(plainOn.stroke.jitter.k, plainOff.stroke.jitter.k);
}
// A round Disk looks the same at any angle: not turned, and painted exactly as before.
const disk = {size: 10, spacing: 'custom', spacing_percent: 60, follow_direction: true};
eq(jittered(disk, path).result(), stroked(disk, path), 'disk');
assert.ok(turns(disk, path).angles.every(a => a === 0));
await reopen(empty(), {size: 12, follow_direction: true}); dragLine([[20, 30], [90, 60]]);
eq(session().codes, stroked(engineBrush(), [[20, 30], [90, 60], [90, 60]]), 'editor disk');
await reopen(empty(), {...long, follow_direction: false}); dragLine([[20, 30], [90, 60]]);
eq(session().codes, stroked(engineBrush(), [[20, 30], [90, 60], [90, 60]]), 'editor off');
""")

    def test_scatter_size_amount_flow_and_pressure_leave_the_direction(self):
        run_node(FOLLOW + r"""
const path = [[15, 20], [100, 35], [90, 100], [30, 70]], first = turns(bar, path);
assert.ok(new Set(first.angles).size > 3, 'the path turns');
for (const v of [{scatter: 150}, {scatter: 200, jitter_seed: 3}, {size_jitter: 60}, {build_up: true, flow: 30, flow_jitter: 70},
  {hardness: 30}, {amount: 40}, {value_profile: 'linear'}]) {
  const t = turns({...bar, ...v}, path), tag = JSON.stringify(v);
  assert.deepEqual(t.angles, first.angles, tag);
  if (v.scatter) assert.ok(t.stamps.every((p, k) => p[0] !== first.stamps[k][0] || p[1] !== first.stamps[k][1]), `${tag} moved`);
}
// Amount Jitter runs a mouse stroke as a pressure stroke at full pressure: the same angles.
assert.deepEqual(penTurns({...bar, amount_jitter: 50}, path.map(p => [...p, null])).angles, first.angles, 'amount jitter');
// Pen pressure: with Auto spacing the slots sit where the mouse stamps do, whatever their size, Amount or Flow.
const auto = {...bar, spacing: 'auto'}, mouseAngles = turns(auto, path).angles;
const pen = [[15, 20, 3000], [100, 35, 65535], [90, 100, 12000], [30, 70, 50000]];
for (const p of [{pressure_size: true, pressure_min_size: 20}, {pressure_size: true, pressure_amount: true, size_jitter: 40},
  {pressure_size: false, pressure_flow: true, build_up: true, flow: 50, scatter: 80}]) {
  const t = penTurns(full({...auto, ...p}), pen);
  assert.deepEqual(t.angles, mouseAngles, JSON.stringify(p));
}
""")

    def test_smoothing_density_and_low_movement(self):
        raw = jitter_path()
        got = run_node(FOLLOW + r"""
const b = {...bar, spacing: 'auto'}, path = data.map(p => p.slice(0, 2));
const smoothPath = [path[0], ...smoothed(60, data).map(p => p.slice(0, 2))];
const rough = turns(b, path), smooth = turns(b, smoothPath);
console.log(JSON.stringify({rough: {base: base(b, path), angles: rough.angles}, smooth: {base: base(b, smoothPath), angles: smooth.angles}}));
""", raw)
        spread = {}
        for name, run in got.items():
            same_angles(self, run['angles'], followed_rotations(run['base'], 0.25), name)
            spread[name] = max(min(a, 360 - a) for a in run['angles'])
        # Smoothing steadies the path the direction is read from.
        self.assertGreater(spread['rough'], 30)
        self.assertLess(spread['smooth'], spread['rough'] / 2)
        run_editor(FOLLOW + r"""
// Event density: the same base stamps give the same angles and field.
const path = [[10, 10], [40, 10], [40, 50], [70, 80], [20, 80]], dense = [path[0]];
for (let j = 0; j < 4; j++) for (let k = 1; k <= 31; k++)
  dense.push([path[j][0] + (path[j + 1][0] - path[j][0]) * k / 31, path[j][1] + (path[j + 1][1] - path[j][1]) * k / 31]);
for (const b of [bar, {...bar, spacing: 'auto', hardness: 50, angle_jitter: 30, scatter: 50}]) {
  const fast = turns(b, path), slow = turns(b, dense);
  assert.deepEqual(slow.stamps, fast.stamps); assert.deepEqual(slow.angles, fast.angles); eq(slow.stroke.result(), fast.stroke.result());
}
// A click, a pointer at rest and tremor in place have no direction: Rotation alone, never NaN, never flipped.
for (const rotation of [0, 30]) {
  const b = {...bar, spacing: 'auto', rotation_degrees: rotation};
  assert.deepEqual(turns(b, [[64, 64]]).angles, [rotation]);
  const still = [[64, 64]]; for (let i = 0; i < 1000; i++) still.push([64, 64]);
  assert.deepEqual(turns(b, still).angles, [rotation]);
  const tremor = [[64, 64]]; for (let i = 0; i < 400; i++) tremor.push([64 + (i % 2 ? 0.05 : -0.05), 64]);
  const shaken = turns(b, tremor).angles;
  assert.ok(shaken.length > 10); assert.ok(shaken.every(a => a === rotation), `${rotation}: ${shaken}`);
  // After travel, tremor keeps the last direction rather than flipping.
  const travel = [[20, 64], [60, 64]]; for (let i = 0; i < 400; i++) travel.push([60 + (i % 2 ? -0.05 : 0.05), 64]);
  const kept = turns(b, travel).angles;
  assert.ok(kept.every(a => a === rotation), `${rotation} travel`);
  const backward = turns(b, [[60, 64], [20, 64], ...travel.slice(2).map(([x, y]) => [x - 40, y])]).angles;
  assert.ok(backward.every(a => a === (rotation + 180) % 360), `${rotation} backward`);
  // Tremor first, then travel: every held stamp takes the first direction.
  const late = turns(b, [...tremor, [64, 100]]).angles;
  assert.ok(late.length > shaken.length + 2); assert.notEqual(late[0], rotation);
  assert.ok(late.slice(0, shaken.length + 1).every(a => a === late[shaken.length]), `${rotation} late`);
  assert.equal(late.at(-1), (rotation + 90) % 360);
}
// Pen slots at pressure 0 paint nothing; every painted slot has a finite angle.
const lifted = penTurns(full({...bar, spacing: 'auto'}), [[10, 30, 20000], [60, 30, 0], [100, 60, 40000]]).angles;
assert.ok(lifted.some(a => a === null)); assert.ok(lifted.every(a => a === null || Number.isFinite(a)));
// Editor: the smoothed path is what is painted and what the direction follows.
const data = [[12, 64], [30, 70], [50, 58], [70, 72], [90, 60], [110, 66]];
await reopen(empty(), {...bar, smoothing: 50});
pointer('pointerdown', ...data[0]); for (const p of data.slice(1, -1)) pointer('pointermove', ...p); pointer('pointerup', ...data.at(-1)); dom.flush();
const st = new angles.JitterStroke(empty(), 128, 128, engineBrush(), ...data[0]);
const sm = new smoothing.StrokeSmoother(50, ...data[0], null, (x, y) => st.add(x, y));
for (const p of data.slice(1)) sm.add(...p); sm.add(...data.at(-1)); sm.finish(); eq(session().codes, st.result(), 'smoothed');
""")

    def test_editor_settings_shift_line_presets_and_reset(self):
        run_editor(FOLLOW + r"""
assert.equal(all().filter(e => e.tagName === 'INPUT' && e.type === 'text').length, 49);
const control = button('Follow Stroke Direction'), shapeGroup = heading('Brush Shape').parent, rows = shapeGroup.children;
assert.equal(control.parent.parent, shapeGroup); assert.equal(control.attributes['aria-pressed'], 'false');
assert.equal(rows.indexOf(control.parent), rows.indexOf(input('Rotation (°)').parent) + 1);
assert.equal(rows.indexOf(input('Angle Jitter (±°)').parent), rows.indexOf(control.parent) + 1);
assert.equal(ui.editorSettings(brush).follow_direction, undefined);
assert.equal(ui.editorSettings({...brush, follow_direction: false}).follow_direction, undefined);
assert.equal(ui.editorSettings({...brush, follow_direction: true}).follow_direction, true);
for (const bad of ['true', 1, 0, null, {}]) assert.equal(ui.editorSettings({...brush, follow_direction: bad}).follow_direction, undefined);
assert.ok(!heading('Brush Shape').textContent.includes('Follow'));
pressIn(shapeGroup, 'Square'); type('Scale X', 2.5); press('Follow Stroke Direction');
assert.equal(settings().follow_direction, true); assert.equal(control.attributes['aria-pressed'], 'true');
assert.ok(summary().textContent.includes('Follow Direction')); assert.ok(heading('Brush Shape').textContent.includes('Follow Direction'));
// A drag paints the followed stroke, and a Shift-click line follows its own direction through the same stamps.
pointer('pointerdown', 20, 40); pointer('pointermove', 90, 40); pointer('pointerup', 90, 40); dom.flush();
const replay = plainJitter(engineBrush(), [[20, 40], [90, 40], [90, 40]]);
eq(session().codes, replay.result());
click(90, 80, {shiftKey: true}); assert.equal(session().history.undoEntries.length, 2);
eq(session().codes, plainJitter(engineBrush(), [[90, 40], [90, 80]], replay.result()).result(), 'line');
const line = turns(engineBrush(), [[90, 40], [90, 80]]).angles;
assert.ok(line.length > 2); assert.ok(line.every(a => a === 90), 'line turned down, its first stamp too');
const unturned = plainJitter({...engineBrush(), follow_direction: false}, [[90, 40], [90, 80]], replay.result()).result();
assert.ok(session().codes.some((v, i) => v !== unturned[i]), 'line differs from Rotation alone');
press('Done'); assert.equal(result.settings.follow_direction, true);
await reopen(empty(), result.settings); assert.equal(settings().follow_direction, true);
assert.equal(button('Follow Stroke Direction').attributes['aria-pressed'], 'true');
// Presets: an optional key, written only when on; old presets unchanged; bad values rejected.
const meta = {id: 'p', name: 'P'};
const preset = await lib.captureBrushPreset(settings(), meta);
assert.equal(preset.version, 1); assert.equal(preset.brush.follow_direction, true);
const old = await lib.captureBrushPreset({...brush, shape: 'square'}, meta);
assert.equal('follow_direction' in old.brush, false); assert.deepEqual(Object.keys(old.brush), lib.SNAPSHOT_KEYS);
assert.equal(JSON.stringify(await lib.validateBrushPreset(JSON.parse(JSON.stringify(old)))), JSON.stringify(old));
await lib.applyBrushPreset(old, session()); assert.equal(settings().follow_direction, false);
await lib.applyBrushPreset(JSON.parse(JSON.stringify(preset)), session()); assert.equal(settings().follow_direction, true);
assert.equal(JSON.stringify(await lib.captureBrushPreset(settings(), meta)), JSON.stringify(preset));
const pen = await lib.captureBrushPreset({...settings(), pressure_enabled: true}, meta);
assert.equal(pen.version, 2); assert.equal(pen.brush.follow_direction, true);
let text = null; const library = lib.createBrushLibrary({read: async () => text, write: async v => { text = v; }}, () => 'x');
await library.save(settings(), 'Followed'); assert.equal((await library.load()).presets[0].brush.follow_direction, true);
assert.equal((await lib.validateBrushPreset({...preset, brush: {...preset.brush, follow_direction: false}})).brush.follow_direction, false);
for (const bad of ['true', 1, 0, null, {}])
  await assert.rejects(() => lib.validateBrushPreset({...preset, brush: {...preset.brush, follow_direction: bad}}), /Invalid brush follow_direction/);
pointer('pointermove', 1, 1); dom.flush(); press('Reset Brush'); assert.equal(settings().follow_direction, false);
assert.equal(button('Follow Stroke Direction').attributes['aria-pressed'], 'false'); assert.ok(!summary().textContent.includes('Follow'));
""")


    def test_held_first_stamp_keeps_its_offsets_pressure_and_scatter(self):
        run_node(FOLLOW + r"""
// A straight line in direction d paints exactly as the stroke without the setting at Rotation r + d: the first
// stamp included, with its own Angle, Size, Amount and Flow Jitter, Scatter and pressure sample.
const lines = [[[30, 64], [100, 64], 0], [[64, 20], [64, 100], 90], [[30, 30], [90, 90], 45], [[90, 30], [30, 90], 135],
  [[100, 64], [20, 64], 180], [[64, 100], [64, 20], 270]];
const kinds = [{}, {angle_jitter: 25, size_jitter: 40, scatter: 70, jitter_seed: 11},
  {angle_jitter: 25, amount_jitter: 30, build_up: true, flow: 40, flow_jitter: 60, hardness: 40},
  {value_profile: 'linear', hardness: 60, size_jitter: 30, scatter: 50}];
for (const [from, to, d] of lines) for (const kind of kinds) {
  const b = {...bar, ...kind, rotation_degrees: 20}, still = {...b, follow_direction: false, rotation_degrees: 20 + d}, tag = `${d} ${JSON.stringify(kind)}`;
  eq(jittered(b, [from, to]).result(), jittered(still, [from, to]).result(), `plain ${tag}`);
  if (b.amount_jitter) eq(mouse(b, [from, to]).result(), mouse(still, [from, to]).result(), `mouse ${tag}`);
  // Pen: the first slot's pressure is far from the rest, so a resampled pressure would show.
  const pen = [[...from, 4000], [...to, 65535]];
  for (const p of [{pressure_size: true, pressure_min_size: 10}, {pressure_size: true, pressure_amount: true},
    {pressure_size: false, pressure_flow: true, build_up: true, flow: 50}]) {
    const on = slotFlows(full({...b, ...p}), pen), off = slotFlows(full({...still, ...p}), pen);
    assert.deepEqual(on.slots.map(v => v.slice(0, 4)), off.slots.map(v => v.slice(0, 4)), `pen slots ${tag}`);
    eq(on.stroke.result(), off.stroke.result(), `pen ${tag} ${JSON.stringify(p)}`);
  }
}
""")

    def test_reading_the_result_mid_stroke_is_withdrawn_exactly(self):
        run_editor(FOLLOW + r"""
// The live preview reads the result after every event. Held stamps it paints at Rotation alone are withdrawn
// exactly, so a stroke read throughout ends as one never read: plain, mouse and pen, every engine buffer.
const tremor = [[40, 64]]; for (let i = 0; i < 30; i++) tremor.push([40 + (i % 2 ? 0.04 : -0.04), 64]);
const path = [...tremor, [40, 100], [90, 100], [90, 40]];
const buffers = s => ['coverage', 'amounts', 'targets', 'centrality', 'strongest', 'strongestAmounts'].map(k => s[k] ? [...s[k]] : null);
for (const kind of [{}, {build_up: true, flow: 35, hardness: 30, value_profile: 'linear', scatter: 60, size_jitter: 30, angle_jitter: 20},
  {amount_jitter: 40, build_up: true, flow: 50, flow_jitter: 50, hardness: 50, value_profile: 'radial', gradient_center_x: 30}]) {
  const b = {...bar, spacing: 'auto', ...kind}, tag = JSON.stringify(kind);
  const quiet = jittered(b, path), read = new angles.JitterStroke(empty(), 128, 128, {...brush, ...b}, ...path[0]);
  read.result(); for (const p of path.slice(1)) { read.add(...p); read.result(); }
  eq(read.result(), quiet.result(), `plain ${tag}`); assert.deepEqual(buffers(read), buffers(quiet), `plain buffers ${tag}`);
  const pen = path.map((p, i) => [...p, 2000 + i * 1500]);
  const penQuiet = new angles.JitterPressureStroke(empty(), 128, 128, full(b), ...pen[0]);
  for (const p of pen.slice(1)) penQuiet.add(...p);
  const penRead = new angles.JitterPressureStroke(empty(), 128, 128, full(b), ...pen[0]);
  penRead.result(); for (const p of pen.slice(1)) { penRead.add(...p); penRead.result(); }
  eq(penRead.result(), penQuiet.result(), `pen ${tag}`); assert.deepEqual(buffers(penRead), buffers(penQuiet), `pen buffers ${tag}`);
}
// Deterministic replay: the same stroke twice is the same field.
eq(jittered({...bar, angle_jitter: 30, scatter: 40}, path).result(), jittered({...bar, angle_jitter: 30, scatter: 40}, path).result(), 'replay');
// Editor: pressing down shows one stamp at Rotation alone; once the stroke moves, it turns with the rest, no artifact left.
await reopen(empty(), {...bar});
pointer('pointerdown', 64, 20); dom.flush();
eq(session().codes, stroked({...engineBrush(), follow_direction: false}, [[64, 20]]), 'pressed');
pointer('pointermove', 64, 100); dom.flush(); pointer('pointerup', 64, 100); dom.flush();
eq(session().codes, stroked({...engineBrush(), follow_direction: false, rotation_degrees: 90}, [[64, 20], [64, 100], [64, 100]]), 'turned whole');
// A click leaves one stamp at Rotation alone, as before.
press('Clear'); click(30, 30); eq(session().codes, stroked({...engineBrush(), follow_direction: false}, [[30, 30]]), 'click');
// A Shift-click line turns its first stamp to the line's direction.
click(30, 100, {shiftKey: true});
eq(session().codes, stroked({...engineBrush(), follow_direction: false, rotation_degrees: 90}, [[30, 30], [30, 100]],
  ).map((v, i) => Math.max(v, stroked({...engineBrush(), follow_direction: false}, [[30, 30]])[i])), 'shift line');
""")


if __name__ == "__main__":
    unittest.main()
