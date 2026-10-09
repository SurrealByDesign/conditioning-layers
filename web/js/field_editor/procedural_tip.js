// E7 version 1. Canonical coverage only; formulas and evaluation order are versioned.
// Callers supply resolved settings. No host access, entropy, or stamp state.
import {hotdogCoverage} from "./hotdog_template.js";
export const PROCEDURAL_TIP_SIZE = 256;
export const PROCEDURAL_VERSION = 1;
export const PROCEDURAL_TYPES = ["scatter", "noise"];
export const PARTICLE_SHAPES = ["circle", "rectangle", "diamond", "trapezoid", "irregular", "hotdog"];
export const isHotdog = b => b.procedural_type === "scatter" && b.procedural_particle_shape === "hotdog";

function mix32(x) {
  x = (x ^ (x >>> 16)) >>> 0;
  x = Math.imul(x, 0x7feb352d) >>> 0;
  x = (x ^ (x >>> 15)) >>> 0;
  x = Math.imul(x, 0x846ca68b) >>> 0;
  return (x ^ (x >>> 16)) >>> 0;
}
export function hashWords(words) {
  let h = 0x9e3779b9;
  for (const w of words) h = mix32(((h ^ w) + 0x9e3779b9) >>> 0);
  return h;
}
const signed = w => w / 2147483648 - 1;

export function turn(d) {
  const a = (d % 360 + 360) % 360, q = Math.floor(a / 90 + 0.5);
  const r = (a - 90 * q) * (Math.PI / 180), r2 = r * r;
  const c = 1 - r2 / 2 * (1 - r2 / 12 * (1 - r2 / 30 * (1 - r2 / 56 * (1 - r2 / 90
    * (1 - r2 / 132 * (1 - r2 / 182 * (1 - r2 / 240)))))));
  const s = r * (1 - r2 / 6 * (1 - r2 / 20 * (1 - r2 / 42 * (1 - r2 / 72 * (1 - r2 / 110
    * (1 - r2 / 156 * (1 - r2 / 210 * (1 - r2 / 272))))))));
  switch (q % 4) {
    case 0: return [c, s];
    case 1: return [-s, c];
    case 2: return [-c, -s];
    default: return [s, -c];
  }
}

function rank(a, b) { return a.key - b.key || a.row - b.row || a.column - b.column; }

export function scatterLayout(b) {
  if (isHotdog(b)) return hotdogLayout(b);
  const g = b.procedural_grid, D = b.procedural_density, seed = b.procedural_seed;
  const S = b.procedural_particle_size, A = b.procedural_particle_aspect;
  const Js = b.procedural_size_jitter, Jp = b.procedural_position_jitter;
  const R0 = b.procedural_particle_rotation, Jr = b.procedural_rotation_jitter;
  const shape = b.procedural_particle_shape, slots = [];
  for (let j = 0; j < g; j++) for (let i = 0; i < g; i++)
    slots.push({column: i, row: j, key: hashWords([0x45375343, seed, i, j, 0])});
  slots.sort(rank);
  const kept = slots.slice(0, Math.floor((g * g * D + 50) / 100));
  return Object.freeze(kept.map(slot => {
    const i = slot.column, j = slot.row;
    const word = d => hashWords([0x45375343, seed, i, j, d]);
    const hx = signed(word(1)), hy = signed(word(2)), hs = signed(word(3)), hr = signed(word(4));
    const x = (2 * i + 1) / g - 1 + Jp * hx / (100 * g);
    const y = (2 * j + 1) / g - 1 + Jp * hy / (100 * g);
    const f = 1 + Js * hs / 100, len = 2 * S * f / (100 * g);
    const a = A >= 1 ? len / 2 : len * A / 2, height = A >= 1 ? len / (2 * A) : len / 2;
    const angle = shape === "circle" && A === 1 ? 0 : R0 + Jr * hr;
    const [cos, sin] = turn(angle);
    let vertices = null;
    if (shape === "irregular") {
      const V = 5 + word(5) % 4;
      vertices = [];
      for (let k = 0; k < V; k++) vertices.push(Object.freeze(turn((k + 0.4 * signed(word(6 + k))) * 360 / V)));
      Object.freeze(vertices);
    }
    return Object.freeze({...slot, x, y, a, b: height, cos, sin, vertices});
  }));
}

// Exact row-major slots. Incomplete rows are centred; jitter reuses E7's
// independent hash channels. Spread scales centres only, never count or size.
function hotdogLayout(b) {
  const count = b.hotdog_count, g = Math.ceil(Math.sqrt(count)), rows = Math.ceil(count / g);
  const spread = b.hotdog_spread / 100, seed = b.procedural_seed;
  return Object.freeze(Array.from({length: count}, (_, index) => {
    const row = Math.floor(index / g), column = index % g, columns = Math.min(g, count - row * g);
    const word = d => hashWords([0x45375343, seed, column, row, d]);
    const jitter = b.procedural_position_jitter / (100 * g);
    const x = count === 1 ? 0 : spread * ((2 * column + 1 - columns) / g + jitter * signed(word(1)));
    const y = count === 1 ? 0 : spread * ((2 * row + 1 - rows) / g + jitter * signed(word(2)));
    const half = b.procedural_particle_size * (1 + b.procedural_size_jitter * signed(word(3)) / 100) / (100 * g);
    const aspect = b.procedural_particle_aspect;
    const a = aspect >= 1 ? half : half * aspect, height = aspect >= 1 ? half / aspect : half;
    const [cos, sin] = turn(b.procedural_particle_rotation + b.procedural_rotation_jitter * signed(word(4)));
    return Object.freeze({row, column, x, y, a, b: height, cos, sin, vertices: null});
  }));
}

function inside(shape, u, v, edges, edgeCount) {
  switch (shape) {
    case "circle": return u * u + v * v <= 1;
    case "rectangle": return Math.abs(u) <= 1 && Math.abs(v) <= 1;
    case "diamond": return Math.abs(u) + Math.abs(v) <= 1;
    case "trapezoid": return Math.abs(v) <= 1 && 4 * Math.abs(u) <= 3 + v;
    default:
      for (let k = 0; k < edgeCount; k += 4) {
        // Stored differences are the same binary64 subtractions as in §20.
        // Keep the cross-product order; expanding it changes edge rounding.
        if (edges[k + 2] * (v - edges[k + 1]) - edges[k + 3] * (u - edges[k]) < 0) return false;
      }
      return true;
  }
}

function scatter(b, codes) {
  const shape = b.procedural_particle_shape;
  // One scratch buffer per generation, reused across particles; layout stays immutable.
  const edges = shape === "irregular" ? new Float64Array(8 * 4) : null;
  for (const p of scatterLayout(b)) {
    let edgeCount = 0;
    if (edges) {
      const vertices = p.vertices;
      for (let k = 0; k < vertices.length; k++) {
        const [x, y] = vertices[k], [nx, ny] = vertices[(k + 1) % vertices.length];
        edges[edgeCount++] = x; edges[edgeCount++] = y;
        edges[edgeCount++] = nx - x; edges[edgeCount++] = ny - y;
      }
    }
    const R = Math.sqrt(p.a * p.a + p.b * p.b);
    const left = Math.max(0, Math.floor((p.x - R + 1) * 128) - 1);
    const right = Math.min(255, Math.floor((p.x + R + 1) * 128) + 1);
    const top = Math.max(0, Math.floor((p.y - R + 1) * 128) - 1);
    const bottom = Math.min(255, Math.floor((p.y + R + 1) * 128) + 1);
    for (let py = top; py <= bottom; py++) {
      const dy = (2 * py + 1) / 256 - 1 - p.y, row = 256 * py;
      for (let px = left; px <= right; px++) {
        const index = px + row;
        // Scatter is binary union; an already covered pixel cannot change again.
        if (codes[index] === 255) continue;
        const dx = (2 * px + 1) / 256 - 1 - p.x;
        const u = (p.cos * dx + p.sin * dy) / p.a, v = (-p.sin * dx + p.cos * dy) / p.b;
        if (shape === "hotdog") {
          // Graded union; invert only inside each template rectangle, before union.
          const value = Math.floor(hotdogCoverage(u, v, b.hotdog_invert) + 0.5);
          if (value > codes[index]) codes[index] = value;
        } else if (inside(shape, u, v, edges, edgeCount)) codes[index] = 255;
      }
    }
  }
}

function noise(b, codes) {
  const octaves = [];
  let L = b.procedural_frequency, amp = 1, sum = 0;
  for (let o = 0; o < b.procedural_octaves; o++) {
    const T = new Float64Array(L * L);
    for (let iy = 0; iy < L; iy++) for (let ix = 0; ix < L; ix++)
      T[ix + L * iy] = hashWords([0x45374e5a, b.procedural_seed, o, ix, iy]) / 4294967295;
    octaves.push({L, amp, T});
    sum = sum + amp; amp = amp * b.procedural_persistence / 100; L = 2 * L;
  }
  for (let py = 0; py < 256; py++) for (let px = 0; px < 256; px++) {
    let acc = 0;
    for (const {L, amp, T} of octaves) {
      const xL = (2 * px + 1) * L / 512, ix = Math.floor(xL), fx = xL - ix, sx = fx * fx * (3 - 2 * fx);
      const yL = (2 * py + 1) * L / 512, iy = Math.floor(yL), fy = yL - iy, sy = fy * fy * (3 - 2 * fy);
      const x1 = (ix + 1) % L, y1 = (iy + 1) % L;
      const top = T[ix + L * iy] + sx * (T[x1 + L * iy] - T[ix + L * iy]);
      const bottom = T[ix + L * y1] + sx * (T[x1 + L * y1] - T[ix + L * y1]);
      acc = acc + amp * (top + sy * (bottom - top));
    }
    const n = acc / sum, remap = (100 * n - b.procedural_noise_low) / (b.procedural_noise_high - b.procedural_noise_low);
    const t = remap <= 0 ? 0 : remap >= 1 ? 1 : remap;
    codes[px + 256 * py] = Math.floor(t * 255) + (t * 255 - Math.floor(t * 255) >= 0.5 ? 1 : 0);
  }
}

export function generateProceduralTip(b) {
  if (b.procedural_version !== PROCEDURAL_VERSION || !PROCEDURAL_TYPES.includes(b.procedural_type))
    throw new Error("Unsupported procedural version or type.");
  const codes = new Uint8Array(256 * 256);
  if (b.procedural_type === "scatter") scatter(b, codes); else noise(b, codes);
  let empty = true;
  for (let i = 0; i < codes.length; i++) {
    if (!isHotdog(b) && b.procedural_invert) codes[i] = 255 - codes[i];
    if (codes[i] > 0) empty = false;
  }
  return Object.freeze({codes, width: 256, height: 256, left: 0, top: 0, sourceWidth: 256, sourceHeight: 256, empty});
}

const TIPS = new Map();
export function proceduralTip(b) {
  const common = `${b.procedural_version} ${b.procedural_type} ${b.procedural_seed}`;
  const baseKey = b.procedural_type === "scatter"
    ? `${common} ${b.procedural_particle_shape} ${b.procedural_grid} ${b.procedural_density} ${b.procedural_particle_size} ${b.procedural_particle_aspect} ${b.procedural_size_jitter} ${b.procedural_position_jitter} ${b.procedural_particle_rotation} ${b.procedural_rotation_jitter} ${b.procedural_invert}`
    : `${common} ${b.procedural_frequency} ${b.procedural_octaves} ${b.procedural_persistence} ${b.procedural_noise_low} ${b.procedural_noise_high} ${b.procedural_invert}`;
  const key = isHotdog(b) ? `${baseKey} ${b.hotdog_count} ${b.hotdog_spread} ${b.hotdog_invert}` : baseKey;
  const mask = TIPS.get(key) ?? generateProceduralTip(b);
  TIPS.delete(key); TIPS.set(key, mask);
  if (TIPS.size > 8) TIPS.delete(TIPS.keys().next().value);
  return mask;
}
