"""Fenced inline Node E5 custom-tip tests; not real-browser interaction evidence.

PNG fixtures are written here by a small independent encoder (zlib and struct), and their
canonical planes are expected from the specification in exact integer and rational arithmetic.
Custom footprints are checked against an exact rational (Fraction) reference of the documented
tip reading, frame, transform order, bilinear rule and Hardness envelope, written without product
code. Default behavior is checked against the retained E1 golden hashes.
"""
import base64
from fractions import Fraction as Q
import itertools
import json
import math
from pathlib import Path
import struct
import subprocess
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "web/js/field_editor"
DOM = Path(__file__).with_name("field_editor_fake_dom.js")
HALF = Q(1, 2)

PRELUDE = r"""
import assert from 'node:assert/strict';
const engine = await import(@ENGINE@);
const brushes = await import(@BRUSH@);
const view = await import(@VIEW@);
const ui = await import(@UI@);
const tips = await import(@TIP@);
const {installDOM, fire, descendants, settle} = await import(@DOM@);
const brush = {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100};
const empty = () => new Uint8Array(16384);
const bytesOf = text => Uint8Array.from(Buffer.from(text, 'base64'));
const tipOf = t => ({width: t.width, height: t.height, luminance: Uint8Array.from(t.luminance), alpha: Uint8Array.from(t.alpha)});
const plain = t => ({width: t.width, height: t.height, luminance: [...t.luminance], alpha: [...t.alpha]});
const options = c => ({...brush, shape: 'custom', tip: tipOf(c.tip), size: c.size, hardness: c.hardness ?? 100,
  falloff_curve: c.curve ?? 'smooth', scale_x: Number(c.sx), scale_y: Number(c.sy), rotation_degrees: c.rotation,
  mirror_horizontal: c.mirror[0], mirror_vertical: c.mirror[1], crop_left: c.crop[0], crop_right: c.crop[1],
  crop_top: c.crop[2], crop_bottom: c.crop[3], tip_channel: c.channel ?? 'alpha', tip_invert: c.invert ?? false,
  tip_trim: c.trim ?? false, ...(c.extra ?? {})});
const decoded = async text => { try { return plain(await tips.decodeTipPng(bytesOf(text))); } catch (e) { return {error: e.message}; } };
"""
for token, path in {"@ENGINE@": CORE / "engine.js", "@BRUSH@": CORE / "brush.js", "@VIEW@": CORE / "view.js",
                    "@UI@": CORE / "editor_ui.js", "@TIP@": CORE / "custom_tip.js", "@DOM@": DOM}.items():
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
const heading = title => all().find(e => e.tagName === 'SUMMARY' && e.textContent?.startsWith(title));
const shapeGroup = () => heading('Brush Shape').parent, tipGroup = () => heading('Custom Tip').parent;
const pressIn = (scope, text) => { descendants(scope).find(e => e.tagName === 'BUTTON' && e.textContent === text).click(); dom.flush(); };
const custom = () => pressIn(shapeGroup(), 'Custom');
const summary = () => heading('Advanced');
const status = () => find('tip-status'), thumbnail = () => find('tip-thumbnail'), error = () => find('error').textContent;
const caption = () => all().find(e => e.tagName === 'SMALL' && e.textContent?.startsWith('Prepared tip'));
const canvas = () => all().find(e => e.tagName === 'CANVAS');
const preview = () => find('brush-preview'), outline = () => find('brush-outline');
const pointer = (name, x, y, extra = {}) => fire(find('viewport'), name, {clientX: 8 + x * 4, clientY: 8 + y * 4, ...extra});
const click = (x, y, extra = {}) => { pointer('pointerdown', x, y, extra); pointer('pointerup', x, y); dom.flush(); };
const session = () => controller.session, settings = () => controller.session.settings;
const engineBrush = () => ({...settings(), tip: session().tip});
const fileOf = (text, name = 'C:\\Users\\someone\\Brushes\\secret-tip.png') => {
  const bytes = bytesOf(text); const file = {name, size: bytes.length, reads: 0};
  file.arrayBuffer = async () => { file.reads++; return bytes.slice().buffer; }; return file;
};
const until = async (test, label) => {  // renders between polls, as frames would
  for (let i = 0; i < 3000; i++) { dom.flush(); if (test()) return; await new Promise(r => setTimeout(r, 1)); }
  assert.fail(`timed out: ${label}`);
};
const tipPicker = () => all().find(e => e.accept === '.png,image/png');
const importFile = async file => {
  const before = session().tip; find('error').textContent = '';
  tipPicker().files = [file]; fire(tipPicker(), 'change');
  await until(() => session().tip !== before || find('error').textContent, 'import');
};
const importTip = (text, name) => importFile(fileOf(text, name));
const reopen = async (codes, stored) => {
  controller.cancel(); controller = open(codes, stored); dom.flush();
  if (stored?.custom_tip) await until(() => session().tip || heading('Custom Tip').textContent.includes('unreadable'), 'stored tip');
};
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
DAMAGED = "The PNG is damaged or incomplete."


def run_node(body, data=None):
    source = PRELUDE + (f"const data = {json.dumps(data)};\n" if data is not None else "") + body
    result = subprocess.run(["node", "--input-type=module"], input=source, cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout or "null")


def run_editor(body, data=None):
    return run_node(EDITOR + body, data)


def first_difference(actual, expected):
    """Index and values of the first difference, or None. Never diff long lists with assertEqual."""
    if len(actual) != len(expected):
        return ("length", len(actual), len(expected))
    for index, (a, b) in enumerate(zip(actual, expected)):
        if a != b:
            return (index, a, b)
    return None


# ---------------------------------------------------------------------------
# An independent PNG writer for fixtures. It is not the product's encoder.
# ---------------------------------------------------------------------------

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def pack_row(samples, depth):
    if depth == 8:
        return bytes(samples)
    if depth == 16:
        return struct.pack(f">{len(samples)}H", *samples)
    out, acc, bits = bytearray(), 0, 0
    for s in samples:
        acc, bits = (acc << depth) | s, bits + depth
        if bits == 8:
            out.append(acc)
            acc = bits = 0
    if bits:
        out.append(acc << (8 - bits))
    return bytes(out)


def filter_row(row, prior, kind, bpp):
    out = bytearray([kind])
    for i, value in enumerate(row):
        left = row[i - bpp] if i >= bpp else 0
        up = prior[i] if prior else 0
        corner = prior[i - bpp] if prior and i >= bpp else 0
        if kind == 1:
            p = left
        elif kind == 2:
            p = up
        elif kind == 3:
            p = (left + up) // 2
        elif kind == 4:
            e = left + up - corner
            da, db, dc = abs(e - left), abs(e - up), abs(e - corner)
            p = left if da <= db and da <= dc else up if db <= dc else corner
        else:
            p = 0
        out.append((value - p) % 256)
    return bytes(out)


def png(width, height, color, depth, pixels, *, palette=None, trns=None, filters=(0,), before=b"", after=b"",
        split=False, between=b"", header=None, raw_suffix=b"", compressed=None, level=6, suffix=b""):
    bpp = max(1, CHANNELS.get(color, 1) * depth // 8)
    raw, prior = bytearray(), None
    for y in range(height):
        row = pack_row([s for x in range(width) for s in pixels[y * width + x]], depth)
        raw += filter_row(row, prior, filters[y % len(filters)], bpp)
        prior = row
    data = zlib.compress(bytes(raw) + raw_suffix, level) if compressed is None else compressed
    idat = chunk(b"IDAT", data[:5]) + between + chunk(b"IDAT", data[5:]) if split else chunk(b"IDAT", data)
    ihdr = struct.pack(">IIBBBBB", *(header or (width, height, depth, color, 0, 0, 0)))
    plte = chunk(b"PLTE", bytes(c for rgb in palette for c in rgb)) if palette is not None else b""
    transparency = chunk(b"tRNS", trns) if trns is not None else b""
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + before + plte + transparency + idat + after
            + chunk(b"IEND", b"") + suffix)


def b64(data):
    return base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------------------
# Expected canonical planes, from the specification.
# ---------------------------------------------------------------------------

def nearest(value):
    floor = math.floor(value)
    return floor + (1 if value - floor >= HALF else 0)


def to8(sample, depth):
    """The nearest 8-bit code to sample / (2^depth - 1), halves up."""
    return nearest(Q(sample * 255, (1 << depth) - 1))


def luma(r, g, b):
    """Rec. 709 weights on the 8-bit samples, rounded half up."""
    return nearest(Q("0.2126") * r + Q("0.7152") * g + Q("0.0722") * b)


def expected_planes(color, depth, pixels, palette=None, trns=None):
    key = struct.unpack(">" + "H" * (len(trns) // 2), trns) if trns is not None and color in (0, 2) else None
    luminance, alpha = [], []
    for p in pixels:
        if color == 3:
            luminance.append(luma(*palette[p[0]]))
            alpha.append(trns[p[0]] if trns is not None and p[0] < len(trns) else 255)
        elif color in (0, 4):
            luminance.append(to8(p[0], depth))
            alpha.append(to8(p[1], depth) if color == 4 else 0 if key and p[0] == key[0] else 255)
        else:
            luminance.append(luma(*(to8(c, depth) for c in p[:3])))
            alpha.append(to8(p[3], depth) if color == 6 else 0 if key and tuple(p[:3]) == key else 255)
    return luminance, alpha


def samples(width, height, channels, depth, seed):
    top = (1 << depth) - 1
    return [tuple((x * 2654435761 + y * 40503 + c * 9973 + seed * 7919) % 1000003 % (top + 1)
                  for c in range(channels)) for y in range(height) for x in range(width)]


# ---------------------------------------------------------------------------
# Tips and the independent footprint reference (exact rationals).
# ---------------------------------------------------------------------------

def make_tip(width, height, alpha=None, luminance=None):
    n = width * height
    return {"width": width, "height": height, "luminance": list(luminance or [255] * n),
            "alpha": list(alpha or [255] * n)}


def textured(width, height, seed=0):
    """Alpha 5..255, never 0, varying in both directions; luminance varies independently."""
    return make_tip(width, height, [(x * 37 + y * 91 + seed * 13) % 251 + 5 for y in range(height) for x in range(width)],
                    [(x * 53 + y * 29 + seed * 7) % 256 for y in range(height) for x in range(width)])


def tip_png(t, color=4):
    n = t["width"] * t["height"]
    if color == 4:
        pixels = [(t["luminance"][i], t["alpha"][i]) for i in range(n)]
    else:  # RGBA with gray colour: its luminance is the gray value
        pixels = [(t["luminance"][i],) * 3 + (t["alpha"][i],) for i in range(n)]
    return b64(png(t["width"], t["height"], color, 8, pixels, filters=(0, 1, 2, 3, 4)))


def read_mask(t, channel="alpha", invert=False, trim=False):
    w, h, luminance, alpha = t["width"], t["height"], t["luminance"], t["alpha"]
    m = [alpha[i] if channel == "alpha" else luminance[i] if channel == "luminance" else nearest(Q(alpha[i] * luminance[i], 255))
         for i in range(w * h)]
    if invert:
        m = [255 - v for v in m]
    left = top = 0
    if trim and any(m):
        xs = [i % w for i in range(w * h) if m[i] > 0]
        ys = [i // w for i in range(w * h) if m[i] > 0]
        left, top = min(xs), min(ys)
        nw, nh = max(xs) - left + 1, max(ys) - top + 1
        m = [m[(top + y) * w + left + x] for y in range(nh) for x in range(nw)]
        w, h = nw, nh
    return {"codes": m, "width": w, "height": h, "left": left, "top": top, "empty": not any(m)}


def bilinear(m, w, h, px, py):
    """Pixel centres at (i + 1/2, j + 1/2); neighbours clamped into the mask; weights form."""
    fx, fy = px - HALF, py - HALF
    x0, y0 = math.floor(fx), math.floor(fy)
    tx, ty = fx - x0, fy - y0
    at = lambda x, y: m[min(max(y, 0), h - 1) * w + min(max(x, 0), w - 1)]
    return ((1 - tx) * (1 - ty) * at(x0, y0) + tx * (1 - ty) * at(x0 + 1, y0)
            + (1 - tx) * ty * at(x0, y0 + 1) + tx * ty * at(x0 + 1, y0 + 1))


UNROTATE = (lambda x, y: (x, y), lambda x, y: (y, -x), lambda x, y: (-x, -y), lambda x, y: (-y, x))
CURVES = {"smooth": lambda s: s * s * (3 - 2 * s), "linear": lambda s: s,
          "sharper": lambda s: s * s * s * (s * (s * 6 - 15) + 10)}


def config(t, size, x="64.25", y="63.75", sx="1", sy="1", rotation=0, mirror=(False, False), crop=(0, 0, 0, 0), **extra):
    return {"tip": t, "size": size, "x": x, "y": y, "sx": sx, "sy": sy, "rotation": rotation,
            "mirror": list(mirror), "crop": list(crop), **extra}


def reference(c, order="specified"):
    """Coverage by cell index from the documented order: read, invert, trim, crop, mirror, fit, scale, rotate, place.

    Other orders are wrong on purpose, to show that the implementation follows the specified one.
    Returns (coverage dict, smallest distance of any cell's local position to the crop edge).
    """
    channel, invert, trim = c.get("channel", "alpha"), c.get("invert", False), c.get("trim", False)
    if order == "invert-after-trim":
        mask = read_mask(c["tip"], channel, False, trim)
        if invert:
            mask = {**mask, "codes": [255 - v for v in mask["codes"]]}
    else:
        mask = read_mask(c["tip"], channel, invert, trim and order != "crop-before-trim")
    m, w, h, size = mask["codes"], mask["width"], mask["height"], c["size"]
    left, right, top, bottom = c["crop"]
    gw, gh = (1, 1) if order == "aspect-ignored" else (w, h)
    width, height = gw * (100 - left - right), gh * (100 - top - bottom)
    fit = {"fit-before-crop": max(gw, gh) * 100, "fit-width": width}.get(order, max(width, height))
    cx, cy = Q((left - right) * gw * size, 2 * fit), Q((top - bottom) * gh * size, 2 * fit)
    hx, hy = Q(width * size, 2 * fit), Q(height * size, 2 * fit)
    rx, ry = Q(50 * gw * size, fit), Q(50 * gh * size, fit)
    sx, sy = Q(c["sx"]), Q(c["sy"])
    angle = Q(str(c["rotation"])) % 360
    if angle % 90 == 0:
        turn = int(angle // 90)
        unrotate = UNROTATE[turn]
    else:  # the engine's one cos/sin pair of the clockwise angle, then exact arithmetic
        radians = float(angle) * (math.pi / 180)
        cos, sin = math.cos(radians), math.sin(radians)
        turn = math.floor(angle / 90 + HALF) % 4
        unrotate = lambda x, y: (Q(cos * float(x) + sin * float(y)), Q(-sin * float(x) + cos * float(y)))
    hard = c.get("hardness", 100) == 100
    ax, ay = hx * sx, hy * sy
    px, py = (ay, ax) if turn % 2 else (ax, ay)
    snap = lambda v, e: math.floor(v) + HALF if nearest(2 * e) % 2 else math.floor(v + HALF)
    x0, y0 = Q(c["x"]), Q(c["y"])
    anchor = (snap(x0, px), snap(y0, py)) if hard else (x0, y0)
    reach_x, reach_y = (ax + ay, ax + ay) if angle % 90 else (ay, ax) if turn % 2 else (ax, ay)
    coverage, margin = {}, math.inf
    for row in range(max(0, math.floor(anchor[1] - reach_y) - 2), min(128, math.ceil(anchor[1] + reach_y) + 2)):
        for col in range(max(0, math.floor(anchor[0] - reach_x) - 2), min(128, math.ceil(anchor[0] + reach_x) + 2)):
            dx, dy = col + HALF - anchor[0], row + HALF - anchor[1]
            if order == "rotate-before-scale":
                x, y = unrotate(dx / sx, dy / sy)
            else:
                x, y = unrotate(dx, dy)
                x, y = x / sx, y / sy
            if order != "mirror-before-crop":
                x, y = (-x if c["mirror"][0] else x), (-y if c["mirror"][1] else y)
            margin = min(margin, abs(abs(x) - hx), abs(abs(y) - hy))
            if abs(x) > hx or abs(y) > hy:
                continue
            u, v = cx + x, cy + y
            if order == "mirror-before-crop":  # mirrored about the tip frame's centre, not the crop's
                u, v = (-u if c["mirror"][0] else u), (-v if c["mirror"][1] else v)
            value = bilinear(m, w, h, Q(w, 2) + u * w / (2 * rx), Q(h, 2) + v * h / (2 * ry)) / 255
            if not hard and value:
                reach, inner = max(abs(u) / rx, abs(v) / ry), Q(c["hardness"], 100)
                value *= 1 if reach <= inner else 0 if reach >= 1 else CURVES[c.get("curve", "smooth")]((1 - reach) / (1 - inner))
            if value:
                coverage[row * 128 + col] = value
    return coverage, margin


COVERAGE = """
console.log(JSON.stringify(data.map(c => {
  const o = options(c), p = engine.stampPreview(128, 128, o, Number(c.x), Number(c.y));
  const stroke = new engine.Stroke(empty(), 128, 128, o, Number(c.x), Number(c.y));
  // A click keeps exactly the previewed coverage (and targets).
  assert.deepEqual(stroke.coverage, p.coverage); assert.deepEqual(stroke.targets, p.targets);
  return [...p.coverage.keys()].filter(i => p.coverage[i] > 0).map(i => [i, p.coverage[i]]);
})));
"""


class TipDecodeTests(unittest.TestCase):
    def decode(self, cases):
        return run_node("console.log(JSON.stringify(await Promise.all(data.map(decoded))));", [b64(c) for c in cases])

    def test_every_colour_type_and_bit_depth_canonicalizes_exactly(self):
        cases, expected = [], []
        add = lambda data, planes: (cases.append(data), expected.append(planes))
        for depth in (1, 2, 4, 8, 16):
            for width, height in ((7, 5), (1, 1), (33, 2), (2, 9)):
                pixels = samples(width, height, 1, depth, depth + width)
                add(png(width, height, 0, depth, pixels, filters=(0, 1, 2, 3, 4)), expected_planes(0, depth, pixels))
        # Gray with a tRNS colour, at 2, 8 and 16 bits; the match is on the stored sample.
        for depth, key in ((2, 2), (8, 77), (16, 0x1234)):
            pixels = samples(6, 4, 1, depth, 3)
            pixels[5] = (key,)
            trns = struct.pack(">H", key)
            add(png(6, 4, 0, depth, pixels, trns=trns), expected_planes(0, depth, pixels, trns=trns))
        for depth in (8, 16):
            pixels = samples(5, 4, 3, depth, 11)
            pixels[3] = pixels[7] = (1, 2, 3)
            trns = struct.pack(">HHH", 1, 2, 3)
            add(png(5, 4, 2, depth, pixels, trns=trns, filters=(4, 3, 2, 1)), expected_planes(2, depth, pixels, trns=trns))
            for color in (4, 6):
                pixels = samples(5, 4, CHANNELS[color], depth, color)
                add(png(5, 4, color, depth, pixels, filters=(1, 4)), expected_planes(color, depth, pixels))
        # Palette at every depth, with a tRNS shorter than the palette.
        for depth in (1, 2, 4, 8):
            entries = min(1 << depth, 40)
            palette = [((i * 67) % 256, (i * 151) % 256, (i * 29) % 256) for i in range(entries)]
            pixels = [(v[0] % entries,) for v in samples(9, 3, 1, depth, 5)]
            trns = bytes((i * 50) % 256 for i in range(max(1, entries // 2)))
            add(png(9, 3, 3, depth, pixels, palette=palette, trns=trns, filters=(2, 0, 4)),
                expected_planes(3, depth, pixels, palette, trns))
        # Alpha-only patterns: one colour, varying alpha; and partial alpha over colour.
        alpha_only = [(0, 0, 0, (i * 23) % 256) for i in range(24)]
        add(png(6, 4, 6, 8, alpha_only), expected_planes(6, 8, alpha_only))
        partial = [((i * 40) % 256, (i * 90) % 256, (i * 13) % 256, 0 if i % 5 == 0 else 255 if i % 5 == 1 else 128) for i in range(24)]
        add(png(4, 6, 6, 8, partial), expected_planes(6, 8, partial))
        # Ancillary chunks (colour management included) are ignored; split image data is joined.
        pixels = samples(8, 8, 2, 8, 9)
        extra = (chunk(b"gAMA", struct.pack(">I", 45455)) + chunk(b"sRGB", b"\x00") + chunk(b"cHRM", bytes(32))
                 + chunk(b"iCCP", b"name\x00\x00" + zlib.compress(b"profile")) + chunk(b"tEXt", b"k\x00v"))
        add(png(8, 8, 4, 8, pixels, before=extra, after=chunk(b"tEXt", b"after\x00idat"), split=True),
            expected_planes(4, 8, pixels))
        results = self.decode(cases)
        self.assertEqual(len(results), len(expected))
        for index, (result, (luminance, alpha)) in enumerate(zip(results, expected)):
            self.assertNotIn("error", result, index)
            self.assertIsNone(first_difference(result["luminance"], luminance), index)
            self.assertIsNone(first_difference(result["alpha"], alpha), index)

    def test_sixteen_bit_reduction_and_luminance_are_exact_everywhere(self):
        every = [(v,) for v in range(65536)]
        rgb = [(r, 0, 0) for r in range(256)] + [(0, g, 0) for g in range(256)] + [(0, 0, b) for b in range(256)]
        rgb += [(v, v, v) for v in range(256)]
        ties = list(itertools.islice(((r, g, b) for r in range(256) for g in range(256) for b in range(256)
                                      if (2126 * r + 7152 * g + 722 * b) % 10000 == 5000), 200))
        self.assertEqual(len(ties), 200)
        rgb += ties + [((i * 7919) % 256, (i * 104729) % 256, (i * 1299709) % 256) for i in range(4000)]
        rgb += [(0, 0, 0)] * (-len(rgb) % 64)  # a 64-pixel-wide image of every triple
        result = run_node("""
const gray = await decoded(data.gray), out = {gray, luma: data.rgb.map(([r, g, b]) => tips.luma(r, g, b))};
out.decodedRgb = await decoded(data.rgbPng);
console.log(JSON.stringify(out));
""", {"gray": b64(png(256, 256, 0, 16, every, filters=(0, 1, 2, 3, 4))), "rgb": rgb,
      "rgbPng": b64(png(64, len(rgb) // 64, 2, 8, rgb, filters=(4, 1)))})
        self.assertIsNone(first_difference(result["gray"]["luminance"], [to8(v, 16) for v in range(65536)]))
        self.assertEqual(set(result["gray"]["alpha"]), {255})
        # The integer rule equals v/257 rounded half up; no 16-bit value is a tie.
        self.assertTrue(all(Q(v, 257) - math.floor(Q(v, 257)) != HALF for v in range(65536)))
        expected = [luma(*p) for p in rgb]
        self.assertIsNone(first_difference(result["luma"], expected))
        self.assertIsNone(first_difference(result["decodedRgb"]["luminance"], expected))
        self.assertEqual([luma(v, v, v) for v in range(256)], list(range(256)))  # gray stays gray
        self.assertTrue(all((2126 * r + 7152 * g + 722 * b) % 10000 == 5000 for r, g, b in ties))  # exact halves round up

    def test_equivalent_encodings_give_the_same_canonical_tip_and_stored_value(self):
        width, height = 9, 7
        gray = [(x * 31 + y * 17) % 256 for y in range(height) for x in range(width)]
        used = sorted(set(gray))
        opaque = [
            png(width, height, 0, 8, [(v,) for v in gray]),
            png(width, height, 0, 8, [(v,) for v in gray], filters=(1, 2, 3, 4, 0), level=9),
            png(width, height, 0, 8, [(v,) for v in gray], split=True, level=0,
                before=chunk(b"tEXt", b"Comment\x00same pixels"), after=chunk(b"pHYs", bytes(9))),
            png(width, height, 0, 16, [(v * 257,) for v in gray], filters=(4,)),
            png(width, height, 2, 8, [(v, v, v) for v in gray]),
            png(width, height, 2, 16, [(v * 257,) * 3 for v in gray], filters=(3,)),
            png(width, height, 6, 8, [(v, v, v, 255) for v in gray], filters=(2,)),
            png(width, height, 4, 8, [(v, 255) for v in gray]),
            png(width, height, 4, 16, [(v * 257, 65535) for v in gray]),
            png(width, height, 3, 8, [(v,) for v in gray], palette=[(i, i, i) for i in range(256)]),
            png(width, height, 3, 8, [(used.index(v),) for v in gray], palette=[(v, v, v) for v in used]),
        ]
        key = gray[4]
        transparent = [
            png(width, height, 0, 8, [(v,) for v in gray], trns=struct.pack(">H", key)),
            png(width, height, 4, 8, [(v, 0 if v == key else 255) for v in gray]),
            png(width, height, 6, 8, [(v, v, v, 0 if v == key else 255) for v in gray], filters=(1,)),
            png(width, height, 2, 8, [(v, v, v) for v in gray], trns=struct.pack(">HHH", key, key, key)),
            png(width, height, 3, 8, [(used.index(v),) for v in gray], palette=[(v, v, v) for v in used],
                trns=bytes(0 if v == key else 255 for v in used)),
        ]
        result = run_node("""
const out = [];
for (const group of data) {
  const decodedTips = await Promise.all(group.map(async text => tips.decodeTipPng(bytesOf(text))));
  const stored = await Promise.all(decodedTips.map(t => tips.encodeTipDataUrl(t)));
  for (const t of decodedTips) assert.ok(tips.sameTip(t, decodedTips[0]));
  assert.equal(new Set(stored).size, 1);  // one canonical stored value for every encoding
  assert.ok(tips.sameTip(await tips.decodeTipDataUrl(stored[0]), decodedTips[0]));
  out.push({tip: plain(decodedTips[0]), stored: stored[0]});
}
console.log(JSON.stringify(out));
""", [[b64(c) for c in opaque], [b64(c) for c in transparent]])
        self.assertEqual(result[0]["tip"]["luminance"], gray)
        self.assertEqual(result[0]["tip"]["alpha"], [255] * len(gray))
        self.assertEqual(result[1]["tip"]["alpha"], [0 if v == key else 255 for v in gray])
        self.assertNotEqual(result[0]["stored"], result[1]["stored"])
        # The stored value is a gray+alpha 8-bit non-interlaced PNG of exactly the two planes.
        data = base64.b64decode(result[0]["stored"][len("data:image/png;base64,"):], validate=True)
        self.assertEqual(data[12:16], b"IHDR")
        self.assertEqual(struct.unpack(">IIBBBBB", data[16:29]), (width, height, 8, 4, 0, 0, 0))

    def test_invalid_and_unsupported_pngs_are_rejected_with_a_clear_reason(self):
        good = [(v,) for v in range(12)]
        base = png(4, 3, 0, 8, good)
        bad_crc = bytearray(base)
        bad_crc[-1] ^= 1
        palette = [(1, 2, 3), (4, 5, 6)]
        cases = {
            "signature": (b"GIF89a" + bytes(20), "Not a PNG file."),
            "short": (base[:7], "Not a PNG file."),
            "truncated": (base[:-5], DAMAGED),
            "bad-crc": (bytes(bad_crc), DAMAGED),
            "after-iend": (base + b"x", DAMAGED),
            "missing-iend": (base[:-12], DAMAGED),
            "ihdr-not-first": (b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", b"a\x00b") + base[8:], DAMAGED),
            "two-ihdr": (png(4, 3, 0, 8, good, before=chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 0, 0, 0, 0))), DAMAGED),
            "zero-width": (png(0, 3, 0, 8, [], header=(0, 3, 8, 0, 0, 0, 0)), "The PNG has no pixels (zero width or height)."),
            "zero-height": (png(4, 0, 0, 8, [], header=(4, 0, 8, 0, 0, 0, 0)), "The PNG has no pixels (zero width or height)."),
            "too-wide": (png(1, 1, 0, 8, [(0,)], header=(1025, 1, 8, 0, 0, 0, 0)),
                         "Custom tips may be at most 1,024 pixels a side and 262,144 pixels in all; this PNG is 1025×1."),
            "too-many-pixels": (png(1, 1, 0, 8, [(0,)], header=(513, 512, 8, 0, 0, 0, 0)),
                                "Custom tips may be at most 1,024 pixels a side and 262,144 pixels in all; this PNG is 513×512."),
            "interlaced": (png(4, 3, 0, 8, good, header=(4, 3, 8, 0, 0, 0, 1)),
                           "Interlaced PNGs are not supported. Save the tip without interlacing."),
            "bad-depth": (png(4, 3, 2, 8, [(0, 0, 0)] * 12, header=(4, 3, 4, 2, 0, 0, 0)),
                          "Unsupported PNG format (colour type 2, bit depth 4)."),
            "bad-colour": (png(4, 3, 0, 8, good, header=(4, 3, 8, 5, 0, 0, 0)), "Unsupported PNG format (colour type 5, bit depth 8)."),
            "compression-method": (png(4, 3, 0, 8, good, header=(4, 3, 8, 0, 1, 0, 0)), DAMAGED),
            "filter-method": (png(4, 3, 0, 8, good, header=(4, 3, 8, 0, 0, 1, 0)), DAMAGED),
            "interlace-method": (png(4, 3, 0, 8, good, header=(4, 3, 8, 0, 0, 0, 2)), DAMAGED),
            "critical-chunk": (png(4, 3, 0, 8, good, before=chunk(b"ABCD", b"")), "Unsupported PNG chunk ABCD."),
            "reserved-bit": (png(4, 3, 0, 8, good, before=chunk(b"abcd", b"")), DAMAGED),
            "animated": (png(4, 3, 0, 8, good, before=chunk(b"acTL", bytes(8))), "Animated PNGs are not supported."),
            "orientation": (png(4, 3, 0, 8, good, before=chunk(b"eXIf", b"MM")), "PNGs with orientation metadata (eXIf) are not supported."),
            "plte-for-gray": (png(4, 3, 0, 8, good, palette=palette), DAMAGED),
            "no-palette": (png(4, 3, 3, 8, [(0,)] * 12), DAMAGED),
            "palette-too-long": (png(4, 3, 3, 1, [(0,)] * 12, palette=palette + [(7, 8, 9)]), DAMAGED),
            "index-out-of-range": (png(4, 3, 3, 2, [(3,)] * 12, palette=palette), DAMAGED),
            "trns-length": (png(4, 3, 0, 8, good, trns=bytes(4)), DAMAGED),
            "trns-for-rgba": (png(2, 2, 6, 8, [(0, 0, 0, 0)] * 4, trns=bytes(6)), DAMAGED),
            "trns-longer-than-palette": (png(4, 3, 3, 8, [(0,)] * 12, palette=palette, trns=bytes(3)), DAMAGED),
            "trns-before-plte": (png(4, 3, 3, 8, [(0,)] * 12, before=chunk(b"tRNS", b"\x00") + chunk(b"PLTE", bytes(6))), DAMAGED),
            "plte-after-idat": (png(4, 3, 3, 8, [(0,)] * 12, palette=palette, after=chunk(b"PLTE", bytes(6))), DAMAGED),
            "split-by-chunk": (png(4, 3, 0, 8, good, split=True, between=chunk(b"tEXt", b"a\x00b")), DAMAGED),
            "split-is-fine": (png(4, 3, 0, 8, good, split=True), None),
            "decoded-short": (png(4, 3, 0, 8, good, compressed=zlib.compress(bytes(10))), DAMAGED),
            "decoded-long": (png(4, 3, 0, 8, good, raw_suffix=b"x"), DAMAGED),
            "zlib-garbage": (png(4, 3, 0, 8, good, compressed=b"not zlib data"), DAMAGED),
            "zlib-tail": (png(4, 3, 0, 8, good, compressed=zlib.compress(bytes(15)) + b"x"), DAMAGED),
            "filter-type-5": (png(4, 3, 0, 8, good, filters=(5,)), DAMAGED),
            "huge-chunk-length": (base[:33] + struct.pack(">I", 0x80000000) + base[37:], DAMAGED),
        }
        self.assertIn(b"tEXt", cases["split-by-chunk"][0])
        self.assertEqual(cases["split-by-chunk"][0].count(b"IDAT"), 2)
        result = run_node("""
const out = {};
for (const [name, text] of Object.entries(data)) out[name] = (await decoded(text)).error ?? null;
// The byte bound is checked before anything else, and the file reader before reading.
out.bytes = (await decoded(Buffer.alloc(8388609).toString('base64'))).error;
let reads = 0;
out.file = await tips.importTipFile({size: 8388609, arrayBuffer: async () => { reads++; return new ArrayBuffer(8); }}).then(() => null, e => e.message);
out.reads = reads;
out.missing = await tips.importTipFile(undefined).then(() => null, e => e.message);
console.log(JSON.stringify(out));
""", {name: b64(data) for name, (data, _) in cases.items()})
        for name, (_, message) in cases.items():
            self.assertEqual(result[name], message, name)
        bound = "PNG files for custom tips may be at most 8,388,608 bytes."
        self.assertEqual((result["bytes"], result["file"], result["reads"], result["missing"]), (bound, bound, 0, bound))

    def test_unsupported_browser_state_and_oversized_image_data_fail_cleanly(self):
        big = png(512, 512, 6, 16, [(1, 2, 3, 4)] * (512 * 512), raw_suffix=bytes(100000))
        result = run_node("""
const valid = data.valid, out = {};
const {DecompressionStream: D, CompressionStream: C} = globalThis;
delete globalThis.DecompressionStream; out.decode = (await decoded(valid)).error;
globalThis.DecompressionStream = D; delete globalThis.CompressionStream;
out.encode = await tips.encodeTipPng(await tips.decodeTipPng(bytesOf(valid))).then(() => null, e => e.message);
globalThis.CompressionStream = C;
out.again = (await decoded(valid)).width;
// Image data that inflates past the declared size is rejected, never kept.
out.big = (await decoded(data.big)).error;
console.log(JSON.stringify(out));
""", {"valid": b64(png(3, 2, 0, 8, [(v,) for v in range(6)])), "big": b64(big)})
        self.assertEqual(result, {"decode": "This browser cannot decompress PNG image data.",
                                  "encode": "This browser cannot compress PNG image data.", "again": 3, "big": DAMAGED})


class TipReadingTests(unittest.TestCase):
    def test_channels_and_invert_are_exact_for_every_alpha_and_luminance_pair(self):
        result = run_node("""
const t = {width: 256, height: 256, luminance: Uint8Array.from({length: 65536}, (_, i) => i % 256),
  alpha: Uint8Array.from({length: 65536}, (_, i) => i >> 8)};
const out = {};
for (const channel of ['alpha', 'luminance', 'alpha_luminance']) for (const invert of [false, true]) {
  const mask = brushes.tipMask(t, channel, invert, false);
  assert.equal(mask.width, 256); assert.equal(mask.empty, false);
  out[`${channel} ${invert}`] = [...mask.codes];
}
console.log(JSON.stringify(out));
""")
        pairs = [(i >> 8, i % 256) for i in range(65536)]
        product = [nearest(Q(a * y, 255)) for a, y in pairs]
        self.assertTrue(all(Q(a * y, 255) - math.floor(Q(a * y, 255)) != HALF for a, y in pairs))  # never a tie
        for channel, codes in (("alpha", [a for a, _ in pairs]), ("luminance", [y for _, y in pairs]), ("alpha_luminance", product)):
            self.assertIsNone(first_difference(result[f"{channel} false"], codes), channel)
            self.assertIsNone(first_difference(result[f"{channel} true"], [255 - v for v in codes]), channel)
        self.assertEqual(product[255 * 256 + 255], 255)
        self.assertEqual(product[128 * 256 + 128], 64)  # 128 x 128 / 255 = 64.25

    def test_trim_keeps_the_smallest_rectangle_holding_every_positive_code(self):
        def tip_from_rows(rows):
            return make_tip(len(rows[0]), len(rows), [v for row in rows for v in row])
        cases = {
            "no border": tip_from_rows([[9, 1, 3, 4], [5, 6, 7, 8], [1, 2, 3, 255]]),
            "border on every side": tip_from_rows([[0] * 7, [0, 0, 5, 6, 7, 0, 0], [0, 0, 8, 0, 9, 0, 0], [0, 0, 1, 2, 3, 0, 0],
                                                   [0] * 7, [0] * 7]),
            "one pixel": tip_from_rows([[0] * 5, [0, 0, 0, 200, 0], [0] * 5, [0] * 5, [0] * 5]),
            "asymmetric": tip_from_rows([[0] * 8, [0, 0, 0, 0, 0, 3, 4, 5], [0, 0, 0, 0, 6, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 7],
                                         [0, 0, 0, 0, 0, 0, 0, 8]]),
            "code 1 counts": tip_from_rows([[0, 0, 0, 0, 200, 0], [0] * 6, [0] * 6, [1, 0, 0, 0, 0, 0]]),
            "all zero": tip_from_rows([[0] * 3] * 2),
        }
        # Trim follows Invert: a 255 frame around 0 inverts to a 0 frame around 255.
        framed = tip_from_rows([[255] * 5, [255, 0, 0, 0, 255], [255, 0, 0, 0, 255], [255] * 5])
        result = run_node("""
const out = {};
for (const [name, t] of Object.entries(data.cases)) for (const trim of [false, true]) {
  const m = brushes.tipMask(tipOf(t), 'alpha', false, trim);
  out[`${name} ${trim}`] = {codes: [...m.codes], width: m.width, height: m.height, left: m.left, top: m.top, empty: m.empty};
}
const f = brushes.tipMask(tipOf(data.framed), 'alpha', true, true);
out.framed = {codes: [...f.codes], width: f.width, height: f.height, left: f.left, top: f.top, empty: f.empty};
console.log(JSON.stringify(out));
""", {"cases": cases, "framed": framed})
        for name, t in cases.items():
            for trim in (False, True):
                self.assertEqual(result[f"{name} {str(trim).lower()}"], read_mask(t, trim=trim), (name, trim))
        self.assertEqual(result["border on every side true"]["width"], 3)
        self.assertEqual((result["one pixel true"]["codes"], result["one pixel true"]["left"], result["one pixel true"]["top"]), ([200], 3, 1))
        self.assertEqual((result["code 1 counts true"]["width"], result["code 1 counts true"]["height"]), (5, 4))
        self.assertEqual((result["all zero true"]["empty"], result["all zero true"]["width"]), (True, 3))
        self.assertEqual(result["asymmetric false"]["width"], 8)  # untrimmed keeps the whole frame
        self.assertEqual(result["framed"], {"codes": [255] * 6, "width": 3, "height": 2, "left": 1, "top": 1, "empty": False})

    def test_masks_are_cached_per_tip_object_and_never_stale(self):
        run_node("""
const a = tipOf(data.a), b = tipOf(data.b), m = (t, ...s) => brushes.tipMask(t, ...s);
assert.equal(m(a, 'alpha', false, false), m(a, 'alpha', false, false));
assert.notEqual(m(a, 'alpha', false, false), m(a, 'alpha', true, false));
assert.notEqual(m(a, 'alpha', false, false), m(a, 'luminance', false, false));
// Same size, different content: never the other tip's mask.
assert.notDeepEqual(m(b, 'alpha', false, false).codes, m(a, 'alpha', false, false).codes);
const stroke = t => new engine.Stroke(empty(), 128, 128, {...brush, shape: 'custom', tip: t, size: 12, hardness: 40}, 40.25, 50.5).coverage;
const first = stroke(a); assert.notDeepEqual(stroke(b), first); assert.deepEqual(stroke(a), first);
for (const bad of [{width: 2, height: 2, luminance: new Uint8Array(3), alpha: new Uint8Array(4)},
  {width: 2.5, height: 2, luminance: new Uint8Array(5), alpha: new Uint8Array(5)}, {width: 1, height: 1, luminance: [1], alpha: [1]}])
  assert.throws(() => m(bad, 'alpha', false, false), /Invalid custom tip/);
assert.throws(() => m(a, 'red', false, false), /Invalid custom tip/);
assert.throws(() => new engine.Stroke(empty(), 128, 128, {...brush, shape: 'custom'}, 9, 9), /No custom tip is loaded/);
assert.throws(() => engine.stampPreview(128, 128, {...brush, shape: 'custom', tip: tipOf(data.zero)}, 9, 9), /empty as read/);
assert.throws(() => brushes.resolveBrush({tip_channel: 'red'}), /Invalid brush tip_channel/);
assert.throws(() => brushes.resolveBrush({tip_invert: 1}), /Invalid brush tip_invert/);
assert.throws(() => brushes.resolveBrush({shape: 'hexagon'}), /Invalid brush shape/);
""", {"a": textured(6, 4, 1), "b": textured(6, 4, 2), "zero": make_tip(2, 2, [0] * 4)})


class TipFootprintTests(unittest.TestCase):
    def assert_reference(self, cases, exact=False):
        for c, entries in zip(cases, run_node(COVERAGE, cases)):
            expected, margin = reference(c)
            actual = dict(entries)
            self.assertGreater(margin, 1e-9, c)  # no cell sits on a crop edge, so the comparison is robust
            self.assertGreater(len(expected), 0, c)
            self.assertEqual(set(actual), set(expected), c)
            for index, value in expected.items():
                if exact:
                    self.assertEqual(actual[index], float(value), (c, index))
                else:
                    self.assertAlmostEqual(actual[index], float(value), delta=1e-12, msg=(c, index))

    def test_bilinear_sampling_is_exact_at_centres_halfway_and_edges(self):
        codes = [10, 50, 90, 130, 170, 250]
        points = [(x, y) for x in ("0", "0.25", "0.5", "0.75", "1", "1.5", "2", "2.5", "2.75", "3")
                  for y in ("0", "0.5", "1", "1.25", "1.5", "2")] + [("-3", "-3"), ("9", "0.5")]
        result = run_node("""
const mask = {codes: Uint8Array.from(data.codes), width: 3, height: 2};
const one = {codes: Uint8Array.from([77]), width: 1, height: 1};
console.log(JSON.stringify({grid: data.points.map(([x, y]) => brushes.sampleTip(mask, Number(x), Number(y))),
  one: [[0, 0], [0.5, 0.5], [0.9, 0.1]].map(([x, y]) => brushes.sampleTip(one, x, y))}));
""", {"codes": codes, "points": points})
        for (x, y), value in zip(points, result["grid"]):
            self.assertEqual(value, float(bilinear(codes, 3, 2, Q(x), Q(y))), (x, y))
        named = dict(zip(points, result["grid"]))
        self.assertEqual(named[("0.5", "0.5")], 10)       # a pixel centre is its code
        self.assertEqual(named[("2.5", "1.5")], 250)
        self.assertEqual(named[("2.5", "1.25")], 210)      # a quarter of the way from 90 to 250, three quarters on
        self.assertEqual(named[("2.5", "2")], 250)         # the outer half pixel holds the edge code
        self.assertEqual(named[("1", "0.5")], 30)          # halfway between two centres
        self.assertEqual(named[("1", "1")], 90)            # the four-pixel corner
        self.assertEqual(named[("0", "0")], 10)            # the outer half pixel holds the edge code
        self.assertEqual(named[("3", "2")], 250)
        self.assertEqual(result["one"], [77, 77, 77])

    def test_custom_coverage_matches_the_rational_reference_exactly_on_dyadic_geometry(self):
        # Mask pixels per cell are powers of two and scales halve or double, so binary64 is exact here.
        tex, odd = textured(16, 16), textured(7, 5, 3)
        cases = [config(tex, 16, x="64.25", y="64.5"), config(tex, 8, x="40.5", y="80.25"), config(tex, 32, x="70", y="30"),
                 config(odd, 14, x="64.25", y="63.75"), config(odd, 28, sx="2", rotation=90, x="50", y="60.5"),
                 config(odd, 7, sy="0.5", rotation=180, mirror=(True, False)), config(odd, 14, rotation=270, mirror=(False, True)),
                 config(tex, 16, rotation=-90, mirror=(True, True), sx="0.5"), config(tex, 64, rotation=360, x="10.5", y="120"),
                 config(odd, 56, sx="0.5", sy="2", x="100.25", y="5.75", channel="alpha_luminance", invert=True)]
        self.assert_reference(cases, exact=True)

    def test_custom_coverage_matches_the_rational_reference_with_crop_scale_and_softness(self):
        tex, odd, wide = textured(16, 16), textured(7, 5, 3), textured(20, 6, 4)
        cases = []
        for t in (tex, odd, wide):
            for hardness, curve in ((100, "smooth"), (0, "smooth"), (37, "linear"), (70, "sharper")):
                cases.append(config(t, 13, x="64.3125", y="63.6875", sx="1.5", rotation=90, crop=(25, 10, 5, 30),
                                    mirror=(True, False), hardness=hardness, curve=curve))
                cases.append(config(t, 21, x="40.125", y="80.4375", sy="0.7", rotation=180, crop=(0, 33, 12, 0),
                                    hardness=hardness, curve=curve))
        cases.append(config(tex, 128, x="64.25", y="64.25", hardness=30))
        cases.append(config(odd, 1, x="3.5", y="3.5"))
        # Arbitrary angles: the same mapping with one cos/sin pair; edges are clear of every cell centre.
        cases.append(config(odd, 15, x="64.3125", y="63.6875", rotation=30, hardness=40))
        cases.append(config(wide, 23, x="50.25", y="70.75", rotation=-123.4, sx="1.3", crop=(10, 0, 0, 20)))
        self.assert_reference(cases)

    def test_outside_the_tip_rectangle_coverage_is_zero_without_wrap_padding_or_replication(self):
        solid = make_tip(4, 2)  # every edge pixel is 255
        result = run_node("""
const p = engine.stampPreview(128, 128, {...brush, shape: 'custom', tip: tipOf(data), size: 16}, 64, 64);
const covered = [...p.coverage.keys()].filter(i => p.coverage[i] > 0);
console.log(JSON.stringify({covered, values: [...new Set(covered.map(i => p.coverage[i]))]}));
""", solid)
        # 4x2 pixels fit to 16x8 cells around the corner anchor (64, 64): exactly that rectangle at full coverage.
        self.assertEqual(sorted(result["covered"]), sorted(r * 128 + c for r in range(60, 68) for c in range(56, 72)))
        self.assertEqual(result["values"], [1])

    def test_longer_side_fits_size_and_aspect_is_kept_before_scale(self):
        def box(t, size, **extra):
            return config(t, size, x="64.25", y="63.75", **extra)
        cases = {"square 8 at 16": box(make_tip(8, 8), 16), "wide 16x8 at 16": box(make_tip(16, 8), 16),
                 "wide 16x8 at 32": box(make_tip(16, 8), 32), "tall 8x16 at 16": box(make_tip(8, 16), 16),
                 "odd 7x3 at 14": box(make_tip(7, 3), 14), "odd 7x3 at 14 scale x2": box(make_tip(7, 3), 14, sx="2"),
                 "one pixel at 5": box(make_tip(1, 1), 5), "wide 16x8 crop left half": box(make_tip(16, 8), 16, crop=(50, 0, 0, 0)),
                 "tall 3x9 at 9 turned": box(make_tip(3, 9), 9, rotation=90)}
        result = run_node("""
const out = {};
for (const [name, c] of Object.entries(data)) {
  const p = engine.stampPreview(128, 128, options(c), Number(c.x), Number(c.y)), cells = [...p.coverage.keys()].filter(i => p.coverage[i] > 0);
  const f = p.footprint;
  out[name] = {cells, columns: new Set(cells.map(i => i % 128)).size, rows: new Set(cells.map(i => Math.floor(i / 128))).size,
    frame: [2 * f.halfX, 2 * f.halfY]};
}
console.log(JSON.stringify(out));
""", cases)
        expected = {"square 8 at 16": (16, 16), "wide 16x8 at 16": (16, 8), "wide 16x8 at 32": (32, 16),
                    "tall 8x16 at 16": (8, 16), "odd 7x3 at 14": (14, 6), "odd 7x3 at 14 scale x2": (28, 6),
                    "one pixel at 5": (5, 5), "wide 16x8 crop left half": (16, 16), "tall 3x9 at 9 turned": (9, 3)}
        for name, (columns, rows) in expected.items():
            got = result[name]
            self.assertEqual((got["columns"], got["rows"], len(got["cells"])), (columns, rows, columns * rows), name)
            self.assertEqual(set(got["cells"]), set(reference(cases[name])[0]), name)
        # The prepared frame before Scale X/Y: the cropped longer side is Size, the aspect is the tip's.
        self.assertEqual(result["wide 16x8 at 16"]["frame"], [16, 8])
        self.assertEqual(result["tall 8x16 at 16"]["frame"], [8, 16])
        self.assertEqual(result["odd 7x3 at 14 scale x2"]["frame"], [14, 6])
        self.assertEqual(result["wide 16x8 crop left half"]["frame"], [16, 16])

    def test_transform_order_is_read_invert_trim_crop_mirror_fit_scale_rotate_place(self):
        # Asymmetric on purpose: a bordered, graded tip, trimmed, cropped, mirrored, stretched and turned.
        width, height = 10, 7
        alpha = [((x * 29 + y * 53) % 200 + 50) if 2 <= x <= 8 and 1 <= y <= 5 and not (x > 6 and y > 3) else 0
                 for y in range(height) for x in range(width)]
        t = make_tip(width, height, alpha)
        c = config(t, 14, x="60.25", y="70.5", sx="2", rotation=90, mirror=(True, False), crop=(20, 0, 10, 30), trim=True)
        tall = config(make_tip(3, 8, [(i * 31) % 250 + 5 for i in range(24)]), 12, x="64", y="64", hardness=40)
        inverted = config(make_tip(6, 5, [255 if x in (0, 5) or y in (0, 4) else 0 for y in range(5) for x in range(6)]),
                          15, x="64.5", y="64.5", invert=True, trim=True)
        actual, actual_tall, actual_inverted = (dict(e) for e in run_node(COVERAGE, [c, tall, inverted]))

        def matches(got, c, order="specified"):
            expected = reference(c, order)[0]
            return set(got) == set(expected) and all(abs(got[i] - float(v)) <= 1e-12 for i, v in expected.items())
        self.assertTrue(matches(actual, c))
        for order in ("crop-before-trim", "mirror-before-crop", "fit-before-crop", "rotate-before-scale", "aspect-ignored"):
            self.assertFalse(matches(actual, c, order), order)
        self.assertTrue(matches(actual_tall, tall))
        for order in ("fit-width", "aspect-ignored"):
            self.assertFalse(matches(actual_tall, tall, order), order)
        self.assertTrue(matches(actual_inverted, inverted))
        self.assertFalse(matches(actual_inverted, inverted, "invert-after-trim"))
        # Readable: the trimmed 7x5 tip, cropped to 5.6x3 pixels, fits Size 14 across; x2 makes it 28 wide, then
        # a quarter turn stands it upright: 28 rows by 7.5 columns of frame.
        rows, columns = {i // 128 for i in actual}, {i % 128 for i in actual}
        self.assertEqual((max(rows) - min(rows) + 1, max(columns) - min(columns) + 1), (28, 8))

    def test_hardness_100_paints_the_sampled_mask_and_softness_fades_only_the_envelope(self):
        tex = textured(16, 16)
        checker = make_tip(16, 16, [255 if (x + y) % 2 == 0 else 0 for y in range(16) for x in range(16)])
        result = run_node("""
const at = (t, o) => engine.stampPreview(128, 128, {...brush, shape: 'custom', tip: tipOf(t), ...o}, 64, 64).coverage;
const out = {};
for (const [name, t] of Object.entries({tex: data.tex, checker: data.checker})) {
  out[name] = {hard: [...at(t, {})]};
  for (const [hardness, curve] of [[0, 'smooth'], [50, 'smooth'], [50, 'linear'], [80, 'sharper']])
    out[name][`${hardness} ${curve}`] = [...at(t, {hardness, falloff_curve: curve})];
}
// One click at full Influence and Amount paints the codes themselves: 255 x code / 255.
out.painted = [...new engine.Stroke(empty(), 128, 128, {...brush, shape: 'custom', tip: tipOf(data.tex)}, 64.3, 64.2).result()];
console.log(JSON.stringify(out));
""", {"tex": tex, "checker": checker})
        alpha = tex["alpha"]
        for row in range(128):
            for col in range(128):
                inside = 56 <= row < 72 and 56 <= col < 72
                code = alpha[(row - 56) * 16 + col - 56] if inside else 0
                self.assertEqual(result["tex"]["hard"][row * 128 + col], code / 255)
                self.assertEqual(result["painted"][row * 128 + col], code)
        for name, t in (("tex", tex), ("checker", checker)):
            hard = result[name]["hard"]
            for key, soft in result[name].items():
                if key == "hard":
                    continue
                hardness, curve = int(key.split()[0]), key.split()[1]
                for row in range(56, 72):
                    for col in range(56, 72):
                        i = row * 128 + col
                        reach = max(abs(Q(2 * col + 1, 2) - 64), abs(Q(2 * row + 1, 2) - 64)) / 8
                        inner = Q(hardness, 100)
                        envelope = 1 if reach <= inner else 0 if reach >= 1 else CURVES[curve]((1 - reach) / (1 - inner))
                        if envelope == 1:
                            self.assertEqual(soft[i], hard[i], (name, key, i))  # untouched inside the Hardness boundary
                        else:
                            self.assertAlmostEqual(soft[i], float(Q(t["alpha"][(row - 56) * 16 + col - 56], 255) * envelope),
                                                   delta=1e-12, msg=(name, key, i))
                        if hard[i] == 0:
                            self.assertEqual(soft[i], 0)  # a 0 code is never filled in
        # The checker keeps its contrast: every 0 stays 0 and every 255 follows the envelope alone.
        soft = result["checker"]["50 smooth"]
        self.assertEqual({soft[i] for i in range(16384) if result["checker"]["hard"][i] == 0}, {0})
        self.assertEqual(soft[63 * 128 + 63], 1)


class TipBrushTests(unittest.TestCase):
    def test_custom_tip_sets_coverage_only_and_the_value_profile_sets_targets_only(self):
        tex = textured(12, 8, 5)
        solid = make_tip(12, 8)
        lin = {"value_profile": "linear", "gradient_start": 0, "gradient_end": 255}
        result = run_node("""
const at = (t, o = {}) => engine.stampPreview(128, 128, {...brush, shape: 'custom', tip: tipOf(t), size: 24, ...o}, 64, 64);
const textured = at(data.tex, data.lin), solid = at(data.solid, data.lin), uniform = at(data.tex);
// The tip's codes change coverage, never targets; the gradient changes targets, never coverage.
for (let i = 0; i < 16384; i++) if (textured.coverage[i] > 0) assert.equal(textured.targets[i], solid.targets[i]);
assert.notDeepEqual(textured.coverage, solid.coverage);
assert.deepEqual(textured.coverage, uniform.coverage); assert.equal(uniform.targets, null);
for (const o of [{gradient_angle: 90}, {gradient_curve: 2.5}, {value_profile: 'radial'}, {value_profile: 'square', gradient_inner: 20}]) {
  const other = at(data.tex, {...data.lin, ...o});
  assert.deepEqual(other.coverage, textured.coverage); assert.notDeepEqual(other.targets, textured.targets);
}
const swapped = at(data.tex, {...data.lin, gradient_start: 255, gradient_end: 0});
textured.targets.forEach((t, i) => { if (textured.coverage[i] > 0) assert.equal(t + swapped.targets[i], 255); });
console.log(JSON.stringify([...textured.coverage.keys()].filter(i => textured.coverage[i] > 0).map(i => [i, textured.targets[i]])));
""", {"tex": tex, "solid": solid, "lin": lin})
        # Linear 0->255 at 0 degrees: T = q(255 (x/halfX + 1)/2) at the cell's brush-local x; the frame is 24x16 cells.
        self.assertEqual(len(result), 24 * 16)
        for index, target in result:
            x = Q(2 * (index % 128) + 1, 2) - 64
            self.assertEqual(target, nearest(255 * (x / 12 + 1) / 2), index)

    def test_build_up_flow_and_amount_with_a_custom_tip_and_gradient(self):
        result = run_node("""
const base = Uint8Array.from({length: 16384}, (_, i) => (i * 29 + 11) % 256), out = [];
const tip = tipOf(data.tex);
for (const [flow, amount, passes] of [[10, 60, 1], [30, 70, 3], [100, 50, 20]]) {
  const o = {...brush, shape: 'custom', tip, size: 14, hardness: 30, value_profile: 'linear', gradient_angle: 90,
    gradient_start: 0, gradient_end: 255, build_up: true, flow, amount};
  const s = new engine.Stroke(base, 128, 128, o, 20.5, 64.25);
  for (let k = 0; k < passes; k++) { s.add(100.5, 64.25); s.add(20.5, 64.25); }
  // Pointer-event count never matters: the same path in many collinear pieces is identical.
  const split = new engine.Stroke(base, 128, 128, o, 20.5, 64.25);
  for (let k = 0; k < passes; k++) { for (let x = 22.5; x <= 100.5; x += 2) split.add(x, 64.25); for (let x = 98.5; x >= 20.5; x -= 2) split.add(x, 64.25); }
  assert.deepEqual(split.coverage, s.coverage); assert.deepEqual(split.targets, s.targets); assert.deepEqual(split.result(), s.result());
  // Build-up selects targets as a single stamp does, and the profile never changes coverage.
  const once = new engine.Stroke(base, 128, 128, {...o, build_up: false}, 20.5, 64.25);
  for (let k = 0; k < passes; k++) { once.add(100.5, 64.25); once.add(20.5, 64.25); }
  assert.deepEqual(s.targets, once.targets);
  const uniform = new engine.Stroke(base, 128, 128, {...o, value_profile: 'uniform'}, 20.5, 64.25);
  for (let k = 0; k < passes; k++) { uniform.add(100.5, 64.25); uniform.add(20.5, 64.25); }
  assert.deepEqual(uniform.coverage, s.coverage);
  // The tip's codes are the per-stamp weights: a solid tip of the same frame builds up differently.
  const solid = new engine.Stroke(base, 128, 128, {...o, tip: tipOf(data.solid)}, 20.5, 64.25), one = new engine.Stroke(base, 128, 128, o, 20.5, 64.25);
  solid.add(100.5, 64.25); one.add(100.5, 64.25); assert.notDeepEqual(solid.coverage, one.coverage);
  out.push({amount, coverage: [...s.coverage], targets: [...s.targets], result: [...s.result()]});
}
console.log(JSON.stringify({base: [...base], strokes: out}));
""", {"tex": textured(10, 10, 6), "solid": make_tip(10, 10)})
        base = result["base"]
        for stroke in result["strokes"]:
            covered = 0
            for i in range(16384):
                m, target = stroke["coverage"][i], stroke["targets"][i]
                delta = ((target - base[i]) * stroke["amount"]) * m / 100
                step = math.floor(abs(delta)) + (abs(delta) - math.floor(abs(delta)) >= 0.5)
                self.assertEqual(stroke["result"][i], base[i] + (step if delta >= 0 else -step), i)
                covered += m > 0
            self.assertGreater(covered, 900)
        # Twenty full-Flow passes at Amount 50: fully covered cells move exactly half way, never further.
        last = result["strokes"][2]
        full = [i for i in range(16384) if last["coverage"][i] == 1]
        self.assertGreater(len(full), 500)
        for i in full:
            delta = Q((last["targets"][i] - base[i]) * 50, 100)
            self.assertEqual(last["result"][i], base[i] + (1 if delta >= 0 else -1) * nearest(abs(delta)))
        for i in range(16384):
            self.assertLessEqual(abs(last["result"][i] - base[i]), nearest(Q(abs(last["targets"][i] - base[i]) * 50, 100)), i)

    def test_raise_only_and_lower_only_with_a_custom_tip_and_gradient(self):
        result = run_node("""
const base = new Uint8Array(16384).fill(128), out = {};
for (const apply_mode of ['normal', 'raise_only', 'lower_only']) for (const amount of [100, 37]) {
  const s = new engine.Stroke(base, 128, 128, {...brush, shape: 'custom', tip: tipOf(data), size: 32, hardness: 60,
    value_profile: 'linear', gradient_start: 0, gradient_end: 255, apply_mode, amount}, 64.25, 63.5);
  s.add(70.25, 66.5);
  out[`${apply_mode} ${amount}`] = {coverage: [...s.coverage], targets: [...s.targets], result: [...s.result()]};
}
console.log(JSON.stringify(out));
""", textured(9, 9, 2))
        moved = {"up": 0, "down": 0}
        for key, s in result.items():
            mode, amount = key.split()
            for i in range(16384):
                # E1's evaluation order in binary64, exactly as the engine: ((T - B) x Amount) x M / 100.
                delta = ((s["targets"][i] - 128) * int(amount)) * s["coverage"][i] / 100
                step = math.floor(abs(delta)) + (abs(delta) - math.floor(abs(delta)) >= 0.5)
                after = 128 + (step if delta >= 0 else -step)
                want = max(128, after) if mode == "raise_only" else min(128, after) if mode == "lower_only" else after
                self.assertEqual(s["result"][i], want, (key, i))
                if mode == "normal":
                    moved["up"] += after > 128
                    moved["down"] += after < 128
        self.assertGreater(moved["up"], 100)
        self.assertGreater(moved["down"], 100)
        self.assertTrue(all(v >= 128 for v in result["raise_only 100"]["result"]))
        self.assertTrue(all(v <= 128 for v in result["lower_only 100"]["result"]))

    def test_erase_and_restore_use_the_custom_footprint_and_ignore_the_profile(self):
        result = run_node("""
const base = Uint8Array.from({length: 16384}, (_, i) => (i * 13) % 256);
const opening = Uint8Array.from({length: 16384}, (_, i) => 255 - (i * 7) % 256), out = {};
const tip = tipOf(data), gradient = {value_profile: 'radial', gradient_start: 0, gradient_end: 255, gradient_curve: 2};
for (const tool of ['erase', 'restore']) for (const hardness of [40, 100]) {
  const o = {...brush, shape: 'custom', tip, tool, size: 20, hardness, amount: 70};
  const plain = new engine.Stroke(base, 128, 128, o, 30.5, 40.25, opening), graded = new engine.Stroke(base, 128, 128, {...o, ...gradient}, 30.5, 40.25, opening);
  for (const p of [[90, 80.5], [91, 20]]) { plain.add(...p); graded.add(...p); }
  assert.equal(graded.profile, null); assert.equal(graded.targets, null);
  assert.deepEqual(graded.coverage, plain.coverage); assert.deepEqual(graded.result(), plain.result());
  assert.equal(engine.stampPreview(128, 128, {...o, ...gradient}, 64, 64).targets, null);
  out[`${tool} ${hardness}`] = {coverage: [...graded.coverage], result: [...graded.result()]};
}
console.log(JSON.stringify({base: [...base], opening: [...opening], strokes: out}));
""", textured(8, 6, 9))
        base, opening = result["base"], result["opening"]
        for key, s in result["strokes"].items():
            tool = key.split()[0]
            self.assertTrue(any(0 < w < 1 for w in s["coverage"]), key)  # the tip's codes are partial coverage
            for i in range(16384):
                target = 0 if tool == "erase" else opening[i]
                delta = ((target - base[i]) * 70) * s["coverage"][i] / 100
                step = math.floor(abs(delta)) + (abs(delta) - math.floor(abs(delta)) >= 0.5)
                self.assertEqual(s["result"][i], base[i] + (step if delta >= 0 else -step), (key, i))

    def test_default_brush_bits_are_unchanged_with_e5_settings_absent_default_or_inert(self):
        groups = run_node("""
const {createHash} = await import('node:crypto');
const initial = Uint8Array.from({length: 16384}, (_, i) => (i * 37 + (i >> 7) * 11) % 256);
const path = [[105.125, 57.25], [110, 70], [60, 80], [10, 10], [-5, 64.3], [130, 64.3], [64.5, 64.5]];
const out = {};
const e5 = Object.fromEntries(Object.entries(brushes.BRUSH_DEFAULTS).filter(([k]) => k.startsWith('tip_')));
assert.deepEqual(e5, {tip_channel: 'alpha', tip_invert: false, tip_trim: false});
const inert = {tip_channel: 'alpha_luminance', tip_invert: true, tip_trim: true, tip: tipOf(data.tip), custom_tip: 'data:image/png;base64,AAAA'};
for (const [variant, extra] of Object.entries({absent: {}, defaults: e5, inert})) {
  const groups = {};
  for (const tool of ['paint', 'erase']) for (const size of [1, 9, 33]) {
    const hash = createHash('sha256');
    for (const hardness of [0, 37, 99, 100]) for (const amount of [1, 29, 50, 100]) {
      const s = new engine.Stroke(initial, 128, 128, {tool, size, influence: 173, hardness, amount, ...extra}, 5.125, 7.25);
      for (const p of path) s.add(...p);
      hash.update(s.result()); hash.update(new Uint8Array(s.coverage.buffer));
    }
    groups[`${tool}-${size}`] = hash.digest('hex');
  }
  out[variant] = groups;
}
console.log(JSON.stringify(out));
""", {"tip": textured(5, 5)})
        for variant in ("absent", "defaults", "inert"):
            self.assertEqual(groups[variant], E1_GOLDEN, variant)


class TipEditorTests(unittest.TestCase):
    def test_custom_without_a_tip_is_a_visible_invalid_state_that_never_paints(self):
        run_editor(r"""
const advanced = summary().parent;
// Basic and the Advanced groups are as before: the Custom Tip group nests in Brush Shape & Transform.
assert.deepEqual(advanced.children.filter(e => e.tagName === 'DETAILS').map(g => g.children[0].textContent),
  ['Brush Behavior', 'Brush Shape & Transform', 'Value Profile', 'Field Tools']);
assert.equal(tipGroup().parent, shapeGroup()); assert.equal(tipGroup().hidden, true); assert.equal(tipGroup().open, false);
assert.equal(all().filter(e => e.type === 'text').length, 41);  // E5 adds no numeric control
custom();
assert.equal(tipGroup().hidden, false); assert.equal(heading('Custom Tip').textContent, 'Custom Tip · none loaded');
assert.equal(heading('Brush Shape').textContent, 'Brush Shape & Transform · Custom (no tip)');
assert.equal(summary().textContent, 'Advanced · Custom (no tip)'); assert.equal(button('Reset Brush').hidden, false);
assert.equal(status().textContent, 'No custom tip is loaded. Import a PNG under Custom Tip.'); assert.equal(status().style.color, '#ffb5ab');
for (const text of ['Clear Custom Tip', 'Alpha', 'Invert Tip', 'Trim Empty Border']) {
  let hidden = false; for (let e = button(text); e; e = e.parent) hidden ||= e.hidden; assert.ok(hidden, text);
}
assert.equal(find('tip-frame').hidden, true);
// No preview, no paint, no history: the message says why.
pointer('pointermove', 64, 64); dom.flush(); assert.equal(preview().hidden, true); assert.equal(outline().style.display, 'none');
click(64, 64); assert.equal(error(), 'No custom tip is loaded. Import a PNG under Custom Tip.');
assert.ok(session().codes.every(v => v === 0)); assert.equal(session().history.undoEntries.length, 0);
pointer('pointerdown', 20, 20, {shiftKey: true}); dom.flush(); assert.ok(session().codes.every(v => v === 0));
// Done keeps Shape Custom and stores no tip.
press('Done'); await settle();
assert.deepEqual(result.settings, {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent', shape: 'custom'});
""")

    def test_import_thumbnail_reading_options_badges_and_clear(self):
        t = textured(6, 4, 1)
        t["alpha"][0] = 0
        t["alpha"][23] = 0
        rgba = tip_png(t, 6)
        opaque = tip_png(make_tip(5, 3, None, [i * 15 for i in range(15)]))
        zero = tip_png(make_tip(2, 2, [0, 0, 0, 0], [9, 9, 9, 9]))
        bordered = tip_png(make_tip(7, 5, [200 if 2 <= x <= 4 and 1 <= y <= 2 else 0 for y in range(5) for x in range(7)]))
        run_editor(r"""
custom(); const stored = () => JSON.stringify(ui.editorSettings(settings()));
await importTip(data.rgba);
assert.equal(error(), ''); assert.deepEqual(plain(session().tip), data.planes);
assert.equal(heading('Custom Tip').textContent, 'Custom Tip · 6×4'); assert.equal(heading('Brush Shape').textContent, 'Brush Shape & Transform · Custom');
assert.equal(summary().textContent, 'Advanced · Custom'); assert.equal(status().hidden, true);
assert.equal(session().history.undoEntries.length, 0); assert.ok(session().codes.every(v => v === 0));
// The thumbnail is the prepared tip in gray (255 white), display only, aspect kept in 96 px.
const shown = () => [...thumbnail().pixels].filter((_, i) => i % 4 === 0);
assert.deepEqual(shown(), data.planes.alpha); assert.equal(thumbnail().width, 6); assert.equal(thumbnail().style.width, '96px');
assert.equal(thumbnail().style.height, '64px');
assert.match(caption().textContent, /^Prepared tip 6×4 · \d+\.\d KB kept with the node$/);
// Reading options: one choice, two toggles; each is a setting, never history.
for (const [label, channel] of [['Luminance', 'luminance'], ['Alpha × Luminance', 'alpha_luminance'], ['Alpha', 'alpha']]) {
  pressIn(tipGroup(), label); assert.equal(settings().tip_channel, channel);
  assert.equal(descendants(tipGroup()).find(e => e.textContent === label).attributes['aria-pressed'], 'true');
  assert.deepEqual(shown(), [...brushes.tipMask(session().tip, channel, false, false).codes]);
}
pressIn(tipGroup(), 'Luminance'); press('Invert Tip'); press('Trim Empty Border');
assert.equal(heading('Custom Tip').textContent, 'Custom Tip · 6×4 · Luminance · Inverted · Trimmed');
assert.equal(heading('Brush Shape').textContent, 'Brush Shape & Transform · Custom · Luminance · Inverted · Trimmed');
assert.equal(summary().textContent, 'Advanced · Custom · Luminance · Inverted · Trimmed');
assert.deepEqual(shown(), [...brushes.tipMask(session().tip, 'luminance', true, true).codes]);
pressIn(tipGroup(), 'Alpha'); press('Invert Tip');
assert.equal(caption().textContent.split(' · ')[0], 'Prepared tip 6×4');
type('Crop Left (%)', 25); assert.equal(find('tip-crop').hidden, false); assert.equal(find('tip-crop').style.left, '25%');
type('Crop Left (%)', 0); assert.equal(find('tip-crop').hidden, true);
assert.equal(session().history.undoEntries.length, 0);
// A PNG with no transparency: Alpha covers its rectangle, and the editor says so.
await importTip(data.opaque); pressIn(tipGroup(), 'Alpha');
assert.match(status().textContent, /no transparency, so Alpha covers its whole rectangle/);
pressIn(tipGroup(), 'Luminance'); assert.equal(status().hidden, true);
// Trim keeps the smallest rectangle holding every positive code; the caption names both sizes.
await importTip(data.bordered); pressIn(tipGroup(), 'Alpha');
assert.equal(heading('Custom Tip').textContent, 'Custom Tip · 7×5 · Trimmed');
assert.match(caption().textContent, /^Prepared tip 3×2 \(trimmed from 7×5\) · \d+\.\d KB kept with the node$/);
assert.deepEqual(shown(), Array(6).fill(200)); assert.equal(thumbnail().style.height, '64px');
press('Trim Empty Border'); assert.equal(caption().textContent.split(' · ')[0], 'Prepared tip 7×5');
// Every value 0 as read: flagged everywhere, and it never paints.
await importTip(data.zero); pressIn(tipGroup(), 'Alpha');
assert.equal(heading('Custom Tip').textContent, 'Custom Tip · 2×2 · empty'); assert.equal(heading('Brush Shape').textContent, 'Brush Shape & Transform · Custom (empty)');
assert.match(status().textContent, /^This custom tip is empty as read: every value is 0/);
click(64, 64); assert.match(error(), /empty as read/); assert.equal(session().history.undoEntries.length, 0);
press('Invert Tip'); assert.equal(heading('Custom Tip').textContent, 'Custom Tip · 2×2 · Inverted');
click(64, 64); assert.equal(session().history.undoEntries.length, 1);
// A failed import names the reason and keeps the current tip; an oversized file is never read.
const kept = session().tip, before = stored();
await importTip(Buffer.from('not a png').toString('base64'));
assert.equal(error(), 'Cannot import the custom tip: Not a PNG file.'); assert.equal(session().tip, kept); assert.equal(stored(), before);
const huge = {size: 8388609, arrayBuffer: () => assert.fail('oversized read')};
await importFile(huge); assert.match(error(), /at most 8,388,608 bytes/); assert.equal(session().tip, kept);
// The drop zone imports a tip and stops the drop reaching the field importer.
const event = fire(find('tip-drop'), 'drop', {dataTransfer: {files: [fileOf(data.rgba)]}});
assert.ok(event.stopped && event.prevented);
await until(() => session().tip !== kept, 'drop'); assert.equal(session().tip.width, 6);
assert.equal(session().history.undoEntries.length, 1);
// Clear removes the tip and how it was read; Shape stays Custom and nothing paints.
press('Luminance'); press('Clear Custom Tip');
assert.equal(settings().custom_tip, undefined); assert.equal(session().tip, null);
assert.deepEqual([settings().tip_channel, settings().tip_invert, settings().tip_trim], ['alpha', false, false]);
assert.equal(settings().shape, 'custom'); assert.equal(heading('Custom Tip').textContent, 'Custom Tip · none loaded');
assert.equal(session().history.undoEntries.length, 1);
press('Disk'); assert.equal(tipGroup().hidden, true);
""", {"rgba": rgba, "planes": t, "opaque": opaque, "zero": zero, "bordered": bordered})

    def test_cursor_preview_is_exactly_the_next_custom_stamp_with_targets_heat_and_outline(self):
        run_editor(r"""
await (async () => { custom(); await importTip(data.tip); })();
let heat = false;
const check = (x, y) => {
  pointer('pointermove', x, y); dom.flush();
  const expected = engine.stampPreview(128, 128, engineBrush(), x, y), pixels = preview().pixels;
  assert.equal(preview().hidden, false); assert.equal(outline().style.display, '');
  for (let i = 0; i < 16384; i++) {
    const w = expected.coverage[i], t = expected.targets?.[i], px = [...pixels.slice(i * 4, i * 4 + 4)];
    if (!(w > 0)) { assert.deepEqual(px, [0, 0, 0, 0]); continue; }
    const color = !expected.targets ? [64, 160, 255] : heat ? view.heatColor(t) : [t, t, t];
    assert.deepEqual(px, [...color, Math.max(1, Math.round(w * 160))], `cell ${i}`);
  }
  for (const layer of [preview(), outline()]) assert.equal(layer.style.transform, canvas().style.transform);
  const before = session().codes.slice(), count = session().history.undoEntries.length;
  click(x, y);
  const stamped = new engine.Stroke(before, 128, 128, engineBrush(), x, y, session().initial);
  assert.deepEqual(stamped.coverage, expected.coverage); assert.deepEqual(stamped.targets, expected.targets);
  assert.deepEqual(session().codes, stamped.result()); assert.equal(session().history.undoEntries.length, count + 1);
  session().undo(); dom.flush();
  return expected;
};
const hard = check(40.3, 50.7); assert.ok(hard.coverage.some(w => w > 0 && w < 1));
Object.assign(settings(), {size: 21, hardness: 35, scale_x: 1.5, rotation_degrees: 90, crop_left: 25, mirror_horizontal: true,
  tip_channel: 'alpha_luminance'});
const soft = check(70.25, 60.5); assert.ok(soft.coverage.some(w => w > 0 && w < 1));
Object.assign(settings(), {value_profile: 'linear', gradient_start: 0, gradient_end: 255, rotation_degrees: 30});
const graded = check(70.25, 60.5); assert.ok(new Set(graded.targets).size > 10);
press('Heat View'); heat = true; check(64.5, 64.5);
// The outline is the transformed crop rectangle of the tip frame.
pointer('pointermove', 64, 64); dom.flush();
const f = engine.stampPreview(128, 128, engineBrush(), 64, 64).footprint;
const points = view.footprintOutline(f);
assert.equal(points.length, 4);
for (const [px, py] of points) {
  const [x, y] = brushes.footprintLocal(f, px, py, [0, 0]);
  assert.ok(Math.abs(Math.abs(x) - f.halfX) < 1e-9 && Math.abs(Math.abs(y) - f.halfY) < 1e-9);
}
// Zoom and pan keep the tint on the field.
for (let i = 0; i < 3; i++) fire(find('viewport'), 'wheel', {clientX: 300, clientY: 200, deltaY: -1});
fire(find('viewport'), 'pointerdown', {button: 1, clientX: 50, clientY: 50});
fire(find('viewport'), 'pointermove', {clientX: 90, clientY: 20}); fire(find('viewport'), 'pointerup', {button: 1}); dom.flush();
const [px, py, z] = canvas().style.transform.match(/translate\(([-\d.]+)px,([-\d.]+)px\) scale\(([-\d.]+)\)/).slice(1).map(Number);
fire(find('viewport'), 'pointermove', {clientX: px + 64.25 * z, clientY: py + 70.5 * z}); dom.flush();
const zoomed = engine.stampPreview(128, 128, engineBrush(), 64.25, 70.5);
for (let i = 0; i < 16384; i++) assert.equal(preview().pixels[i * 4 + 3] > 0, zoomed.coverage[i] > 0);
// Erase keeps the blue coverage tint of the same custom footprint.
press('Erase'); fire(find('viewport'), 'pointermove', {clientX: px + 64 * z, clientY: py + 64 * z}); dom.flush();
const erase = engine.stampPreview(128, 128, engineBrush(), 64, 64);
assert.equal(erase.targets, null);
for (let i = 0; i < 16384; i++) if (erase.coverage[i] > 0) assert.deepEqual([...preview().pixels.slice(i * 4, i * 4 + 3)], [64, 160, 255]);
""", {"tip": tip_png(textured(9, 7, 3))})

    def test_strokes_build_up_and_shift_lines_are_one_history_entry_and_tip_changes_none(self):
        run_editor(r"""
const field = Uint8Array.from({length: 16384}, (_, i) => (i % 128) * 2);
await reopen(field, {size: 12, influenceUnit: 'code'}); custom(); await importTip(data.tip);
for (const label of ['Luminance', 'Alpha × Luminance', 'Alpha']) pressIn(tipGroup(), label);
press('Invert Tip'); press('Invert Tip'); press('Trim Empty Border'); press('Trim Empty Border');
assert.deepEqual(session().codes, field); assert.equal(session().history.undoEntries.length, 0);
// One Build-up scrub with many pointer events is one entry and replays the sampled path exactly.
press('Build-up'); press('Raise Only'); type('Influence (0–255)', 200);
const path = [[20, 64], [100, 64], [20, 64], [100, 64.5], [60, 64.5]];
pointer('pointerdown', ...path[0]); for (const p of path.slice(1)) pointer('pointermove', ...p);
pointer('pointerup', ...path.at(-1)); dom.flush();
const replay = new engine.Stroke(field, 128, 128, engineBrush(), ...path[0], session().initial);
for (const p of path.slice(1)) replay.add(...p); replay.add(...path.at(-1));
assert.deepEqual(session().codes, replay.result()); assert.equal(session().history.undoEntries.length, 1);
session().codes.forEach((v, i) => assert.ok(v >= field[i])); assert.ok(session().codes.some((v, i) => v > field[i]));
// A Shift-click line uses the same custom footprint and profile from the last endpoint: one more entry.
press('Normal'); press('Build-up'); press('Linear Gradient'); type('Rotation (°)', 45);
const before = session().codes.slice();
pointer('pointerdown', 120.5, 20.5, {shiftKey: true}); dom.flush();
const line = new engine.Stroke(before, 128, 128, engineBrush(), 60, 64.5, session().initial); line.add(120.5, 20.5);
assert.deepEqual(session().codes, line.result()); assert.equal(session().history.undoEntries.length, 2);
assert.ok(new Set(line.targets).size > 10);
const after = session().codes.slice();
press('Undo'); assert.deepEqual(session().codes, before); press('Redo'); assert.deepEqual(session().codes, after);
// Importing another tip of the same size changes the next stroke, never an earlier one or the history.
await importTip(data.other); assert.equal(session().history.undoEntries.length, 2); assert.deepEqual(session().codes, after);
click(30.5, 100.5);
const next = new engine.Stroke(after, 128, 128, engineBrush(), 30.5, 100.5, session().initial);
assert.deepEqual(session().codes, next.result());
const stale = new engine.Stroke(after, 128, 128, {...engineBrush(), tip: tipOf(data.first)}, 30.5, 100.5, session().initial);
assert.notDeepEqual(next.coverage, stale.coverage);
""", {"tip": tip_png(textured(8, 8, 1)), "other": tip_png(textured(8, 8, 2)), "first": textured(8, 8, 1)})

    def test_done_keeps_the_tip_in_brush_settings_and_reopen_restores_it_exactly(self):
        t = textured(7, 5, 4)
        run_editor(r"""
const E1 = {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent'};
press('Done'); await settle(); assert.deepEqual(result.settings, E1);
controller = open(); dom.flush(); custom(); await importTip(data.tip, 'C:\\Users\\someone\\Brushes\\secret-tip.png');
pressIn(tipGroup(), 'Luminance'); press('Trim Empty Border');
click(64.3, 63.7); const painted = session().codes.slice();
press('Done'); await settle();
const stored = result.settings, text = JSON.stringify(stored);
assert.deepEqual(Object.keys(stored), [...Object.keys(E1), 'shape', 'tip_channel', 'tip_trim', 'custom_tip']);
assert.deepEqual({...stored, custom_tip: undefined}, {...E1, shape: 'custom', tip_channel: 'luminance', tip_trim: true, custom_tip: undefined});
assert.ok(tips.storedTipValid(stored.custom_tip));
for (const leak of ['secret', 'someone', 'Brushes', 'C:', '.png', 'blob:']) assert.ok(!text.includes(leak), leak);
assert.deepEqual(plain(await tips.decodeTipDataUrl(stored.custom_tip)), data.planes);
// Reopen: the stored tip is read again, exactly, and paints exactly the same stroke.
await reopen(empty(), stored);
assert.deepEqual(plain(session().tip), data.planes); assert.equal(heading('Custom Tip').textContent, 'Custom Tip · 7×5 · Luminance · Trimmed');
click(64.3, 63.7); assert.deepEqual(session().codes, painted);
// Settings-only: Done again stores the same string, byte for byte.
press('Done'); await settle(); assert.equal(JSON.stringify(result.settings), text);
// Reset Brush keeps the imported tip, returns Shape to Disk and the reading to its defaults.
await reopen(empty(), stored); press('Reset Brush');
assert.equal(settings().shape, 'disk'); assert.equal(settings().custom_tip, stored.custom_tip);
assert.deepEqual([settings().tip_channel, settings().tip_trim], ['alpha', false]);
assert.equal(heading('Custom Tip').textContent, 'Custom Tip · 7×5 · not in use'); assert.equal(tipGroup().hidden, false);
assert.match(status().textContent, /Kept with this node: choose Shape Custom to paint with it\./);
assert.equal(summary().textContent, 'Advanced'); assert.equal(button('Reset Brush').hidden, true);
// The next default stroke is the retained E1 stroke, bit for bit.
click(64.3, 63.7);
assert.deepEqual(session().codes, new engine.Stroke(empty(), 128, 128, {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100}, 64.3, 63.7).result());
assert.equal(session().codes.filter(v => v).length, 208);
press('Done'); await settle(); assert.deepEqual(result.settings, {...E1, custom_tip: stored.custom_tip});
// Choosing Custom again paints the kept tip.
await reopen(empty(), result.settings); custom(); click(64.3, 63.7);
assert.deepEqual(session().codes, new engine.Stroke(empty(), 128, 128, engineBrush(), 64.3, 63.7).result());
// Clear Custom Tip then Done stores no tip at all.
press('Clear Custom Tip'); press('Done'); await settle();
assert.deepEqual(result.settings, {...E1, shape: 'custom'});
// Cancel discards an import.
controller = open(); dom.flush(); custom(); await importTip(data.tip); const done = result; controller.cancel();
assert.equal(result, done);
""", {"tip": tip_png(t), "planes": t})

    def test_stored_settings_are_sanitized_and_an_unreadable_tip_is_kept_and_reported(self):
        good = "data:image/png;base64," + tip_png(textured(3, 3))
        unreadable = "data:image/png;base64," + b64(b"\x89PNG\r\n\x1a\n" + bytes(30))
        run_editor(r"""
const E1 = {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent'};
// E1-E4 workflows open and save byte for byte: no E5 key appears.
const e4 = {tool: 'paint', size: 9, influence: 77, hardness: 40, amount: 60, influenceUnit: 'code', shape: 'diamond',
  rotation_degrees: 22.5, crop_left: 10, build_up: true, flow: 40, value_profile: 'radial', gradient_curve: 3};
await reopen(empty(), e4); press('Done'); await settle(); assert.equal(JSON.stringify(result.settings), JSON.stringify(e4));
// Invalid stored values fall back to their defaults; an invalid tip string is not kept.
const prefix = 'data:image/png;base64,';
for (const bad of [42, '', 'data:image/jpeg;base64,AAAA', prefix + 'AAA', prefix + 'AA=A', prefix + 'A B=', prefix + '====',
  prefix + 'A'.repeat(tips.TIP_LIMITS.stored), 'C:\\brush.png'])
  assert.deepEqual(ui.editorSettings({custom_tip: bad}), E1, String(bad).slice(0, 30));
assert.deepEqual(ui.editorSettings({shape: 'custom', tip_channel: 'red', tip_invert: 'yes', tip_trim: 1, custom_tip: data.good}),
  {...E1, shape: 'custom', custom_tip: data.good});
// A well-formed string that is no readable PNG is kept unchanged, reported, and never paints.
await reopen(empty(), {...E1, shape: 'custom', custom_tip: data.unreadable});
assert.equal(heading('Custom Tip').textContent, 'Custom Tip · unreadable');
assert.equal(heading('Brush Shape').textContent, 'Brush Shape & Transform · Custom (unreadable)');
assert.equal(status().textContent, 'The stored custom tip cannot be read: The PNG is damaged or incomplete. Import a PNG or clear it.');
click(64, 64); assert.match(error(), /cannot be read/); assert.equal(session().history.undoEntries.length, 0);
press('Done'); await settle(); assert.equal(result.settings.custom_tip, data.unreadable);
// While a stored tip loads, Custom says so and does not paint; then it paints.
controller = open(empty(), {...E1, shape: 'custom', custom_tip: data.good}); dom.flush();
assert.equal(heading('Custom Tip').textContent, 'Custom Tip · loading');
click(64, 64); assert.equal(error(), 'The stored custom tip is still loading.'); assert.ok(session().codes.every(v => v === 0));
await until(() => session().tip, 'load'); click(64, 64); assert.ok(session().codes.some(v => v > 0));
// An import or Clear made while the stored tip loads wins over the late result.
controller.cancel(); controller = open(empty(), {...E1, shape: 'custom', custom_tip: data.good}); dom.flush();
press('Clear Custom Tip'); await settle(); await new Promise(r => setTimeout(r, 20)); dom.flush();
assert.equal(session().tip, null); assert.equal(heading('Custom Tip').textContent, 'Custom Tip · none loaded');
""", {"good": good, "unreadable": unreadable})

    def test_custom_tip_group_expansion_is_a_per_user_preference_outside_session_state(self):
        run_editor(r"""
const toggle = open => { const d = tipGroup(); d.open = open; fire(d, 'toggle'); dom.flush(); };
const reopenSame = () => { controller.cancel(); controller = open(); dom.flush(); };
custom(); assert.equal(tipGroup().open, false); assert.deepEqual(writes, []);
const stored = JSON.stringify(ui.editorSettings(settings()));
toggle(true); assert.deepEqual(writes, [['tip', true]]);
assert.equal(session().history.undoEntries.length, 0); assert.equal(JSON.stringify(ui.editorSettings(settings())), stored);
reopenSame(); assert.equal(tipGroup().open, true); toggle(false); reopenSame(); assert.equal(tipGroup().open, false);
press('Done'); await settle();
assert.deepEqual(result.settings, {tool: 'paint', size: 16, influence: 255, hardness: 100, amount: 100, influenceUnit: 'percent'});
assert.deepEqual(writes, [['tip', true], ['tip', false]]); assert.deepEqual(expanded, {tip: false});
""")

    def test_custom_tip_messages_clear_once_their_cause_is_gone_and_never_clear_another_message(self):
        good = tip_png(textured(5, 4))
        zero = tip_png(make_tip(2, 2, [0, 0, 0, 0], [9, 9, 9, 9]))
        unreadable = "data:image/png;base64," + b64(b"\x89PNG\r\n\x1a\n" + bytes(30))
        run_editor(r"""
// Unlike importFile above, the message line is not cleared before the import.
const load = async text => {
  const before = session().tip, shown = error(); tipPicker().files = [fileOf(text)]; fire(tipPicker(), 'change');
  await until(() => session().tip !== before || error() !== shown, 'import');
};
const NONE = 'No custom tip is loaded. Import a PNG under Custom Tip.', painted = () => session().history.undoEntries.length;
const CROP = 'Crop Left + Crop Right must stay below 100%. Crop Right 50% was not applied.';
const crop = () => { type('Crop Left (%)', 60); type('Crop Right (%)', 50); assert.equal(error(), CROP); };
// No tip: the refusal stays while it holds, and a valid import clears it.
custom(); click(64, 64); assert.equal(error(), NONE); press('Heat View'); press('Heat View'); assert.equal(error(), NONE);
await load(data.good); assert.equal(error(), ''); click(64, 64); assert.equal(painted(), 1);
// Empty as read: a reading change that makes the tip usable clears the refusal; one that does not keeps it.
await load(data.zero); click(64, 64); assert.match(error(), /empty as read/); assert.equal(painted(), 1);
press('Trim Empty Border'); assert.match(error(), /empty as read/);
pressIn(tipGroup(), 'Luminance'); assert.equal(error(), ''); click(64, 64); assert.equal(painted(), 2);
// Invert clears it too; leaving Custom clears it, since the brush no longer refuses.
pressIn(tipGroup(), 'Alpha'); click(64, 64); assert.match(error(), /empty as read/);
press('Invert Tip'); assert.equal(error(), ''); press('Invert Tip');
click(64, 64); assert.match(error(), /empty as read/); press('Disk'); assert.equal(error(), ''); custom();
// A refusal for a condition that has since changed is cleared, not left describing the old one.
click(64, 64); press('Clear Custom Tip'); assert.equal(error(), ''); assert.equal(status().textContent, NONE);
// A stroke that starts clears a stale refusal itself, before any render.
await load(data.zero); click(64, 64); assert.match(error(), /empty as read/);
settings().tip_channel = 'luminance'; pointer('pointerdown', 30, 30); assert.equal(error(), '');
pointer('pointerup', 30, 30); dom.flush(); assert.equal(painted(), 3);
// A failed import stays while it is current, reading changes leave it, and a valid import clears it.
await load(Buffer.from('not a png').toString('base64'));
assert.equal(error(), 'Cannot import the custom tip: Not a PNG file.'); press('Invert Tip'); press('Invert Tip');
assert.equal(error(), 'Cannot import the custom tip: Not a PNG file.');
await load(data.good); assert.equal(error(), '');
// An oversized file is refused unread; the next valid import clears that, and so does a stroke that starts.
const huge = {size: 8388609, arrayBuffer: () => assert.fail('oversized read')};
let before = error(); tipPicker().files = [huge]; fire(tipPicker(), 'change'); await until(() => error() !== before, 'huge');
assert.match(error(), /at most 8,388,608 bytes/); await load(data.zero); assert.equal(error(), '');
before = error(); tipPicker().files = [huge]; fire(tipPicker(), 'change'); await until(() => error() !== before, 'huge');
pressIn(tipGroup(), 'Luminance'); assert.match(error(), /at most 8,388,608 bytes/);
click(64, 64); assert.equal(error(), ''); assert.equal(painted(), 4);
// Clear Custom Tip clears a failed import too.
await load(Buffer.from('not a png').toString('base64')); press('Clear Custom Tip'); assert.equal(error(), '');
// Another message is never cleared by Custom Tip: not by an import, a resolved refusal or a stroke.
crop(); await load(data.good); assert.equal(error(), CROP);
press('Clear Custom Tip'); click(64, 64); assert.equal(error(), NONE); crop();
await load(data.good); assert.equal(error(), CROP); click(64, 64); assert.equal(error(), CROP); assert.equal(painted(), 5);
type('Crop Right (%)', 0); assert.equal(error(), '');
// An unreadable stored tip refuses while it is current; importing a valid tip clears that.
await reopen(empty(), {shape: 'custom', custom_tip: data.unreadable});
click(64, 64); assert.match(error(), /cannot be read/); await load(data.good); assert.equal(error(), '');
// A stored tip still loading refuses until it is read.
controller.cancel(); controller = open(empty(), {shape: 'custom', custom_tip: 'data:image/png;base64,' + data.good}); dom.flush();
click(64, 64); assert.equal(error(), 'The stored custom tip is still loading.');
await until(() => session().tip, 'load'); assert.equal(error(), '');
""", {"good": good, "zero": zero, "unreadable": unreadable})

    def test_custom_tip_warning_help_and_prepared_tip_have_separate_blocks(self):
        run_editor(r"""
const css = all().find(e => e.tagName === 'STYLE').textContent, rules = css.split('\n').map(line => line.trim());
const at = text => { const i = rules.indexOf(text); assert.ok(i >= 0, text); return i; };
// Scoped block rules, written before [hidden] so a hidden element still does not show.
const prepared = at('.cl-field-editor .tip-prepared {display:flex;flex-direction:column;align-items:flex-start;gap:4px;}');
const blocks = at('.cl-field-editor .tip-status,.cl-field-editor .tip-help {display:block;}');
assert.ok(Math.max(prepared, blocks) < at('.cl-field-editor [hidden] {display:none;}'));
for (const rule of rules.filter(r => r.includes('tip-'))) assert.match(rule, /^\.cl-field-editor \.tip-/);
custom(); await importTip(data.zero);
// The warning and the help text are separate block elements, in that order.
const parts = tipGroup().children, help = find('tip-help');
assert.equal(status().tagName, 'SMALL'); assert.equal(help.tagName, 'SMALL'); assert.notEqual(status(), help);
assert.equal(parts.indexOf(help), parts.indexOf(status()) + 1);
assert.match(status().textContent, /Invert Tip\.$/); assert.match(help.textContent, /^PNG only/);
// The thumbnail and its caption form one column, the caption under the thumbnail.
const column = find('tip-prepared');
assert.equal(column.parent, tipGroup()); assert.deepEqual(column.children, [find('tip-frame'), caption()]);
assert.equal(column.hidden, false); assert.match(caption().textContent, /^Prepared tip 2×2/);
press('Clear Custom Tip'); assert.equal(column.hidden, true);
""", {"zero": tip_png(make_tip(2, 2, [0, 0, 0, 0], [9, 9, 9, 9]))})

    def test_custom_tip_module_is_host_free_and_reads_no_file_name_path_or_browser_image(self):
        source = (CORE / "custom_tip.js").read_text(encoding="utf-8")
        brush = (CORE / "brush.js").read_text(encoding="utf-8")
        editor = (CORE / "editor_ui.js").read_text(encoding="utf-8")
        code = "\n".join(line.split("//")[0] for line in source.splitlines())  # its comments name what it avoids
        self.assertEqual([line for line in source.splitlines() if line.startswith("import")], [])
        self.assertEqual([line for line in brush.splitlines() if line.startswith("import")], ['import {PARTICLE_SHAPES, PROCEDURAL_TYPES, PROCEDURAL_VERSION, proceduralTip} from "./procedural_tip.js";', 'import {sampleTip} from "./tip_sampling.js";'])
        self.assertIn('import {decodeTipDataUrl, importTipFile, storedTipValid} from "./custom_tip.js";', editor)
        for forbidden in ("getImageData", "createImageBitmap", "Image(", "OffscreenCanvas", "drawImage", "toBlob", "fetch(",
                          "XMLHttpRequest", "upload", "scripts/app", "scripts/api", "document", "window", "localStorage",
                          "createObjectURL", "Math.random", "Math.pow", "**", "Date.", ".name", "webkitRelativePath", "path"):
            self.assertNotIn(forbidden, code, forbidden)
        for forbidden in ("file.name", "files?.[0]?.name", "webkitRelativePath"):
            self.assertNotIn(forbidden, editor, forbidden)
        for forbidden in ("Math.pow", "Math.hypot", "Math.exp", "Math.log", "**"):
            self.assertNotIn(forbidden, brush, forbidden)
        self.assertEqual((brush.count("Math.sin("), brush.count("Math.cos(")), (1, 1))
        run_node("assert.equal(globalThis.document, undefined); assert.equal(globalThis.window, undefined);")


if __name__ == "__main__":
    unittest.main()
