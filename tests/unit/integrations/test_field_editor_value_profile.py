"""Fenced inline Node E4 value-profile tests; not real-browser interaction evidence.

Gradient targets are checked against an independent 50-digit Decimal oracle of design record
§9, evaluated in the documented brush-local frame with exact rationals for the brush transform.
The curve and rounding definition is checked against a bit-exact Python replica, Uniform
against retained E1 and E3 golden hashes, and the overlap rule against stroke properties.
"""
from decimal import Decimal, localcontext
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
const engine = await import(@ENGINE@);
const brushes = await import(@BRUSH@);
const profiles = await import(@PROFILE@);
const view = await import(@VIEW@);
const ui = await import(@UI@);
const {installDOM, fire, descendants, settle} = await import(@DOM@);
const brush = {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100};
const empty = () => new Uint8Array(16384);
const options = c => ({...brush, shape: c.shape, size: c.size, scale_x: Number(c.sx), scale_y: Number(c.sy),
  rotation_degrees: c.rotation, mirror_horizontal: c.mirror[0], mirror_vertical: c.mirror[1], crop_left: c.crop[0],
  crop_right: c.crop[1], crop_top: c.crop[2], crop_bottom: c.crop[3], ...c.gradient});
"""
for token, path in {"@ENGINE@": CORE / "engine.js", "@BRUSH@": CORE / "brush.js", "@PROFILE@": CORE / "value_profile.js",
                    "@VIEW@": CORE / "view.js", "@UI@": CORE / "editor_ui.js", "@DOM@": DOM}.items():
    PRELUDE = PRELUDE.replace(token, json.dumps(path.as_uri()))

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
const drag = (label, dx, extra = {}) => { const e = input(label); fire(e, 'pointerdown', {clientX: 100});
  fire(e, 'pointermove', {clientX: 100 + dx, ...extra}); fire(e, 'pointerup', {clientX: 100 + dx}); dom.flush(); };
const canvas = () => all().find(e => e.tagName === 'CANVAS');
const preview = () => find('brush-preview');
const pointer = (name, x, y, extra = {}) => fire(find('viewport'), name, {clientX: 8 + x * 4, clientY: 8 + y * 4, ...extra});
const click = (x, y, extra = {}) => { pointer('pointerdown', x, y, extra); pointer('pointerup', x, y); dom.flush(); };
const settings = () => controller.session.settings;
const reopen = (codes, stored) => { controller.cancel(); controller = open(codes, stored); dom.flush(); };
const summary = () => all().find(e => e.tagName === 'SUMMARY' && e.textContent.startsWith('Advanced'));
const heading = title => all().find(e => e.tagName === 'SUMMARY' && e.textContent.startsWith(title));
const small = prefix => all().find(e => e.tagName === 'SMALL' && e.textContent?.startsWith(prefix));
const error = () => find('error').textContent;
const COMMON = ['Start Value (0–255)', 'End Value (0–255)', 'Curve (exponent)'];
const LINEAR = ['Gradient Angle (°)', 'Start Position (%)', 'End Position (%)'];
const CENTRED = ['Center X (%)', 'Center Y (%)', 'Inner (%)', 'Outer (%)', 'Aspect X', 'Aspect Y', 'Gradient Rotation (°)'];
const visible = () => [...COMMON, ...LINEAR, ...CENTRED].filter(label => !input(label).parent.hidden);
"""

# Retained E1 engine at 8340d7d: SHA-256 of results and coverage bytes for the default brush.
E1_GOLDEN = {
    "paint-1": "740a3758d2dcd42a7cd79a904384e145fc1d2bc4797f92636b0b17a05bab8253",
    "paint-9": "2af311e338aaf25868efdfcce01beaca181039b444ff47f877cec8ec3b83cd00",
    "paint-33": "bbccfd0763c5bdf3138283add11ff9d5375c4a08713736e50a3353eb1a155c8f",
    "erase-1": "b0c9d5c56be3543fbf89873ad739e13f794a3372a8e810964d2e3ce50038a159",
    "erase-9": "82fca9e3f06c5b6e74d40fe102dcb78b6e3d18e579bf158b86347220c0112f16",
    "erase-33": "f8992ed9dfeb34b3b7fdbddd4debd8dc59d3a18f5e91ccbad304559bc7564b79",
}

# Retained E3 engine at 2680bfa: SHA-256 of results and coverage bytes for non-default E3 brushes.
E3_CASES = {
    "square-soft-30": {"shape": "square", "size": 9, "hardness": 37, "rotation_degrees": 30, "scale_x": 1.5, "amount": 73},
    "diamond-sharper-mirror-crop": {"shape": "diamond", "size": 17, "hardness": 0, "falloff_curve": "sharper",
                                    "mirror_horizontal": True, "crop_left": 25},
    "disk-linear-crop-turned": {"size": 33, "hardness": 60, "falloff_curve": "linear", "scale_y": 0.4,
                                "rotation_degrees": -123.4, "crop_top": 10, "crop_bottom": 35, "amount": 29},
    "hard-build-up-7": {"size": 12, "build_up": True, "flow": 7},
    "soft-build-up-custom": {"size": 20, "hardness": 50, "build_up": True, "flow": 63, "spacing": "custom",
                             "spacing_percent": 37, "amount": 50},
    "square-dots-raise": {"shape": "square", "size": 6, "spacing": "custom", "spacing_percent": 140, "apply_mode": "raise_only"},
    "erase-lower": {"tool": "erase", "size": 16, "hardness": 20, "apply_mode": "lower_only"},
    "restore-turned-mirror": {"tool": "restore", "size": 24, "hardness": 40, "amount": 60, "rotation_degrees": 90,
                              "mirror_vertical": True},
    "diamond-128-build-up": {"shape": "diamond", "size": 128, "hardness": 0, "build_up": True, "flow": 100},
    "size-1": {"size": 1},
    "disk-scaled-quarter": {"size": 14, "scale_x": 2.5, "scale_y": 0.7, "crop_left": 50, "crop_top": 50, "rotation_degrees": 270},
    "square-45-lower": {"shape": "square", "size": 10, "rotation_degrees": 45, "apply_mode": "lower_only", "amount": 88},
}
E3_GOLDEN = {
    "square-soft-30": "ec2535d3e71972672f86f670cdcf0648574ab8c7e4112e4f44413bf3b61e5df3",
    "diamond-sharper-mirror-crop": "8d54682915de15a5b16e8350472b449e6508880041afb22431f60d6edf7a5ee3",
    "disk-linear-crop-turned": "775c9cdacf0e1bfb3f7eeda02293044f17d63e919c98a0b6411fbf1da423e9fe",
    "hard-build-up-7": "947d156e1d181ffdf165b4e71f260e247c43eb6fc7ea641ef0bb71540f841a13",
    "soft-build-up-custom": "ba29ab8ff98c849bcbf09578960fa924ed55706821b1246fda8b5cde9eee424b",
    "square-dots-raise": "e444cc4758be40fc07ea78978cc45975293488bffd503a87e543059750b37d17",
    "erase-lower": "c22fc25ac4296300a73cc3af871a83d8c49c06dee684d8b814a504ae431008e9",
    "restore-turned-mirror": "f4e4faf0ce55fd4685ba9efdddb1892a4e4513fedc08a0faf0cffd93c0d92b69",
    "diamond-128-build-up": "d65b6596eb3fe142ed0248ec51bfb16dc5d4a6e5ffe6701f52be6180a32c0af6",
    "size-1": "20325cfa1dc01ab58423af4b97c5934501eebdc453d978c9b7661beded748f5a",
    "disk-scaled-quarter": "52fc65138030d4251cdd5cf740ab31a9a3fa55badfa5194020ccc8583fed95d0",
    "square-45-lower": "72e86ce4549243dab314b282dd21372f3cd00c599b5c348b26fa81f7155876d2",
}

# E4 settings that must be inert while the profile is Uniform.
INERT = {"value_profile": "uniform", "gradient_start": 3, "gradient_end": 250, "gradient_curve": 4.2,
         "gradient_angle": 33, "gradient_start_position": 20, "gradient_end_position": 21, "gradient_center_x": 7,
         "gradient_center_y": 93, "gradient_inner": 40, "gradient_outer": 41, "gradient_aspect_x": 0.3,
         "gradient_aspect_y": 7.5, "gradient_rotation": -71.5}


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
# Independent reference: the brush transform in exact rationals, design record §9 in Decimal.
# ---------------------------------------------------------------------------

UNROTATE = (lambda x, y: (x, y), lambda x, y: (y, -x), lambda x, y: (-x, -y), lambda x, y: (-y, x))


def nearest(value):
    floor = math.floor(value)
    return floor + (1 if value - floor >= HALF else 0)


def half_up(value):
    """q: the target's one rounding, half up."""
    floor = math.floor(value)
    return floor + (1 if value - floor >= Decimal("0.5") else 0)


def case(gradient, shape="disk", size=16, x="64.25", y="63.75", sx="1", sy="1", rotation=0,
         mirror=(False, False), crop=(0, 0, 0, 0)):
    return {"gradient": gradient, "shape": shape, "size": size, "x": x, "y": y, "sx": sx, "sy": sy,
            "rotation": rotation, "mirror": list(mirror), "crop": list(crop)}


def hard_stamp(c, frame="specified"):
    """Covered cells of one hard click -> profile-frame (u, v), exact rationals.

    Specified: undo rotation (quarter turns), scale and mirror, then divide by the crop
    rectangle's half extents. Other frames are wrong on purpose; the footprint itself always
    follows the specified order, so only the profile's frame differs.
    """
    left, right, top, bottom = c["crop"]
    width, height = 100 - left - right, 100 - top - bottom
    fit, size, shape = max(width, height), c["size"], c["shape"]
    radius = Q(50 * size, fit)
    cx, cy = Q((left - right) * size, 2 * fit), Q((top - bottom) * size, 2 * fit)
    hx, hy = Q(width * size, 2 * fit), Q(height * size, 2 * fit)
    sx, sy = Q(c["sx"]), Q(c["sy"])
    assert c["rotation"] % 90 == 0, c
    turn = c["rotation"] % 360 // 90
    px, py = (hy * sy, hx * sx) if turn % 2 else (hx * sx, hy * sy)
    snap = lambda v, e: math.floor(v) + HALF if nearest(2 * e) % 2 else math.floor(v + HALF)
    ax, ay = snap(Q(c["x"]), px), snap(Q(c["y"]), py)
    flip = lambda x, y: (-x if c["mirror"][0] else x, -y if c["mirror"][1] else y)
    cells = {}
    for row in range(max(0, math.floor(ay - py) - 2), min(128, math.ceil(ay + py) + 2)):
        for col in range(max(0, math.floor(ax - px) - 2), min(128, math.ceil(ax + px) + 2)):
            dx, dy = col + HALF - ax, row + HALF - ay
            x, y = UNROTATE[turn](dx, dy)
            x, y = flip(x / sx, y / sy)
            if abs(x) > hx or abs(y) > hy:
                continue
            u, v = cx + x, cy + y
            if not (u * u + v * v <= radius * radius if shape == "disk" else
                    max(abs(u), abs(v)) <= radius if shape == "square" else abs(u) + abs(v) <= radius):
                continue
            if frame == "field":  # ignores the brush transform
                x, y = dx, dy
            elif frame == "shape":  # the uncropped shape square instead of the crop rectangle
                x, y = u * hx / radius, v * hy / radius
            elif frame == "unmirrored":
                x, y = flip(x, y)
            elif frame == "unscaled":
                x, y = x * sx, y * sy
            elif frame == "twice":  # the inverse rotation applied again
                x, y = UNROTATE[turn](x, y)
            cells[row * 128 + col] = (x / hx, y / hy)
    return cells


def axis(degrees):
    angle = Q(str(degrees)) % 360
    if angle % 45 == 0:
        h = Decimal("0.5").sqrt()
        return [(1, 0), (h, h), (0, 1), (-h, h), (-1, 0), (-h, -h), (0, -1), (h, -h)][int(angle / 45)]
    radians = math.radians(float(angle))
    return Decimal(math.cos(radians)), Decimal(math.sin(radians))


def oracle(g, u, v):
    """Start + t^Curve (End - Start) at profile-frame (u, v), to 50 digits (design record §9)."""
    with localcontext() as context:
        context.prec = 50
        u, v = Decimal(u.numerator) / u.denominator, Decimal(v.numerator) / v.denominator
        kind = g["value_profile"]
        if kind == "linear":
            c, s = axis(g.get("gradient_angle", 0))
            rho = 50 * (u * c + v * s + 1)
            low, high = g.get("gradient_start_position", 0), g.get("gradient_end_position", 100)
        else:
            ax, ay = Decimal(str(g.get("gradient_aspect_x", 1))), Decimal(str(g.get("gradient_aspect_y", 1)))
            c, s = axis(0 if kind == "radial" and ax == ay else g.get("gradient_rotation", 0))
            du = u - Decimal(g.get("gradient_center_x", 50) - 50) / 50
            dv = v - Decimal(g.get("gradient_center_y", 50) - 50) / 50
            lx, ly = (c * du + s * dv) / ax, (-s * du + c * dv) / ay
            rho = 100 * ((lx * lx + ly * ly).sqrt() if kind == "radial" else max(abs(lx), abs(ly)))
            low, high = g.get("gradient_inner", 0), g.get("gradient_outer", 100)
        t = min(Decimal(1), max(Decimal(0), (rho - low) / (high - low)))
        start, end = g.get("gradient_start", 255), g.get("gradient_end", 0)
        power = t ** Decimal(str(g.get("gradient_curve", 1))) if t else Decimal(0)
        return start + power * (end - start)


def curve_power(t, c):
    """Bit-exact replica of the documented square-root construction of t^c."""
    result, fraction = 1.0, c - math.floor(c)
    for _ in range(math.floor(c)):
        result *= t
    root = t
    while fraction > 0 and root < 1:
        root, fraction = math.sqrt(root), fraction * 2
        if fraction >= 1:
            result, fraction = result * root, fraction - 1
    return result


def gradient_code(start, end, curve, t):
    value = start + curve_power(t, curve) * (end - start)
    floor = math.floor(value)
    return floor + (1 if value - floor >= 0.5 else 0)


TARGETS = """
console.log(JSON.stringify(data.map(c => {
  const o = options(c), p = engine.stampPreview(128, 128, o, Number(c.x), Number(c.y));
  const stroke = new engine.Stroke(empty(), 128, 128, o, Number(c.x), Number(c.y));
  // A click keeps exactly the previewed coverage and targets.
  assert.deepEqual(stroke.coverage, p.coverage); assert.deepEqual(stroke.targets, p.targets);
  return [...p.coverage.keys()].filter(i => p.coverage[i] > 0).map(i => [i, p.targets[i]]);
})));
"""


class ProfileOracleTests(unittest.TestCase):
    def assert_code(self, actual, value, context):
        fraction = value - math.floor(value)
        if fraction != Decimal("0.5"):  # exact ties round up; nothing may sit within 1e-9 of one
            self.assertGreater(abs(fraction - Decimal("0.5")), Decimal("1e-9"), context)
        self.assertEqual(actual, half_up(value), context)

    def assert_oracle(self, cases):
        for c, entries in zip(cases, run_node(TARGETS, cases)):
            expected, actual = hard_stamp(c), dict(entries)
            self.assertEqual(set(actual), set(expected), c)  # the footprint is E3's
            self.assertGreater(len(expected), 0, c)
            for index, (u, v) in expected.items():
                self.assert_code(actual[index], oracle(c["gradient"], u, v), (c, index))
            yield c, actual

    def test_linear_targets_match_the_oracle_for_direction_endpoints_span_and_curve(self):
        lin = lambda **g: {"value_profile": "linear", **g}
        cases = [case(lin()), case(lin(gradient_start=0, gradient_end=255)),
                 case(lin(gradient_start=128, gradient_end=128)),
                 case(lin(gradient_start=0, gradient_end=255, gradient_angle=90)),
                 case(lin(gradient_start=0, gradient_end=255, gradient_angle=45)),
                 case(lin(gradient_start=0, gradient_end=255, gradient_angle=-30)),
                 case(lin(gradient_start=10, gradient_end=240, gradient_angle=-135)),
                 case(lin(gradient_start=0, gradient_end=255, gradient_start_position=25, gradient_end_position=75)),
                 case(lin(gradient_start=0, gradient_end=255, gradient_angle=200.5, gradient_start_position=40,
                          gradient_end_position=45))]
        for curve in (0.1, 0.5, 1, 2.5, 10):
            cases.append(case(lin(gradient_start=0, gradient_end=255, gradient_curve=curve, gradient_angle=60)))
        cases += [case(lin(gradient_start=64, gradient_end=192, gradient_angle=180, gradient_start_position=10,
                           gradient_end_position=90, gradient_curve=1.7), shape="square", size=9, x="40.5", y="80.25"),
                  case(lin(gradient_curve=3), shape="diamond", size=13, x="100", y="20.5"),
                  case(lin(gradient_start=1, gradient_end=254, gradient_angle=-360), size=128, x="64", y="64")]
        results = dict((json.dumps(c), actual) for c, actual in self.assert_oracle(cases))
        get = lambda c: results[json.dumps(c)]
        # Readable identities: equal endpoints are uniform; 255->0 mirrors 0->255 left to right.
        self.assertEqual(set(get(cases[2]).values()), {128})
        ascending, descending = get(cases[1]), get(cases[0])
        self.assertEqual(len(set(ascending.values())), 16)  # one code per column of the Size-16 disk
        for index, code in ascending.items():
            col, row = index % 128, index // 128
            self.assertEqual(descending[row * 128 + 127 - col], code)  # the anchor is (64, 64)
        # Partial span: codes outside the 25..75% transition clamp to Start or End.
        span = get(cases[7])
        self.assertEqual({code for index, code in span.items() if index % 128 < 60}, {0})
        self.assertEqual({code for index, code in span.items() if index % 128 >= 68}, {255})

    def test_radial_targets_match_the_oracle_for_center_extents_aspect_and_curve(self):
        rad = lambda **g: {"value_profile": "radial", **g}
        cases = [case(rad()), case(rad(gradient_start=0, gradient_end=255)),
                 case(rad(gradient_center_x=25, gradient_center_y=70)),
                 case(rad(gradient_inner=40, gradient_outer=90)),
                 case(rad(gradient_inner=0, gradient_outer=300, gradient_center_x=0, gradient_center_y=0)),
                 case(rad(gradient_aspect_x=2, gradient_aspect_y=0.5, gradient_rotation=30)),
                 case(rad(gradient_aspect_x=1.5, gradient_aspect_y=1.5, gradient_rotation=77)),
                 case(rad(gradient_curve=0.3, gradient_start=0, gradient_end=200)),
                 case(rad(gradient_curve=4, gradient_inner=10)),
                 case(rad(gradient_start=30, gradient_end=30)),
                 case(rad(gradient_center_x=60, gradient_aspect_x=0.5), shape="square", size=21, sx="2", sy="0.5",
                      rotation=90, crop=(25, 0, 0, 10), mirror=(True, False), x="70.5", y="50.25"),
                 case(rad(gradient_inner=50, gradient_outer=51), shape="diamond", size=31, x="20.75", y="99")]
        results = [actual for _, actual in self.assert_oracle(cases)]
        self.assertEqual(set(results[9].values()), {30})
        # A true circle ignores Rotation; the same circle without it is identical.
        same = run_node(TARGETS, [case(rad(gradient_aspect_x=1.5, gradient_aspect_y=1.5))])[0]
        self.assertEqual(results[6], dict(same))
        # Centred 255->0: the centre four cells are the highest code, the rim the lowest.
        centred = results[0]
        self.assertEqual(max(centred.values()), centred[63 * 128 + 63])

    def test_square_targets_match_the_oracle_for_center_extents_aspect_rotation_and_curve(self):
        sq = lambda **g: {"value_profile": "square", **g}
        cases = [case(sq()), case(sq(gradient_start=0, gradient_end=255, gradient_inner=50)),
                 case(sq(gradient_center_x=10, gradient_center_y=90)),
                 case(sq(gradient_inner=30, gradient_outer=120)),
                 case(sq(gradient_aspect_x=1.5)), case(sq(gradient_rotation=45)), case(sq(gradient_rotation=30)),
                 case(sq(gradient_rotation=-90, gradient_aspect_y=2)),
                 case(sq(gradient_curve=0.7, gradient_start=20, gradient_end=220)),
                 case(sq(gradient_curve=6)),
                 case(sq(gradient_aspect_x=2.5), shape="square", size=12, sy="0.5", rotation=270,
                      crop=(0, 20, 30, 0), mirror=(False, True), x="30", y="30.5")]
        results = [actual for _, actual in self.assert_oracle(cases)]
        # Square contours: a Size-16 square brush keeps rings of equal code.
        ring = run_node(TARGETS, [case(sq(), shape="square", x="64", y="64")])[0]
        by_ring = {}
        for index, code in ring:
            col, row = index % 128, index // 128
            by_ring.setdefault(max(abs(col + 0.5 - 64), abs(row + 0.5 - 64)), set()).add(code)
        self.assertTrue(all(len(codes) == 1 for codes in by_ring.values()))
        self.assertEqual(len(by_ring), 8)
        self.assertNotEqual(results[5], results[0])  # 45 degrees turns the contours into diamonds

    def test_profile_frame_is_the_transformed_crop_rectangle_in_the_documented_order(self):
        # Asymmetric on purpose: a cropped, mirrored, stretched, turned disk with an off-axis gradient.
        gradient = {"value_profile": "linear", "gradient_angle": 30, "gradient_start": 0, "gradient_end": 255,
                    "gradient_start_position": 10, "gradient_end_position": 80, "gradient_curve": 1.5}
        c = case(gradient, size=14, crop=(30, 0, 0, 20), mirror=(True, False), sx="1.5", sy="0.5",
                 rotation=90, x="60.5", y="70.25")
        (_, actual), = self.assert_oracle([c])
        for frame in ("field", "shape", "unmirrored", "unscaled", "twice"):
            wrong = {i: half_up(oracle(gradient, *uv)) for i, uv in hard_stamp(c, frame).items()}
            self.assertNotEqual(actual, wrong, frame)
        result = run_node("""
const codes = (o, x = 64, y = 64) => [...new engine.Stroke(empty(), 128, 128, {...brush, ...o}, x, y).result()];
const lin = {value_profile: 'linear', gradient_start: 0, gradient_end: 255};
const out = {
  // Crop: the profile spans the cropped footprint, so a half square still runs 0..255 across.
  cropped: codes({...lin, shape: 'square', crop_left: 50}),
  // Mirror and quarter turns carry the gradient with the footprint.
  plain: codes({...lin, shape: 'square'}), mirrored: codes({...lin, shape: 'square', mirror_horizontal: true}),
  turned: codes({...lin, shape: 'square', rotation_degrees: 90}), angled: codes({...lin, shape: 'square', gradient_angle: 90}),
  // Scale X stretches the profile with the footprint: Size 8 x2 has Size 16's columns.
  stretched: codes({...lin, shape: 'square', size: 8, scale_x: 2}),
  // Brush rotation and gradient angle add within the brush frame.
  both: codes({...lin, shape: 'square', rotation_degrees: 90, gradient_angle: 90}),
  opposite: codes({...lin, shape: 'square', gradient_angle: 180}),
};
console.log(JSON.stringify(out));
""")
        grid = lambda codes: [codes[row * 128:(row + 1) * 128] for row in range(128)]
        cropped = grid(result["cropped"])  # an 8 x 16 half square around its crop centre, the anchor
        self.assertEqual(cropped[60][60:68], [16, 48, 80, 112, 143, 175, 207, 239])
        self.assertEqual((cropped[60][59], cropped[60][68]), (0, 0))
        plain, mirrored, turned = grid(result["plain"]), grid(result["mirrored"]), grid(result["turned"])
        stretched = grid(result["stretched"])
        for row in range(56, 72):
            for col in range(56, 72):
                self.assertEqual(mirrored[row][col], plain[row][127 - col])
                # Turned 90 clockwise about the corner anchor (64, 64).
                self.assertEqual(turned[row][col], plain[127 - col][row])
        self.assertEqual(result["turned"], result["angled"])
        self.assertEqual(result["both"], result["opposite"])
        self.assertEqual(stretched[61][56:72], plain[61][56:72])
        self.assertEqual(len({code for code in result["stretched"] if code}), 16)


class ProfileEngineTests(unittest.TestCase):
    def test_uniform_reproduces_retained_e1_and_e3_bits_with_e4_absent_default_or_inert(self):
        groups = run_node("""
const {createHash} = await import('node:crypto');
const initial = Uint8Array.from({length: 16384}, (_, i) => (i * 37 + (i >> 7) * 11) % 256);
const opening = Uint8Array.from({length: 16384}, (_, i) => (i * 101 + 7) % 256);
const path = [[105.125, 57.25], [110, 70], [60, 80], [10, 10], [-5, 64.3], [130, 64.3], [64.5, 64.5]];
const out = {e1: {}, e3: {}};
const e4 = Object.fromEntries(Object.entries(brushes.BRUSH_DEFAULTS).filter(([k]) => k === 'value_profile' || k.startsWith('gradient_')));
assert.equal(Object.keys(e4).length, 14);
for (const [variant, extra] of Object.entries({absent: {}, defaults: e4, inert: data.inert})) {
  const e1 = {}, e3 = {};
  for (const tool of ['paint', 'erase']) for (const size of [1, 9, 33]) {
    const hash = createHash('sha256');
    for (const hardness of [0, 37, 99, 100]) for (const amount of [1, 29, 50, 100]) {
      const s = new engine.Stroke(initial, 128, 128, {tool, size, influence: 173, hardness, amount, ...extra}, 5.125, 7.25);
      for (const p of path) s.add(...p);
      assert.equal(s.targets, null);
      hash.update(s.result()); hash.update(new Uint8Array(s.coverage.buffer));
    }
    e1[`${tool}-${size}`] = hash.digest('hex');
  }
  for (const [name, options] of Object.entries(data.cases)) {
    const o = {tool: 'paint', influence: 173, hardness: 100, amount: 100, ...options, ...extra};
    const s = new engine.Stroke(initial, 128, 128, o, 5.125, 7.25, opening);
    for (const p of path) s.add(...p);
    e3[name] = createHash('sha256').update(s.result()).update(new Uint8Array(s.coverage.buffer)).digest('hex');
  }
  out.e1[variant] = e1; out.e3[variant] = e3;
  // A Uniform preview has no targets: the E3 tint.
  assert.equal(engine.stampPreview(128, 128, {...brush, ...extra}, 64, 64).targets, null);
}
console.log(JSON.stringify(out));
""", {"inert": INERT, "cases": E3_CASES})
        for variant in ("absent", "defaults", "inert"):
            self.assertEqual(groups["e1"][variant], E1_GOLDEN, variant)
            self.assertEqual(groups["e3"][variant], E3_GOLDEN, variant)

    def test_equal_start_and_end_is_uniform_at_that_code_bit_for_bit(self):
        run_node("""
const field = Uint8Array.from({length: 16384}, (_, i) => (i * 37) % 256);
for (const value_profile of ['linear', 'radial', 'square']) for (const build_up of [false, true])
 for (const hardness of [0, 50, 100]) for (const apply_mode of ['normal', 'raise_only', 'lower_only']) {
  const o = {...brush, size: 20, hardness, build_up, flow: 30, amount: 70, apply_mode, shape: 'diamond',
    rotation_degrees: 20, crop_top: 15};
  const a = new engine.Stroke(field, 128, 128, {...o, influence: 99}, 10.3, 20.7);
  const b = new engine.Stroke(field, 128, 128, {...o, value_profile, gradient_start: 99, gradient_end: 99,
    gradient_curve: 2.3, gradient_angle: 17, gradient_inner: 20}, 10.3, 20.7);
  for (const p of [[100.2, 40.9], [30, 110.4], [31, 110.4]]) { a.add(...p); b.add(...p); }
  assert.deepEqual(b.coverage, a.coverage); assert.deepEqual(b.result(), a.result());
  assert.ok(b.targets.every((t, i) => t === 99 || b.coverage[i] === 0));
 }
""")

    def test_a_true_circle_ignores_rotation_bit_for_bit_and_an_ellipse_turns(self):
        run_node("""
const f = brushes.prepareFootprint({...brush, size: 24});
const prepared = o => profiles.prepareProfile(brushes.resolveBrush({value_profile: 'radial', gradient_aspect_x: 1.5,
  gradient_aspect_y: 1.5, gradient_center_x: 37, ...o}), f);
let seed = 11;
const random = () => (seed = seed * 16807 % 2147483647) / 2147483647;
const points = Array.from({length: 2000}, () => [24 * random() - 12, 24 * random() - 12]);
const plain = prepared({}), ellipse = prepared({gradient_aspect_y: 1.4});
for (const gradient_rotation of [30, 77, 123.4, -71.5]) {
  // As Field Fade: equal aspects skip Rotation, so a circle's transition never changes, even in its last bit.
  const turned = prepared({gradient_rotation});
  for (const [x, y] of points) assert.equal(profiles.profileTransition(turned, x, y), profiles.profileTransition(plain, x, y));
  const turnedEllipse = prepared({gradient_aspect_y: 1.4, gradient_rotation});
  assert.ok(points.some(([x, y]) => profiles.profileTransition(turnedEllipse, x, y) !== profiles.profileTransition(ellipse, x, y)));
}
""")

    def test_hardness_and_falloff_change_coverage_not_targets_and_curve_changes_targets_not_coverage(self):
        run_node("""
// (64, 64) is where a hard Size-24 stamp snaps, so hard and soft stamps share the anchor.
const at = o => engine.stampPreview(128, 128, {...brush, size: 24, value_profile: 'radial', gradient_start: 0,
  gradient_end: 255, gradient_center_x: 30, gradient_aspect_x: 1.5, gradient_rotation: 20, ...o}, 64, 64);
const hard = at({});
for (const o of [{hardness: 0}, {hardness: 37, falloff_curve: 'linear'}, {hardness: 80, falloff_curve: 'sharper'}]) {
  const soft = at(o);
  assert.notDeepEqual(soft.coverage, hard.coverage);
  // Every cell both cover keeps its target: footprint and profile share one position.
  for (let i = 0; i < 16384; i++) if (soft.coverage[i] > 0 && hard.coverage[i] > 0) assert.equal(soft.targets[i], hard.targets[i]);
}
for (const gradient_curve of [0.3, 2.5, 7]) {
  const curved = at({hardness: 40, gradient_curve}), plain = at({hardness: 40});
  assert.deepEqual(curved.coverage, plain.coverage); assert.notDeepEqual(curved.targets, plain.targets);
}
// Strokes too: Hardness never moves a target, Curve never moves coverage.
const stroke = o => { const s = new engine.Stroke(empty(), 128, 128, {...brush, size: 16, value_profile: 'linear',
  gradient_angle: 30, build_up: true, flow: 40, ...o}, 20.5, 64.5); s.add(90.5, 70.5); return s; };
const b = stroke({hardness: 30}), c = stroke({hardness: 30, gradient_curve: 3});
assert.deepEqual(c.coverage, b.coverage); assert.notDeepEqual(c.targets, b.targets);
""")

    def test_overlap_keeps_the_strongest_then_most_central_then_earlier_stamp(self):
        run_node("""
const lin = {...brush, value_profile: 'linear', gradient_start: 0, gradient_end: 255};  // varies along x
const drag = (o, from, to) => { const s = new engine.Stroke(empty(), 128, 128, o, from, 64); s.add(to, 64); return s; };
const right = drag(lin, 40, 80), left = drag(lin, 80, 40);
const click = x => engine.stampPreview(128, 128, lin, x, 64).targets;
// Hard Size 16 snaps to cell corners: anchors c and c + 1 are equally central for column c.
// Moving right, anchor c comes first; moving left, c + 1 does.
for (let col = 50; col < 70; col++) for (let row = 57; row < 71; row++) {
  const i = row * 128 + col;
  assert.equal(right.targets[i], click(col)[i]); assert.equal(left.targets[i], click(col + 1)[i]);
}
assert.notDeepEqual(right.targets, left.targets);
// A radial profile leaves a ridge (design record §9): the most central stamp's values, constant
// along the stroke and highest on its line.
const radial = {...brush, value_profile: 'radial'}, ridge = drag(radial, 40, 80).result();
for (let row = 56; row < 72; row++) for (let col = 50; col < 70; col++) {
  assert.equal(ridge[row * 128 + col], ridge[row * 128 + 50]);
  assert.equal(ridge[row * 128 + col], engine.stampPreview(128, 128, radial, col, 64).targets[row * 128 + col]);
}
assert.equal(Math.max(...ridge), ridge[63 * 128 + 60]); assert.ok(ridge[63 * 128 + 60] > ridge[57 * 128 + 60]);
// Soft brushes: the strongest stamp wins, which for a disk is the nearest one.
const soft = {...lin, hardness: 0, size: 12};
const s = drag(soft, 20.5, 100.5);
for (let col = 30; col < 90; col++) assert.equal(s.targets[64 * 128 + col], engine.stampPreview(128, 128, soft, col + 0.5, 64).targets[64 * 128 + col]);
// Build-up accumulates coverage but selects targets the same way, at any Flow.
for (const flow of [1, 10, 90, 100]) {
  const b = drag({...lin, build_up: true, flow}, 40, 80);
  assert.deepEqual(b.targets, right.targets);
  if (flow < 100) assert.notDeepEqual(b.coverage, right.coverage);
  const uniform = drag({...brush, build_up: true, flow}, 40, 80);
  assert.deepEqual(b.coverage, uniform.coverage);
}
""")

    def test_build_up_flow_and_amount_move_each_cell_toward_its_own_target(self):
        data = run_node("""
const base = Uint8Array.from({length: 16384}, (_, i) => (i * 29 + 11) % 256);
const out = [];
for (const [flow, amount, passes] of [[10, 60, 1], [10, 60, 6], [90, 100, 2], [100, 50, 20]]) {
  const o = {...brush, size: 12, hardness: 30, value_profile: 'linear', gradient_angle: 90, gradient_start: 0,
    gradient_end: 255, build_up: true, flow, amount};
  const s = new engine.Stroke(base, 128, 128, o, 20.5, 64.25);
  for (let k = 0; k < passes; k++) { s.add(100.5, 64.25); s.add(20.5, 64.25); }
  // Pointer-event count never matters: the same path in many collinear pieces is identical.
  const split = new engine.Stroke(base, 128, 128, o, 20.5, 64.25);
  for (let k = 0; k < passes; k++) { for (let x = 22.5; x <= 100.5; x += 2) split.add(x, 64.25); for (let x = 98.5; x >= 20.5; x -= 2) split.add(x, 64.25); }
  assert.deepEqual(split.coverage, s.coverage); assert.deepEqual(split.targets, s.targets); assert.deepEqual(split.result(), s.result());
  out.push({amount, coverage: [...s.coverage], targets: [...s.targets], result: [...s.result()]});
}
console.log(JSON.stringify({base: [...base], strokes: out}));
""")
        base = data["base"]
        for stroke in data["strokes"]:
            covered = 0
            for i in range(16384):
                m, target = stroke["coverage"][i], stroke["targets"][i]
                delta = ((target - base[i]) * stroke["amount"]) * m / 100
                step = math.floor(abs(delta)) + (abs(delta) - math.floor(abs(delta)) >= 0.5)
                self.assertEqual(stroke["result"][i], base[i] + (step if delta >= 0 else -step), i)
                if m > 0:
                    covered += 1
                    # A vertical gradient on a horizontal stroke: the target depends on the row only.
                    self.assertEqual(target, stroke["targets"][(i // 128) * 128 + 64])
            self.assertGreater(covered, 900)
            rows = {stroke["targets"][row * 128 + 64] for row in range(58, 71)}
            self.assertGreater(len(rows), 10)  # never one target for the whole brush
        # Twenty full-Flow passes at Amount 50 reach exactly half way to each cell's own target.
        last = data["strokes"][3]
        for i in range(16384):
            if last["coverage"][i] == 1:
                delta = (last["targets"][i] - base[i]) * 50 / 100
                self.assertEqual(last["result"][i], base[i] + (1 if delta >= 0 else -1) * nearest(abs(Q(delta))))

    def test_raise_only_and_lower_only_compare_each_cell_with_its_own_target(self):
        gradient = {"value_profile": "linear", "gradient_start": 0, "gradient_end": 255}
        c = case(gradient, shape="square", size=32, x="64", y="64")
        expected_targets = {i: half_up(oracle(gradient, *uv)) for i, uv in hard_stamp(c).items()}
        result = run_node("""
const base = new Uint8Array(16384).fill(128), out = {};
for (const apply_mode of ['normal', 'raise_only', 'lower_only']) for (const amount of [100, 50])
  out[`${apply_mode}-${amount}`] = [...new engine.Stroke(base, 128, 128, {...options(data), apply_mode, amount}, 64, 64).result()];
console.log(JSON.stringify(out));
""", c)
        self.assertTrue(any(t > 128 for t in expected_targets.values()) and any(t < 128 for t in expected_targets.values()))
        for key, codes in result.items():
            mode, amount = key.rsplit("-", 1)
            for i in range(16384):
                if i not in expected_targets:
                    self.assertEqual(codes[i], 128)
                    continue
                delta = Q((expected_targets[i] - 128) * int(amount), 100)
                after = 128 + (1 if delta >= 0 else -1) * nearest(abs(delta))
                want = max(128, after) if mode == "raise_only" else min(128, after) if mode == "lower_only" else after
                self.assertEqual(codes[i], want, (key, i))

    def test_erase_and_restore_ignore_the_profile_but_keep_footprint_coverage(self):
        run_node("""
const base = Uint8Array.from({length: 16384}, (_, i) => (i * 13) % 256);
const opening = Uint8Array.from({length: 16384}, (_, i) => 255 - (i * 7) % 256);
const gradient = {value_profile: 'radial', gradient_start: 0, gradient_end: 255, gradient_curve: 2};
for (const tool of ['erase', 'restore']) for (const hardness of [0, 60, 100]) for (const build_up of [false, true]) {
  const o = {...brush, tool, size: 30, hardness, build_up, amount: 70};
  const plain = new engine.Stroke(base, 128, 128, o, 30.5, 40.25, opening), graded = new engine.Stroke(base, 128, 128, {...o, ...gradient}, 30.5, 40.25, opening);
  for (const p of [[90, 80.5], [91, 20]]) { plain.add(...p); graded.add(...p); }
  assert.equal(graded.profile, null); assert.equal(graded.targets, null);
  assert.deepEqual(graded.coverage, plain.coverage); assert.deepEqual(graded.result(), plain.result());
  assert.equal(engine.stampPreview(128, 128, {...o, ...gradient}, 64, 64).targets, null);
  if (hardness < 100) assert.ok(graded.coverage.some(w => w > 0 && w < 1));
}
// The same gradient paints with Paint.
assert.notEqual(new engine.Stroke(base, 128, 128, {...brush, ...gradient}, 64, 64).profile, null);
""")

    def test_curve_and_rounding_are_exactly_specified_and_the_level_table_equals_them(self):
        samples = [0, 5e-324, 1e-300, 1e-30, 1e-9, 0.001, 0.1, 0.25, 0.3, 1 / 3, 0.5, 0.7, 0.9, 0.999999, 1 - 2 ** -53, 1]
        curves = [round(0.1 * k, 1) for k in range(1, 101)]
        result = run_node("""
const out = {powers: data.curves.map(c => data.t.map(t => profiles.curvePower(t, c))),
  codes: [[0, 255], [255, 0], [3, 250], [200, 200], [64, 65]].map(([a, b]) => data.curves.filter((_, k) => k % 7 === 0)
    .map(c => data.t.map(t => profiles.gradientCode(a, b, c, t))))};
// The per-profile level table returns gradientCode exactly, at and next to every threshold.
const view64 = new DataView(new ArrayBuffer(8));
const next = (x, d) => { view64.setFloat64(0, x); view64.setBigUint64(0, view64.getBigUint64(0) + BigInt(d)); return view64.getFloat64(0); };
const f = brushes.prepareFootprint({...brush});
let seed = 7, checked = 0;
const random = () => (seed = seed * 16807 % 2147483647) / 2147483647;
for (const [start, end, curve] of [[0, 255, 0.1], [255, 0, 10], [3, 250, 1.7], [200, 200, 3], [0, 1, 0.3], [255, 254, 1], [17, 220, 2.5]]) {
  const p = profiles.prepareProfile(brushes.resolveBrush({value_profile: 'linear', gradient_start: start, gradient_end: end, gradient_curve: curve}), f);
  assert.equal(p.levels.length, Math.abs(end - start));
  const points = [0, 1, 5e-324, 1 - 2 ** -53];
  for (const level of p.levels) points.push(level, next(level, -1), next(level, 1));
  for (let k = 0; k < 3000; k++) points.push(random());
  for (const t of points) if (t >= 0 && t <= 1) { assert.equal(profiles.transitionCode(p, t), profiles.gradientCode(start, end, curve, t)); checked++; }
  // The definition is monotone in t, from Start to End.
  let last = start;
  for (let k = 0; k <= 4096; k++) { const code = profiles.gradientCode(start, end, curve, k / 4096); assert.ok(Math.sign(end - start) * (code - last) >= 0); last = code; }
  assert.equal(last, end);
}
out.checked = checked;
console.log(JSON.stringify(out));
""", {"t": samples, "curves": curves})
        for c, row in zip(curves, result["powers"]):
            for t, power in zip(samples, row):
                self.assertEqual(power, curve_power(t, c), (t, c))  # bit for bit
                with localcontext() as context:
                    context.prec = 40
                    exact = Decimal(t) ** Decimal(str(c)) if t else Decimal(0)
                    self.assertLessEqual(abs(Decimal(power) - exact), exact * Decimal("1e-13") + Decimal("1e-300"), (t, c))
        for (a, b), table in zip([[0, 255], [255, 0], [3, 250], [200, 200], [64, 65]], result["codes"]):
            for c, row in zip([c for k, c in enumerate(curves) if k % 7 == 0], table):
                self.assertEqual(row, [gradient_code(a, b, c, t) for t in samples], (a, b, c))
        self.assertGreater(result["checked"], 20000)

    def test_profile_settings_are_validated_and_never_normalized(self):
        run_node("""
const bad = [[{gradient_start_position: 50, gradient_end_position: 50}, /Start Position must stay below End Position/],
  [{gradient_start_position: 80, gradient_end_position: 20}, /Start Position must stay below End Position/],
  [{gradient_inner: 100, gradient_outer: 100}, /Inner must stay below Outer/],
  [{gradient_inner: 120, gradient_outer: 40}, /Inner must stay below Outer/],
  [{value_profile: 'conical'}, /Invalid brush value_profile/], [{gradient_start: 256}, /Invalid brush gradient_start/],
  [{gradient_end: 1.5}, /Invalid brush gradient_end/], [{gradient_curve: 0}, /Invalid brush gradient_curve/],
  [{gradient_curve: 10.1}, /Invalid brush gradient_curve/], [{gradient_center_x: 101}, /Invalid brush gradient_center_x/],
  [{gradient_outer: 301}, /Invalid brush gradient_outer/], [{gradient_aspect_y: 0.05}, /Invalid brush gradient_aspect_y/],
  [{gradient_angle: 361}, /Invalid brush gradient_angle/], [{gradient_rotation: '5'}, /Invalid brush gradient_rotation/]];
for (const [o, message] of bad) {
  assert.throws(() => brushes.resolveBrush(o), message);
  assert.throws(() => new engine.Stroke(empty(), 128, 128, {...brush, value_profile: 'linear', ...o}, 64, 64), message);
}
// Equal and descending values are valid gradients; Uniform validates its stored geometry too.
for (const o of [{gradient_start: 7, gradient_end: 7}, {gradient_start: 255, gradient_end: 0}, {gradient_start: 0, gradient_end: 255}])
  assert.ok(brushes.resolveBrush({value_profile: 'square', ...o}));
assert.throws(() => brushes.resolveBrush({value_profile: 'uniform', gradient_inner: 9, gradient_outer: 9}), /Inner/);
""")

    def test_value_profile_module_is_host_free_and_exactly_specified(self):
        source = (CORE / "value_profile.js").read_text(encoding="utf-8")
        engine = (CORE / "engine.js").read_text(encoding="utf-8")
        self.assertEqual([line for line in source.splitlines() if line.startswith("import")], [])
        self.assertEqual((source.count("Math.sin("), source.count("Math.cos(")), (1, 1))
        axis_body = source[source.index("function axis"):source.index("export function curvePower")]
        self.assertIn("Math.sin(", axis_body)
        self.assertIn("Math.cos(", axis_body)
        self.assertEqual(source.count("axis("), 3)  # the definition and its two calls in prepareProfile
        prepare = source[source.index("export function prepareProfile"):source.index("export function profileTransition")]
        self.assertEqual(prepare.count("axis("), 2)
        for forbidden in ("Math.random", "Math.pow", "Math.hypot", "Math.exp", "Math.log", "**", "Date.",
                          "scripts/app", "fetch(", "document", "window"):
            self.assertNotIn(forbidden, source, forbidden)
        for forbidden in ("Math.sin", "Math.cos", "Math.pow", "**"):
            self.assertNotIn(forbidden, engine, forbidden)
        run_node("assert.equal(globalThis.document, undefined); assert.equal(globalThis.window, undefined);")


class ProfileEditorTests(unittest.TestCase):
    def test_value_profile_is_a_collapsed_advanced_group_and_basic_is_unchanged(self):
        run_editor(r"""
const advanced = summary().parent, groups = advanced.children.filter(e => e.tagName === 'DETAILS');
assert.deepEqual(groups.map(g => g.children[0].textContent), ['Brush Behavior', 'Brush Shape & Transform', 'Value Profile', 'Field Tools']);
const group = groups[2]; assert.equal(group.open, false); assert.equal(advanced.open, false);
const within = (e, parent) => { for (let p = e.parent; p; p = p.parent) if (p === parent) return true; return false; };
for (const label of [...COMMON, ...LINEAR, ...CENTRED]) assert.ok(within(input(label), group), label);
for (const text of ['Uniform', 'Linear Gradient', 'Radial Gradient', 'Square Gradient', 'Swap Start/End']) assert.ok(within(button(text), group), text);
assert.equal(button('Uniform').attributes['aria-pressed'], 'true');
for (const label of ['Size (cells)', 'Influence (%)', 'Hardness (%)']) assert.ok(!within(input(label), advanced), label);
assert.equal(all().filter(e => e.type === 'text').length, 49);
assert.equal(small('Paint targets'), undefined); assert.equal(button('Reset Brush').hidden, true);
click(64, 64); assert.equal(controller.session.codes.filter(v => v === 255).length, 208);
assert.equal(controller.session.history.undoEntries.length, 1);
""")

    def test_rows_follow_the_chosen_profile_and_hidden_rows_really_disappear(self):
        run_editor(r"""
const swap = () => !button('Swap Start/End').parent.hidden, help = () => small('Start Value');
assert.deepEqual(visible(), []); assert.equal(swap(), false); assert.equal(help().hidden, true);
press('Linear Gradient'); assert.deepEqual(visible(), [...COMMON, ...LINEAR]); assert.equal(swap(), true);
assert.equal(help().hidden, false); assert.match(help().textContent, /^Start Value sits at Start Position .* crops, mirrors, scales and turns with the brush/);
assert.equal(button('Linear Gradient').attributes['aria-pressed'], 'true'); assert.equal(button('Uniform').attributes['aria-pressed'], 'false');
press('Radial Gradient'); assert.deepEqual(visible(), [...COMMON, ...CENTRED]); assert.match(help().textContent, /^Start Value fills Inner/);
press('Square Gradient'); assert.deepEqual(visible(), [...COMMON, ...CENTRED]);
press('Uniform'); assert.deepEqual(visible(), []); assert.equal(swap(), false);
assert.match(all().find(e => e.tagName === 'STYLE').textContent, /\.cl-field-editor \[hidden\] \{display:none;\}/);
// Hiding keeps values: switching profiles never resets the other profile's geometry.
press('Linear Gradient'); type('Gradient Angle (°)', 30); press('Square Gradient'); type('Inner (%)', 20);
press('Linear Gradient'); press('Radial Gradient');
assert.equal(settings().gradient_angle, 30); assert.equal(settings().gradient_inner, 20);
assert.deepEqual(controller.session.history.undoEntries, []);
""")

    def test_influence_stays_visible_but_never_mixes_with_gradient_targets(self):
        run_editor(r"""
reopen(empty(), {size: 16, influenceUnit: 'code'});
press('Linear Gradient');
const note = small('Paint targets');
assert.equal(note.hidden, false); assert.equal(note.textContent, 'Paint targets Linear gradient 255→0 (Value Profile), not Influence.');
assert.equal(input('Influence (0–255)').parent.hidden, false); assert.equal(input('Influence (0–255)').readOnly, true);
const strokes = [];
for (const value of [0, 77, 255]) {
  type('Influence (0–255)', value); click(64, 64); strokes.push(controller.session.codes.slice()); controller.session.undo();
}
assert.deepEqual(strokes[0], strokes[1]); assert.deepEqual(strokes[1], strokes[2]);
assert.deepEqual(strokes[0], new engine.Stroke(empty(), 128, 128, settings(), 64, 64).result());
assert.equal(new Set(strokes[0].filter(v => v)).size, 16);  // one code per column of the Size-16 disk
// Fill still uses Influence, and the chips, digits and eyedropper still set it.
press('Fill with Influence'); assert.ok(controller.session.codes.every(v => v === 255));
press('50%'); assert.equal(settings().influence, 128); assert.equal(settings().gradient_start, 255);
type('Start Value (0–255)', 10); assert.equal(note.textContent, 'Paint targets Linear gradient 10→0 (Value Profile), not Influence.');
press('Erase'); assert.equal(note.hidden, true); press('Paint'); assert.equal(note.hidden, false);
press('Uniform'); assert.equal(note.hidden, true);
""")

    def test_badges_reset_brush_and_the_next_default_stroke(self):
        run_editor(r"""
const profile = () => heading('Value Profile').textContent;
press('Radial Gradient');
assert.equal(profile(), 'Value Profile · Radial gradient · 255→0'); assert.equal(summary().textContent, 'Advanced · Radial gradient · 255→0');
assert.equal(button('Reset Brush').hidden, false); assert.equal(summary().parent.open, false);
type('Start Value (0–255)', 64); type('End Value (0–255)', 192); type('Curve (exponent)', 2.5);
assert.equal(profile(), 'Value Profile · Radial gradient · 64→192 · Curve 2.5');
press('Erase'); assert.equal(profile(), 'Value Profile · Radial gradient · 64→192 · Curve 2.5 · inactive for Erase');
press('Restore'); assert.equal(profile(), 'Value Profile · Radial gradient · 64→192 · Curve 2.5 · inactive for Restore');
press('Paint'); press('Square');
assert.equal(summary().textContent, 'Advanced · Square · Radial gradient · 64→192 · Curve 2.5');
press('Linear Gradient'); assert.equal(profile(), 'Value Profile · Linear gradient · 64→192 · Curve 2.5');
// Under Uniform the gradient values do nothing, so they are not flagged (as E3's Flow).
press('Uniform'); assert.equal(profile(), 'Value Profile'); assert.equal(summary().textContent, 'Advanced · Square');
press('Square Gradient'); type('Gradient Rotation (°)', 45); type('Inner (%)', 30);
press('Reset Brush');
assert.deepEqual(Object.fromEntries(Object.keys(brushes.BRUSH_DEFAULTS).map(k => [k, settings()[k]])), brushes.BRUSH_DEFAULTS);
assert.equal(summary().textContent, 'Advanced'); assert.equal(profile(), 'Value Profile'); assert.equal(button('Reset Brush').hidden, true);
assert.deepEqual(visible(), []); assert.equal(input('Start Value (0–255)').value, '255'); assert.equal(input('Inner (%)').value, '0');
assert.deepEqual(controller.session.history.undoEntries, []);
// The next default stroke is the retained default stroke, bit for bit.
click(64.3, 63.7);
assert.deepEqual(controller.session.codes, new engine.Stroke(empty(), 128, 128, {tool: 'paint', size: 16, influence: 255,
  hardness: 100, amount: 100}, 64.3, 63.7).result());
assert.equal(controller.session.codes.filter(v => v).length, 208);
""")

    def test_every_e4_number_drags_types_reverts_steps_and_clamps_in_one_control(self):
        run_editor(r"""
const cases = [['Start Value (0–255)', 'gradient_start', 0, 255, 1, true, '173', 'Linear Gradient'],
  ['End Value (0–255)', 'gradient_end', 0, 255, 1, true, '64', 'Radial Gradient'],
  ['Curve (exponent)', 'gradient_curve', 0.1, 10, 0.1, false, '2.5', 'Square Gradient'],
  ['Gradient Angle (°)', 'gradient_angle', -360, 360, 1, false, '-22.5', 'Linear Gradient'],
  ['Start Position (%)', 'gradient_start_position', 0, 100, 1, true, '35', 'Linear Gradient'],
  ['End Position (%)', 'gradient_end_position', 0, 100, 1, true, '65', 'Linear Gradient'],
  ['Center X (%)', 'gradient_center_x', 0, 100, 1, true, '25', 'Radial Gradient'],
  ['Center Y (%)', 'gradient_center_y', 0, 100, 1, true, '80', 'Square Gradient'],
  ['Inner (%)', 'gradient_inner', 0, 300, 1, true, '40', 'Radial Gradient'],
  ['Outer (%)', 'gradient_outer', 0, 300, 1, true, '250', 'Square Gradient'],
  ['Aspect X', 'gradient_aspect_x', 0.1, 10, 0.1, false, '2.5', 'Radial Gradient'],
  ['Aspect Y', 'gradient_aspect_y', 0.1, 10, 0.1, false, '0.3', 'Square Gradient'],
  ['Gradient Rotation (°)', 'gradient_rotation', -360, 360, 1, false, '33.3', 'Radial Gradient']];
// Positions and extents keep their order: a value that would break it is rejected, not adjusted.
const PARTNER = {gradient_start_position: ['gradient_end_position', -1], gradient_end_position: ['gradient_start_position', 1],
  gradient_inner: ['gradient_outer', -1], gradient_outer: ['gradient_inner', 1]};
const allowed = (key, v) => !PARTNER[key] || Math.sign(v - settings()[PARTNER[key][0]]) === PARTNER[key][1];
for (const [label, key, min, max, step, integer, typed, profile] of cases) {
  press(profile); const e = input(label);
  const round = v => { v = Math.max(min, Math.min(max, v)); return integer ? Math.round(v) : Math.round(v * 10) / 10; };
  const accept = (v, before) => allowed(key, v) ? v : before;
  assert.equal(e.parent.hidden, false); assert.equal(e.type, 'text'); assert.equal(e.readOnly, true);
  for (const [modifier, scale] of [[{}, 1], [{shiftKey: true}, 0.1], [{ctrlKey: true}, 10]]) {
    const start = settings()[key];
    drag(label, 20, modifier);
    assert.equal(settings()[key], accept(round(start + 20 * step * scale), start), `${label} drag ${scale}`);
    assert.equal(e.value, String(settings()[key])); assert.equal(e.readOnly, true);
  }
  type(label, typed); assert.equal(settings()[key], Number(typed), label); assert.equal(e.value, typed);
  fire(e, 'pointerdown'); fire(e, 'pointerup'); assert.equal(e.readOnly, false); e.value = '9';
  fire(window, 'keydown', {key: 'Escape', target: e}); dom.flush();
  assert.equal(settings()[key], Number(typed)); assert.equal(e.value, typed);
  fire(window, 'keydown', {key: 'ArrowUp', target: e}); dom.flush(); assert.equal(settings()[key], round(Number(typed) + step));
  fire(window, 'keydown', {key: 'ArrowDown', target: e}); dom.flush(); assert.equal(settings()[key], round(Number(typed)));
  let before = settings()[key]; type(label, max + 1000); assert.equal(settings()[key], accept(max, before));
  before = settings()[key]; type(label, min - 1000); assert.equal(settings()[key], accept(min, before));
  before = settings()[key]; type(label, 'abc'); assert.equal(settings()[key], before);
  press('Reset Brush');
}
// Every exact one-decimal value is reachable by typing.
press('Square Gradient');
for (const v of ['0.1', '7.3', '10']) { type('Curve (exponent)', v); assert.equal(settings().gradient_curve, Number(v)); }
for (const v of ['-360', '359.9', '0.5']) { type('Gradient Rotation (°)', v); assert.equal(settings().gradient_rotation, Number(v)); }
// Typing into an E4 number never reaches editor shortcuts, and no number touches field history.
const e = input('Center X (%)'); fire(e, 'pointerdown'); fire(e, 'pointerup');
fire(window, 'keydown', {key: 'e', target: e}); dom.flush(); assert.equal(settings().tool, 'paint');
assert.deepEqual(controller.session.history.undoEntries, []); assert.ok(controller.session.codes.every(v => v === 0));
""")

    def test_ordered_pairs_are_rejected_visibly_and_swap_exchanges_values_exactly(self):
        run_editor(r"""
press('Linear Gradient');
type('End Position (%)', 50); type('Start Position (%)', 90);
assert.equal(settings().gradient_start_position, 0); assert.equal(input('Start Position (%)').value, '0');
assert.equal(error(), 'Start Position must stay below End Position. Start Position 90% was not applied.');
type('Start Position (%)', 49); assert.equal(settings().gradient_start_position, 49); assert.equal(error(), '');
type('End Position (%)', 49); assert.equal(settings().gradient_end_position, 50);
assert.equal(error(), 'Start Position must stay below End Position. End Position 49% was not applied.');
drag('End Position (%)', -5); assert.equal(settings().gradient_end_position, 50); assert.equal(input('End Position (%)').value, '50');
assert.match(error(), /End Position 45% was not applied/);
fire(window, 'keydown', {key: 'ArrowDown', target: input('End Position (%)')}); dom.flush();
assert.equal(settings().gradient_end_position, 50); assert.match(error(), /End Position 49% was not applied/);
press('Radial Gradient');
type('Inner (%)', 100); assert.equal(settings().gradient_inner, 0);
assert.equal(error(), 'Inner must stay below Outer. Inner 100% was not applied.');
type('Outer (%)', 0); assert.equal(settings().gradient_outer, 100); assert.match(error(), /^Inner must stay below Outer. Outer 0%/);
type('Inner (%)', 99); type('Outer (%)', 300); assert.deepEqual([settings().gradient_inner, settings().gradient_outer], [99, 300]);
// Swap exchanges the values exactly, as a setting: no field or history change.
type('Start Value (0–255)', 30); type('End Value (0–255)', 200);
press('Swap Start/End');
assert.deepEqual([settings().gradient_start, settings().gradient_end], [200, 30]);
assert.deepEqual([input('Start Value (0–255)').value, input('End Value (0–255)').value], ['200', '30']);
assert.deepEqual(controller.session.history.undoEntries, []); assert.ok(controller.session.codes.every(v => v === 0));
// A value still being typed is committed first, then swapped.
const e = input('Start Value (0–255)'); fire(e, 'pointerdown'); fire(e, 'pointerup'); e.value = '17';
press('Swap Start/End'); assert.deepEqual([settings().gradient_start, settings().gradient_end], [30, 17]);
// Equal values are a valid gradient: a uniform target at that code.
type('End Value (0–255)', 30); click(64, 64);
assert.deepEqual(new Set(controller.session.codes), new Set([0, 30]));
""")

    def test_preview_shows_exact_targets_and_coverage_and_heat_view_is_display_only(self):
        run_editor(r"""
let heat = false;
const check = (x, y) => {
  pointer('pointermove', x, y); dom.flush();
  const expected = engine.stampPreview(128, 128, settings(), x, y), pixels = preview().pixels;
  assert.ok(expected.targets); assert.equal(preview().hidden, false);
  for (let i = 0; i < 16384; i++) {
    const w = expected.coverage[i], t = expected.targets[i], px = [...pixels.slice(i * 4, i * 4 + 4)];
    if (w > 0) assert.deepEqual(px, [...(heat ? view.heatColor(t) : [t, t, t]), Math.max(1, Math.round(w * 160))], `cell ${i}`);
    else assert.deepEqual(px, [0, 0, 0, 0]);
  }
  assert.equal(preview().style.transform, canvas().style.transform);
  const before = controller.session.codes.slice(), count = controller.session.history.undoEntries.length;
  click(x, y);
  const stamped = new engine.Stroke(before, 128, 128, settings(), x, y, controller.session.initial);
  assert.deepEqual(stamped.coverage, expected.coverage); assert.deepEqual(stamped.targets, expected.targets);
  assert.deepEqual(controller.session.codes, stamped.result());
  controller.session.undo(); assert.equal(controller.session.history.undoEntries.length, count); dom.flush();
  return expected;
};
press('Linear Gradient'); type('Start Value (0–255)', 0); type('End Value (0–255)', 255);
const up = check(40.3, 50.7);
press('Swap Start/End'); const down = check(40.3, 50.7);
up.targets.forEach((t, i) => { if (up.coverage[i] > 0) assert.equal(t + down.targets[i], 255); });
type('Curve (exponent)', 0.5); const shallow = check(40.3, 50.7); type('Curve (exponent)', 3); const steep = check(40.3, 50.7);
assert.notDeepEqual(shallow.targets, steep.targets);
Object.assign(settings(), {value_profile: 'radial', shape: 'square', size: 20, hardness: 40, scale_x: 1.5,
  rotation_degrees: 90, crop_left: 25, mirror_horizontal: true, gradient_center_x: 30});
const radial = check(70.25, 60.5); assert.ok(radial.coverage.some(w => w > 0 && w < 1));
settings().value_profile = 'square'; const square = check(70.25, 60.5);
assert.notDeepEqual(radial.targets, square.targets);
// Heat View recolors the tint only; targets and the stamped field are unchanged.
press('Heat View'); heat = true; const hot = check(70.25, 60.5);
assert.deepEqual(hot.targets, square.targets);
// Zoom and pan keep the tint in field coordinates.
for (let i = 0; i < 3; i++) fire(find('viewport'), 'wheel', {clientX: 300, clientY: 200, deltaY: -1});
fire(find('viewport'), 'pointerdown', {button: 1, clientX: 50, clientY: 50});
fire(find('viewport'), 'pointermove', {clientX: 90, clientY: 20}); fire(find('viewport'), 'pointerup', {button: 1}); dom.flush();
const [px, py, z] = canvas().style.transform.match(/translate\(([-\d.]+)px,([-\d.]+)px\) scale\(([-\d.]+)\)/).slice(1).map(Number);
fire(find('viewport'), 'pointermove', {clientX: px + 64.25 * z, clientY: py + 70.5 * z}); dom.flush();
const zoomed = engine.stampPreview(128, 128, settings(), 64.25, 70.5);
for (let i = 0; i < 16384; i++) if (zoomed.coverage[i] > 0) assert.deepEqual([...preview().pixels.slice(i * 4, i * 4 + 3)], view.heatColor(zoomed.targets[i]));
assert.equal(preview().style.transform, canvas().style.transform);
// Erase and Restore show E3's coverage tint: their targets ignore the gradient.
for (const tool of ['Erase', 'Restore']) {
  press(tool); fire(find('viewport'), 'pointermove', {clientX: px + 64 * z, clientY: py + 64 * z}); dom.flush();
  const shown = engine.stampPreview(128, 128, settings(), 64, 64);
  assert.equal(shown.targets, null);
  for (let i = 0; i < 16384; i++) if (shown.coverage[i] > 0) assert.deepEqual([...preview().pixels.slice(i * 4, i * 4 + 3)], [64, 160, 255]);
}
""")

    def test_gradient_strokes_and_shift_lines_are_one_history_entry_and_settings_none(self):
        run_editor(r"""
const field = Uint8Array.from({length: 16384}, (_, i) => (i % 128) * 2);
reopen(field, {size: 12, influenceUnit: 'code'});
const s = () => controller.session;
for (const action of ['Linear Gradient', 'Radial Gradient', 'Square Gradient', 'Swap Start/End', 'Uniform', 'Linear Gradient']) press(action);
for (const [label, value] of [['Start Value (0–255)', 0], ['End Value (0–255)', 255], ['Curve (exponent)', 1.5],
  ['Gradient Angle (°)', 30], ['Start Position (%)', 10], ['End Position (%)', 90]]) type(label, value);
assert.deepEqual(s().codes, field); assert.equal(s().history.undoEntries.length, 0);
// One Build-up drag with many events: one entry, replaying the sampled path exactly.
press('Build-up'); press('Raise Only');
const path = [[20, 64], [100, 64], [20, 64], [100, 64.5], [60, 64.5]];
pointer('pointerdown', ...path[0]); for (const p of path.slice(1)) pointer('pointermove', ...p);
pointer('pointerup', ...path.at(-1)); dom.flush();
const replay = new engine.Stroke(field, 128, 128, settings(), ...path[0], s().initial);
for (const p of path.slice(1)) replay.add(...p); replay.add(...path.at(-1));
assert.deepEqual(s().codes, replay.result()); assert.equal(s().history.undoEntries.length, 1);
s().codes.forEach((v, i) => assert.ok(v >= field[i])); assert.ok(s().codes.some((v, i) => v > field[i]));
// Shift-click: the same gradient brush along a line from the last endpoint, one more entry.
press('Normal'); press('Build-up'); press('Square'); type('Rotation (°)', 45);
const before = s().codes.slice();
pointer('pointerdown', 120.5, 20.5, {shiftKey: true}); dom.flush();
const line = new engine.Stroke(before, 128, 128, settings(), 60, 64.5, s().initial); line.add(120.5, 20.5);
assert.deepEqual(s().codes, line.result()); assert.equal(s().history.undoEntries.length, 2);
assert.ok(line.targets.some(t => t > 0) && new Set(line.targets).size > 20);
const after = s().codes.slice();
press('Undo'); assert.deepEqual(s().codes, before); press('Redo'); assert.deepEqual(s().codes, after);
""")

    def test_erase_and_restore_mark_the_profile_inactive_and_paint_unchanged(self):
        run_editor(r"""
const opening = Uint8Array.from({length: 16384}, (_, i) => (i * 7) % 256);
reopen(opening, {size: 10, influenceUnit: 'code', hardness: 40});
press('Fill with Influence'); press('Radial Gradient'); type('Start Value (0–255)', 0); type('End Value (0–255)', 99);
const inactive = () => small('Inactive');
assert.equal(inactive().hidden, true);
for (const [tool, text] of [['Erase', 'Inactive: Erase targets 0. The gradient applies to Paint.'],
  ['Restore', 'Inactive: Restore targets the field as it was when this field joined the session. The gradient applies to Paint.']]) {
  press(tool); assert.equal(inactive().hidden, false); assert.equal(inactive().textContent, text);
  const before = controller.session.codes.slice();
  click(50.25, 60.5);
  const uniform = new engine.Stroke(before, 128, 128, {...settings(), value_profile: 'uniform'}, 50.25, 60.5, controller.session.initial);
  assert.deepEqual(controller.session.codes, uniform.result());
}
press('Paint'); assert.equal(inactive().hidden, true);
""")

    def test_done_stores_only_nondefault_e4_settings_and_reopen_restores_them(self):
        run_editor(r"""
const E1 = {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent'};
press('Done'); await settle(); assert.deepEqual(result.settings, E1); assert.deepEqual(Object.keys(result.settings), Object.keys(E1));
const roundTrip = async (actions, stored, badge) => {
  controller = open(); dom.flush(); actions(); press('Done'); await settle();
  assert.deepEqual(result.settings, {...E1, ...stored}); assert.deepEqual(Object.keys(result.settings), [...Object.keys(E1), ...Object.keys(stored)]);
  controller = open(empty(), result.settings); dom.flush();
  assert.deepEqual(settings(), {...E1, ...brushes.BRUSH_DEFAULTS, ...stored});
  assert.equal(summary().textContent, badge); controller.cancel();
};
await roundTrip(() => { press('Linear Gradient'); type('Start Value (0–255)', 0); type('End Value (0–255)', 255);
  type('Curve (exponent)', 2.5); type('Gradient Angle (°)', -30.5); type('Start Position (%)', 10); type('End Position (%)', 90); },
  {value_profile: 'linear', gradient_start: 0, gradient_end: 255, gradient_curve: 2.5, gradient_angle: -30.5,
   gradient_start_position: 10, gradient_end_position: 90}, 'Advanced · Linear gradient · 0→255 · Curve 2.5');
await roundTrip(() => { press('Radial Gradient'); type('Center X (%)', 30); type('Inner (%)', 20); type('Outer (%)', 150);
  type('Aspect X', 1.5); type('Gradient Rotation (°)', 15); },
  {value_profile: 'radial', gradient_center_x: 30, gradient_inner: 20, gradient_outer: 150, gradient_aspect_x: 1.5,
   gradient_rotation: 15}, 'Advanced · Radial gradient · 255→0');
await roundTrip(() => { press('Square Gradient'); press('Swap Start/End'); type('Center Y (%)', 0); type('Aspect Y', 0.5); },
  {value_profile: 'square', gradient_start: 0, gradient_end: 255, gradient_center_y: 0, gradient_aspect_y: 0.5},
  'Advanced · Square gradient · 0→255');
// A stored E3 workflow opens and saves byte-identically: no E4 key appears.
const e3 = {tool: 'paint', size: 9, influence: 77, hardness: 40, amount: 60, influenceUnit: 'code', shape: 'diamond',
  rotation_degrees: 22.5, crop_left: 10, build_up: true, flow: 40, apply_mode: 'raise_only'};
controller = open(empty(), e3); dom.flush(); assert.equal(settings().value_profile, 'uniform');
press('Done'); await settle(); assert.equal(JSON.stringify(result.settings), JSON.stringify(e3));
// Reset Brush leaves nothing E4 to store.
controller = open(empty(), {...E1, value_profile: 'radial', gradient_curve: 3, gradient_inner: 10}); dom.flush();
press('Reset Brush'); press('Done'); await settle(); assert.deepEqual(result.settings, E1);
// Cancel discards E4 changes and never calls Done.
const done = result; controller = open(); dom.flush(); press('Linear Gradient'); controller.cancel(); assert.equal(result, done);
// Stored E4 values are sanitized as E3's: invalid values and impossible pairs fall back to defaults.
assert.deepEqual(ui.editorSettings({value_profile: 'conical', gradient_start: 256, gradient_end: -1, gradient_curve: 1.25,
  gradient_angle: 400, gradient_start_position: 80, gradient_end_position: 20, gradient_center_x: 50.5, gradient_center_y: 101,
  gradient_inner: 70, gradient_outer: 70, gradient_aspect_x: 0, gradient_aspect_y: 2, gradient_rotation: -12.5}),
  {...E1, gradient_aspect_y: 2, gradient_rotation: -12.5});
assert.deepEqual(ui.editorSettings({value_profile: 'square', gradient_start_position: 40, gradient_end_position: 60,
  gradient_inner: 300, gradient_outer: 299}), {...E1, value_profile: 'square', gradient_start_position: 40, gradient_end_position: 60});
""")

    def test_value_profile_group_expansion_is_a_per_user_preference_outside_session_state(self):
        run_editor(r"""
const group = () => heading('Value Profile').parent;
const toggle = open => { const d = group(); d.open = open; fire(d, 'toggle'); dom.flush(); };
const reopenSame = () => { controller.cancel(); controller = open(); dom.flush(); };
assert.equal(group().open, false); assert.deepEqual(writes, []);
const stored = JSON.stringify(ui.editorSettings(settings()));
toggle(true); assert.deepEqual(writes, [['profile', true]]);
assert.equal(controller.session.history.undoEntries.length, 0); assert.equal(JSON.stringify(ui.editorSettings(settings())), stored);
let asked = 0; host.confirmDiscard = () => { asked++; return true; };
reopenSame(); assert.equal(asked, 0); assert.equal(group().open, true); assert.equal(expanded.profile, true);
toggle(false); reopenSame(); assert.equal(group().open, false);
// Badges do not depend on expansion, and Reset Brush does not change it.
toggle(true); press('Linear Gradient'); assert.equal(group().children[0].textContent, 'Value Profile · Linear gradient · 255→0');
press('Reset Brush'); assert.equal(group().open, true);
press('Done'); await settle();
assert.deepEqual(result.settings, {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent'});
assert.deepEqual(writes, [['profile', true], ['profile', false], ['profile', true]]); assert.deepEqual(expanded, {profile: true});
""")


if __name__ == "__main__":
    unittest.main()
