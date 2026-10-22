"""Fenced inline Node E3 brush-engine logic tests; not real-browser interaction evidence.

Hard footprints are checked against an exact rational (Fraction) reference of the specified
transform order, soft coverage against exact or float references, and default behavior
against the retained E1 engine's bit-level golden hashes.
"""
from fractions import Fraction as Q
import json
import math
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "web/js/field_editor"
DOM = Path(__file__).with_name("field_editor_fake_dom.js")
HALF = Q(1, 2)

PRELUDE = """
import assert from 'node:assert/strict';
const engine = await import(%(engine)s);
const brushes = await import(%(brush)s);
const view = await import(%(view)s);
const ui = await import(%(ui)s);
const {installDOM, fire, descendants, settle} = await import(%(dom)s);
const brush = {tool:'paint', size:1, influence:255, hardness:100, amount:100};
const empty = () => new Uint8Array(16384);
const covered = codes => { const out = []; codes.forEach((v, i) => { if (v) out.push([i %% 128, Math.floor(i / 128)]); }); return out; };
const options = c => ({...brush, shape: c.shape, size: c.size, hardness: c.hardness ?? 100,
  falloff_curve: c.curve ?? 'smooth', scale_x: Number(c.scale_x), scale_y: Number(c.scale_y),
  rotation_degrees: c.rotation, mirror_horizontal: c.mirror_h, mirror_vertical: c.mirror_v,
  crop_left: c.crop[0], crop_right: c.crop[1], crop_top: c.crop[2], crop_bottom: c.crop[3]});
""" % {name: json.dumps(path.as_uri()) for name, path in {
    "engine": CORE / "engine.js", "brush": CORE / "brush.js", "view": CORE / "view.js",
    "ui": CORE / "editor_ui.js", "dom": DOM}.items()}

EDITOR = r"""
const dom = installDOM(); let result, cancelled = 0;
const expanded = {}, writes = [];  // Per-user preference store, shared across editor sessions.
const host = {getAdvancedExpanded: () => expanded.advanced ?? false, setAdvancedExpanded: v => { writes.push(['advanced', v]); expanded.advanced = v; },
  getGroupExpanded: key => expanded[key] ?? false, setGroupExpanded: (key, v) => { writes.push([key, v]); expanded[key] = v; },
  confirmDiscard: () => true};
const open = (codes = empty(), stored = {size: 16}) => ui.openInfluenceFieldEditor({codes, settings: stored, host,
  onDone: (codes, settings) => { result = {codes, settings}; }, onCancel: () => cancelled++});
let controller = open(); dom.flush();
const all = () => descendants(document.body), find = cls => all().find(e => e.className === cls);
const button = text => all().find(e => e.tagName === 'BUTTON' && e.textContent === text);
const press = text => { button(text).click(); dom.flush(); };
const input = label => all().find(e => e.attributes['aria-label'] === label);
const type = (label, value) => { const e = input(label); fire(e, 'pointerdown'); fire(e, 'pointerup');
  e.value = String(value); fire(window, 'keydown', {key: 'Enter', target: e}); dom.flush(); };
const canvas = () => all().find(e => e.tagName === 'CANVAS');
const preview = () => find('brush-preview'), outline = () => find('brush-outline');
const pointer = (name, x, y, extra = {}) => fire(find('viewport'), name, {clientX: 8 + x * 4, clientY: 8 + y * 4, ...extra});
const click = (x, y, extra = {}) => { pointer('pointerdown', x, y, extra); pointer('pointerup', x, y); dom.flush(); };
const settings = () => controller.session.settings;
const reopen = (codes, stored) => { controller.cancel(); controller = open(codes, stored); dom.flush(); };
const summary = () => all().find(e => e.tagName === 'SUMMARY' && e.textContent.startsWith('Advanced'));
"""

# Retained E1 engine at 8340d7d: SHA-256 of results and coverage bytes for the default brush.
E1_GOLDEN = {
    "paint-1": "740a3758d2dcd42a7cd79a904384e145fc1d2bc4797f92636b0b17a05bab8253",
    "paint-2": "0cb14ab955166024b480871b2df632654b44a5aa57138fb2c9fad91d4035fbe3",
    "paint-3": "610a86789cfbcc898910293e377d9df2988ad67ff90bb5330c8586ca8d1fa67f",
    "paint-6": "13bf49324f1bd8598edd4ecca8508f763f7b7d8c1dcc1bcbadeb9bb603a10471",
    "paint-9": "2af311e338aaf25868efdfcce01beaca181039b444ff47f877cec8ec3b83cd00",
    "paint-16": "eddd155fdd4b7ee625567d08a61e101e61bf5c5c06808775af6d471a2dc6ed83",
    "paint-33": "bbccfd0763c5bdf3138283add11ff9d5375c4a08713736e50a3353eb1a155c8f",
    "paint-128": "f1571b475b906befe600d8b0686c767255e92262fcc611011734719fcf5c6c3f",
    "erase-1": "b0c9d5c56be3543fbf89873ad739e13f794a3372a8e810964d2e3ce50038a159",
    "erase-2": "65e3df2a5ead607dba18183543dfdbc759d9f4b8e228a204becb44ef0d40f02c",
    "erase-3": "5c2e68bca4836dbfd5c43161340306dadd5527c85743c626b07126d003642ce8",
    "erase-6": "825c159e9e93b21018ee0b167ca13299311819dced79f2710f21a3247b9a66ae",
    "erase-9": "82fca9e3f06c5b6e74d40fe102dcb78b6e3d18e579bf158b86347220c0112f16",
    "erase-16": "3b2ff47723ff27931ffe78086e8028f7a391df7ee53c66bed4fcdaa44e1b25fa",
    "erase-33": "f8992ed9dfeb34b3b7fdbddd4debd8dc59d3a18f5e91ccbad304559bc7564b79",
    "erase-128": "0d057bb976c9a1474b74c33b0304853ba67a2fc7762a647de707a65992e7e4e5",
}


def run_node(body, data=None):
    source = PRELUDE + (f"const data = {json.dumps(data)};\n" if data is not None else "") + body
    result = subprocess.run(["node", "--input-type=module"], input=source, cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout or "null")


def run_editor(body, data=None):
    return run_node(EDITOR + body, data)


# ---------------------------------------------------------------------------
# Independent reference geometry: exact rationals, written from the specification.
# ---------------------------------------------------------------------------

def nearest(value):
    floor = math.floor(value)
    return floor + (1 if value - floor >= HALF else 0)


def q(delta):
    """The engine's one signed rounding: halves move away from the start value."""
    step = math.floor(abs(delta)) + (abs(delta) - math.floor(abs(delta)) >= 0.5)
    return step if delta >= 0 else -step


UNROTATE = (lambda x, y: (x, y), lambda x, y: (y, -x), lambda x, y: (-x, -y), lambda x, y: (-y, x))
CURVES = {"smooth": lambda s: s * s * (3 - 2 * s), "linear": lambda s: s,
          "sharper": lambda s: s * s * s * (s * (s * 6 - 15) + 10)}


def frame(size, crop, fit=None):
    """Crop rectangle and shape radius in cells; the cropped area's longer side fits Size."""
    left, right, top, bottom = crop
    width, height = 100 - left - right, 100 - top - bottom
    fit = fit or max(width, height)
    return {"radius": Q(50 * size, fit), "cx": Q((left - right) * size, 2 * fit),
            "cy": Q((top - bottom) * size, 2 * fit), "hx": Q(width * size, 2 * fit),
            "hy": Q(height * size, 2 * fit)}


def quarter(rotation):
    angle = rotation % 360
    assert angle % 90 == 0, rotation
    return angle // 90


def reach(shape, u, v):
    if shape == "square":
        return max(abs(u), abs(v))
    if shape == "diamond":
        return abs(u) + abs(v)
    return math.sqrt(u * u + v * v)


def member(shape, f, u, v):
    r = f["radius"]
    if shape == "disk":
        return u * u + v * v <= r * r
    return reach(shape, u, v) <= r


def anchor(config, f):
    """Hard stamps snap per axis by the parity of the frame's whole-cell extent."""
    ax, ay = f["hx"] * Q(config["scale_x"]), f["hy"] * Q(config["scale_y"])
    px, py = (ay, ax) if quarter(config["rotation"]) % 2 else (ax, ay)
    snap = lambda v, e: math.floor(v) + HALF if nearest(2 * e) % 2 else math.floor(v + HALF)
    x, y = Q(config["x"]), Q(config["y"])
    return (snap(x, px), snap(y, py)) if config.get("hardness", 100) == 100 else (x, y)


def local(config, f, dx, dy, order):
    """Map an offset from the anchor back to shape-frame (u, v), or None outside the crop."""
    sx, sy = Q(config["scale_x"]), Q(config["scale_y"])
    unrotate = UNROTATE[quarter(config["rotation"])]
    flip = lambda x, y: (-x if config["mirror_h"] else x, -y if config["mirror_v"] else y)
    inside = lambda x, y: abs(x) <= f["hx"] and abs(y) <= f["hy"]
    if order in ("specified", "fit-before-crop"):  # crop -> mirror -> scale -> rotate -> place
        x, y = unrotate(dx, dy)
        x, y = flip(x / sx, y / sy)
        return (f["cx"] + x, f["cy"] + y) if inside(x, y) else None
    if order == "mirror-before-crop":  # mirror about the shape centre, then crop
        x, y = unrotate(dx, dy)
        x, y = x / sx, y / sy
        return flip(f["cx"] + x, f["cy"] + y) if inside(x, y) else None
    if order == "rotate-before-scale":
        x, y = unrotate(dx / sx, dy / sy)
        x, y = flip(x, y)
        return (f["cx"] + x, f["cy"] + y) if inside(x, y) else None
    if order == "rotate-before-crop":  # rotate the whole shape about its centre, crop afterwards
        x, y = flip(dx / sx, dy / sy)
        return unrotate(f["cx"] + x, f["cy"] + y) if inside(x, y) else None
    raise ValueError(order)


def window(config, f, ax, ay, order="specified"):
    sx, sy = Q(config["scale_x"]), Q(config["scale_y"])
    if order == "specified":  # the transformed crop frame, exactly, plus a cell
        ex, ey = f["hx"] * sx + 1, f["hy"] * sy + 1
        if quarter(config["rotation"]) % 2:
            ex, ey = ey, ex
    else:
        ex = ey = (f["hx"] + f["hy"]) * max(sx, sy) * 2 + 1
    for row in range(max(0, math.floor(ay - ey)), min(128, math.ceil(ay + ey) + 1)):
        for col in range(max(0, math.floor(ax - ex)), min(128, math.ceil(ax + ex) + 1)):
            yield col, row, col + HALF - ax, row + HALF - ay


def hard_cells(config, order="specified"):
    spec = frame(config["size"], config["crop"])
    f = frame(config["size"], config["crop"], fit=100) if order == "fit-before-crop" else spec
    ax, ay = anchor(config, spec)
    cells = set()
    for col, row, dx, dy in window(config, spec, ax, ay, order):
        point = local(config, f, dx, dy, order)
        if point and member(config["shape"], f, *point):
            cells.add((col, row))
    return cells


def soft_coverage(config):
    f = frame(config["size"], config["crop"])
    ax, ay = anchor(config, f)
    inner, radius = Q(config["hardness"], 100) * f["radius"], f["radius"]
    coverage = {}
    for col, row, dx, dy in window(config, f, ax, ay):
        point = local(config, f, dx, dy, "specified")
        if not point:
            continue
        distance = reach(config["shape"], *point)
        if distance <= inner:
            coverage[row * 128 + col] = 1.0
        elif distance < radius:
            coverage[row * 128 + col] = float(CURVES[config["curve"]]((radius - distance) / (radius - inner)))
    return coverage


def config(shape, size, x="64.25", y="63.75", sx="1", sy="1", rotation=0, mirror=(False, False),
           crop=(0, 0, 0, 0), **extra):
    return {"shape": shape, "size": size, "x": x, "y": y, "scale_x": sx, "scale_y": sy, "rotation": rotation,
            "mirror_h": mirror[0], "mirror_v": mirror[1], "crop": list(crop), **extra}


class BrushFootprintTests(unittest.TestCase):
    def js_cells(self, configs):
        result = run_node("""
console.log(JSON.stringify(data.map(c => covered(new engine.Stroke(empty(), 128, 128, options(c), Number(c.x), Number(c.y)).result()))));
""", configs)
        return [{tuple(cell) for cell in cells} for cells in result]

    def test_identity_hard_counts_match_closed_forms_for_every_shape(self):
        counts = run_node("""
const count = (o, x, y) => new engine.Stroke(empty(), 128, 128, {...brush, ...o}, x, y).result().filter(v => v).length;
const out = {};
for (const shape of ['disk', 'square', 'diamond'])
  out[shape] = Array.from({length: 16}, (_, i) => [64.3, 20.9, 100.6].map(x => count({shape, size: i + 1}, x, 64.7)));
console.log(JSON.stringify(out));
""")
        for shape, rows in counts.items():
            for size, per_position in enumerate(rows, 1):
                self.assertEqual(len(set(per_position)), 1, (shape, size))  # snapped stamps never vary
        self.assertEqual([c[0] for c in counts["square"]], [s * s for s in range(1, 17)])
        diamond = [2 * k * k + 2 * k + 1 if s % 2 else 2 * k * (k + 1) for s in range(1, 17) for k in [s // 2]]
        self.assertEqual([c[0] for c in counts["diamond"]], diamond)
        self.assertEqual([c[0] for c in counts["disk"]][:6], [1, 4, 9, 12, 21, 32])  # retained E1 counts
        disk = [len(hard_cells(config("disk", s, x="64.3", y="64.7"))) for s in range(1, 17)]
        self.assertEqual([c[0] for c in counts["disk"]], disk)

    def test_hard_transformed_footprints_match_exact_rational_reference(self):
        configs = []
        for shape in ("disk", "square", "diamond"):
            for size in (1, 2, 5, 8, 13):
                for sx, sy in (("1", "1"), ("1.5", "1"), ("1", "0.5"), ("2", "2.5")):
                    for rotation in (0, 90):
                        configs.append(config(shape, size, sx=sx, sy=sy, rotation=rotation))
            for rotation in (180, 270, -90, 360, -270):
                configs.append(config(shape, 7, sx="1.5", sy="0.5", rotation=rotation, crop=(25, 10, 0, 30)))
            for mirror in ((True, False), (False, True), (True, True)):
                for crop in ((50, 0, 0, 0), (0, 0, 40, 0), (25, 10, 5, 30)):
                    configs.append(config(shape, 10, x="40.125", y="80.5", mirror=mirror, crop=crop))
                    configs.append(config(shape, 9, sx="2", sy="1.5", rotation=90, mirror=mirror, crop=crop))
            for crop in ((50, 0, 50, 0), (0, 50, 0, 50), (49, 50, 0, 0), (0, 0, 99, 0), (12, 37, 26, 3)):
                configs.append(config(shape, 12, crop=crop))
        for c, actual in zip(configs, self.js_cells(configs)):
            self.assertEqual(actual, hard_cells(c), c)
        # Scale X / Scale Y multiply the local axes; a crop fits its longer side to Size.
        named = {"square 4 x2": config("square", 4, sx="2"), "square 6 y.5": config("square", 6, sy="0.5"),
                 "square 8 left half": config("square", 8, crop=(50, 0, 0, 0)),
                 "square 8 quarter": config("square", 8, crop=(50, 0, 50, 0)),
                 "square 4 x2 turned": config("square", 4, sx="2", rotation=90)}
        sizes = {name: (len({x for x, _ in cells}), len({y for _, y in cells}), len(cells))
                 for name, cells in zip(named, self.js_cells(list(named.values())))}
        self.assertEqual(sizes, {"square 4 x2": (8, 4, 32), "square 6 y.5": (6, 3, 18),
                                 "square 8 left half": (4, 8, 32), "square 8 quarter": (8, 8, 64),
                                 "square 4 x2 turned": (4, 8, 32)})

    def test_transform_order_is_crop_mirror_scale_rotate_place(self):
        # Asymmetric: a quarter disk (crop keeps the lower-right quadrant), mirrored, stretched, turned.
        c = config("disk", 12, x="64.3", y="63.8", sx="1.5", rotation=90, mirror=(True, False), crop=(50, 0, 50, 0))
        actual, = self.js_cells([c])
        self.assertEqual(actual, hard_cells(c))
        for order in ("mirror-before-crop", "rotate-before-scale", "rotate-before-crop", "fit-before-crop"):
            self.assertNotEqual(actual, hard_cells(c, order), order)
        xs, ys = {x for x, _ in actual}, {y for _, y in actual}
        self.assertEqual((len(xs), len(ys)), (12, 18))  # 12x12 quadrant, x1.5 wide, then turned upright
        ax, ay = anchor(c, frame(12, c["crop"]))
        self.assertEqual((ax, ay), (64, 64))
        # The quadrant's square corner (the disk centre) is mirrored to the frame's upper right,
        # then turned clockwise to its lower right; the curved edge cuts the upper-left corner.
        self.assertIn((63, 72), actual)
        self.assertNotIn((58, 56), actual)
        # Crop before mirror: the mirrored half disk faces the other way. Anchor x = 64.5.
        half = config("disk", 10, x="64.5", y="64.5", mirror=(True, False), crop=(50, 0, 0, 0))
        mirrored, plain = self.js_cells([half, {**half, "mirror_h": False}])
        self.assertEqual(mirrored, hard_cells(half))
        self.assertEqual(mirrored, {(128 - x, y) for x, y in plain})
        self.assertNotEqual(mirrored, plain)
        self.assertEqual(hard_cells(half, "mirror-before-crop"), plain)

    def test_arbitrary_rotations_obey_independent_geometric_identities(self):
        result = run_node("""
const cells = o => covered(new engine.Stroke(empty(), 128, 128, {...brush, ...o}, 64.3, 63.8).result());
const coverage = o => engine.stampPreview(128, 128, {...brush, ...o}, 64.3, 63.8).coverage;
const out = {square45: cells({shape: 'square', size: 8, rotation_degrees: 45}),
  diamond45: cells({shape: 'diamond', size: 8, rotation_degrees: -315}),
  disk: [0, 17, 33, 45, 90.5, 200, -123.4].map(r => cells({size: 9, rotation_degrees: r})),
  disk8: [0, 33, 45].map(r => cells({size: 8, rotation_degrees: r})),
  diskScaled: [0, 33, 45, 200].map(r => cells({size: 7, scale_x: 1.5, scale_y: 1.5, rotation_degrees: r})),
  softDisk: Math.max(...[17, 45, 200].map(r => { const a = coverage({size: 15, hardness: 30}),
    b = coverage({size: 15, hardness: 30, rotation_degrees: r}); return Math.max(...a.map((v, i) => Math.abs(v - b[i]))); })),
  rect30: cells({shape: 'square', size: 10, scale_x: 2, rotation_degrees: 30}),
  quarterExact: [90, -270].map(r => cells({shape: 'square', size: 6, scale_x: 2, rotation_degrees: r}))};
console.log(JSON.stringify(out));
""")
        to_set = lambda cells: {tuple(c) for c in cells}
        # A square turned 45 degrees is the L1 ball of radius half-side*sqrt(2); corner anchors (Size 8).
        l1 = {(64 + i, 64 + j) for i in range(-6, 6) for j in range(-6, 6)
              if abs(i + 0.5) + abs(j + 0.5) <= 4 * math.sqrt(2)}
        self.assertEqual(to_set(result["square45"]), l1)
        self.assertEqual(len(l1), 60)
        # A diamond turned 45 degrees is the Chebyshev ball of radius radius/sqrt(2).
        chebyshev = {(64 + i, 64 + j) for i in range(-4, 4) for j in range(-4, 4)
                     if max(abs(i + 0.5), abs(j + 0.5)) <= 4 / math.sqrt(2)}
        self.assertEqual(to_set(result["diamond45"]), chebyshev)
        # Rotation has no visible effect on an equal-scale hard disk; soft disks agree to rounding noise.
        for group in ("disk", "disk8", "diskScaled"):
            self.assertTrue(all(to_set(cells) == to_set(result[group][0]) for cells in result[group]), group)
        self.assertLess(result["softDisk"], 1e-12)
        # Field Transform convention: clockwise, inverse mapped. 30 degrees on a 20x10 rectangle.
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        expected, margin = set(), math.inf
        for row in range(40, 90):
            for col in range(40, 90):
                dx, dy = col + 0.5 - 64, row + 0.5 - 64  # 20 and 10 are even: corner anchor (64, 64)
                x, y = c * dx + s * dy, -s * dx + c * dy
                margin = min(margin, abs(abs(x) - 10), abs(abs(y) - 5))
                if abs(x) <= 10 and abs(y) <= 5:
                    expected.add((col, row))
        self.assertGreater(margin, 1e-6)
        self.assertEqual(to_set(result["rect30"]), expected)
        self.assertEqual(to_set(result["quarterExact"][0]), to_set(result["quarterExact"][1]))

    def test_soft_coverage_matches_reference_in_the_transformed_frame(self):
        configs = []
        for shape in ("disk", "square", "diamond"):
            for curve in ("smooth", "linear", "sharper"):
                for hardness in (0, 37):
                    configs.append(config(shape, 12, hardness=hardness, curve=curve))
                    configs.append(config(shape, 9, x="40.5", y="70.25", sx="2", sy="0.5", rotation=90,
                                          hardness=hardness, curve=curve))
                    configs.append(config(shape, 10, x="80.125", y="30.5", mirror=(True, True),
                                          crop=(30, 0, 10, 25), rotation=180, hardness=hardness, curve=curve))
                    # Unsnapped soft stamps can put cell centres exactly on a crop edge: it is closed.
                    configs.append(config(shape, 8, x="64.5", y="64.25", crop=(50, 0, 0, 0),
                                          hardness=hardness, curve=curve))
        result = run_node("""
console.log(JSON.stringify(data.map(c => {
  const s = engine.stampPreview(128, 128, options(c), Number(c.x), Number(c.y));
  const stroke = new engine.Stroke(empty(), 128, 128, options(c), Number(c.x), Number(c.y));
  assert.deepEqual(stroke.coverage, s.coverage);
  return [...s.coverage.entries()].filter(([, w]) => w > 0);
})));
""", configs)
        for c, entries in zip(configs, result):
            expected, actual = soft_coverage(c), dict(entries)
            for index in set(expected) | set(actual):
                self.assertAlmostEqual(actual.get(index, 0.0), expected.get(index, 0.0), delta=1e-12,
                                       msg=(c, index))
            self.assertGreater(len(actual), 0)
            self.assertTrue(any(0 < w < 1 for w in actual.values()), c)

    def test_falloff_curves_are_the_documented_polynomials(self):
        values = run_node("""
console.log(JSON.stringify(Object.fromEntries(Object.entries(brushes.FALLOFF_CURVES).map(([k, f]) =>
  [k, [0, 0.125, 0.25, 0.5, 0.75, 1].map(f)]))));
""")
        for name, curve in CURVES.items():
            self.assertEqual(values[name], [float(curve(Q(s))) for s in ("0", "0.125", "0.25", "0.5", "0.75", "1")])
        self.assertEqual([v[3] for v in values.values()], [0.5, 0.5, 0.5])
        self.assertLess(values["sharper"][1], values["smooth"][1])
        self.assertLess(values["smooth"][1], values["linear"][1])

    def test_build_up_off_and_auto_spacing_reproduce_retained_e1_engine_bits(self):
        groups = run_node("""
const {createHash} = await import('node:crypto');
const initial = Uint8Array.from({length: 16384}, (_, i) => (i * 37 + (i >> 7) * 11) % 256);
const path = [[105.125, 57.25], [110, 70], [60, 80], [10, 10], [-5, 64.3], [130, 64.3], [64.5, 64.5]];
const result = {};
for (const explicit of [false, true]) {
  const groups = {};
  for (const tool of ['paint', 'erase']) for (const size of explicit ? [1, 9, 33] : [1, 2, 3, 6, 9, 16, 33, 128]) {
    const hash = createHash('sha256');
    for (const hardness of [0, 37, 99, 100]) for (const amount of [1, 29, 50, 100]) {
      const o = {tool, size, influence: 173, hardness, amount, ...(explicit ? brushes.BRUSH_DEFAULTS : {})};
      const s = new engine.Stroke(initial, 128, 128, o, 5.125, 7.25);
      for (const p of path) s.add(...p);
      hash.update(s.result()); hash.update(new Uint8Array(s.coverage.buffer));
    }
    groups[`${tool}-${size}`] = hash.digest('hex');
  }
  result[explicit ? 'explicit' : 'implicit'] = groups;
}
console.log(JSON.stringify(result));
""")
        self.assertEqual(groups["implicit"], E1_GOLDEN)
        self.assertEqual(groups["explicit"], {key: E1_GOLDEN[key] for key in groups["explicit"]})


class BrushBehaviorTests(unittest.TestCase):
    def test_flow_factor_mapping_and_exact_square_root_powers(self):
        rows = run_node("""
const rows = [];
for (const flow of [1, 10, 25, 50, 99, 100]) for (const spacing of [64, 77, 256, 3277, 25600]) for (const size of [1, 3, 16, 128])
  rows.push([flow, spacing, size, engine.flowFactor(flow, spacing, size)]);
console.log(JSON.stringify(rows));
""")
        for flow, spacing, size, factor in rows:
            t = min(1, spacing / (256 * size))
            self.assertAlmostEqual(factor, 1 - (1 - flow / 100) ** t, delta=1e-12, msg=(flow, spacing, size))
            if flow == 100:
                self.assertEqual(factor, 1)
            elif t == 1:
                self.assertEqual(factor, 1 - (100 - flow) / 100)
            elif spacing == 64 and size in (1, 16, 128):  # Auto: t = 2^-k is k exact square roots
                g = (100 - flow) / 100
                for _ in range({1: 2, 16: 6, 128: 9}[size]):
                    g = math.sqrt(g)
                self.assertEqual(factor, 1 - g)

    def test_build_up_accumulates_per_stamp_by_distance_and_never_exceeds_amount(self):
        result = run_node("""
const out = {};
const square = {...brush, shape: 'square', build_up: true, flow: 40};
const s = new engine.Stroke(empty(), 128, 128, square, 10.5, 20.5); s.add(20.5, 20.5);
out.factor = s.flow; out.row = [...s.coverage.slice(20 * 128 + 8, 20 * 128 + 23)];
out.codes = [...s.result().slice(20 * 128 + 8, 20 * 128 + 23)];
// Amount stays the cap however often a stroke covers a cell.
const soft = {...brush, size: 8, hardness: 37, amount: 50, build_up: true, flow: 100};
const scrub = new engine.Stroke(empty(), 128, 128, soft, 20.5, 64.5);
for (let i = 0; i < 20; i++) { scrub.add(100.5, 64.5); scrub.add(20.5, 64.5); }
out.max = Math.max(...scrub.result()); out.centre = scrub.result()[64 * 128 + 60];
out.coverageMax = Math.max(...scrub.coverage);
// Passing again in the same stroke builds up; without Build-up it does not (E1 maximum).
const passes = (n, buildUp) => { const t = new engine.Stroke(empty(), 128, 128,
  {...brush, size: 8, hardness: 0, build_up: buildUp, flow: 25}, 20.5, 64.5);
  for (let i = 0; i < n; i++) { t.add(100.5, 64.5); t.add(20.5, 64.5); } return t.result(); };
const once = passes(1, true), twice = passes(2, true);
out.accumulates = twice.every((v, i) => v >= once[i]) && twice.some((v, i) => v > once[i]);
const maxOnce = passes(1, false), maxTwice = passes(2, false);
out.maxOnly = maxOnce.every((v, i) => v === maxTwice[i]);
// One traversal of a hard Size-8 square: each interior cell gets 32 stamps, one Size of travel.
const traversal = new engine.Stroke(empty(), 128, 128, {...brush, shape: 'square', size: 8, build_up: true, flow: 25}, 20.5, 64.5);
traversal.add(100.5, 64.5);
out.traversal = [traversal.coverage[64 * 128 + 60], traversal.result()[64 * 128 + 60]];
console.log(JSON.stringify(out));
""")
        f = result["factor"]
        self.assertAlmostEqual(f, 1 - 0.6 ** 0.25, delta=1e-15)
        # Stamps every 0.25 cell from x=10.5 to 20.5; each snaps to the cell that contains it.
        stamps = [math.floor(10.5 + 0.25 * k) for k in range(41)]
        expected = []
        for col in range(8, 23):
            m = 0.0
            for _ in range(stamps.count(col)):
                m = min(1.0, m + (1 - m) * (f * 1))
            expected.append(m)
        self.assertEqual(result["row"], expected)
        self.assertEqual([stamps.count(col) for col in (10, 11, 19, 20)], [2, 4, 4, 3])
        self.assertEqual(result["codes"], [q(((255 - 0) * 100) * m / 100) for m in expected])
        self.assertAlmostEqual(expected[5], 0.4, delta=1e-12)  # four stamps = one Size of travel = Flow
        self.assertEqual((result["max"], result["centre"], result["coverageMax"]), (128, 128, 1))
        self.assertTrue(result["accumulates"])
        self.assertTrue(result["maxOnly"])
        self.assertAlmostEqual(result["traversal"][0], 0.25, delta=1e-12)
        self.assertEqual(result["traversal"][1], 64)  # q(255 x 25%) = q(63.75)

    def test_build_up_and_custom_spacing_are_exact_under_collinear_subdivision(self):
        run_node("""
for (const extra of [{build_up: true, flow: 7}, {build_up: true, flow: 63, spacing: 'custom', spacing_percent: 37},
  {spacing: 'custom', spacing_percent: 140}, {build_up: true, flow: 25, shape: 'diamond', rotation_degrees: 30, scale_x: 1.7}])
 for (const hardness of [0, 37, 100]) for (const size of [1, 2, 9, 16]) {
  const o = {...brush, size, hardness, amount: 73, ...extra}, start = [5.125, 7.25], end = [105.125, 57.25];
  const direct = new engine.Stroke(empty(), 128, 128, o, ...start), split = new engine.Stroke(empty(), 128, 128, o, ...start);
  direct.add(...end);
  for (let k = 1; k <= 50; k++) { split.add(start[0] + 2 * k, start[1] + k); split.result(); split.add(start[0] + 2 * k, start[1] + k); }
  assert.deepEqual(split.coverage, direct.coverage); assert.deepEqual(split.result(), direct.result());
  for (const p of [[110, 70], [60, 80], [10, 10]]) { direct.add(...p); split.add(...p); }
  assert.deepEqual(split.coverage, direct.coverage); assert.deepEqual(split.result(), direct.result());
 }
""")

    def test_custom_spacing_percent_of_size_dots_and_remainder_between_runs(self):
        result = run_node("""
const out = {spacing: []};
for (const size of [1, 3, 7, 16, 128]) for (const percent of [1, 10, 25, 33, 100, 250, 1000])
  out.spacing.push([size, percent, engine.stampSpacing({...brush, size, spacing: 'custom', spacing_percent: percent})]);
out.auto = [1, 16, 128].map(size => engine.stampSpacing({...brush, size}));
const dots = {...brush, shape: 'square', spacing: 'custom', spacing_percent: 1000};
let s = new engine.Stroke(empty(), 128, 128, dots, 5.5, 5.5); s.add(45.5, 5.5); out.dotted = covered(s.result());
s = new engine.Stroke(empty(), 128, 128, dots, 5.5, 5.5); s.add(20.5, 5.5); s.add(20.5, 40.5); out.turn = covered(s.result());
s = new engine.Stroke(empty(), 128, 128, {...dots, size: 4, spacing_percent: 200}, 10, 10); s.add(50, 10);
out.blocks = covered(s.result());
console.log(JSON.stringify(out));
""")
        for size, percent, units in result["spacing"]:
            exact = Q(size * percent * 256, 100)
            self.assertNotEqual(exact - math.floor(exact), HALF)
            self.assertEqual(units, nearest(exact), (size, percent))
        self.assertEqual(result["auto"], [64, 64, 64])
        self.assertEqual(result["dotted"], [[5, 5], [15, 5], [25, 5], [35, 5], [45, 5]])
        # 15 cells right: stamps at 0 and 10; the remaining 5 carry into the downward run.
        self.assertEqual(sorted(map(tuple, result["turn"])),
                         [(5, 5), (15, 5), (20, 10), (20, 20), (20, 30), (20, 40)])
        # Size 4 at 200%: stamps every 8 cells, each a 4x4 block around a corner anchor.
        blocks = {tuple(c) for c in result["blocks"]}
        self.assertEqual(blocks, {(x - 2 + i, y) for x in (10, 18, 26, 34, 42, 50) for i in range(4) for y in range(8, 12)})
        self.assertEqual(len(blocks), 96)

    def test_raise_only_lower_only_and_restore_targets_on_grayscale_fields(self):
        result = run_node("""
const base = Uint8Array.from({length: 16384}, (_, i) => (i % 128) * 2);
const source = Uint8Array.from({length: 16384}, (_, i) => 255 - (i % 128) * 2);
const out = {};
for (const tool of ['paint', 'erase', 'restore']) for (const mode of ['normal', 'raise_only', 'lower_only'])
 for (const amount of [100, 50]) {
  const s = new engine.Stroke(base, 128, 128, {...brush, tool, shape: 'square', size: 64, influence: 128, amount,
    apply_mode: mode}, 64, 64, source);
  out[`${tool}-${mode}-${amount}`] = [...s.result()];
 }
assert.throws(() => new engine.Stroke(base, 128, 128, {...brush, tool: 'restore'}, 64, 64), /opening field/);
console.log(JSON.stringify(out));
""")
        for key, codes in result.items():
            tool, mode, amount = key.split("-")
            expected = []
            for i in range(16384):
                col, row = i % 128, i // 128
                b = col * 2
                if not (32 <= col < 96 and 32 <= row < 96):
                    expected.append(b)
                    continue
                target = {"paint": 128, "erase": 0, "restore": 255 - col * 2}[tool]
                after = b + q(((target - b) * int(amount)) * 1.0 / 100)
                expected.append(max(b, after) if mode == "raise_only" else min(b, after) if mode == "lower_only" else after)
            self.assertEqual(codes, expected, key)
        # Equal target and value never move; Erase can never raise.
        self.assertEqual(result["paint-raise_only-100"][64 * 128 + 64], 128)
        self.assertEqual(result["erase-raise_only-100"], [(i % 128) * 2 for i in range(16384)])


class BrushEditorTests(unittest.TestCase):
    def test_basic_stays_basic_and_e3_controls_live_in_collapsed_advanced_groups(self):
        run_editor(r"""
const advanced = summary().parent;
assert.equal(summary().textContent, 'Advanced'); assert.equal(advanced.open, false);
const groups = advanced.children.filter(e => e.tagName === 'DETAILS');
assert.deepEqual(groups.map(g => g.children[0].textContent), ['Brush Behavior', 'Brush Shape & Transform', 'Value Profile', 'Field Tools']);
assert.ok(groups.every(g => g.open === false));
const within = (e, parent) => { for (let p = e.parent; p; p = p.parent) if (p === parent) return true; return false; };
const numbers = ['Amount (%)', 'Flow (%)', 'Spacing (% of Size)', 'Scale X', 'Scale Y', 'Rotation (°)',
  'Crop Left (%)', 'Crop Right (%)', 'Crop Top (%)', 'Crop Bottom (%)'];
const choices = ['Build-up', 'Auto', 'Custom', 'Smooth', 'Linear', 'Sharper', 'Normal', 'Raise Only', 'Lower Only',
  'Restore', 'Disk', 'Square', 'Diamond', 'Mirror H', 'Mirror V'];
for (const label of numbers) assert.ok(within(input(label), advanced), label);
for (const text of choices) assert.ok(within(button(text), advanced), text);
for (const text of ['Paint', 'Erase', 'Undo', 'Redo', 'Clear', 'Done', 'Cancel', 'Fit', '% ⇄ 0–255'])
  assert.ok(!within(button(text), advanced), text);
for (const label of ['Size (cells)', 'Influence (%)', 'Hardness (%)']) assert.ok(!within(input(label), advanced), label);
assert.equal(button('Reset Brush').hidden, true); assert.ok(!within(button('Reset Brush'), advanced));
assert.equal(all().filter(e => e.type === 'text').length, 49);
// The default footprint is E1's disk: the retained 208-cell Size-16 mark.
click(64, 64); assert.equal(controller.session.codes.filter(v => v).length, 208);
assert.equal(controller.session.history.undoEntries.length, 1);
""")

    def test_nested_group_expansion_is_a_per_user_preference_outside_session_state(self):
        run_editor(r"""
const group = title => all().find(e => e.tagName === 'SUMMARY' && e.textContent.startsWith(title)).parent;
const toggle = (title, open) => { const d = group(title); d.open = open; fire(d, 'toggle'); dom.flush(); };
const reopenSame = () => { controller.cancel(); controller = open(); dom.flush(); };
// First use: every Advanced level is collapsed and nothing is written.
assert.deepEqual([summary().parent.open, group('Brush Behavior').open, group('Brush Shape').open], [false, false, false]);
assert.deepEqual(writes, []);
const codes = controller.session.codes.slice(), stored = JSON.stringify(ui.editorSettings(settings()));
toggle('Brush Behavior', true); assert.deepEqual(writes, [['behavior', true]]);
// Not session state: no field history or settings change, so Cancel neither asks nor reverts it.
assert.equal(controller.session.history.undoEntries.length, 0); assert.deepEqual(controller.session.codes, codes);
assert.equal(JSON.stringify(ui.editorSettings(settings())), stored);
let asked = 0; host.confirmDiscard = () => { asked++; return true; };
reopenSame(); assert.equal(asked, 0); assert.equal(cancelled, 1); assert.equal(expanded.behavior, true);
assert.deepEqual([summary().parent.open, group('Brush Behavior').open, group('Brush Shape').open], [false, true, false]);
toggle('Brush Behavior', false); reopenSame(); assert.equal(group('Brush Behavior').open, false);
toggle('Brush Shape', true); reopenSame();
assert.deepEqual([group('Brush Behavior').open, group('Brush Shape').open], [false, true]);
toggle('Brush Shape', false); reopenSame(); assert.equal(group('Brush Shape').open, false);
assert.deepEqual(writes, [['behavior', true], ['behavior', false], ['shape', true], ['shape', false]]);
// Badges and Reset Brush do not depend on, or change, remembered expansion.
toggle('Brush Behavior', true); press('Square'); press('Build-up');
assert.equal(group('Brush Behavior').children[0].textContent, 'Brush Behavior · Build-up 25%');
assert.equal(group('Brush Shape').children[0].textContent, 'Brush Shape & Transform · Square');
assert.equal(summary().textContent, 'Advanced · Build-up 25% · Square'); assert.equal(button('Reset Brush').hidden, false);
press('Reset Brush'); assert.equal(summary().textContent, 'Advanced'); assert.equal(button('Reset Brush').hidden, true);
assert.equal(group('Brush Behavior').children[0].textContent, 'Brush Behavior');
assert.deepEqual([summary().parent.open, group('Brush Behavior').open, group('Brush Shape').open], [false, true, false]);
// Done stores brush settings only; expansion never enters them.
press('Done'); await settle();
assert.deepEqual(result.settings, {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent'});
assert.deepEqual(expanded, {behavior: true, shape: false});
""")

    def test_nondefault_advanced_behavior_is_badged_while_collapsed_and_reset_restores_defaults(self):
        run_editor(r"""
const behavior = () => all().find(e => e.tagName === 'SUMMARY' && e.textContent.startsWith('Brush Behavior'));
const shape = () => all().find(e => e.tagName === 'SUMMARY' && e.textContent.startsWith('Brush Shape'));
const before = controller.session.codes.slice();
press('Square'); assert.equal(summary().textContent, 'Advanced · Square');
assert.equal(shape().textContent, 'Brush Shape & Transform · Square'); assert.equal(button('Reset Brush').hidden, false);
type('Rotation (°)', 45); type('Scale X', 2.5); press('Mirror V'); type('Crop Top (%)', 20);
press('Build-up'); press('Custom'); press('Linear'); press('Lower Only'); press('Restore'); type('Amount (%)', 40);
assert.equal(behavior().textContent,
  'Brush Behavior · Amount 40% · Restore · Build-up 25% · Spacing 25% · Linear falloff · Lower Only');
assert.equal(shape().textContent, 'Brush Shape & Transform · Square · Scale 2.5×1 · Rotation 45° · Mirror V · Crop L0 R0 T20 B0');
assert.equal(summary().textContent, 'Advanced · Amount 40% · Restore · Build-up 25% · Spacing 25% · Linear falloff · ' +
  'Lower Only · Square · Scale 2.5×1 · Rotation 45° · Mirror V · Crop L0 R0 T20 B0');
assert.equal(summary().parent.open, false);
press('Reset Brush');
assert.equal(summary().textContent, 'Advanced'); assert.equal(button('Reset Brush').hidden, true);
assert.deepEqual(Object.fromEntries(Object.keys(brushes.BRUSH_DEFAULTS).map(k => [k, settings()[k]])), brushes.BRUSH_DEFAULTS);
assert.equal(settings().amount, 100); assert.equal(settings().tool, 'paint');
assert.equal(input('Rotation (°)').value, '0'); assert.equal(input('Scale X').value, '1');
assert.deepEqual(controller.session.codes, before); assert.equal(controller.session.history.undoEntries.length, 0);
// A Flow value has no effect, and no badge, while Build-up is off; enabling it shows it.
press('Build-up'); type('Flow (%)', 40); press('Build-up'); assert.equal(summary().textContent, 'Advanced');
assert.equal(settings().flow, 40); assert.equal(input('Flow (%)').parent.hidden, true);
press('Build-up'); assert.equal(summary().textContent, 'Advanced · Build-up 40%');
assert.equal(input('Flow (%)').parent.hidden, false);
press('Custom'); assert.equal(input('Spacing (% of Size)').parent.hidden, false);
press('Auto'); assert.equal(input('Spacing (% of Size)').parent.hidden, true);
// The editor's flex label rule must not override [hidden] (D1); the fake DOM has no computed style.
assert.match(all().find(e => e.tagName === 'STYLE').textContent, /\.cl-field-editor \[hidden\] \{display:none;\}/);
// View badges remain E2's and combine with brush badges.
press('Heat View'); assert.equal(summary().textContent, 'Advanced · Build-up 40% · View modified');
""")

    def test_every_e3_number_drags_types_reverts_steps_and_clamps_in_one_control(self):
        run_editor(r"""
const cases = [['Scale X', 'scale_x', 0.1, 10, 0.1, '2.5', 2.5], ['Scale Y', 'scale_y', 0.1, 10, 0.1, '0.3', 0.3],
  ['Rotation (°)', 'rotation_degrees', -360, 360, 1, '-22.5', -22.5], ['Crop Left (%)', 'crop_left', 0, 99, 1, '25', 25],
  ['Crop Right (%)', 'crop_right', 0, 99, 1, '31', 31], ['Crop Top (%)', 'crop_top', 0, 99, 1, '7', 7],
  ['Crop Bottom (%)', 'crop_bottom', 0, 99, 1, '64', 64], ['Flow (%)', 'flow', 1, 100, 1, '37', 37],
  ['Spacing (% of Size)', 'spacing_percent', 1, 1000, 1, '150', 150]];
for (const [label, key, min, max, step, typed, expected] of cases) {
  const e = input(label), integer = !['scale_x', 'scale_y', 'rotation_degrees'].includes(key);
  const round = v => { v = Math.max(min, Math.min(max, v)); return integer ? Math.round(v) : Math.round(v * 10) / 10; };
  assert.equal(e.type, 'text'); assert.equal(e.readOnly, true);
  for (const [modifier, scale] of [[{}, 1], [{shiftKey: true}, 0.1], [{ctrlKey: true}, 10]]) {
    const start = settings()[key];
    fire(e, 'pointerdown', {clientX: 100}); fire(e, 'pointermove', {clientX: 120, ...modifier});
    fire(e, 'pointerup', {clientX: 120}); dom.flush();
    assert.equal(settings()[key], round(start + 20 * step * scale), `${label} drag ${scale}`);
    assert.equal(e.value, String(settings()[key])); assert.equal(e.readOnly, true);
  }
  type(label, typed); assert.equal(settings()[key], expected, label); assert.equal(e.value, typed);
  fire(e, 'pointerdown'); fire(e, 'pointerup'); assert.equal(e.readOnly, false); e.value = '9';
  fire(window, 'keydown', {key: 'Escape', target: e}); dom.flush();
  assert.equal(settings()[key], expected); assert.equal(e.value, typed);
  fire(window, 'keydown', {key: 'ArrowUp', target: e}); dom.flush(); assert.equal(settings()[key], round(expected + step));
  fire(window, 'keydown', {key: 'ArrowDown', target: e}); dom.flush(); assert.equal(settings()[key], round(expected));
  type(label, max + 1000); assert.equal(settings()[key], max);
  type(label, min - 1000); assert.equal(settings()[key], min);
  type(label, 'abc'); assert.equal(settings()[key], min);
  press('Reset Brush');
}
// Every exact one-decimal value is reachable by typing.
for (const v of ['0.1', '7.3', '10']) { type('Scale Y', v); assert.equal(settings().scale_y, Number(v)); }
for (const v of ['-360', '359.9', '0.5']) { type('Rotation (°)', v); assert.equal(settings().rotation_degrees, Number(v)); }
// Typing into an E3 number never reaches editor shortcuts.
const e = input('Flow (%)'); fire(e, 'pointerdown'); fire(e, 'pointerup');
fire(window, 'keydown', {key: 'e', target: e}); dom.flush(); assert.equal(settings().tool, 'paint');
""")

    def test_crop_pairs_that_leave_no_area_are_rejected_visibly_never_normalized(self):
        run_editor(r"""
const error = () => find('error').textContent;
type('Crop Left (%)', 60); assert.equal(settings().crop_left, 60);
type('Crop Right (%)', 50); assert.equal(settings().crop_right, 0); assert.equal(input('Crop Right (%)').value, '0');
assert.equal(error(), 'Crop Left + Crop Right must stay below 100%. Crop Right 50% was not applied.');
type('Crop Right (%)', 39); assert.equal(settings().crop_right, 39); assert.equal(error(), '');
const right = input('Crop Right (%)');
fire(right, 'pointerdown', {clientX: 100}); fire(right, 'pointermove', {clientX: 105}); fire(right, 'pointerup', {clientX: 105});
dom.flush(); assert.equal(settings().crop_right, 39); assert.equal(right.value, '39'); assert.match(error(), /Crop Right 44%/);
type('Crop Bottom (%)', 99); type('Crop Top (%)', 1);
assert.equal(settings().crop_top, 0); assert.match(error(), /^Crop Top \+ Crop Bottom must stay below 100%/);
// Valid crops paint: the middle half of the Size-16 disk is an 8-column band.
for (const [label, value] of [['Crop Bottom (%)', 0], ['Crop Left (%)', 25], ['Crop Right (%)', 25]]) type(label, value);
click(64.5, 64.5);
assert.equal(new Set(covered(controller.session.codes).map(([x]) => x)).size, 8);
assert.throws(() => brushes.resolveBrush({crop_left: 50, crop_right: 50}), /below 100%/);
assert.throws(() => new engine.Stroke(empty(), 128, 128, {...brush, crop_top: 70, crop_bottom: 30}, 1, 1), /below 100%/);
""")

    def test_cursor_preview_is_exactly_the_next_stamp_and_shares_the_field_transform(self):
        run_editor(r"""
const alpha = i => preview().pixels[i * 4 + 3];
const check = (x, y) => {
  pointer('pointermove', x, y); dom.flush();
  const expected = engine.stampPreview(128, 128, settings(), x, y);
  assert.equal(preview().hidden, false); assert.equal(outline().style.display, '');
  for (let i = 0; i < 16384; i++) {
    const w = expected.coverage[i];
    assert.equal(alpha(i), w > 0 ? Math.max(1, Math.round(w * 160)) : 0, `cell ${i}`);
  }
  for (const layer of [preview(), outline()]) assert.equal(layer.style.transform, canvas().style.transform);
  const before = controller.session.codes.slice(), count = controller.session.history.undoEntries.length;
  click(x, y);
  const stamped = new engine.Stroke(before, 128, 128, settings(), x, y, controller.session.initial);
  assert.deepEqual(stamped.coverage, expected.coverage);
  assert.deepEqual(controller.session.codes, stamped.result());
  controller.session.undo(); assert.equal(controller.session.history.undoEntries.length, count); dom.flush();
  return expected;
};
const hard = check(40.3, 50.7);
assert.ok(hard.coverage.some(v => v === 1) && hard.coverage.every(v => v === 0 || v === 1));
Object.assign(settings(), {shape: 'square', size: 6, scale_x: 1.5, rotation_degrees: 90, crop_left: 25, mirror_horizontal: true});
check(40.3, 50.7); check(0.2, 127.9);
Object.assign(settings(), {shape: 'diamond', hardness: 40, falloff_curve: 'sharper', rotation_degrees: 33, size: 20});
const soft = check(70.25, 60.5); assert.ok(soft.coverage.some(v => v > 0 && v < 1));
// Zoom and pan: the preview stays in field coordinates.
for (let i = 0; i < 3; i++) fire(find('viewport'), 'wheel', {clientX: 300, clientY: 200, deltaY: -1});
fire(find('viewport'), 'pointerdown', {button: 1, clientX: 50, clientY: 50});
fire(find('viewport'), 'pointermove', {clientX: 90, clientY: 20}); fire(find('viewport'), 'pointerup', {button: 1}); dom.flush();
const [px, py, z] = canvas().style.transform.match(/translate\(([-\d.]+)px,([-\d.]+)px\) scale\(([-\d.]+)\)/).slice(1).map(Number);
fire(find('viewport'), 'pointermove', {clientX: px + 64.25 * z, clientY: py + 70.5 * z}); dom.flush();
const zoomed = engine.stampPreview(128, 128, settings(), 64.25, 70.5);
for (let i = 0; i < 16384; i++) assert.equal(alpha(i) > 0, zoomed.coverage[i] > 0);
for (const layer of [preview(), outline()]) assert.equal(layer.style.transform, canvas().style.transform);
// The outline strokes stay one and three screen pixels wide at any zoom.
assert.ok(Math.abs(Number(outline().children[1].attributes['stroke-width']) * z - 1) < 1e-12);
assert.ok(Math.abs(Number(outline().children[0].attributes['stroke-width']) * z - 3) < 1e-12);
// During a stroke the tint hides and the outline follows; Space-pan and leaving hide both.
fire(find('viewport'), 'pointerdown', {clientX: px + 30 * z, clientY: py + 30 * z});
fire(find('viewport'), 'pointermove', {clientX: px + 35 * z, clientY: py + 30 * z}); dom.flush();
assert.equal(preview().hidden, true); assert.equal(outline().style.display, '');
fire(find('viewport'), 'pointerup', {clientX: px + 35 * z, clientY: py + 30 * z}); dom.flush();
assert.equal(preview().hidden, false);
fire(window, 'keydown', {key: ' '}); dom.flush();
assert.equal(preview().hidden, true); assert.equal(outline().style.display, 'none');
fire(window, 'keyup', {key: ' '}); fire(find('viewport'), 'pointerleave'); dom.flush();
assert.equal(preview().hidden, true); assert.equal(outline().style.display, 'none');
// Holding E2's Compare hides both brush layers with the field; release restores them.
URL.createObjectURL = () => 'blob:reference'; URL.revokeObjectURL = () => {};
const picker = all().find(e => e.accept === 'image/*'); picker.files = [new Blob(['reference'])];
fire(picker, 'change'); await settle(); dom.flush();
fire(find('viewport'), 'pointermove', {clientX: px + 64 * z, clientY: py + 64 * z}); dom.flush();
assert.equal(preview().hidden, false);
fire(button('Hold to Compare'), 'pointerdown'); dom.flush();
assert.equal(preview().hidden, true); assert.equal(outline().style.display, 'none');
fire(button('Hold to Compare'), 'pointerup'); dom.flush();
assert.equal(preview().hidden, false); assert.equal(outline().style.display, '');
""")

    def test_outline_follows_crop_mirror_scale_rotation_and_snapped_anchor(self):
        result = run_editor(r"""
const path = () => outline().children[1].attributes.d;
Object.assign(settings(), {shape: 'square', size: 4});
pointer('pointermove', 64.2, 64.2); dom.flush();
const out = {plain: path(), shade: outline().children[0].attributes.d};
Object.assign(settings(), {scale_x: 2, rotation_degrees: 90}); dom.flush(); pointer('pointermove', 64.2, 64.2); dom.flush();
out.turned = path();
Object.assign(settings(), {shape: 'disk', size: 10, scale_x: 1, rotation_degrees: 0, crop_left: 50, mirror_horizontal: true});
pointer('pointermove', 64.5, 64.5); dom.flush(); out.half = path();
const f = brushes.prepareFootprint({...brush, ...settings()});
out.points = view.footprintOutline(f);
console.log(JSON.stringify(out));
""")
        self.assertEqual(result["plain"], "M66 66 L62 66 L62 62 L66 62 Z")
        self.assertEqual(result["shade"], result["plain"])
        self.assertEqual(result["turned"], "M62 68 L62 60 L66 60 L66 68 Z")
        # Half disk (right half kept), mirrored to face left, anchored at its crop centre.
        xs = [x for x, _ in result["points"]]
        ys = [y for _, y in result["points"]]
        self.assertAlmostEqual(min(xs), -2.5, delta=1e-12)
        self.assertAlmostEqual(max(xs), 2.5, delta=1e-12)
        self.assertAlmostEqual(max(ys) - min(ys), 10, delta=0.01)
        flat = [x for x, y in result["points"] if abs(x - 2.5) < 1e-9]
        self.assertGreaterEqual(len(flat), 2)  # the straight crop edge, now on the right

    def test_restore_paints_toward_the_session_open_field_with_amount_coverage_and_history(self):
        run_editor(r"""
const opening = Uint8Array.from({length: 16384}, (_, i) => (i * 7) % 256);
reopen(opening, {size: 8, influenceUnit: 'code'});
type('Influence (0–255)', 200); press('Fill with Influence');
assert.ok(controller.session.codes.every(v => v === 200));
press('Restore'); assert.equal(button('Restore').attributes['aria-pressed'], 'true');
assert.equal(button('Paint').attributes['aria-pressed'], 'false'); assert.equal(summary().textContent, 'Advanced · Restore');
click(64.5, 64.5);
const disk = engine.stampPreview(128, 128, settings(), 64.5, 64.5).coverage;
controller.session.codes.forEach((v, i) => assert.equal(v, disk[i] ? opening[i] : 200));
assert.deepEqual(controller.session.initial, opening); assert.equal(controller.session.history.undoEntries.length, 2);
press('Undo'); assert.ok(controller.session.codes.every(v => v === 200));
press('Redo'); controller.session.codes.forEach((v, i) => assert.equal(v, disk[i] ? opening[i] : 200));
// Amount and soft coverage still apply; the source stays the session-open field.
type('Amount (%)', 50); type('Hardness (%)', 0); click(30.25, 90.75);
const soft = new engine.Stroke(new Uint8Array(16384).fill(200), 128, 128, settings(), 30.25, 90.75, opening);
const region = [...soft.coverage.keys()].filter(i => soft.coverage[i] > 0);
assert.ok(soft.coverage.some(w => w > 0 && w < 1));
for (const i of region) assert.equal(controller.session.codes[i], soft.result()[i]);
assert.deepEqual(controller.session.initial, opening);
// Done while Restore is active stores Paint, never the session-scoped Restore.
assert.equal(settings().tool, 'restore'); press('Done'); await settle();
assert.equal(result.settings.tool, 'paint'); assert.equal(result.settings.amount, 50);
// Reopening takes the new field as the new Restore baseline.
const committed = result.codes;
controller = open(committed, result.settings); dom.flush();
assert.deepEqual(controller.session.initial, committed); assert.equal(settings().tool, 'paint');
press('Restore'); type('Amount (%)', 100); type('Hardness (%)', 100); click(64.5, 64.5);
assert.deepEqual(controller.session.codes, committed); assert.equal(controller.session.history.undoEntries.length, 0);
""")

    def test_build_up_raise_lower_and_shift_lines_are_one_history_entry_each(self):
        run_editor(r"""
const gradient = Uint8Array.from({length: 16384}, (_, i) => (i % 128) * 2);
reopen(gradient, {size: 12, influenceUnit: 'code'});
const s = () => controller.session;
for (const action of ['Square', 'Diamond', 'Disk', 'Build-up', 'Custom', 'Sharper', 'Raise Only', 'Mirror H', 'Restore',
  'Paint', 'Auto', 'Smooth', 'Normal', 'Mirror H', 'Build-up']) press(action);
for (const [label, value] of [['Scale X', 2], ['Rotation (°)', 30], ['Crop Top (%)', 20], ['Flow (%)', 30],
  ['Spacing (% of Size)', 50], ['Crop Top (%)', 0], ['Scale X', 1], ['Rotation (°)', 0]]) type(label, value);
assert.deepEqual(s().codes, gradient); assert.equal(s().history.undoEntries.length, 0);
// One Build-up scrub with many pointer events is one entry and replays the sampled path exactly.
press('Build-up'); type('Influence (0–255)', 128); press('Raise Only');
const path = [[20, 64], [100, 64], [20, 64], [100, 64.5], [60, 64.5]];
pointer('pointerdown', ...path[0]); for (const p of path.slice(1)) pointer('pointermove', ...p);
pointer('pointerup', ...path.at(-1)); dom.flush();
const replay = new engine.Stroke(gradient, 128, 128, settings(), ...path[0], s().initial);
for (const p of path.slice(1)) replay.add(...p); replay.add(...path.at(-1));
assert.deepEqual(s().codes, replay.result()); assert.equal(s().history.undoEntries.length, 1);
s().codes.forEach((v, i) => assert.ok(v >= gradient[i]));
assert.ok(s().codes.some((v, i) => v > gradient[i]));
// Lower Only Shift-click line: one entry, identical to the engine stroke from the anchor.
press('Lower Only'); press('Square'); type('Rotation (°)', 45);
const before = s().codes.slice();
pointer('pointerdown', 120.5, 20.5, {shiftKey: true}); dom.flush();
const line = new engine.Stroke(before, 128, 128, settings(), 60, 64.5, s().initial); line.add(120.5, 20.5);
assert.deepEqual(s().codes, line.result()); assert.equal(s().history.undoEntries.length, 2);
s().codes.forEach((v, i) => assert.ok(v <= before[i]));
assert.ok(s().codes.some((v, i) => v < before[i]));
""")

    def test_done_stores_only_nondefault_e3_settings_and_reopen_restores_them(self):
        run_editor(r"""
press('Done'); await settle();
assert.deepEqual(result.settings, {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent'});
controller = open(); dom.flush();
press('Square'); type('Scale X', 2.5); press('Build-up'); type('Flow (%)', 40); press('Restore');
press('Mirror V'); type('Crop Left (%)', 30); press('Done'); await settle();
const stored = {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent',
  shape: 'square', scale_x: 2.5, mirror_vertical: true, crop_left: 30, build_up: true, flow: 40};
assert.deepEqual(result.settings, stored); assert.deepEqual(Object.keys(result.settings), Object.keys(stored));
controller = open(empty(), result.settings); dom.flush();
assert.deepEqual(settings(), {...ui.editorSettings(), ...brushes.BRUSH_DEFAULTS, ...stored});
assert.equal(summary().textContent, 'Advanced · Build-up 40% · Square · Scale 2.5×1 · Mirror V · Crop L30 R0 T0 B0');
assert.equal(ui.editorSettings(result.settings).flow, 40);
// Cancel discards settings changes and never calls Done.
const done = result; type('Rotation (°)', 15); controller.cancel(); assert.equal(result, done); assert.equal(cancelled, 1);
// Stored settings are sanitized like E1's: invalid values and impossible crop pairs fall back to defaults.
assert.deepEqual(ui.editorSettings({shape: 'hexagon', scale_x: 0.05, scale_y: 1.25, rotation_degrees: 400,
  crop_left: 60, crop_right: 50, crop_top: 30, crop_bottom: 20, falloff_curve: 'cubic', build_up: 'yes', flow: 0,
  spacing: 'custom', spacing_percent: 1001, apply_mode: 'raise_only', mirror_horizontal: 1, tool: 'restore'}),
  {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent',
   crop_top: 30, crop_bottom: 20, spacing: 'custom', apply_mode: 'raise_only'});
""")

    def test_e3_modules_are_host_free_and_trigonometry_is_confined_to_footprint_preparation(self):
        brush = (CORE / "brush.js").read_text(encoding="utf-8")
        engine = (CORE / "engine.js").read_text(encoding="utf-8")
        view = (CORE / "view.js").read_text(encoding="utf-8")
        self.assertEqual([line for line in brush.splitlines() if line.startswith("import")], ['import {PARTICLE_SHAPES, PROCEDURAL_TYPES, PROCEDURAL_VERSION, proceduralTip} from "./procedural_tip.js";', 'import {sampleTip} from "./tip_sampling.js";'])
        self.assertEqual([line for line in engine.splitlines() if line.startswith("import")],
                         ['import {footprintLocal, localCoverage, prepareFootprint, resolveBrush, snapAnchor} from "./brush.js";',
                          'import {prepareProfile, profileTarget} from "./value_profile.js";'])
        self.assertEqual([line for line in view.splitlines() if line.startswith("import")],
                         ['import {footprintToCell} from "./brush.js";'])
        self.assertEqual((brush.count("Math.sin("), brush.count("Math.cos(")), (1, 1))
        prepare = brush[brush.index("export function prepareFootprint"):brush.index("export function snapAnchor")]
        self.assertIn("Math.sin(", prepare)
        self.assertIn("Math.cos(", prepare)
        for forbidden in ("Math.random", "Math.pow", "Math.hypot", "Math.exp", "Math.log", "**", "Date.",
                          "scripts/app", "fetch(", "document", "window"):
            self.assertNotIn(forbidden, brush, forbidden)
        for forbidden in ("Math.sin", "Math.cos", "Math.pow", "**"):
            self.assertNotIn(forbidden, engine, forbidden)
        run_node("assert.equal(globalThis.document, undefined); assert.equal(globalThis.window, undefined);")


if __name__ == "__main__":
    unittest.main()
