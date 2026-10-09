// Exact one-field code arithmetic. No host or import-time work.
import {footprintLocal, localCoverage, prepareFootprint, resolveBrush, snapAnchor} from "./brush.js";
import {prepareProfile, profileTarget} from "./value_profile.js";

export function roundHalf(value) {
  const floor = Math.floor(value);
  return floor + (value - floor >= 0.5 ? 1 : 0);
}

export function percentToCode(percent) {
  return roundHalf(Math.max(0, Math.min(100, percent)) * 255 / 100);
}

export function sameCodes(a, b) {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

export function fieldOperation(codes, operation, influence = 255) {
  if (operation === "clear") return new Uint8Array(codes.length);
  if (operation === "fill") return new Uint8Array(codes.length).fill(influence);
  if (operation === "invert") return codes.map(v => 255 - v);
  throw new Error("Unknown field operation");
}

export const FIELD_TRANSFORMS = Object.freeze(["flip_horizontal", "flip_vertical", "rotate_cw", "rotate_ccw"]);

export function transformField(codes, name) {
  if (!FIELD_TRANSFORMS.includes(name)) throw new Error("Unknown field transform");
  const next = new Uint8Array(16384);
  for (let y = 0; y < 128; y++) for (let x = 0; x < 128; x++) {
    const source = name === "flip_horizontal" ? y * 128 + 127 - x
      : name === "flip_vertical" ? (127 - y) * 128 + x
      : name === "rotate_cw" ? (127 - x) * 128 + y : x * 128 + 127 - y;
    next[y * 128 + x] = codes[source];
  }
  return next;
}

export function withinSelection(before, after, selection) {
  return selection === null ? after : after.map((v, i) => selection[i] ? v : before[i]);
}

function quantize(value) {
  if (!Number.isFinite(value)) throw new Error("Invalid pointer position");
  return Math.round(Math.max(-4096, Math.min(4096, value)) * 256);
}

function gcd(a, b) {
  a = Math.abs(a); b = Math.abs(b);
  while (b) [a, b] = [b, a % b];
  return a;
}

function checkBrush(brush) {
  for (const [name, low, high] of [["size", 1, 128], ["influence", 0, 255],
    ["hardness", 0, 100], ["amount", 1, 100]]) {
    if (!Number.isInteger(brush[name]) || brush[name] < low || brush[name] > high)
      throw new Error(`Invalid brush ${name}`);
  }
  return resolveBrush(brush);
}

// Stamp distance in 1/256-cell units. Auto keeps E1's 0.25 cell; Custom is a percentage of
// Size rounded to that grid (Size x percent x 256 / 100 is never an exact half).
export function stampSpacing(brush) {
  const {spacing, spacing_percent} = resolveBrush(brush);
  return spacing === "custom" ? roundHalf(brush.size * spacing_percent * 256 / 100) : 64;
}

// g^t for 0 < g < 1 and 0 < t <= 1 from square roots and products only: the binary digits
// of t select the factors g^(1/2), g^(1/4), ... Exactly specified, so engines agree.
function unitPower(g, t) {
  if (t === 1) return g;
  let result = 1;
  for (let root = g; t > 0 && root < 1;) {
    root = Math.sqrt(root); t *= 2;
    if (t >= 1) { result *= root; t -= 1; }
  }
  return result;
}

// Build-up share f that one stamp adds at full coverage: travelling one Size closes Flow % of
// the remaining gap, so f = 1 - (1 - Flow/100)^min(1, spacing/Size). Distance, not time.
export function flowFactor(flow, spacing, size) {
  if (flow === 100) return 1;
  return 1 - unitPower((100 - flow) / 100, Math.min(1, spacing / (256 * size)));
}

// While visit runs, LOCAL holds the visited cell's brush-local position: the one mapping that
// both its coverage and a value profile read.
const LOCAL = [0, 0];

function visitStamp(footprint, width, height, x, y, visit) {
  const [ex, ey] = footprint.extent;
  const top = Math.max(0, Math.floor(y - ey) - 1), bottom = Math.min(height, Math.ceil(y + ey) + 1);
  const left = Math.max(0, Math.floor(x - ex) - 1), right = Math.min(width, Math.ceil(x + ex) + 1);
  for (let row = top; row < bottom; row++) {
    for (let col = left; col < right; col++) {
      footprintLocal(footprint, col + 0.5 - x, row + 0.5 - y, LOCAL);
      const weight = localCoverage(footprint, LOCAL[0], LOCAL[1]);
      if (weight > 0) visit(row * width + col, weight);
    }
  }
}

// Paint's value profile, or null. Erase (0) and Restore (the session-open field) keep their
// targets whatever the profile is.
function paintProfile(brush, settings, footprint) {
  return brush.tool === "erase" || brush.tool === "restore" ? null : prepareProfile(settings, footprint);
}

// One stamp exactly as a stroke beginning at (x, y) would place it: coverage and, for a Paint
// gradient, each covered cell's target. Display preview only.
export function stampPreview(width, height, brush, x, y) {
  const settings = checkBrush(brush), footprint = prepareFootprint(brush);
  const profile = paintProfile(brush, settings, footprint), coverage = new Float64Array(width * height);
  const targets = profile ? new Uint8Array(width * height) : null;
  let anchor = [quantize(x) / 256, quantize(y) / 256];
  if (footprint.hard) anchor = snapAnchor(footprint, ...anchor);
  visitStamp(footprint, width, height, ...anchor, (i, weight) => {
    coverage[i] = weight;
    if (profile) targets[i] = profileTarget(profile, LOCAL[0], LOCAL[1]);
  });
  return {coverage, targets, anchor, footprint};
}

export class Stroke {
  constructor(codes, width, height, brush, x, y, restore = null, selection = null) {
    if (!(codes instanceof Uint8Array) || codes.length !== width * height)
      throw new Error("Invalid field grid");
    const settings = checkBrush(brush);
    if (selection !== null && (!(selection instanceof Uint8Array) || selection.length !== width * height
        || selection.some(v => v !== 0 && v !== 1))) throw new Error("Invalid selection");
    this.selection = selection === null ? null : selection.slice();
    // Restore paints toward the field as it was when the editor session opened.
    if (brush.tool === "restore" && !(restore instanceof Uint8Array && restore.length === codes.length))
      throw new Error("Restore needs the session's opening field");
    this.before = codes.slice();
    this.coverage = new Float64Array(codes.length);
    this.width = width; this.height = height;
    this.brush = {...brush};
    this.footprint = prepareFootprint(brush);
    this.spacing = stampSpacing(brush);
    this.buildUp = settings.build_up;
    this.flow = settings.build_up ? flowFactor(settings.flow, this.spacing, brush.size) : 0;
    this.applyMode = settings.apply_mode;
    this.target = brush.tool === "erase" ? 0 : brush.influence;
    this.source = brush.tool === "restore" ? restore.slice() : null;
    // A gradient gives Paint one target per cell: the code its value profile gives at the
    // cell's position in the stamp that covers it most strongly (design record §9).
    this.profile = paintProfile(brush, settings, this.footprint);
    this.targets = this.profile ? new Uint8Array(codes.length) : null;
    if (this.profile) {
      this.centrality = new Float64Array(codes.length);
      this.strongest = this.buildUp ? new Float64Array(codes.length) : this.coverage;
    }
    this.last = [quantize(x), quantize(y)];
    this.run = null;
    this.lastSnap = null;
    this.stamp(this.last[0] / 256, this.last[1] / 256);
  }

  add(x, y) {
    const end = [quantize(x), quantize(y)];
    const dx = end[0] - this.last[0], dy = end[1] - this.last[1];
    const n = gcd(dx, dy);
    if (!n) return;
    const ux = dx / n, uy = dy / n;
    if (!this.run || this.run.ux !== ux || this.run.uy !== uy) {
      const remainder = this.run ? this.run.next - this.run.n * this.run.length : this.spacing;
      this.run = {start: this.last, ux, uy, length: Math.sqrt(ux * ux + uy * uy),
        next: remainder, n: 0};
    }
    const run = this.run;
    run.n += n;
    while (run.next <= run.n * run.length) {
      const along = run.next / run.length;
      this.stamp((run.start[0] + along * ux) / 256,
        (run.start[1] + along * uy) / 256);
      run.next += this.spacing;
    }
    this.last = end;
  }

  stamp(x, y) {
    const footprint = this.footprint, coverage = this.coverage, flow = this.flow;
    if (footprint.hard) {
      [x, y] = snapAnchor(footprint, x, y);
      // Repeating a snapped hard stamp cannot raise a maximum; Build-up counts every stamp.
      if (!this.buildUp) {
        if (this.lastSnap && x === this.lastSnap[0] && y === this.lastSnap[1]) return;
        this.lastSnap = [x, y];
      }
    }
    if (this.profile) { this.profileStamp(x, y); return; }
    visitStamp(footprint, this.width, this.height, x, y, this.buildUp
      ? (i, weight) => { const m = coverage[i]; coverage[i] = Math.min(1, m + (1 - m) * (flow * weight)); }
      : (i, weight) => { if (weight > coverage[i]) coverage[i] = weight; });
  }

  // Coverage accumulates exactly as above. Each cell keeps the target of the stamp with its
  // greatest coverage; ties go to the most central stamp (squared distance from the cell centre
  // to the anchor), then the earlier one. Without Build-up, that coverage is the cell's maximum.
  profileStamp(x, y) {
    const {coverage, flow, buildUp, profile, targets, centrality, strongest, width} = this;
    visitStamp(this.footprint, width, this.height, x, y, (i, weight) => {
      if (buildUp) { const m = coverage[i]; coverage[i] = Math.min(1, m + (1 - m) * (flow * weight)); }
      if (weight < strongest[i]) return;
      const col = i % width, dx = col + 0.5 - x, dy = (i - col) / width + 0.5 - y, distance = dx * dx + dy * dy;
      if (weight > strongest[i] || distance < centrality[i]) {
        strongest[i] = weight; centrality[i] = distance;
        targets[i] = profileTarget(profile, LOCAL[0], LOCAL[1]);
      }
    });
  }

  result() {
    const {amount} = this.brush, source = this.source, targets = this.targets, mode = this.applyMode;
    return this.before.map((base, i) => {
      if (this.selection !== null && this.selection[i] === 0) return base;
      const target = targets ? targets[i] : source ? source[i] : this.target;
      const delta = ((target - base) * amount) * this.coverage[i] / 100;
      const next = base + Math.sign(delta) * roundHalf(Math.abs(delta));
      // Field-value constraints relative to the stroke's starting field, not composition.
      return mode === "raise_only" ? Math.max(base, next) : mode === "lower_only" ? Math.min(base, next) : next;
    });
  }
}

// E9 pressure owns its stamp loop; the ordinary engine above remains byte-identical.
export const PRESSURE_FULL = 65535;
export function pressureCode(pressure) {
  return typeof pressure !== "number" || !Number.isFinite(pressure) ? PRESSURE_FULL
    : roundHalf(Math.max(0, Math.min(1, pressure)) * PRESSURE_FULL);
}
export function scaledControl(base, code) { return Math.max(1, Math.floor((2 * base * code + 65535) / 131070)); }
export function pressurePercent(code) { return Math.floor((200 * code + 65535) / 131070); }
export function pressureMappings(settings) {
  if (settings.pressure_enabled !== true) return null;
  const size = settings.pressure_size === true, amount = settings.pressure_amount === true;
  const flow = settings.pressure_flow === true && settings.build_up === true;
  return size || amount || flow ? Object.freeze({size, amount, flow}) : null;
}
function checkPressure(code) {
  if (!Number.isInteger(code) || code < 0 || code > PRESSURE_FULL) throw new Error("Invalid pressure.");
}

export class PressureStroke {
  constructor(codes, width, height, brush, x, y, restore = null, selection = null, pressure = PRESSURE_FULL) {
    if (!(codes instanceof Uint8Array) || codes.length !== width * height) throw new Error("Invalid field grid");
    this.settings = checkBrush(brush);
    this.mappings = pressureMappings(this.settings);
    if (!this.mappings) throw new Error("Pen pressure is not active for this brush.");
    checkPressure(pressure);
    if (selection !== null && (!(selection instanceof Uint8Array) || selection.length !== width * height
        || selection.some(v => v !== 0 && v !== 1))) throw new Error("Invalid selection");
    if (brush.tool === "restore" && !(restore instanceof Uint8Array && restore.length === codes.length))
      throw new Error("Restore needs the session's opening field");
    this.selection = selection === null ? null : selection.slice();
    this.before = codes.slice(); this.coverage = new Float64Array(codes.length);
    this.amounts = this.mappings.amount ? new Uint8Array(codes.length) : null;
    this.width = width; this.height = height; this.brush = {...brush};
    this.buildUp = this.settings.build_up; this.applyMode = this.settings.apply_mode;
    this.target = brush.tool === "erase" ? 0 : brush.influence;
    this.source = brush.tool === "restore" ? restore.slice() : null;
    this.prepared = new Map();
    const entry = this.prepare(brush.size);
    this.targets = entry.profile ? new Uint8Array(codes.length) : null;
    if (this.targets) {
      this.centrality = new Float64Array(codes.length);
      this.strongest = this.buildUp ? new Float64Array(codes.length) : this.coverage;
      this.strongestAmounts = this.amounts === null ? null : this.buildUp ? new Uint8Array(codes.length) : this.amounts;
    }
    this.pressure = pressure; this.contact = false;
    this.last = [quantize(x), quantize(y)]; this.run = null; this.lastStamp = null;
    if (pressure > 0) this.begin();
  }

  prepare(size) {
    if (!this.prepared.has(size)) {
      const brush = {...this.brush, size}, footprint = prepareFootprint(brush);
      this.prepared.set(size, {footprint, spacing: stampSpacing(brush), profile: paintProfile(brush, this.settings, footprint)});
    }
    return this.prepared.get(size);
  }
  begin() {
    this.contact = true;
    this.gap = this.slot(this.last[0] / 256, this.last[1] / 256, this.pressure);
  }
  add(x, y, pressure) {
    checkPressure(pressure);
    const end = [quantize(x), quantize(y)];
    if (!this.contact) {
      this.pressure = pressure;
      if (pressure > 0) { this.last = end; this.begin(); }
      return;
    }
    const dx = end[0] - this.last[0], dy = end[1] - this.last[1], n = gcd(dx, dy);
    if (!n) {
      if (pressure !== this.pressure) { this.pressure = pressure; if (this.run) this.run.piece = null; }
      return;
    }
    const ux = dx / n, uy = dy / n;
    if (!this.run || this.run.ux !== ux || this.run.uy !== uy) {
      const remainder = this.run ? this.run.next - this.run.n * this.run.length : this.gap;
      this.run = {start: this.last, ux, uy, length: Math.sqrt(ux * ux + uy * uy), next: remainder, n: 0, piece: null};
    }
    const run = this.run, piece = run.piece;
    if (!piece || (pressure - piece.p0) * piece.den !== piece.num * (run.n + n - piece.n0)) {
      const divisor = gcd(pressure - this.pressure, n);
      run.piece = {n0: run.n, p0: this.pressure, num: (pressure - this.pressure) / divisor, den: n / divisor};
    }
    const p = run.piece;
    run.n += n;
    while (run.next <= run.n * run.length) {
      const along = run.next / run.length;
      const code = Math.max(0, Math.min(65535, roundHalf(p.p0 + p.num * (along - p.n0) / p.den)));
      run.next += this.slot((run.start[0] + along * ux) / 256, (run.start[1] + along * uy) / 256, code);
    }
    this.last = end; this.pressure = pressure;
  }

  slot(x, y, code) {
    const size = this.mappings.size ? scaledControl(this.brush.size, code) : this.brush.size;
    const {footprint, spacing, profile} = this.prepare(size);
    if (code === 0) return spacing;
    const a = this.mappings.amount ? scaledControl(this.brush.amount, code) : this.brush.amount;
    const f = this.buildUp ? flowFactor(this.mappings.flow ? scaledControl(this.settings.flow, code) : this.settings.flow, spacing, size) : 0;
    if (footprint.hard) {
      [x, y] = snapAnchor(footprint, x, y);
      if (!this.buildUp) {
        if (this.lastStamp && x === this.lastStamp[0] && y === this.lastStamp[1]
            && size === this.lastStamp[2] && a === this.lastStamp[3]) return spacing;
        this.lastStamp = [x, y, size, a];
      }
    }
    const {coverage, amounts, buildUp, targets, strongest, strongestAmounts, centrality, width, height} = this;
    const [ex, ey] = footprint.extent;
    const top = Math.max(0, Math.floor(y - ey) - 1), bottom = Math.min(height, Math.ceil(y + ey) + 1);
    const left = Math.max(0, Math.floor(x - ex) - 1), right = Math.min(width, Math.ceil(x + ex) + 1);
    for (let row = top; row < bottom; row++) for (let col = left; col < right; col++) {
      footprintLocal(footprint, col + 0.5 - x, row + 0.5 - y, LOCAL);
      const w = localCoverage(footprint, LOCAL[0], LOCAL[1]);
      if (w <= 0) continue;
      const i = row * width + col, m = coverage[i], k = amounts ? amounts[i] : a;
      if (buildUp) {
        if (a === k) coverage[i] = Math.min(1, m + (1 - m) * (f * w));
        else if (a > k) {
          const c = m * k / a;
          coverage[i] = Math.min(1, c + (1 - c) * (f * w)); amounts[i] = a;
        } else {
          const r = a / k;
          if (m < r) coverage[i] = Math.min(r, m + (r - m) * (f * w));
        }
      }
      if (targets) {
        const s = strongest[i], key = strongestAmounts ? strongestAmounts[i] : a;
        const l = a * w, r = key * s;
        const cmp = key === a ? (w > s ? 1 : w < s ? -1 : 0) : (l > r ? 1 : l < r ? -1 : 0);
        if (cmp < 0) continue;
        const dx = col + 0.5 - x, dy = (i - col) / width + 0.5 - y, d = dx * dx + dy * dy;
        if (cmp > 0 || d < centrality[i]) {
          if (strongestAmounts) strongestAmounts[i] = a;
          strongest[i] = w; centrality[i] = d; targets[i] = profileTarget(profile, LOCAL[0], LOCAL[1]);
        }
      } else if (!buildUp && (a === k ? w > m : a * w > k * m)) {
        if (amounts) amounts[i] = a;
        coverage[i] = w;
      }
    }
    return spacing;
  }

  result() {
    const {amounts, source, targets, applyMode: mode} = this;
    return this.before.map((base, i) => {
      if (this.selection !== null && this.selection[i] === 0) return base;
      const target = targets ? targets[i] : source ? source[i] : this.target;
      const amount = amounts ? amounts[i] : this.brush.amount;
      const delta = ((target - base) * amount) * this.coverage[i] / 100;
      const next = base + Math.sign(delta) * roundHalf(Math.abs(delta));
      return mode === "raise_only" ? Math.max(base, next) : mode === "lower_only" ? Math.min(base, next) : next;
    });
  }
}
